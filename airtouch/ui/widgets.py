"""Componentes de interfaz de AirTouch.

Todos los widgets pintados a mano leen ``theme.C`` dentro de ``paintEvent`` y
se repintan solos al cambiar de tema, asi que claro y oscuro salen gratis.
"""
from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import (
    Property, QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QSizePolicy,
    QSlider, QVBoxLayout, QWidget,
)

from . import theme
from .anim import EASE_OUT, FAST, NORMAL, Smooth, tween


def _themed(widget: QWidget) -> None:
    """Repinta el widget cuando cambia el tema.

    La suscripcion se cancela sola al destruirse el widget: si no, la senal
    seguiria apuntando a un objeto C++ ya borrado y reventaria.
    """

    def _repaint(_name: str) -> None:
        try:
            widget.update()
        except RuntimeError:            # el objeto C++ ya no existe
            pass

    theme.signals.changed.connect(_repaint)

    def _unsubscribe(*_a) -> None:
        theme.unsubscribe(_repaint)

    widget.destroyed.connect(_unsubscribe)


def label(text: str, role: str = "", wrap: bool = True) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb


def title_block(title: str, subtitle: str = "") -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    t = label(title, "h1", wrap=False)
    lay.addWidget(t)
    if subtitle:
        s = label(subtitle, "dim")
        lay.addWidget(s)
    return box


# --------------------------------------------------------------------- tarjeta
class Card(QFrame):
    """Contenedor con superficie, borde y sombra suave."""

    def __init__(self, title: str = "", subtitle: str = "",
                 parent: QWidget | None = None, compact: bool = False) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        self.body = QVBoxLayout(self)
        m = 16 if compact else 20
        self.body.setContentsMargins(m, m - 2, m, m - 2)
        self.body.setSpacing(10)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(26)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(4)
        self._refresh_shadow()
        self.setGraphicsEffect(self._shadow)
        theme.signals.changed.connect(self._refresh_shadow)
        self.destroyed.connect(self._drop_theme_hook)

        if title:
            head = QHBoxLayout()
            head.setSpacing(10)
            box = QVBoxLayout()
            box.setSpacing(2)
            box.setContentsMargins(0, 0, 0, 0)
            self.title_label = label(title, "h2", wrap=False)
            box.addWidget(self.title_label)
            if subtitle:
                self.subtitle_label = label(subtitle, "faint")
                box.addWidget(self.subtitle_label)
            head.addLayout(box, 1)
            self.header_extra = QHBoxLayout()
            self.header_extra.setSpacing(8)
            head.addLayout(self.header_extra)
            self.body.addLayout(head)

    def _refresh_shadow(self, *_a) -> None:
        try:
            self._shadow.setColor(QColor(0, 0, 0, 90 if theme.C.dark else 26))
        except RuntimeError:
            pass

    def _drop_theme_hook(self, *_a) -> None:
        theme.unsubscribe(self._refresh_shadow)

    def add(self, w: QWidget) -> QWidget:
        self.body.addWidget(w)
        return w

    def add_layout(self, lay) -> None:
        self.body.addLayout(lay)

    def add_action(self, w: QWidget) -> QWidget:
        self.header_extra.addWidget(w)
        return w


class Hr(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "sep")
        self.setFixedHeight(1)


# ------------------------------------------------------------------ indicador
class Dot(QWidget):
    """Punto de estado. Puede latir para llamar la atencion."""

    def __init__(self, token: str = "text_faint", size: int = 10,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # se acepta tanto un token del tema ("ok") como un color literal
        self._token = "text_faint" if token.startswith("#") else token
        self._override: str | None = token if token.startswith("#") else None
        self._size = size
        self._pulse = 0.0
        self._pulsing = False
        self.setFixedSize(size + 10, size + 10)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        _themed(self)

    def set_token(self, token: str) -> None:
        self._token, self._override = token, None
        self.update()

    def set_color(self, color: str) -> None:
        self._override = color
        self.update()

    def set_pulsing(self, on: bool) -> None:
        if on == self._pulsing:
            return
        self._pulsing = on
        if on:
            self._timer.start()
        else:
            self._timer.stop()
            self._pulse = 0.0
        self.update()

    def _tick(self) -> None:
        self._pulse = (time.perf_counter() * 1.5) % 1.0
        self.update()

    def _color(self) -> QColor:
        return QColor(self._override or getattr(theme.C, self._token))

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col = self._color()
        cx, cy = self.width() / 2, self.height() / 2
        r = self._size / 2

        if self._pulsing:
            t = self._pulse
            halo = QColor(col)
            halo.setAlpha(int(90 * (1.0 - t)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QPointF(cx, cy), r + t * (r + 5), r + t * (r + 5))

        glow = QColor(col)
        glow.setAlpha(58)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), r + 3.2, r + 3.2)
        p.setBrush(col)
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


