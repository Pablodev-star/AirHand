"""Gestion de ventanas de Windows.

Aqui vive la parte "Vision Pro": encontrar la ventana que hay bajo el puntero
(o justo encima de el, cuando el dedo esta por debajo del borde inferior),
moverla y redimensionarla.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

GA_ROOT = 2
GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_CHILD = 0x40000000
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SW_RESTORE = 9
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14

user32.GetWindowLongW.restype = ctypes.c_long
try:
    _GetWindowLongPtr = user32.GetWindowLongPtrW
except AttributeError:  # 32-bit
    _GetWindowLongPtr = user32.GetWindowLongW


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]     # left, top, right, bottom (bordes visuales)

    @property
    def left(self) -> int:
        return self.rect[0]

    @property
    def top(self) -> int:
        return self.rect[1]

    @property
    def right(self) -> int:
        return self.rect[2]

    @property
    def bottom(self) -> int:
        return self.rect[3]

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


# ---------------- consultas ----------------
def _visual_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Bordes reales sin la sombra invisible que Windows anade a las ventanas."""
    r = wintypes.RECT()
    hr = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), ctypes.c_uint(DWMWA_EXTENDED_FRAME_BOUNDS),
        ctypes.byref(r), ctypes.sizeof(r),
    )
    if hr != 0:
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
            return None
    return (r.left, r.top, r.right, r.bottom)


def _is_cloaked(hwnd: int) -> bool:
    val = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), ctypes.c_uint(DWMWA_CLOAKED),
        ctypes.byref(val), ctypes.sizeof(val),
    )
    return bool(val.value)


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _is_manageable(hwnd: int, ignore: set[int]) -> bool:
    if hwnd in ignore or not user32.IsWindowVisible(hwnd):
        return False
    if user32.IsIconic(hwnd):
        return False
    ex = _GetWindowLongPtr(hwnd, GWL_EXSTYLE)
    if ex & WS_EX_TOOLWINDOW:
        return False
    if _GetWindowLongPtr(hwnd, GWL_STYLE) & WS_CHILD:
        return False
    if _is_cloaked(hwnd):
        return False
    return bool(_title(hwnd))


def enumerate_windows(ignore: set[int] | None = None) -> list[WindowInfo]:
    """Ventanas de nivel superior en orden Z (la de delante primero)."""
    ignore = ignore or set()
    out: list[WindowInfo] = []

    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        if _is_manageable(hwnd, ignore):
            r = _visual_rect(hwnd)
            if r and r[2] > r[0] and r[3] > r[1]:
                out.append(WindowInfo(int(hwnd), _title(hwnd), r))
        return 1

    user32.EnumWindows(EnumProc(_cb), 0)
    return out


def window_at(x: float, y: float, ignore: set[int] | None = None) -> WindowInfo | None:
    """Ventana raiz bajo el punto, usando el hit-test nativo (respeta el orden Z)."""
    ignore = ignore or set()
    pt = wintypes.POINT(int(x), int(y))
    hwnd = user32.WindowFromPoint(pt)
    if not hwnd:
        return None
    root = user32.GetAncestor(hwnd, GA_ROOT)
    root = int(root or hwnd)
    if root in ignore or not _is_manageable(root, ignore):
        return None
    r = _visual_rect(root)
    if not r:
        return None
    return WindowInfo(root, _title(root), r)


def find_chrome_target(
    x: float, y: float, band: int, corner: int, ignore: set[int] | None = None,
) -> tuple[WindowInfo | None, str]:
    """Determina si el puntero esta activando el "chrome" de una ventana.

    Devuelve (ventana, zona) donde zona es "" | "move" | "resize".
      * "resize": cerca de la esquina inferior derecha (dentro o justo fuera)
      * "move":   en la franja del borde inferior o justo debajo de el
    """
    ignore = ignore or set()

    # 1) prioridad al hit-test nativo: si el dedo esta DENTRO de una ventana,
    #    esa es la ventana, sin ambiguedad de orden Z.
    inside = window_at(x, y, ignore)
    candidates: list[WindowInfo] = []
    if inside is not None:
        candidates.append(inside)

    # 2) si esta fuera (por debajo del borde), buscamos entre todas las ventanas
    #    la que tenga su borde inferior justo encima del dedo.
    for w in enumerate_windows(ignore):
        if inside is not None and w.hwnd == inside.hwnd:
            continue
        if w.left - corner <= x <= w.right + corner and w.bottom <= y <= w.bottom + band:
            candidates.append(w)

    for w in candidates:
        near_bottom = (w.bottom - band) <= y <= (w.bottom + band)
        if not near_bottom:
            continue
        if abs(x - w.right) <= corner and abs(y - w.bottom) <= corner:
            return w, "resize"
        if w.left <= x <= w.right:
            return w, "move"
    return None, ""


# ---------------- acciones ----------------
def restore_if_maximized(hwnd: int) -> None:
    if user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)


