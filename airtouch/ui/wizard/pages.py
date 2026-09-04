"""Las siete paginas del asistente (apartado 9.3).

La regla rectora del apartado 9.1 gobierna el archivo entero: **ninguna pagina
termina solo con texto**. Todas acaban con el usuario habiendo hecho algo con su
cuerpo y con la interfaz contestando: el movil emitiendo video de verdad, los
cuatro medidores en verde, tres pinches contados, el umbral deslizandose a su
sitio, cuatro esquinas y tres dianas, y el recibo con tus numeros.

De ahi salen las dos senales que toda pagina emite y que son el motor del
asistente:

* ``progreso`` — cuanto lleva cumplido **dentro** de la pagina, de 0 a 1. El
  hilo del apartado 9.2.1 lo reparte en su tramo, y por eso la barra se mueve
  porque mueves la mano y no porque pulsas Continuar.
* ``estado_cambiado`` — la pagina ya es satisfacible. El armazon materializa el
  boton primario en ese instante, y ni un momento antes: el boton nunca miente.

Ninguna pagina crea un ``QTimer``: todas heredan ``Beating`` y avanzan con el
``dt`` del latido, que es tambien de donde salen sus relojes (los 20 s de la
segunda via de la camara, los 1,2 s en verde del encuadre, los 6 s del
histograma). Y ninguna escribe texto en un ``QLabel``: lo pinta, para poder
escalonarlo a la entrada sin un efecto grafico por hijo.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QWidget

from ...config import Config
from ...core.controller import Controller
from ...gestures.engine import EngineOutput
from .. import charts, glass, motion, theme, tipo
from ..kit.base import Sheet
from ..kit.controls import Button, Slider, Toggle
from ..kit.display import LeaderLine
from ..tokens import GAP_SAME, R_LG, R_MD, R_SM, R_XL, SPACE
from . import piezas
from .pantalla import PantallaPunteria

__all__ = [
    "Pagina", "IntroPage", "CameraPage", "FramingPage", "GesturePage",
    "PinchPage", "AimPage", "FinishPage",
]

#: Escalonado de la entrada de una pagina. El apartado 9.3 lo fija en 90 ms
#: para la portada; el resto usa el mismo paso, que es el que hace que el
#: bloque se lea de arriba abajo en vez de aparecer de golpe.
PASO_MS = 90.0
BLOQUE_MS = 380.0
SUBIDA = 14.0


class Pagina(piezas.ThemeAware, piezas.Beating, QWidget):
    """Base de las siete: cabecera pintada, escalonado y protocolo comun."""

    progreso = Signal(float)
    estado_cambiado = Signal()
    pedir_avance = Signal()
    pedir_destello = Signal()
    pedir_barrido = Signal()
    #: k de 0 a 1 del anillo que se cierra sobre el boton (solo P2)
    anillo = Signal(float)

    BEAT_HZ = motion.HZ_FULL

    #: rotulo del boton primario cuando la pagina ya es satisfacible
    BOTON = "Continuar"
    #: sin cromo de navegacion: solo la portada
    SIN_CROMO = False
    #: la pagina mide, asi que el motor tiene que estar en marcha
    NECESITA_MOTOR = False
    #: la pagina pinta la camara
    NECESITA_FRAMES = False
    #: cuanto se espera que dure, en segundos. Alimenta la estimacion viva (9.2.4)
    SEGUNDOS = 20.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.reloj = 0.0
        self._entrada = 0.0
        self._kicker = ""
        self._titulo = ""
        self._cuerpo = tipo.Parrafo("", "body")
        self._cuerpo_texto = ""
        self._alto_cabecera = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    # -- cabecera -----------------------------------------------------------
    def set_cabecera(self, kicker: str, titulo: str, cuerpo: str = "") -> None:
        self._kicker = kicker
        self._titulo = titulo
        if cuerpo != self._cuerpo_texto:
            self._cuerpo_texto = cuerpo
            self._cuerpo.set_text(cuerpo)
        self.update()

    def textos(self) -> list[str]:
        """Todo el texto que la pagina ensena. Lo usan las pruebas."""
        return [t for t in (self._kicker, self._titulo, self._cuerpo_texto) if t]

    # -- protocolo ----------------------------------------------------------
    def on_enter(self) -> None:
        self.reloj = 0.0
        self._entrada = 0.0
        self.animate()

    def on_leave(self) -> None:
        pass

    def on_output(self, out: EngineOutput) -> None:
        pass

    def on_frame(self, payload) -> None:
        pass

    def on_stats(self, s: dict) -> None:
        pass

    def can_advance(self) -> bool:
        return True

    def next_label(self) -> str:
        return self.BOTON

    def colocar(self) -> None:
        """Coloca los hijos. Se llama al redimensionar y al cambiar de tema."""

    def pintar(self, p: QPainter, caja: QRectF) -> None:
        """Lo que la pagina pinta bajo su cabecera."""

    def avanzar(self, dt: float) -> bool:
        """Paso propio de la pagina. Devuelve True si sigue habiendo movimiento."""
        return False

    # -- escalonado ---------------------------------------------------------
    def bloque(self, indice: int) -> tuple[float, float]:
        """(opacidad, desplazamiento) del bloque ``indice`` al entrar."""
        if motion.reduce_motion():
            return 1.0, 0.0
        t = (self._entrada * 1000.0 - indice * PASO_MS) / BLOQUE_MS
        k = motion.ease(t, motion.EASE_GLASS)
        return k, (1.0 - k) * SUBIDA

    # -- latido -------------------------------------------------------------
    def tick(self, dt: float) -> bool:
        self.reloj += dt
        vivo = False
        if self._entrada * 1000.0 < 8 * PASO_MS + BLOQUE_MS:
            self._entrada += dt
            vivo = True
        if self.avanzar(dt):
            vivo = True
        self.update()
        return True if vivo else True

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.colocar()

    def on_theme(self) -> None:
        self.colocar()
        self.update()

    # -- pintado ------------------------------------------------------------
    def _pintar_cabecera(self, p: QPainter, ancho: float) -> float:
        y = 0.0
        if self._kicker:
            a, dy = self.bloque(0)
            p.setOpacity(a)
            piezas.texto(p, QRectF(0, y + dy, ancho, 16), "overline",
                         self._kicker, theme.C.tokens.color.accent)
            y += 22.0
        if self._titulo:
            a, dy = self.bloque(1)
            p.setOpacity(a)
            alto = tipo.metrics("title").height()
            piezas.texto(p, QRectF(0, y + dy, ancho, alto), "title",
                         self._titulo, theme.C.tokens.text.primary)
            y += alto + 6.0
        if self._cuerpo_texto:
            a, dy = self.bloque(2)
            p.setOpacity(a)
            self._cuerpo.set_width(min(ancho, 620.0))
            self._cuerpo.draw(p, 0.0, y + dy, theme.C.tokens.text.secondary)
            y += self._cuerpo.height() + 4.0
        p.setOpacity(1.0)
        self._alto_cabecera = y
        return y

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        y = self._pintar_cabecera(p, float(self.width()))
        self.pintar(p, QRectF(0.0, y + SPACE[3],
                              float(self.width()),
                              max(0.0, self.height() - y - SPACE[3])))
        p.end()


# --------------------------------------------------------------------------- #
# P0 - BIENVENIDA
# --------------------------------------------------------------------------- #

class IntroPage(Pagina):
    """La portada, a sangre y sin cromo de navegacion.

    La lente responde al raton antes de que el usuario pulse nada: paralaje de
    0.06x y el reflejo especular siguiendo al cursor. Es la primera promesa del
    programa, y se paga con un ``mouseMoveEvent``, no con una animacion en
    bucle.
    """

    SIN_CROMO = True
    SEGUNDOS = 8.0

    empezar = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.lente = piezas.Lente(self)
        self.boton = Button("Empezar", "primary", self)
        self.boton.clicked.connect(self.empezar.emit)
        self._halo = 0.0
        self._movido = False
        self.set_cabecera(
            "Bienvenido", "Tus manos son el ratón",
            "Apunta con el índice. Junta los dedos para hacer clic.")

    def on_enter(self) -> None:
        super().on_enter()
        self.lente.entrar()
        self.progreso.emit(0.0)

    def colocar(self) -> None:
        w, h = self.width(), self.height()
        self.lente.move(int((w - self.lente.width()) / 2),
                        int(h * 0.06))
        b = self.boton.sizeHint()
        self.boton.setGeometry(int((w - b.width()) / 2),
                               int(h - b.height() - 24), b.width(), b.height())

    def mouseMoveEvent(self, event) -> None:
        self.lente.apuntar(self.lente.mapFrom(self, event.position().toPoint()))
        if not self._movido:
            self._movido = True
            # el hilo avanza porque mueves algo, no porque pulses (9.2.1)
            self.progreso.emit(1.0)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.lente.apuntar(None)

    def avanzar(self, dt: float) -> bool:
        if motion.reduce_motion():
            return False
        self._halo = (self._halo + dt * 1000.0 / motion.BREATH) % 1.0
        return True

    def pintar(self, p: QPainter, caja: QRectF) -> None:
        """El halo que respira bajo el boton (9.3, P0).

        Es una luz, no un anillo: un aro fino a esa distancia del boton se lee
        como un elemento suelto de la interfaz y no como el resplandor de lo que
        hay que pulsar.
        """
        t = theme.C.tokens
        g = QRectF(self.boton.geometry())
        centro = g.center()
        b = 0.5 - 0.5 * math.cos(self._halo * 2.0 * math.pi)
        radio = g.width() * (0.66 + 0.05 * b)
        color = QColor(t.color.accent_glow.hex)
        color.setAlphaF(t.color.accent_glow.alpha * (0.32 + 0.26 * b))
        apagado = QColor(color)
        apagado.setAlpha(0)
        grad = QRadialGradient(centro, radio)
        grad.setColorAt(0.0, color)
        grad.setColorAt(0.38, color)
        grad.setColorAt(1.0, apagado)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(centro, radio, radio * 0.82)

    def _pintar_cabecera(self, p: QPainter, ancho: float) -> float:
        """La portada centra su texto bajo la lente, con ``display`` de 46."""
        t = theme.C.tokens
        y = self.lente.y() + self.lente.height() - 24.0
        centro = (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        a, dy = self.bloque(0)
        p.setOpacity(a)
        piezas.texto(p, QRectF(0, y + dy, ancho, 18), "overline", self._kicker,
                     t.color.accent, centro)
        y += 26.0
        a, dy = self.bloque(1)
        p.setOpacity(a)
        alto = tipo.metrics("display").height()
        piezas.texto(p, QRectF(0, y + dy, ancho, alto), "display", self._titulo,
                     t.text.primary, centro)
        y += alto + 10.0
        a, dy = self.bloque(2)
        p.setOpacity(a)
        piezas.texto(p, QRectF(0, y + dy, ancho, 24), "body", self._cuerpo_texto,
                     t.text.secondary, centro)
        p.setOpacity(1.0)
        self._alto_cabecera = y
        return y + 30.0


# --------------------------------------------------------------------------- #
# P1 - TU CAMARA
# --------------------------------------------------------------------------- #

class TarjetaFuente(Sheet):
    """Una de las dos tarjetas grandes de la pagina de camara.

    Ilustracion a sangre y titulo en ``mosaico`` a la derecha, que es el
    lenguaje del mosaico del panel: la primera vez que se ve esa maqueta es
    aqui, y por eso el panel luego resulta familiar.
    """

    elegida = Signal(str)

    def __init__(self, clave: str, titulo: str, detalle: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent, elevation="E2", radius=R_LG, padding=24,
                         interactive=True)
        self.clave = clave
        self.titulo = titulo
        self._detalle = tipo.Parrafo(detalle, "caption")
        self._detalle_texto = detalle
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def textos(self) -> list[str]:
        return [self.titulo, self._detalle_texto]

    def mouseReleaseEvent(self, event) -> None:
        if (event.button() == Qt.MouseButton.LeftButton
                and self.glass_box().contains(event.position())):
            self.flash()
            self.elegida.emit(self.clave)

    def paint_content(self, painter: QPainter, rect: QRectF) -> None:
        t = theme.C.tokens
        self._dibujar_glifo(painter, rect, t)
        alto = tipo.metrics("mosaico").height()
        piezas.texto_ajustado(
            painter, QRectF(rect.left(), rect.bottom() - alto - 34.0,
                            rect.width(), alto),
            "mosaico", self.titulo, t.text.primary,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._detalle.set_width(rect.width())
        self._detalle.draw(painter, rect.left(), rect.bottom() - 30.0,
                           t.text.tertiary)

    def _dibujar_glifo(self, p: QPainter, rect: QRectF, t) -> None:
        """La ilustracion: un movil o una camara, en linea fina y a sangre."""
        lado = min(rect.width(), rect.height()) * 0.52
        c = QPointF(rect.left() + lado * 0.52, rect.top() + lado * 0.60)
        pluma = QPen(QColor(t.text.tertiary))
        pluma.setWidthF(2.0)
        pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.clave == "airlink":
            cuerpo = QRectF(c.x() - lado * 0.26, c.y() - lado * 0.48,
                            lado * 0.52, lado * 0.96)
            p.drawRoundedRect(cuerpo, R_SM, R_SM)
            p.drawLine(QPointF(c.x() - lado * 0.08, cuerpo.top() + 8.0),
                       QPointF(c.x() + lado * 0.08, cuerpo.top() + 8.0))
            # las ondas del enlace
            pluma.setColor(QColor(t.color.accent))
            p.setPen(pluma)
            for i in range(3):
                r = lado * (0.34 + 0.16 * i)
                p.drawArc(QRectF(cuerpo.right() - r * 0.2, c.y() - r,
                                 2 * r, 2 * r), -50 * 16, 100 * 16)
        else:
            cuerpo = QRectF(c.x() - lado * 0.42, c.y() - lado * 0.30,
                            lado * 0.84, lado * 0.60)
            p.drawRoundedRect(cuerpo, R_SM, R_SM)
            p.drawEllipse(cuerpo.center(), lado * 0.16, lado * 0.16)
            p.drawLine(QPointF(cuerpo.center().x(), cuerpo.bottom()),
                       QPointF(cuerpo.center().x(), cuerpo.bottom() + lado * 0.26))
            p.drawLine(QPointF(cuerpo.center().x() - lado * 0.22,
                               cuerpo.bottom() + lado * 0.26),
                       QPointF(cuerpo.center().x() + lado * 0.22,
                               cuerpo.bottom() + lado * 0.26))


class CameraPage(Pagina):
    """P1: eliges la fuente y el flujo continua **dentro** de la tarjeta.

    Esta pagina arrastra el fallo mas caro que ha tenido el proyecto: la version
    anterior pedia instalar iVCam y al salir dejaba
    ``camera.source_type = "index"``, asi que completar el asistente apagaba
    AirLink en silencio y el usuario se quedaba sin camara. Aqui la salida
    escribe siempre la fuente que el usuario ha elegido de verdad, y la
    predeterminada es AirLink.
    """

    BOTON = "Perfecto, seguir"
    SEGUNDOS = 30.0
    NECESITA_FRAMES = True

    #: fotogramas antes de dar la conexion por buena. Con uno o dos ya es cierto
    #: "phone_connected", pero la primera imagen llega antes de que el movil
    #: estabilice la camara y el usuario veria un fotograma negro celebrado.
    _MIN_FRAMES = 15

    #: a los 20 s aparece en voz baja la segunda via (9.3, P1)
    _SEGUNDA_VIA_S = 20.0

    _EXPANSION_MS = 240

    def __init__(self, cfg: Config, ctl: Controller,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.ctl = ctl
        self.eleccion: str | None = None
        self.indice_webcam: int | None = None
        self._conectado = False
        self._marca = 0.0
        self._celebrado = False
        self._qr: QPixmap | None = None
        self._qr_url = ""
        self._expansion = piezas.Progresion(0.0, self._EXPANSION_MS,
                                            motion.EASE_SOFT)
        self._camaras: list[str] = []

        self.tarjeta_airlink = TarjetaFuente(
            "airlink", "Tu móvil",
            "La cámara del teléfono por WiFi. Es la mejor imagen que tienes en "
            "casa y no pasa por internet.", self)
        self.tarjeta_webcam = TarjetaFuente(
            "webcam", "Webcam",
            "La cámara que ya tiene el equipo. Suele ver menos y peor, pero no "
            "necesita nada más.", self)
        for tarjeta in (self.tarjeta_airlink, self.tarjeta_webcam):
            tarjeta.elegida.connect(self._elegir)

        self.vista = piezas.Vista(
            self, radio=R_MD,
            vacio="Cuando el teléfono empiece a emitir, su imagen aparecerá "
                  "aquí y podremos seguir.")
        self.pasos = piezas.PasosConNombre(
            ["Servidor AirLink en marcha", "Móvil emparejado",
             "Vídeo estable"], self)
        self.chispas = piezas.Chispas(self)
        self.segunda_via = piezas.Enlace(
            "¿No aparece? Usa la webcam del sistema", self)
        self.segunda_via.pulsado.connect(lambda: self._elegir("webcam"))
        self.segunda_via.hide()

        self.set_cabecera("Tu cámara", "¿Con qué te va a ver?",
                          "Elige una. Puedes cambiarla luego en Ajustes.")

    # -- protocolo ----------------------------------------------------------
    def on_enter(self) -> None:
        super().on_enter()
        if not self.ctl.airlink.running:
            self.ctl.airlink.start()
        self._camaras = self._nombres_de_camara()
        self._refrescar_qr()
        self._comprobar()
        self.progreso.emit(0.05)

    def on_leave(self) -> None:
        """Deja escrita la fuente **elegida**. Por defecto, AirLink.

        Es el contrato que rompio la version anterior y que vigila
        ``tests/test_wizard.py``: salir de esta pagina no puede devolver la
        aplicacion a una camara que el usuario no ha pedido.
        """
        if self.eleccion == "webcam" and self.indice_webcam is not None:
            self.cfg.camera.source_type = "index"
            self.cfg.camera.index = int(self.indice_webcam)
            nombre = (self._camaras[self.indice_webcam]
                      if self.indice_webcam < len(self._camaras) else "Webcam")
            self.cfg.camera.friendly_name = nombre
        else:
            self.cfg.camera.source_type = "airlink"
            self.cfg.camera.friendly_name = "AirLink"
        self.cfg.save()

    def on_frame(self, payload) -> None:
        frame, estado = payload
        self.vista.set_frame(frame, estado)

    def can_advance(self) -> bool:
        return self._conectado

    def next_label(self) -> str:
        return self.BOTON if self._conectado else "Esperando al móvil…"

    def textos(self) -> list[str]:
        fuera = super().textos()
        fuera += self.tarjeta_airlink.textos() + self.tarjeta_webcam.textos()
        fuera.append(self.segunda_via.text())
        return fuera

    # -- estado -------------------------------------------------------------
    def _nombres_de_camara(self) -> list[str]:
        try:
            from ...core.capture import list_camera_names

            return list_camera_names()
        except Exception:
            return []

    def _elegir(self, clave: str) -> None:
        if self.eleccion == clave:
            return
        self.eleccion = clave
        if clave == "webcam" and self.indice_webcam is None:
            self.indice_webcam = 0
        self._expansion.jump(0.0)
        self._expansion.set(1.0)
        self.segunda_via.setVisible(False)
        self.progreso.emit(0.4 if clave == "airlink" else 0.5)
        self.animate()
        self.colocar()
        self._comprobar()

    def _refrescar_qr(self) -> None:
        url = self.ctl.airlink.pair_url
        if url == self._qr_url and self._qr is not None:
            return
        self._qr_url = url
        try:
            # negro sobre blanco a proposito: esto no lo lee una persona, lo lee
            # la camara de un telefono, y ahi manda el contraste maximo
            datos = self.ctl.airlink.qr_png(scale=6, dark="#000000",
                                            light="#FFFFFF")
        except Exception:
            self._qr = None
            return
        pix = QPixmap()
        pix.loadFromData(datos)
        self._qr = pix if not pix.isNull() else None

    def _comprobar(self) -> None:
        """Lo que de verdad esta pasando, no lo que nos gustaria que pasara."""
        link = self.ctl.airlink
        if self.eleccion == "webcam":
            ok = self.indice_webcam is not None
        else:
            ok = bool(link.phone_connected
                      and link.frames_received > self._MIN_FRAMES)
        self.pasos.set_hecho(0, bool(link.running))
        self.pasos.set_hecho(1, bool(link.phone_connected))
        self.pasos.set_hecho(2, bool(link.frames_received > self._MIN_FRAMES))
        if ok == self._conectado:
            return
        self._conectado = ok
        if ok:
            self._celebrar()
        self.estado_cambiado.emit()

    def _celebrar(self) -> None:
        if self._celebrado:
            return
        self._celebrado = True
        self._marca = 0.0
        self.progreso.emit(1.0)
        self.pedir_destello.emit()
        caja = self.vista.geometry()
        self.chispas.setGeometry(self.rect())
        self.chispas.estallar(46, QPointF(caja.center()))
        link = self.ctl.airlink
        if self.eleccion != "webcam" and link.device:
            self.set_cabecera(
                "Tu cámara", "Móvil conectado",
                f"{link.device} · {self.cfg.camera.width}×{self.cfg.camera.height}"
                f" · {link.fps:.0f} fps")
        elif self.eleccion != "webcam":
            self.set_cabecera("Tu cámara", "Móvil conectado",
                              "Ya está emitiendo. Sigamos.")
        self.animate()

    def avanzar(self, dt: float) -> bool:
        self._comprobar()
        vivo = self._expansion.step(dt)
        if self._expansion.value != 1.0 or not self._expansion.settled:
            self.colocar()
        if self._conectado and self._marca < 1.0:
            self._marca = min(1.0, self._marca
                              + dt * 1000.0 / motion.dur(int(piezas.MARCA_MS)))
            vivo = True
        if (not self._conectado and self.eleccion != "webcam"
                and self.reloj >= self._SEGUNDA_VIA_S
                and not self.segunda_via.isVisible()):
            self.segunda_via.show()
            self.colocar()
        return vivo

    # -- geometria ----------------------------------------------------------
    def colocar(self) -> None:
        w, h = float(self.width()), float(self.height())
        arriba = 132.0
        alto = max(180.0, h - arriba - 30.0)
        derecha = 300.0
        hueco = float(GAP_SAME)
        izquierda = max(240.0, w - derecha - hueco)

        k = self._expansion.value if self.eleccion else 0.0
        media = (izquierda - hueco) / 2.0
        if self.eleccion == "airlink":
            a_x, a_w = 0.0, media + (izquierda - media) * k
            b_x, b_w = media + hueco + (izquierda + 40.0) * k, media
        elif self.eleccion == "webcam":
            a_x, a_w = -(media + hueco + 40.0) * k, media
            b_x, b_w = media + hueco - (media + hueco) * k, media + (izquierda - media) * k
        else:
            a_x, a_w = 0.0, media
            b_x, b_w = media + hueco, media

        self.tarjeta_airlink.place(QRectF(a_x, arriba, a_w, alto))
        self.tarjeta_webcam.place(QRectF(b_x, arriba, b_w, alto))
        self.tarjeta_airlink.setVisible(a_w > 8.0)
        self.tarjeta_webcam.setVisible(b_w > 8.0)

        self.vista.setGeometry(QRect(int(w - derecha), int(arriba + 44),
                                     int(derecha), int(derecha * 0.62)))
        self.pasos.setGeometry(QRect(int(w - derecha),
                                     int(arriba + 44 + derecha * 0.62 + 22),
                                     int(derecha), self.pasos.height()))
        s = self.segunda_via.sizeHint()
        self.segunda_via.setGeometry(int(w - derecha),
                                     int(arriba + alto - s.height()),
                                     s.width(), s.height())
        self.chispas.setGeometry(self.rect())

    # -- pintado ------------------------------------------------------------
    def pintar(self, p: QPainter, caja: QRectF) -> None:
        t = theme.C.tokens
        # la silueta del dispositivo: vacia y gris hasta que llega el video
        marco = QRectF(self.vista.geometry()).adjusted(-6, -6, 6, 6)
        pluma = QPen(QColor(t.color.ok if self._conectado else t.text.quiet))
        pluma.setWidthF(1.4)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(marco, R_MD + 4, R_MD + 4)
        piezas.texto(p, QRectF(marco.left(), marco.top() - 22.0,
                               marco.width(), 16.0),
                     "overline", "Lo que ve la cámara", t.text.tertiary)

        if self._marca > 0.0:
            interior = QRectF(0, 0, 44.0, 44.0)
            interior.moveCenter(QPointF(marco.right() - 30.0,
                                        marco.bottom() - 30.0))
            pluma = QPen(QColor(t.color.ok))
            pluma.setWidthF(3.0)
            pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
            pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pluma)
            p.drawPath(piezas.camino_parcial(piezas.camino_marca(interior),
                                             self._marca))

        if self.eleccion == "airlink" and self._expansion.value > 0.4:
            self._pintar_qr(p, t)
        elif self.eleccion == "webcam" and self._expansion.value > 0.4:
            self._pintar_camaras(p, t)

    def _placa_qr(self) -> QRectF:
        g = QRectF(self.tarjeta_airlink.geometry())
        caja = g.adjusted(48, 96, -48, -48)
        lado = min(228.0, caja.width(), caja.height() - 54.0)
        return QRectF(caja.left(), caja.top(), lado, lado)

    def _pintar_qr(self, p: QPainter, t) -> None:
        placa = self._placa_qr()
        if placa.width() < 80.0:
            return
        p.setOpacity(min(1.0, (self._expansion.value - 0.4) / 0.4))
        glass.paint_sheet(p, placa, "E3", R_MD, tokens=t,
                          canvas_origin=self.mapTo(self.window(), QPoint(0, 0)))
        if self._qr is not None:
            dentro = placa.adjusted(14, 14, -14, -14)
            camino = QPainterPath()
            camino.addRoundedRect(dentro, R_SM, R_SM)
            p.save()
            p.setClipPath(camino)
            p.fillRect(dentro, QColor("#FFFFFF"))
            p.drawPixmap(dentro, self._qr, QRectF(self._qr.rect()))
            p.restore()
        else:
            piezas.texto(p, placa, "caption",
                         "No se ha podido dibujar el código", t.text.tertiary,
                         Qt.AlignmentFlag.AlignCenter)
        piezas.texto(p, QRectF(placa.left(), placa.bottom() + 14.0,
                               placa.width() + 200.0, 20.0),
                     "mono", self._qr_url or "—", t.text.secondary)
        piezas.texto(p, QRectF(placa.left(), placa.bottom() + 38.0,
                               placa.width() + 200.0, 18.0),
                     "caption",
                     "Apunta la cámara del móvil al código y abre el aviso.",
                     t.text.tertiary)
        p.setOpacity(1.0)

    def _pintar_camaras(self, p: QPainter, t) -> None:
        g = QRectF(self.tarjeta_webcam.geometry())
        caja = g.adjusted(48, 96, -48, -48)
        p.setOpacity(min(1.0, (self._expansion.value - 0.4) / 0.4))
        if not self._camaras:
            piezas.texto(p, QRectF(caja.left(), caja.top(), caja.width(), 20.0),
                         "caption", "No se ha encontrado ninguna webcam.",
                         t.text.tertiary)
            p.setOpacity(1.0)
            return
        for i, nombre in enumerate(self._camaras[:5]):
            fila = QRectF(caja.left(), caja.top() + i * 34.0,
                          caja.width(), 28.0)
            elegida = i == self.indice_webcam
            if elegida:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(glass.qcolor(t.color.accent_soft))
                p.drawRoundedRect(fila.adjusted(-8, 0, 8, 0), R_SM, R_SM)
            piezas.texto(p, fila, "body", nombre,
                         t.text.primary if elegida else t.text.secondary)
        p.setOpacity(1.0)

    def mouseReleaseEvent(self, event) -> None:
        """Elegir una webcam de la lista pintada."""
        if self.eleccion != "webcam" or not self._camaras:
            return
        g = QRectF(self.tarjeta_webcam.geometry())
        caja = g.adjusted(48, 96, -48, -48)
        y = event.position().y() - caja.top()
        i = int(y // 34.0)
        if 0 <= i < len(self._camaras[:5]) and 0 <= y:
            self.indice_webcam = i
            self._comprobar()
            self.update()


# --------------------------------------------------------------------------- #
# P2 - EL ENCUADRE
# --------------------------------------------------------------------------- #

class FramingPage(Pagina):
    """P2: cuatro medidas reales y el unico auto-avance del asistente.

    El auto-avance no es un atajo: es lo que convierte cuatro barras en una
    conversacion. Cuando las cuatro llevan 1,2 s en verde la pagina se da por
    buena sola, con un compas de 900 ms y un anillo cerrandose sobre el boton
    para que no sea un susto. En ninguna otra pagina pasa esto.
    """

    BOTON = "Continuar"
    SEGUNDOS = 18.0
    NECESITA_MOTOR = True
    NECESITA_FRAMES = True

    VERDE_S = 1.2
    COMPAS_S = 0.9

    #: rangos del apartado 8.6, medidos sobre el fotograma reducido
    LUZ = (60.0, 180.0)
    DISTANCIA = (0.14, 0.32)
    CENTRADO = 0.22
    NITIDEZ = 0.62

    def __init__(self, cfg: Config, ctl: Controller,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.ctl = ctl
        self.vista = piezas.Vista(
            self, radio=R_MD,
            vacio="Sin imagen no se puede medir el encuadre. Vuelve atrás si "
                  "el móvil ha dejado de emitir.")
        self.medidores = {
            clave: piezas.MedidorRadial(nombre, self)
            for clave, nombre in (("luz", "Luz"), ("distancia", "Distancia"),
                                  ("centrado", "Centrado"),
                                  ("nitidez", "Nitidez"))
        }
        self._verde = 0.0
        self._compas = -1.0
        self._satisfecha = False
        self._low_res = False
        self.set_cabecera(
            "El encuadre", "Colócate delante",
            "El móvil encima de la pantalla, mirándote. Levanta una mano a la "
            "altura del pecho, a medio metro.")

    def on_enter(self) -> None:
        super().on_enter()
        self.vista.region = (self.cfg.mapping.region_x0, self.cfg.mapping.region_y0,
                             self.cfg.mapping.region_x1, self.cfg.mapping.region_y1)
        self._verde = 0.0
        self._compas = -1.0
        self.progreso.emit(0.0)

    def on_stats(self, s: dict) -> None:
        self._low_res = bool(s.get("low_res"))

    def on_frame(self, payload) -> None:
        frame, estado = payload
        self.vista.set_frame(frame, estado)
        self._medir(frame, estado)

    def can_advance(self) -> bool:
        return self._satisfecha

    def next_label(self) -> str:
        return self.BOTON if self._satisfecha else "Ajusta el encuadre…"

    # -- las cuatro medidas -------------------------------------------------
    def _medir(self, frame, estado) -> None:
        # luminancia media sobre una submuestra: medir los dos millones de
        # pixeles enteros por fotograma seria tirar el presupuesto entero
        media = float(frame[::8, ::8].mean())
        lo, hi = self.LUZ
        self.medidores["luz"].set_valor(min(1.0, media / hi), lo <= media <= hi)

        mano = estado.primary if estado.hands else None
        if mano is None:
            for clave in ("distancia", "centrado", "nitidez"):
                self.medidores[clave].set_valor(0.0, False)
        else:
            palma = mano.lm[[0, 5, 9, 13, 17], :2]
            ancho = float(palma[:, 0].max() - palma[:, 0].min())
            d_lo, d_hi = self.DISTANCIA
            self.medidores["distancia"].set_valor(
                min(1.0, ancho / d_hi), d_lo <= ancho <= d_hi)

            m = self.cfg.mapping
            cx = (m.region_x0 + m.region_x1) / 2.0
            cy = (m.region_y0 + m.region_y1) / 2.0
            dist = math.hypot(float(mano.palm[0]) - cx, float(mano.palm[1]) - cy)
            self.medidores["centrado"].set_valor(
                max(0.0, 1.0 - dist / (self.CENTRADO * 2.0)),
                dist <= self.CENTRADO)

            nitidez = float(mano.score) * (0.72 if self._low_res else 1.0)
            self.medidores["nitidez"].set_valor(nitidez, nitidez >= self.NITIDEZ)

        verdes = sum(1 for m in self.medidores.values() if m.en_rango)
        self.progreso.emit(verdes / 4.0)

    def avanzar(self, dt: float) -> bool:
        if self._satisfecha:
            if self._compas >= 0.0:
                self._compas += dt
                self.anillo.emit(min(1.0, self._compas / self.COMPAS_S))
                if self._compas >= self.COMPAS_S:
                    self._compas = -1.0
                    self.pedir_avance.emit()
                return True
            return False

        todos = all(m.en_rango for m in self.medidores.values())
        self._verde = self._verde + dt if todos else 0.0
        if self._verde >= self.VERDE_S:
            self._satisfecha = True
            self._compas = 0.0
            self.progreso.emit(1.0)
            self.estado_cambiado.emit()
            self.pedir_barrido.emit()
        return True

    # -- geometria y pintado ------------------------------------------------
    def colocar(self) -> None:
        w, h = float(self.width()), float(self.height())
        arriba = 148.0
        # el medidor mide 56 + 18 de etiqueta + 6; el resto es el hueco de la
        # palabra «Listo», que se pinta debajo y no puede caer sobre la etiqueta
        alto_med = 80.0 + 26.0
        alto = max(160.0, h - arriba - alto_med - 24.0)
        self.vista.setGeometry(QRect(0, int(arriba), int(w), int(alto)))
        n = len(self.medidores)
        paso = w / n
        for i, medidor in enumerate(self.medidores.values()):
            medidor.move(int(paso * i + (paso - medidor.width()) / 2.0),
                         int(arriba + alto + 20.0))

    def pintar(self, p: QPainter, caja: QRectF) -> None:
        if not self._satisfecha:
            return
        t = theme.C.tokens
        piezas.texto(p, QRectF(0, self.height() - 22.0, float(self.width()), 18.0),
                     "overline", "Listo", t.color.ok,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)


# --------------------------------------------------------------------------- #
# P3 - EL GESTO
# --------------------------------------------------------------------------- #

class GesturePage(Pagina):
    """P3: el gesto se aprende haciendolo tres veces.

    Y mientras, en silencio, la pagina guarda el ``pinch_ratio`` minimo de cada
    cierre. Eso es lo que la pagina siguiente ensena como si lo hubiera
    adivinado: el sistema trabajo mientras el usuario no miraba.

    Aqui todavia no hay calibracion, asi que los umbrales guardados no sirven
    para contar cierres: si no coinciden con esta mano, el medidor se queda en
    verde permanente y no cuenta ni uno. El rango se aprende sobre la marcha.
    """

    BOTON = "Continuar"
    SEGUNDOS = 16.0
    NECESITA_MOTOR = True

    META = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.minimos: list[float] = []
        self.abierto = 1.0
        self._lo: float | None = None
        self._hi: float | None = None
        self._cerrado = False
        self._min_actual = 1.0

        self.mano = piezas.ManoArt(self)
        self.columna = piezas.ColumnaPinch(self)
        self.fichas = [piezas.Ficha(i + 1, self) for i in range(self.META)]
        self.chispas = piezas.Chispas(self)
        self.set_cabecera(
            "El gesto", "Junta los dedos tres veces",
            "Pulgar e índice, como si cogieras algo pequeño. La columna de la "
            "derecha es tu mano ahora mismo.")

    def on_enter(self) -> None:
        super().on_enter()
        self.progreso.emit(len(self.minimos) / float(self.META))

    def on_output(self, out: EngineOutput) -> None:
        if not out.hands:
            self.columna.set_ratio(None)
            return
        r = float(out.pinch_ratio)
        self._lo = r if self._lo is None else min(self._lo, r)
        self._hi = r if self._hi is None else max(self._hi, r)
        span = (self._hi - self._lo) if self._hi is not None else 0.0
        self.columna.set_ratio(r, self._cerrado)

        if span < 0.14:
            # aun no te ha visto abrir y cerrar: no hay rango que normalizar
            self._cerrado = False
            return
        norm = (r - self._lo) / span
        cerrado = norm < (0.30 if not self._cerrado else 0.48)   # histeresis
        self.columna.set_ratio(r, cerrado)

        if cerrado:
            self._min_actual = min(self._min_actual, r)
        if cerrado and not self._cerrado and len(self.minimos) < self.META:
            self._min_actual = r
        if not cerrado and self._cerrado and len(self.minimos) < self.META:
            self._contar()
        self._cerrado = cerrado

    def _contar(self) -> None:
        self.minimos.append(self._min_actual)
        self.abierto = float(self._hi or 1.0)
        self._min_actual = 1.0
        ficha = self.fichas[len(self.minimos) - 1]
        ficha.marcar()
        self.chispas.setGeometry(self.rect())
        self.chispas.estallar(14, QPointF(ficha.geometry().center()),
                              lado=3.0, rapidez=200.0)
        self.progreso.emit(len(self.minimos) / float(self.META))
        if len(self.minimos) >= self.META:
            self.set_cabecera(
                "El gesto", "Ya es tuyo",
                "Ese es el clic. Todo lo demás del programa sale de aquí.")
            self.pedir_barrido.emit()
            self.estado_cambiado.emit()

    def can_advance(self) -> bool:
        return len(self.minimos) >= self.META

    def next_label(self) -> str:
        return self.BOTON

    def colocar(self) -> None:
        w, h = float(self.width()), float(self.height())
        arriba = 152.0
        alto = max(180.0, h - arriba - 162.0)
        self.mano.setGeometry(QRect(0, int(arriba), int(w * 0.52), int(alto)))
        self.columna.move(int(w * 0.62),
                          int(arriba + (alto - self.columna.height()) / 2.0))
        ancho = self.fichas[0].width()
        total = ancho * self.META
        x0 = (w * 0.52 - total) / 2.0
        for i, ficha in enumerate(self.fichas):
            ficha.move(int(x0 + i * ancho), int(arriba + alto + 12.0))
        self.chispas.setGeometry(self.rect())

    def pintar(self, p: QPainter, caja: QRectF) -> None:
        t = theme.C.tokens
        y = self.fichas[0].y() + self.fichas[0].height() + 2.0
        hechos = len(self.minimos)
        piezas.texto(p, QRectF(0, y, self.width() * 0.52, 18.0), "overline",
                     f"{hechos} de {self.META}",
                     t.color.ok if hechos >= self.META else t.text.tertiary,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        piezas.texto(p, QRectF(self.width() * 0.62, self.columna.y() - 26.0,
                               260.0, 18.0),
                     "overline", "Tu mano ahora", t.text.tertiary)


# --------------------------------------------------------------------------- #
# P4 - TU PINCH
# --------------------------------------------------------------------------- #

class PinchPage(Pagina):
    """P4: el pico del asistente. Se ensena lo que P3 guardo sin decirlo.

    El histograma se construye delante del usuario mientras abre y cierra la
    mano; a los pocos segundos las dos jorobas estan separadas y la aplicacion
    dibuja el umbral en el valle. Despues hay tres segundos de prueba en vivo:
    dos pinches correctos y la pagina queda satisfecha.

    Si la medida sale mal no hay error rojo. El titular cambia a "Vamos otra
    vez", se explica por que y el boton dice «Repetir»: un error del sistema no
    puede leerse como una culpa del usuario.
    """

    BOTON = "Perfecto"
    SEGUNDOS = 26.0
    NECESITA_MOTOR = True

    BINS = 34
    LO, HI = 0.0, 1.10
    CONSTRUIR_S = 6.0
    PRUEBAS = 2
    RECORRIDO_MINIMO = 0.22

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.minimos: list[float] = []
        self.abierto = 1.0
        self.pinch_on = cfg.gestures.pinch_on
        self.pinch_off = cfg.gestures.pinch_off
        self.pruebas = 0
        self._fiable = True
        self._ajustado = False
        self._cerrado = False
        self._cuentas = np.zeros(self.BINS, dtype=np.float32)

        self.eje = piezas.EjePinch(self)
        self.hist = charts.Histogram(self, ground=False, unit="")
        self.enlace = piezas.Enlace("Prefiero ajustarlo yo", self)
        self.enlace.pulsado.connect(self._revelar)
        self.slider_on = Slider(0.10, 0.70, self.pinch_on, decimals=2, parent=self)
        self.slider_off = Slider(0.12, 0.80, self.pinch_off, decimals=2, parent=self)
        self.slider_on.valueChanged.connect(self._mano_on)
        self.slider_off.valueChanged.connect(self._mano_off)
        for s in (self.slider_on, self.slider_off):
            s.hide()
        self._manual = False
        self.set_cabecera("Tu pinch", "Abre y cierra la mano",
                          "Estoy midiendo cómo cierras tú. No hay nada que "
                          "tocar: sigue abriendo y cerrando.")

    # -- entrada de datos ---------------------------------------------------
    def set_medidas(self, minimos: list[float], abierto: float) -> None:
        """Lo que P3 guardo en silencio."""
        self.minimos = list(minimos)
        self.abierto = float(abierto)
        lo = min(self.minimos) if self.minimos else 0.0
        self.eje.set_datos(self.minimos, max(0.0, lo - 0.12),
                           max(0.6, self.abierto + 0.08))

    def on_enter(self) -> None:
        super().on_enter()
        self._recalcular()
        self.progreso.emit(0.15 if self._ajustado else 0.0)

    def on_output(self, out: EngineOutput) -> None:
        if not out.hands:
            self.eje.set_vivo(None, False)
            return
        r = float(out.pinch_ratio)
        i = int((r - self.LO) / (self.HI - self.LO) * self.BINS)
        if 0 <= i < self.BINS:
            self._cuentas[i] += 1.0
        cerrado = r < (self.pinch_on if not self._cerrado else self.pinch_off)
        self.eje.set_vivo(r, cerrado)
        if self._ajustado and cerrado and not self._cerrado:
            self._acertar()
        self._cerrado = cerrado

    def _acertar(self) -> None:
        if self.pruebas >= self.PRUEBAS:
            return
        self.pruebas += 1
        self.progreso.emit(0.6 + 0.4 * self.pruebas / self.PRUEBAS)
        if self.pruebas >= self.PRUEBAS:
            self.set_cabecera(
                "Tu pinch", "Ajustado a tu mano",
                f"Cierras a {self._coma(min(self.minimos))}. He puesto el "
                f"umbral en {self._coma(self.pinch_on)}.")
            self.estado_cambiado.emit()

    # -- calculo ------------------------------------------------------------
    @staticmethod
    def _coma(v: float) -> str:
        return f"{v:.2f}".replace(".", ",")

    def _recalcular(self) -> None:
        """Los umbrales salen de tus tres cierres, no de una tabla."""
        if not self.minimos:
            self._fiable = False
            return
        cerrado = float(min(self.minimos))
        span = self.abierto - cerrado
        self._fiable = span >= self.RECORRIDO_MINIMO
        if not self._fiable:
            self.set_cabecera(
                "Tu pinch", "Vamos otra vez",
                "Tu mano se ha visto de perfil o demasiado lejos, y el "
                "recorrido medido no da para ajustar nada. Ponte de frente y "
                "repítelo.")
            self.estado_cambiado.emit()
            return
        # el umbral de apertura va MUY pegado al de cierre: si se separa, sigues
        # clicando con los dedos ya abiertos
        self.pinch_on = round(cerrado + span * 0.32, 3)
        self.pinch_off = round(cerrado + span * 0.44, 3)
        self.slider_on.setValue(self.pinch_on)
        self.slider_off.setValue(self.pinch_off)
        self._guardar()
        self._ajustado = True
        self.eje.deslizar_umbral(self.pinch_on)
        self.set_cabecera(
            "Tu pinch", "Ajustado a tu mano",
            f"Tu pinch cierra a {self._coma(cerrado)}. He ajustado el umbral a "
            f"{self._coma(self.pinch_on)}. Pruébalo dos veces.")

    def _guardar(self) -> None:
        self.cfg.gestures.pinch_on = self.pinch_on
        self.cfg.gestures.pinch_off = self.pinch_off
        self.cfg.save()

    def _revelar(self) -> None:
        self._manual = not self._manual
        self.slider_on.setVisible(self._manual)
        self.slider_off.setVisible(self._manual)
        self.enlace.setText("Déjalo como estaba" if self._manual
                            else "Prefiero ajustarlo yo")
        self.colocar()

    def _mano_on(self, v: float) -> None:
        self.pinch_on = round(float(v), 3)
        self.pinch_off = max(self.pinch_off, self.pinch_on + 0.03)
        self.slider_off.setValue(self.pinch_off)
        self.eje.deslizar_umbral(self.pinch_on)
        self._guardar()

    def _mano_off(self, v: float) -> None:
        self.pinch_off = max(round(float(v), 3), self.pinch_on + 0.03)
        self._guardar()

    def avanzar(self, dt: float) -> bool:
        if self.reloj < self.CONSTRUIR_S + 0.2:
            self.hist.set_bins(self._cuentas, self.LO, self.HI)
            if self._ajustado:
                self.hist.set_marks([(self.pinch_on, "cierra"),
                                     (self.pinch_off, "abre")])
                self.hist.set_bands([(self.pinch_on, self.pinch_off,
                                      theme.C.tokens.color.accent)])
            return True
        return False

    def can_advance(self) -> bool:
        return self._ajustado and self.pruebas >= self.PRUEBAS

    def next_label(self) -> str:
        if not self._fiable:
            return "Repetir"
        return self.BOTON

    def textos(self) -> list[str]:
        return super().textos() + [self.enlace.text()]

    # -- geometria y pintado ------------------------------------------------
    def colocar(self) -> None:
        w, h = float(self.width()), float(self.height())
        arriba = 152.0
        self.eje.setGeometry(QRect(0, int(arriba), int(w), self.eje.height()))
        y = arriba + self.eje.height() + 18.0
        alto = max(120.0, h - y - 96.0)
        self.hist.setGeometry(QRect(16, int(y + 16), int(w - 32), int(alto - 32)))
        s = self.enlace.sizeHint()
        self.enlace.setGeometry(0, int(h - 30), s.width(), s.height())
        ancho = min(280.0, (w - 40.0) / 2.0)
        self.slider_on.setGeometry(int(w - 2 * ancho - 20), int(h - 40),
                                   int(ancho), 40)
        self.slider_off.setGeometry(int(w - ancho), int(h - 40), int(ancho), 40)

    def pintar(self, p: QPainter, caja: QRectF) -> None:
        t = theme.C.tokens
        # el pozo E1 del histograma: el grafico va con ground=False y el pozo se
        # pinta detras, o el rectangulo a canto recto se come las esquinas
        pozo = QRectF(self.hist.geometry()).adjusted(-16, -16, 16, 16)
        glass.paint_sheet(p, pozo, "E1", R_MD, tokens=t,
                          canvas_origin=self.mapTo(self.window(), QPoint(0, 0)))
        piezas.texto(p, QRectF(pozo.left() + 14.0, pozo.top() + 8.0,
                               pozo.width(), 16.0),
                     "overline", "Cómo cierras tú", t.text.tertiary)
        if self._ajustado:
            piezas.texto(p, QRectF(pozo.left() + 14.0, pozo.bottom() - 24.0,
                                   pozo.width(), 16.0),
                         "caption",
                         f"Probado {self.pruebas} de {self.PRUEBAS}",
                         t.color.ok if self.pruebas >= self.PRUEBAS
                         else t.text.tertiary)


# --------------------------------------------------------------------------- #
# P5 - TUS ESQUINAS Y TU PUNTERIA
# --------------------------------------------------------------------------- #

class AimPage(Pagina):
    """P5: la aplicacion se aparta y la pantalla entera se vuelve la interfaz.

    El dialogo baja su cuerpo al 12 % mientras dura, y vuelve a subir con la
    region mapeada dibujada sobre la vista previa. Se puede saltar en un clic,
    aunque casi nadie lo hara.

    La pantalla completa **no** se abre sin imagen: sin camara conectada no hay
    nada que calibrar, y abrir una ventana negra a pantalla completa que no
    responde es la peor cosa que le puede pasar a un usuario nuevo.
    """

    BOTON = "Continuar"
    SEGUNDOS = 35.0
    NECESITA_MOTOR = True
    NECESITA_FRAMES = True

    #: compas antes de que la pantalla se apodere del monitor
    PREVIO_S = 1.4

    #: la pagina pide al armazon que se apague hasta este 12 % (9.3, P5)
    OPACIDAD_FONDO = 0.12

    apagar = Signal(float)

    def __init__(self, cfg: Config, ctl: Controller,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.ctl = ctl
        self.pantalla: PantallaPunteria | None = None
        self.calibrada = bool(cfg.mapping.homography)
        self.dianas = 0
        self._lanzada = False
        self._cuadro: list[tuple[float, float]] = []

        self.vista = piezas.Vista(
            self, radio=R_MD,
            vacio="Sin imagen no se puede calibrar. Puedes usar el área por "
                  "defecto y ajustarlo más tarde.")
        self.saltar = piezas.Enlace("Usar el área por defecto", self)
        self.saltar.pulsado.connect(self._saltar)
        self.pasos = piezas.PasosConNombre(
            ["Cuatro esquinas", "Tres dianas"], self)
        self.set_cabecera(
            "Tus esquinas", "Ahora la pantalla es tuya",
            "Voy a apagarme un momento. Apunta a las cuatro esquinas y luego a "
            "tres dianas; con eso el puntero cae donde miras.")

    def on_enter(self) -> None:
        super().on_enter()
        self._lanzada = False
        self.progreso.emit(1.0 if self.calibrada else 0.0)

    def on_leave(self) -> None:
        self._cerrar_pantalla(False)

    def on_frame(self, payload) -> None:
        frame, estado = payload
        self.vista.set_frame(frame, estado)

    def on_output(self, out: EngineOutput) -> None:
        if self.pantalla is not None:
            self.pantalla.on_output(out)

    def can_advance(self) -> bool:
        return self.calibrada or self.dianas > 0

    def next_label(self) -> str:
        return self.BOTON

    def textos(self) -> list[str]:
        return super().textos() + [self.saltar.text()]

    # -- la pantalla completa ----------------------------------------------
    def avanzar(self, dt: float) -> bool:
        if (not self._lanzada and self.reloj >= self.PREVIO_S
                and self.isVisible() and self.ctl.source_connected):
            self._lanzar()
        return False

    def _lanzar(self) -> None:
        self._lanzada = True
        self.pantalla = PantallaPunteria(self.cfg)
        self.pantalla.progreso.connect(self.progreso.emit)
        self.pantalla.terminada.connect(self._volver)
        self.apagar.emit(self.OPACIDAD_FONDO)
        self.pantalla.empezar()

    def _volver(self, ok: bool) -> None:
        pantalla = self.pantalla
        if pantalla is not None:
            self.pasos.set_hecho(0, pantalla.paso >= 4)
            self.pasos.set_hecho(1, pantalla.aciertos >= 3)
            self.dianas = pantalla.aciertos
            self._cuadro = list(pantalla.muestras)
            if pantalla.paso >= 4:
                self.calibrada = True
                self.ctl.mapper.refresh_calibration()
                self.vista.quad = self._cuadro
        self._cerrar_pantalla(True)
        self.apagar.emit(1.0)
        if ok:
            self.set_cabecera(
                "Tus esquinas", "Apuntas donde miras",
                f"Cuatro esquinas calibradas y {self.dianas} de 3 dianas. "
                "Puedes repetirlo cuando quieras desde Ajustes.")
            self.pedir_destello.emit()
        self.estado_cambiado.emit()

    def _cerrar_pantalla(self, ya_oculta: bool) -> None:
        if self.pantalla is None:
            return
        pantalla, self.pantalla = self.pantalla, None
        if not ya_oculta:
            pantalla.rest()
            pantalla.hide()
            self.apagar.emit(1.0)
        pantalla.deleteLater()

    def _saltar(self) -> None:
        self._lanzada = True
        self._cerrar_pantalla(False)
        self.calibrada = self.calibrada or True
        self.progreso.emit(1.0)
        self.set_cabecera(
            "Tus esquinas", "Área por defecto",
            "Usaremos el centro del encuadre. Apuntar será algo menos preciso, "
            "y lo puedes calibrar luego desde Ajustes.")
        self.estado_cambiado.emit()

    # -- geometria ----------------------------------------------------------
    def colocar(self) -> None:
        w, h = float(self.width()), float(self.height())
        arriba = 164.0
        alto = max(160.0, h - arriba - 78.0)
        ancho = min(w * 0.62, w - 260.0)
        self.vista.setGeometry(QRect(0, int(arriba), int(ancho), int(alto)))
        self.pasos.setGeometry(QRect(int(ancho + GAP_SAME), int(arriba + 8),
                                     int(w - ancho - GAP_SAME),
                                     self.pasos.height()))
        s = self.saltar.sizeHint()
        self.saltar.setGeometry(0, int(arriba + alto + 16), s.width(), s.height())


# --------------------------------------------------------------------------- #
# P6 - LISTO
# --------------------------------------------------------------------------- #

class FinishPage(Pagina):
    """P6: el recibo de configuracion.

    No se felicita a nadie: se le devuelve una hoja de especificaciones con sus
    numeros, que no existia hace dos minutos. Cada linea entra con 90 ms de
    retardo y cada cifra cuenta desde cero en 500 ms; eso lo hace ``LeaderLine``
    del kit, que existe justamente para esta pagina.
    """

    BOTON = "Entrar en AirTouch"
    SEGUNDOS = 18.0

    def __init__(self, cfg: Config, ctl: Controller,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.ctl = ctl
        self._jugado = False
        self.marca = piezas.MarcaExito(96, self)
        self.chispas = piezas.Chispas(self)
        self.lineas = [LeaderLine("", "", self) for _ in range(5)]
        self.control = Toggle(False, self)
        self.set_cabecera("Listo", "Ya es tuyo",
                          "Esto es lo que hemos ajustado juntos.")

    def on_enter(self) -> None:
        super().on_enter()
        self._rellenar()
        self.progreso.emit(0.5)
        if self._jugado:
            return
        self._jugado = True
        self.marca.play()
        self.chispas.setGeometry(self.rect())
        self.chispas.estallar(46, QPointF(self.marca.geometry().center()),
                              color=theme.C.tokens.color.accent)
        for i, linea in enumerate(self.lineas):
            linea.reveal(i)

    def _rellenar(self) -> None:
        cfg = self.cfg
        m = cfg.mapping
        area = max(0.0, (m.region_x1 - m.region_x0) * (m.region_y1 - m.region_y0))
        esquinas = 4 if m.homography else 0
        camara = cfg.camera.friendly_name or "AirLink"
        link = self.ctl.airlink
        if cfg.camera.source_type == "airlink" and link.device:
            camara = link.device
        datos = [
            ("Cámara", f"{camara} · {cfg.camera.width}×{cfg.camera.height} · "
                       f"{cfg.camera.fps} fps"),
            ("Tu pinch", f"{cfg.gestures.pinch_on:.2f} / "
                         f"{cfg.gestures.pinch_off:.2f}".replace(".", ",")),
            ("Región activa", f"{area * 100:.0f} % del encuadre · "
                              f"{esquinas} esquinas calibradas"),
            ("Retardo medio", f"{self.retardo_ms:.0f} ms"),
            ("Gestos probados", f"{self.gestos_ok} de 3"),
        ]
        for linea, (etiqueta, valor) in zip(self.lineas, datos):
            linea._label = etiqueta          # noqa: SLF001 (contrato del kit)
            linea.set_value(valor)

    #: los rellena el armazon con lo que ha visto pasar de verdad
    retardo_ms: float = 0.0
    gestos_ok: int = 0

    def quiere_control(self) -> bool:
        return self.control.isChecked()

    def commit(self) -> None:
        """Solo al terminar de verdad: volver atras no da la vuelta por hecha."""
        self.cfg.app.first_run = False
        self.cfg.save()

    def can_advance(self) -> bool:
        return True

    def textos(self) -> list[str]:
        return super().textos() + ["Activar control real ahora"]

    def colocar(self) -> None:
        w, h = float(self.width()), float(self.height())
        self.marca.move(int((w - self.marca.width()) / 2.0), 0)
        ancho = min(560.0, w - 80.0)
        x = (w - ancho) / 2.0
        # el recibo arranca donde acaba la cabecera de verdad, no en un numero
        # a ojo: la marca de exito cambia de tamano con el tema y la escala
        # tipografica, y con un 250 fijo la primera linea caia sobre el cuerpo
        y = (self.marca.height() + 16.0 + tipo.metrics("title").height()
             + 4.0 + 22.0 + 30.0)
        for linea in self.lineas:
            linea.setGeometry(int(x), int(y), int(ancho),
                              int(linea.sizeHint().height() + 6))
            y += linea.height() + 8.0
        self.control.move(int(x + ancho - self.control.width()),
                          int(h - self.control.height() - 18))
        self.chispas.setGeometry(self.rect())

    def pintar(self, p: QPainter, caja: QRectF) -> None:
        t = theme.C.tokens
        ancho = min(560.0, self.width() - 80.0)
        x = (self.width() - ancho) / 2.0
        y = self.control.y() + self.control.height() / 2.0
        piezas.texto(p, QRectF(x, y - 20.0, ancho - 80.0, 18.0), "body-fuerte",
                     "Activar control real ahora", t.text.primary)
        piezas.texto(p, QRectF(x, y + 2.0, ancho - 80.0, 16.0), "caption",
                     "Tus gestos moverán el ratón de verdad. Puedes cambiarlo "
                     "cuando quieras.", t.text.tertiary)

    def _pintar_cabecera(self, p: QPainter, ancho: float) -> float:
        """Centrada bajo la marca de exito."""
        t = theme.C.tokens
        centro = (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        y = float(self.marca.height()) - 8.0
        a, dy = self.bloque(0)
        p.setOpacity(a)
        piezas.texto(p, QRectF(0, y + dy, ancho, 18), "overline", self._kicker,
                     t.color.ok, centro)
        y += 24.0
        a, dy = self.bloque(1)
        p.setOpacity(a)
        alto = tipo.metrics("title").height()
        piezas.texto(p, QRectF(0, y + dy, ancho, alto), "title", self._titulo,
                     t.text.primary, centro)
        y += alto + 4.0
        a, dy = self.bloque(2)
        p.setOpacity(a)
        piezas.texto(p, QRectF(0, y + dy, ancho, 22), "body", self._cuerpo_texto,
                     t.text.secondary, centro)
        p.setOpacity(1.0)
        self._alto_cabecera = y
        return y + 26.0
