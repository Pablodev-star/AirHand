"""Mano -> coordenadas de pantalla.

Dos modos:
  * absoluto: una region del encuadre se estira sobre la pantalla. Con
    calibracion de 4 esquinas se usa una homografia, lo que corrige el angulo
    y la distorsion del gran angular del movil.
  * relativo: como un raton. Cansa menos y da mas precision fina, pero pierdes
    el "apunto y ya esta".
"""
from __future__ import annotations

import numpy as np

from ..config import FilterConfig, MappingConfig
from .filters import VectorOneEuro
from .screen import Rect, primary_screen, virtual_screen


class PointerMapper:
    def __init__(self, mcfg: MappingConfig, fcfg: FilterConfig) -> None:
        self.mcfg = mcfg
        self.fcfg = fcfg
        self._filter = VectorOneEuro(2, fcfg.min_cutoff, fcfg.beta, fcfg.d_cutoff)
        self._last_raw: np.ndarray | None = None
        self._rel_pos: np.ndarray | None = None
        self._H: np.ndarray | None = None
        self._last_out: tuple[float, float] | None = None
        self._prev_smooth: np.ndarray | None = None
        self._prev_t: float | None = None
        self.refresh_target()
        self.refresh_calibration()

    # ---------------- configuracion ----------------
    def refresh_target(self) -> None:
        self.target: Rect = (
            virtual_screen() if self.mcfg.monitor == "virtual" else primary_screen()
        )

    def refresh_calibration(self) -> None:
        h = self.mcfg.homography
        self._H = np.asarray(h, dtype=np.float64).reshape(3, 3) if h else None

    def retune(self) -> None:
        self._filter.tune(self.fcfg.min_cutoff, self.fcfg.beta, self.fcfg.d_cutoff)
        self.refresh_target()
        self.refresh_calibration()

    def reset(self) -> None:
        self._filter.reset()
        self._last_raw = None
        self._rel_pos = None
        self._last_out = None
        self._prev_smooth = None
        self._prev_t = None

    # ---------------- calibracion ----------------
    @staticmethod
    def compute_homography(image_pts: list[tuple[float, float]], target: Rect) -> list[float]:
        """image_pts en orden: sup-izq, sup-der, inf-der, inf-izq (normalizados)."""
        import cv2

        src = np.asarray(image_pts, dtype=np.float32)
        dst = np.asarray([
            [target.x, target.y],
            [target.right - 1, target.y],
            [target.right - 1, target.bottom - 1],
            [target.x, target.bottom - 1],
        ], dtype=np.float32)
        H = cv2.getPerspectiveTransform(src, dst)
        return [float(v) for v in H.reshape(-1)]

    # ---------------- mapeo ----------------
    def _to_screen_absolute(self, nx: float, ny: float) -> tuple[float, float]:
        if self._H is not None:
            v = self._H @ np.array([nx, ny, 1.0])
            if abs(v[2]) < 1e-9:
                return float(self.target.x), float(self.target.y)
            return float(v[0] / v[2]), float(v[1] / v[2])

        m = self.mcfg
        span_x = max(m.region_x1 - m.region_x0, 1e-3)
        span_y = max(m.region_y1 - m.region_y0, 1e-3)
        u = (nx - m.region_x0) / span_x
        v = (ny - m.region_y0) / span_y
        return (self.target.x + u * (self.target.w - 1),
                self.target.y + v * (self.target.h - 1))

    def _to_screen_relative(self, nx: float, ny: float) -> tuple[float, float]:
        raw = np.array([nx, ny])
        if self._last_raw is None or self._rel_pos is None:
            self._last_raw = raw
            self._rel_pos = np.array([
                self.target.x + self.target.w / 2.0,
                self.target.y + self.target.h / 2.0,
            ])
            return float(self._rel_pos[0]), float(self._rel_pos[1])

        d = raw - self._last_raw
        self._last_raw = raw
        px = d * np.array([self.target.w, self.target.h]) * self.mcfg.relative_gain
        speed = float(np.linalg.norm(px))
        if speed > 0:
            boost = 1.0 + (self.mcfg.relative_accel - 1.0) * min(speed / 40.0, 1.0)
            px *= boost
        self._rel_pos = self._rel_pos + px
        self._rel_pos[0] = min(max(self._rel_pos[0], self.target.x), self.target.right - 1)
        self._rel_pos[1] = min(max(self._rel_pos[1], self.target.y), self.target.bottom - 1)
        return float(self._rel_pos[0]), float(self._rel_pos[1])

    def update(self, pointer_norm: np.ndarray, t: float) -> tuple[float, float]:
        nx, ny = float(pointer_norm[0]), float(pointer_norm[1])
        if self.mcfg.mode == "relative":
            sx, sy = self._to_screen_relative(nx, ny)
        else:
            sx, sy = self._to_screen_absolute(nx, ny)

        base = np.asarray(self._filter.update([sx, sy], t), dtype=np.float64)

        # Compensacion de latencia: la camara siempre va por detras de tu mano.
        # Extrapolando un poco hacia donde vas, el puntero se siente pegado al
        # dedo en vez de arrastrandose. El tope evita rebotes al frenar de golpe.
        out = base
        pred_ms = self.fcfg.prediction_ms
        if pred_ms > 0:
            vel = self._filter.derivative
            if vel is not None:
                speed = float(np.linalg.norm(vel))
                # Prediccion ADAPTATIVA: con la mano quieta no compensa nada
                # (solo anadiria temblor) y a partir de cierta velocidad entra
                # del todo. Compensar latencia solo importa cuando te mueves.
                lo, hi = self.fcfg.prediction_min_speed, self.fcfg.prediction_full_speed
                k = 0.0 if speed <= lo else min((speed - lo) / max(hi - lo, 1.0), 1.0)
                if k > 0.0:
                    offset = vel * (pred_ms / 1000.0) * k
                    mag = float(np.linalg.norm(offset))
                    cap = self.fcfg.prediction_max_px
                    if mag > cap:
                        offset = offset * (cap / mag)
                    out = base + offset

        self._prev_smooth = base
        self._prev_t = t

        x, y = self.target.clamp(out[0], out[1])

        if self._last_out is not None:
            dx = x - self._last_out[0]
            dy = y - self._last_out[1]
            if (dx * dx + dy * dy) < self.mcfg.dead_zone_px ** 2:
                x, y = self._last_out
        self._last_out = (x, y)
        return x, y

