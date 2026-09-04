"""Los mandos: lo unico del kit que el usuario toca con el raton.

Todos cuelgan de ``base.py`` -de ``Sheet`` los que son una lamina de verdad
(``Button``), del par de mixins los que no- y ninguno se sale de las tres
fuentes de verdad del sistema: la tipografia sale de ``tipo.py``, el movimiento
del ``Beat`` de ``motion.py`` y el color de ``tokens.py``. Aqui no se escribe un
hex.

Tres decisiones que conviene entender antes de tocar nada:

* **``Phase`` en vez de ``Smooth``.** El apartado 5.4 pide 120 ms de ida y 90 de
  vuelta, y el 5.2 pide curvas distintas para cada sentido. ``Smooth`` es
  exponencial y no tiene ni duracion ni curva, asi que un hover hecho con
  ``Smooth`` entra y sale igual. ``Phase`` es el 0->1 con dos duraciones y dos
  curvas que necesita cualquier mando; ``Spring`` sigue siendo el de la perilla
  y la pildora, donde importa la velocidad con la que se llega.
* **El foco no alza, solo dibuja el anillo.** Alzar con el foco obligaba a
  arbitrar entre raton y teclado en cada widget (con el raton dentro y el foco
  fuera, quien manda) y el resultado se veia como un parpadeo. El anillo de
  acento es lo que de verdad hace falta para navegar con el teclado.
* **El boton primario se materializa.** El apartado 9.2.3 lo convierte en el
  mecanismo central del asistente: el boton no existe hasta que la pagina es
  satisfacible. Nace ocupando ya su hueco de layout pero sin pintarse y
  transparente al raton, de modo que al aparecer nada se recoloca.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence

from PySide6.QtCore import (QEasingCurve, QEvent, QMarginsF, QPoint, QRectF,
                            QSize, Qt, Signal)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLineEdit, QSizePolicy, QWidget

from .. import glass, theme, tipo
from ..motion import (EASE_EXIT, EASE_GLASS, EASE_LIFT, ELEMENT, MICRO_IN,
                      MICRO_OUT, Spring, dur, ease)
from ..tokens import R_FULL, R_SM, ROW_GAP, ROW_HEIGHT, Ink, Tokens
from .base import Beating, Sheet, ThemeAware

__all__ = [
    "Phase", "Toggle", "Button", "Slider", "Segmented", "Field", "SettingRow",
    "Chip", "DISABLED_ALPHA", "RING", "BIRTH_MS", "BIRTH_RISE",
]

#: Lo que se apaga un mando deshabilitado. No se le cambia el color: se baja la
#: opacidad entera, que es lo unico que funciona igual en los dos temas.
DISABLED_ALPHA = 0.38

#: Hueco que cada mando se guarda alrededor para su anillo de foco. Es el mismo
#: problema que la reserva de sombra de ``Sheet``: Qt recorta al rectangulo del
#: widget, y un anillo pintado en el borde sale con un canto recto.
RING = 4

#: Materializacion del boton primario (9.2.3): opacidad y subida.
BIRTH_MS = 320
BIRTH_RISE = 12.0

#: El color del glifo entrante de un segmento no debe rebotar aunque la pildora
#: si (patron 5.5.9), asi que su cruce es lineal y corto.
EASE_LINEAR = QEasingCurve(QEasingCurve.Type.Linear)
CROSSFADE_MS = 140


# --------------------------------------------------------------------------- #
# el 0->1 con ida y vuelta propias
# --------------------------------------------------------------------------- #

class Phase:
    """Un 0->1 con duracion y curva distintas en cada sentido.

    Avanza con el ``dt`` del ``Beat``, igual que ``Spring``, para poder mezclar
    los dos en la misma lista de ``_moving()``. ``dur()`` va dentro, asi que
    ``reduce_motion`` lo encoge sin que nadie se acuerde.

    ``value`` puede pasarse de 1 cuando la curva de entrada es ``EASE_LIFT``
    (sobrepaso 1.12): eso es exactamente lo que se quiere en una geometria y lo
    que hay que recortar en un alfa, y por eso existe ``alpha``.
    """

    __slots__ = ("_t", "_on", "_in", "_out", "_ci", "_co")

    def __init__(self, ms_in: int = MICRO_IN, ms_out: int = MICRO_OUT,
                 ease_in: QEasingCurve = EASE_LIFT,
                 ease_out: QEasingCurve = EASE_EXIT) -> None:
        self._t = 0.0
        self._on = False
        self._in = ms_in
        self._out = ms_out
        self._ci = ease_in
        self._co = ease_out

    def set(self, on: bool) -> None:
        self._on = bool(on)

    def jump(self, on: bool) -> None:
        self._on = bool(on)
        self._t = 1.0 if self._on else 0.0

    @property
    def on(self) -> bool:
        return self._on

    @property
    def settled(self) -> bool:
        return self._t >= 1.0 if self._on else self._t <= 0.0

    @property
    def value(self) -> float:
        if self._t <= 0.0:
            return 0.0
        if self._t >= 1.0:
            return 1.0
        return ease(self._t, self._ci if self._on else self._co)

    @property
    def alpha(self) -> float:
        return max(0.0, min(1.0, self.value))

    def step(self, dt: float) -> float:
        ms = max(1, dur(self._in if self._on else self._out))
        d = dt * 1000.0 / ms
        self._t = min(1.0, self._t + d) if self._on else max(0.0, self._t - d)
        return self.value


# --------------------------------------------------------------------------- #
# utilidades de pintado compartidas
# --------------------------------------------------------------------------- #

def _ink(hex_color: str, alpha: float) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _soft(hex_color: str, t: Tokens) -> Ink:
    """El relleno tenue de un color de estado, a la razon del acento.

    ``accent_soft`` existe en los tokens pero ``ok``/``warn``/``danger``/``info``
    no tienen version tenue, y hacen falta para los chips. Se toma el alfa del
    acento de cada paleta en vez de escribir uno: en claro es 0.12 y en oscuro
    0.16, y esa diferencia es justo la que evita que en claro parezca sucio.
    """
    return Ink(hex_color, t.color.accent_soft.alpha)


def _brightest(t: Tokens) -> str:
    """La superficie mas clara que tiene la paleta.

    Se elige por luminancia y no con un ``if t.dark`` porque el color que hace
    de "cosa iluminada" cambia de token entre las dos paletas: en oscuro es la
    tinta de texto y en claro el vidrio flotante, que es blanco puro.
    """
    return max((t.glass.float_.solid, t.text.primary), key=glass.luminance)


def _deepest(t: Tokens) -> str:
    """El tono mas hundido de la paleta. Es hacia donde va una pulsacion.

    En oscuro sale el lienzo y en claro la tinta de texto. Escribirlo como
    "hacia el lienzo" dejaba la pulsacion del boton primario **aclarando** en
    claro, o sea al reves que el hover: un boton que se hunde tiene que alejarse
    de la luz en las dos paletas.
    """
    return min((t.canvas.base, t.text.primary), key=glass.luminance)


def _contour(p: QPainter, box: QRectF, radius: float, t: Tokens) -> None:
    """El contorno de un mando pequenyo, con el filo dominante reforzado.

    Es la misma cuenta que ``theme.border_strong`` y por el mismo motivo: el
    filo dominante a su alfa nominal separa dos laminas pero no dibuja el borde
    de un mando. Sin esto, en claro un interruptor apagado o el canal de un
    segmentado desaparecen del todo sobre la lamina blanca (apartado 11.2). No
    es una linea divisoria: es el borde del propio objeto.
    """
    rad = min(box.width(), box.height()) / 2.0 if radius <= R_FULL else radius
    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(glass.qcolor(t.edge.dominant.scaled(1.8)), 1.0))
    p.drawPath(glass.rounded_path(box.adjusted(0.5, 0.5, -0.5, -0.5), rad))
    p.restore()


def _focus_ring(p: QPainter, box: QRectF, radius: float, k: float,
                t: Tokens) -> None:
    """El anillo de acento del foco de teclado.

    Va por fuera del mando y no dentro: dentro se come el filo de la lamina y a
    brillo alto no se distingue de un hover.
    """
    if k <= 0.0:
        return
    r = box.adjusted(-2.5, -2.5, 2.5, 2.5)
    rad = (min(r.width(), r.height()) / 2.0 if radius <= R_FULL
           else radius + 2.5)
    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_ink(t.color.accent, 0.85 * k), 2.0))
    p.drawPath(glass.rounded_path(r, rad))
    p.restore()


# --------------------------------------------------------------------------- #
# base de los mandos que no son una lamina
# --------------------------------------------------------------------------- #

class _Control(ThemeAware, Beating, QWidget):
    """Hover, pulsacion y foco, ya enganchados al latido.

    Lo que un mando redefine es ``_moving()`` (para anadir sus muelles) y
    ``paintEvent``. Nadie vuelve a escribir un ``enterEvent`` ni un ``QTimer``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._cursor_on = Qt.CursorShape.PointingHandCursor
        self.setCursor(self._cursor_on)
        self._hover = Phase()
        self._press = Phase(MICRO_OUT, MICRO_OUT, EASE_GLASS, EASE_EXIT)
        self._focus = Phase(MICRO_IN, MICRO_OUT, EASE_GLASS, EASE_EXIT)

    def _moving(self) -> Iterable:
        return (self._hover, self._press, self._focus)

    def tick(self, dt: float) -> bool:
        busy = False
        for m in self._moving():
            m.step(dt)
            busy = busy or not m.settled
        self.update()
        if not busy:
            self.rest()
        return busy

    # -- estado -------------------------------------------------------------
    def event(self, e) -> bool:
        t = e.type()
        if t == QEvent.Type.HoverEnter:
            self._hover.set(True)
            self.animate()
        elif t == QEvent.Type.HoverLeave:
            self._hover.set(False)
            self.animate()
        return super().event(e)

    def changeEvent(self, e) -> None:                       # noqa: N802
        if e.type() == QEvent.Type.EnabledChange:
            # sin esto un mando deshabilitado bajo el raton se queda con el
            # hover encendido para siempre: Qt deja de mandarle eventos
            if not self.isEnabled():
                self._hover.jump(False)
                self._press.jump(False)
            self.setCursor(self._cursor_on if self.isEnabled()
                           else Qt.CursorShape.ArrowCursor)
            self.update()
        super().changeEvent(e)

    def focusInEvent(self, e) -> None:                      # noqa: N802
        self._focus.set(True)
        self.animate()
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:                     # noqa: N802
        self._focus.set(False)
        self.animate()
        super().focusOutEvent(e)

    def mousePressEvent(self, e) -> None:                   # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press.set(True)
            self.animate()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:                 # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press.set(False)
            self.animate()
            if self.rect().contains(e.position().toPoint()):
                self.activate()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:                     # noqa: N802
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._press.set(True)
            self.animate()
            self.activate()
            self._press.set(False)
            return
        super().keyPressEvent(e)

    def activate(self) -> None:
        """Lo que hace el mando al pulsarse, venga del raton o del teclado."""


