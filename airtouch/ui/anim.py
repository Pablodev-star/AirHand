"""Compatibilidad: el vocabulario de animacion de la 1.x apuntando a motion.py.

Mientras siga viva la interfaz vieja (``dashboard.py``, ``widgets.py`` y
``wizard/wizard.py``) estos nombres se importan desde aqui. ``Smooth``, ``fade``,
``tween`` y ``ease`` estaban duplicados palabra por palabra con los de
``motion``: la copia se ha borrado y lo que queda son alias. Dos suavizados
distintos en la misma ventana es como empieza a desencajarse una interfaz, y
ademas un arreglo en uno no llegaba nunca al otro.

Con cuerpo propio quedan solo ``AnimatedStack`` y ``shake``, que la 2.0 no
hereda: la transicion de pagina pasa a ser el patron 6 de la spec (escala con
QTransform en el paintEvent del contenedor, no un efecto por hijo). Se van con
el resto de esta capa.
"""
from __future__ import annotations

import math

from PySide6.QtCore import (
    QAbstractAnimation, QParallelAnimationGroup, QPoint, QPropertyAnimation,
    QVariantAnimation, Qt,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget

from .motion import (
    EASE_GLASS, EASE_LIFT, EASE_SOFT, ELEMENT, HOVER_IN, STAGGER_DUR, Smooth,
    ease, fade, tween,
)

# nombres viejos -> vocabulario de la 2.0. Los tres duraciones sueltas de la 1.x
# (160/240/380) resultaron ser tres constantes que la spec ya nombra.
EASE_OUT = EASE_GLASS
EASE_IN_OUT = EASE_SOFT
EASE_SPRING = EASE_LIFT
FAST = HOVER_IN        # 160 ms: el alzado de lamina del patron 3
NORMAL = ELEMENT       # 200 ms
SLOW = STAGGER_DUR     # 380 ms


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


# Qt viaja en esta lista desde la 1.x: hay modulos que lo toman de aqui en vez
# de importarlo de QtCore. Se quita cuando caiga la interfaz vieja, no antes.
__all__ = [
    "Smooth", "AnimatedStack", "fade", "tween", "shake", "ease",
    "EASE_OUT", "EASE_IN_OUT", "EASE_SPRING", "FAST", "NORMAL", "SLOW", "Qt",
]
