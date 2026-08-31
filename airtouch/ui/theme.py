"""Sistema de temas: claro, oscuro y automatico segun Windows.

Los colores se exponen como atributos del modulo (``theme.TEXT``, ``theme.OK``…)
y se reescriben al cambiar de tema. Como todo el codigo los consulta por
atributo y no con ``from theme import TEXT``, el cambio se propaga solo.

Los widgets pintados a mano leen ``theme.C.<token>`` dentro de ``paintEvent``,
asi que basta con repintar para que adopten el tema nuevo.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor


@dataclass(frozen=True)
class Palette:
    name: str
    dark: bool

    # superficies, de atras hacia delante
    bg: str
    bg_grad: str            # segundo tono del degradado del fondo
    surface: str
    surface_alt: str
    surface_hover: str
    surface_sunken: str

    # lineas
    border: str
    border_strong: str

    # texto
    text: str
    text_dim: str
    text_faint: str

    # interaccion
    primary: str            # boton principal
    primary_text: str
    primary_hover: str
    accent: str             # seleccion, foco, elementos activos
    accent_soft: str        # mismo tono, muy diluido, para fondos

    # estado
    ok: str
    warn: str
    danger: str
    info: str

    # extras
    shadow: str
    overlay_scrim: str
    track: str              # canales de sliders y barras


DARK = Palette(
    name="dark", dark=True,
    bg="#0b0c0f", bg_grad="#101218",
    surface="#16181e", surface_alt="#1b1e26", surface_hover="#22262f",
    surface_sunken="#0e1014",
    border="#252932", border_strong="#343a47",
    text="#e9ebf0", text_dim="#98a0b0", text_faint="#646c7c",
    primary="#ffffff", primary_text="#0b0c0f", primary_hover="#e4e7ee",
    accent="#6aa9ff", accent_soft="#1b2a41",
    ok="#5fd39a", warn="#ffc260", danger="#ff7b7b", info="#7cb8ff",
    shadow="#00000080", overlay_scrim="#000000a6", track="#262b35",
)

LIGHT = Palette(
    name="light", dark=False,
    bg="#f4f5f8", bg_grad="#eceef3",
    surface="#ffffff", surface_alt="#f7f8fa", surface_hover="#eef0f5",
    surface_sunken="#f0f2f6",
    border="#e2e5ec", border_strong="#cdd2dc",
    text="#14161b", text_dim="#5c6473", text_faint="#8c94a3",
    primary="#16181e", primary_text="#ffffff", primary_hover="#2a2e38",
    accent="#1668d9", accent_soft="#e3edfc",
    ok="#1a9f6a", warn="#b4700a", danger="#cf3b3b", info="#1668d9",
    shadow="#0f172a1f", overlay_scrim="#0f172a26", track="#dfe3ea",
)

PALETTES = {"dark": DARK, "light": LIGHT}


class _ThemeSignals(QObject):
    changed = Signal(str)


signals = _ThemeSignals()

#: Paleta activa. Los widgets pintados a mano leen de aqui en cada repintado.
C: Palette = DARK
mode: str = "dark"          # "dark" | "light" | "system"


# ---------------------------------------------------------------- deteccion
def windows_prefers_light() -> bool:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        with key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return bool(value)
    except Exception:
        return False


def resolve(requested: str) -> Palette:
    if requested == "system":
        return LIGHT if windows_prefers_light() else DARK
    return PALETTES.get(requested, DARK)


# ---------------------------------------------------------------- aplicacion
def apply(requested: str) -> Palette:
    """Cambia la paleta activa y republica los colores del modulo."""
    global C, mode
    mode = requested
    C = resolve(requested)
    g = globals()
    for f in fields(Palette):
        if f.name in ("name", "dark"):
            continue
        g[f.name.upper()] = getattr(C, f.name)
    # alias historicos usados por el resto de la interfaz
    g["BG_CARD"] = C.surface
    g["BG_ELEV"] = C.surface_alt
    g["QSS"] = qss()
    signals.changed.emit(C.name)
    return C


def unsubscribe(slot) -> None:
    """Desconecta un slot de la senal de tema sin quejarse al cerrar la app.

    Al terminar el proceso, Qt destruye el emisor antes que los widgets, y un
    disconnect ciego llena la consola de avisos.
    """
    try:
        from shiboken6 import isValid

        if not isValid(signals):
            return
    except Exception:
        pass
    try:
        signals.changed.disconnect(slot)
    except (RuntimeError, TypeError):
        pass


def rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:.3f})"


def qcolor(token: str, alpha: int | None = None) -> QColor:
    c = QColor(getattr(C, token))
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(
        int(ca.red() + (cb.red() - ca.red()) * t),
        int(ca.green() + (cb.green() - ca.green()) * t),
        int(ca.blue() + (cb.blue() - ca.blue()) * t),
    ).name()


# ---------------------------------------------------------------- hoja de estilo
def qss() -> str:
    c = C
    focus_ring = rgba(c.accent, 0.55)
    return f"""
* {{ outline: none; }}