class Badge(QWidget):
    """Etiqueta redondeada de estado."""

    def __init__(self, text: str = "", token: str = "text_dim",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._token = token
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        _themed(self)

    def set(self, text: str, token: str = "text_dim") -> None:
        if (text, token) == (self._text, self._token):
            return
        self._text, self._token = text, token
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self._text) + 24, fm.height() + 11)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col = QColor(getattr(theme.C, self._token))
        bg = QColor(col)
        bg.setAlpha(38 if theme.C.dark else 30)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        border = QColor(col)
        border.setAlpha(80)
        p.setPen(QPen(border, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        f = self.font()
        f.setPointSizeF(max(8.0, f.pointSizeF() - 1))
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(col)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


# ------------------------------------------------------------------- toggle
class Toggle(QWidget):
    """Interruptor deslizante."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(48, 27)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = checked
        self._pos = 1.0 if checked else 0.0
        self._hover = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        _themed(self)

    def isChecked(self) -> bool:  # noqa: N802
        return self._checked

    def setChecked(self, value: bool) -> None:  # noqa: N802
        if value == self._checked:
            return
        self._checked = value
        tween(self._pos, 1.0 if value else 0.0, 170, self._set_knob, self)

    def _set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, lambda self: self._pos, _set_knob)

    def event(self, ev) -> bool:
        if ev.type() == QEvent.Type.HoverEnter:
            tween(self._hover, 1.0, FAST, self._set_hover, self)
        elif ev.type() == QEvent.Type.HoverLeave:
            tween(self._hover, 0.0, FAST, self._set_hover, self)
        return super().event(ev)

    def _set_hover(self, v: float) -> None:
        self._hover = v
        self.update()

    def mousePressEvent(self, _ev) -> None:  # noqa: N802
        self.setChecked(not self._checked)
        self.toggled.emit(self._checked)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        off = QColor(c.track)
        on = QColor(c.ok)
        t = self._pos
        track = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)

        if self._hover > 0.01:
            ring = QColor(c.ok if self._checked else c.text_faint)
            ring.setAlpha(int(55 * self._hover))
            p.setPen(QPen(ring, 3.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5),
                              r.height() / 2 + 2, r.height() / 2 + 2)

        d = r.height() - 5
        x = r.x() + 2.5 + t * (r.width() - d - 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, r.y() + 2.5, d, d))
        p.end()


class SegmentedControl(QWidget):
    """Selector de pocas opciones con pastilla deslizante."""

    changed = Signal(int)

    def __init__(self, options: list[str], index: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.options = options
        self._index = index
        self._pill = Smooth(float(index), 0.10)
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        fm = self.fontMetrics()
        widest = max((fm.horizontalAdvance(o) for o in options), default=40)
        self.setMinimumWidth((widest + 22) * len(options))
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        _themed(self)

    def index(self) -> int:
        return self._index

    def set_index(self, i: int, emit: bool = False) -> None:
        i = max(0, min(len(self.options) - 1, i))
        if i == self._index:
            return
        self._index = i
        self._pill.set(float(i))
        self._timer.start()
        self.update()
        if emit:
            self.changed.emit(i)

    def _tick(self) -> None:
        self._pill.step()
        self.update()
        if self._pill.settled:
            self._timer.stop()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        w = self.width() / max(len(self.options), 1)
        self.set_index(int(ev.position().x() // w), emit=True)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c.surface_sunken))
        p.drawRoundedRect(r, 11, 11)
        p.setPen(QPen(QColor(c.border), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 11, 11)

        n = max(len(self.options), 1)
        w = r.width() / n
        pill = QRectF(3 + self._pill.value * w, 3, w - 6, r.height() - 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c.surface))
        p.drawRoundedRect(pill, 9, 9)
        p.setPen(QPen(QColor(c.border_strong), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill, 9, 9)

        f = self.font()
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        for i, text in enumerate(self.options):
            cell = QRectF(i * w, 0, w, r.height())
            active = abs(self._pill.value - i) < 0.5
            p.setPen(QColor(c.text if active else c.text_dim))
            p.drawText(cell, Qt.AlignmentFlag.AlignCenter, text)
        p.end()


# ------------------------------------------------------------------ metricas
class Sparkline(QWidget):
    """Historial reciente de un valor, como linea suavizada con relleno."""

    def __init__(self, capacity: int = 90, token: str = "accent",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values: deque[float] = deque(maxlen=capacity)
        self.token = token
        self.lo: float | None = None
        self.hi: float | None = None
        self.setMinimumHeight(38)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        _themed(self)

    def push(self, value: float) -> None:
        self.values.append(float(value))
        self.update()

    def clear(self) -> None:
        self.values.clear()
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 3, -1, -3)

        if len(self.values) < 2:
            p.setPen(QPen(QColor(c.border), 1.0, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(r.left(), r.center().y()),
                       QPointF(r.right(), r.center().y()))
            p.end()
            return

        vals = list(self.values)
        lo = self.lo if self.lo is not None else min(vals)
        hi = self.hi if self.hi is not None else max(vals)
        if hi - lo < 1e-6:
            hi = lo + 1.0

        n = len(vals)
        step = r.width() / max(n - 1, 1)

        def pt(i: int) -> QPointF:
            v = (vals[i] - lo) / (hi - lo)
            v = max(0.0, min(1.0, v))
            return QPointF(r.left() + i * step, r.bottom() - v * r.height())

        path = QPainterPath(pt(0))
        for i in range(1, n):
            a, b = pt(i - 1), pt(i)
            cx = (a.x() + b.x()) / 2
            path.cubicTo(QPointF(cx, a.y()), QPointF(cx, b.y()), b)

        fill = QPainterPath(path)
        fill.lineTo(r.right(), r.bottom())
        fill.lineTo(r.left(), r.bottom())
        fill.closeSubpath()

        base = QColor(getattr(c, self.token))
        grad = QLinearGradient(0, r.top(), 0, r.bottom())
        top = QColor(base)
        top.setAlpha(70 if c.dark else 46)
        bottom = QColor(base)
        bottom.setAlpha(0)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawPath(fill)

        pen = QPen(base, 1.9)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        last = pt(n - 1)
        p.setPen(Qt.PenStyle.NoPen)
        halo = QColor(base)
        halo.setAlpha(70)
        p.setBrush(halo)
        p.drawEllipse(last, 5.0, 5.0)
        p.setBrush(base)
        p.drawEllipse(last, 2.6, 2.6)
        p.end()


class StatTile(QWidget):
    """Metrica grande con unidad, etiqueta y grafico opcional."""

    def __init__(self, caption: str, unit: str = "", spark: bool = False,
                 token: str = "accent", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unit = unit
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self.caption = label(caption.upper(), "h3", wrap=False)
        lay.addWidget(self.caption)

        row = QHBoxLayout()
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)
        self.value = label("—", "metric", wrap=False)
        row.addWidget(self.value)
        self.unit = label(unit, "faint", wrap=False)
        self.unit.setAlignment(Qt.AlignmentFlag.AlignLeft |
                               Qt.AlignmentFlag.AlignBottom)
        row.addWidget(self.unit)
        row.addStretch(1)
        lay.addLayout(row)

        self.spark = Sparkline(token=token) if spark else None
        if self.spark is not None:
            lay.addWidget(self.spark)

    def set(self, value: str, token: str | None = None) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(
            f"color: {getattr(theme.C, token)};" if token else "")

    def push(self, raw: float) -> None:
        if self.spark is not None:
            self.spark.push(raw)


class StatRow(QWidget):
    """Fila etiqueta / valor."""

    def __init__(self, name: str, value: str = "—",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 3, 0, 3)
        self.name = label(name, "dim", wrap=False)
        self.value = label(value, "mono", wrap=False)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight |
                                Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.name)
        lay.addStretch(1)
        lay.addWidget(self.value)

    def set(self, value: str, token: str | None = None) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(
            f"color: {getattr(theme.C, token)};" if token else "")


class PinchGauge(QWidget):
    """Distancia de pinch con los dos umbrales dibujados.

    Es la herramienta de calibrado: ves la aguja moverse y donde estan los
    umbrales de cierre y apertura, asi que ajustarlos deja de ser a ciegas.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(64)
        self.value = Smooth(1.0, 0.07)
        self.on_threshold = 0.34
        self.off_threshold = 0.46
        self.closed = False
        self.max_value = 1.4
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        _themed(self)

    def set_value(self, v: float, closed: bool) -> None:
        self.value.set(max(0.0, min(self.max_value, v)))
        self.closed = closed

    def set_thresholds(self, on: float, off: float) -> None:
        self.on_threshold, self.off_threshold = on, off
        self.update()

    def _tick(self) -> None:
        if not self.value.settled:
            self.value.step()
            self.update()
        else:
            self.value.step()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(2, 16, -2, -14)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c.surface_sunken))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)

        def x_of(v: float) -> float:
            return r.left() + (v / self.max_value) * r.width()

        # banda de histeresis
        band = QRectF(x_of(self.on_threshold), r.top(),
                      max(x_of(self.off_threshold) - x_of(self.on_threshold), 1),
                      r.height())
        hb = QColor(c.warn)
        hb.setAlpha(46)
        p.setBrush(hb)
        p.drawRect(band)

        # zona de "cerrado"
        closed_rect = QRectF(r.left(), r.top(), max(x_of(self.on_threshold) - r.left(), 0),
                             r.height())
        cb = QColor(c.ok)
        cb.setAlpha(52)
        p.setBrush(cb)
        p.drawRoundedRect(closed_rect, r.height() / 2, r.height() / 2)

        # umbrales
        for v, tok in ((self.on_threshold, "ok"), (self.off_threshold, "warn")):
            p.setPen(QPen(QColor(getattr(c, tok)), 1.6))
            p.drawLine(QPointF(x_of(v), r.top() - 4), QPointF(x_of(v), r.bottom() + 4))

        # aguja
        x = x_of(self.value.value)
        needle = QColor(c.ok if self.closed else c.text)
        glow = QColor(needle)
        glow.setAlpha(70)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(x, r.center().y()), 11, 11)
        p.setBrush(needle)
        p.drawEllipse(QPointF(x, r.center().y()), 5.5, 5.5)

        f = self.font()
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(c.text_faint))
        p.drawText(QRectF(r.left(), r.bottom() + 3, 90, 14),
                   Qt.AlignmentFlag.AlignLeft, "cerrado")
        p.drawText(QRectF(r.right() - 90, r.bottom() + 3, 90, 14),
                   Qt.AlignmentFlag.AlignRight, "abierto")
        # el valor sigue a la aguja, para poder leerlo sin apartar la vista
        p.setPen(QColor(c.text_dim))
        lx = max(r.left(), min(x - 26, r.right() - 52))
        p.drawText(QRectF(lx, 0, 52, 14),
                   Qt.AlignmentFlag.AlignHCenter, f"{self.value.target:.3f}")
        p.end()


