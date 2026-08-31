"""Eventos que produce el motor de gestos.

El motor NO toca el sistema: solo describe que ha pasado. Quien actua es el
controlador, y solo si el modo seguro esta desactivado. Esta separacion es lo
que permite tener un modo simulacion honesto.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class EventType(Enum):
    MOVE = auto()
    LEFT_DOWN = auto()
    LEFT_UP = auto()
    CLICK = auto()
    DOUBLE_CLICK = auto()
    RIGHT_CLICK = auto()
    SCROLL = auto()
    HSCROLL = auto()
    ZOOM = auto()
    WINDOW_BOUNDS = auto()
    KEY_TEXT = auto()
    KEY_VK = auto()
    PAUSE = auto()
    RESUME = auto()


@dataclass
class GestureEvent:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:  # pragma: no cover - solo para logs
        return f"{self.type.name}({', '.join(f'{k}={v}' for k, v in self.data.items())})"


class Mode(Enum):
    IDLE = "inactivo"
    POINTING = "apuntando"
    PINCH_PENDING = "pinch"
    SCROLLING = "scroll"
    DRAGGING = "arrastrando"
    WINDOW_MOVE = "moviendo ventana"
    WINDOW_RESIZE = "redimensionando"
    ZOOMING = "zoom"
    KEYBOARD = "teclado"
    PAUSED = "en pausa"
