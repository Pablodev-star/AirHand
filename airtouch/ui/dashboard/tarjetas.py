"""Zona B: las tarjetas del mosaico (apartado 8.2).

Seis laminas y una franja. Lo que las separa de un cuadro de mando corriente no
son los datos que enseñan sino **el peso**: dos grandes arriba, tres menores
debajo, y el titulo en 38 px de caja alta abajo a la derecha. La jerarquia se
dibuja con tamaño, que es el principio 1.

Tres decisiones del archivo:

* **El grafico de fondo se pinta a mano, no es un widget hijo.** Qt pinta a los
  hijos *despues* del padre, asi que un grafico metido como hijo taparia el
  titulo y las cifras. El sangrado del apartado 4.3 tiene que ir por debajo del
  texto, y eso solo se consigue pintandolo dentro de ``paint_content``, antes.
  Es tambien mas barato: no hay un ``QWidget`` mas por tarjeta ni un pixmap
  intermedio.
* **El tope de opacidad del fondo es ``glass.BLEED_ALPHA`` y el velo es
  obligatorio.** Sin velo el texto se pierde justo cuando el grafico sube, que
  es cuando hay algo que mirar. No es ajustable a proposito.
* **Ninguna tarjeta guarda datos propios.** Leen del ``Telemetry`` del armazon o
  reciben lo que llega por señal. Una tarjeta que acumula su propio historial se
  queda desincronizada del resto en cuanto se cambia de pagina.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ...core.frame_state import HAND_CONNECTIONS, INDEX_TIP, THUMB_TIP
from ...gestures.events import Mode
from .. import charts, glass, motion, theme, tipo
from ..kit.base import Sheet
from ..telemetry import MIN_QUANTILES, PINCH_MAX, Telemetry
from ..tokens import R_LG, SHEET_PADDING
from .comun import GROSOR_ICONO, icono, texto, texto_ajustado

__all__ = [
    "Tarjeta", "TarjetaRendimiento", "TarjetaMano", "TarjetaGestos",
    "TarjetaSeguridad", "TarjetaEnlace", "FranjaNovedades", "Novedad",
    "ALTO_FILA_1", "ALTO_FILA_2", "ALTO_NOVEDADES", "COLUMNAS",
]

#: La rejilla del apartado 8.2: seis columnas y dos filas de alturas distintas.
COLUMNAS = 6
ALTO_FILA_1 = 300.0
ALTO_FILA_2 = 190.0
ALTO_NOVEDADES = 96.0

#: Lado del icono de linea fina de la esquina superior izquierda.
ICONO = 20.0

#: Rejilla del lienzo de LA MANO. 32 px es el numero del apartado 8.2 y tambien
#: la escala a la que una mano de 21 puntos se lee como un instrumento.
REJILLA = 32.0

#: Pose de reposo del esqueleto: la que queda cuando no hay ninguna mano a la
#: vista. No es una mano capturada y guardada, es una mano dibujada, porque una
#: captura real de la sesion anterior seria un dato viejo haciendose pasar por
#: uno nuevo. Coordenadas normalizadas 0..1 con la muñeca abajo.
POSE_REPOSO: tuple[tuple[float, float], ...] = (
    (0.50, 0.92),
    (0.36, 0.86), (0.28, 0.75), (0.24, 0.65), (0.22, 0.56),
    (0.42, 0.58), (0.40, 0.44), (0.39, 0.35), (0.38, 0.27),
    (0.52, 0.56), (0.52, 0.40), (0.52, 0.30), (0.52, 0.22),
    (0.62, 0.58), (0.63, 0.44), (0.64, 0.34), (0.65, 0.27),
    (0.71, 0.63), (0.75, 0.52), (0.77, 0.44), (0.79, 0.38),
)

#: Alfa a la que se desvanece el esqueleto sin mano (apartado 8.2).
FANTASMA = 0.12

#: Lo que se tarda en dar una mano por perdida. Menos que esto y el esqueleto
#: parpadearia en cada fotograma que el detector se salta.
PERDIDA_S = 0.45


def _p95(a: np.ndarray) -> float:
    """Percentil 95, o ``nan`` si no hay muestras para sostenerlo.

    Es la misma definicion y el mismo umbral de honestidad que usa
    ``Telemetry._quantiles``, calculada aqui sobre una sola serie: la tanda
    entera de agregados solo se pide con la pagina de analisis delante
    (apartado 6.3), y el mosaico necesita este numero y ninguno mas.
    """
    if a.size < MIN_QUANTILES:
        return float("nan")
    return float(np.percentile(a.astype(np.float64), 95))


def _cifra(valor: float, decimales: int = 0) -> str:
    if not math.isfinite(valor):
        return "—"
    return charts.num(valor, decimales)


# --------------------------------------------------------------------------- #
# la base
# --------------------------------------------------------------------------- #

class Tarjeta(Sheet):
    """Una lamina del mosaico: icono arriba, titulo enorme abajo a la derecha.

    ``ABRE`` nombra la pagina profunda a la que lleva. Una tarjeta que no abre
    nada sigue siendo interactiva -se alza al pasar por encima, que es el canal
    de retroalimentacion del apartado 4.3- pero no promete un destino con el
    cursor de mano.
    """

    TITULO = ""
    GLIFO = ""
    ABRE = ""

    #: La tarjeta pinta un grafico a sangre. Manda dos cosas: el tope de
    #: opacidad y el velo obligatorio del apartado 4.3. Una tarjeta sin fondo
    #: no lleva velo, porque un degradado oscuro sobre vidrio limpio se ve.
    FONDO = False

    #: Rol del titulo. Las tarjetas de la fila 2 lo heredan igual: el titulo se
    #: encoge solo con ``texto_ajustado`` si no cabe, y esa es justamente la
    #: jerarquia por tamaño, no una excepcion a ella.
    ROL_TITULO = "mosaico"

    pulsada = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, elevation="E2", radius=R_LG,
                         padding=SHEET_PADDING, interactive=True)
        if self.ABRE:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(self.TITULO)

    # -- interaccion --------------------------------------------------------
    def _abrir(self) -> None:
        if self.ABRE:
            self.flash()
            self.pulsada.emit(self.ABRE)

    def mouseReleaseEvent(self, e) -> None:                 # noqa: N802
        if (e.button() == Qt.MouseButton.LeftButton
                and self.glass_box().contains(e.position())):
            self._abrir()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:                     # noqa: N802
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._abrir()
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e) -> None:                      # noqa: N802
        super().focusInEvent(e)
        self.set_hover(True)

    def focusOutEvent(self, e) -> None:                     # noqa: N802
        super().focusOutEvent(e)
        self.set_hover(False)

    # -- ganchos ------------------------------------------------------------
    def pintar_fondo(self, p: QPainter, caja: QRectF) -> None:
        """El grafico que **es** el fondo. Ya viene recortado a la lamina."""

    def pintar_datos(self, p: QPainter, rect: QRectF) -> None:
        """Cifras y rotulos, por encima del velo."""

    # -- pintado ------------------------------------------------------------
    def _caja_titulo(self, rect: QRectF) -> QRectF:
        alto = tipo.metrics(self.ROL_TITULO).height()
        return QRectF(rect.left(), rect.bottom() - alto, rect.width(), alto)

    def paint_content(self, p: QPainter, rect: QRectF) -> None:
        caja = self.glass_box()
        if self.FONDO:
            p.save()
            p.setOpacity(glass.BLEED_ALPHA)
            self.pintar_fondo(p, caja)
            p.restore()
            charts.veil(p, caja)

        t = theme.C
        if self.GLIFO:
            icono(p, QRectF(rect.left(), rect.top(), ICONO, ICONO),
                  self.GLIFO, t.ink.secondary)
        self.pintar_datos(p, rect)
        texto_ajustado(p, self._caja_titulo(rect), self.ROL_TITULO,
                       self.TITULO, t.ink.primary,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


# --------------------------------------------------------------------------- #
# fila 1
# --------------------------------------------------------------------------- #

class TarjetaRendimiento(Tarjeta):
    """RENDIMIENTO: el grafico grande de fps y retardo es el fondo.

    Las tres cifras que lleva encima son las tres que de verdad se miran: los
    fotogramas que el motor procesa, el **percentil 95** del retardo de captura
    -no la media, que esconde justo los picos que se sienten- y lo que tarda la
    deteccion. Pulsandola se abre ANALISIS, que es donde estan las otras nueve.
    """

    TITULO = "Rendimiento"
    GLIFO = "rendimiento"
    ABRE = "analisis"
    FONDO = True

    def __init__(self, tele: Telemetry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tele = tele
        self._fps = 0.0
        self._proc = 0.0

    def on_stats(self, stats: dict) -> None:
        self._fps = float(stats.get("pipeline_fps", 0.0) or 0.0)
        self._proc = float(stats.get("process_ms", 0.0) or 0.0)
        self.update()

    # -- el fondo -----------------------------------------------------------
    def pintar_fondo(self, p: QPainter, caja: QRectF) -> None:
        fps = self.tele.fps_pipe.view()
        lat = self.tele.lat.view()
        if fps.size < 2:
            return
        techo = charts.ceil_nice(max(60.0, float(fps.max())))
        self._area(p, caja, fps, techo, theme.C.color.accent)
        if lat.size >= 2:
            techo_lat = charts.ceil_nice(max(60.0, float(lat.max())))
            self._linea(p, caja, lat, techo_lat, theme.C.color.warn)

    @staticmethod
    def _puntos(caja: QRectF, serie: np.ndarray, techo: float) -> list[QPointF]:
        dx = caja.width() / max(1, serie.size - 1)
        return [QPointF(caja.left() + i * dx,
                        caja.bottom() - min(1.0, float(v) / techo) * caja.height())
                for i, v in enumerate(serie)]

    def _area(self, p: QPainter, caja: QRectF, serie: np.ndarray,
              techo: float, color: str) -> None:
        pts = self._puntos(caja, serie, techo)
        camino = QPainterPath(QPointF(caja.left(), caja.bottom()))
        for punto in pts:
            camino.lineTo(punto)
        camino.lineTo(QPointF(caja.right(), caja.bottom()))
        camino.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(charts.area_gradient(caja, color))
        p.drawPath(camino)

    def _linea(self, p: QPainter, caja: QRectF, serie: np.ndarray,
               techo: float, color: str) -> None:
        pts = self._puntos(caja, serie, techo)
        camino = QPainterPath(pts[0])
        for punto in pts[1:]:
            camino.lineTo(punto)
        pluma = QPen(QColor(color), 1.5)
        pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
        pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(camino)

    # -- las cifras ---------------------------------------------------------
    def pintar_datos(self, p: QPainter, rect: QRectF) -> None:
        t = theme.C
        p95 = _p95(self.tele.lat.view())
        columnas = (
            ("fps del motor", _cifra(self._fps), "", ""),
            ("retardo p95", _cifra(p95), "ms",
             "percentil 95 de latency_ms"),
            ("detección", _cifra(self._proc, 1), "ms", ""),
        )
        ancho = rect.width() / 3.0
        base = self._caja_titulo(rect).top() - 8.0
        alto = tipo.metrics("metric").height()
        for i, (rotulo, valor, unidad, nota) in enumerate(columnas):
            x = rect.left() + i * ancho
            texto(p, QRectF(x, base - alto - 30.0, ancho, 14.0), "overline",
                  rotulo, t.ink.tertiary)
            texto(p, QRectF(x, base - alto - 12.0, ancho, alto), "metric",
                  valor, t.ink.primary)
            avance = tipo.metrics("metric").horizontalAdvance(valor)
            if unidad:
                texto(p, QRectF(x + avance + 6.0, base - alto - 12.0,
                                ancho - avance, alto), "caption", unidad,
                      t.ink.tertiary)
            if nota:
                p.setFont(tipo.font("caption", size=11))
                p.setPen(QColor(t.ink.quiet))
                p.drawText(QRectF(x, base - 12.0, ancho, 13.0),
                           int(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter), nota)


class TarjetaMano(Tarjeta):
    """LA MANO: el esqueleto en vivo sobre una rejilla, sin la imagen.

    No se pinta el fotograma de la camara a proposito. Los veintiun puntos y sus
    veintiun huesos cuestan ~1,5 ms, se leen mejor que un video comprimido de
    una habitacion mal iluminada, y convierten la tarjeta en un instrumento: lo
    que se mira aqui es si el detector te sigue los dedos, no como esta tu
    salon.

    La tarjeta enciende ``preview_enabled`` al mostrarse y lo apaga al
    esconderse, y sube ``_preview_every`` a 3 mientras vive en el mosaico: en el
    mosaico basta con ver que la mano responde, no con contarla fotograma a
    fotograma (eso es la pagina de Camara, que baja a 2).
    """

    TITULO = "La mano"
    GLIFO = "mano"
    ABRE = "camara"
    FONDO = True

    #: Cadencia de fotograma que pide la tarjeta mientras esta en el mosaico.
    CADA = 3

    def __init__(self, ctl, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self._puntos: np.ndarray | None = None
        self._manos = 0
        self._pinch = 1.0
        self._modo = Mode.IDLE
        self._score = 0.0
        self._visto = 0.0
        self._vivo = motion.Smooth(0.0, 0.18)

    # -- ciclo --------------------------------------------------------------
    def showEvent(self, event) -> None:                     # noqa: N802
        super().showEvent(event)
        self.ctl.preview_enabled = True
        self.ctl._preview_every = self.CADA

    def hideEvent(self, event) -> None:                     # noqa: N802
        self.ctl.preview_enabled = False
        super().hideEvent(event)

    # -- datos --------------------------------------------------------------
    def on_frame(self, _frame, estado) -> None:
        mano = estado.primary
        self._manos = len(estado.hands)
        if mano is not None:
            self._puntos = np.array(mano.lm[:, :2], dtype=np.float32)
            self._score = float(mano.score)
            self._visto = 0.0
            self._vivo.set(1.0)
        self.animate()

    def on_output(self, out) -> None:
        self._pinch = float(out.pinch_ratio)
        self._modo = out.mode

    def tick(self, dt: float) -> bool:
        vivo = super().tick(dt)
        self._visto += dt
        if self._visto > PERDIDA_S:
            self._vivo.set(0.0)
        self._vivo.step()
        self.update()
        return vivo or not self._vivo.settled or self._vivo.value > 0.001

    # -- pintado ------------------------------------------------------------
    def _lienzo(self, caja: QRectF) -> QRectF:
        """El cuadrado donde vive la mano, centrado y con margen."""
        lado = min(caja.width(), caja.height()) - 2.0 * SHEET_PADDING
        return QRectF(caja.center().x() - lado / 2.0,
                      caja.top() + SHEET_PADDING, lado, lado)

    def pintar_fondo(self, p: QPainter, caja: QRectF) -> None:
        t = theme.C
        # el pozo llega a los cantos: la tarjeta *es* el lienzo hundido
        p.fillRect(caja, QColor(t.glass.sunken.solid))
        pluma = QPen(glass.qcolor(t.edge.hair), 1.0)
        pluma.setCosmetic(True)
        p.setPen(pluma)
        x = caja.left() + REJILLA
        while x < caja.right():
            p.drawLine(QPointF(round(x) + 0.5, caja.top()),
                       QPointF(round(x) + 0.5, caja.bottom()))
            x += REJILLA
        y = caja.top() + REJILLA
        while y < caja.bottom():
            p.drawLine(QPointF(caja.left(), round(y) + 0.5),
                       QPointF(caja.right(), round(y) + 0.5))
            y += REJILLA

    def pintar_datos(self, p: QPainter, rect: QRectF) -> None:
        t = theme.C
        k = max(0.0, min(1.0, self._vivo.value))
        alfa = FANTASMA + (1.0 - FANTASMA) * k
        origen = self._puntos
        if origen is None:
            origen = np.array(POSE_REPOSO, dtype=np.float32)
            alfa = FANTASMA
        self._pintar_esqueleto(p, self._lienzo(self.glass_box()), origen, alfa)

        if k < 0.5 and self._puntos is None:
            texto(p, QRectF(rect.left(), rect.top() + ICONO + 10.0,
                            rect.width(), 16.0), "overline", "Sin mano",
                  t.ink.tertiary)
            return
        linea = " · ".join((
            self._modo.value,
            "1 mano" if self._manos == 1 else f"{self._manos} manos",
            self._calidad()))
        caja = self._caja_titulo(rect)
        texto(p, QRectF(rect.left(), caja.top() - 18.0, rect.width(), 14.0),
              "caption", linea, t.ink.secondary)

    def _calidad(self) -> str:
        if self._score >= 0.85:
            return "señal buena"
        if self._score >= 0.6:
            return "señal justa"
        return "señal pobre"

    def _pintar_esqueleto(self, p: QPainter, caja: QRectF, puntos: np.ndarray,
                          alfa: float) -> None:
        t = theme.C
        pts = [QPointF(caja.left() + float(x) * caja.width(),
                       caja.top() + float(y) * caja.height())
               for x, y in puntos[:, :2]]
        hueso = QColor(t.ink.secondary)
        hueso.setAlphaF(alfa)
        pluma = QPen(hueso, 2.0)
        pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for a, b in HAND_CONNECTIONS:
            if (a, b) == (3, 4):
                continue                # el pulgar-indice va aparte, teñido
            p.drawLine(pts[a], pts[b])

        # el segmento pulgar-indice lleva el color de modo y engorda al cerrar:
        # es el unico canal de color de la tarjeta, y dice lo unico que importa
        pinza = QColor(t.tokens.mode_color(self._modo))
        pinza.setAlphaF(alfa)
        grosor = 2.0 + 3.0 * max(0.0, min(1.0, 1.0 - self._pinch))
        p.setPen(QPen(pinza, grosor, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(pts[THUMB_TIP], pts[INDEX_TIP])

        p.setPen(Qt.PenStyle.NoPen)
        articulacion = QColor(t.ink.secondary)
        articulacion.setAlphaF(alfa)
        p.setBrush(articulacion)
        for i, punto in enumerate(pts):
            if i in (4, 8, 12, 16, 20):
                continue
            p.drawEllipse(punto, 1.5, 1.5)
        yema = QColor(t.ink.primary)
        yema.setAlphaF(alfa)
        p.setBrush(yema)
        for i in (4, 8, 12, 16, 20):
            p.drawEllipse(pts[i], 2.25, 2.25)


# --------------------------------------------------------------------------- #
# fila 2
# --------------------------------------------------------------------------- #

class TarjetaGestos(Tarjeta):
    """GESTOS: el histograma de pinch en vivo es el fondo.

    El histograma cuenta en que posicion se queda la pinza, y con la sesion
    puesta enseña dos montañas -mano abierta y mano cerrada- con un valle en
    medio. Ese valle es donde deberia estar el umbral, y por eso este grafico
    vive en la portada y no escondido en una pagina de ajustes.
    """

    TITULO = "Gestos"
    GLIFO = "gestos"
    ABRE = "gestos"
    FONDO = True

    def __init__(self, tele: Telemetry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tele = tele
        self._cuentas = {"clic": 0, "scroll": 0, "zoom": 0}

    def set_cuentas(self, cuentas: dict[str, int]) -> None:
        if cuentas != self._cuentas:
            self._cuentas = dict(cuentas)
            self.update()

    def pintar_fondo(self, p: QPainter, caja: QRectF) -> None:
        h = self.tele.pinch_hist.astype(np.float64)
        pico = float(h.max())
        if pico <= 0.0:
            return
        ancho = caja.width() / h.size
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(charts.area_gradient(caja, theme.C.color.accent))
        for i, v in enumerate(h):
            alto = float(v) / pico * caja.height()
            if alto < 0.5:
                continue
            p.drawRect(QRectF(caja.left() + i * ancho, caja.bottom() - alto,
                              max(1.0, ancho - 1.0), alto))

    def pintar_datos(self, p: QPainter, rect: QRectF) -> None:
        t = theme.C
        ancho = rect.width() / 3.0
        y = rect.top() + ICONO + 12.0
        alto = tipo.metrics("h1").height()
        for i, nombre in enumerate(("clic", "scroll", "zoom")):
            x = rect.left() + i * ancho
            texto(p, QRectF(x, y, ancho, alto), "h1",
                  str(self._cuentas.get(nombre, 0)), t.ink.primary)
            texto(p, QRectF(x, y + alto, ancho, 14.0), "overline", nombre,
                  t.ink.tertiary)


class TarjetaSeguridad(Tarjeta):
    """SEGURIDAD: las cuatro guardas, y el motivo real cuando hay pausa.

    Los cuatro puntos no son decorativos: dicen que guardas estan **armadas**
    (las que el usuario ha dejado encendidas en ajustes) y cual esta actuando
    ahora mismo. Cuando una pausa el motor, el detalle no dice "en pausa": dice
    el motivo que ha escrito ``SafetyGuard``, que es lo unico accionable.
    """

    TITULO = "Seguridad"
    GLIFO = "seguridad"
    FONDO = True

    GUARDAS = (("cara", "no se detecta al usuario"),
               ("ratón físico", ""),
               ("palma abierta", "palma abierta"),
               ("Esc", "Esc"))

    def __init__(self, ctl, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self._cara = False
        self._pausado = False

    def on_stats(self, stats: dict) -> None:
        cara = bool(stats.get("face"))
        pausado = bool(stats.get("paused"))
        if cara != self._cara or pausado != self._pausado:
            self._cara, self._pausado = cara, pausado
            self._marcar()
            self.update()

    def _marcar(self) -> None:
        """El filo sube a 0.24 mientras hay pausa: el estado se dice en el filo.

        El tinte de fondo lo pone ``pintar_fondo``, que es donde el sangrado se
        topa a ``BLEED_ALPHA`` y se le pone el velo; hacerlo con ``set_tint``
        pintaria por encima del recorte del lienzo y a plena opacidad.
        """
        self.set_active(self._pausado)

    def _armadas(self) -> tuple[bool, ...]:
        c = self.ctl.cfg.safety
        return (c.pause_on_no_face, c.mouse_override, c.open_palm_pause, True)

    def _tonos(self) -> tuple[str, ...]:
        t = theme.C
        g = self.ctl.safety
        motivo = g.state.reason
        activa = [motivo == "no se detecta al usuario",
                  g.overridden,
                  motivo == "palma abierta",
                  motivo == "Esc"]
        salud = [self._cara, True, True, True]
        fuera: list[str] = []
        for i, armada in enumerate(self._armadas()):
            if not armada:
                fuera.append(t.ink.quiet)
            elif activa[i]:
                fuera.append(t.color.danger)
            elif not salud[i]:
                fuera.append(t.color.warn)
            else:
                fuera.append(t.color.ok)
        return tuple(fuera)

    def pintar_fondo(self, p: QPainter, caja: QRectF) -> None:
        if not self._pausado:
            return
        # el fondo se tiñe de danger cuando hay pausa. Es un lavado y no un
        # borde: el principio 1 prohibe resolver esto con una linea.
        tinta = QColor(theme.C.color.danger)
        tinta.setAlphaF(0.55)
        p.fillRect(caja, tinta)

    def pintar_datos(self, p: QPainter, rect: QRectF) -> None:
        t = theme.C
        y = rect.top() + ICONO + 10.0
        for (nombre, _motivo), color in zip(self.GUARDAS, self._tonos()):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(rect.left() + 4.0, y + 7.0), 3.5, 3.5)
            texto(p, QRectF(rect.left() + 16.0, y, rect.width() - 16.0, 15.0),
                  "caption", nombre, t.ink.secondary)
            y += 17.0

        caja = self._caja_titulo(rect)
        detalle = self.ctl.safety.status_text()
        p.setFont(tipo.font("caption", size=11))
        p.setPen(QColor(t.color.danger if self._pausado else t.ink.tertiary))
        p.drawText(QRectF(rect.left(), caja.top() - 16.0, rect.width(), 14.0),
                   int(Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter), detalle)


class TarjetaEnlace(Tarjeta):
    """ENLACE: el movil, su resolucion y el atajo al QR.

    Con una webcam del sistema en vez de AirLink la tarjeta no miente ni se
    queda en blanco: dice que fuente hay puesta. Un hueco vacio en el mosaico se
    lee como un fallo de carga.
    """

    TITULO = "Enlace"
    GLIFO = "enlace"
    ABRE = "camara"

    def __init__(self, ctl, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self._resolucion = ""

    def on_stats(self, stats: dict) -> None:
        res = str(stats.get("resolution", ""))
        if res != self._resolucion:
            self._resolucion = res
            self.update()

    def pintar_datos(self, p: QPainter, rect: QRectF) -> None:
        t = theme.C
        link = self.ctl.airlink
        usa_airlink = self.ctl.using_airlink
        if not usa_airlink:
            estado, tono = "Cámara del sistema", t.ink.secondary
        elif link.phone_connected:
            estado, tono = "Móvil conectado", t.color.ok
        elif link.error:
            estado, tono = "Error del servidor", t.color.danger
        elif link.running:
            estado, tono = "Esperando al móvil", t.color.warn
        else:
            estado, tono = "Servidor detenido", t.ink.tertiary

        y = rect.top() + ICONO + 10.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(tono))
        p.drawEllipse(QPointF(rect.left() + 4.0, y + 8.0), 3.5, 3.5)
        texto(p, QRectF(rect.left() + 16.0, y, rect.width() - 16.0, 16.0),
              "body-fuerte", estado, t.ink.primary)

        detalle = self._resolucion or "—"
        if usa_airlink and link.phone_connected and link.fps:
            detalle = f"{detalle} · {charts.num(link.fps, 0)} fps"
        texto(p, QRectF(rect.left(), y + 20.0, rect.width(), 16.0), "mono",
              detalle, t.ink.secondary)

        caja = self._caja_titulo(rect)
        texto(p, QRectF(rect.left(), caja.top() - 16.0, rect.width(), 14.0),
              "caption",
              "Ver el código QR" if usa_airlink else "Ver la cámara",
              t.ink.tertiary)


# --------------------------------------------------------------------------- #
# la franja de novedades
# --------------------------------------------------------------------------- #

class Novedad:
    """Una mini-tarjeta fechada. Sin dato que contar, no existe."""

    __slots__ = ("fecha", "titulo", "texto", "tono")

    def __init__(self, fecha: str, titulo: str, texto: str,
                 tono: str = "neutral") -> None:
        self.fecha = fecha
        self.titulo = titulo
        self.texto = texto
        self.tono = tono

    def __eq__(self, otra: object) -> bool:
        return (isinstance(otra, Novedad) and otra.fecha == self.fecha
                and otra.titulo == self.titulo and otra.texto == self.texto)


class FranjaNovedades(Sheet):
    """La franja de 96 px del apartado 8.2: solo si hay algo que decir.

    Es la unica pieza del mosaico que puede no estar. Una franja permanente con
    "todo va bien" escrito dentro ocupa 96 px para no decir nada, y a la tercera
    vez ya nadie la mira.
    """

    ALTO = ALTO_NOVEDADES
    MAX = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, elevation="E2", radius=R_LG, padding=16)
        self._items: list[Novedad] = []

    @property
    def items(self) -> list[Novedad]:
        return list(self._items)

    def set_items(self, items) -> None:
        nuevos = list(items)[:self.MAX]
        if nuevos == self._items:
            return
        self._items = nuevos
        self.setVisible(bool(nuevos))
        self.update()

    def paint_content(self, p: QPainter, rect: QRectF) -> None:
        if not self._items:
            return
        t = theme.C
        ancho = rect.width() / len(self._items)
        for i, item in enumerate(self._items):
            x = rect.left() + i * ancho
            caja = QRectF(x, rect.top(), ancho - 16.0, rect.height())
            color = {"ok": t.color.ok, "warn": t.color.warn,
                     "danger": t.color.danger,
                     "accent": t.color.accent}.get(item.tono, t.ink.tertiary)
            icono(p, QRectF(caja.left(), caja.top() + 1.0, 16.0, 16.0),
                  "novedad", color)
            texto(p, QRectF(caja.left() + 24.0, caja.top(),
                            caja.width() - 24.0, 16.0), "overline",
                  item.fecha, t.ink.quiet)
            texto(p, QRectF(caja.left(), caja.top() + 20.0, caja.width(), 18.0),
                  "body-fuerte", item.titulo, t.ink.primary)
            parrafo = tipo.Parrafo(item.texto, "caption", max_lines=2)
            parrafo.set_width(caja.width())
            parrafo.draw(p, caja.left(), caja.top() + 40.0,
                         QColor(t.ink.secondary))
