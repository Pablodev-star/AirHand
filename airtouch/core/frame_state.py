"""Modelo de datos que viaja entre hilos.

Un FrameState es inmutable en la practica: lo produce el hilo de vision y lo
consumen el motor de gestos y la UI sin locks.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

# Indices de landmarks de MediaPipe Hands
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

FINGER_TIPS = (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)
FINGER_MCPS = (THUMB_MCP, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)

# Longitud dedo-extendido / tamano de palma en una mano abierta. Se usa para
# normalizar la extension a un rango 0..1.
_EXTENSION_REF = 1.72


def _norm(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


@dataclass
class HandState:
    """Estado geometrico de una mano en un frame."""

    label: str                       # "Left" | "Right" (ya corregido por espejo)
    score: float
    lm: np.ndarray                   # (21,3) normalizado a la imagen 0..1
    world: np.ndarray                # (21,3) metrico relativo al centro de la mano

    # derivados
    scale: float = 1.0               # tamano de la mano en unidades world
    pinch_ratio: float = 1.0         # pulgar-indice normalizado
    middle_pinch_ratio: float = 1.0  # pulgar-corazon normalizado
    index_extension: float = 1.0     # 0 = totalmente curvado, 1 = extendido
    extended: tuple[bool, ...] = (False,) * 5
    pointer: np.ndarray = field(default_factory=lambda: np.zeros(2))  # (x,y) 0..1
    palm: np.ndarray = field(default_factory=lambda: np.zeros(2))
    pinch_point: np.ndarray = field(default_factory=lambda: np.zeros(2))

    @property
    def is_open_palm(self) -> bool:
        return sum(self.extended[1:]) >= 4

    @property
    def is_pointing(self) -> bool:
        return self.extended[1] and not any(self.extended[2:])

    @classmethod
    def build(cls, label: str, score: float, lm: np.ndarray, world: np.ndarray) -> "HandState":
        h = cls(label=label, score=score, lm=lm, world=world)
        h.scale = max(_norm(world[WRIST], world[MIDDLE_MCP]), 1e-4)

        h.pinch_ratio = _norm(world[THUMB_TIP], world[INDEX_TIP]) / h.scale
        h.middle_pinch_ratio = _norm(world[THUMB_TIP], world[MIDDLE_TIP]) / h.scale

        ext_raw = _norm(world[INDEX_TIP], world[INDEX_MCP]) / h.scale
        h.index_extension = float(np.clip(ext_raw / _EXTENSION_REF, 0.0, 1.25))

        ext: list[bool] = []
        for tip, mcp in zip(FINGER_TIPS, FINGER_MCPS):
            r = _norm(world[tip], world[mcp]) / h.scale
            # el pulgar tiene un recorrido mas corto que el resto
            ext.append(r > (0.95 if tip == THUMB_TIP else 1.15))
        h.extended = tuple(ext)

        # la yema es el landmark mas ruidoso de los 21: mezclarla con la falange
        # siguiente quita bastante temblor sin desplazar el puntero en la practica
        h.pointer = lm[INDEX_TIP, :2] * 0.78 + lm[INDEX_DIP, :2] * 0.22
        h.palm = lm[[WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP], :2].mean(axis=0)
        h.pinch_point = (lm[THUMB_TIP, :2] + lm[INDEX_TIP, :2]) * 0.5
        return h


@dataclass
class FaceState:
    present: bool = False
    center: np.ndarray = field(default_factory=lambda: np.zeros(2))
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0


@dataclass
class FrameState:
    """Todo lo que el motor de gestos necesita saber de un instante."""

    t: float = field(default_factory=time.perf_counter)
    frame_id: int = 0
    hands: list[HandState] = field(default_factory=list)
    face: FaceState = field(default_factory=FaceState)
    width: int = 0
    height: int = 0
    capture_latency_ms: float = 0.0
    process_ms: float = 0.0

    def hand(self, label: str) -> HandState | None:
        for h in self.hands:
            if h.label == label:
                return h
        return None

    @property
    def primary(self) -> HandState | None:
        """La mano que manda: la de mayor confianza, con preferencia a la derecha."""
        if not self.hands:
            return None
        return max(self.hands, key=lambda h: (h.score + (0.05 if h.label == "Right" else 0.0)))

    @property
    def secondary(self) -> HandState | None:
        if len(self.hands) < 2:
            return None
        p = self.primary
        for h in self.hands:
            if h is not p:
                return h
        return None