# ---------------------------------------------------------------- navegacion
class NavItem:
    __slots__ = ("key", "text", "glyph")

    def __init__(self, key: str, text: str, glyph: str) -> None:
        self.key, self.text, self.glyph = key, text, glyph


class NavRail(QWidget):
    """Barra lateral con pastilla de seleccion animada."""

    selected = Signal(int)

    ROW_H = 44

    def __init__(self, items: list[NavItem], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items = items
        self._index = 0
        self._hover = -1
        self._pill = Smooth(0.0, 0.09)
        self.setFixedWidth(208)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        _themed(self)

    def index(self) -> int:
        return self._index

    def set_index(self, i: int, emit: bool = True) -> None:
        i = max(0, min(len(self.items) - 1, i))
        if i == self._index:
            return
        self._index = i
        self._pill.set(float(i))
        self._timer.start()
        if emit:
            self.selected.emit(i)
        self.update()

    def _tick(self) -> None:
        self._pill.step()
        self.update()
        if self._pill.settled:
            self._timer.stop()

    def _row_at(self, y: float) -> int:
        i = int((y - 6) // self.ROW_H)
        return i if 0 <= i < len(self.items) else -1

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        i = self._row_at(ev.position().y())
        if i >= 0:
            self.set_index(i)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        i = self._row_at(ev.position().y())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, _ev) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        top = 6
        if self._hover >= 0 and self._hover != self._index:
            hr = QRectF(4, top + self._hover * self.ROW_H, self.width() - 8,
                        self.ROW_H - 5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c.surface_hover))
            p.drawRoundedRect(hr, 12, 12)

        pill = QRectF(4, top + self._pill.value * self.ROW_H, self.width() - 8,
                      self.ROW_H - 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c.surface))
        p.drawRoundedRect(pill, 12, 12)
        p.setPen(QPen(QColor(c.border), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill, 12, 12)

        # marca de acento a la izquierda de la pastilla
        marker = QRectF(pill.left() + 1, pill.center().y() - 9, 3, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c.accent))
        p.drawRoundedRect(marker, 1.5, 1.5)

        glyph_font = QFont(self.font())
        glyph_font.setPointSizeF(13.5)
        text_font = QFont(self.font())
        text_font.setWeight(QFont.Weight.DemiBold)

        for i, item in enumerate(self.items):
            y = top + i * self.ROW_H
            active = abs(self._pill.value - i) < 0.5
            col = QColor(c.text if active else c.text_dim)
            p.setPen(col)
            p.setFont(glyph_font)
            p.drawText(QRectF(16, y, 30, self.ROW_H - 5),
                       Qt.AlignmentFlag.AlignCenter, item.glyph)
            p.setFont(text_font)
            p.drawText(QRectF(50, y, self.width() - 60, self.ROW_H - 5),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       item.text)
        p.end()