QWidget {{
    background: transparent;
    color: {c.text};
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{ background: {c.bg}; }}

QLabel {{ background: transparent; }}
QLabel[role="display"] {{ font-size: 30px; font-weight: 650; letter-spacing: -0.5px; }}
QLabel[role="h1"] {{ font-size: 23px; font-weight: 620; letter-spacing: -0.3px; }}
QLabel[role="h2"] {{ font-size: 16px; font-weight: 600; }}
QLabel[role="h3"] {{ font-size: 12px; font-weight: 650; color: {c.text_faint};
                     letter-spacing: 0.7px; }}
QLabel[role="dim"] {{ color: {c.text_dim}; }}
QLabel[role="faint"] {{ color: {c.text_faint}; font-size: 12px; }}
QLabel[role="mono"] {{ font-family: "Cascadia Mono", Consolas, monospace;
                       font-size: 12px; }}
QLabel[role="metric"] {{ font-size: 25px; font-weight: 620; }}

QFrame[role="card"] {{
    background: {c.surface};
    border: 1px solid {c.border};
    border-radius: 18px;
}}
QFrame[role="inset"] {{
    background: {c.surface_sunken};
    border: 1px solid {c.border};
    border-radius: 14px;
}}
QFrame[role="sep"] {{ background: {c.border}; max-height: 1px; border: none; }}

/* ---------------- botones ---------------- */
QPushButton {{
    background: {c.surface_alt};
    border: 1px solid {c.border};
    border-radius: 12px;
    padding: 10px 18px;
    font-weight: 550;
    color: {c.text};
}}
QPushButton:hover {{ background: {c.surface_hover}; border-color: {c.border_strong}; }}
QPushButton:pressed {{ background: {c.surface_sunken}; }}
QPushButton:disabled {{ color: {c.text_faint}; background: {c.surface_alt};
                        border-color: {c.border}; }}
QPushButton:focus {{ border-color: {focus_ring}; }}

QPushButton[role="primary"] {{
    background: {c.primary}; color: {c.primary_text};
    border: 1px solid {c.primary}; font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {c.primary_hover};
                                     border-color: {c.primary_hover}; }}
QPushButton[role="primary"]:disabled {{ background: {c.surface_hover};
                                        color: {c.text_faint};
                                        border-color: {c.border}; }}
QPushButton[role="ghost"] {{ background: transparent; border-color: transparent; }}
QPushButton[role="ghost"]:hover {{ background: {c.surface_hover}; }}
QPushButton[role="danger"] {{ color: {c.danger};
                              border-color: {rgba(c.danger, 0.35)}; }}
QPushButton[role="danger"]:hover {{ background: {rgba(c.danger, 0.10)}; }}

/* ---------------- campos ---------------- */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {c.surface_alt};
    border: 1px solid {c.border};
    border-radius: 11px;
    padding: 8px 12px;
    min-height: 19px;
    selection-background-color: {c.accent};
    selection-color: #ffffff;
}}
QComboBox:hover, QLineEdit:hover {{ border-color: {c.border_strong}; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {c.accent}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background: {c.surface};
    border: 1px solid {c.border};
    selection-background-color: {c.accent_soft};
    selection-color: {c.text};
    border-radius: 12px;
    padding: 5px;
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none;
                                              background: transparent; }}

/* ---------------- sliders ---------------- */
QSlider::groove:horizontal {{ height: 5px; background: {c.track};
                              border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {c.accent}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {c.surface}; border: 2px solid {c.accent};
    width: 15px; height: 15px; margin: -7px 0; border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{ background: {c.accent_soft}; }}

/* ---------------- casillas ---------------- */
QCheckBox, QRadioButton {{ background: transparent; spacing: 9px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 6px;
    border: 1px solid {c.border_strong}; background: {c.surface_alt};
}}
QCheckBox::indicator:checked {{ background: {c.accent}; border-color: {c.accent}; }}

/* ---------------- progreso ---------------- */
QProgressBar {{
    background: {c.track}; border: none; border-radius: 5px;
    height: 9px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {c.accent}; border-radius: 5px; }}

/* ---------------- texto largo ---------------- */
QPlainTextEdit, QTextEdit {{
    background: {c.surface_sunken}; border: 1px solid {c.border};
    border-radius: 14px; padding: 12px;
    font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px;
    color: {c.text_dim};
    selection-background-color: {c.accent};
}}

/* ---------------- barras de desplazamiento ---------------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 3px; }}
QScrollBar::handle:vertical {{ background: {c.border_strong}; border-radius: 4px;
                               min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c.text_faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 3px; }}
QScrollBar::handle:horizontal {{ background: {c.border_strong}; border-radius: 4px;
                                 min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------------- agrupaciones ---------------- */
QGroupBox {{
    border: 1px solid {c.border}; border-radius: 15px;
    margin-top: 15px; padding: 16px 14px 12px 14px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 15px; padding: 0 7px; }}

QToolTip {{
    background: {c.surface}; color: {c.text};
    border: 1px solid {c.border_strong}; border-radius: 9px; padding: 7px 10px;
}}

QMenu {{
    background: {c.surface}; border: 1px solid {c.border};
    border-radius: 12px; padding: 6px;
}}
QMenu::item {{ padding: 8px 26px 8px 14px; border-radius: 8px; }}
QMenu::item:selected {{ background: {c.surface_hover}; }}
QMenu::separator {{ height: 1px; background: {c.border}; margin: 5px 8px; }}
"""


# paleta inicial
apply("dark")