# --------------------------------------------------------------------------- #
# 1. Toggle
# --------------------------------------------------------------------------- #

class Toggle(_Control):
    """El interruptor. Es el mando con el que se enciende el motor (8.9).

    La perilla va con ``Spring`` y no con una curva: el usuario puede volver a
    pulsar a mitad del recorrido, y un muelle conserva la velocidad que llevaba
    mientras que una curva reinicia el trayecto y se ve el corte.
    """

    toggled = Signal(bool)

    TRACK_W = 46
    TRACK_H = 26
    KNOB_PAD = 3

    def __init__(self, checked: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = bool(checked)
        self._knob = Spring(1.0 if self._checked else 0.0)
        self.setFixedSize(self.TRACK_W + 2 * RING, self.TRACK_H + 2 * RING)

    def _moving(self) -> Iterable:
        return (*super()._moving(), self._knob)

    # -- API ----------------------------------------------------------------
    def isChecked(self) -> bool:                            # noqa: N802
        return self._checked

    def setChecked(self, value: bool) -> None:              # noqa: N802
        """Pone el estado sin emitir. Es el contrato de ``control_toggle``."""
        if bool(value) == self._checked:
            return
        self._checked = bool(value)
        self._knob.set(1.0 if self._checked else 0.0)
        self.animate()

    def activate(self) -> None:
        self.setChecked(not self._checked)
        self.toggled.emit(self._checked)

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, event) -> None:                    # noqa: N802
        t = theme.C.tokens
        k = max(0.0, min(1.0, self._knob.value))
        box = QRectF(RING, RING, self.TRACK_W, self.TRACK_H)
        rad = self.TRACK_H / 2.0

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(DISABLED_ALPHA)

        # el canal es un rebaje de verdad: la perilla tiene que leerse dentro
        path = glass.paint_sheet(p, box, "E1", R_FULL, shadows=False,
                                 tokens=t,
                                 canvas_origin=self.mapTo(self.window(),
                                                          QPoint(0, 0)))
        p.save()
        p.setClipPath(path)
        if k > 0.0:
            p.fillRect(box, _ink(t.color.accent, k))
        if self._hover.value > 0.0:
            p.fillRect(box, glass.qcolor(
                t.glass.hover.ink.scaled(self._hover.alpha)))
        p.restore()
        _contour(p, box, rad, t)

        # la perilla no cambia de color al encenderse el interruptor: lo que
        # significa es el canal. Con la tinta legible sobre el acento la perilla
        # pasaba de blanca a negra al pulsar y parecia un agujero, no un mando
        knob_hex = _brightest(t)
        d = self.TRACK_H - 2 * self.KNOB_PAD
        travel = self.TRACK_W - 2 * self.KNOB_PAD - d
        # la pulsacion estira la perilla hacia donde va, que es el gesto fisico
        grow = 3.0 * self._press.alpha
        x = box.left() + self.KNOB_PAD + travel * k - (grow if k > 0.5 else 0.0)
        knob = QRectF(x, box.top() + self.KNOB_PAD, d + grow, d)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(knob_hex))
        p.drawRoundedRect(knob, d / 2.0, d / 2.0)

        _focus_ring(p, box, rad, self._focus.alpha, t)
        p.end()


