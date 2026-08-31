"""Filtros de suavizado.

El jitter de MediaPipe es lo que hace que un puntero por camara se sienta
barato. One Euro es el estandar para esto: suaviza mucho cuando la mano esta
quieta y deja de suavizar cuando te mueves rapido, asi no introduce lag
perceptible.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np


class _LowPass:
    __slots__ = ("_y", "_initialised")

    def __init__(self) -> None:
        self._y = None
        self._initialised = False

    def __call__(self, x, alpha: float):
        if not self._initialised:
            self._y = x
            self._initialised = True
        else:
            self._y = alpha * x + (1.0 - alpha) * self._y
        return self._y

    @property
    def last(self):
        return self._y

    def reset(self) -> None:
        self._y = None
        self._initialised = False


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
    return 1.0 / (1.0 + tau / max(dt, 1e-6))


class OneEuroFilter:
    """Funciona con escalares o con vectores numpy."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0, d_cutoff: float = 1.0) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x = _LowPass()
        self._dx = _LowPass()
        self._last_t: float | None = None

    def reset(self) -> None:
        self._x.reset()
        self._dx.reset()
        self._last_t = None

    def __call__(self, value, t: float):
        if self._last_t is None:
            dt = 1.0 / 60.0
        else:
            dt = t - self._last_t
            if dt <= 0:
                dt = 1.0 / 60.0
        self._last_t = t

        prev = self._x.last
        if prev is None:
            dx = value * 0.0
        else:
            dx = (value - prev) / dt
        edx = self._dx(dx, _alpha(self.d_cutoff, dt))

        speed = float(np.linalg.norm(edx)) if isinstance(edx, np.ndarray) else abs(float(edx))
        cutoff = self.min_cutoff + self.beta * speed
        return self._x(value, _alpha(cutoff, dt))

    @property
    def derivative(self):
        """Velocidad ya filtrada (unidades por segundo).

        Es mucho mas limpia que restar dos muestras seguidas: el tiempo entre
        frames varia, y esa varianza se convierte en picos de velocidad.
        """
        return self._dx.last


class VectorOneEuro:
    """One Euro sobre un array numpy de tamano fijo, con reset por perdida."""

    def __init__(self, size: int, min_cutoff: float, beta: float, d_cutoff: float = 1.0) -> None:
        self.size = size
        self._f = OneEuroFilter(min_cutoff, beta, d_cutoff)

    def update(self, vec: Sequence[float], t: float) -> np.ndarray:
        arr = np.asarray(vec, dtype=np.float64)
        return np.asarray(self._f(arr, t), dtype=np.float64)

    @property
    def derivative(self) -> np.ndarray | None:
        d = self._f.derivative
        return None if d is None else np.asarray(d, dtype=np.float64)

    def tune(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0) -> None:
        self._f.min_cutoff = min_cutoff
        self._f.beta = beta
        self._f.d_cutoff = d_cutoff

    def reset(self) -> None:
        self._f.reset()


class Hysteresis:
    """Interruptor con dos umbrales. Evita el parpadeo del pinch en el limite."""

    def __init__(self, on_below: float, off_above: float, state: bool = False) -> None:
        self.on_below = on_below
        self.off_above = off_above
        self.state = state

    def update(self, value: float) -> bool:
        if self.state:
            if value > self.off_above:
                self.state = False
        else:
            if value < self.on_below:
                self.state = True
        return self.state

    def reset(self, state: bool = False) -> None:
        self.state = state


class EMA:
    """Media movil exponencial simple, para metricas (FPS, latencia)."""

    def __init__(self, alpha: float = 0.15, initial: float | None = None) -> None:
        self.alpha = alpha
        self.value = initial

    def update(self, x: float) -> float:
        if self.value is None:
            self.value = x
        else:
            self.value = self.alpha * x + (1 - self.alpha) * self.value
        return self.value

    def reset(self) -> None:
        self.value = None
