"""Zona C: la barra flotante inferior (apartado 8.3).

Una pildora E4 centrada, de alto 56 y radio 28, a 22 px del borde. Cinco
destinos y, separado por un filo, el chip de estado que **sobrevive a cualquier
pagina**: da igual donde estes, la barra te dice si tus gestos estan tocando el
escritorio de verdad.

Dos cosas que hacen esta barra distinta de una barra de pestañas cualquiera:

* **La pildora del activo se tiñe del color de modo cuando el control real esta
  puesto.** Es la unica pieza de cromo del panel que cambia de color por si
  sola, y lo hace porque el dato que lleva -"estas en directo"- es el unico que
  no se puede permitir tener que buscar.
* **La pildora viaja con ``Spring`` e interpola tambien su anchura**, como el
  segmentado del kit (patron 5.5.9). Un rectangulo que se estira mientras viaja
  se lee como un objeto; uno que salta se lee como un fallo de pintado.

Los destinos se pintan a mano y se aciertan por golpe de raton. No son botones:
seis widgets hijos dentro de una lamina de 56 px de alto obligarian a repartir
la reserva de sombra de cada uno dentro del padre, y el ``Badge`` de la derecha
-que si es un widget, porque tiene su propio pop- ya es el unico que lo pide.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ...gestures.events import Mode
from .. import glass, motion, theme, tipo
from ..kit.base import Sheet
from ..kit.display import Badge
from ..tokens import BOTTOM_BAR_H, R_FULL
from .comun import icono, texto

__all__ = ["BarraInferior", "DESTINOS", "MARGEN_INFERIOR"]

#: Los cinco destinos del apartado 8.3, en orden. (clave, rotulo, glifo).
DESTINOS: tuple[tuple[str, str, str], ...] = (
    ("mosaico", "Mosaico", "nav-mosaico"),
    ("camara", "Cámara", "nav-camara"),
    ("gestos", "Gestos", "nav-gestos"),
    ("ajustes", "Ajustes", "nav-ajustes"),
    ("registro", "Registro", "nav-registro"),
)

#: Distancia de la barra al borde inferior de la ventana (apartado 8.3).
MARGEN_INFERIOR = 22

#: Geometria interna de un destino.
PAD_H = 16.0
GLIFO = 18.0
HUECO_GLIFO = 8.0
PAD_LADO = 8.0
HUECO_CHIP = 14.0


def _legible_sobre(relleno: QColor) -> str:
    """Tinta que se lee encima del relleno de la pildora activa.

    El relleno cruza del acento al color de modo, y los dos extremos piden
    tintas opuestas segun la paleta: el acento oscuro (#7C8CFF) es una lavanda
    clara y pide tinta, el claro (#4257E8) es un azul saturado y pide blanco.
    Se decide por luminancia y no por tema, que es lo unico que acierta tambien
    en los diez colores de la rampa de modo.
    """
    lum = (0.2126 * relleno.redF() + 0.7152 * relleno.greenF()
           + 0.0722 * relleno.blueF())
    return theme.C.canvas.base if lum > 0.55 else "#FFFFFF"


class BarraInferior(Sheet):
    """La pildora de navegacion. ``status_badge`` es el chip de la derecha."""

    navegar = Signal(str)

    ALTO = BOTTOM_BAR_H

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, elevation="E4", radius=R_FULL, padding=8)
        self._indice = 0
        self._hover = -1
        self._x = motion.Spring(0.0, eps=0.25)
        self._w = motion.Spring(0.0, eps=0.25)
        self._color = motion.Smooth(0.0, motion.TAU_MODE_COLOR)
        self._modo = Mode.IDLE
        self._control = False

        self.status_badge = Badge("modo seguro", self, tone="neutral", dot=True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # -- API ----------------------------------------------------------------
    @property
    def indice(self) -> int:
        return self._indice

    def set_destino(self, clave: str) -> None:
        """Marca el destino activo sin emitir. Lo llama el armazon.

        Una pagina profunda (ANALISIS) no tiene destino propio: se llego a ella
        desde una tarjeta. El armazon deja marcado el destino desde el que se
        entro, que es exactamente adonde devuelve pulsarlo (apartado 8.4).
        """
        for i, (nombre, _rotulo, _glifo) in enumerate(DESTINOS):
            if nombre == clave and i != self._indice:
                self._indice = i
                self._retarget()
                self.animate()
                self.update()
                return

    def set_control(self, activo: bool, modo: Mode, pausado: bool) -> None:
        """El estado que pinta el chip y tiñe la pildora."""
        activo = bool(activo)
        cambio = activo != self._control or modo is not self._modo
        self._control, self._modo = activo, modo
        self._color.set(1.0 if activo else 0.0)
        if pausado:
            self.status_badge.set_text("en pausa", "danger")
        elif motion.beat.saving:
            self.status_badge.set_text("ahorro", "warn")
        elif activo:
            self.status_badge.set_text("control activo", "ok")
        else:
            self.status_badge.set_text("modo seguro", "neutral")
        if cambio:
            self.animate()
        self.update()

    # -- geometria ----------------------------------------------------------
    def _anchos(self) -> list[float]:
        m = tipo.metrics("caption")
        return [m.horizontalAdvance(tipo.text("caption", rotulo))
                + GLIFO + HUECO_GLIFO + 2.0 * PAD_H
                for _clave, rotulo, _glifo in DESTINOS]

    def _tramos(self) -> list[tuple[float, float]]:
        x = self.content_rect().left()
        fuera: list[tuple[float, float]] = []
        for w in self._anchos():
            fuera.append((x, w))
            x += w
        return fuera

    def ancho_pedido(self) -> float:
        """Ancho del **vidrio** que necesita la barra con su contenido."""
        chip = self.status_badge.sizeHint().width()
        return (sum(self._anchos()) + 2.0 * PAD_LADO
                + HUECO_CHIP * 2.0 + 1.0 + chip)

    def _retarget(self) -> None:
        x, w = self._tramos()[self._indice]
        self._x.set(x)
        self._w.set(w)

    def colocar(self) -> None:
        """Recoloca el chip y reengancha la pildora. Tras un ``place()``."""
        c = self.content_rect()
        h = self.status_badge.sizeHint()
        self.status_badge.setGeometry(
            int(c.right() - h.width()), int(c.center().y() - h.height() / 2.0),
            h.width(), h.height())
        x, w = self._tramos()[self._indice]
        self._x.jump(x)
        self._w.jump(w)

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        self.colocar()

    def on_theme(self) -> None:
        super().on_theme()
        self.colocar()

    # -- interaccion --------------------------------------------------------
    def _en(self, x: float) -> int:
        for i, (izq, w) in enumerate(self._tramos()):
            if izq <= x < izq + w:
                return i
        return -1

    def event(self, e) -> bool:
        if e.type() == e.Type.HoverLeave and self._hover != -1:
            self._hover = -1
            self.update()
        return super().event(e)

    def mouseMoveEvent(self, e) -> None:                    # noqa: N802
        i = self._en(e.position().x())
        if i != self._hover:
            self._hover = i
            self.setCursor(Qt.CursorShape.PointingHandCursor if i >= 0
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, e) -> None:                 # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            i = self._en(e.position().x())
            if i >= 0:
                self.navegar.emit(DESTINOS[i][0])
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:                     # noqa: N802
        if e.key() == Qt.Key.Key_Left:
            self.navegar.emit(DESTINOS[max(0, self._indice - 1)][0])
            return
        if e.key() == Qt.Key.Key_Right:
            i = min(len(DESTINOS) - 1, self._indice + 1)
            self.navegar.emit(DESTINOS[i][0])
            return
        super().keyPressEvent(e)

    # -- latido -------------------------------------------------------------
    def tick(self, dt: float) -> bool:
        vivo = super().tick(dt)
        self._x.step(dt)
        self._w.step(dt)
        self._color.step()
        moviendo = not (self._x.settled and self._w.settled
                        and self._color.settled)
        if moviendo:
            self.update()
        return vivo or moviendo

    # -- pintado ------------------------------------------------------------
    def _color_activo(self) -> QColor:
        t = theme.C
        k = max(0.0, min(1.0, self._color.value))
        return QColor(theme.mix(t.color.accent,
                                t.tokens.mode_color(self._modo), k))

    def paint_content(self, p: QPainter, rect: QRectF) -> None:
        t = theme.C
        alto = rect.height()
        relleno = self._color_activo()

        pildora = QRectF(self._x.value, rect.top(), max(1.0, self._w.value), alto)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(relleno)
        p.drawRoundedRect(pildora, alto / 2.0, alto / 2.0)

        tinta_activa = _legible_sobre(relleno)
        for i, (_clave, rotulo, glifo) in enumerate(DESTINOS):
            izq, w = self._tramos()[i]
            if i == self._indice:
                color = tinta_activa
            elif i == self._hover:
                color = t.ink.primary
            else:
                color = t.ink.secondary
            caja = QRectF(izq, rect.top(), w, alto)
            icono(p, QRectF(caja.left() + PAD_H, caja.center().y() - GLIFO / 2.0,
                            GLIFO, GLIFO), glifo, color)
            texto(p, QRectF(caja.left() + PAD_H + GLIFO + HUECO_GLIFO,
                            caja.top(), w, alto), "caption", rotulo, color)

        # el filo de 1 px que separa la navegacion del chip de estado. Es la
        # unica linea del panel, y esta permitida porque no separa dos bloques
        # de contenido: separa el mando del indicador, que es un cambio de
        # naturaleza y no de tema
        x = self.status_badge.x() - HUECO_CHIP
        pluma = QPen(glass.qcolor(t.edge.dominant), 1.0)
        pluma.setCosmetic(True)
        p.setPen(pluma)
        p.drawLine(QPointF(round(x) + 0.5, rect.top() + 8.0),
                   QPointF(round(x) + 0.5, rect.bottom() - 8.0))
