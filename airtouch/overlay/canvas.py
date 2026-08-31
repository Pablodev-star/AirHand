"""Overlay transparente que cubre todo el escritorio.

Una sola ventana sin marco, translucida y atravesable por el raton, sobre la
que se dibuja todo: el cursor, la barra y la esquina de las ventanas, el
teclado virtual y el HUD.

Dos cosas importantes de este archivo:

* **Coordenadas.** El motor trabaja en pixeles fisicos (los que usa SendInput).
  Qt dibuja en logicos. Con la pantalla al 150 % no son lo mismo, asi que todo
  lo que entra se convierte con ``_to_local`` / ``_sc``.
* **Repintado parcial.** Repintar 2560x1440 translucidos a 60 Hz cuesta CPU y
  GPU de verdad. Se lleva la cuenta de que rectangulos ha tocado cada elemento
  y solo se repinta esa zona.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QWidget

from ..config import Config
from ..core.screen import virtual_screen
from ..gestures.engine import EngineOutput
from ..gestures.events import Mode
from . import style as S

# color del cursor segun lo que estas haciendo
_MODE_TINT = {
    Mode.POINTING: "neutral",
    Mode.PINCH_PENDING: "pinch",
    Mode.SCROLLING: "scroll",
    Mode.DRAGGING: "drag",
    Mode.WINDOW_MOVE: "window",
    Mode.WINDOW_RESIZE: "window",
    Mode.ZOOMING: "zoom",
    Mode.KEYBOARD: "neutral",
}


class OverlayCanvas(QWidget):
    def __init__(self, cfg: Config) -> None:
        super().__init__(None)
        self.cfg = cfg
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._origin = (0, 0)
        self._dpr = 1.0
        self.refresh_geometry()

        self.out: EngineOutput | None = None
        self.engine_ref = None
        self._last_t = time.perf_counter()

        # valores animados
        self._cursor_xy = (self.width() / 2.0, self.height() / 2.0)
        self._cursor_a = 0.0
        self._pinch_a = 0.0
        self._chrome_a = 0.0
        self._chrome_w = 0.0          # 0..1: crecimiento de la barra desde el centro
        self._chrome_geom: tuple[float, float, float, float] | None = None
        self._chrome_zone = ""
        self._kb_a = 0.0
        self._popup_a = 0.0
        self._hud_a = 0.0
        self._note = ""
        self._note_until = 0.0
        self._tint = "neutral"
        self._tint_mix = 0.0
        self._prev_tint = "neutral"

        self._damage = QRegion()      # zona repintada el frame anterior
        self._hud_rects: list[QRect] = []

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # ---------------- ciclo de vida ----------------
    def show_overlay(self) -> None:
        self._apply_native_flags()
        self.show()
        self._timer.start()

    def hide_overlay(self) -> None:
        self._timer.stop()
        self.hide()

    def _apply_native_flags(self) -> None:
        try:
            import ctypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x20
            WS_EX_LAYERED = 0x80000
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x80
            hwnd = int(self.winId())
            get = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            setf = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            ex = get(hwnd, GWL_EXSTYLE)
            setf(hwnd, GWL_EXSTYLE,
                 ex | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE
                 | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def hwnd(self) -> int:
        try:
            return int(self.winId())
        except Exception:
            return 0

    def refresh_geometry(self) -> None:
        from PySide6.QtGui import QGuiApplication

        vs = virtual_screen()
        self._origin = (vs.x, vs.y)
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            self._dpr = float(screen.devicePixelRatio()) or 1.0
            self.setGeometry(screen.virtualGeometry())
        else:
            self._dpr = 1.0
            self.setGeometry(vs.x, vs.y, vs.w, vs.h)

    # ---------------- entrada de datos ----------------
    def set_output(self, out: EngineOutput) -> None:
        self.out = out
        if out.note:
            self._note = out.note
            self._note_until = time.perf_counter() + 1.1

    def _to_local(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self._origin[0]) / self._dpr,
                (y - self._origin[1]) / self._dpr)

    def _sc(self, v: float) -> float:
        return v / self._dpr

    # ---------------- colores ----------------
    def _tint_color(self, name: str) -> QColor:
        return {
            "neutral": S.CURSOR_CORE,
            "pinch": S.TINT_PINCH,
            "scroll": S.TINT_SCROLL,
            "drag": S.TINT_DRAG,
            "window": S.TINT_WINDOW,
            "zoom": S.TINT_ZOOM,
        }.get(name, S.CURSOR_CORE)

    def _current_tint(self) -> QColor:
        a = self._tint_color(self._prev_tint)
        b = self._tint_color(self._tint)
        k = self._tint_mix
        return QColor(
            int(a.red() + (b.red() - a.red()) * k),
            int(a.green() + (b.green() - a.green()) * k),
            int(a.blue() + (b.blue() - a.blue()) * k),
        )

    # ---------------- animacion ----------------
    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(now - self._last_t, 0.1)
        self._last_t = now
        out = self.out

        want_cursor = bool(out and out.pointer and self.cfg.ui.show_cursor)
        self._cursor_a = S.smooth(self._cursor_a, 1.0 if want_cursor else 0.0,
                                  dt, S.ANIM_FAST)
        if out and out.pointer:
            self._cursor_xy = self._to_local(*out.pointer)
        self._pinch_a = S.smooth(self._pinch_a,
                                 1.0 if (out and out.pinching) else 0.0, dt, 0.07)

        tint = _MODE_TINT.get(out.mode, "neutral") if out else "neutral"
        if tint != self._tint:
            self._prev_tint = self._tint
            self._tint = tint
            self._tint_mix = 0.0
        self._tint_mix = min(1.0, self._tint_mix + dt / 0.14)

        chrome = out.chrome if out else None
        if chrome is not None:
            left, top, right, bottom = chrome.rect
            lx, ly = self._to_local(left, top)
            self._chrome_geom = (lx, ly, self._sc(right - left),
                                 self._sc(bottom - top))
            self._chrome_zone = chrome.zone
        self._chrome_a = S.smooth(self._chrome_a, 1.0 if chrome else 0.0, dt, 0.10)
        # la anchura crece desde el centro, pero solo un poco
        self._chrome_w = S.smooth(self._chrome_w, 1.0 if chrome else 0.0, dt, 0.13)

        kb_on = bool(out and out.keyboard and out.mode is not Mode.PAUSED
                     and self.cfg.gestures.keyboard_enabled
                     and getattr(self.engine_ref, "keyboard_visible", False))
        self._kb_a = S.smooth(self._kb_a, 1.0 if kb_on else 0.0, dt, S.ANIM_SLOW)
        self._popup_a = S.smooth(self._popup_a,
                                 1.0 if (out and out.accent_popup) else 0.0, dt, 0.13)

        hud_on = bool(out and self.cfg.ui.show_hud and out.mode is not Mode.IDLE)
        self._hud_a = S.smooth(self._hud_a, 1.0 if hud_on else 0.0, dt, S.ANIM_SLOW)

        # --- repintado parcial ---
        region = self._current_region()
        damage = QRegion(region)
        damage += self._damage
        self._damage = region
        if not damage.isEmpty():
            self.update(damage)

    def _current_region(self) -> QRegion:
        """Rectangulos que ocupa ahora mismo cada elemento visible."""
        region = QRegion()
        out = self.out

        if self._cursor_a > 0.01:
            x, y = self._cursor_xy
            r = S.CURSOR_GLOW_RADIUS + 26
            region += QRect(int(x - r), int(y - r), int(r * 2), int(r * 2))

        if self._chrome_a > 0.01 and self._chrome_geom:
            gx, gy, gw, gh = self._chrome_geom
            if self._chrome_zone == "move":
                pad = 46
                region += QRect(int(gx - pad), int(gy + gh - pad),
                                int(gw + pad * 2), int(pad * 2.4))
            else:
                r = S.CHROME_CORNER_RADIUS + 34
                region += QRect(int(gx + gw - r), int(gy + gh - r),
                                int(r * 2), int(r * 2))

        if out is not None and out.zoom_span:
            (ax, ay), (bx, by) = out.zoom_span
            ax, ay = self._to_local(ax, ay)
            bx, by = self._to_local(bx, by)
            region += QRect(int(min(ax, bx) - 70), int(min(ay, by) - 70),
                            int(abs(bx - ax) + 140), int(abs(by - ay) + 140))

        if self._kb_a > 0.01 and out is not None and out.keyboard \
                and out.keyboard.keys:
            kx, ky, kw, kh = out.keyboard.rect
            lx, ly = self._to_local(kx, ky)
            pad = 90
            region += QRect(int(lx - pad), int(ly - pad),
                            int(self._sc(kw) + pad * 2), int(self._sc(kh) + pad * 2))

        # el HUD son dos pastillas pequenas: se usa el rectangulo que ocuparon
        # de verdad al pintarlas, no una franja de lado a lado
        if self._hud_a > 0.01:
            if self._hud_rects:
                for r in self._hud_rects:
                    region += r.adjusted(-70, -12, 70, 12)
            else:
                cx = self.width() // 2
                region += QRect(cx - 340, 20, 680, 56)
                region += QRect(cx - 340, self.height() - 96, 680, 76)
        return region

    # ---------------- pintado ----------------
    def paintEvent(self, _ev) -> None:  # noqa: N802
        out = self.out
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        if self._kb_a > 0.01 and out and out.keyboard:
            self._paint_keyboard(p, out)
        if self._chrome_a > 0.01 and self._chrome_geom:
            self._paint_chrome(p)
        if out and out.zoom_span:
            self._paint_zoom(p, out)
        if self._cursor_a > 0.01:
            self._paint_cursor(p, out)
        if self._hud_a > 0.01 and out:
            self._paint_hud(p, out)
        p.end()

    @staticmethod
    def _glow(alpha: float) -> QColor:
        c = QColor(S.GLOW_TINT)
        c.setAlpha(max(0, min(255, int(alpha))))
        return c

    # ---- cursor ----
    def _paint_cursor(self, p: QPainter, out: EngineOutput | None) -> None:
        x, y = self._cursor_xy
        a = self._cursor_a
        pinch = self._pinch_a
        tint = self._current_tint()
        mode = out.mode if out else Mode.POINTING

        # 1) halo suave: hace que se vea sobre fondos oscuros
        glow_r = S.CURSOR_GLOW_RADIUS * (1.0 - 0.16 * pinch)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(S.glow_gradient(x, y, glow_r, self._glow(52 * a))))
        p.drawEllipse(QPointF(x, y), glow_r, glow_r)

        # 2) anillo exterior en color de estado
        ring_r = S.CURSOR_RING_RADIUS * (1.0 - 0.26 * pinch)
        ring = QColor(tint)
        ring.setAlpha(int(150 * a))
        p.setPen(QPen(ring, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(x, y), ring_r, ring_r)

        # 3) contorno oscuro: hace que se vea sobre fondos claros
        outline = QColor(12, 14, 18, int(150 * a))
        core_r = S.CURSOR_RADIUS * (1.0 - 0.30 * pinch)
        p.setPen(QPen(outline, 2.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(x, y), core_r + 1.3, core_r + 1.3)

        # 4) nucleo
        core = QColor(tint)
        core.setAlpha(int(248 * a))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(core)
        p.drawEllipse(QPointF(x, y), core_r, core_r)

        # 5) pistas de lo que estas haciendo
        if mode is Mode.SCROLLING:
            self._paint_scroll_hint(p, x, y, ring_r, a)
        elif mode is Mode.WINDOW_MOVE:
            self._paint_move_hint(p, x, y, ring_r, a)
        elif mode is Mode.WINDOW_RESIZE:
            self._paint_resize_hint(p, x, y, ring_r, a)

        # 6) carga de la catapulta: solo cuando va en serio, y con etiqueta
        charge = out.flick_charge if out else 0.0
        if charge > 0.35:
            k = (charge - 0.35) / 0.65
            arc_r = ring_r + 9
            pen = QPen(QColor(S.TINT_FLICK), 3.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(x - arc_r, y - arc_r, arc_r * 2, arc_r * 2)
            p.drawArc(rect, 90 * 16, -int(k * 360 * 16))
            if charge > 0.75:
                self._label(p, "clic derecho", x, y + arc_r + 18,
                            QColor(S.TINT_FLICK), a)

    def _arrow(self, p: QPainter, cx: float, cy: float, dx: float, dy: float,
               size: float, col: QColor) -> None:
        pen = QPen(col, 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        tip = QPointF(cx + dx * size, cy + dy * size)
        # dos alas perpendiculares
        px_, py_ = -dy, dx
        w = size * 0.42
        b = size * 0.42
        p.drawLine(tip, QPointF(tip.x() - dx * b + px_ * w, tip.y() - dy * b + py_ * w))
        p.drawLine(tip, QPointF(tip.x() - dx * b - px_ * w, tip.y() - dy * b - py_ * w))

    def _paint_scroll_hint(self, p: QPainter, x: float, y: float, r: float,
                           a: float) -> None:
        col = QColor(S.TINT_SCROLL)
        col.setAlpha(int(225 * a))
        self._arrow(p, x, y, 0, -1, r + 11, col)
        self._arrow(p, x, y, 0, 1, r + 11, col)

    def _paint_move_hint(self, p: QPainter, x: float, y: float, r: float,
                         a: float) -> None:
        col = QColor(S.TINT_WINDOW)
        col.setAlpha(int(225 * a))
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            self._arrow(p, x, y, dx, dy, r + 11, col)

    def _paint_resize_hint(self, p: QPainter, x: float, y: float, r: float,
                           a: float) -> None:
        col = QColor(S.TINT_WINDOW)
        col.setAlpha(int(225 * a))
        d = 0.7071
        self._arrow(p, x, y, -d, -d, r + 11, col)
        self._arrow(p, x, y, d, d, r + 11, col)

    def _label(self, p: QPainter, text: str, cx: float, cy: float,
               color: QColor, a: float) -> None:
        p.setFont(S.font(10))
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 16
        h = fm.height() + 7
        rect = QRectF(cx - w / 2, cy - h / 2, w, h)
        bg = QColor(S.GLASS_FILL)
        bg.setAlpha(int(bg.alpha() * a))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, h / 2, h / 2)
        c = QColor(color)
        c.setAlpha(int(240 * a))
        p.setPen(c)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    # ---- chrome de ventana ----
    def _paint_chrome(self, p: QPainter) -> None:
        assert self._chrome_geom is not None
        x, y, w, h = self._chrome_geom
        a = self._chrome_a
        grow = self._chrome_w

        if self._chrome_zone == "move":
            full = max(S.CHROME_BAR_MIN_W, min(S.CHROME_BAR_MAX_W, w * 0.30))
            # crece desde el centro, pero solo un poco: de 72 % a 100 %
            bw = full * (0.72 + 0.28 * grow)
            bh = S.CHROME_BAR_HEIGHT
            bx = x + (w - bw) / 2
            by = y + h + S.CHROME_BAR_GAP

            # brillo: varias pastillas apiladas, cada una mas grande y mas
            # tenue. Da un halo continuo, sin el borde duro de un degradado
            # radial recortado.
            for i, (spread, alpha) in enumerate(((9.0, 16), (5.0, 26), (2.0, 40))):
                halo = QColor(S.CHROME_BAR)
                halo.setAlpha(int(alpha * a))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(halo)
                rr = QRectF(bx - spread, by - spread, bw + spread * 2,
                            bh + spread * 2)
                p.drawRoundedRect(rr, rr.height() / 2, rr.height() / 2)

            col = QColor(S.CHROME_BAR)
            col.setAlpha(int(col.alpha() * a))
            p.setBrush(col)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), bh / 2, bh / 2)
            return

        # --- esquina de redimension ---
        # El arco ocupa el cuadrante inferior derecho: sus extremos apuntan
        # hacia arriba (por el lado derecho) y hacia la izquierda (por abajo),
        # que es como se ve la esquina de una ventana redondeada.
        r = S.CHROME_CORNER_RADIUS * (0.82 + 0.18 * grow)
        cx = x + w - r * 0.30
        cy = y + h - r * 0.30
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)

        for spread, alpha in ((7.0, 18), (3.5, 30)):
            halo = QColor(S.CHROME_BAR)
            halo.setAlpha(int(alpha * a))
            pen = QPen(halo, S.CHROME_CORNER_THICK + spread * 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(rect, 0, -90 * 16)

        hard = QColor(S.CHROME_BAR)
        hard.setAlpha(int(236 * a))
        pen = QPen(hard, S.CHROME_CORNER_THICK)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 0, -90 * 16)

    # ---- zoom a dos manos ----
    def _paint_zoom(self, p: QPainter, out: EngineOutput) -> None:
        (ax, ay), (bx, by) = out.zoom_span
        ax, ay = self._to_local(ax, ay)
        bx, by = self._to_local(bx, by)
        col = QColor(S.TINT_ZOOM)

        line = QColor(col)
        line.setAlpha(150)
        p.setPen(QPen(line, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(ax, ay), QPointF(bx, by))

        # flechas hacia fuera en cada extremo: dicen "separa para ampliar"
        dx, dy = bx - ax, by - ay
        dist = math.hypot(dx, dy) or 1.0
        ux, uy = dx / dist, dy / dist
        arrow = QColor(col)
        arrow.setAlpha(230)
        self._arrow(p, ax, ay, -ux, -uy, 22, arrow)
        self._arrow(p, bx, by, ux, uy, 22, arrow)

        p.setPen(Qt.PenStyle.NoPen)
        for px_, py_ in ((ax, ay), (bx, by)):
            halo = QColor(col)
            halo.setAlpha(70)
            p.setBrush(halo)
            p.drawEllipse(QPointF(px_, py_), 13, 13)
            p.setBrush(col)
            p.drawEllipse(QPointF(px_, py_), 7, 7)

        mx, my = (ax + bx) / 2, (ay + by) / 2
        self._pill(p, f"zoom · separa o junta las manos", mx, my - 34,
                   QColor(S.HUD_TEXT), 12)

    # ---- teclado virtual ----
    def _paint_keyboard(self, p: QPainter, out: EngineOutput) -> None:
        kb = out.keyboard
        if kb is None or not kb.keys:
            return
        a = self._kb_a
        x, y, w, h = kb.rect
        w, h = self._sc(w), self._sc(h)
        lx, ly = self._to_local(x, y)
        ly += (1.0 - a) * 40.0

        pad = w * 0.014
        panel = QRectF(lx - pad, ly - pad, w + pad * 2, h + pad * 2)

        p.setPen(Qt.PenStyle.NoPen)
        fill = QColor(S.GLASS_FILL_STRONG)
        fill.setAlpha(int(fill.alpha() * a))
        p.setBrush(fill)
        p.drawRoundedRect(panel, S.PANEL_RADIUS, S.PANEL_RADIUS)

        p.setBrush(QBrush(S.glass_gradient(panel.x(), panel.y(),
                                           panel.width(), panel.height() * 0.5)))
        p.drawRoundedRect(panel, S.PANEL_RADIUS, S.PANEL_RADIUS)

        gb = QColor(S.GLASS_BORDER)
        gb.setAlpha(int(S.GLASS_BORDER.alpha() * a))
        p.setPen(QPen(gb, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(panel, S.PANEL_RADIUS, S.PANEL_RADIUS)

        p.setFont(S.font(max(10, int(self._sc(kb.key_h) * 0.36))))
        for key in kb.keys:
            kx, ky = self._to_local(key.x, key.y)
            ky += (1.0 - a) * 40.0
            rect = QRectF(kx, ky, self._sc(key.w), self._sc(key.h))

            if key.ident == out.key_active:
                fill = QColor(S.KEY_FILL_ACTIVE)
                text_col = QColor(S.KEY_TEXT_ACTIVE)
            elif key.ident == out.key_hover:
                fill = QColor(S.KEY_FILL_HOVER)
                text_col = QColor(S.KEY_TEXT)
            else:
                fill = QColor(S.KEY_FILL)
                text_col = QColor(S.KEY_TEXT)
            fill.setAlpha(int(fill.alpha() * a))
            text_col.setAlpha(int(text_col.alpha() * a))

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(rect, S.KEY_RADIUS, S.KEY_RADIUS)
            kbd = QColor(S.KEY_BORDER)
            kbd.setAlpha(int(S.KEY_BORDER.alpha() * a))
            p.setPen(QPen(kbd, 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, S.KEY_RADIUS, S.KEY_RADIUS)

            p.setPen(text_col)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, key.label)

            if key.accents() and key.ident != out.key_active:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self._glow(120 * a))
                p.drawEllipse(QPointF(rect.right() - 7, rect.top() + 7), 1.8, 1.8)

        if out.accent_popup is not None and self.engine_ref is not None:
            self._paint_accents(p, out)

    def _paint_accents(self, p: QPainter, out: EngineOutput) -> None:
        geom = self.engine_ref.accent_popup_geometry()
        if geom is None or out.accent_popup is None:
            return
        x0, y, cell, h, _n = geom
        cell, h = self._sc(cell), self._sc(h)
        _key, options, idx = out.accent_popup
        a = self._popup_a
        lx, ly = self._to_local(x0, y)
        ly -= (1.0 - a) * 10.0

        panel = QRectF(lx - 6, ly - 6, cell * len(options) + 12, h + 12)
        p.setPen(Qt.PenStyle.NoPen)
        fill = QColor(S.GLASS_FILL_STRONG)
        fill.setAlpha(int(238 * a))
        p.setBrush(fill)
        p.drawRoundedRect(panel, 16, 16)
        p.setPen(QPen(self._glow(52 * a), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(panel, 16, 16)

        p.setFont(S.font(max(12, int(h * 0.42))))
        for i, opt in enumerate(options):
            rect = QRectF(lx + i * cell, ly, cell, h)
            if i == idx:
                p.setPen(Qt.PenStyle.NoPen)
                c = QColor(S.KEY_FILL_ACTIVE)
                c.setAlpha(int(230 * a))
                p.setBrush(c)
                p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), S.KEY_RADIUS,
                                  S.KEY_RADIUS)
                act = QColor(S.KEY_TEXT_ACTIVE)
                act.setAlpha(int(255 * a))
                p.setPen(act)
            else:
                kt = QColor(S.KEY_TEXT)
                kt.setAlpha(int(226 * a))
                p.setPen(kt)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, opt)

    # ---- HUD ----
    def _paint_hud(self, p: QPainter, out: EngineOutput) -> None:
        self._hud_rects = []
        label = out.mode.value
        if time.perf_counter() < self._note_until and self._note:
            label = f"{out.mode.value} · {self._note}"

        cx = self.width() / 2
        cy = self.height() - 58
        if self._kb_a > 0.05 and out.keyboard and out.keyboard.keys:
            kx, ky, _kw, _kh = out.keyboard.rect
            _lx, top = self._to_local(kx, ky)
            cy = min(cy, top - 42)
        self._pill(p, label, cx, cy, QColor(S.HUD_TEXT), 13, alpha=self._hud_a)

        if not self.cfg.safety.control_enabled:
            self._pill(p, "MODO SEGURO · no se inyecta nada", cx, 46,
                       QColor(S.ACCENT_WARN), 12, alpha=self._hud_a)
        elif out.mode is Mode.PAUSED:
            self._pill(p, "EN PAUSA", cx, 46, QColor(S.ACCENT_DANGER), 13,
                       alpha=self._hud_a)

    def _pill(self, p: QPainter, text: str, cx: float, cy: float,
              color: QColor, size: int, alpha: float = 1.0) -> None:
        p.setFont(S.font(size))
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 34
        h = fm.height() + 16
        rect = QRectF(cx - w / 2, cy - h / 2, w, h)
        self._hud_rects.append(rect.toRect())

        path = QPainterPath()
        path.addRoundedRect(rect, S.HUD_RADIUS, S.HUD_RADIUS)
        p.setPen(Qt.PenStyle.NoPen)
        fill = QColor(S.GLASS_FILL)
        fill.setAlpha(int(fill.alpha() * alpha))
        p.setBrush(fill)
        p.drawPath(path)
        p.setPen(QPen(self._glow(34 * alpha), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        c = QColor(color)
        c.setAlpha(int(c.alpha() * alpha))
        p.setPen(c)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
