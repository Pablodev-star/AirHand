"""Tema activo: publica los tokens de CRISTAL VIVO al resto de la aplicacion.

``tokens.py`` guarda los valores crudos y no sabe nada de Qt. Este modulo es la
capa delgada que los convierte en algo consumible: una paleta viva (``theme.C``),
una senal de cambio y una hoja de estilo minima.

Dos cosas que conviene entender antes de tocar nada:

* **El QSS solo lleva familia y colores.** Qt ignora ``letter-spacing`` y
  ``line-height``, y el theme.py anterior los escribia igualmente: media
  especificacion tipografica era decorativa. El tamano, el peso y el tracking los
  pone ``tipo.py`` con ``QFont``; la forma (radios, filos, sombras) la pinta
  ``glass.py``. Aqui no se escribe ninguna de las dos cosas.
* **Los nombres antiguos de ``Palette`` siguen vivos como alias.** La interfaz
  anterior sigue pintando mientras se sustituye pieza a pieza, y es como
  verificamos que nada se ha roto. Ningun alias guarda un color propio: todos
  resuelven a un token del apartado 3.

Los widgets pintados a mano leen ``theme.C.<token>`` dentro de ``paintEvent``, y
consultan por atributo en vez de importar el color, asi que un cambio de tema se
propaga solo con repintar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from ..gestures.events import Mode
from .tokens import (TOKENS, CanvasTokens, ColorTokens, EdgeTokens, Elevation,
                     GlassTokens, Ink, ShadowTokens, TextTokens, Tokens, _rgb)


# ------------------------------------------------------------------ utilidades
def rgba(hex_color: str, alpha: float) -> str:
    """Color CSS con alfa, para el QSS."""
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:.3f})"


def mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(
        int(ca.red() + (cb.red() - ca.red()) * t),
        int(ca.green() + (cb.green() - ca.green()) * t),
        int(ca.blue() + (cb.blue() - ca.blue()) * t),
    ).name()


def _argb(ink: Ink) -> str:
    """Hex ``#AARRGGBB``, el unico formato con alfa que ``QColor`` entiende.

    El theme.py anterior escribia ``#RRGGBBAA`` (``#00000080``) y Qt lo leia como
    ``#AARRGGBB``: alfa 0. Las sombras y el velo del overlay llevaban meses sin
    pintarse y nadie lo habia notado.
    """
    r, g, b = _rgb(ink.hex)
    return "#{:02X}{:02X}{:02X}{:02X}".format(round(ink.alpha * 255), r, g, b)


def _readable_on(bg: str, t: Tokens) -> str:
    """Texto legible sobre un relleno solido: o el lienzo o blanco puro.

    El acento oscuro (#7C8CFF) es una lavanda clara y pide tinta; el claro
    (#4257E8) es un azul saturado y pide blanco. Decidirlo por luminancia evita
    tener que escribir a mano el par de cada paleta.
    """
    r, g, b = _rgb(bg)
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return t.canvas.base if lum > 0.55 else "#FFFFFF"


# ------------------------------------------------------------------ la paleta
@dataclass(frozen=True)
class Palette:
    """La paleta activa. Tokens nuevos delante, alias de la interfaz vieja detras.

    ``shadows`` e ``ink`` se llaman asi porque ``shadow`` y ``text`` los ocupan
    dos alias antiguos que son cadenas sueltas. Cuando la interfaz vieja
    desaparezca, se renombran a los del apartado 3 y este comentario se borra.
    """

    tokens: Tokens
    name: str
    dark: bool

    # apartado 3 completo, para glass.py, charts.py y el overlay
    canvas: CanvasTokens
    glass: GlassTokens
    edge: EdgeTokens
    shadows: ShadowTokens
    ink: TextTokens
    color: ColorTokens
    elevation: Mapping[str, Elevation]

    # alias historicos: superficies, de atras hacia delante
    bg: str
    bg_grad: str
    surface: str
    surface_alt: str
    surface_hover: str
    surface_sunken: str

    # alias historicos: lineas
    border: str
    border_strong: str

    # alias historicos: texto
    text: str
    text_dim: str
    text_faint: str

    # alias historicos: interaccion
    primary: str
    primary_text: str
    primary_hover: str
    accent: str
    accent_soft: str

    # alias historicos: estado
    ok: str
    warn: str
    danger: str
    info: str

    # alias historicos: extras
    shadow: str
    overlay_scrim: str
    track: str

    def mode_color(self, mode: Mode, flick: bool = False) -> str:
        """Rampa de modo del apartado 3.1. El flick manda sobre el modo base."""
        return self.tokens.mode_color(mode, flick)


def _build(t: Tokens) -> Palette:
    """Deriva la paleta completa de un juego de tokens.

    Los alias antiguos se aplanan aqui porque el QSS y los ``paintEvent`` de la
    interfaz vieja piden un hex opaco, y un lavado translucido sobre el lienzo
    vivo no tiene un unico valor. ``Surface.solid`` es justamente ese aplanado.
    """
    surface = t.glass.wash.solid
    accent = t.color.accent
    return Palette(
        tokens=t, name=t.name, dark=t.dark,
        canvas=t.canvas, glass=t.glass, edge=t.edge, shadows=t.shadow,
        ink=t.text, color=t.color, elevation=t.elevation,

        bg=t.canvas.base,
        # el segundo tono del degradado es la mancha de luz del lienzo aplanada:
        # asi el fondo plano de la interfaz vieja cae donde caera el lienzo vivo
        bg_grad=t.canvas.light.ink.over(t.canvas.base),
        surface=surface,
        surface_alt=t.glass.raised.solid,
        surface_hover=t.glass.hover.solid,
        surface_sunken=t.glass.sunken.solid,

        border=t.edge.hair.over(surface),
        # el filo dominante a su alfa nominal separa dos laminas, pero no dibuja
        # el contorno de un mando: a brillo alto un campo con 0.10 desaparece
        border_strong=t.edge.dominant.scaled(1.8).over(surface),

        text=t.text.primary,
        text_dim=t.text.secondary,
        text_faint=t.text.tertiary,

        primary=accent,
        primary_text=_readable_on(accent, t),
        # el hover mueve el relleno hacia la fuente de luz de cada paleta
        primary_hover=mix(accent, "#FFFFFF" if t.dark else t.text.primary, 0.14),
        accent=accent,
        accent_soft=t.color.accent_soft.over(surface),

        ok=t.color.ok, warn=t.color.warn, danger=t.color.danger,
        info=t.color.info,

        shadow=_argb(t.shadow.key),
        # el velo usa la tinta de las sombras: en claro es azulada, y un negro
        # translucido sobre vidrio claro se ve sucio (apartado 11.3)
        overlay_scrim=_argb(t.shadow.key.at(0.55)),
        track=t.glass.sunken.solid,
    )


PALETTES: Mapping[str, Palette] = {k: _build(v) for k, v in TOKENS.items()}
DARK = PALETTES["dark"]
LIGHT = PALETTES["light"]


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
    """Cambia la paleta activa y avisa a quien pinte a mano."""
    global C, mode
    mode = requested
    C = resolve(requested)
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


def qcolor(token: str, alpha: int | None = None) -> QColor:
    c = QColor(getattr(C, token))
    if alpha is not None:
        c.setAlpha(alpha)
    return c


# ---------------------------------------------------------------- hoja de estilo
def qss() -> str:
    """Familia y colores base. Nada mas.

    Ni una propiedad tipografica (Qt ignora la mitad y ``tipo.py`` pone la otra)
    ni geometria de laminas (la pinta ``glass.py``). Lo que queda son los mandos
    nativos de Qt, que no pasan por ninguna de las dos y que sin esto salen con
    los colores del sistema sobre el lienzo.
    """
    c = C
    return f"""
* {{ outline: none; }}

QWidget {{
    background: transparent;
    color: {c.text};
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
}}
QMainWindow, QDialog {{ background: {c.bg}; }}

QLabel {{ background: transparent; }}
QLabel[role="h3"], QLabel[role="faint"] {{ color: {c.text_faint}; }}
QLabel[role="dim"] {{ color: {c.text_dim}; }}
QLabel[role="mono"] {{ font-family: "Cascadia Mono", Consolas, monospace; }}

QFrame[role="card"] {{ background: {c.surface}; }}
QFrame[role="inset"] {{ background: {c.surface_sunken}; }}
QFrame[role="sep"] {{ background: {c.border}; }}

QPushButton {{
    background: {c.surface_alt};
    border: 1px solid {c.border};
    color: {c.text};
}}
QPushButton:hover {{ background: {c.surface_hover}; border-color: {c.border_strong}; }}
QPushButton:pressed {{ background: {c.surface_sunken}; }}
QPushButton:disabled {{ color: {c.text_faint}; }}
QPushButton:focus {{ border-color: {c.accent}; }}

QPushButton[role="primary"] {{
    background: {c.primary}; color: {c.primary_text}; border-color: {c.primary};
}}
QPushButton[role="primary"]:hover {{
    background: {c.primary_hover}; border-color: {c.primary_hover};
}}
QPushButton[role="primary"]:disabled {{
    background: {c.surface_hover}; color: {c.text_faint}; border-color: {c.border};
}}
QPushButton[role="ghost"] {{ background: transparent; border-color: transparent; }}
QPushButton[role="ghost"]:hover {{ background: {c.surface_hover}; }}
QPushButton[role="danger"] {{ color: {c.danger}; border-color: {rgba(c.danger, 0.35)}; }}
QPushButton[role="danger"]:hover {{ background: {rgba(c.danger, 0.10)}; }}

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {c.surface_alt};
    border: 1px solid {c.border};
    color: {c.text};
    selection-background-color: {c.accent};
    selection-color: {c.primary_text};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: {c.border_strong}; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {c.accent}; }}
QComboBox QAbstractItemView {{
    background: {c.surface};
    border: 1px solid {c.border};
    selection-background-color: {c.accent_soft};
    selection-color: {c.text};
}}

QProgressBar {{ background: {c.track}; border: none; color: transparent; }}
QProgressBar::chunk {{ background: {c.accent}; }}

QPlainTextEdit, QTextEdit {{
    background: {c.surface_sunken};
    border: 1px solid {c.border};
    color: {c.text_dim};
    font-family: "Cascadia Mono", Consolas, monospace;
    selection-background-color: {c.accent};
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar {{ background: transparent; }}
QScrollBar::handle {{ background: {c.border_strong}; }}
QScrollBar::handle:hover {{ background: {c.text_faint}; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QGroupBox {{ border: 1px solid {c.border}; }}

QToolTip {{
    background: {c.surface}; color: {c.text}; border: 1px solid {c.border_strong};
}}

QMenu {{ background: {c.surface}; border: 1px solid {c.border}; }}
QMenu::item:selected {{ background: {c.surface_hover}; }}
QMenu::separator {{ background: {c.border}; }}
"""


# paleta inicial
apply("dark")
