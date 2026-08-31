"""Deteccion de la "catapulta" (el gesto de tirar chapas) -> clic derecho.

El gesto, tal cual se hace: el indice se curva hacia atras y se apoya contra el
pulgar — queda cerca, pero **poco tiempo** — y despues sale disparado hacia
delante hasta quedar recto.

Eso da tres senales que un pinch normal no tiene:

  1. **Curvatura**: en un pinch el indice esta casi estirado; aqui esta doblado.
  2. **Contacto breve**: un clic se mantiene; una catapulta se suelta al instante.
  3. **Velocidad de salida**: la extension crece de golpe, no poco a poco.

Se exigen las tres. Y como el clic izquierdo tambien se dispara al separar los
dedos, el motor retiene el clic unos milisegundos por si resulta ser esto.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from ..config import GestureConfig


class Phase(Enum):
    IDLE = auto()
    LOADED = auto()


@dataclass
class FlickDetector:
    cfg: GestureConfig
    phase: Phase = Phase.IDLE
    _loaded_at: float = 0.0
    _loaded_ext: float = 1.0
    _min_ext: float = 1.0
    _last_ext: float = 1.0
    _last_t: float = 0.0
    # telemetria para la interfaz
    charge: float = 0.0
    last_speed: float = 0.0

    @property
    def loaded(self) -> bool:
        return self.phase is Phase.LOADED

    def reset(self) -> None:
        self.phase = Phase.IDLE
        self._loaded_at = 0.0
        self.charge = 0.0

    def update(self, extension: float, pinch_ratio: float, t: float) -> bool:
        """Devuelve True en el instante exacto del disparo."""
        c = self.cfg
        if not c.flick_enabled:
            self.reset()
            return False

        dt = max(t - self._last_t, 1e-3) if self._last_t else 1e-3
        speed = (extension - self._last_ext) / dt
        self._last_ext, self._last_t = extension, t
        self.last_speed = speed

        curled = extension < c.flick_load_curl
        near = pinch_ratio < c.flick_contact_ratio
        loaded_now = curled and near

        if self.phase is Phase.IDLE:
            if loaded_now:
                self.phase = Phase.LOADED
                self._loaded_at = t
                self._loaded_ext = extension
                self._min_ext = extension
            self.charge = 0.0
            return False

        # --- fase LOADED ---
        held_ms = (t - self._loaded_at) * 1000.0
        self._min_ext = min(self._min_ext, extension)
        self.charge = min(held_ms / max(c.flick_min_load_ms, 1), 1.0)

        if loaded_now:
            if held_ms > c.flick_max_contact_ms:
                # lleva demasiado apoyado: era un pinch, no una catapulta
                self.reset()
            return False

        # ha dejado de estar cargado: comprobamos si fue un disparo
        fired = (
            held_ms >= c.flick_min_load_ms
            and held_ms <= c.flick_max_contact_ms
            and extension >= c.flick_release_curl
            and (extension - self._min_ext) >= c.flick_min_delta
            and speed >= c.flick_min_speed
        )
        self.reset()
        return fired