def set_bounds(hwnd: int, left: int, top: int, width: int, height: int) -> None:
    user32.SetWindowPos(
        wintypes.HWND(hwnd), None, int(left), int(top), int(width), int(height),
        SWP_NOZORDER | SWP_NOACTIVATE,
    )


def _raw_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Rectangulo REAL de la ventana (el que entiende SetWindowPos)."""
    r = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def _frame_insets(hwnd: int) -> tuple[int, int, int, int]:
    """Diferencia entre el borde visual y el real.

    Windows 10/11 anaden un margen invisible alrededor de las ventanas para el
    redimensionado. DwmGetWindowAttribute devuelve el borde que TU ves;
    SetWindowPos espera el que incluye ese margen. Sin corregirlo, cada vez que
    agarras una ventana pega un salto de unos 8 px.
    """
    raw = _raw_rect(hwnd)
    vis = _visual_rect(hwnd)
    if raw is None or vis is None:
        return (0, 0, 0, 0)
    return (vis[0] - raw[0], vis[1] - raw[1], raw[2] - vis[2], raw[3] - vis[3])


def set_visual_bounds(hwnd: int, left: int, top: int, width: int,
                      height: int) -> None:
    """Coloca el borde VISIBLE de la ventana justo donde se le pide."""
    dl, dt, dr, db = _frame_insets(hwnd)
    user32.SetWindowPos(
        wintypes.HWND(hwnd), None,
        int(left - dl), int(top - dt),
        int(width + dl + dr), int(height + dt + db),
        SWP_NOZORDER | SWP_NOACTIVATE,
    )


def move_window(hwnd: int, left: int, top: int) -> None:
    user32.SetWindowPos(
        wintypes.HWND(hwnd), None, int(left), int(top), 0, 0,
        SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOSIZE,
    )


def resize_window(hwnd: int, width: int, height: int) -> None:
    user32.SetWindowPos(
        wintypes.HWND(hwnd), None, 0, 0, int(width), int(height),
        SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOMOVE,
    )


def get_info(hwnd: int) -> WindowInfo | None:
    r = _visual_rect(hwnd)
    if not r:
        return None
    return WindowInfo(hwnd, _title(hwnd), r)


# ---------------- apartar ventanas de la vista ----------------
# Guarda la posicion original de cada ventana apartada. Se persiste a disco
# porque si AirTouch muere de golpe la ventana se quedaria fuera de pantalla
# para siempre, y el usuario no tendria forma facil de recuperarla.
_stashed: dict[int, tuple[int, int, int, int]] = {}


def _stash_file():
    from ..config import app_data_dir

    return app_data_dir() / "stashed_windows.json"


def _persist() -> None:
    import json

    try:
        path = _stash_file()
        if _stashed:
            path.write_text(
                json.dumps({str(k): list(v) for k, v in _stashed.items()}),
                encoding="utf-8")
        elif path.exists():
            path.unlink()
    except Exception:
        pass


def restore_from_previous_run() -> int:
    """Devuelve a su sitio ventanas que quedaron apartadas por un cierre brusco."""
    import json

    path = _stash_file()
    if not path.exists():
        return 0
    restored = 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, rect in data.items():
            hwnd = int(key)
            if not user32.IsWindow(wintypes.HWND(hwnd)):
                continue
            set_bounds(hwnd, rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])
            restored += 1
    except Exception:
        pass
    try:
        path.unlink()
    except Exception:
        pass
    return restored


def find_windows_by_title(fragment: str) -> list[WindowInfo]:
    frag = fragment.lower()
    return [w for w in enumerate_windows() if frag in w.title.lower()]


def stash_window(hwnd: int) -> bool:
    """Aparta una ventana fuera de la pantalla sin minimizarla.

    Minimizar una app de captura como iVCam hace que deje de retransmitir.
    Moverla fuera del area visible la mantiene funcionando: sigue dibujando,
    simplemente no la ves.
    """
    if hwnd in _stashed:
        return True
    raw = _raw_rect(hwnd)               # el real, no el visual: si no, al
    if raw is None:                      # devolverla queda descolocada
        return False
    _stashed[hwnd] = raw
    vs_right = user32.GetSystemMetrics(78) + user32.GetSystemMetrics(76)
    set_bounds(hwnd, vs_right + 40, raw[1], raw[2] - raw[0], raw[3] - raw[1])
    _persist()
    return True


def restore_stashed(hwnd: int | None = None) -> None:
    """Devuelve a su sitio las ventanas apartadas."""
    targets = [hwnd] if hwnd is not None else list(_stashed)
    for h in targets:
        rect = _stashed.pop(h, None)
        if rect is None:
            continue
        try:
            set_bounds(h, rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])
        except Exception:
            pass
    _persist()


def stashed_hwnds() -> set[int]:
    return set(_stashed)


def focus(hwnd: int) -> None:
    try:
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
    except Exception:
        pass
