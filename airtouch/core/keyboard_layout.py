"""Distribucion del teclado virtual (QWERTY espanol) y hit-testing.

Es un modelo puro: sin Qt. Lo usan tanto el motor de gestos (para saber que
tecla estas tocando) como el renderizador del overlay (para dibujarlo).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Teclas especiales: identificador -> (etiqueta, ancho relativo)
SHIFT = "@shift"
BACKSPACE = "@back"
ENTER = "@enter"
SPACE = "@space"
SYMBOLS = "@sym"
LETTERS = "@abc"
TAB = "@tab"
CLOSE = "@close"
LEFT = "@left"
RIGHT = "@right"

# Variantes que aparecen al hacer catapulta sobre una tecla
ACCENTS: dict[str, list[str]] = {
    "a": ["á", "à", "ä", "â", "ã", "å", "æ", "ª"],
    "e": ["é", "è", "ë", "ê", "€"],
    "i": ["í", "ì", "ï", "î"],
    "o": ["ó", "ò", "ö", "ô", "õ", "ø", "º"],
    "u": ["ú", "ù", "ü", "û"],
    "n": ["ñ"],
    "c": ["ç", "©"],
    "y": ["ý", "ÿ"],
    "s": ["ß", "$"],
    "z": ["ž"],
    "!": ["¡"],
    "?": ["¿"],
    "-": ["–", "—", "_"],
    ".": ["…", "·"],
    ",": [";"],
    "'": ["\"", "`", "´"],
    "1": ["¹", "½"],
    "2": ["²"],
    "3": ["³"],
    "0": ["º", "°"],
    "/": ["\\", "|"],
    "(": ["[", "{"],
    ")": ["]", "}"],
}

_ROWS_LETTERS = [
    list("1234567890"),
    list("qwertyuiop"),
    list("asdfghjklñ"),
    [SHIFT] + list("zxcvbnm,.") + [BACKSPACE],
    [SYMBOLS, "@", SPACE, "-", ENTER],
]

_ROWS_SYMBOLS = [
    list("1234567890"),
    list("!@#$%&*()"),
    list("-_=+/:;\"'"),
    [SHIFT] + list("¿?¡!<>[]") + [BACKSPACE],
    [LETTERS, ",", SPACE, ".", ENTER],
]

_WIDE = {SPACE: 4.6, ENTER: 1.9, BACKSPACE: 1.7, SHIFT: 1.7, SYMBOLS: 1.7, LETTERS: 1.7}

_LABELS = {
    SHIFT: "⇧", BACKSPACE: "⌫", ENTER: "⏎", SPACE: "espacio",
    SYMBOLS: "?123", LETTERS: "ABC", TAB: "⇥", CLOSE: "✕",
    LEFT: "◀", RIGHT: "▶",
}


@dataclass
class Key:
    ident: str
    label: str
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def is_special(self) -> bool:
        return self.ident.startswith("@")

    def contains(self, px: float, py: float, pad: float = 0.0) -> bool:
        return (self.x - pad) <= px <= (self.x + self.w + pad) and \
               (self.y - pad) <= py <= (self.y + self.h + pad)

    def accents(self) -> list[str]:
        return ACCENTS.get(self.ident.lower(), [])


@dataclass
class KeyboardLayout:
    """Teclado colocado dentro de un rectangulo de pantalla."""

    keys: list[Key] = field(default_factory=list)
    rect: tuple[float, float, float, float] = (0, 0, 0, 0)
    shift: bool = False
    symbols: bool = False
    key_h: float = 0.0
    gap: float = 0.0

    def build(self, x: float, y: float, w: float, h: float) -> None:
        self.rect = (x, y, w, h)
        rows = _ROWS_SYMBOLS if self.symbols else _ROWS_LETTERS
        n_rows = len(rows)
        pad = w * 0.012
        gap = w * 0.008
        self.gap = gap
        usable_w = w - 2 * pad
        usable_h = h - 2 * pad
        key_h = (usable_h - gap * (n_rows - 1)) / n_rows
        self.key_h = key_h

        self.keys = []
        for r, row in enumerate(rows):
            units = sum(_WIDE.get(k, 1.0) for k in row)
            unit_w = (usable_w - gap * (len(row) - 1)) / units
            cx = x + pad
            cy = y + pad + r * (key_h + gap)
            for ident in row:
                kw = unit_w * _WIDE.get(ident, 1.0)
                self.keys.append(Key(ident, self.label_for(ident), cx, cy, kw, key_h))
                cx += kw + gap

    def label_for(self, ident: str) -> str:
        if ident in _LABELS:
            return _LABELS[ident]
        return ident.upper() if self.shift else ident

    def relabel(self) -> None:
        for k in self.keys:
            k.label = self.label_for(k.ident)

    def hit(self, px: float, py: float, pad: float = 0.0) -> Key | None:
        for k in self.keys:
            if k.contains(px, py, pad):
                return k
        return None

    def nearest(self, px: float, py: float, max_dist: float) -> Key | None:
        best, best_d = None, max_dist ** 2
        for k in self.keys:
            d = (px - k.cx) ** 2 + (py - k.cy) ** 2
            if d < best_d:
                best, best_d = k, d
        return best

    def contains(self, px: float, py: float) -> bool:
        x, y, w, h = self.rect
        return x <= px <= x + w and y <= py <= y + h

    def output_for(self, key: Key) -> str:
        """Texto que produce una tecla normal, respetando shift."""
        return key.ident.upper() if self.shift else key.ident