# --------------------------------------------------------------------------- #
# 2. Button
# --------------------------------------------------------------------------- #

class Button(Sheet):
    """El boton, en sus tres variantes.

    * ``primary`` — relleno de acento sobre la lamina. Es el que se materializa.
    * ``normal``  — una lamina E2 que sube a E3 en hover, como una tarjeta.
    * ``ghost``   — ni lamina ni sombra: solo el rotulo, y un lavado al pasar por
      encima. Es el «Restablecer seccion» del apartado 8.7 y el «Salir del
      asistente» del 9.2.6.

    El primario y el normal reservan dentro de si mismos el hueco de su sombra,
    igual que cualquier lamina, asi que se colocan con ``gap_between`` o con
    ``place()`` y **no** con margenes a ojo.
    """

    HEIGHT = 38
    PAD_H = 20

    clicked = Signal()

    def __init__(self, text: str = "", variant: str = "normal",
                 parent: QWidget | None = None, *, born: bool = True) -> None:
        fantasma = variant == "ghost"
        super().__init__(parent, elevation="E1" if fantasma else "E2",
                         radius=R_SM, padding=8, interactive=True,
                         hover_to="E1" if fantasma else "E3")
        self._variant = variant
        self._text = text
        self._press = Phase(MICRO_OUT, MICRO_OUT, EASE_GLASS, EASE_EXIT)
        self._focus = Phase(MICRO_IN, MICRO_OUT, EASE_GLASS, EASE_EXIT)
        # el muelle de la materializacion (9.2.3). Nace ya en 1 cuando el boton
        # nace vivo: asi no hay un fotograma a 0.96 al abrirse la ventana
        self._birth_scale = Spring(1.0)
        self._birth = 1.0 if born else 0.0
        self._born = bool(born)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if not self._born:
            self.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    # -- API ----------------------------------------------------------------
    def text(self) -> str:
        return self._text

    def setText(self, value: str) -> None:                  # noqa: N802
        """Contrato de ``btn_engine`` (8.9): el rotulo cambia en caliente."""
        if value == self._text:
            return
        self._text = value
        self.updateGeometry()
        self.update()

    @property
    def born(self) -> bool:
        return self._born

    def materialize(self) -> None:
        """Aparece: opacidad 0->1 + subida de 12 px + muelle de escala 0.96->1.

        Es el mecanismo del apartado 9.2.3 y la razon de que el asistente se
        sienta como un acompanamiento: el boton no estaba porque la pagina no
        era satisfacible, y aparece en el instante exacto en que lo es.
        """
        if self._born:
            return
        self._born = True
        self._birth = 0.0
        self._birth_scale.jump(0.96)
        self._birth_scale.set(1.0)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.animate()

    # -- geometria ----------------------------------------------------------
    def reserve(self) -> QMarginsF:
        # el fantasma no proyecta sombra, pero su anillo de foco sale 4 px por
        # fuera y Qt lo recortaria contra el borde del widget
        if self._variant == "ghost":
            return QMarginsF(RING, RING, RING, RING)
        return super().reserve()

    def sizeHint(self) -> QSize:                            # noqa: N802
        m = self.reserve()
        ancho = tipo.metrics("body-fuerte").horizontalAdvance(self._text)
        return QSize(int(math.ceil(ancho + 2 * self.PAD_H
                                   + m.left() + m.right())),
                     int(self.HEIGHT + m.top() + m.bottom()))

    def minimumSizeHint(self) -> QSize:                     # noqa: N802
        return self.sizeHint()

    def on_theme(self) -> None:
        super().on_theme()
        self.updateGeometry()                # la metrica del rotulo ha cambiado

    # -- estado -------------------------------------------------------------
    def tick(self, dt: float) -> bool:
        propio = False
        for m in (self._press, self._focus):
            m.step(dt)
            propio = propio or not m.settled
        if self._birth < 1.0:
            self._birth = min(1.0, self._birth + dt * 1000.0 / dur(BIRTH_MS))
            self._birth_scale.step(dt)
            propio = propio or self._birth < 1.0 or not self._birth_scale.settled
        # ``super().tick`` da de baja del latido en cuanto lo suyo se asienta,
        # asi que hay que volver a apuntarse si lo mio sigue vivo
        heredado = super().tick(dt)
        if propio and not self.beating:
            self.animate()
        return heredado or propio

    def focusInEvent(self, e) -> None:                      # noqa: N802
        self._focus.set(True)
        self.animate()
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:                     # noqa: N802
        self._focus.set(False)
        self.animate()
        super().focusOutEvent(e)

    def mousePressEvent(self, e) -> None:                   # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press.set(True)
            self.animate()

    def mouseReleaseEvent(self, e) -> None:                 # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._press.set(False)
        self.animate()
        if self.glass_box().contains(e.position()):
            self.flash()                     # el filo cuenta que se ha pulsado
            self.clicked.emit()

    def keyPressEvent(self, e) -> None:                     # noqa: N802
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.flash()
            self.clicked.emit()
            return
        super().keyPressEvent(e)

    # -- pintado ------------------------------------------------------------
    def _fill(self, t: Tokens) -> QColor:
        """Relleno del primario. El hover aclara y la pulsacion hunde."""
        c = t.color.accent
        if self._lift.value > 0.0:
            c = theme.mix(c, theme.C.primary_hover,
                          max(0.0, min(1.0, self._lift.value)))
        if self._press.value > 0.0:
            c = theme.mix(c, _deepest(t), 0.14 * self._press.alpha)
        return QColor(c)

    def paint_glass(self, painter: QPainter):
        t = theme.C.tokens
        if self._variant == "ghost":
            # sin lamina: el fantasma no es una superficie, es solo un rotulo
            path = glass.rounded_path(self.glass_box(), self._radius)
            k = max(self._lift.value, self._press.alpha * 1.6)
            if k > 0.0:
                painter.fillPath(path, glass.qcolor(
                    t.glass.hover.ink.scaled(max(0.0, min(1.0, k)))))
            return path
        path = super().paint_glass(painter)
        if self._variant == "primary":
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(path.boundingRect(), self._fill(t))
            painter.restore()
        return path

    def paint_content(self, painter: QPainter, rect: QRectF) -> None:
        t = theme.C.tokens
        if self._variant == "primary":
            color = theme.C.primary_text
        elif self._variant == "ghost":
            color = theme.mix(t.text.secondary, t.text.primary,
                              max(0.0, min(1.0, self._lift.value)))
        else:
            color = t.text.primary
        painter.setPen(QColor(color))
        painter.setFont(tipo.font("body-fuerte"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), self._text)

    def paintEvent(self, event) -> None:                    # noqa: N802
        if self._birth <= 0.0:
            return                       # aun no existe: ni un pixel, ni sombra
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(DISABLED_ALPHA)
        if self._birth < 1.0:
            k = ease(self._birth, EASE_GLASS)
            p.setOpacity(p.opacity() * k)
            c = self.glass_box().center()
            s = self._birth_scale.value
            p.translate(0.0, BIRTH_RISE * (1.0 - k))
            p.translate(c)
            p.scale(s, s)
            p.translate(-c)
        path = self.paint_glass(p)
        p.save()
        p.setClipPath(path)
        self.paint_content(p, self.content_rect())
        self._sweep.paint(p, path.boundingRect(), self._radius)
        p.restore()
        _focus_ring(p, self.glass_box(), self._radius, self._focus.alpha,
                    theme.C.tokens)
        p.end()


