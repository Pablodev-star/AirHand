"""Paleta y geometria del overlay.

Todo el "look Vision Pro" sale de tres ideas: cristal oscuro translucido,
bordes muy redondeados y luz blanca difusa. Nada de colores saturados.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QLinearGradient, QRadialGradient

# ---------------- color ----------------
WHITE = QColor(255, 255, 255)
GLASS_FILL = QColor(20, 21, 24, 168)
GLASS_FILL_STRONG = QColor(16, 17, 20, 214)
GLASS_BORDER = QColor(255, 255, 255, 38)
GLASS_HILIGHT = QColor(255, 255, 255, 22)

KEY_FILL = QColor(255, 255, 255, 26)
KEY_FILL_HOVER = QColor(255, 255, 255, 64)
KEY_FILL_ACTIVE = QColor(255, 255, 255, 226)
KEY_TEXT = QColor(255, 255, 255, 232)
KEY_TEXT_ACTIVE = QColor(18, 18, 20, 255)
KEY_BORDER = QColor(255, 255, 255, 30)

CURSOR_CORE = QColor(255, 255, 255, 236)
CURSOR_RING = QColor(255, 255, 255, 92)
CURSOR_GLOW = QColor(255, 255, 255, 46)
CURSOR_PINCH = QColor(190, 226, 255, 250)

CHROME_BAR = QColor(255, 255, 255, 232)
CHROME_BAR_DIM = QColor(255, 255, 255, 120)
CHROME_GLOW = QColor(255, 255, 255, 40)

ACCENT_OK = QColor(126, 231, 165)
ACCENT_WARN = QColor(255, 196, 92)
ACCENT_DANGER = QColor(255, 122, 122)
ACCENT_INFO = QColor(150, 200, 255)

# Color del cursor segun la accion. Que cambie de color es lo que hace que
# entiendas de un vistazo en que modo estas sin leer nada.
TINT_PINCH = QColor(126, 214, 255)      # decidiendo si es clic
TINT_SCROLL = QColor(178, 158, 255)     # desplazando
TINT_DRAG = QColor(126, 231, 165)       # arrastrando
TINT_WINDOW = QColor(255, 196, 92)      # moviendo o escalando una ventana
TINT_ZOOM = QColor(150, 200, 255)       # zoom a dos manos
TINT_FLICK = QColor(255, 176, 92)       # cargando la catapulta

HUD_TEXT = QColor(255, 255, 255, 224)
HUD_TEXT_DIM = QColor(255, 255, 255, 140)

# ---------------- geometria ----------------
CURSOR_RADIUS = 11.0
CURSOR_RING_RADIUS = 21.0
CURSOR_GLOW_RADIUS = 34.0

CHROME_BAR_HEIGHT = 7.0
CHROME_BAR_MIN_W = 96.0
CHROME_BAR_MAX_W = 260.0
CHROME_BAR_GAP = 13.0
CHROME_CORNER_RADIUS = 26.0
CHROME_CORNER_THICK = 6.0

KEY_RADIUS = 11.0
PANEL_RADIUS = 26.0
HUD_RADIUS = 17.0

ANIM_FAST = 0.22      # constante de tiempo en segundos
ANIM_SLOW = 0.38


def apply_theme(dark: bool) -> None:
    """Adapta el overlay al tema.

    En modo claro una barra blanca sobre una ventana blanca seria invisible, asi
    que el cristal y los elementos se invierten.
    """
    g = globals()
    if dark:
        g.update(
            GLASS_FILL=QColor(20, 21, 24, 168),
            GLASS_FILL_STRONG=QColor(16, 17, 20, 214),
            GLASS_BORDER=QColor(255, 255, 255, 38),
            KEY_FILL=QColor(255, 255, 255, 26),
            KEY_FILL_HOVER=QColor(255, 255, 255, 64),
            KEY_FILL_ACTIVE=QColor(255, 255, 255, 226),
            KEY_TEXT=QColor(255, 255, 255, 232),
            KEY_TEXT_ACTIVE=QColor(18, 18, 20, 255),
            KEY_BORDER=QColor(255, 255, 255, 30),
            CURSOR_CORE=QColor(255, 255, 255, 236),
            CURSOR_RING=QColor(255, 255, 255, 92),
            CHROME_BAR=QColor(255, 255, 255, 232),
            HUD_TEXT=QColor(255, 255, 255, 224),
            HUD_TEXT_DIM=QColor(255, 255, 255, 140),
            GLOW_TINT=QColor(255, 255, 255),
            ACCENT_OK=QColor(126, 231, 165),
            ACCENT_WARN=QColor(255, 196, 92),
            ACCENT_DANGER=QColor(255, 122, 122),
            ACCENT_INFO=QColor(150, 200, 255),
        )
    else:
        g.update(
            GLASS_FILL=QColor(250, 250, 252, 198),
            GLASS_FILL_STRONG=QColor(252, 252, 254, 238),
            GLASS_BORDER=QColor(15, 23, 42, 42),
            KEY_FILL=QColor(15, 23, 42, 16),
            KEY_FILL_HOVER=QColor(15, 23, 42, 44),
            KEY_FILL_ACTIVE=QColor(22, 24, 30, 232),
            KEY_TEXT=QColor(20, 22, 27, 236),
            KEY_TEXT_ACTIVE=QColor(255, 255, 255, 255),
            KEY_BORDER=QColor(15, 23, 42, 28),
            CURSOR_CORE=QColor(24, 26, 32, 238),
            CURSOR_RING=QColor(24, 26, 32, 104),
            CHROME_BAR=QColor(28, 30, 38, 236),
            HUD_TEXT=QColor(20, 22, 27, 232),
            HUD_TEXT_DIM=QColor(20, 22, 27, 150),
            GLOW_TINT=QColor(15, 23, 42),
            # sobre cristal claro hacen falta tonos mucho mas oscuros
            ACCENT_OK=QColor(20, 122, 80),
            ACCENT_WARN=QColor(150, 88, 6),
            ACCENT_DANGER=QColor(178, 40, 40),
            ACCENT_INFO=QColor(22, 90, 190),
        )


GLOW_TINT = QColor(255, 255, 255)


def font(size: int, weight: int = QFont.Weight.Medium) -> QFont:
    f = QFont("Segoe UI Variable Display", size)
    if not f.exactMatch():
        f = QFont("Segoe UI", size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def glass_gradient(x: float, y: float, w: float, h: float) -> QLinearGradient:
    g = QLinearGradient(x, y, x, y + h)
    g.setColorAt(0.0, QColor(255, 255, 255, 26))
    g.setColorAt(0.35, QColor(255, 255, 255, 8))
    g.setColorAt(1.0, QColor(255, 255, 255, 0))
    _ = w
    return g


def glow_gradient(cx: float, cy: float, r: float, color: QColor) -> QRadialGradient:
    g = QRadialGradient(cx, cy, r)
    inner = QColor(color)
    outer = QColor(color)
    outer.setAlpha(0)
    g.setColorAt(0.0, inner)
    g.setColorAt(0.45, QColor(color.red(), color.green(), color.blue(),
                              int(color.alpha() * 0.42)))
    g.setColorAt(1.0, outer)
    return g


def smooth(current: float, target: float, dt: float, tau: float = ANIM_FAST) -> float:
    """Interpolacion exponencial independiente del framerate."""
    if tau <= 0:
        return target
    import math

    a = 1.0 - math.exp(-dt / tau)
    return current + (target - current) * a
