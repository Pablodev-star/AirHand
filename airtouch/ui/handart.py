"""Ilustraciones animadas de los gestos.

Una mano estilizada que ejecuta el gesto en bucle. Es mucho mas claro que
cualquier parrafo: ves exactamente que tienen que hacer tus dedos. El dibujo
usa el mismo lenguaje que el esqueleto de la camara (yemas como circulos,
dedos como trazos redondeados) para que reconozcas la relacion.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme

# ---- geometria de la mano en coordenadas unitarias (y hacia abajo) ----
PALM = (0.50, 0.79)
PALM_R = 0.155
INDEX_BASE = (0.565, 0.655)
THUMB_BASE = (0.345, 0.735)
INDEX_TIP_OPEN = (0.585, 0.255)
THUMB_TIP_OPEN = (0.235, 0.505)
PINCH_POINT = (0.500, 0.395)
INDEX_TIP_CURLED = (0.470, 0.560)


def _lerp(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _ease(t: float) -> float:
    """Suavizado tipo Apple: sale despacio, acelera, frena."""
    return t * t * (3.0 - 2.0 * t)


class GestureArt(QWidget):
    """Anima uno de los gestos en bucle.

    gesture: "point" | "pinch" | "click" | "scroll" | "flick" | "zoom" | "window"
    """

    def __init__(self, gesture: str = "pinch", parent: QWidget | None = None,
                 period: float = 2.6) -> None:
        super().__init__(parent)
        self.gesture = gesture
        self.period = period
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._t0 = time.perf_counter()
        self._contact_at = -10.0
        self._was_contact = False
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.update)
        theme.signals.changed.connect(self._on_theme)

    def _on_theme(self, *_a) -> None:
        try:
            self.update()
        except RuntimeError:
            pass

    def set_gesture(self, gesture: str) -> None:
        self.gesture = gesture
        self._t0 = time.perf_counter()
        self.update()

    def showEvent(self, ev) -> None:  # noqa: N802
        self._t0 = time.perf_counter()
        self._timer.start()
        super().showEvent(ev)

    def hideEvent(self, ev) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(ev)

    # ---------------- estado del gesto ----------------
    def _phase(self) -> float:
        return ((time.perf_counter() - self._t0) % self.period) / self.period

    def _pose(self, phase: float):
        """Devuelve (index_tip, thumb_tip, offset, contact, spread)."""
        g = self.gesture
        offset = (0.0, 0.0)
        spread = 0.0

        if g == "point":
            return INDEX_TIP_OPEN, THUMB_TIP_OPEN, offset, False, spread

        if g in ("pinch", "click", "window"):
            # cerrar - mantener - abrir - esperar
            if phase < 0.30:
                k = _ease(phase / 0.30)
            elif phase < 0.55:
                k = 1.0
            elif phase < 0.80:
                k = 1.0 - _ease((phase - 0.55) / 0.25)
            else:
                k = 0.0
            idx = _lerp(INDEX_TIP_OPEN, PINCH_POINT, k)
            thb = _lerp(THUMB_TIP_OPEN, PINCH_POINT, k)
            if g == "window":
                offset = (0.10 * k * math.sin(phase * math.pi * 2), 0.0)
            return idx, thb, offset, k > 0.94, spread

        if g == "scroll":
            k = 1.0 if 0.15 < phase < 0.95 else _ease(min(phase / 0.15, 1.0))
            idx = _lerp(INDEX_TIP_OPEN, PINCH_POINT, k)
            thb = _lerp(THUMB_TIP_OPEN, PINCH_POINT, k)
            if phase > 0.15:
                slide = _ease(min((phase - 0.15) / 0.65, 1.0))
                offset = (0.0, -0.20 * slide)
            return idx, thb, offset, k > 0.94, spread

        if g == "flick":
            # cargar (indice curvado contra el pulgar) y soltar de golpe
            if phase < 0.55:
                k = _ease(min(phase / 0.25, 1.0))
                idx = _lerp(INDEX_TIP_OPEN, INDEX_TIP_CURLED, k)
                thb = _lerp(THUMB_TIP_OPEN, INDEX_TIP_CURLED, k * 0.92)
                return idx, thb, offset, k > 0.9, spread
            k = _ease(min((phase - 0.55) / 0.14, 1.0))   # liberacion rapida
            idx = _lerp(INDEX_TIP_CURLED, INDEX_TIP_OPEN, k)
            thb = _lerp(INDEX_TIP_CURLED, THUMB_TIP_OPEN, k)
            return idx, thb, offset, False, spread

        if g == "zoom":
            k = _ease(min(phase / 0.18, 1.0))
            idx = _lerp(INDEX_TIP_OPEN, PINCH_POINT, k)
            thb = _lerp(THUMB_TIP_OPEN, PINCH_POINT, k)
            wave = math.sin(max(phase - 0.18, 0.0) / 0.82 * math.pi)
            spread = 0.16 * wave * (1.0 if phase > 0.18 else 0.0)
            return idx, thb, offset, k > 0.94, spread

        return INDEX_TIP_OPEN, THUMB_TIP_OPEN, offset, False, spread

    # ---------------- pintado ----------------
    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        side = min(self.width(), self.height())
        ox = (self.width() - side) / 2
        oy = (self.height() - side) / 2

        phase = self._phase()
        idx, thb, offset, contact, spread = self._pose(phase)

        if contact and not self._was_contact:
            self._contact_at = time.perf_counter()
        self._was_contact = contact

        def P(u: tuple[float, float], dx: float = 0.0) -> QPointF:
            return QPointF(ox + (u[0] + offset[0] + dx) * side,
                           oy + (u[1] + offset[1]) * side)

        if self.gesture == "zoom":
            self._draw_hand(p, P, side, idx, thb, contact, mirror=False, dx=-spread)
            self._draw_hand(p, P, side, idx, thb, contact, mirror=True, dx=spread)
            self._draw_zoom_link(p, P, side, spread)
        else:
            self._draw_hand(p, P, side, idx, thb, contact, mirror=False)

        if self.gesture == "scroll":
            self._draw_scroll_hint(p, ox, oy, side, phase)
        p.end()

    def _draw_hand(self, p: QPainter, P, side: float,
                   idx: tuple[float, float], thb: tuple[float, float],
                   contact: bool, mirror: bool, dx: float = 0.0) -> None:
        c = theme.C
        stroke = QColor(c.text)
        stroke.setAlpha(232)
        soft = QColor(c.text)
        soft.setAlpha(58)

        def M(u: tuple[float, float]) -> tuple[float, float]:
            return (1.0 - u[0], u[1]) if mirror else u

        palm = P(M(PALM), dx)
        r = PALM_R * side

        # halo de la palma
        grad = QRadialGradient(palm, r * 1.9)
        g0 = QColor(c.accent)
        g0.setAlpha(40 if c.dark else 30)
        g1 = QColor(c.accent)
        g1.setAlpha(0)
        grad.setColorAt(0.0, g0)
        grad.setColorAt(1.0, g1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(palm, r * 1.9, r * 1.9)

        # palma
        p.setBrush(soft)
        p.drawEllipse(palm, r, r)

        # dedos plegados, insinuados detras
        folded = QColor(c.text)
        folded.setAlpha(52)
        pen = QPen(folded, side * 0.045, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for k in range(3):
            base = M((0.50 + 0.055 * k, 0.70))
            tip = M((0.50 + 0.060 * k, 0.575))
            p.drawLine(P(base, dx), P(tip, dx))

        # indice y pulgar
        pen = QPen(stroke, side * 0.052, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        index_path = QPainterPath(P(M(INDEX_BASE), dx))
        index_path.quadTo(P(M((INDEX_BASE[0] + 0.03, (INDEX_BASE[1] + idx[1]) / 2)), dx),
                          P(M(idx), dx))
        p.drawPath(index_path)

        thumb_path = QPainterPath(P(M(THUMB_BASE), dx))
        thumb_path.quadTo(P(M((THUMB_BASE[0] - 0.05, (THUMB_BASE[1] + thb[1]) / 2)), dx),
                          P(M(thb), dx))
        p.drawPath(thumb_path)

        # yemas
        tip_col = QColor(c.accent if contact else c.text)
        p.setPen(Qt.PenStyle.NoPen)
        for u in (idx, thb):
            pt = P(M(u), dx)
            halo = QColor(tip_col)
            halo.setAlpha(70)
            p.setBrush(halo)
            p.drawEllipse(pt, side * 0.052, side * 0.052)
            p.setBrush(tip_col)
            p.drawEllipse(pt, side * 0.031, side * 0.031)

        # onda al tocarse
        age = time.perf_counter() - self._contact_at
        if 0.0 <= age < 0.55:
            k = age / 0.55
            ring = QColor(c.ok)
            ring.setAlpha(int(190 * (1.0 - k)))
            p.setPen(QPen(ring, side * 0.012))
            p.setBrush(Qt.BrushStyle.NoBrush)
            mid = P(M(((idx[0] + thb[0]) / 2, (idx[1] + thb[1]) / 2)), dx)
            p.drawEllipse(mid, side * (0.04 + 0.14 * k), side * (0.04 + 0.14 * k))

    def _draw_zoom_link(self, p: QPainter, P, side: float, spread: float) -> None:
        c = theme.C
        col = QColor(c.accent)
        col.setAlpha(120)
        p.setPen(QPen(col, side * 0.008, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        a = P(PINCH_POINT, -spread)
        b = P((1.0 - PINCH_POINT[0], PINCH_POINT[1]), spread)
        p.drawLine(a, b)

    def _draw_scroll_hint(self, p: QPainter, ox: float, oy: float, side: float,
                          phase: float) -> None:
        c = theme.C
        col = QColor(c.accent)
        col.setAlpha(int(150 * min(max((phase - 0.2) / 0.2, 0.0), 1.0)))
        p.setPen(QPen(col, side * 0.011, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x = ox + side * 0.86
        top = oy + side * 0.30
        bottom = oy + side * 0.66
        p.drawLine(QPointF(x, bottom), QPointF(x, top))
        p.drawLine(QPointF(x, top), QPointF(x - side * 0.035, top + side * 0.045))
        p.drawLine(QPointF(x, top), QPointF(x + side * 0.035, top + side * 0.045))


class PinchMeterArt(QWidget):
    """Dos circulos que se acercan segun tu pinch real.

    En la calibracion sustituye a cualquier explicacion: mueves los dedos y ves
    los circulos moverse contigo, y cuando se tocan se ilumina.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.gap = 1.0            # 0 = tocandose, 1 = muy separados
        self.closed = False
        self.label = ""
        self._shown = 1.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        theme.signals.changed.connect(lambda *_a: self.update())

    def set_gap(self, gap: float, closed: bool) -> None:
        self.gap = max(0.0, min(1.0, gap))
        self.closed = closed

    def _tick(self) -> None:
        self._shown += (self.gap - self._shown) * 0.25
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        cy = h * 0.5
        r = min(h * 0.22, 34.0)
        span = min(w * 0.30, 150.0)
        d = span * self._shown

        col = QColor(c.ok if self.closed else c.text_dim)

        # guia
        guide = QColor(c.border)
        p.setPen(QPen(guide, 2, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(w / 2 - span, cy), QPointF(w / 2 + span, cy))

        if self.closed:
            glow = QRadialGradient(QPointF(w / 2, cy), r * 3.2)
            g0 = QColor(c.ok)
            g0.setAlpha(70)
            g1 = QColor(c.ok)
            g1.setAlpha(0)
            glow.setColorAt(0.0, g0)
            glow.setColorAt(1.0, g1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(w / 2, cy), r * 3.2, r * 3.2)

        p.setPen(Qt.PenStyle.NoPen)
        for sx in (-1, 1):
            cx = w / 2 + sx * d
            halo = QColor(col)
            halo.setAlpha(64)
            p.setBrush(halo)
            p.drawEllipse(QPointF(cx, cy), r * 1.35, r * 1.35)
            p.setBrush(col)
            p.drawEllipse(QPointF(cx, cy), r, r)

        if self.label:
            f = self.font()
            f.setPointSizeF(f.pointSizeF() + 1)
            p.setFont(f)
            p.setPen(QColor(c.text_dim))
            p.drawText(QRectF(0, h - 26, w, 22),
                       Qt.AlignmentFlag.AlignCenter, self.label)
        p.end()