# --------------------------------------------------------------------------- #
# 3. Slider
# --------------------------------------------------------------------------- #

class Slider(_Control):
    """El deslizador del apartado 8.7, con su instrumentacion.

    Canal E1 de 1 px dentro de un area sensible de 24, marca de 2x16, el valor a
    la derecha en ``mono`` tabular, diez subdivisiones que aparecen al arrastrar
    y una burbuja en ``metric`` sobre el pulgar que se va 400 ms despues de
    soltar.

    El canal no se pinta con ``paint_sheet``: un E1 de 1 px de alto lleva su filo
    invertido a 0.067 de alfa en la paleta clara y desaparece por completo sobre
    una lamina blanca. Se pinta con el filo dominante reforzado, que es la misma
    cuenta que hace ``theme.border_strong`` y por el mismo motivo.
    """

    valueChanged = Signal(float)
    released = Signal()

    AREA_H = 24
    BUBBLE_H = 44
    MARK_W = 2
    MARK_H = 16
    TICKS = 10
    TICK_H = 6
    HOLD_MS = 400.0

    def __init__(self, minimum: float = 0.0, maximum: float = 1.0,
                 value: float = 0.0, *, step: float = 0.0,
                 decimals: int = 2, unit: str = "",
                 fmt: Callable[[float], str] | None = None,
                 bubble: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._min = float(minimum)
        self._max = max(float(maximum), float(minimum) + 1e-6)
        self._step = float(step)
        self._decimals = int(decimals)
        self._unit = unit
        self._fmt = fmt
        self._bubble_on = bool(bubble)
        self._value = self._clamp(float(value))
        self._drag = False
        self._hold = 0.0
        self._subs = Phase(MICRO_IN, MICRO_IN, EASE_GLASS, EASE_EXIT)
        self._bubble = Phase(MICRO_IN, ELEMENT, EASE_GLASS, EASE_EXIT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.AREA_H + 2 * RING
                            + (self.BUBBLE_H if bubble else 0))

    def _moving(self) -> Iterable:
        return (*super()._moving(), self._subs, self._bubble)

    # -- API ----------------------------------------------------------------
    def value(self) -> float:
        return self._value

    def setValue(self, value: float) -> None:               # noqa: N802
        v = self._clamp(float(value))
        if abs(v - self._value) < 1e-9:
            return
        self._value = v
        self.update()

    def format(self, value: float | None = None) -> str:
        v = self._value if value is None else value
        if self._fmt is not None:
            return self._fmt(v)
        return f"{v:.{self._decimals}f}{self._unit}"

    def _clamp(self, v: float) -> float:
        v = max(self._min, min(self._max, v))
        if self._step > 0.0:
            v = self._min + round((v - self._min) / self._step) * self._step
        return max(self._min, min(self._max, v))

    @property
    def _fraction(self) -> float:
        return (self._value - self._min) / (self._max - self._min)

    # -- geometria ----------------------------------------------------------
    def _value_width(self) -> float:
        """Ancho reservado al readout. Se mide con el texto mas ancho posible.

        Medir el valor actual dejaba el canal cambiando de largo mientras
        arrastras, que es exactamente lo que la cifra tabular viene a evitar.
        """
        m = tipo.metrics("mono")
        return max(m.horizontalAdvance(self.format(self._min)),
                   m.horizontalAdvance(self.format(self._max))) + 2.0

    def sizeHint(self) -> QSize:                            # noqa: N802
        # el ancho es orientativo (el deslizador se estira), pero el alto no:
        # de el sale la altura de la fila de ajustes que lo contiene
        return QSize(240, self.height())

    def _channel(self) -> QRectF:
        top = RING + (self.BUBBLE_H if self._bubble_on else 0)
        ancho = self.width() - 2 * RING - self._value_width() - ROW_GAP
        return QRectF(RING, top, max(24.0, ancho), self.AREA_H)

    def _x_of(self, fraction: float) -> float:
        c = self._channel()
        return c.left() + self.MARK_W / 2.0 + (c.width() - self.MARK_W) * fraction

    def _value_at(self, x: float) -> float:
        c = self._channel()
        span = max(1.0, c.width() - self.MARK_W)
        f = (x - c.left() - self.MARK_W / 2.0) / span
        return self._min + (self._max - self._min) * max(0.0, min(1.0, f))

    # -- interaccion --------------------------------------------------------
    def mousePressEvent(self, e) -> None:                   # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._drag = True
        self._subs.set(True)
        self._bubble.set(True)
        self._press.set(True)
        self._emit(self._value_at(e.position().x()))
        self.animate()

    def mouseMoveEvent(self, e) -> None:                    # noqa: N802
        if self._drag:
            self._emit(self._value_at(e.position().x()))

    def mouseReleaseEvent(self, e) -> None:                 # noqa: N802
        if not self._drag:
            return
        self._drag = False
        self._press.set(False)
        self._subs.set(False)
        # la burbuja no se va al soltar: se queda 400 ms para que puedas leer
        # el valor que acabas de fijar sin perseguirla con la vista
        self._hold = self.HOLD_MS
        self.animate()
        self.released.emit()

    def keyPressEvent(self, e) -> None:                     # noqa: N802
        paso = self._step if self._step > 0.0 else (self._max - self._min) / 100.0
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self._emit(self._value - paso)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self._emit(self._value + paso)
        elif k == Qt.Key.Key_Home:
            self._emit(self._min)
        elif k == Qt.Key.Key_End:
            self._emit(self._max)
        else:
            super().keyPressEvent(e)
            return
        self._bubble.set(True)
        self._hold = self.HOLD_MS
        self.animate()

    def _emit(self, raw: float) -> None:
        v = self._clamp(raw)
        if abs(v - self._value) < 1e-9:
            return
        self._value = v
        self.update()
        self.valueChanged.emit(v)

    def tick(self, dt: float) -> bool:
        esperando = self._hold > 0.0
        if esperando:
            self._hold = max(0.0, self._hold - dt * 1000.0)
            if self._hold <= 0.0 and not self._drag:
                self._bubble.set(False)
        busy = super().tick(dt)          # da de baja del latido si ya no anima
        if esperando and not self.beating:
            self.animate()               # la cuenta de los 400 ms sigue viva
        return busy or esperando

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, event) -> None:                    # noqa: N802
        t = theme.C.tokens
        c = self._channel()
        cy = c.center().y()
        x = self._x_of(self._fraction)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(DISABLED_ALPHA)
        p.setPen(Qt.PenStyle.NoPen)

        # canal y recorrido cubierto
        p.fillRect(QRectF(c.left(), cy - 0.5, c.width(), 1.0),
                   glass.qcolor(t.edge.dominant.scaled(2.0)))
        p.fillRect(QRectF(c.left(), cy - 0.5, x - c.left(), 1.0),
                   QColor(t.color.accent))

        # subdivisiones: solo mientras arrastras, y por debajo del canal
        if self._subs.value > 0.0:
            p.setBrush(_ink(t.text.quiet, self._subs.alpha))
            for i in range(self.TICKS + 1):
                tx = self._x_of(i / self.TICKS)
                p.drawRect(QRectF(tx - 0.5, cy + 4.0, 1.0, self.TICK_H))

        # la marca. Cromo monocromo: el color lo lleva el recorrido cubierto
        p.setBrush(QColor(t.text.primary))
        mark = QRectF(x - self.MARK_W / 2.0, cy - self.MARK_H / 2.0,
                      self.MARK_W, self.MARK_H)
        crece = 2.0 * max(self._hover.alpha, self._press.alpha)
        mark.adjust(0.0, -crece, 0.0, crece)
        p.drawRoundedRect(mark, 1.0, 1.0)

        # readout a la derecha, tabular para que no baile al arrastrar
        p.setPen(QColor(t.text.secondary))
        p.setFont(tipo.font("mono"))
        p.drawText(QRectF(c.right() + ROW_GAP, c.top(),
                          self._value_width(), c.height()),
                   int(Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter),
                   self.format())

        if self._bubble_on and self._bubble.value > 0.0:
            p.setOpacity(p.opacity() * self._bubble.alpha)
            p.setPen(QColor(t.text.primary))
            p.setFont(tipo.font("metric"))
            ancho = 160.0
            p.drawText(QRectF(x - ancho / 2.0, RING, ancho, self.BUBBLE_H),
                       int(Qt.AlignmentFlag.AlignCenter), self.format())
            p.setOpacity(1.0 if self.isEnabled() else DISABLED_ALPHA)

        _focus_ring(p, c, R_SM, self._focus.alpha, t)
        p.end()


