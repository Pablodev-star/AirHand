"""Tokens del overlay y constantes de dano (apartado 10 de la especificacion).

El overlay flota sobre contenido arbitrario, asi que **no puede apoyarse en un
fondo que controle**: aqui no vale el truco del lienzo pre-desenfocado de
``glass.py``, que solo funciona dentro de la ventana de la aplicacion. Su vidrio
es **autoiluminado**: placa opaca tenida por el color del estado, realce interior
arriba-izquierda y un halo exterior amplio y blando del mismo color. Se lee como
un objeto encendido este lo que este detras.

Tres cosas que conviene entender antes de tocar nada:

* **Las constantes de dano son la ley del proyecto** (10.1). Ningun elemento del
  HUD puede declarar una region que dependa del ancho de la pantalla ni del
  ancho de una ventana. Por eso todas las medidas de dano viven aqui arriba,
  como constantes, y ``canvas.py`` construye su region con ellas. El unico
  elemento que se sale es el anillo de pantalla de la pausa, y se sale a
  proposito: *es* el borde de la pantalla, se pinta una vez y se queda quieto.
* **El halo sale del atlas de sombras.** ``glass.ATLAS`` cachea rounded-rects
  desenfocados por (radio, desenfoque, tinta) y los pinta en ocho ``drawImage``.
  Un halo es una sombra de color sin desplazamiento, asi que sale gratis y con
  el alcance exacto que declara la constante de dano: el margen del atlas es el
  desenfoque, y ese es justo el relleno que se reserva.
* **Ningun color escrito a mano.** Todo sale de ``ui/tokens.py`` a traves de
  ``theme``. La placa de la capsula es el lienzo del tema tenido por el color
  del estado, no un rgba inventado.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPen, QPixmap, QRadialGradient)

from ..gestures.events import Mode
from ..ui import glass, theme, tipo
from ..ui.tokens import DARK, LIGHT, Ink, R_KEY, Shadow, Tokens, compose

__all__ = [
    "P", "Paleta", "apply_theme",
    "CURSOR_CORE_D", "CURSOR_RING_R", "CURSOR_RING_PINCH_R",
    "CURSOR_RING_OVERSHOOT_R", "CURSOR_GLOW_R", "CURSOR_ARC_W",
    "CURSOR_FLASH_D", "CURSOR_FLASH_MS", "CURSOR_ARC_GAP_DEG", "CURSOR_DAMAGE",
    "CAPSULE_H", "CAPSULE_R", "CAPSULE_MIN_W", "CAPSULE_MAX_W", "CAPSULE_Y",
    "CAPSULE_GLOW", "CAPSULE_PAD", "CAPSULE_DAMAGE", "CAPSULE_DAMAGE_SMALL",
    "CAPSULE_COLLAPSE_MS", "CAPSULE_REEXPAND_MS", "CAPSULE_FADE_MS",
    "HATCH_STEP", "HATCH_ALPHA", "HATCH_ALPHA_LIGHT",
    "LAMP_D", "LAMP_ALPHA", "LAMP_DOT_D", "LAMP_DAMAGE", "LAMP_DOT_DAMAGE",
    "RING_THICK", "RING_ALPHA", "PILL_DY", "PILL_RISE", "PILL_DAMAGE",
    "CHROME_BAR_H", "CHROME_BAR_MIN_W", "CHROME_BAR_MAX_W", "CHROME_BAR_GAP",
    "CHROME_DASH_GAP", "CHROME_DASH_H", "CHROME_CORNER_R", "CHROME_CORNER_THICK",
    "CHROME_GLOW", "CHROME_GLOW_HELD", "CHROME_BLUR",
    "CHROME_DAMAGE_BAR", "CHROME_DAMAGE_DASH", "CHROME_DAMAGE_CORNER",
    "PANEL_RADIUS", "KEY_RADIUS", "KEY_PAD", "KEY_LIFT", "KEY_RING",
    "KEY_RING_MS", "ZOOM_PAD",
    "font", "fuente", "glow_gradient", "hatch_brush", "paint_glow",
    "paint_plate", "breath",
]


# --------------------------------------------------------------------------- #
# 10.2  cursor
# --------------------------------------------------------------------------- #
CURSOR_CORE_D = 9.0             # diametro del nucleo blanco
CURSOR_RING_R = 20.0            # radio del anillo de modo en reposo
CURSOR_RING_PINCH_R = 13.0      # al que se contrae al pinzar (90 ms)
CURSOR_RING_OVERSHOOT_R = 23.0  # sobrepaso al soltar, antes de asentar en 20
CURSOR_GLOW_R = 30.0            # halo radial (antes 34: se baja)
CURSOR_GLOW_ALPHA = 0.14        # (antes 46/255 = 0.18)
CURSOR_RING_ALPHA = 0.55
CURSOR_CORE_ALPHA = 0.94
CURSOR_ARC_W = 2.5              # medidor de pinch sobre el anillo
CURSOR_FLASH_D = 13.0           # destello del nucleo al cruzar el umbral
CURSOR_FLASH_MS = 120.0
#: Hueco arriba del medidor. El arco recorre 340 grados y no 360 para que las
#: dos muescas de umbral (la de cierre y la de apertura) no caigan en el mismo
#: pixel: un medidor circular completo no tiene principio ni final visibles.
CURSOR_ARC_GAP_DEG = 20.0
#: Radio maximo 30 + 4 de margen. Constante: el cursor es lo que mas se mueve y
#: lo que mas veces se repinta, asi que su region no puede crecer con nada.
CURSOR_DAMAGE = (68, 68)        # 4,6 kpx


# --------------------------------------------------------------------------- #
# 10.3  capsula de estado
# --------------------------------------------------------------------------- #
CAPSULE_H = 44.0
CAPSULE_R = 22.0
CAPSULE_MIN_W = 132.0
#: Tope duro del ancho. El detalle se recorta antes que pasar de aqui, porque de
#: este numero cuelga la constante de dano y no puede depender del texto.
CAPSULE_MAX_W = 268.0
CAPSULE_Y = 28.0                # borde superior, arriba y centrada
#: Desenfoque del halo. El atlas reserva exactamente este margen alrededor de la
#: forma, asi que es tambien el relleno de la region de dano.
CAPSULE_GLOW = 24
CAPSULE_PAD = float(CAPSULE_GLOW)
CAPSULE_GLOW_ALPHA = 0.16
#: (268 + 48) x (44 + 48) = 29,1 kpx expandida. Solo se paga mientras cambia:
#: quieta sale de la region sucia a los dos fotogramas (10.1.2).
CAPSULE_DAMAGE = (int(CAPSULE_MAX_W + 2 * CAPSULE_PAD),
                  int(CAPSULE_H + 2 * CAPSULE_PAD))
#: Colapsada es un circulo de 44: 92 x 92 = 8,5 kpx.
CAPSULE_DAMAGE_SMALL = (int(CAPSULE_H + 2 * CAPSULE_PAD),
                        int(CAPSULE_H + 2 * CAPSULE_PAD))

CAPSULE_COLLAPSE_MS = 4000.0    # el modo seguro se vuelve ambiental
CAPSULE_REEXPAND_MS = 2500.0    # y vuelve ante un cambio de modo
CAPSULE_FADE_MS = 140.0         # el texto se va en los primeros 140 ms
CAPSULE_ANATOMY = (16.0, 22.0, 10.0, 10.0, 8.0)  # pad, glifo, hueco, hueco, hueco

#: Rayado diagonal del modo seguro: la textura universal de "esto es un ensayo".
HATCH_STEP = 6.0
HATCH_ALPHA = 0.14
HATCH_ALPHA_LIGHT = 0.10

#: Respiracion de la pausa (senoidal, 1,6 s, a 20 Hz).
BREATH_MS = 1600.0
BREATH_LOW = 0.12
BREATH_HIGH = 0.26

#: Hairline de cuenta atras pegada al borde inferior interior.
COUNTDOWN_H = 2.0
COUNTDOWN_INSET = 3.0

#: Anillo de 2 px en el borde de TODA la pantalla, en cuatro rectangulos finos.
#: 2 x (2560 + 1440) x 2 = 16 kpx, y se pinta una vez: despues queda quieto.
RING_THICK = 2.0
RING_ALPHA = 0.22

#: Lampara del control activo: sin capsula, solo esto, y al 55 %.
LAMP_D = 34.0
LAMP_DOT_D = 12.0
LAMP_ALPHA = 0.55
LAMP_DAMAGE = (40, 40)
#: El punto que respira invalida solo su circulo: 0,6 kpx en vez de 16.
LAMP_DOT_DAMAGE = (24, 24)


# --------------------------------------------------------------------------- #
# 10.4  pildora inferior de modo
# --------------------------------------------------------------------------- #
PILL_DY = 54.0                  # centro en y = alto - 54
PILL_RISE = 12.0                # entra deslizando 12 px hacia arriba
PILL_NOTE_MS = 1100.0
PILL_DAMAGE = CAPSULE_DAMAGE


# --------------------------------------------------------------------------- #
# 10.5  barras de ventana
# --------------------------------------------------------------------------- #
CHROME_BAR_H = 7.0
CHROME_BAR_MIN_W = 96.0
CHROME_BAR_MAX_W = 260.0        # el tope que hace constante la region
CHROME_BAR_GAP = 13.0
CHROME_DASH_GAP = 34.0          # guiones de arrastre, a 34 px de la barra
CHROME_DASH_H = 14.0
CHROME_CORNER_R = 26.0
CHROME_CORNER_THICK = 6.0
CHROME_BLUR = 18                # desenfoque del halo = margen de dano
CHROME_GLOW = 0.16
CHROME_GLOW_HELD = 0.34         # al agarrarla, en 120 ms
#: 260 + 36 = 296 de ancho y 7 + 36 = 43 de alto: caben en (300, 44).
CHROME_DAMAGE_BAR = (300, 44)
CHROME_DAMAGE_DASH = (36, 36)
CHROME_DAMAGE_CORNER = (96, 96)  # antes 120x120


# --------------------------------------------------------------------------- #
# 10.6  teclado
# --------------------------------------------------------------------------- #
PANEL_RADIUS = 26.0
KEY_RADIUS = float(R_KEY)
KEY_PAD = 10.0                  # margen de dano de UNA tecla
KEY_LIFT = 2.0                  # la tecla se eleva al pasar por encima
KEY_RING = 8.0                  # anillo que se expande al activarla
KEY_RING_MS = 220.0
KEY_FADE_MS = 90.0
ZOOM_PAD = 46.0


# --------------------------------------------------------------------------- #
# la paleta
# --------------------------------------------------------------------------- #

def _c(hex_color: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


@dataclass(frozen=True)
class Paleta:
    """Los colores del overlay, derivados de los tokens del tema activo.

    Nada de esto se escribe a mano: el nucleo del cursor es el texto primario de
    la paleta, la placa es el lienzo tenido por el color del estado y los tintes
    de modo son la rampa del apartado 3.1 tal cual.
    """

    tokens: Tokens
    dark: bool

    core: QColor                # nucleo del cursor
    outline: QColor             # contorno oscuro: lo que lo salva sobre blanco
    glow: QColor                # halo del cursor
    text: QColor                # texto del HUD
    text_dim: QColor            # detalle del HUD
    warn: QColor
    danger: QColor
    edge: QColor                # realce interior arriba-izquierda
    panel: QColor               # placa del teclado
    key_fill: QColor
    key_hover: QColor
    key_active: QColor
    key_text: QColor
    key_text_active: QColor
    key_edge: QColor
    hatch_alpha: float

    def modo(self, mode: Mode, flick: bool = False) -> QColor:
        return QColor(self.tokens.mode_color(mode, flick))

    def placa(self, estado: QColor, alpha: float = 0.86) -> QColor:
        """Placa autoiluminada: el lienzo del tema, tenido por el estado.

        El apartado 10.3 la escribe como ``rgba(18,14,6,0.72)`` para el modo
        seguro, que es exactamente eso: casi negro con una gota de ambar. Aqui
        se deriva en vez de copiarse, y asi el tema claro sale solo.
        """
        base = self.tokens.canvas.base if self.dark else self.tokens.glass.float_.solid
        return _c(compose(estado.name(), 0.10 if self.dark else 0.05, base), alpha)


def _paleta(t: Tokens) -> Paleta:
    ink, col = t.text, t.color
    # El nucleo del cursor es blanco en los dos temas y lleva contorno oscuro:
    # el cursor flota sobre el escritorio, no sobre nuestro lienzo, y el tema de
    # la aplicacion no dice nada de lo que hay debajo.
    return Paleta(
        tokens=t, dark=t.dark,
        core=_c("#FFFFFF", CURSOR_CORE_ALPHA),
        outline=_c(t.canvas.base if t.dark else ink.primary, 0.58),
        glow=_c("#FFFFFF", CURSOR_GLOW_ALPHA),
        text=_c(ink.primary if t.dark else ink.primary, 0.92),
        text_dim=_c(ink.secondary, 0.86),
        warn=_c(col.warn), danger=_c(col.danger),
        edge=_c(t.edge.light.hex, t.edge.light.alpha * (1.0 if t.dark else 0.7)),
        panel=_c(t.glass.float_.solid, 0.90),
        key_fill=_c(ink.primary if t.dark else t.canvas.base, 0.10),
        key_hover=_c(ink.primary if t.dark else t.canvas.base, 0.25),
        key_active=_c(ink.primary if t.dark else t.canvas.base, 0.89),
        key_text=_c(ink.primary, 0.92),
        key_text_active=_c(t.canvas.base if t.dark else t.glass.float_.solid),
        key_edge=_c(t.edge.light.hex, t.edge.light.alpha),
        hatch_alpha=HATCH_ALPHA if t.dark else HATCH_ALPHA_LIGHT,
    )


#: Paleta activa. ``canvas.py`` la lee en cada repintado.
P: Paleta = _paleta(DARK)


def apply_theme(dark: bool) -> None:
    """Adapta el overlay al tema. Lo llama ``app.py`` al arrancar y al cambiar."""
    global P
    P = _paleta(DARK if dark else LIGHT)
    _HATCH.clear()


# --------------------------------------------------------------------------- #
# tipografia (toda por tipo.py: apartado 3.3 y ley 1 del proyecto)
# --------------------------------------------------------------------------- #

def fuente(rol: str, *, size: float | None = None, weight: int | None = None,
           tracking: float | None = None) -> QFont:
    """Fuente del overlay. El cuerpo y el peso salen de ``tipo``; el tracking se
    ajusta encima porque la escala no trae una fila de +0.4 y el apartado 10.3
    la pide para el rotulo de la capsula.
    """
    f = tipo.font(rol, size=size, weight=weight)
    if tracking is not None:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, tracking)
    return f


def font(size: float, weight: int = 500) -> QFont:
    """Compatibilidad: la ventana de calibracion pide fuentes por cuerpo.

    Se resuelve por ``tipo`` igual que todo lo demas, asi que hereda la talla
    optica, las cifras tabulares y los respaldos de familia.
    """
    rol = "h1" if size >= 16 else "body" if size >= 12 else "caption"
    return tipo.font(rol, size=float(size), weight=weight)


# --------------------------------------------------------------------------- #
# pintura compartida
# --------------------------------------------------------------------------- #

def glow_gradient(cx: float, cy: float, r: float, color: QColor) -> QRadialGradient:
    """Halo radial. Lo usan el cursor y la ventana de calibracion."""
    g = QRadialGradient(cx, cy, max(1.0, r))
    inner = QColor(color)
    medio = QColor(color)
    medio.setAlphaF(color.alphaF() * 0.42)
    fuera = QColor(color)
    fuera.setAlpha(0)
    g.setColorAt(0.0, inner)
    g.setColorAt(0.45, medio)
    g.setColorAt(1.0, fuera)
    return g


_HATCH: dict[tuple, QPixmap] = {}


def hatch_brush(color: QColor, step: float = HATCH_STEP) -> QBrush:
    """Rayado diagonal a 45 grados, en un tile cacheado que se repite solo.

    El tile es un cuadrado de lado ``step`` con su diagonal, mas las dos
    diagonales vecinas desplazadas: sin ellas las esquinas del tile quedan sin
    linea y el rayado sale a trozos al repetirse.
    """
    key = (color.rgba(), round(step, 2))
    hit = _HATCH.get(key)
    if hit is None:
        s = max(2, int(round(step)))
        hit = QPixmap(s, s)
        hit.fill(Qt.GlobalColor.transparent)
        p = QPainter(hit)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(color, 1.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        for off in (-s, 0, s):
            p.drawLine(QPointF(off, s), QPointF(off + s, 0.0))
        p.end()
        _HATCH[key] = hit
    return QBrush(hit)


def paint_glow(painter: QPainter, rect: QRectF, radius: float, color: QColor,
               alpha: float, blur: int = CAPSULE_GLOW) -> None:
    """Halo exterior blando del color del estado, desde el atlas de sombras.

    Un halo es una sombra de color sin desplazamiento. Reusar el atlas cuesta
    ocho ``drawImage`` de un tile cacheado en vez de seis rounded-rects
    apilados, y su alcance es exactamente ``blur``, que es la constante con la
    que se dimensiona la region de dano.
    """
    if alpha <= 0.002:
        return
    ink = Ink(color.name(), max(0.0, min(1.0, alpha)))
    glass.ATLAS.paint(painter, rect, radius, Shadow("key", int(blur), 0, 0, ink))


def paint_plate(painter: QPainter, rect: QRectF, radius: float,
                estado: QColor, *, alpha_placa: float = 0.86,
                filo: float = 1.0) -> None:
    """Placa autoiluminada: relleno opaco, realce interior arriba-izquierda.

    El realce va **dentro** del camino, con un degradado que muere a media
    altura: es lo que hace que la pieza parezca encendida en vez de recortada, y
    es tambien lo que hace que una tecla plana parezca una tecla (10.6).
    """
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(P.placa(estado, alpha_placa))
    painter.drawRoundedRect(rect, radius, radius)

    realce = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.center().y()))
    arriba = QColor(P.edge)
    arriba.setAlphaF(P.edge.alphaF() * 1.6)
    abajo = QColor(P.edge)
    abajo.setAlpha(0)
    realce.setColorAt(0.0, arriba)
    realce.setColorAt(1.0, abajo)
    painter.setBrush(QBrush(realce))
    painter.drawRoundedRect(rect, radius, radius)

    if filo > 0.0:
        pen = QPen(_c(estado.name(), 0.34), 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    painter.restore()


def breath(phase: float) -> float:
    """Respiracion senoidal 0..1 a partir de una fase 0..1."""
    import math

    return 0.5 - 0.5 * math.cos(phase * 2.0 * math.pi)
