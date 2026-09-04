"""Tokens de CRISTAL VIVO: los valores crudos del apartado 3 de la especificacion.

Este modulo no pinta y no importa Qt. Es la raiz del grafo de dependencias de la
interfaz, asi que se mantiene deliberadamente tonto: solo datos y las cuentas
minimas para derivarlos. Quien pinta es ``glass.py``; quien compone fuentes es
``tipo.py``; quien publica todo esto al resto de la aplicacion es ``theme.py``.

Dos decisiones que conviene entender antes de tocar nada:

* Los colores translucidos se guardan como ``Ink`` (hex + alfa), no como cadena
  ya compuesta. Un lavado sobre el lienzo vivo no da el mismo resultado en la
  esquina iluminada que en la oscura, y aplanarlo aqui seria mentir.
* Los escalones de la elevacion se guardan como *razones* sobre el filo de la
  paleta, no como alfas absolutas. La especificacion los fija en oscuro
  (edge.light 0.14 -> 0.18 -> 0.22); en claro edge.light vale 0.95 y un 0.18
  absoluto no significaria nada.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..gestures.events import Mode


# ------------------------------------------------------------------ utilidades
def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def compose(fg: str, alpha: float, bg: str) -> str:
    """Aplana ``fg`` con ``alpha`` sobre ``bg``. Devuelve hex de seis digitos."""
    f, b = _rgb(fg), _rgb(bg)
    out = tuple(int(round(b[i] + (f[i] - b[i]) * alpha)) for i in range(3))
    return "#{:02X}{:02X}{:02X}".format(*out)


@dataclass(frozen=True)
class Ink:
    """Color con alfa. La unidad de todo lo translucido del sistema."""

    hex: str
    alpha: float = 1.0

    def over(self, bg: str) -> str:
        return compose(self.hex, self.alpha, bg)

    def css(self) -> str:
        r, g, b = _rgb(self.hex)
        return f"rgba({r}, {g}, {b}, {self.alpha:.3f})"

    def at(self, alpha: float) -> "Ink":
        return Ink(self.hex, max(0.0, min(1.0, alpha)))

    def scaled(self, factor: float) -> "Ink":
        return self.at(self.alpha * factor)


@dataclass(frozen=True)
class Blob:
    """Mancha radial del lienzo. Centro y radio en fraccion del rectangulo."""

    ink: Ink
    cx: float
    cy: float
    radius: float           # fraccion de la diagonal


@dataclass(frozen=True)
class Surface:
    """Un lavado de vidrio: como se pinta y su equivalente opaco.

    ``solid`` no es ``ink.over(canvas.base)``: la especificacion lo resuelve
    sobre el lienzo ya iluminado, no sobre su base plana. Lo usan el QSS y todo
    lo que todavia pinta plano sin pasar por glass.py.
    """

    ink: Ink
    solid: str


@dataclass(frozen=True)
class Shadow:
    """Una sombra proyectada. ``role`` es 'key' o 'ambient'."""

    role: str
    blur: int
    dx: int
    dy: int
    ink: Ink


@dataclass(frozen=True)
class Elevation:
    """Un nivel de altura: relleno, dos filos direccionales y sus sombras.

    ``fill`` nombra un campo de ``GlassTokens``, no un color: quien pinta decide
    si recorta el lienzo debajo (``clip_canvas``) o rellena plano.
    """

    name: str
    fill: str
    edge_tl: Ink            # filo arriba-izquierda
    edge_br: Ink            # filo abajo-derecha
    shadows: tuple[Shadow, ...]
    scale: float = 1.0
    clip_canvas: bool = False


@dataclass(frozen=True)
class TypeSpec:
    """Una fila de la escala tipografica. ``tracking`` en px absolutos."""

    size: float
    weight: int
    tracking: float
    leading: float
    upper: bool = False
    tabular: bool = False


@dataclass(frozen=True)
class CanvasTokens:
    base: str
    light: Blob
    cool: Blob
    tint: Blob
    vignette: Blob | None


@dataclass(frozen=True)
class GlassTokens:
    wash: Surface
    raised: Surface
    hover: Surface
    float_: Surface
    sunken: Surface


@dataclass(frozen=True)
class EdgeTokens:
    light: Ink
    dark: Ink
    hair: Ink
    flash: Ink
    dominant: Ink           # el filo que separa de verdad en esta paleta


@dataclass(frozen=True)
class ShadowTokens:
    key: Ink
    ambient: Ink


@dataclass(frozen=True)
class TextTokens:
    primary: str
    secondary: str
    tertiary: str
    quiet: str


@dataclass(frozen=True)
class ColorTokens:
    accent: str
    accent_soft: Ink
    accent_glow: Ink
    ok: str
    warn: str
    danger: str
    info: str


@dataclass(frozen=True)
class Tokens:
    name: str
    dark: bool
    canvas: CanvasTokens
    glass: GlassTokens
    edge: EdgeTokens
    shadow: ShadowTokens
    text: TextTokens
    color: ColorTokens
    elevation: Mapping[str, Elevation]
    modes: Mapping[Mode, str]
    flick: str

    def mode_color(self, mode: Mode, flick: bool = False) -> str:
        """Color de la rampa de modo. El flick manda sobre el modo de base."""
        if flick:
            return self.flick
        return self.modes.get(mode, self.modes[Mode.IDLE])


# ------------------------------------------------------------------ tipografia
FAMILY_DISPLAY = "Segoe UI Variable Display"
FAMILY_TEXT = "Segoe UI Variable Text"
FAMILY_SMALL = "Segoe UI Variable Small"
FAMILY_MONO = "Cascadia Mono"

#: Windows 10 no trae las Variable. Se comprueba una vez al arrancar.
FALLBACKS = ("Segoe UI Semibold", "Segoe UI", "sans-serif")
FALLBACKS_MONO = ("Consolas", "Courier New", "monospace")


def family_for(size: float) -> str:
    """Talla optica real de Windows 11: la familia depende del tamano."""
    if size >= 16:
        return FAMILY_DISPLAY
    if size >= 12:
        return FAMILY_TEXT
    return FAMILY_SMALL


TYPE: Mapping[str, TypeSpec] = {
    "display":   TypeSpec(46, 700, -1.6, 1.05),
    "title":     TypeSpec(30, 650, -0.8, 1.10),
    "h1":        TypeSpec(21, 620, -0.3, 1.15),
    "h2":        TypeSpec(16, 600, -0.1, 1.20),
    "body":      TypeSpec(13.5, 400, 0.0, 1.35),
    "body-fuerte": TypeSpec(13.5, 600, 0.0, 1.35),
    "caption":   TypeSpec(11.5, 500, 0.2, 1.30),
    "overline":  TypeSpec(10.5, 700, 1.2, 1.20, upper=True),
    # el peso Light es la firma; con 600 esto parece un dashboard corporativo
    "metric":    TypeSpec(34, 300, -1.0, 1.00, tabular=True),
    "metric-xl": TypeSpec(46, 300, -1.4, 1.00, tabular=True),
    "mosaico":   TypeSpec(38, 800, 2.0, 1.00, upper=True),
    "axis":      TypeSpec(10, 500, 0.3, 1.10, tabular=True),
    "mono":      TypeSpec(12, 300, 0.0, 1.55, tabular=True),
}

#: Segunda escala. Evita que los titulares se rompan en portatiles de 1366x768.
TYPE_COMPACT: Mapping[str, TypeSpec] = {
    "display":   TypeSpec(36, 700, -1.2, 1.05),
    "title":     TypeSpec(24, 650, -0.6, 1.10),
    "mosaico":   TypeSpec(28, 800, 1.6, 1.00, upper=True),
    "metric":    TypeSpec(28, 300, -0.8, 1.00, tabular=True),
    "metric-xl": TypeSpec(36, 300, -1.1, 1.00, tabular=True),
}

#: Ancho de ventana por debajo del cual manda TYPE_COMPACT, con histeresis.
SCALE_BREAKPOINT = 1180
SCALE_HYSTERESIS = 40

#: Rebaja cuando faltan las familias Variable: sin ellas los cuerpos grandes
#: pesan mas y el tracking negativo cierra demasiado las letras.
TYPE_NO_VARIABLE: Mapping[str, TypeSpec] = {
    "display": TypeSpec(40, 700, -1.1, 1.05),
    "mosaico": TypeSpec(34, 800, 2.0, 1.00, upper=True),
}


# ------------------------------------------------------------------ espaciado
SPACE = (4, 8, 12, 16, 20, 24, 32, 40, 56, 72)

WINDOW_MARGIN = 28
STATS_MARGIN = 32           # la pagina profunda de analisis respira mas
GUTTER = 16
SHEET_PADDING = 20
SHEET_PADDING_LARGE = 24
ROW_GAP = 12
GROUP_GAP = 32
ROW_HEIGHT = 56
ROW_HEIGHT_COMPACT = 40

#: Hueco entre laminas: misma elevacion 16, apoyada 0, claramente flotando 24.
#: Nunca 8: a esa distancia dos vidrios parecen un error de layout.
GAP_SAME = 16
GAP_STACKED = 0
GAP_FLOATING = 24

LIVE_COLUMN_W = 320
SETTINGS_LIST_W = 200
BOTTOM_BAR_H = 56


# ------------------------------------------------------------------ radios
R_XS = 8
R_SM = 12
R_MD = 18
R_LG = 24
R_XL = 32
R_FULL = -1                 # pildora: el pintor usa la mitad del alto
R_KEY = 11                  # teclas del overlay


def concentric(parent_radius: int, padding: int) -> int:
    """Radio del hijo = radio del padre - padding.

    Es la regla que hace que el vidrio parezca fabricado y no recortado. Nunca
    dos radios distintos en la misma esquina fisica.
    """
    if parent_radius == R_FULL:
        return R_FULL
    return max(R_XS, parent_radius - padding)


# ------------------------------------------------------------------ elevacion
#: Razones sacadas de las alfas que fija el apartado 3.6 para oscuro. Se guardan
#: como razon y no como absoluto porque en claro edge.light vale 0.95 y un 0.18
#: absoluto no seria un escalon, seria un filo mas debil que el de reposo.
_LIFT_E3 = 0.18 / 0.14
_LIFT_E4 = 0.22 / 0.14
_INSET_TL = 0.30 / 0.45     # E1: el filo oscuro sube arriba-izquierda
_INSET_BR = 0.06 / 0.14     # E1: y el claro baja abajo-derecha

#: Las dos sombras de E4 no valen lo que shadow.key: 0.55 y 0.40 frente a 0.50.
#: Tambien como razon, por lo mismo que los filos.
_E4_KEY = 0.55 / 0.50
_E4_TIGHT = 0.40 / 0.50

#: En claro los desenfoques y desplazamientos van al 60 %: las sombras largas y
#: negras ensucian el vidrio claro.
LIGHT_SHADOW_FACTOR = 0.60


def _elevations(edge: EdgeTokens, sh: ShadowTokens,
                geom: float = 1.0) -> dict[str, Elevation]:
    """Los cinco niveles del apartado 3.6, escritos una sola vez.

    ``geom`` encoge desenfoques y desplazamientos; en claro vale 0.60. Los
    colores salen de la paleta que entra, asi que la misma receta sirve para
    los dos temas sin duplicar un solo numero.
    """
    key, amb = sh.key, sh.ambient

    def s(role: str, blur: int, dx: int, dy: int, ink: Ink) -> Shadow:
        return Shadow(role, round(blur * geom), round(dx * geom),
                      round(dy * geom), ink)

    e2_shadows = (s("key", 32, 4, 10, key), s("ambient", 12, 0, 2, amb))
    return {
        # E1 se lee como un rebaje: el filo va invertido y no proyecta sombra
        "E1": Elevation("E1", "sunken",
                        edge_tl=edge.dark.scaled(_INSET_TL),
                        edge_br=edge.light.scaled(_INSET_BR),
                        shadows=()),
        "E2": Elevation("E2", "wash",
                        edge_tl=edge.light, edge_br=edge.dark,
                        shadows=e2_shadows, clip_canvas=True),
        # la especificacion solo redefine la sombra principal de E3; la ambiente
        # se hereda de E2 para que el contacto con el fondo no cambie al pasar
        # el raton por encima
        # E3 y E4 tambien pasan por s(): el apartado 3.6 dice "todos" los
        # desenfoques y desplazamientos al 60 % en claro, sin excepciones.
        # Construidas a pelo se quedaban con la geometria oscura y en claro
        # E4 proyectaba una sombra de 64 px desplazada 22 sobre fondo blanco,
        # que es exactamente el "ensuciar" que prohibe el apartado 11.3.
        "E3": Elevation("E3", "raised",
                        edge_tl=edge.light.scaled(_LIFT_E3), edge_br=edge.dark,
                        shadows=(s("key", 44, 5, 14, key), e2_shadows[1]),
                        scale=1.008),
        # la segunda sombra de E4 es corta y apretada: es la que la "pega"
        "E4": Elevation("E4", "float_",
                        edge_tl=edge.light.scaled(_LIFT_E4), edge_br=edge.dark,
                        shadows=(s("key", 64, 0, 22, key.at(_E4_KEY * key.alpha)),
                                 s("key", 8, 0, 3, key.at(_E4_TIGHT * key.alpha)))),
    }


# ------------------------------------------------------------------ paleta oscura
_DARK_CANVAS = CanvasTokens(
    base="#090B10",
    # es la fuente de luz del sistema: todo filo claro finge venir de aqui
    light=Blob(Ink("#22293A", 0.40), cx=0.18, cy=0.10, radius=0.62),
    # la especificacion solo fija el radio de la mancha de luz; los demas se
    # derivan de el hacia abajo para que ninguna mancha compita con la fuente
    cool=Blob(Ink("#0C1C2E", 0.34), cx=0.86, cy=0.92, radius=0.58),
    tint=Blob(Ink("#103038", 0.22), cx=0.98, cy=0.52, radius=0.44),
    vignette=Blob(Ink("#000000", 0.32), cx=1.00, cy=1.00, radius=0.70),
)

_DARK_GLASS = GlassTokens(
    wash=Surface(Ink("#FFFFFF", 0.055), "#171A22"),
    raised=Surface(Ink("#FFFFFF", 0.095), "#202430"),
    # hover no esta en el apartado 3: hace falta un escalon plano para el QSS.
    # Se extrapola linealmente del par wash/raised que si esta (+0.035 de alfa)
    hover=Surface(Ink("#FFFFFF", 0.130), "#282D3C"),
    # E4 es el nivel flotante: barra de navegacion, menus, el dialogo del
    # asistente, la capsula del overlay. Tiene que leerse como lo mas
    # cercano, y con Ink("#161921", 0.78) salia (19,22,29): la lamina MAS
    # OSCURA de las tres, un agujero que solo salvaba la sombra. La
    # especificacion se contradecia a si misma en este valor (daba tres
    # numeros distintos); se toma el de su formula, blanco incluido.
    float_=Surface(Ink("#2D3037", 0.798), "#26292F"),
    sunken=Surface(Ink("#000000", 0.28), "#070910"),
)

_DARK_EDGE = EdgeTokens(
    light=Ink("#FFFFFF", 0.14),
    dark=Ink("#000000", 0.45),
    hair=Ink("#FFFFFF", 0.07),
    flash=Ink("#FFFFFF", 0.30),
    dominant=Ink("#FFFFFF", 0.14),
)

_DARK_SHADOW = ShadowTokens(key=Ink("#000000", 0.50), ambient=Ink("#000000", 0.26))

_DARK_TEXT = TextTokens("#F2F4F9", "#A6AEC0", "#6F7789", "#4A5162")

_DARK_COLOR = ColorTokens(
    accent="#7C8CFF",
    accent_soft=Ink("#7C8CFF", 0.16),
    accent_glow=Ink("#7C8CFF", 0.32),
    ok="#5FE3B0", warn="#FFC46B", danger="#FF7A85", info="#74C0FF",
)

_DARK_MODES: Mapping[Mode, str] = {
    Mode.IDLE: "#8A94A6",
    Mode.POINTING: "#E8EDF5",
    Mode.PINCH_PENDING: "#7ED6FF",
    Mode.SCROLLING: "#B29EFF",
    Mode.DRAGGING: "#5FE3B0",
    Mode.WINDOW_MOVE: "#FFC46B",
    Mode.WINDOW_RESIZE: "#FFC46B",
    Mode.ZOOMING: "#96C8FF",
    Mode.KEYBOARD: "#E8EDF5",
    Mode.PAUSED: "#FF7A85",
}

DARK = Tokens(
    name="dark", dark=True,
    canvas=_DARK_CANVAS, glass=_DARK_GLASS, edge=_DARK_EDGE,
    shadow=_DARK_SHADOW, text=_DARK_TEXT, color=_DARK_COLOR,
    elevation=_elevations(_DARK_EDGE, _DARK_SHADOW),
    modes=_DARK_MODES, flick="#FFB05C",
)


# ------------------------------------------------------------------ paleta clara
# El claro no es la oscura invertida. Las sombras se acortan y se enfrian, y el
# filo que de verdad separa pasa a ser el oscuro de abajo-derecha.
# El lienzo claro baja de #EEF0F6 a #E4E7F0 a proposito. En claro no hay
# recorrido por encima del blanco, asi que el sitio para la rampa de
# elevaciones se saca por abajo: fondo mas bajo, laminas donde estaban. Con el
# fondo anterior el escalon lienzo-lamina quedaba en 1,5 % y una tarjeta E2
# apenas se despegaba del fondo.
_LIGHT_CANVAS = CanvasTokens(
    base="#E4E7F0",
    light=Blob(Ink("#FFFFFF", 0.52), cx=0.18, cy=0.10, radius=0.62),
    cool=Blob(Ink("#CFD5E4", 0.55), cx=0.86, cy=0.92, radius=0.58),
    tint=Blob(Ink("#DBE5F5", 0.40), cx=0.98, cy=0.52, radius=0.44),
    vignette=None,          # una vinneta en claro solo ensucia la esquina
)

_LIGHT_GLASS = GlassTokens(
    # En claro NO hay recorrido por encima del blanco. Con la rampa del oscuro
    # (mas blanco segun sube el nivel) E2, E3 y E4 salian 254/253/254: el mismo
    # blanco, y solo la sombra los separaba. Medido a ojo: E3 y E4
    # indistinguibles. Asi que aqui la rampa se INVIERTE: las laminas bajas se
    # dejan tenir por el lienzo y solo la flotante llega a blanco puro. El
    # recorrido se gana bajando el LIENZO, no las laminas: bajarlas acercaba
    # E2 al fondo y una tarjeta dejaba de despegarse.
    wash=Surface(Ink("#FFFFFF", 0.74), "#F4F6FA"),
    raised=Surface(Ink("#FFFFFF", 0.90), "#FBFCFE"),
    hover=Surface(Ink("#0F172A", 0.035), "#D8DCE8"),
    float_=Surface(Ink("#FFFFFF", 1.0), "#FFFFFF"),
    # Nada de pozos oscuros dentro de tarjetas claras, pero 0.045 era
    # invisible: el canal de un interruptor apagado desaparecia sobre lamina
    # blanca y solo lo salvaba su contorno de 1 px. Y ese interruptor es el de
    # "Inyectar clics", el mando mas importante del panel.
    sunken=Surface(Ink("#0F172A", 0.080), "#DDE1EB"),
)

_LIGHT_EDGE = EdgeTokens(
    light=Ink("#FFFFFF", 0.95),
    # si un panel desaparece a brillo 100 %, este sube a 0.14. Nunca se anade
    # una linea divisoria: eso romperia el principio 1
    dark=Ink("#0F172A", 0.10),
    hair=Ink("#0F172A", 0.06),
    flash=Ink("#0F172A", 0.22),
    dominant=Ink("#0F172A", 0.10),
)

_LIGHT_SHADOW = ShadowTokens(key=Ink("#1F2947", 0.14), ambient=Ink("#1F2947", 0.07))

_LIGHT_TEXT = TextTokens("#10131B", "#4E5768", "#798194", "#98A0B0")

_LIGHT_COLOR = ColorTokens(
    accent="#4257E8",
    accent_soft=Ink("#4257E8", 0.12),
    # el apartado 3.2 no fija el halo claro; se mantiene la razon 2:1 del oscuro
    accent_glow=Ink("#4257E8", 0.24),
    ok="#0F9E74", warn="#A66A05", danger="#C93848", info="#1F6FD0",
)

#: Rampa oscurecida para pasar AA sobre blanco.
_LIGHT_MODES: Mapping[Mode, str] = {
    Mode.IDLE: "#6B7686",
    Mode.POINTING: "#2A3140",
    Mode.PINCH_PENDING: "#1E7FB8",
    Mode.SCROLLING: "#6B4FD8",
    Mode.DRAGGING: "#0F9E74",
    Mode.WINDOW_MOVE: "#A66A05",
    Mode.WINDOW_RESIZE: "#A66A05",
    Mode.ZOOMING: "#1F6FD0",
    Mode.KEYBOARD: "#2A3140",
    Mode.PAUSED: "#C93848",
}

# En claro las sombras van acortadas (geom 0.60) y enfriadas: la tinta clara
# es un azul grisaceo, no un negro rebajado. Un negro translucido sobre blanco
# se ve sucio, y es el error tipico al portar un tema oscuro.
_LIGHT_ELEV = _elevations(_LIGHT_EDGE, _LIGHT_SHADOW, geom=0.60)

LIGHT = Tokens(
    name="light", dark=False,
    canvas=_LIGHT_CANVAS, glass=_LIGHT_GLASS, edge=_LIGHT_EDGE,
    shadow=_LIGHT_SHADOW, text=_LIGHT_TEXT, color=_LIGHT_COLOR,
    elevation=_LIGHT_ELEV, modes=_LIGHT_MODES, flick="#B85C05",
)

TOKENS: Mapping[str, Tokens] = {"dark": DARK, "light": LIGHT}
