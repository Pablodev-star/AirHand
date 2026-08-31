"""Motor de gestos: maquina de estados finita.

Entra un FrameState, salen eventos. El motor no toca el sistema operativo:
solo interpreta. Asi el "modo seguro" es real y no un parche.

Transiciones principales
------------------------
    IDLE --(mano)--> POINTING
    POINTING --(pinch sobre chrome)--> WINDOW_MOVE / WINDOW_RESIZE
    POINTING --(pinch)--> PINCH_PENDING --(suelta rapido)--> CLICK
                                        --(mueve)--> SCROLLING | DRAGGING
    POINTING --(catapulta)--> CLIC DERECHO
    *  --(pinch con las dos manos)--> ZOOMING
    *  --(puntero sobre el teclado)--> KEYBOARD
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..actuators import windows_mgr as wm
from ..config import Config
from ..core.filters import EMA, Hysteresis
from ..core.frame_state import FrameState, HandState
from ..core.keyboard_layout import (
    BACKSPACE, ENTER, LETTERS, SHIFT, SPACE, SYMBOLS, Key, KeyboardLayout,
)
from ..core.mapping import PointerMapper
from ..core.screen import primary_screen
from .events import EventType, GestureEvent, Mode
from .flick import FlickDetector


@dataclass
class ChromeTarget:
    hwnd: int
    rect: tuple[int, int, int, int]
    zone: str          # "move" | "resize"
    title: str = ""


@dataclass
class EngineOutput:
    """Todo lo que la UI necesita para dibujar el estado actual."""

    mode: Mode = Mode.IDLE
    pointer: tuple[float, float] | None = None
    raw_pointer: tuple[float, float] | None = None
    pinching: bool = False
    pinch_ratio: float = 1.0
    flick_charge: float = 0.0
    hands: int = 0
    chrome: ChromeTarget | None = None
    zoom_span: tuple[tuple[float, float], tuple[float, float]] | None = None
    keyboard: KeyboardLayout | None = None
    key_hover: str | None = None
    key_active: str | None = None
    accent_popup: tuple[Key, list[str], int] | None = None
    events: list[GestureEvent] = field(default_factory=list)
    note: str = ""


class GestureEngine:
    def __init__(self, cfg: Config, mapper: PointerMapper) -> None:
        self.cfg = cfg
        self.mapper = mapper
        self.mode = Mode.POINTING

        g = cfg.gestures
        self._pinch = {
            "Left": Hysteresis(g.pinch_on, g.pinch_off),
            "Right": Hysteresis(g.pinch_on, g.pinch_off),
        }
        self._flick = {"Left": FlickDetector(g), "Right": FlickDetector(g)}
        # la distancia de pinch en crudo tiembla lo suficiente como para cruzar
        # el umbral sola; una EMA corta lo elimina sin retardo perceptible
        a = cfg.filter.pinch_smoothing
        self._pinch_ema = {"Left": EMA(a), "Right": EMA(a)}

        # pinch en curso
        self._pinch_active = False
        self._pinch_t0 = 0.0
        self._pinch_p0 = (0.0, 0.0)
        self._pinch_anchor = (0.0, 0.0)
        self._palm0 = (0.0, 0.0)
        self._palm_prev = (0.0, 0.0)
        self._last_pointer: tuple[float, float] | None = None

        # scroll / drag
        self._scroll_accum = 0.0
        self._hscroll_accum = 0.0
        self._drag_down = False

        # ventanas
        self._chrome: ChromeTarget | None = None
        self._chrome_t = 0.0
        self._win_start_rect: tuple[int, int, int, int] | None = None
        self._win_start_ptr = (0.0, 0.0)

        # zoom
        self._zoom_prev: float | None = None
        self._zoom_accum = 0.0

        # teclado
        self.keyboard = KeyboardLayout()
        self.keyboard_visible = False
        self._kb_hover: str | None = None
        self._kb_active: str | None = None
        self._kb_last_emit = 0.0
        self._accent_popup: tuple[Key, list[str], int] | None = None

        self.ignore_hwnds: set[int] = set()
        self.paused = False
        self._last_click_t = -1e9
        # clic retenido: (instante, x, y). Se emite pasado flick_guard_ms si no
        # ha resultado ser una catapulta.
        self._pending_click: tuple[float, float, float] | None = None

    # ---------------- utilidades ----------------
    def retune(self) -> None:
        g = self.cfg.gestures
        for h in self._pinch.values():
            h.on_below, h.off_above = g.pinch_on, g.pinch_off
        for f in self._flick.values():
            f.cfg = g
        for e in self._pinch_ema.values():
            e.alpha = self.cfg.filter.pinch_smoothing

    def reset(self) -> None:
        self._pinch_active = False
        self._drag_down = False
        self._scroll_accum = self._hscroll_accum = 0.0
        self._zoom_prev = None
        self._win_start_rect = None
        self._accent_popup = None
        self._kb_active = None
        self._pending_click = None
        for h in self._pinch.values():
            h.reset()
        for f in self._flick.values():
            f.reset()
        for e in self._pinch_ema.values():
            e.reset()
        self.mapper.reset()
        self.mode = Mode.POINTING

    def show_keyboard(self, visible: bool) -> None:
        if visible == self.keyboard_visible:
            return
        self.keyboard_visible = visible
        self._accent_popup = None
        self._kb_active = self._kb_hover = None
        if visible:
            self._layout_keyboard()

    def _layout_keyboard(self) -> None:
        s = primary_screen()
        w = min(s.w * 0.78, 1400.0)
        h = w * 0.30
        x = s.x + (s.w - w) / 2
        y = s.bottom - h - s.h * 0.045
        self.keyboard.build(x, y, w, h)

    # ---------------- ciclo principal ----------------
    def update(self, fs: FrameState) -> EngineOutput:
        out = EngineOutput(hands=len(fs.hands))

        if self.paused:
            self._pending_click = None
            self._release_all(out)
            self.mode = Mode.PAUSED
            out.mode = self.mode
            return out

        primary = fs.primary
        if primary is None:
            # sin mano no puede llegar una catapulta: el clic retenido sale ya
            self._flush_pending_click(fs.t, out, force=True)
            self._release_all(out)
            self.mode = Mode.IDLE
            out.mode = self.mode
            self.mapper.reset()
            self._last_pointer = None
            return out

        # --- puntero ---
        px, py = self.mapper.update(primary.pointer, fs.t)
        out.pointer = (px, py)
        out.raw_pointer = (float(primary.pointer[0]), float(primary.pointer[1]))

        ratio = self._pinch_ema[primary.label].update(primary.pinch_ratio)
        out.pinch_ratio = ratio
        pinching = self._pinch[primary.label].update(ratio)
        out.pinching = pinching

        # --- zoom a dos manos: tiene prioridad sobre todo lo demas ---
        if self.cfg.gestures.zoom_enabled and len(fs.hands) >= 2:
            second = fs.secondary
            if second is not None:
                other_ratio = self._pinch_ema[second.label].update(second.pinch_ratio)
                other_pinch = self._pinch[second.label].update(other_ratio)
                if pinching and other_pinch:
                    self._handle_zoom(primary, second, out)
                    self.mode = Mode.ZOOMING
                    out.mode = self.mode
                    self._last_pointer = (px, py)
                    return out
        self._zoom_prev = None

        # --- catapulta -> clic derecho ---
        fd = self._flick[primary.label]
        if fd.update(primary.index_extension, ratio, fs.t):
            self._pending_click = None       # era catapulta, no clic izquierdo
            if self.keyboard_visible and self.keyboard.contains(px, py) \
                    and self._accent_popup is None:
                self._open_accent_popup(px, py, out)
            else:
                out.events.append(GestureEvent(EventType.MOVE, {"x": px, "y": py}))
                out.events.append(GestureEvent(EventType.RIGHT_CLICK))
                out.note = "clic derecho"
            # la catapulta invalida el pinch en curso
            self._pinch[primary.label].reset(False)
            self._pinch_active = False
            pinching = False
        out.flick_charge = fd.charge
        # ya sabemos si era catapulta: se puede resolver el clic retenido
        self._flush_pending_click(fs.t, out)

        # --- teclado virtual ---
        if self.keyboard_visible:
            if self._accent_popup is not None or self.keyboard.contains(px, py):
                self._handle_keyboard(px, py, pinching, fs.t, out)
                self.mode = Mode.KEYBOARD
                out.mode = self.mode
                out.keyboard = self.keyboard
                out.key_hover, out.key_active = self._kb_hover, self._kb_active
                out.accent_popup = self._accent_popup
                self._last_pointer = (px, py)
                return out
            self._kb_hover = self._kb_active = None
            out.keyboard = self.keyboard

        # --- deteccion del chrome de ventana (solo con la mano abierta) ---
        if not pinching and self.cfg.gestures.window_chrome_enabled:
            if fs.t - self._chrome_t > 0.08:
                self._chrome_t = fs.t
                self._chrome = self._query_chrome(px, py)
            out.chrome = self._chrome

        # --- transiciones de pinch ---
        if pinching and not self._pinch_active:
            self._on_pinch_down(px, py, primary, fs.t, out)
        elif pinching and self._pinch_active:
            self._on_pinch_hold(px, py, primary, fs.t, out)
        elif not pinching and self._pinch_active:
            self._on_pinch_up(px, py, fs.t, out)
        else:
            self.mode = Mode.POINTING
            out.events.append(GestureEvent(EventType.MOVE, {"x": px, "y": py}))

        if self.mode in (Mode.WINDOW_MOVE, Mode.WINDOW_RESIZE):
            out.chrome = self._chrome

        # El cursor se ancla SOLO mientras decide si es un clic: asi el clic cae
        # justo donde apuntabas. Durante el scroll sigue moviendose en tiempo
        # real, que es lo que uno espera ver.
        if self._pinch_active and self.mode is Mode.PINCH_PENDING:
            out.pointer = self._pinch_anchor

        out.mode = self.mode
        self._last_pointer = (px, py)
        return out

    # ---------------- pinch ----------------
    def _palm_px(self, hand: HandState) -> tuple[float, float]:
        """Palma en pixeles de pantalla.

        La palma es el punto estable de la mano: no se desplaza al juntar los
        dedos, asi que es lo que hay que usar para medir arrastres.
        """
        t = self.mapper.target
        return float(hand.palm[0]) * t.w, float(hand.palm[1]) * t.h

    def _on_pinch_down(self, px: float, py: float, hand: HandState, t: float,
                       out: EngineOutput) -> None:
        self._pinch_active = True
        self._pinch_t0 = t
        self._pinch_p0 = (px, py)
        self._pinch_anchor = (px, py)
        self._palm0 = self._palm_prev = self._palm_px(hand)
        self._scroll_accum = self._hscroll_accum = 0.0

        ch = self._chrome
        if ch is not None and self.cfg.gestures.window_chrome_enabled:
            info = wm.get_info(ch.hwnd)
            if info is not None:
                wm.restore_if_maximized(ch.hwnd)
                info = wm.get_info(ch.hwnd) or info
                self._win_start_rect = info.rect
                self._win_start_ptr = (px, py)
                self.mode = Mode.WINDOW_MOVE if ch.zone == "move" else Mode.WINDOW_RESIZE
                out.note = "moviendo ventana" if ch.zone == "move" else "redimensionando"
                return

        self.mode = Mode.PINCH_PENDING
        out.events.append(GestureEvent(EventType.MOVE, {"x": px, "y": py}))

    def _on_pinch_hold(self, px: float, py: float, hand: HandState, t: float,
                       out: EngineOutput) -> None:
        g = self.cfg.gestures
        palm = self._palm_px(hand)
        dx = palm[0] - self._palm0[0]
        dy = palm[1] - self._palm0[1]
        travel = (dx * dx + dy * dy) ** 0.5

        if self.mode in (Mode.WINDOW_MOVE, Mode.WINDOW_RESIZE) and self._win_start_rect:
            # La ventana sigue al PUNTERO, no a la palma: la palma se mueve con
            # ganancia 1 y la ventana se quedaba corta respecto a tu mano.
            self._handle_window((px, py), out)
            self._palm_prev = palm
            return

        # ventana muerta: al cerrar el pinch la mano se agita un poco, y sin
        # esto cada clic se convertia en scroll
        if (t - self._pinch_t0) * 1000.0 < g.pinch_grace_ms:
            self._palm_prev = palm
            return

        # El scroll solo se arma cuando el pinch lleva mantenido mas de lo que
        # dura un clic. Sin atajos: si se permitiera armar por recorrido, el
        # desplazamiento natural de la mano al pinzar volveria a colarse.
        armed = (t - self._pinch_t0) * 1000.0 >= g.scroll_arm_ms

        if self.mode is Mode.PINCH_PENDING and armed and travel > g.click_max_travel_px:
            self.mode = Mode.DRAGGING if g.pinch_drag_mode == "drag" else Mode.SCROLLING
            if self.mode is Mode.DRAGGING:
                out.events.append(GestureEvent(
                    EventType.MOVE, {"x": self._pinch_p0[0], "y": self._pinch_p0[1]}))
                out.events.append(GestureEvent(EventType.LEFT_DOWN))
                self._drag_down = True
            else:
                # el cursor se ancla donde empezo el scroll
                out.events.append(GestureEvent(
                    EventType.MOVE, {"x": self._pinch_anchor[0], "y": self._pinch_anchor[1]}))

        if self.mode is Mode.DRAGGING:
            out.events.append(GestureEvent(EventType.MOVE, {"x": px, "y": py}))
        elif self.mode is Mode.SCROLLING:
            # el cursor acompana al scroll en vez de quedarse clavado
            out.events.append(GestureEvent(EventType.MOVE, {"x": px, "y": py}))
            self._handle_scroll(palm, out)
        self._palm_prev = palm

    def _on_pinch_up(self, px: float, py: float, t: float, out: EngineOutput) -> None:
        g = self.cfg.gestures
        dt_ms = (t - self._pinch_t0) * 1000.0
        dx = self._palm_prev[0] - self._palm0[0]
        dy = self._palm_prev[1] - self._palm0[1]
        travel = (dx * dx + dy * dy) ** 0.5

        if self._drag_down:
            out.events.append(GestureEvent(EventType.LEFT_UP))
            self._drag_down = False
        elif self.mode is Mode.PINCH_PENDING and dt_ms <= g.click_max_ms \
                and travel <= g.click_max_travel_px:
            # no se emite todavia: puede ser el final de una catapulta
            self._pending_click = (t, self._pinch_p0[0], self._pinch_p0[1])

        self._pinch_active = False
        self._win_start_rect = None
        self.mode = Mode.POINTING

    def _flush_pending_click(self, now: float, out: EngineOutput,
                             force: bool = False) -> None:
        """Emite el clic retenido si ya no puede ser una catapulta."""
        if self._pending_click is None:
            return
        t0, x, y = self._pending_click
        guard = self.cfg.gestures.flick_guard_ms if self.cfg.gestures.flick_enabled else 0
        if not force and (now - t0) * 1000.0 < guard:
            return
        self._pending_click = None
        out.events.append(GestureEvent(EventType.MOVE, {"x": x, "y": y}))
        if (t0 - self._last_click_t) * 1000.0 < 420:
            out.events.append(GestureEvent(EventType.DOUBLE_CLICK))
            out.note = "doble clic"
            self._last_click_t = -1e9
        else:
            out.events.append(GestureEvent(EventType.CLICK))
            out.note = "clic"
            self._last_click_t = t0

    def _release_all(self, out: EngineOutput) -> None:
        if self._drag_down:
            out.events.append(GestureEvent(EventType.LEFT_UP))
            self._drag_down = False
        self._pinch_active = False
        self._win_start_rect = None
        self._zoom_prev = None
        for h in self._pinch.values():
            h.reset(False)
        for f in self._flick.values():
            f.reset()

    # ---------------- acciones concretas ----------------
    def _handle_scroll(self, palm: tuple[float, float], out: EngineOutput) -> None:
        g = self.cfg.gestures
        prev = self._palm_prev
        dy = palm[1] - prev[1]
        dx = palm[0] - prev[0]

        # mano hacia arriba (dy negativo) -> scroll hacia abajo
        notches = dy * g.scroll_gain / 100.0
        if g.scroll_invert:
            notches = -notches
        self._scroll_accum += notches
        whole = int(self._scroll_accum)
        if whole:
            self._scroll_accum -= whole
            out.events.append(GestureEvent(EventType.SCROLL, {"notches": whole}))

        if g.hscroll_enabled and abs(dx) > abs(dy) * 1.6:
            hn = dx * g.scroll_gain / 140.0
            self._hscroll_accum += hn
            hwhole = int(self._hscroll_accum)
            if hwhole:
                self._hscroll_accum -= hwhole
                out.events.append(GestureEvent(EventType.HSCROLL, {"notches": hwhole}))

    def _handle_window(self, pointer: tuple[float, float], out: EngineOutput) -> None:
        if self._win_start_rect is None or self._chrome is None:
            return
        left, top, right, bottom = self._win_start_rect
        dx = pointer[0] - self._win_start_ptr[0]
        dy = pointer[1] - self._win_start_ptr[1]
        hwnd = self._chrome.hwnd
        m = self.cfg.gestures.window_min_size

        if self.mode is Mode.WINDOW_MOVE:
            nl, nt = int(left + dx), int(top + dy)
            nw, nh = right - left, bottom - top
        else:
            nl, nt = left, top
            nw = max(m, int(right - left + dx))
            nh = max(m, int(bottom - top + dy))

        # zona muerta: sin esto la ventana vibra un pixel constantemente
        cur = self._chrome.rect
        if abs(nl - cur[0]) < 2 and abs(nt - cur[1]) < 2 \
                and abs((nl + nw) - cur[2]) < 2 and abs((nt + nh) - cur[3]) < 2:
            return

        # el chrome dibujado se actualiza al vuelo para que la barra y la
        # esquina viajen pegadas a la ventana mientras la mueves
        self._chrome.rect = (nl, nt, nl + nw, nt + nh)
        out.events.append(GestureEvent(EventType.WINDOW_BOUNDS, {
            "hwnd": hwnd, "left": nl, "top": nt, "width": nw, "height": nh,
        }))

    def _handle_zoom(self, a: HandState, b: HandState, out: EngineOutput) -> None:
        s = primary_screen()
        pa = np.array([a.pinch_point[0] * s.w, a.pinch_point[1] * s.h])
        pb = np.array([b.pinch_point[0] * s.w, b.pinch_point[1] * s.h])
        dist = float(np.linalg.norm(pa - pb))
        out.zoom_span = ((float(pa[0]), float(pa[1])), (float(pb[0]), float(pb[1])))

        if self._zoom_prev is None:
            self._zoom_prev = dist
            return

        delta = dist - self._zoom_prev
        self._zoom_prev = dist
        self._zoom_accum += delta * self.cfg.gestures.zoom_gain / 90.0
        whole = int(self._zoom_accum)
        if whole:
            self._zoom_accum -= whole
            out.events.append(GestureEvent(EventType.ZOOM, {"notches": whole}))
            out.note = "zoom +" if whole > 0 else "zoom -"

    def _query_chrome(self, px: float, py: float) -> ChromeTarget | None:
        g = self.cfg.gestures
        w, zone = wm.find_chrome_target(
            px, py, g.window_grab_band_px, g.window_corner_px, self.ignore_hwnds
        )
        if w is None or not zone:
            return None
        return ChromeTarget(w.hwnd, w.rect, zone, w.title)

    # ---------------- teclado ----------------
    def _open_accent_popup(self, px: float, py: float, out: EngineOutput) -> None:
        key = self.keyboard.hit(px, py, pad=self.keyboard.gap)
        if key is None:
            return
        options = key.accents()
        if not options:
            out.note = "esa tecla no tiene variantes"
            return
        self._accent_popup = (key, options, 0)
        out.note = "variantes de " + key.ident

    def accent_popup_geometry(self) -> tuple[float, float, float, float, int] | None:
        """(x0, y, ancho_celda, alto, n) del desplegable de variantes."""
        if self._accent_popup is None:
            return None
        key, options, _ = self._accent_popup
        n = len(options)
        cell = max(key.w, 46.0)
        total = cell * n
        kx, ky, kw, _kh = self.keyboard.rect
        x0 = min(max(key.cx - total / 2, kx), kx + kw - total)
        y = key.y - key.h - self.keyboard.gap * 2
        return x0, y, cell, key.h, n

    def _handle_keyboard(self, px: float, py: float, pinching: bool, t: float,
                         out: EngineOutput) -> None:
        # popup de acentos abierto: el puntero elige, el pinch confirma
        if self._accent_popup is not None:
            geom = self.accent_popup_geometry()
            if geom is None:
                return
            x0, _y, cell, _h, n = geom
            key, options, _ = self._accent_popup
            idx = int((px - x0) // cell)
            idx = max(0, min(n - 1, idx))
            self._accent_popup = (key, options, idx)
            if pinching and not self._pinch_active:
                self._pinch_active = True
                out.events.append(GestureEvent(EventType.KEY_TEXT, {"text": options[idx]}))
                out.note = options[idx]
                self._accent_popup = None
            elif not pinching:
                self._pinch_active = False
            return

        key = self.keyboard.hit(px, py, pad=self.keyboard.gap * 0.5)
        self._kb_hover = key.ident if key else None

        if pinching and not self._pinch_active:
            self._pinch_active = True
            if key is not None:
                self._kb_active = key.ident
                self._kb_last_emit = t
                self._emit_key(key, out)
        elif pinching and self._pinch_active and key is not None:
            # autorepeticion en borrar y espacio
            if key.ident in (BACKSPACE, SPACE) and \
                    (t - self._kb_last_emit) * 1000 > self.cfg.gestures.key_repeat_ms:
                self._kb_last_emit = t
                self._emit_key(key, out)
        elif not pinching:
            self._pinch_active = False
            self._kb_active = None

    def _emit_key(self, key: Key, out: EngineOutput) -> None:
        kb = self.keyboard
        ident = key.ident
        if ident == SHIFT:
            kb.shift = not kb.shift
            kb.relabel()
            out.note = "mayusculas " + ("on" if kb.shift else "off")
            return
        if ident in (SYMBOLS, LETTERS):
            kb.symbols = not kb.symbols
            x, y, w, h = kb.rect
            kb.build(x, y, w, h)
            return
        if ident == BACKSPACE:
            out.events.append(GestureEvent(EventType.KEY_VK, {"key": "backspace"}))
            return
        if ident == ENTER:
            out.events.append(GestureEvent(EventType.KEY_VK, {"key": "enter"}))
            return
        if ident == SPACE:
            out.events.append(GestureEvent(EventType.KEY_TEXT, {"text": " "}))
            return

        text = kb.output_for(key)
        out.events.append(GestureEvent(EventType.KEY_TEXT, {"text": text}))
        if kb.shift:
            kb.shift = False
            kb.relabel()

    # ---------------- introspeccion ----------------
    def describe(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "pinch": self._pinch_active,
            "keyboard": self.keyboard_visible,
            "chrome": None if self._chrome is None else self._chrome.zone,
        }