# -------------------------------------------------------------------- gestos
class GestureIndicator(QWidget):
    """Fila de un gesto con destello al detectarlo."""

    def __init__(self, name: str, description: str, glyph: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.count = 0
        self._flash = Smooth(0.0, 0.16)
        self._active = False
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._name = name
        self._desc = description
        self._glyph = glyph
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        _themed(self)

    def flash(self) -> None:
        self.count += 1
        self._flash.jump(1.0)
        self._flash.set(0.0)
        self._timer.start()
        self.update()

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def cool(self) -> None:
        self._active = False
        self.update()

    def reset(self) -> None:
        self.count = 0
        self._flash.jump(0.0)
        self.cool()

    def _tick(self) -> None:
        self._flash.step()
        self.update()
        if self._flash.settled:
            self._timer.stop()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0, 2, 0, -2)

        f = self._flash.value
        if f > 0.01 or self._active:
            bg = QColor(c.ok if f > 0.01 else c.accent)
            bg.setAlpha(int(max(f * 46, 22 if self._active else 0)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 13, 13)

        # punto de estado
        if f > 0.01:
            dot_col = QColor(c.ok)
        elif self._active:
            dot_col = QColor(c.accent)
        else:
            dot_col = QColor(c.border_strong)
        cx, cy = r.left() + 18, r.center().y()
        if f > 0.01:
            halo = QColor(c.ok)
            halo.setAlpha(int(110 * f))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QPointF(cx, cy), 5 + 9 * (1 - f), 5 + 9 * (1 - f))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot_col)
        p.drawEllipse(QPointF(cx, cy), 4.5, 4.5)

        name_font = QFont(self.font())
        name_font.setWeight(QFont.Weight.DemiBold)
        p.setFont(name_font)
        p.setPen(QColor(c.text))
        p.drawText(QRectF(r.left() + 36, r.top() + 7, r.width() - 110, 18),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._name)

        desc_font = QFont(self.font())
        desc_font.setPointSizeF(max(8.5, self.font().pointSizeF() - 1))
        p.setFont(desc_font)
        p.setPen(QColor(c.text_dim))
        p.drawText(QRectF(r.left() + 36, r.top() + 25, r.width() - 110, 16),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._desc)

        counter_font = QFont("Cascadia Mono")
        if not counter_font.exactMatch():
            counter_font = QFont("Consolas")
        counter_font.setPointSizeF(11.5)
        p.setFont(counter_font)
        p.setPen(QColor(c.ok if self.count else c.text_faint))
        p.drawText(QRectF(r.right() - 62, r.top(), 50, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   str(self.count))
        p.end()


# --------------------------------------------------------------------- otros
class LabeledSlider(QWidget):
    """Slider con etiqueta, valor y trabajo en coma flotante."""

    valueChanged = Signal(float)

    def __init__(self, text: str, minimum: float, maximum: float, value: float,
                 decimals: int = 2, suffix: str = "", hint: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._min, self._max = minimum, maximum
        self._dec = decimals
        self._suffix = suffix

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(5)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = label(text, "dim", wrap=False)
        self.readout = label("", "mono", wrap=False)
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.readout)
        lay.addLayout(head)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.valueChanged.connect(self._on_change)
        lay.addWidget(self.slider)

        if hint:
            lay.addWidget(label(hint, "faint"))
        self.set_value(value)

    def _to_float(self, raw: int) -> float:
        return self._min + (raw / 1000.0) * (self._max - self._min)

    def _on_change(self, raw: int) -> None:
        v = self._to_float(raw)
        self.readout.setText(f"{v:.{self._dec}f}{self._suffix}")
        self.valueChanged.emit(v)

    def value(self) -> float:
        return self._to_float(self.slider.value())

    def set_value(self, v: float) -> None:
        span = max(self._max - self._min, 1e-9)
        raw = int(round((v - self._min) / span * 1000))
        self.slider.blockSignals(True)
        self.slider.setValue(max(0, min(1000, raw)))
        self.slider.blockSignals(False)
        self.readout.setText(f"{v:.{self._dec}f}{self._suffix}")


class SettingRow(QWidget):
    """Fila de ajuste: titulo, descripcion y control a la derecha."""

    def __init__(self, title: str, description: str, control: QWidget,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(14)

        box = QVBoxLayout()
        box.setSpacing(2)
        box.setContentsMargins(0, 0, 0, 0)
        t = label(title, wrap=False)
        box.addWidget(t)
        if description:
            d = label(description, "faint")
            box.addWidget(d)
        lay.addLayout(box, 1)
        lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.control = control


class Banner(QWidget):
    """Aviso contextual con icono, texto y color de estado."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self._token = "info"
        self._glyph = "i"
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _themed(self)

    def set(self, text: str, token: str = "info", glyph: str = "i") -> None:
        if (text, token) == (self._text, self._token):
            return
        self._text, self._token, self._glyph = text, token, glyph
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, 48)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        if not self._text:
            return
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col = QColor(getattr(c, self._token))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        bg = QColor(col)
        bg.setAlpha(30 if c.dark else 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 13, 13)
        border = QColor(col)
        border.setAlpha(78)
        p.setPen(QPen(border, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 13, 13)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(r.left() + 22, r.center().y()), 9, 9)
        gf = QFont(self.font())
        gf.setPointSizeF(9.5)
        gf.setWeight(QFont.Weight.Bold)
        p.setFont(gf)
        p.setPen(QColor(c.surface if c.dark else "#ffffff"))
        p.drawText(QRectF(r.left() + 13, r.center().y() - 9, 18, 18),
                   Qt.AlignmentFlag.AlignCenter, self._glyph)

        p.setFont(self.font())
        p.setPen(QColor(c.text))
        p.drawText(QRectF(r.left() + 40, r.top(), r.width() - 52, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft |
                   int(Qt.TextFlag.TextWordWrap), self._text)
        p.end()


class Ring(QWidget):
    """Anillo de progreso, para cargas y cuentas atras."""

    def __init__(self, size: int = 54, token: str = "accent",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.token = token
        self.progress = Smooth(0.0, 0.1)
        self.text = ""
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        _themed(self)

    def set_progress(self, v: float, text: str = "") -> None:
        self.progress.set(max(0.0, min(1.0, v)))
        self.text = text

    def _tick(self) -> None:
        self.progress.step()
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(5, 5, -5, -5)
        p.setPen(QPen(QColor(c.track), 4.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r)
        p.setPen(QPen(QColor(getattr(c, self.token)), 4.5, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 90 * 16, -int(self.progress.value * 360 * 16))
        if self.text:
            f = QFont(self.font())
            f.setPointSizeF(9.0)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(QColor(c.text_dim))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text)
        p.end()


__all__ = [
    "label", "title_block", "Card", "Hr", "Dot", "Badge", "Toggle",
    "SegmentedControl", "Sparkline", "StatTile", "StatRow", "PinchGauge",
    "NavItem", "NavRail", "GestureIndicator", "LabeledSlider", "SettingRow",
    "Banner", "Ring", "math", "EASE_OUT", "NORMAL",
]