# --------------------------------------------------------------------------- #
# 4. Segmented
# --------------------------------------------------------------------------- #

class Segmented(_Control):
    """Selector de una opcion entre pocas: el rango de la pagina de analisis.

    La pildora viaja con ``Spring`` e **interpola tambien su anchura** a la del
    rotulo de destino (patron 5.5.9). El color del texto cruza aparte, lineal y
    en 140 ms: si el color rebotase con la pildora, el rotulo parpadearia.
    """

    changed = Signal(int)

    HEIGHT = 32
    PAD_H = 16

    def __init__(self, options: Sequence[str], index: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options = list(options)
        self._index = max(0, min(len(self._options) - 1, int(index)))
        self._x = Spring(0.0, eps=0.25)
        self._w = Spring(0.0, eps=0.25)
        self._cross = [Phase(CROSSFADE_MS, CROSSFADE_MS,
                             EASE_LINEAR, EASE_LINEAR)
                       for _ in self._options]
        for i, ph in enumerate(self._cross):
            ph.jump(i == self._index)
        self.setFixedHeight(self.HEIGHT + 2 * RING)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _moving(self) -> Iterable:
        return (*super()._moving(), self._x, self._w, *self._cross)

    # -- API ----------------------------------------------------------------
    def index(self) -> int:
        return self._index

    def setIndex(self, i: int, *, emit: bool = False) -> None:   # noqa: N802
        i = max(0, min(len(self._options) - 1, int(i)))
        if i == self._index:
            return
        self._index = i
        for j, ph in enumerate(self._cross):
            ph.set(j == i)
        self._retarget()
        self.animate()
        if emit:
            self.changed.emit(i)

    # -- geometria ----------------------------------------------------------
    def _widths(self) -> list[float]:
        m = tipo.metrics("caption")
        return [m.horizontalAdvance(tipo.text("caption", o)) + 2 * self.PAD_H
                for o in self._options]

    def _spans(self) -> list[tuple[float, float]]:
        x = float(RING)
        out: list[tuple[float, float]] = []
        for w in self._widths():
            out.append((x, w))
            x += w
        return out

    def sizeHint(self) -> QSize:                            # noqa: N802
        return QSize(int(math.ceil(sum(self._widths()))) + 2 * RING,
                     self.HEIGHT + 2 * RING)

    def minimumSizeHint(self) -> QSize:                     # noqa: N802
        return self.sizeHint()

    def _retarget(self) -> None:
        x, w = self._spans()[self._index]
        self._x.set(x)
        self._w.set(w)

    def showEvent(self, e) -> None:                         # noqa: N802
        # al mostrarse por primera vez la pildora tiene que estar ya puesta: si
        # arrancase en 0 se veria salir disparada desde el borde izquierdo
        if self._w.value <= 0.0:
            x, w = self._spans()[self._index]
            self._x.jump(x)
            self._w.jump(w)
        super().showEvent(e)

    def on_theme(self) -> None:
        self._retarget()
        self.updateGeometry()
        self.update()

    # -- interaccion --------------------------------------------------------
    def _at(self, x: float) -> int:
        for i, (sx, w) in enumerate(self._spans()):
            if sx <= x < sx + w:
                return i
        return self._index

    def mousePressEvent(self, e) -> None:                   # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.setIndex(self._at(e.position().x()), emit=True)

    def keyPressEvent(self, e) -> None:                     # noqa: N802
        if e.key() == Qt.Key.Key_Left:
            self.setIndex(self._index - 1, emit=True)
        elif e.key() == Qt.Key.Key_Right:
            self.setIndex(self._index + 1, emit=True)
        else:
            super().keyPressEvent(e)

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, event) -> None:                    # noqa: N802
        t = theme.C.tokens
        box = QRectF(RING, RING, self.width() - 2 * RING, self.HEIGHT)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(DISABLED_ALPHA)

        path = glass.paint_sheet(p, box, "E1", R_FULL, shadows=False, tokens=t,
                                 canvas_origin=self.mapTo(self.window(),
                                                          QPoint(0, 0)))
        p.save()
        p.setClipPath(path)
        # la pildora se rellena plana con el lavado del nivel alzado: recortar
        # el lienzo aqui la dejaria mas oscura que el canal que la contiene
        pill = QRectF(self._x.value, box.top() + 3.0,
                      max(0.0, self._w.value), box.height() - 6.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glass.qcolor(t.glass.raised.ink))
        p.drawRoundedRect(pill, pill.height() / 2.0, pill.height() / 2.0)
        p.setPen(QPen(glass.qcolor(t.edge.light), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5),
                          pill.height() / 2.0, pill.height() / 2.0)
        p.restore()
        _contour(p, box, R_FULL, t)

        p.setFont(tipo.font("caption"))
        for i, ((sx, w), opt) in enumerate(zip(self._spans(), self._options)):
            k = self._cross[i].alpha
            p.setPen(QColor(theme.mix(t.text.secondary, t.text.primary, k)))
            p.drawText(QRectF(sx, box.top(), w, box.height()),
                       int(Qt.AlignmentFlag.AlignCenter),
                       tipo.text("caption", opt))

        _focus_ring(p, box, R_FULL, self._focus.alpha, t)
        p.end()


