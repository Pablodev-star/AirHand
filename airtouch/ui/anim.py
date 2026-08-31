"""Utilidades de animacion.

Dos familias:

* **Qt puro** (``QPropertyAnimation``) para opacidad y geometria de widgets.
* **Suavizado por frame** (``Smooth``) para valores que se pintan a mano, donde
  animar con Qt seria un lio: barras, agujas, indicadores. Es interpolacion
  exponencial, asi que da igual el framerate.
"""
from __future__ import annotations

import math
import time
from typing import Callable

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QParallelAnimationGroup, QPoint,
    QPropertyAnimation, QVariantAnimation, Qt,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget

# curvas que usamos en toda la app, para que todo se mueva igual
EASE_OUT = QEasingCurve.Type.OutCubic
EASE_IN_OUT = QEasingCurve.Type.InOutCubic
EASE_SPRING = QEasingCurve.Type.OutBack

FAST = 160
NORMAL = 240
SLOW = 380


class Smooth:
    """Valor que persigue a un objetivo con constante de tiempo fija."""

    __slots__ = ("value", "target", "tau", "_t")

    def __init__(self, value: float = 0.0, tau: float = 0.14) -> None:
        self.value = value
        self.target = value
        self.tau = tau
        self._t = time.perf_counter()

    def set(self, target: float) -> None:
        self.target = target

    def jump(self, value: float) -> None:
        self.value = self.target = value

    def step(self, now: float | None = None) -> float:
        now = now if now is not None else time.perf_counter()
        dt = min(max(now - self._t, 0.0), 0.1)
        self._t = now
        if self.tau <= 0:
            self.value = self.target
        else:
            a = 1.0 - math.exp(-dt / self.tau)
            self.value += (self.target - self.value) * a
        return self.value

    @property
    def settled(self) -> bool:
        return abs(self.target - self.value) < 1e-3


def fade(widget: QWidget, start: float, end: float, duration: int = NORMAL,
         on_done: Callable[[], None] | None = None) -> QPropertyAnimation:
    """Anima la opacidad de un widget.

    Al llegar a opacidad plena se retira el efecto: un QGraphicsEffect activo
    cuesta rendimiento y ademas impide que el widget aparezca en capturas.
    """
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(start)

    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(EASE_OUT)

    def _cleanup() -> None:
        if end >= 0.999:
            try:
                widget.setGraphicsEffect(None)
            except RuntimeError:
                pass
        if on_done is not None:
            on_done()

    anim.finished.connect(_cleanup)
    widget._fade_anim = anim  # type: ignore[attr-defined]
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
    return anim


def tween(start: float, end: float, duration: int,
          on_value: Callable[[float], None], parent: QWidget | None = None,
          curve: QEasingCurve.Type = EASE_OUT) -> QVariantAnimation:
    """Interpola un numero y llama a on_value en cada paso."""
    anim = QVariantAnimation(parent)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(duration)
    anim.setEasingCurve(curve)
    anim.valueChanged.connect(lambda v: on_value(float(v)))
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


class AnimatedStack(QStackedWidget):
    """Pila de paginas con transicion de fundido y desplazamiento.

    Se anima la pagina entrante sobre la saliente; la direccion depende de si
    vas hacia delante o hacia atras en la navegacion.
    """

    def __init__(self, parent: QWidget | None = None, offset: int = 18,
                 duration: int = NORMAL) -> None:
        super().__init__(parent)
        self.offset = offset
        self.duration = duration
        self._running: QParallelAnimationGroup | None = None

    def go_to(self, index: int, forward: bool | None = None) -> None:
        current = self.currentIndex()
        if index == current or not (0 <= index < self.count()):
            return
        if forward is None:
            forward = index > current

        outgoing = self.widget(current)
        incoming = self.widget(index)
        if outgoing is None or incoming is None:
            self.setCurrentIndex(index)
            return

        if self._running is not None:
            self._running.stop()
            self._running = None

        incoming.setGeometry(outgoing.geometry())
        target = incoming.pos()
        shift = self.offset if forward else -self.offset

        group = QParallelAnimationGroup(self)

        slide = QPropertyAnimation(incoming, b"pos", group)
        slide.setDuration(self.duration)
        slide.setEasingCurve(EASE_OUT)
        slide.setStartValue(QPoint(target.x(), target.y() + shift))
        slide.setEndValue(target)
        group.addAnimation(slide)

        effect = QGraphicsOpacityEffect(incoming)
        incoming.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        opacity = QPropertyAnimation(effect, b"opacity", group)
        opacity.setDuration(self.duration)
        opacity.setEasingCurve(EASE_OUT)
        opacity.setStartValue(0.0)
        opacity.setEndValue(1.0)
        group.addAnimation(opacity)

        def _cleanup() -> None:
            incoming.setGraphicsEffect(None)
            incoming.move(target)
            self._running = None

        group.finished.connect(_cleanup)
        self.setCurrentIndex(index)
        incoming.raise_()
        self._running = group
        group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def shake(widget: QWidget, amplitude: int = 7, duration: int = 320) -> None:
    """Sacudida horizontal para errores. Discreta, no de dibujos animados."""
    origin = widget.pos()
    anim = QVariantAnimation(widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)

    def _step(t: float) -> None:
        dx = math.sin(t * math.pi * 3) * amplitude * (1.0 - t)
        widget.move(origin.x() + int(dx), origin.y())

    anim.valueChanged.connect(lambda v: _step(float(v)))
    anim.finished.connect(lambda: widget.move(origin))
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    widget._shake_anim = anim  # type: ignore[attr-defined]


def ease(t: float, curve: QEasingCurve.Type = EASE_OUT) -> float:
    return QEasingCurve(curve).valueForProgress(max(0.0, min(1.0, t)))


__all__ = [
    "Smooth", "AnimatedStack", "fade", "tween", "shake", "ease",
    "EASE_OUT", "EASE_IN_OUT", "EASE_SPRING", "FAST", "NORMAL", "SLOW", "Qt",
]
