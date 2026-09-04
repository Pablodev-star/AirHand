"""Las piezas pintadas del asistente: lo que el kit no trae porque solo se usa aqui.

Todo lo de este archivo cumple las tres fuentes de verdad del proyecto: la
tipografia sale de ``tipo.py``, el movimiento del ``Beat`` de ``motion.py`` y el
color de ``tokens.py``. Ni un hex, ni un ``QTimer``, ni un ``setPointSize``.

Por que existen estas piezas y no se reutilizan las de la interfaz vieja
(``handart.py``, ``celebrate.py``, ``live_preview.py``): las tres crean su
propio ``QTimer`` y se conectan a ``theme.signals.changed`` con una lambda que
nadie desconecta, que es exactamente el fallo que documenta ``kit/base.py`` y
que tira la aplicacion al cambiar de tema con una ventana a medio cerrar. El
asistente es la primera pantalla que ve un usuario nuevo: no puede colgarse.

La regla que gobierna el archivo entero: **el texto lo pinta quien lo tiene**.
No hay un solo ``QLabel``. Con el texto pintado, un escalonado de entrada es
una multiplicacion en el ``paintEvent`` en vez de un efecto grafico por hijo, y
el apartado 9 pide escalonados en casi todas las paginas.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core.frame_state import HAND_CONNECTIONS, FrameState
from .. import glass, motion, theme, tipo
from ..kit.base import Beating, ThemeAware
from ..tokens import R_MD, R_SM, Ink

__all__ = [
    "Progresion", "camino_parcial", "camino_marca", "texto", "texto_ajustado",
    "Lente", "MedidorRadial", "ColumnaPinch", "ManoArt", "Ficha",
    "PasosConNombre", "Vista", "Enlace", "Chispas", "MarcaExito", "EjePinch",
]

#: Lo que tarda una marca de verificacion en dibujarse sola (9.2.5).
MARCA_MS = 260.0

#: Muelle corto de los medidores y las fichas: 260 ms de asentamiento (9.3).
OMEGA_CORTO = 19.0


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #

class Progresion:
    """Un recorrido con duracion y curva fijas, avanzado con el ``dt`` del latido.

    El hilo de progreso del apartado 9.2.1 pide "saltos de 300 ms EASE_GLASS":
    ni ``Smooth`` (exponencial, sin duracion) ni ``Spring`` (rebasa) sirven, y
    ``tween`` fabricaria una animacion nueva por cada sub-objetivo cumplido.
    Esto es lo minimo que hace falta: sale del valor donde este y llega al
    nuevo en el tiempo escrito.
    """

    __slots__ = ("_de", "_a", "_t", "_ms", "_curva")

    def __init__(self, value: float = 0.0, ms: int = 300,
                 curva=motion.EASE_GLASS) -> None:
        self._de = self._a = float(value)
        self._t = 1.0
        self._ms = int(ms)
        self._curva = curva

    def set(self, target: float) -> None:
        target = float(target)
        if abs(target - self._a) < 1e-4:
            return
        self._de = self.value
        self._a = target
        self._t = 0.0

    def jump(self, value: float) -> None:
        self._de = self._a = float(value)
        self._t = 1.0

    @property
    def target(self) -> float:
        return self._a

    @property
    def value(self) -> float:
        if self._t >= 1.0:
            return self._a
        return self._de + (self._a - self._de) * motion.ease(self._t, self._curva)

    @property
    def settled(self) -> bool:
        return self._t >= 1.0

    def step(self, dt: float) -> bool:
        """Avanza. Devuelve True mientras quede recorrido."""
        if self._t >= 1.0:
            return False
        self._t = min(1.0, self._t + dt * 1000.0 / max(1, motion.dur(self._ms)))
        return True


def camino_parcial(camino: QPainterPath, k: float, pasos: int = 44) -> QPainterPath:
    """La fraccion ``k`` de un trazo, para que se dibuje solo.

    Es el equivalente honesto del ``setDashOffset`` que pide el apartado 9.2.5:
    con un patron de guiones el trazo aparece a trozos si el camino tiene
    esquinas, y todas las marcas de este asistente las tienen.
    """
    fuera = QPainterPath()
    k = max(0.0, min(1.0, k))
    if k <= 0.0 or camino.elementCount() == 0:
        return fuera
    fuera.moveTo(camino.pointAtPercent(0.0))
    for i in range(1, pasos + 1):
        fuera.lineTo(camino.pointAtPercent(k * i / pasos))
    return fuera


def camino_marca(caja: QRectF) -> QPainterPath:
    """La marca de verificacion inscrita en un cuadrado."""
    c = QPainterPath()
    c.moveTo(caja.left() + caja.width() * 0.20, caja.top() + caja.height() * 0.53)
    c.lineTo(caja.left() + caja.width() * 0.42, caja.top() + caja.height() * 0.74)
    c.lineTo(caja.left() + caja.width() * 0.80, caja.top() + caja.height() * 0.27)
    return c


def texto(p: QPainter, caja: QRectF, rol: str, valor: str, color: str,
          align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft
          | Qt.AlignmentFlag.AlignVCenter) -> None:
    """Una linea de texto con la fuente y la caja del rol."""
    p.setFont(tipo.font(rol))
    p.setPen(QColor(color))
    p.drawText(caja, int(align), tipo.text(rol, valor))


def texto_ajustado(p: QPainter, caja: QRectF, rol: str, valor: str, color: str,
                   align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft
                   | Qt.AlignmentFlag.AlignVCenter) -> None:
    """Como ``texto``, pero encogiendo la fuente hasta que quepa de ancho.

    Hace falta para los titulos en ``mosaico``: 38 px con tracking +2 y una
    palabra larga se sale de la tarjeta, y ``drawText`` no avisa — recorta por
    el lado contrario a la alineacion, asi que "TU MÓVIL" alineado a la derecha
    se quedaba en "U MÓVIL" y parecia un fallo de datos.
    """
    cadena = tipo.text(rol, valor)
    escala = 1.0
    ancho = tipo.metrics(rol).horizontalAdvance(cadena)
    if ancho > caja.width() > 0.0:
        escala = caja.width() / ancho
    fuente = tipo.font(rol, size=tipo.spec(rol).size * escala) if escala < 1.0 \
        else tipo.font(rol)
    p.setFont(fuente)
    p.setPen(QColor(color))
    p.drawText(caja, int(align), cadena)


def _mezcla(a: str, b: str, k: float) -> QColor:
    return QColor(theme.mix(a, b, max(0.0, min(1.0, k))))


# --------------------------------------------------------------------------- #
# P0 - la lente de la marca
# --------------------------------------------------------------------------- #

class Lente(ThemeAware, Beating, QWidget):
    """La lente de vidrio de la portada: oscila, barre y responde al raton.

    El apartado 9.3 la describe como el primer contacto: *antes de pulsar nada,
    la aplicacion ya te ha contestado*. Por eso el paralaje y el reflejo
    especular no son adorno; son la respuesta.

    El raton se lo pasa la pagina con ``apuntar()`` en vez de leerlo del sistema:
    consultar ``QCursor.pos()`` desde el latido despierta la CPU aunque no haya
    nadie moviendo nada, y el lienzo vivo ya paga ese muestreo por todos.
    """

    BEAT_HZ = motion.HZ_GLOW

    LADO = 236.0
    HOLGURA = 62.0              # sitio para la sombra de E4 y el glow
    OSC_S = 9.0
    OSC_GRADOS = 3.0
    BARRIDO_S = 6.0
    ENTRADA_MS = 700
    PARALAJE = 0.06
    PARALAJE_MAX = 18.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lado = int(self.LADO + 2 * self.HOLGURA)
        self.setFixedSize(lado, lado)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._fase = 0.0
        self._desde_barrido = 0.0
        self._entrada = Progresion(1.0, self.ENTRADA_MS)
        self._px = motion.Smooth(0.0, 0.12)
        self._py = motion.Smooth(0.0, 0.12)
        self._sweep = motion.SpecularSweep(self.update)

    # -- API ----------------------------------------------------------------
    def entrar(self) -> None:
        """La lente escala 0.86 -> 1 en 700 ms (apartado 9.3, P0)."""
        self._entrada.jump(0.0)
        self._entrada.set(1.0)
        self._desde_barrido = self.BARRIDO_S - 1.2
        self.animate()

    def apuntar(self, punto: QPointF | None) -> None:
        """Posicion del raton en coordenadas de la lente, o ``None`` si esta fuera."""
        if punto is None:
            self._px.set(0.0)
            self._py.set(0.0)
        else:
            c = QPointF(self.width() / 2.0, self.height() / 2.0)
            self._px.set(max(-1.0, min(1.0, (punto.x() - c.x()) / max(1.0, c.x()))))
            self._py.set(max(-1.0, min(1.0, (punto.y() - c.y()) / max(1.0, c.y()))))
        self.animate()

    # -- latido -------------------------------------------------------------
    def tick(self, dt: float) -> bool:
        self._fase = (self._fase + dt / self.OSC_S) % 1.0
        self._entrada.step(dt)
        self._px.step()
        self._py.step()
        self._desde_barrido += dt
        if self._desde_barrido >= self.BARRIDO_S and not motion.reduce_motion():
            self._desde_barrido = 0.0
            self._sweep.start()
        self.update()
        return True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.animate()

    def hideEvent(self, event) -> None:
        if self._sweep.active:
            self._sweep.tick(10.0)
        super().hideEvent(event)

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        k = self._entrada.value
        escala = 0.86 + 0.14 * k
        centro = QPointF(self.width() / 2.0, self.height() / 2.0)
        dx = max(-self.PARALAJE_MAX, min(self.PARALAJE_MAX,
                                         self._px.value * self.PARALAJE_MAX))
        dy = max(-self.PARALAJE_MAX, min(self.PARALAJE_MAX,
                                         self._py.value * self.PARALAJE_MAX))
        p.setOpacity(max(0.0, min(1.0, k * 1.4)))
        p.translate(centro.x() + dx, centro.y() + dy)
        p.scale(escala, escala)
        p.rotate(self.OSC_GRADOS * math.sin(self._fase * 2.0 * math.pi))
        p.translate(-centro.x(), -centro.y())

        caja = QRectF(self.HOLGURA, self.HOLGURA, self.LADO, self.LADO)

        # el glow de la marca: es lo unico que se sale del vidrio
        halo = QRadialGradient(caja.center(), self.LADO * 0.78)
        glow = QColor(t.color.accent_glow.hex)
        glow.setAlphaF(t.color.accent_glow.alpha * 0.55)
        halo.setColorAt(0.55, glow)
        transparente = QColor(glow)
        transparente.setAlpha(0)
        halo.setColorAt(1.0, transparente)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(caja.adjusted(-self.HOLGURA * 0.7, -self.HOLGURA * 0.7,
                                    self.HOLGURA * 0.7, self.HOLGURA * 0.7))

        camino = glass.paint_sheet(
            p, caja, "E4", caja.width() / 2.0,
            tint=t.color.accent_soft.at(t.color.accent_soft.alpha * 0.55),
            tokens=t, canvas_origin=self.mapTo(self.window(), QPoint(0, 0)))

        p.save()
        p.setClipPath(camino)
        # el reflejo especular sigue al cursor: es la respuesta que el apartado
        # 9.3 pide antes de que el usuario pulse nada
        foco = QPointF(caja.center().x() + self._px.value * caja.width() * 0.30,
                       caja.center().y() + self._py.value * caja.height() * 0.30)
        brillo = QRadialGradient(foco, caja.width() * 0.72)
        alto = QColor(255, 255, 255, 46 if t.dark else 150)
        brillo.setColorAt(0.0, alto)
        bajo = QColor(alto)
        bajo.setAlpha(0)
        brillo.setColorAt(1.0, bajo)
        p.setBrush(brillo)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(caja)

        self._dibujar_marca(p, caja, t)
        self._sweep.paint(p, caja, caja.width() / 2.0)
        p.restore()
        p.end()

    def _dibujar_marca(self, p: QPainter, caja: QRectF, t) -> None:
        """El simbolo: el indice que apunta y el pinch que se cierra."""
        c = caja.center()
        r = caja.width() * 0.26
        pluma = QPen(QColor(t.color.accent))
        pluma.setWidthF(3.0)
        pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # el arco abierto es la yema del pulgar; el segmento, el indice
        p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), -40 * 16, 260 * 16)
        p.drawLine(QPointF(c.x() + r * 0.62, c.y() - r * 0.62),
                   QPointF(c.x() + r * 1.34, c.y() - r * 1.34))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.text.primary))
        p.drawEllipse(c, 5.0, 5.0)


# --------------------------------------------------------------------------- #
# P2 - los cuatro medidores del encuadre
# --------------------------------------------------------------------------- #

class MedidorRadial(ThemeAware, Beating, QWidget):
    """Medidor radial de 56 px con su marca dibujandose por trazo (9.3, P2).

    Cada uno es una medida real del apartado 8.6, no un adorno de "estado":
    LUZ es la luminancia media del fotograma, DISTANCIA el ancho de la palma,
    CENTRADO la distancia al centro de la region y NITIDEZ el ``score`` de la
    mano. Si no hay dato, el medidor se queda vacio en vez de inventarse uno.
    """

    BEAT_HZ = motion.HZ_FULL

    DIAMETRO = 56.0
    GROSOR = 4.0
    ALTO_ETIQUETA = 18.0

    def __init__(self, etiqueta: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.etiqueta = etiqueta
        self._valor = motion.Spring(0.0, omega=OMEGA_CORTO, eps=1.5e-3)
        self._verde = motion.Smooth(0.0, motion.TAU_METER)
        self._marca = 0.0
        self._en_rango = False
        self.setFixedSize(int(self.DIAMETRO + 24),
                          int(self.DIAMETRO + self.ALTO_ETIQUETA + 6))

    def set_valor(self, fraccion: float, en_rango: bool) -> None:
        self._valor.set(max(0.0, min(1.0, fraccion)))
        self._verde.set(1.0 if en_rango else 0.0)
        if en_rango != self._en_rango:
            self._en_rango = en_rango
            if not en_rango:
                self._marca = 0.0
        self.animate()

    @property
    def en_rango(self) -> bool:
        return self._en_rango

    def tick(self, dt: float) -> bool:
        self._valor.step(dt)
        self._verde.step()
        vivo = not self._valor.settled or not self._verde.settled
        if self._en_rango and self._marca < 1.0:
            self._marca = min(1.0, self._marca + dt * 1000.0 / motion.dur(int(MARCA_MS)))
            vivo = True
        self.update()
        if not vivo:
            self.rest()
        return vivo

    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        d = self.GROSOR
        caja = QRectF((self.width() - self.DIAMETRO) / 2.0, 0.0,
                      self.DIAMETRO, self.DIAMETRO).adjusted(d / 2, d / 2,
                                                             -d / 2, -d / 2)
        color = _mezcla(t.color.accent, t.color.ok, self._verde.value)

        pista = QColor(color)
        pista.setAlphaF(0.14)
        p.setPen(QPen(pista, d))
        p.drawEllipse(caja)

        k = max(0.0, min(1.0, self._valor.value))
        if k > 0.001:
            pluma = QPen(color, d)
            pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pluma)
            p.drawArc(caja, 90 * 16, -int(round(k * 360 * 16)))

        if self._marca > 0.0:
            interior = QRectF(0, 0, self.DIAMETRO * 0.46, self.DIAMETRO * 0.46)
            interior.moveCenter(caja.center())
            pluma = QPen(QColor(t.color.ok), 2.4)
            pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
            pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pluma)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(camino_parcial(camino_marca(interior), self._marca))

        texto(p, QRectF(0, self.DIAMETRO + 2, self.width(), self.ALTO_ETIQUETA),
              "overline", self.etiqueta,
              t.color.ok if self._en_rango else t.text.tertiary,
              Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        p.end()


# --------------------------------------------------------------------------- #
# P3 - la columna de pinch
# --------------------------------------------------------------------------- #

class ColumnaPinch(ThemeAware, Beating, QWidget):
    """La columna vertical de pinch de 280 px con las dos reglas de umbral.

    Es el mismo vocabulario que la regla horizontal del panel (8.6): aprenderlo
    aqui es lo que hace que luego el panel se lea sin explicaciones.
    """

    BEAT_HZ = motion.HZ_FULL

    ALTO = 280
    ANCHO_CANAL = 14.0
    TOPE = 1.05                 # ratio por encima del cual la mano ya esta abierta

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ratio = motion.Smooth(self.TOPE, motion.TAU_PINCH)
        self._cerrado = False
        self._hay_mano = False
        self._on = 0.34
        self._off = 0.40
        self.setFixedSize(150, self.ALTO)

    def set_umbrales(self, on: float, off: float) -> None:
        self._on, self._off = float(on), float(off)
        self.update()

    def set_ratio(self, ratio: float | None, cerrado: bool = False) -> None:
        self._hay_mano = ratio is not None
        if ratio is not None:
            self._ratio.set(max(0.0, min(self.TOPE, ratio)))
        self._cerrado = bool(cerrado)
        self.animate()

    def _y(self, ratio: float) -> float:
        caja = self._canal()
        k = max(0.0, min(1.0, ratio / self.TOPE))
        return caja.bottom() - k * caja.height()

    def _canal(self) -> QRectF:
        x = 26.0
        return QRectF(x, 14.0, self.ANCHO_CANAL, self.height() - 28.0)

    def tick(self, dt: float) -> bool:
        self._ratio.step()
        self.update()
        if self._ratio.settled:
            self.rest()
            return False
        return True

    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        canal = self._canal()

        glass.paint_sheet(p, canal, "E1", self.ANCHO_CANAL / 2.0, tokens=t,
                          canvas_origin=self.mapTo(self.window(), QPoint(0, 0)))

        color = QColor(t.color.ok if self._cerrado else t.color.accent)
        if not self._hay_mano:
            color = QColor(t.text.quiet)

        # el relleno cuenta cuanto queda para cerrar: crece hacia abajo
        y = self._y(self._ratio.value)
        relleno = QRectF(canal.left(), y, canal.width(), canal.bottom() - y)
        if relleno.height() > 1.0:
            suave = QColor(color)
            suave.setAlphaF(0.30)
            camino = QPainterPath()
            camino.addRoundedRect(canal, self.ANCHO_CANAL / 2.0,
                                  self.ANCHO_CANAL / 2.0)
            p.save()
            p.setClipPath(camino)
            p.fillRect(relleno, suave)
            p.restore()

        # las dos reglas de umbral, etiquetadas
        for valor, nombre in ((self._off, "abre"), (self._on, "cierra")):
            yr = self._y(valor)
            pluma = QPen(QColor(t.text.tertiary))
            pluma.setWidthF(1.0)
            pluma.setCosmetic(True)
            pluma.setDashPattern([3.0, 3.0])
            p.setPen(pluma)
            p.drawLine(QPointF(canal.left() - 8.0, round(yr) + 0.5),
                       QPointF(self.width() - 6.0, round(yr) + 0.5))
            texto(p, QRectF(canal.right() + 10.0, yr - 14.0, 90.0, 12.0),
                  "axis", f"{nombre} {valor:.2f}".replace(".", ","),
                  t.text.tertiary)

        # la posicion actual: triangulo relleno de 8 px
        if self._hay_mano:
            yv = self._y(self._ratio.value)
            punta = QPainterPath()
            punta.moveTo(canal.left() - 6.0, yv)
            punta.lineTo(canal.left() - 16.0, yv - 6.0)
            punta.lineTo(canal.left() - 16.0, yv + 6.0)
            punta.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPath(punta)
        else:
            texto(p, QRectF(0, canal.center().y() - 8, self.width(), 16),
                  "axis", "sin mano", t.text.quiet,
                  Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        p.end()


# --------------------------------------------------------------------------- #
# P3 - la ilustracion de la mano
# --------------------------------------------------------------------------- #

#: La mano abierta y la mano en pinch, en los 21 puntos de MediaPipe y en
#: coordenadas 0..1 de la caja. Solo cambian el pulgar y la punta del indice:
#: es lo unico que se mueve en un pinch de verdad, y animar mas puntos "para que
#: se note" produce una mano de goma.
_MANO_ABIERTA = (
    (0.50, 0.95),
    (0.36, 0.84), (0.26, 0.74), (0.20, 0.63), (0.17, 0.52),
    (0.38, 0.55), (0.35, 0.42), (0.33, 0.33), (0.32, 0.25),
    (0.50, 0.52), (0.51, 0.44), (0.55, 0.52), (0.51, 0.57),
    (0.61, 0.55), (0.63, 0.47), (0.67, 0.55), (0.62, 0.59),
    (0.71, 0.61), (0.73, 0.54), (0.76, 0.61), (0.71, 0.64),
)
_MANO_CERRADA = (
    (0.50, 0.95),
    (0.36, 0.84), (0.27, 0.73), (0.28, 0.58), (0.34, 0.36),
    (0.38, 0.55), (0.36, 0.43), (0.35, 0.36), (0.34, 0.30),
    (0.50, 0.52), (0.51, 0.44), (0.55, 0.52), (0.51, 0.57),
    (0.61, 0.55), (0.63, 0.47), (0.67, 0.55), (0.62, 0.59),
    (0.71, 0.61), (0.73, 0.54), (0.76, 0.61), (0.71, 0.64),
)


class ManoArt(ThemeAware, Beating, QWidget):
    """La mano que hace el gesto en bucle de 1,6 s.

    Es una ilustracion, no un dato: no dibuja tu mano, dibuja la que hay que
    imitar. Y la dibuja **con el mismo esqueleto de 21 puntos** que se ve luego
    en la vista de la camara y en la tarjeta LA MANO del panel, para que el
    usuario aprenda aqui el vocabulario que va a ver en todas partes. Un dibujo
    "bonito" distinto del esqueleto real seria una segunda cosa que aprender.

    Solo la yema se tine de acento, y solo cuando los dedos se juntan.
    """

    BEAT_HZ = motion.HZ_GLOW
    PERIODO_S = 1.6

    #: proporcion del lado que ocupa la mano. El resto es aire: la ilustracion
    #: comparte pagina con la columna de pinch y no puede pesar mas que ella.
    ESCALA = 0.86

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fase = 0.0
        self.setMinimumSize(220, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.animate()

    def tick(self, dt: float) -> bool:
        if motion.reduce_motion():
            self._fase = 0.5
            self.update()
            return False
        self._fase = (self._fase + dt / self.PERIODO_S) % 1.0
        self.update()
        return True

    def _puntos(self, caja: QRectF, cierre: float) -> list[QPointF]:
        lado = min(caja.width(), caja.height()) * self.ESCALA
        x0 = caja.center().x() - lado / 2.0
        y0 = caja.center().y() - lado / 2.0
        fuera = []
        for (ax, ay), (bx, by) in zip(_MANO_ABIERTA, _MANO_CERRADA):
            fuera.append(QPointF(x0 + (ax + (bx - ax) * cierre) * lado,
                                 y0 + (ay + (by - ay) * cierre) * lado))
        return fuera

    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        caja = QRectF(self.rect()).adjusted(16, 16, -16, -16)
        # 0 abierto, 1 cerrado y vuelta: el gesto entero en un periodo
        cierre = 0.5 - 0.5 * math.cos(self._fase * 2.0 * math.pi)
        pts = self._puntos(caja, cierre)

        hueso = QPen(QColor(t.text.secondary))
        hueso.setWidthF(2.0)
        hueso.setCapStyle(Qt.PenCapStyle.RoundCap)
        hueso.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(hueso)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for a, b in HAND_CONNECTIONS:
            p.drawLine(pts[a], pts[b])

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.text.tertiary))
        for i, punto in enumerate(pts):
            if i in (4, 8):
                continue
            p.drawEllipse(punto, 3.0, 3.0)

        # el contacto: cuando las yemas se tocan, se tine y late
        contacto = max(0.0, (cierre - 0.68) / 0.32)
        yemas = (pts[4], pts[8])
        color = _mezcla(t.text.primary, t.color.accent, contacto)
        p.setBrush(color)
        for punto in yemas:
            p.drawEllipse(punto, 4.0 + 1.5 * contacto, 4.0 + 1.5 * contacto)
        if contacto > 0.0:
            medio = QPointF((yemas[0].x() + yemas[1].x()) / 2.0,
                            (yemas[0].y() + yemas[1].y()) / 2.0)
            halo = QRadialGradient(medio, 26.0 * contacto)
            vivo = QColor(t.color.accent)
            vivo.setAlphaF(0.34 * contacto)
            apagado = QColor(vivo)
            apagado.setAlpha(0)
            halo.setColorAt(0.0, vivo)
            halo.setColorAt(1.0, apagado)
            p.setBrush(halo)
            p.drawEllipse(medio, 26.0 * contacto, 26.0 * contacto)
        p.end()


# --------------------------------------------------------------------------- #
# P3 - las tres fichas
# --------------------------------------------------------------------------- #

class Ficha(ThemeAware, Beating, QWidget):
    """Ficha de vidrio que se rellena con un pop y un anillo que se expande."""

    BEAT_HZ = motion.HZ_FULL

    LADO = 62.0
    ANILLO_MS = 380.0

    def __init__(self, numero: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.numero = numero
        self._lleno = False
        self._pop = motion.Spring(1.0, omega=OMEGA_CORTO, eps=2e-3)
        self._anillo = 1.0
        holgura = 22.0
        self.setFixedSize(int(self.LADO + 2 * holgura), int(self.LADO + 2 * holgura))
        self._holgura = holgura

    @property
    def lleno(self) -> bool:
        return self._lleno

    def marcar(self) -> None:
        if self._lleno:
            return
        self._lleno = True
        self._pop.jump(0.82)
        self._pop.set(1.0)
        self._anillo = 0.0
        self.animate()

    def limpiar(self) -> None:
        self._lleno = False
        self._pop.jump(1.0)
        self._anillo = 1.0
        self.update()

    def tick(self, dt: float) -> bool:
        self._pop.step(dt)
        vivo = not self._pop.settled
        if self._anillo < 1.0:
            self._anillo = min(1.0, self._anillo
                               + dt * 1000.0 / motion.dur(int(self.ANILLO_MS)))
            vivo = True
        self.update()
        if not vivo:
            self.rest()
        return vivo

    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        caja = QRectF(self._holgura, self._holgura, self.LADO, self.LADO)
        centro = caja.center()

        if self._anillo < 1.0:
            k = motion.ease(self._anillo, motion.EASE_GLASS)
            radio = self.LADO * (0.5 + 0.9 * k)
            color = QColor(t.color.accent)
            color.setAlphaF(0.42 * (1.0 - k))
            pluma = QPen(color)
            pluma.setWidthF(2.0)
            p.setPen(pluma)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(centro, radio, radio)

        s = max(0.1, self._pop.value)
        p.save()
        p.translate(centro)
        p.scale(s, s)
        p.translate(-centro)
        tinte: Ink | None = None
        if self._lleno:
            tinte = t.color.accent_soft
        camino = glass.paint_sheet(
            p, caja, "E2" if self._lleno else "E1", R_MD, tint=tinte, tokens=t,
            canvas_origin=self.mapTo(self.window(), QPoint(0, 0)))
        p.setClipPath(camino)
        if self._lleno:
            interior = QRectF(0, 0, self.LADO * 0.46, self.LADO * 0.46)
            interior.moveCenter(centro)
            pluma = QPen(QColor(t.color.accent))
            pluma.setWidthF(2.6)
            pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
            pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pluma)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(camino_parcial(camino_marca(interior),
                                      min(1.0, self._anillo * 1.6)))
        else:
            texto(p, caja, "h2", str(self.numero), t.text.quiet,
                  Qt.AlignmentFlag.AlignCenter)
        p.restore()
        p.end()


# --------------------------------------------------------------------------- #
# 9.2.5 - nunca esperas a solas
# --------------------------------------------------------------------------- #

class PasosConNombre(ThemeAware, Beating, QWidget):
    """Los pasos con nombre de una espera, marcandose uno a uno.

    El apartado 9.2.5 lo justifica bien: *una espera con nombre se percibe mas
    corta que una barra indeterminada*. La condicion de cada paso la pone la
    pagina y sale de un dato real; aqui no hay ninguna espera simulada.
    """

    BEAT_HZ = motion.HZ_FULL

    ALTO_FILA = 30.0
    CAJA = 18.0

    def __init__(self, nombres: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nombres = list(nombres)
        self._hechos = [False] * len(nombres)
        self._marcas = [0.0] * len(nombres)
        self.setFixedHeight(int(self.ALTO_FILA * len(nombres)))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    @property
    def hechos(self) -> int:
        return sum(1 for h in self._hechos if h)

    def set_hecho(self, indice: int, valor: bool = True) -> None:
        if not 0 <= indice < len(self._hechos) or self._hechos[indice] == valor:
            return
        self._hechos[indice] = valor
        if not valor:
            self._marcas[indice] = 0.0
        self.animate()

    def tick(self, dt: float) -> bool:
        vivo = False
        for i, hecho in enumerate(self._hechos):
            if hecho and self._marcas[i] < 1.0:
                self._marcas[i] = min(
                    1.0, self._marcas[i] + dt * 1000.0 / motion.dur(int(MARCA_MS)))
                vivo = True
        self.update()
        if not vivo:
            self.rest()
        return vivo

    def _en_curso(self) -> int:
        for i, hecho in enumerate(self._hechos):
            if not hecho:
                return i
        return -1

    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        curso = self._en_curso()
        for i, nombre in enumerate(self._nombres):
            y = i * self.ALTO_FILA
            caja = QRectF(0.0, y + (self.ALTO_FILA - self.CAJA) / 2.0,
                          self.CAJA, self.CAJA)
            hecho = self._hechos[i]
            color = t.color.ok if hecho else (
                t.text.secondary if i == curso else t.text.quiet)
            aro = QPen(QColor(color))
            aro.setWidthF(1.4)
            p.setPen(aro)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(caja)
            if hecho:
                pluma = QPen(QColor(t.color.ok))
                pluma.setWidthF(2.0)
                pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
                pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pluma)
                p.drawPath(camino_parcial(
                    camino_marca(caja.adjusted(1, 1, -1, -1)), self._marcas[i]))
            texto(p, QRectF(caja.right() + 12.0, y, self.width() - 40.0,
                            self.ALTO_FILA),
                  "caption", nombre,
                  t.text.primary if i == curso and not hecho else color)
        p.end()


# --------------------------------------------------------------------------- #
# la vista de camara
# --------------------------------------------------------------------------- #

class Vista(ThemeAware, QWidget):
    """La camara a sangre dentro del vidrio, con la region activa dibujada.

    Sin senal no pinta un error rojo: pinta el estado vacio maquetado del
    apartado 8.6, "SIN SEÑAL" en ``overline`` y un parrafo con que hacer.
    """

    def __init__(self, parent: QWidget | None = None, *, radio: float = R_MD,
                 vacio: str = "") -> None:
        super().__init__(parent)
        self._pix: QPixmap | None = None
        self._estado: FrameState | None = None
        self._radio = float(radio)
        self._vacio = vacio or ("El móvil aún no está emitiendo. Abre el enlace "
                                "en el teléfono y da permiso a la cámara.")
        self._par = tipo.Parrafo("", "caption")
        self.region: tuple[float, float, float, float] | None = None
        #: Las cuatro esquinas que el usuario apunto de verdad, en fraccion del
        #: encuadre. Es lo que P5 devuelve dibujado sobre la vista previa
        #: cuando el dialogo vuelve a subir: la prueba de que la calibracion
        #: existe y de que es suya.
        self.quad: list[tuple[float, float]] = []
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    @property
    def hay_imagen(self) -> bool:
        return self._pix is not None

    def set_frame(self, frame_bgr: np.ndarray, estado: FrameState | None) -> None:
        alto, ancho = frame_bgr.shape[:2]
        # BGR -> RGB sin cv2: es una vuelta del ultimo eje, y asi la vista no
        # arrastra una dependencia mas de la que ya tiene la captura
        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])
        img = QImage(rgb.data, ancho, alto, rgb.strides[0],
                     QImage.Format.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(img)
        self._estado = estado
        self.update()

    def limpiar(self) -> None:
        self._pix = None
        self._estado = None
        self.update()

    def _encaje(self) -> QRectF:
        """La imagen llena el hueco recortando lo que sobra: va a sangre."""
        r = QRectF(self.rect())
        if self._pix is None or self._pix.isNull():
            return r
        pw, ph = float(self._pix.width()), float(self._pix.height())
        escala = max(r.width() / pw, r.height() / ph)
        w, h = pw * escala, ph * escala
        return QRectF(r.center().x() - w / 2.0, r.center().y() - h / 2.0, w, h)

    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        marco = QRectF(self.rect())
        camino = glass.rounded_path(marco, self._radio)
        p.setClipPath(camino)

        if self._pix is None:
            p.fillRect(marco, QColor(t.glass.sunken.solid))
            caja = marco.adjusted(20, 20, -20, -20)
            texto(p, QRectF(caja.left(), caja.top(), caja.width(), 16),
                  "overline", "Sin señal", t.text.tertiary)
            self._par.set_text(self._vacio)
            self._par.set_width(min(360.0, caja.width()))
            self._par.draw(p, caja.left(), caja.top() + 24.0, t.text.quiet)
            p.end()
            return

        r = self._encaje()
        p.drawPixmap(r, self._pix, QRectF(self._pix.rect()))

        if self.region:
            x0, y0, x1, y1 = self.region
            pluma = QPen(QColor(255, 255, 255, 96))
            pluma.setWidthF(1.4)
            pluma.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pluma)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(
                QRectF(r.x() + x0 * r.width(), r.y() + y0 * r.height(),
                       (x1 - x0) * r.width(), (y1 - y0) * r.height()),
                R_SM, R_SM)

        if len(self.quad) == 4:
            self._pintar_quad(p, r)

        if self._estado is not None and self._estado.hands:
            self._pintar_manos(p, r)
        p.end()

    def _pintar_quad(self, p: QPainter, r: QRectF) -> None:
        """La region mapeada: el cuadrilatero de las cuatro esquinas apuntadas."""
        t = theme.C.tokens
        pts = [QPointF(r.x() + x * r.width(), r.y() + y * r.height())
               for x, y in self.quad]
        camino = QPainterPath()
        camino.moveTo(pts[0])
        for q in pts[1:]:
            camino.lineTo(q)
        camino.closeSubpath()
        relleno = QColor(t.color.accent)
        relleno.setAlphaF(0.14)
        p.fillPath(camino, relleno)
        pluma = QPen(QColor(t.color.accent))
        pluma.setWidthF(2.0)
        pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(camino)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.color.accent))
        for q in pts:
            p.drawEllipse(q, 4.0, 4.0)

    def _pintar_manos(self, p: QPainter, r: QRectF) -> None:
        assert self._estado is not None
        # el esqueleto va sobre una foto, no sobre el tema: blanco siempre
        hueso = QPen(QColor(255, 255, 255, 176))
        hueso.setWidthF(2.0)
        hueso.setCapStyle(Qt.PenCapStyle.RoundCap)
        for mano in self._estado.hands:
            pts = [QPointF(r.x() + float(x) * r.width(),
                           r.y() + float(y) * r.height())
                   for x, y, _z in mano.lm]
            p.setPen(hueso)
            for a, b in HAND_CONNECTIONS:
                p.drawLine(pts[a], pts[b])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 228))
            for punto in pts:
                p.drawEllipse(punto, 2.4, 2.4)


# --------------------------------------------------------------------------- #
# el enlace callado
# --------------------------------------------------------------------------- #

class Enlace(ThemeAware, Beating, QWidget):
    """Texto casi invisible que se puede pulsar (9.2.6).

    ``Button(variant="ghost")`` seria una lamina con rotulo en ``body-fuerte``;
    aqui hace falta ``overline`` en ``text.quiet``, que es lo que pide la
    especificacion para "Salir del asistente" y para las segundas vias.
    """

    pulsado = Signal()

    ALTO = 22

    def __init__(self, etiqueta: str, parent: QWidget | None = None, *,
                 rol: str = "overline") -> None:
        super().__init__(parent)
        self._etiqueta = etiqueta
        self._rol = rol
        self._hover = motion.Smooth(0.0, 0.10)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(self.ALTO)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def setText(self, valor: str) -> None:                  # noqa: N802
        if valor != self._etiqueta:
            self._etiqueta = valor
            self.updateGeometry()
            self.update()

    def text(self) -> str:
        return self._etiqueta

    def sizeHint(self) -> QSize:                            # noqa: N802
        m = tipo.metrics(self._rol)
        return QSize(int(math.ceil(
            m.horizontalAdvance(tipo.text(self._rol, self._etiqueta)) + 4)),
            self.ALTO)

    def minimumSizeHint(self) -> QSize:                     # noqa: N802
        return self.sizeHint()

    def enterEvent(self, event) -> None:
        self._hover.set(1.0)
        self.animate()

    def leaveEvent(self, event) -> None:
        self._hover.set(0.0)
        self.animate()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.pulsado.emit()

    def tick(self, dt: float) -> bool:
        self._hover.step()
        self.update()
        if self._hover.settled:
            self.rest()
            return False
        return True

    def on_theme(self) -> None:
        self.updateGeometry()
        self.update()

    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = _mezcla(t.text.quiet, t.text.primary, self._hover.value)
        p.setFont(tipo.font(self._rol))
        p.setPen(color)
        p.drawText(QRectF(self.rect()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   tipo.text(self._rol, self._etiqueta))
        p.end()


# --------------------------------------------------------------------------- #
# celebracion
# --------------------------------------------------------------------------- #

class _Chispa:
    __slots__ = ("x", "y", "vx", "vy", "vida", "total", "lado", "color")

    def __init__(self, x, y, vx, vy, vida, lado, color) -> None:
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.vida = self.total = vida
        self.lado = lado
        self.color = color


class Chispas(ThemeAware, Beating, QWidget):
    """El estallido de particulas: 46 al conectar, 12 en cada diana (9.3).

    Un solo widget transparente por encima de la pagina. Se da de baja del
    latido en cuanto muere la ultima particula, asi que no cuesta nada estando
    quieto.
    """

    BEAT_HZ = motion.HZ_FULL

    def __init__(self, parent: QWidget | None = None, *,
                 gravedad: float = 320.0) -> None:
        super().__init__(parent)
        self._p: list[_Chispa] = []
        self._gravedad = float(gravedad)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def estallar(self, cantidad: int = 46, origen: QPointF | None = None,
                 color: str | None = None, lado: float = 4.0,
                 rapidez: float = 420.0) -> None:
        if motion.reduce_motion():
            return
        o = origen if origen is not None else QPointF(self.width() / 2.0,
                                                      self.height() / 2.0)
        col = color or theme.C.tokens.color.accent
        rng = np.random.default_rng()
        for _ in range(int(cantidad)):
            ang = float(rng.uniform(0.0, 2.0 * math.pi))
            vel = float(rng.uniform(0.45, 1.0)) * rapidez
            self._p.append(_Chispa(
                o.x(), o.y(), math.cos(ang) * vel, math.sin(ang) * vel - vel * 0.35,
                float(rng.uniform(0.6, 1.15)),
                lado * float(rng.uniform(0.6, 1.3)), col))
        self.raise_()
        self.animate()

    def tick(self, dt: float) -> bool:
        vivas: list[_Chispa] = []
        for c in self._p:
            c.vida -= dt
            if c.vida <= 0.0:
                continue
            c.vy += self._gravedad * dt
            c.x += c.vx * dt
            c.y += c.vy * dt
            vivas.append(c)
        self._p = vivas
        self.update()
        if not self._p:
            self.rest()
            return False
        return True

    def paintEvent(self, event) -> None:
        if not self._p:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        for c in self._p:
            k = max(0.0, c.vida / c.total)
            color = QColor(c.color)
            color.setAlphaF(min(1.0, k * 1.4))
            p.setBrush(color)
            p.drawEllipse(QPointF(c.x, c.y), c.lado / 2.0, c.lado / 2.0)
        p.end()


class MarcaExito(ThemeAware, Beating, QWidget):
    """La marca de exito de P6: el trazo se dibuja y un anillo de luz se expande."""

    BEAT_HZ = motion.HZ_FULL

    TRAZO_MS = 420.0
    ANILLO_MS = 900.0

    def __init__(self, diametro: int = 108, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._d = float(diametro)
        self._trazo = 0.0
        self._anillo = 1.0
        self.setFixedSize(int(diametro * 1.9), int(diametro * 1.9))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def play(self) -> None:
        self._trazo = 0.0
        self._anillo = 0.0
        self.animate()

    def tick(self, dt: float) -> bool:
        ms = dt * 1000.0
        vivo = False
        if self._trazo < 1.0:
            self._trazo = min(1.0, self._trazo + ms / motion.dur(int(self.TRAZO_MS)))
            vivo = True
        if self._anillo < 1.0:
            self._anillo = min(1.0, self._anillo + ms / motion.dur(int(self.ANILLO_MS)))
            vivo = True
        self.update()
        if not vivo:
            self.rest()
        return vivo

    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        centro = QRectF(self.rect()).center()
        caja = QRectF(0, 0, self._d, self._d)
        caja.moveCenter(centro)

        if self._anillo < 1.0:
            k = motion.ease(self._anillo, motion.EASE_GLASS)
            radio = self._d * (0.5 + 0.42 * k)
            color = QColor(t.color.ok)
            color.setAlphaF(0.40 * (1.0 - k))
            pluma = QPen(color)
            pluma.setWidthF(3.0)
            p.setPen(pluma)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(centro, radio, radio)

        aro = QColor(t.color.ok)
        aro.setAlphaF(0.24)
        pluma = QPen(aro)
        pluma.setWidthF(3.0)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(caja)

        pluma = QPen(QColor(t.color.ok))
        pluma.setWidthF(4.5)
        pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
        pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pluma)
        p.drawPath(camino_parcial(
            camino_marca(caja.adjusted(self._d * 0.12, self._d * 0.12,
                                       -self._d * 0.12, -self._d * 0.12)),
            self._trazo))
        p.end()


# --------------------------------------------------------------------------- #
# P4 - el eje con tus tres cierres
# --------------------------------------------------------------------------- #

class EjePinch(ThemeAware, Beating, QWidget):
    """Los tres cierres medidos y el umbral que se desliza a su sitio.

    Es el pago del apartado 9.3 P4: el sistema trabajo mientras el usuario no
    miraba, y aqui se ve el resultado con sus propios numeros. Los puntos son
    los minimos reales de P3; el umbral se desliza en 700 ms ``EASE_SOFT``.
    """

    BEAT_HZ = motion.HZ_FULL

    ALTO = 92
    MARGEN = 26.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._puntos: list[float] = []
        self._umbral = Progresion(0.0, 700, motion.EASE_SOFT)
        self._lo, self._hi = 0.0, 1.0
        self._vivo: float | None = None
        self._cerrado = False
        self.setFixedHeight(self.ALTO)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_datos(self, puntos: list[float], lo: float, hi: float) -> None:
        self._puntos = list(puntos)
        self._lo, self._hi = float(lo), float(hi)
        self._umbral.jump(lo)
        self.update()

    def deslizar_umbral(self, valor: float) -> None:
        self._umbral.set(float(valor))
        self.animate()

    def set_vivo(self, valor: float | None, cerrado: bool) -> None:
        self._vivo = valor
        self._cerrado = bool(cerrado)
        self.update()

    def _x(self, valor: float) -> float:
        span = max(1e-6, self._hi - self._lo)
        k = max(0.0, min(1.0, (valor - self._lo) / span))
        return self.MARGEN + k * (self.width() - 2 * self.MARGEN)

    def tick(self, dt: float) -> bool:
        vivo = self._umbral.step(dt)
        self.update()
        if not vivo:
            self.rest()
        return vivo

    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        y = self.height() * 0.56

        pluma = QPen(QColor(t.edge.hair.over(t.glass.wash.solid)))
        pluma.setWidthF(1.0)
        pluma.setCosmetic(True)
        p.setPen(pluma)
        p.drawLine(QPointF(self.MARGEN, round(y) + 0.5),
                   QPointF(self.width() - self.MARGEN, round(y) + 0.5))

        p.setPen(Qt.PenStyle.NoPen)
        for i, v in enumerate(self._puntos):
            x = self._x(v)
            halo = QColor(t.color.accent)
            halo.setAlphaF(0.20)
            p.setBrush(halo)
            p.drawEllipse(QPointF(x, y), 11.0, 11.0)
            p.setBrush(QColor(t.color.accent))
            p.drawEllipse(QPointF(x, y), 4.5, 4.5)
            texto(p, QRectF(x - 30.0, y + 12.0, 60.0, 14.0), "axis",
                  f"{v:.2f}".replace(".", ","), t.text.tertiary,
                  Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        if self._vivo is not None:
            x = self._x(self._vivo)
            color = QColor(t.color.ok if self._cerrado else t.text.secondary)
            aguja = QPainterPath()
            aguja.moveTo(x, y - 13.0)
            aguja.lineTo(x - 5.0, y - 23.0)
            aguja.lineTo(x + 5.0, y - 23.0)
            aguja.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPath(aguja)

        if self._puntos:
            x = self._x(self._umbral.value)
            pluma = QPen(QColor(t.color.accent))
            pluma.setWidthF(1.6)
            p.setPen(pluma)
            p.drawLine(QPointF(round(x) + 0.5, y - 30.0),
                       QPointF(round(x) + 0.5, y + 10.0))
            texto(p, QRectF(x + 8.0, y - 34.0, 140.0, 14.0), "axis",
                  "umbral " + f"{self._umbral.value:.2f}".replace(".", ","),
                  t.color.accent)
        p.end()