# --------------------------------------------------------------------------- #
# 5. Field
# --------------------------------------------------------------------------- #

class Field(ThemeAware, QWidget):
    """Campo de texto: el buscador de Ajustes y poco mas.

    Es un ``QLineEdit`` dentro de un rebaje pintado por ``glass.py``. El
    ``QLineEdit`` va con fondo y borde a cero y solo se le dan colores: la
    tipografia sale de ``tipo.py`` como en todo lo demas, porque Qt ignora la
    mitad de las propiedades tipograficas de una hoja de estilo.

    No hereda de ``_Control`` porque quien tiene el foco es el hijo, no el
    contenedor, y duplicar el estado en los dos acaba en un anillo que se queda
    encendido.
    """

    HEIGHT = 38
    PAD_H = 14

    textChanged = Signal(str)
    returnPressed = Signal()

    def __init__(self, placeholder: str = "", text: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._edit = QLineEdit(text, self)
        self._edit.setFrame(False)
        self._edit.setPlaceholderText(placeholder)
        self._edit.setAttribute(
            Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self._edit.textChanged.connect(self.textChanged.emit)
        self._edit.returnPressed.connect(self.returnPressed.emit)
        self._edit.installEventFilter(self)
        self.setFixedHeight(self.HEIGHT + 2 * RING)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusProxy(self._edit)
        self.on_theme()

    # -- API ----------------------------------------------------------------
    def text(self) -> str:
        return self._edit.text()

    def setText(self, value: str) -> None:                  # noqa: N802
        self._edit.setText(value)

    def setPlaceholderText(self, value: str) -> None:       # noqa: N802
        self._edit.setPlaceholderText(value)

    def clear(self) -> None:
        self._edit.clear()

    # -- estado -------------------------------------------------------------
    def eventFilter(self, obj, e) -> bool:                  # noqa: N802
        if obj is self._edit and e.type() in (QEvent.Type.FocusIn,
                                              QEvent.Type.FocusOut):
            self.update()
        return super().eventFilter(obj, e)

    def on_theme(self) -> None:
        t = theme.C.tokens
        self._edit.setFont(tipo.font("body"))
        self._edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none;"
            f" color: {t.text.primary};"
            f" selection-background-color: {t.color.accent_soft.css()};"
            f" selection-color: {t.text.primary}; }}")
        self.update()

    def resizeEvent(self, e) -> None:                       # noqa: N802
        self._edit.setGeometry(RING + self.PAD_H, RING,
                               max(0, self.width() - 2 * (RING + self.PAD_H)),
                               self.HEIGHT)
        super().resizeEvent(e)

    def paintEvent(self, event) -> None:                    # noqa: N802
        t = theme.C.tokens
        box = QRectF(RING, RING, self.width() - 2 * RING, self.HEIGHT)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(DISABLED_ALPHA)
        glass.paint_sheet(p, box, "E1", R_SM, shadows=False, tokens=t,
                          canvas_origin=self.mapTo(self.window(), QPoint(0, 0)))
        _contour(p, box, R_SM, t)
        _focus_ring(p, box, R_SM, 1.0 if self._edit.hasFocus() else 0.0, t)
        p.end()


# --------------------------------------------------------------------------- #
# 6. SettingRow
# --------------------------------------------------------------------------- #

class SettingRow(ThemeAware, Beating, QWidget):
    """Una fila de Ajustes: rotulo, consecuencia y mando.

    Dos cosas que no son decorativas:

    * ``keywords`` — el buscador en vivo del apartado 8.7 filtra por aqui. Sin
      palabras clave, buscar "raton" no encuentra la fila "Suavizado del
      puntero", que es justo lo que el usuario acaba de escribir.
    * ``set_modified`` — el punto de acento de 4 px en el borde izquierdo dice
      que esa fila ya no esta en su valor por defecto. Es la unica manera de que
      "3 modificados" y «Restablecer seccion» signifiquen algo.
    """

    DOT = 4
    PAD_L = 12

    def __init__(self, label: str, control: QWidget, *, hint: str = "",
                 keywords: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self.hint = hint
        self.keywords = keywords
        self.control = control
        control.setParent(self)
        self._modified = Phase(ELEMENT, MICRO_OUT, EASE_LIFT, EASE_EXIT)
        alto = max(ROW_HEIGHT, control.sizeHint().height())
        self.setFixedHeight(int(alto))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # -- API ----------------------------------------------------------------
    def set_modified(self, value: bool) -> None:
        if bool(value) == self._modified.on:
            return
        self._modified.set(bool(value))
        self.animate()

    @property
    def modified(self) -> bool:
        return self._modified.on

    def matches(self, query: str) -> bool:
        """Filtro del buscador. Vacio casa con todo: la lista no se vacia sola."""
        q = query.strip().lower()
        if not q:
            return True
        heno = f"{self.label} {self.hint} {self.keywords}".lower()
        return all(palabra in heno for palabra in q.split())

    def tick(self, dt: float) -> bool:
        self._modified.step(dt)
        self.update()
        if self._modified.settled:
            self.rest()
            return False
        return True

    # -- geometria ----------------------------------------------------------
    def resizeEvent(self, e) -> None:                       # noqa: N802
        s = self.control.sizeHint()
        ancho = (self.width() // 2 if s.width() <= 0 else s.width())
        self.control.setGeometry(self.width() - ancho,
                                 (self.height() - s.height()) // 2,
                                 ancho, s.height())
        super().resizeEvent(e)

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, event) -> None:                    # noqa: N802
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(DISABLED_ALPHA)

        k = self._modified.value
        if k > 0.0:
            d = self.DOT * max(0.0, min(1.2, k))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.color.accent))
            p.drawEllipse(QRectF(0.0, (self.height() - d) / 2.0, d, d))

        x = self.PAD_L
        ancho = max(40.0, self.control.x() - x - ROW_GAP)
        if self.hint:
            m = tipo.metrics("body")
            p.setPen(QColor(t.text.primary))
            p.setFont(tipo.font("body"))
            p.drawText(QRectF(x, self.height() / 2.0 - m.height() - 1.0,
                              ancho, m.height()),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter), self.label)
            p.setPen(QColor(t.text.tertiary))
            p.setFont(tipo.font("caption"))
            p.drawText(QRectF(x, self.height() / 2.0 + 1.0, ancho,
                              tipo.metrics("caption").height()),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter), self.hint)
        else:
            p.setPen(QColor(t.text.primary))
            p.setFont(tipo.font("body"))
            p.drawText(QRectF(x, 0.0, ancho, self.height()),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter), self.label)
        p.end()


