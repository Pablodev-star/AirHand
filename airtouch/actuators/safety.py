"""Red de seguridad.

Un bug en el motor de gestos con el control activado significa clics aleatorios
en tu escritorio. Estas cuatro salidas de emergencia existen para que eso nunca
pase de ser una molestia:

  1. Modo seguro    - por defecto no se inyecta nada, solo se dibuja.
  2. Esc mantenido  - pausa inmediata.
  3. Raton fisico   - si mueves el raton de verdad, AirTouch se aparta.
  4. Mano abierta   - palma abierta un momento = pausa.
  5. Sin cara       - si no estas delante, se pausa solo.
"""
from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass, field

from ..config import SafetyConfig
from ..core.frame_state import FrameState
from ..core.screen import cursor_pos

user32 = ctypes.WinDLL("user32", use_last_error=True)
VK_ESCAPE = 0x1B


def _key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


@dataclass
class SafetyState:
    paused: bool = False
    reason: str = ""
    esc_progress: float = 0.0
    palm_progress: float = 0.0


@dataclass
class SafetyGuard:
    cfg: SafetyConfig
    state: SafetyState = field(default_factory=SafetyState)

    _esc_since: float | None = None
    _palm_since: float | None = None
    _no_face_since: float | None = None
    _expected_cursor: tuple[int, int] | None = None
    _override_until: float = 0.0

    # -------- lo llama el controlador tras inyectar un movimiento --------
    def note_injected_cursor(self, x: float, y: float) -> None:
        self._expected_cursor = (int(x), int(y))

    def resume(self) -> None:
        self.state.paused = False
        self.state.reason = ""
        self._esc_since = self._palm_since = self._no_face_since = None
        self._override_until = 0.0

    def pause(self, reason: str) -> None:
        self.state.paused = True
        self.state.reason = reason

    # -------- comprobacion por frame --------
    def check(self, fs: FrameState, now: float | None = None) -> SafetyState:
        now = now if now is not None else time.perf_counter()
        c = self.cfg

        # 1) Esc mantenido: alterna pausa
        if _key_down(VK_ESCAPE):
            if self._esc_since is None:
                self._esc_since = now
            held = (now - self._esc_since) * 1000.0
            self.state.esc_progress = min(held / max(c.esc_hold_ms, 1), 1.0)
            if held >= c.esc_hold_ms:
                self._esc_since = now + 10.0  # evita repetir hasta soltar
                if self.state.paused:
                    self.resume()
                else:
                    self.pause("Esc")
        else:
            self._esc_since = None
            self.state.esc_progress = 0.0

        # 2) raton fisico: si el cursor esta lejos de donde lo dejamos, no somos
        #    nosotros quien lo mueve -> cedemos el control un momento
        if c.mouse_override and self._expected_cursor is not None:
            cx, cy = cursor_pos()
            ex, ey = self._expected_cursor
            if abs(cx - ex) + abs(cy - ey) > c.mouse_override_px:
                self._override_until = now + 1.2
                self._expected_cursor = None

        # 3) palma abierta mantenida
        if c.open_palm_pause:
            palm = any(h.is_open_palm for h in fs.hands)
            if palm:
                if self._palm_since is None:
                    self._palm_since = now
                held = (now - self._palm_since) * 1000.0
                self.state.palm_progress = min(held / max(c.open_palm_ms, 1), 1.0)
                if held >= c.open_palm_ms:
                    self._palm_since = now + 10.0
                    if self.state.paused:
                        self.resume()
                    else:
                        self.pause("palma abierta")
            else:
                self._palm_since = None
                self.state.palm_progress = 0.0

        # 4) sin cara delante
        if c.pause_on_no_face:
            if fs.face.present:
                self._no_face_since = None
            else:
                if self._no_face_since is None:
                    self._no_face_since = now
                elif (now - self._no_face_since) * 1000.0 > c.no_face_timeout_ms:
                    if not self.state.paused:
                        self.pause("no se detecta al usuario")
        return self.state

    @property
    def overridden(self) -> bool:
        """True mientras el usuario esta usando el raton fisico."""
        return time.perf_counter() < self._override_until

    def may_inject(self) -> bool:
        return self.cfg.control_enabled and not self.state.paused and not self.overridden

    def status_text(self) -> str:
        if not self.cfg.control_enabled:
            return "Modo seguro (no se inyecta nada)"
        if self.state.paused:
            return f"En pausa - {self.state.reason}"
        if self.overridden:
            return "Cediendo el control al raton fisico"
        return "Control activo"
