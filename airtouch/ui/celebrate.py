"""Momentos de celebracion.

Cuando alguien consigue algo hay que decirselo. Un check que aparece con
rebote y una lluvia de particulas cuestan poco y cambian por completo la
sensacion de terminar la configuracion.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme


def _ease_out_back(t: float, s: float = 1.7) -> float:
    t -= 1.0
    return t * t * ((s + 1) * t + s) + 1.0


def _ease_out(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


@dataclass
class _Particle:
    x: float
    y: float
    vx: float
    vy: float
    size: float
    spin: float
    angle: float
    color: QColor
    life: float


class Confetti(QWidget):
    """Lluvia de particulas. Atraviesa el raton, solo decora."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._parts: list[_Particle] = []
        self._t = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def burst(self, count: int = 90, origin: QPointF | None = None) -> None:
        c = theme.C
        palette = [QColor(c.accent), QColor(c.ok), QColor(c.warn),
                   QColor(c.info), QColor(c.text)]
        w, h = max(self.width(), 1), max(self.height(), 1)
        src = origin or QPointF(w / 2, h * 0.42)
        rng = random.Random(1234 + count)
        for _ in range(count):
            ang = rng.uniform(-math.pi, 0.0)          # hacia arriba
            speed = rng.uniform(180.0, 520.0)
            self._parts.append(_Particle(
                x=src.x() + rng.uniform(-24, 24),
                y=src.y() + rng.uniform(-12, 12),
                vx=math.cos(ang) * speed * rng.uniform(0.5, 1.2),
                vy=math.sin(ang) * speed,
                size=rng.uniform(5.0, 11.0),
                spin=rng.uniform(-7.0, 7.0),
                angle=rng.uniform(0, math.tau),
                color=rng.choice(palette),
                life=rng.uniform(1.5, 2.6),
            ))
        self._t = time.perf_counter()
        self.raise_()
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(now - self._t, 0.05)
        self._t = now
        alive: list[_Particle] = []
        for p in self._parts:
            p.life -= dt
            if p.life <= 0:
                continue
            p.vy += 900.0 * dt                 # gravedad
            p.vx *= 0.995
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.angle += p.spin * dt
            if p.y < self.height() + 40:
                alive.append(p)
        self._parts = alive
        if not self._parts:
            self._timer.stop()
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        if not self._parts:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        for part in self._parts:
            col = QColor(part.color)
            col.setAlpha(int(255 * min(part.life, 1.0)))
            p.setBrush(col)
            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.angle))
            p.drawRoundedRect(
                QRectF(-part.size / 2, -part.size * 0.32, part.size, part.size * 0.64),
                1.6, 1.6)
            p.restore()
        p.end()


class SuccessMark(QWidget):
    """Circulo con check que se dibuja solo."""

    finished = Signal()

    def __init__(self, size: int = 108, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._t0 = 0.0
        self._running = False
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        theme.signals.changed.connect(lambda *_a: self.update())

    def play(self) -> None:
        self._t0 = time.perf_counter()
        self._running = True
        self._timer.start()
        self.update()

    def _tick(self) -> None:
        if time.perf_counter() - self._t0 > 1.3:
            self._timer.stop()
            self.finished.emit()
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        if not self._running:
            return
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        el = time.perf_counter() - self._t0
        s = min(self.width(), self.height())
        r = QRectF(4, 4, s - 8, s - 8)

        # 1) el circulo entra con rebote
        pop = _ease_out_back(min(el / 0.42, 1.0))
        p.save()
        p.translate(s / 2, s / 2)
        p.scale(pop, pop)
        p.translate(-s / 2, -s / 2)

        halo = QColor(c.ok)
        halo.setAlpha(46)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(r.adjusted(-4, -4, 4, 4))
        p.setBrush(QColor(c.ok))
        p.drawEllipse(r)

        # 2) el check se dibuja despues
        draw = max(0.0, min((el - 0.26) / 0.34, 1.0))
        if draw > 0:
            path = QPainterPath()
            a = QPointF(s * 0.31, s * 0.52)
            b = QPointF(s * 0.44, s * 0.65)
            d = QPointF(s * 0.70, s * 0.37)
            k = _ease_out(draw)
            path.moveTo(a)
            if k <= 0.45:
                t = k / 0.45
                path.lineTo(QPointF(a.x() + (b.x() - a.x()) * t,
                                    a.y() + (b.y() - a.y()) * t))
            else:
                path.lineTo(b)
                t = (k - 0.45) / 0.55
                path.lineTo(QPointF(b.x() + (d.x() - b.x()) * t,
                                    b.y() + (d.y() - b.y()) * t))
            pen = QPen(QColor("#ffffff"), s * 0.085, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.restore()

        # 3) onda expansiva
        if 0.30 < el < 1.1:
            k = (el - 0.30) / 0.8
            ring = QColor(c.ok)
            ring.setAlpha(int(150 * (1 - k)))
            p.setPen(QPen(ring, 3.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            grow = r.adjusted(-k * 26, -k * 26, k * 26, k * 26)
            p.drawEllipse(grow)
        p.end()


class Pulse(QWidget):
    """Anillo que late detras de un boton para atraer la mirada."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._t0 = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)

    def showEvent(self, ev) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(ev)

    def hideEvent(self, ev) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(ev)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = ((time.perf_counter() - self._t0) % 2.0) / 2.0
        k = _ease_out(t)
        col = QColor(c.accent)
        col.setAlpha(int(110 * (1 - k)))
        p.setPen(QPen(col, 2.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        grow = r.adjusted(-k * 14, -k * 10, k * 14, k * 10)
        p.drawRoundedRect(grow, grow.height() / 2, grow.height() / 2)
        p.end()