# --------------------------------------------------------------------------- #
# 7. Chip
# --------------------------------------------------------------------------- #

class Chip(_Control):
    """Etiqueta diminuta: "ahorro" en la barra inferior, un gesto reconocido.

    Con ``checkable`` se marca y se desmarca, y al marcarse da el pop de
    ``Spring`` del patron "chip que se marca". El tono no es decorativo: nombra
    un estado (``ok``, ``warn``, ``danger``, ``info``, ``accent``), y el neutro
    -que es el normal- se queda estrictamente monocromo.
    """

    toggled = Signal(bool)
    clicked = Signal()

    HEIGHT = 24
    PAD_H = 10

    def __init__(self, text: str = "", tone: str = "neutral", *,
                 checkable: bool = False, checked: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._tone = tone
        self._checkable = bool(checkable)
        self._checked = bool(checked) and self._checkable
        self._pop = Spring(1.0)
        self.setFixedHeight(self.HEIGHT + 2 * RING)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if not self._checkable:
            # un chip que no se marca es una etiqueta, no un mando: ni foco de
            # teclado ni cursor de mano prometiendo algo que no va a pasar
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._cursor_on = Qt.CursorShape.ArrowCursor
            self.setCursor(self._cursor_on)

    def _moving(self) -> Iterable:
        return (*super()._moving(), self._pop)

    # -- API ----------------------------------------------------------------
    def text(self) -> str:
        return self._text

    def setText(self, value: str) -> None:                  # noqa: N802
        if value == self._text:
            return
        self._text = value
        self.updateGeometry()
        self.update()

    def isChecked(self) -> bool:                            # noqa: N802
        return self._checked

    def setChecked(self, value: bool) -> None:              # noqa: N802
        if not self._checkable or bool(value) == self._checked:
            return
        self._checked = bool(value)
        if self._checked:
            self._pop.jump(0.90)
            self._pop.set(1.0)
        self.animate()

    def activate(self) -> None:
        if self._checkable:
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)
        self.clicked.emit()

    # -- geometria ----------------------------------------------------------
    def sizeHint(self) -> QSize:                            # noqa: N802
        ancho = tipo.metrics("caption").horizontalAdvance(
            tipo.text("caption", self._text))
        return QSize(int(math.ceil(ancho + 2 * self.PAD_H)) + 2 * RING,
                     self.HEIGHT + 2 * RING)

    def minimumSizeHint(self) -> QSize:                     # noqa: N802
        return self.sizeHint()

    def on_theme(self) -> None:
        self.updateGeometry()
        self.update()

    def _color(self, t: Tokens) -> str:
        if self._tone == "neutral":
            return t.text.secondary
        if self._tone == "accent":
            return t.color.accent
        return getattr(t.color, self._tone, t.text.secondary)

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, event) -> None:                    # noqa: N802
        t = theme.C.tokens
        color = self._color(t)
        encendido = self._checked or self._tone != "neutral"

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(DISABLED_ALPHA)

        box = QRectF(RING, RING, self.width() - 2 * RING, self.HEIGHT)
        s = max(0.0, min(1.2, self._pop.value))
        if s != 1.0:
            c = box.center()
            p.translate(c)
            p.scale(s, s)
            p.translate(-c)
        rad = box.height() / 2.0

        relleno = (glass.qcolor(_soft(color, t)) if encendido
                   else glass.qcolor(t.glass.sunken.ink))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(relleno)
        p.drawRoundedRect(box, rad, rad)
        if self._hover.value > 0.0:
            p.setBrush(glass.qcolor(
                t.glass.hover.ink.scaled(self._hover.alpha)))
            p.drawRoundedRect(box, rad, rad)
        # el filo del chip: en claro el relleno tenue solo no lo separa de la
        # lamina blanca sobre la que vive
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_ink(color if encendido else t.edge.dominant.hex,
                           0.35 if encendido else t.edge.dominant.alpha * 2.0),
                      1.0))
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)

        p.setPen(QColor(color if encendido else t.text.secondary))
        p.setFont(tipo.font("caption"))
        p.drawText(box, int(Qt.AlignmentFlag.AlignCenter),
                   tipo.text("caption", self._text))

        _focus_ring(p, box, R_FULL, self._focus.alpha, t)
        p.end()
