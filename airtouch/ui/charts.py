"""Los graficos del panel, pintados a mano con QPainter (apartado 7).

No hay QtCharts ni QtWebEngine y no se anaden dependencias: cada grafico es un
``paintEvent`` y un pixmap. Eso no es una limitacion, es lo que permite cumplir
el presupuesto de repintado, porque una libreria de graficos no sabe nada de que
en esta ventana solo se puede tocar la columna nueva.

Las tres reglas que sostienen el presupuesto, y que son el motivo de que este
archivo tenga la forma que tiene:

* **Blit desplazado en toda traza temporal.** Una traza guarda un ``QPixmap`` del
  tamano del pozo; cuando entra una muestra, ``QPixmap.scroll`` mueve el pozo un
  paso a la izquierda y solo se pinta la columna nueva. Repintar la traza entera
  por muestra cuesta veinte veces mas (los dos numeros estan medidos en
  ``tools/prueba_charts.py``, no estimados).
* **Ningun grafico tiene temporizador propio.** Se apuntan al ``Beat`` con su
  compuerta de frecuencia mediante el mixin ``Beating``, y solo mientras haya
  algo que interpolar. Un histograma con las alturas ya asentadas no despierta
  la CPU.
* **``update()`` solo cuando llegan datos nuevos**, y con el rectangulo de la
  columna, no con el widget entero.

Dos cosas del diseno que conviene entender antes de tocar nada:

* ``ScrollBuffer`` es dumb a proposito: sabe desplazarse y limpiar la columna,
  y nada mas. Quien dibuja es su dueno. Asi el mismo mecanismo sirve a un widget
  suelto dentro de un pozo E1 y a una tarjeta de vidrio que pinta el grafico en
  su propia superficie, que son los dos sitios donde hace falta.
* **``WA_OpaquePaintEvent`` solo se pone cuando el widget pinta de verdad todos
  sus pixeles**, o sea cuando tiene suelo propio (``ground=True``, el pozo E1
  del apartado 3.6). Un grafico transparente sobre vidrio no lo lleva: con el
  puesto, Qt se ahorra recomponer el fondo y en el pozo queda la basura del
  fotograma anterior. La regla del apartado 7 se cumple donde significa algo.

Los rellenos de area van a alfa 0.90 en oscuro y **0.36 en claro** (apartado
11.5). En claro el pozo es ``glass.sunken`` claro, nunca negro (11.4): un pozo
oscuro dentro de una tarjeta clara es exactamente lo que hace que estos sistemas
se vean baratos.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum
from typing import Sequence

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import QWidget

from ..gestures.events import Mode
from . import glass, motion, theme, tipo
from .kit.base import Beating, Sheet, ThemeAware
from .tokens import R_LG, R_MD, R_XS, SHEET_PADDING

__all__ = [
    "ScrollBuffer", "ChartWidget",
    "Trace", "StackedTrace", "AreaChart", "Histogram", "Donut", "Scatter",
    "Heartbeat", "Strip", "Sparkline",
    "LatencyBudget", "Closures", "PointerStability",
    "Outcome", "Advice", "tremor", "closure_advice",
    "AREA_ALPHA_DARK", "AREA_ALPHA_LIGHT", "TREMOR_WINDOW",
]


# --------------------------------------------------------------------------- #
# constantes del apartado 7 y del 11
# --------------------------------------------------------------------------- #

#: Relleno de las areas. En claro baja a 0.36 o el grafico se come el texto.
AREA_ALPHA_DARK = 0.90
AREA_ALPHA_LIGHT = 0.36

#: Rejilla: cuatro horizontales y **ninguna vertical** (apartado 8.5.1).
GRID_LINES = 4

#: Halo del punto de cabeza de una traza. Es lo que pide los 12 px de holgura
#: del rectangulo de dano: sin ellos el halo se corta con canto recto.
HEAD_HALO = 12.0

#: La linea de escrutinio persigue al cursor con esta constante de tiempo.
TAU_SCRUTINY = 0.05

#: Muestras de la ventana de temblor (apartado 6.3).
TREMOR_WINDOW = 300

#: Posiciones superpuestas en la huella del puntero (apartado 8.5.7).
FOOTPRINT_POINTS = 600

#: Objetivo del presupuesto de retardo, en ms (apartado 8.5.3).
BUDGET_TARGET_MS = 100.0


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #

def num(value: float, decimals: int = 0) -> str:
    """Numero con coma decimal. Lo lee un humano espanol, no un parser."""
    return f"{value:.{decimals}f}".replace(".", ",")


def nice_step(span: float, lines: int = GRID_LINES) -> float:
    """Paso de rejilla de la familia 1 / 2 / 5 x 10^n.

    Sin esto los ejes salen con etiquetas de 37,4 y 74,8 y el grafico parece
    generado por una maquina en vez de leido por una persona.
    """
    if span <= 0.0 or lines <= 0:
        return 1.0
    crudo = span / lines
    exp = math.floor(math.log10(crudo))
    base = crudo / (10.0 ** exp)
    for corte in (1.0, 2.0, 5.0):
        if base <= corte:
            return corte * (10.0 ** exp)
    return 10.0 ** (exp + 1)


def ceil_nice(value: float, margin: float = 1.18) -> float:
    """Techo de eje redondeado hacia arriba a un multiplo de rejilla bonito."""
    objetivo = max(1e-6, value * margin)
    paso = nice_step(objetivo, GRID_LINES)
    return math.ceil(objetivo / paso) * paso


def area_alpha() -> float:
    return AREA_ALPHA_DARK if theme.C.dark else AREA_ALPHA_LIGHT


def _c(hex_color: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def area_gradient(rect: QRectF, hex_color: str) -> QLinearGradient:
    """Relleno del apartado 8.5.1: del color de la serie a transparente."""
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0.0, _c(hex_color, area_alpha()))
    g.setColorAt(1.0, _c(hex_color, 0.0))
    return g


def draw_grid(p: QPainter, well: QRectF, lo: float, hi: float, *,
              unit: str = "", labels: bool = True) -> float:
    """Cuatro horizontales en ``edge.hair`` y sus etiquetas. Devuelve el paso.

    Ninguna vertical, nunca: el tiempo ya lo cuenta el desplazamiento, y una
    rejilla vertical sobre una traza que se mueve produce un batido feisimo.
    """
    if hi <= lo:
        return 1.0
    paso = nice_step(hi - lo, GRID_LINES)
    pen = QPen(glass.qcolor(theme.C.edge.hair))
    pen.setWidthF(1.0)
    pen.setCosmetic(True)
    p.setPen(pen)
    fuente = tipo.font("axis")
    etiquetas: list[tuple[float, str]] = []
    v = math.ceil(lo / paso) * paso
    while v <= hi + 1e-9:
        y = well.bottom() - (v - lo) / (hi - lo) * well.height()
        p.drawLine(QPointF(well.left(), round(y) + 0.5),
                   QPointF(well.right(), round(y) + 0.5))
        etiquetas.append((y, f"{num(v, 0 if paso >= 1 else 1)}{unit}"))
        v += paso
    if labels:
        p.setFont(fuente)
        p.setPen(QColor(theme.C.ink.tertiary))
        alto = tipo.metrics("axis").height()
        for y, txt in etiquetas:
            p.drawText(QRectF(well.left() + 4, y - alto - 1, well.width() - 8, alto),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       txt)
    return paso


def veil(p: QPainter, rect: QRectF, band: float = 0.55) -> None:
    """El velo del apartado 4.3, para el texto que cae sobre un grafico vivo.

    ``glass.paint_sheet`` lo pone solo cuando la lamina lleva sangrado. Las
    tarjetas que pintan su grafico ellas mismas tienen que ponerlo a mano, y sin
    el el texto deja de leerse justo cuando hay datos interesantes.
    """
    zona = QRectF(rect.left(), rect.bottom() - rect.height() * band,
                  rect.width(), rect.height() * band)
    fuerte = glass.VEIL_DARK if theme.C.dark else glass.VEIL_LIGHT
    claro = QColor(fuerte)
    claro.setAlpha(0)
    g = QLinearGradient(zona.topLeft(), zona.bottomLeft())
    g.setColorAt(0.0, claro)
    g.setColorAt(1.0, fuerte)
    p.fillRect(zona, g)


def _rounded_top(rect: QRectF, radius: float) -> QPainterPath:
    """Barra con el tope redondeado y la base recta."""
    r = min(radius, rect.width() / 2.0, rect.height())
    path = QPainterPath()
    if r <= 0.5:
        path.addRect(rect)
        return path
    path.moveTo(rect.left(), rect.bottom())
    path.lineTo(rect.left(), rect.top() + r)
    path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())
    path.lineTo(rect.right() - r, rect.top())
    path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
    path.lineTo(rect.right(), rect.bottom())
    path.closeSubpath()
    return path


# --------------------------------------------------------------------------- #
# el pozo que se desplaza a si mismo
# --------------------------------------------------------------------------- #

class ScrollBuffer:
    """Pixmap de traza temporal que se desplaza a si mismo (apartado 7).

    Es la pieza que sostiene el presupuesto entero. Cuando entra una muestra,
    ``advance()`` mueve el contenido un paso a la izquierda con ``QPixmap.scroll``
    y devuelve **la columna nueva**, que es lo unico que hay que pintar. A 420 px
    de ancho con paso 2 eso son 2 columnas de pixeles en vez de 420.

    Sabe desplazarse y limpiar, y nada mas: quien dibuja es su dueno. Asi el
    mismo mecanismo sirve a un widget suelto en un pozo E1 y a una tarjeta de
    vidrio que pinta el grafico sobre su propia superficie.

    **El paso se guarda en pixeles de dispositivo.** ``QPixmap.scroll`` trabaja
    en pixeles reales aunque el pixmap lleve ``devicePixelRatio``, asi que un
    paso logico de 2 px a escala 150 % desplazaria 2 pixeles reales y la traza
    se comprimiria un tercio por muestra. Se guarda entero en dispositivo y se
    deriva el logico, no al reves.
    """

    __slots__ = ("_pm", "_dpr", "_step_dev", "_size", "_transparent", "_dirty")

    def __init__(self, transparent: bool = False) -> None:
        self._pm: QPixmap | None = None
        self._dpr = 1.0
        self._step_dev = 2
        self._size = QSize()
        self._transparent = bool(transparent)
        self._dirty = True

    # -- ciclo de vida ------------------------------------------------------
    def configure(self, size: QSize, dpr: float, step: float) -> bool:
        """Ajusta el pozo. ``True`` si hay que redibujarlo entero.

        Devuelve ``True`` al crecer, al cambiar de escala y al arrancar. El
        apartado 7 pide exactamente eso: al cambiar el tema o el tamano se
        regenera el pixmap entero **una vez**, no por fotograma.
        """
        dpr = max(1.0, float(dpr))
        paso = max(1, int(round(step * dpr)))
        if (self._pm is not None and self._size == size
                and abs(self._dpr - dpr) < 1e-6 and self._step_dev == paso):
            return self._dirty
        self._size = QSize(size)
        self._dpr = dpr
        self._step_dev = paso
        if size.isEmpty():
            self._pm = None
            return False
        pm = QPixmap(max(1, int(math.ceil(size.width() * dpr))),
                     max(1, int(math.ceil(size.height() * dpr))))
        pm.setDevicePixelRatio(dpr)
        self._pm = pm
        self._dirty = True
        return True

    def invalidate(self) -> None:
        """Marca el pozo para regeneracion completa (tema, rango, datos)."""
        self._dirty = True

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def valid(self) -> bool:
        return self._pm is not None

    @property
    def pixmap(self) -> QPixmap | None:
        return self._pm

    @property
    def step(self) -> float:
        """Paso en pixeles logicos. Puede ser fraccionario: no pasa nada."""
        return self._step_dev / self._dpr

    @property
    def size(self) -> QSize:
        return self._size

    # -- pintado ------------------------------------------------------------
    def fill(self, ground: QColor | None) -> None:
        """Deja el pozo listo para que su dueno lo redibuje entero."""
        if self._pm is None:
            return
        self._pm.fill(ground if ground is not None else Qt.GlobalColor.transparent)
        self._dirty = False

    def advance(self) -> QRectF:
        """Desplaza el pozo un paso y devuelve la columna nueva, en logicas.

        No limpia: limpiar exige abrir un ``QPainter``, y el dueno va a abrir
        uno de todas formas para pintar la columna. Abrir dos por muestra es el
        tipo de coste que no se ve hasta que hay ocho graficos en pantalla.
        """
        if self._pm is None:
            return QRectF()
        self._pm.scroll(-self._step_dev, 0, self._pm.rect())
        paso = self.step
        return QRectF(self._size.width() - paso, 0.0, paso,
                      float(self._size.height()))

    def clear_column(self, p: QPainter, col: QRectF,
                     ground: QColor | None) -> None:
        """Borra la columna vacante. Transparente o con suelo, segun el pozo."""
        if self._transparent or ground is None:
            modo = p.compositionMode()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(col, Qt.GlobalColor.transparent)
            p.setCompositionMode(modo)
        else:
            p.fillRect(col, ground)


# --------------------------------------------------------------------------- #
# base comun de los widgets de grafico
# --------------------------------------------------------------------------- #

class ChartWidget(ThemeAware, Beating, QWidget):
    """Base de todos los graficos: pozo cacheado, latido compartido, escrutinio.

    Un grafico no crea temporizadores (se apunta al ``Beat``), no se conecta a
    la senal de tema (lo hace ``ThemeAware``) y no repinta el widget entero por
    fotograma (usa ``update(QRect)``).

    ``ground=True`` da suelo propio: el widget rellena todos sus pixeles con
    ``glass.sunken`` y lleva ``WA_OpaquePaintEvent``. Es el pozo E1 del apartado
    3.6. ``ground=False`` lo deja transparente para pintarse sobre el vidrio de
    una lamina, y entonces **no** lleva el atributo: seria mentir y en el pozo
    quedaria la basura del fotograma anterior.
    """

    BEAT_HZ = motion.HZ_FULL

    #: Los graficos temporales encienden la linea de escrutinio del apartado 7.
    SCRUTINY = False

    def __init__(self, parent: QWidget | None = None, *,
                 ground: bool = True, margins: tuple[float, ...] = (0, 0, 0, 0)
                 ) -> None:
        super().__init__(parent)
        self._ground = bool(ground)
        self._margins = tuple(float(m) for m in margins)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, self._ground)
        self._scrutiny = motion.Smooth(0.0, TAU_SCRUTINY)
        self._scrutiny_on = False
        self._scrutiny_damage = QRect()
        if self.SCRUTINY:
            self.setMouseTracking(True)

    # -- geometria ----------------------------------------------------------
    def ground_color(self) -> QColor | None:
        """El suelo del pozo. En claro es ``#E7EAF1``, jamas negro (11.4)."""
        if not self._ground:
            return None
        return QColor(theme.C.glass.sunken.solid)

    def well_rect(self) -> QRectF:
        """El pozo: el widget menos los margenes de eje."""
        l, t, r, b = self._margins
        return QRectF(self.rect()).adjusted(l, t, -r, -b)

    # -- tema y tamano ------------------------------------------------------
    def on_theme(self) -> None:
        self.invalidate()
        self.update()

    def invalidate(self) -> None:
        """Gancho: el grafico tiene que regenerar lo que tenga cacheado."""

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.invalidate()

    # -- linea de escrutinio (apartado 7) -----------------------------------
    def scrutiny_value(self, x: float) -> tuple[str, str] | None:
        """(etiqueta, valor) bajo esa x logica, o ``None`` si no hay dato."""
        return None

    def _scrutiny_rect(self, x: float) -> QRect:
        """Columna danada por la linea y su chip. Nunca el widget entero."""
        pozo = self.well_rect()
        ancho = 132.0
        left = min(max(pozo.left(), x - 6.0), pozo.right() - ancho - 6.0)
        return QRect(int(left) - 2, int(pozo.top()) - 2,
                     int(ancho) + 12, int(pozo.height()) + 4)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if self.SCRUTINY:
            self._scrutiny_on = True

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._scrutiny_on:
            self._scrutiny_on = False
            self.update(self._scrutiny_damage)

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if not self.SCRUTINY:
            return
        pozo = self.well_rect()
        self._scrutiny_on = pozo.contains(event.position())
        if self._scrutiny_on:
            if not self._scrutiny.settled or self._scrutiny.value == 0.0:
                self._scrutiny.jump(event.position().x())
            self._scrutiny.set(event.position().x())
            self.animate()

    def paint_scrutiny(self, p: QPainter) -> None:
        """Linea de 1 px en acento y chip flotante E4 con el valor."""
        if not (self.SCRUTINY and self._scrutiny_on):
            return
        pozo = self.well_rect()
        x = min(max(pozo.left(), self._scrutiny.value), pozo.right())
        pen = QPen(_c(theme.C.color.accent, 0.75))
        pen.setWidthF(1.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawLine(QPointF(round(x) + 0.5, pozo.top()),
                   QPointF(round(x) + 0.5, pozo.bottom()))

        dato = self.scrutiny_value(x)
        if dato is None:
            return
        etiqueta, valor = dato
        fe, fv = tipo.font("axis"), tipo.font("caption")
        ancho = max(tipo.metrics("axis").horizontalAdvance(etiqueta),
                    tipo.metrics("caption").horizontalAdvance(valor)) + 20.0
        alto = 38.0
        left = x + 10.0
        if left + ancho > pozo.right():
            left = x - 10.0 - ancho
        chip = QRectF(left, pozo.top() + 6.0, ancho, alto)
        glass.paint_sheet(p, chip, "E4", R_XS + 4,
                          canvas_origin=self.mapTo(self.window(), QPoint(0, 0)))
        p.setFont(fe)
        p.setPen(QColor(theme.C.ink.tertiary))
        p.drawText(chip.adjusted(10, 5, -10, 0),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                   tipo.text("axis", etiqueta))
        p.setFont(fv)
        p.setPen(QColor(theme.C.ink.primary))
        p.drawText(chip.adjusted(10, 0, -10, -5),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
                   valor)

    def tick(self, dt: float) -> bool:
        antes = self._scrutiny.value
        self._scrutiny.step()
        if not self._scrutiny.settled:
            dano = self._scrutiny_rect(antes).united(
                self._scrutiny_rect(self._scrutiny.value))
            self._scrutiny_damage = dano
            self.update(dano)
            return True
        return False

    # -- pintado ------------------------------------------------------------
    def paint_chart(self, p: QPainter) -> None:
        """Gancho de la subclase. El suelo y el escrutinio ya estan puestos."""

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        suelo = self.ground_color()
        if suelo is not None:
            p.fillRect(event.rect(), suelo)
        self.paint_chart(p)
        self.paint_scrutiny(p)
        p.end()


# --------------------------------------------------------------------------- #
# trazas temporales: aqui es donde vive el blit desplazado
# --------------------------------------------------------------------------- #

class _Scrolling:
    """Fontaneria comun de las trazas con blit desplazado.

    Existe para que el estado del pozo se resuelva en **un** sitio. Las tres
    trazas repetian esta danza y la repetian mal: cuando el pozo habia que
    regenerarlo entero, la muestra que acababa de entrar se dibujaba dos veces,
    una en la regeneracion y otra en la columna nueva, y la traza salia con un
    escalon fantasma cada vez que se redimensionaba la ventana.

    ``_ensure()`` devuelve que ha pasado, y quien empuja una muestra actua en
    consecuencia:

    * ``"none"``  no hay pozo (widget sin geometria todavia);
    * ``"full"``  se ha regenerado entero, la muestra nueva **ya esta dentro**;
    * ``"ok"``    el pozo esta al dia, toca desplazarlo y pintar la columna.
    """

    def _init_scroll(self, step: float, transparent: bool) -> None:
        self._buf = ScrollBuffer(transparent=transparent)
        self._step = float(step)

    def invalidate(self) -> None:
        self._buf.invalidate()

    def _draw_all(self, p: QPainter) -> None:
        """Redibuja el pozo entero desde el anillo. Lo implementa la traza."""
        raise NotImplementedError

    def _ensure(self) -> str:
        pozo = self.well_rect()
        if pozo.isEmpty():
            return "none"
        nuevo = self._buf.configure(pozo.size().toSize(),
                                    self.devicePixelRatioF(), self._step)
        if not (nuevo or self._buf.dirty):
            return "ok"
        self._buf.fill(self.ground_color())
        pm = self._buf.pixmap
        if pm is None:
            return "none"
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._draw_all(p)
        p.end()
        return "full"

    def _capacity(self) -> int:
        """Muestras que caben en el pozo. Manda el paso real, no el nominal."""
        paso = self._buf.step if self._buf.valid else self._step
        return max(0, int(self.well_rect().width() / max(0.5, paso)) + 1)

    def _columns(self, n: int):
        """Las columnas de las ``n`` muestras visibles, de izquierda a derecha."""
        paso = self._buf.step
        ancho = self._buf.size.width()
        alto = float(self._buf.size.height())
        for i in range(n):
            derecha = ancho - (n - 1 - i) * paso
            yield i, QRectF(derecha - paso, 0.0, paso, alto)


class Trace(_Scrolling, ChartWidget):
    """Traza temporal de una serie, con blit desplazado.

    Guarda un anillo de las muestras que caben en el pozo porque lo necesita
    para dos cosas que no se pueden hacer con el pixmap: regenerar entero al
    cambiar de tema o de tamano, y contestar a la linea de escrutinio.

    El autoescalado no se hace por muestra: reescalar obliga a redibujar el pozo
    entero, asi que el techo solo sube cuando una muestra lo rebasa y luego baja
    con histeresis (no baja hasta que el pico cae por debajo del 55 % durante
    todo el pozo). Sin la histeresis la traza respira sola y marea.
    """

    SCRUTINY = True

    def __init__(self, parent: QWidget | None = None, *, ground: bool = True,
                 step: float = 2.0, color: str | None = None,
                 fill: bool = True, width: float = 1.5,
                 lo: float = 0.0, hi: float = 100.0, autoscale: bool = True,
                 unit: str = "", grid: bool = True,
                 margins: tuple[float, ...] = (0, 6, 0, 0)) -> None:
        super().__init__(parent, ground=ground, margins=margins)
        self._init_scroll(step, transparent=not ground)
        self._color = color
        self._fill = bool(fill)
        self._width = float(width)
        self._lo, self._hi = float(lo), float(hi)
        self._auto = bool(autoscale)
        self._unit = unit
        self._grid = bool(grid)
        self._n = 0
        self._ring = np.full(1024, np.nan, dtype=np.float32)
        self._head: float | None = None

    # -- datos --------------------------------------------------------------
    def color(self) -> str:
        return self._color or theme.C.color.accent

    def set_range(self, lo: float, hi: float) -> None:
        if abs(lo - self._lo) < 1e-9 and abs(hi - self._hi) < 1e-9:
            return
        self._lo, self._hi = float(lo), float(hi)
        self.invalidate()
        self.update()

    def push(self, value: float) -> None:
        """Una muestra nueva. Esto es todo lo que cuesta un fotograma de datos."""
        cap = self._capacity()
        if cap <= 0:
            return
        if self._n >= self._ring.size:
            self._ring = np.roll(self._ring, -self._ring.size // 2)
            self._n = self._ring.size // 2
        self._ring[self._n] = float(value)
        self._n += 1

        if self._auto and self._rescale():
            self.invalidate()
        estado = self._ensure()
        if estado == "none":
            return
        if estado == "full":
            # el pozo se ha redibujado entero y la muestra nueva ya esta dentro
            self.update()
            return
        col = self._buf.advance()
        p = QPainter(self._buf.pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._buf.clear_column(p, col, self.ground_color())
        self._draw_column(p, col, self._head, float(value))
        p.end()
        self._head = float(value)
        # la columna mas el halo del punto de cabeza: 14 px de ancho danado
        # frente a los 420 del widget entero
        pozo = self.well_rect()
        x0 = int(pozo.left() + col.left() - 1)
        self.update(QRect(x0, int(pozo.top()) - 1,
                          int(col.width() + HEAD_HALO + 2),
                          int(pozo.height()) + 2))

    def clear(self) -> None:
        self._n = 0
        self._head = None
        self.invalidate()
        self.update()

    # -- escala -------------------------------------------------------------
    def _visible(self) -> np.ndarray:
        cap = self._capacity()
        return self._ring[max(0, self._n - cap):self._n]

    def _rescale(self) -> bool:
        v = self._visible()
        if v.size == 0:
            return False
        pico = float(np.nanmax(v))
        if not math.isfinite(pico):
            return False
        if pico > self._hi:
            self._hi = ceil_nice(pico)
            return True
        # solo baja cuando todo el pozo ya cabe holgado: si no, la traza respira
        # sola y marea, que es peor que un eje un poco grande
        if pico < self._hi * 0.45 and v.size >= self._capacity() - 1:
            nuevo = ceil_nice(pico, 1.6)
            if 0.0 < nuevo < self._hi:
                self._hi = nuevo
                return True
        return False

    # -- pozo ---------------------------------------------------------------
    def _draw_all(self, p: QPainter) -> None:
        """Redibuja el pozo entero. Solo al cambiar tema, tamano o escala."""
        v = self._visible()
        previo: float | None = None
        for i, col in self._columns(v.size):
            self._draw_column(p, col, previo, float(v[i]))
            previo = float(v[i])
        self._head = previo

    def _y(self, value: float, h: float) -> float:
        span = max(1e-6, self._hi - self._lo)
        k = (value - self._lo) / span
        return h - max(0.0, min(1.0, k)) * h

    def _draw_column(self, p: QPainter, col: QRectF,
                     previo: float | None, valor: float) -> None:
        """La columna nueva: el trozo de linea y su relleno. Nada mas."""
        h = float(self._buf.size.height())
        y1 = self._y(valor, h)
        y0 = self._y(previo if previo is not None else valor, h)
        color = self.color()
        if self._fill:
            path = QPainterPath()
            path.moveTo(col.left(), y0)
            path.lineTo(col.right(), y1)
            path.lineTo(col.right(), h)
            path.lineTo(col.left(), h)
            path.closeSubpath()
            p.fillPath(path, area_gradient(QRectF(0, 0, 1, h), color))
        pen = QPen(_c(color, 1.0))
        pen.setWidthF(self._width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(col.left(), y0), QPointF(col.right(), y1))

    # -- escrutinio ---------------------------------------------------------
    def scrutiny_value(self, x: float) -> tuple[str, str] | None:
        v = self._visible()
        if v.size == 0:
            return None
        pozo = self.well_rect()
        paso = self._buf.step if self._buf.valid else self._step
        idx = v.size - 1 - int(round((pozo.right() - x) / max(0.5, paso)))
        if not 0 <= idx < v.size:
            return None
        return ("hace " + num((v.size - 1 - idx) * 0.25, 1) + " s",
                num(float(v[idx]), 1) + self._unit)

    # -- pintado ------------------------------------------------------------
    def paint_chart(self, p: QPainter) -> None:
        pozo = self.well_rect()
        if pozo.isEmpty():
            return
        if self._grid:
            draw_grid(p, pozo, self._lo, self._hi, unit=self._unit)
        if self._ensure() == "none":
            return
        pm = self._buf.pixmap
        if pm is not None:
            p.drawPixmap(pozo.topLeft(), pm)
        if self._head is not None:
            # el halo del punto de cabeza se pinta aqui y no en el pozo: si
            # entrase en el pixmap se desplazaria con el y la traza dejaria un
            # rastro de halos viejos
            centro = QPointF(pozo.right(),
                             pozo.top() + self._y(self._head, pozo.height()))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(self.color(), 0.16))
            p.drawEllipse(centro, 7.0, 7.0)
            p.setBrush(_c(self.color(), 1.0))
            p.drawEllipse(centro, 2.4, 2.4)


class StackedTrace(_Scrolling, ChartWidget):
    """Traza temporal apilada de N series. El motor del presupuesto de retardo.

    Se apila por columnas y no con ``QPainterPath`` a proposito: una columna
    apilada son tres trapecios, se dibuja en el pozo desplazado y sale con los
    cantos entre bandas limpios. Un area apilada con curvas cubicas no se puede
    desplazar, porque una cubica necesita a sus vecinos, y habria que regenerar
    el pozo entero por muestra.
    """

    SCRUTINY = True

    def __init__(self, parent: QWidget | None = None, *, ground: bool = True,
                 step: float = 2.0, colors: Sequence[str] | None = None,
                 labels: Sequence[str] = (), hi: float = 120.0,
                 margins: tuple[float, ...] = (0, 0, 0, 0)) -> None:
        super().__init__(parent, ground=ground, margins=margins)
        self._init_scroll(step, transparent=not ground)
        self._colors = list(colors or [])
        self._labels = list(labels)
        self._hi = float(hi)
        self._series = max(1, len(self._colors))
        self._ring = np.zeros((1024, self._series), dtype=np.float32)
        self._n = 0
        self._prev: np.ndarray | None = None
        self._rule: float | None = None

    def set_rule(self, value: float | None) -> None:
        """Regla de objetivo (los 100 ms del apartado 8.5.3)."""
        self._rule = value
        self.update()

    def push(self, values: Sequence[float]) -> None:
        v = np.asarray(values, dtype=np.float32)[:self._series]
        if v.size < self._series:
            v = np.pad(v, (0, self._series - v.size))
        if self._n >= self._ring.shape[0]:
            mitad = self._ring.shape[0] // 2
            self._ring[:mitad] = self._ring[mitad:]
            self._n = mitad
        self._ring[self._n] = v
        self._n += 1

        if float(v.sum()) > self._hi:
            self._hi = ceil_nice(float(v.sum()), 1.2)
            self.invalidate()
        estado = self._ensure()
        if estado == "none":
            return
        if estado == "full":
            self.update()
            return
        col = self._buf.advance()
        p = QPainter(self._buf.pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._buf.clear_column(p, col, self.ground_color())
        self._draw_column(p, col, self._prev, v)
        p.end()
        self._prev = v.copy()
        pozo = self.well_rect()
        self.update(QRect(int(pozo.left() + col.left()) - 1, int(pozo.top()) - 1,
                          int(col.width()) + 3, int(pozo.height()) + 2))

    # -- agregados que la tarjeta imprime a la derecha -----------------------
    def means(self) -> np.ndarray:
        v = self._visible()
        if v.shape[0] == 0:
            return np.zeros(self._series)
        return v.mean(axis=0)

    def _visible(self) -> np.ndarray:
        cap = self._capacity()
        return self._ring[max(0, self._n - cap):self._n]

    def _draw_all(self, p: QPainter) -> None:
        v = self._visible()
        previo: np.ndarray | None = None
        for i, col in self._columns(v.shape[0]):
            self._draw_column(p, col, previo, v[i])
            previo = v[i]
        self._prev = None if previo is None else previo.copy()

    def _draw_column(self, p: QPainter, col: QRectF,
                     previo: np.ndarray | None, valores: np.ndarray) -> None:
        h = float(self._buf.size.height())
        anterior = valores if previo is None else previo
        base0 = base1 = h
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(self._series):
            k = h / max(1e-6, self._hi)
            top0 = base0 - float(anterior[i]) * k
            top1 = base1 - float(valores[i]) * k
            path = QPainterPath()
            path.moveTo(col.left(), base0)
            path.lineTo(col.left(), top0)
            path.lineTo(col.right(), top1)
            path.lineTo(col.right(), base1)
            path.closeSubpath()
            color = self._colors[i] if i < len(self._colors) else theme.C.accent
            alfa = area_alpha() if i < self._series - 1 else area_alpha() * 0.45
            p.fillPath(path, _c(color, alfa))
            base0, base1 = top0, top1

    def scrutiny_value(self, x: float) -> tuple[str, str] | None:
        v = self._visible()
        if v.shape[0] == 0:
            return None
        pozo = self.well_rect()
        paso = self._buf.step if self._buf.valid else self._step
        idx = v.shape[0] - 1 - int(round((pozo.right() - x) / max(0.5, paso)))
        if not 0 <= idx < v.shape[0]:
            return None
        return ("total", num(float(v[idx].sum()), 0) + " ms")

    def paint_chart(self, p: QPainter) -> None:
        pozo = self.well_rect()
        if pozo.isEmpty() or self._ensure() == "none":
            return
        pm = self._buf.pixmap
        if pm is not None:
            p.drawPixmap(pozo.topLeft(), pm)
        if self._rule is not None and self._rule < self._hi:
            y = pozo.bottom() - self._rule / self._hi * pozo.height()
            pen = QPen(_c(theme.C.ink.tertiary, 0.75))
            pen.setWidthF(1.0)
            pen.setCosmetic(True)
            pen.setDashPattern([4.0, 4.0])
            p.setPen(pen)
            p.drawLine(QPointF(pozo.left(), round(y) + 0.5),
                       QPointF(pozo.right(), round(y) + 0.5))


class Heartbeat(_Scrolling, ChartWidget):
    """Tira de latido: un tick vertical por fotograma, coloreado por tramo.

    Paso 1 px, 900 ticks (apartado 8.5.8). Es el grafico que mas se beneficia
    del blit: a 60 Hz se repinta **una** columna de 1 px por muestra.
    """

    #: Tramos del apartado 8.5.8, en ms.
    FAST = 20.0
    SLOW = 33.0

    def __init__(self, parent: QWidget | None = None, *, ground: bool = True,
                 margins: tuple[float, ...] = (0, 0, 0, 0)) -> None:
        super().__init__(parent, ground=ground, margins=margins)
        self._init_scroll(1.0, transparent=not ground)
        self._ring = np.zeros(1024, dtype=np.float32)
        self._n = 0
        self._hi = 50.0

    def push(self, dt_ms: float) -> None:
        if self._n >= self._ring.size:
            mitad = self._ring.size // 2
            self._ring[:mitad] = self._ring[mitad:]
            self._n = mitad
        self._ring[self._n] = float(dt_ms)
        self._n += 1
        estado = self._ensure()
        if estado == "none":
            return
        if estado == "full":
            self.update()
            return
        col = self._buf.advance()
        p = QPainter(self._buf.pixmap)
        self._buf.clear_column(p, col, self.ground_color())
        self._draw_tick(p, col, float(dt_ms))
        p.end()
        pozo = self.well_rect()
        self.update(QRect(int(pozo.left() + col.left()) - 1, int(pozo.top()),
                          int(col.width()) + 3, int(pozo.height())))

    def summary(self) -> str:
        """La frase del apartado 8.5.8, calculada, no inventada."""
        v = self._ring[max(0, self._n - 900):self._n]
        if v.size == 0:
            return "sin fotogramas todavía"
        rapidos = float((v <= self.FAST).mean()) * 100.0
        saltos = int((v > self.SLOW).sum())
        return (f"{num(rapidos, 1)} % de los fotogramas por debajo de "
                f"{num(self.FAST, 0)} ms · {saltos} saltos en {v.size} muestras")

    def _draw_all(self, p: QPainter) -> None:
        v = self._ring[max(0, self._n - self._capacity()):self._n]
        for i, col in self._columns(v.size):
            self._draw_tick(p, col, float(v[i]))

    def _tick_color(self, dt_ms: float) -> str:
        if dt_ms <= self.FAST:
            return theme.C.color.ok
        if dt_ms <= self.SLOW:
            return theme.C.color.warn
        return theme.C.color.danger

    def _draw_tick(self, p: QPainter, col: QRectF, dt_ms: float) -> None:
        h = float(self._buf.size.height())
        k = max(0.06, min(1.0, dt_ms / self._hi))
        alto = h * k
        p.fillRect(QRectF(col.left(), h - alto, max(1.0, col.width() - 0.4), alto),
                   _c(self._tick_color(dt_ms), 0.92))

    def paint_chart(self, p: QPainter) -> None:
        pozo = self.well_rect()
        if pozo.isEmpty() or self._ensure() == "none":
            return
        pm = self._buf.pixmap
        if pm is not None:
            p.drawPixmap(pozo.topLeft(), pm)


# --------------------------------------------------------------------------- #
# graficos que no se desplazan: se regeneran cuando entra una muestra
# --------------------------------------------------------------------------- #

class AreaChart(ChartWidget):
    """Areas superpuestas con curva cubica y una linea sobre el eje derecho.

    Es la LINEA DE TIEMPO del apartado 8.5.1. No usa blit desplazado y es la
    unica traza temporal que no lo hace: la curva cubica necesita a sus vecinos
    a los dos lados, asi que la columna nueva cambiaria el trazo de la anterior.
    A cambio cumple la otra regla del apartado 7 al pie de la letra: el
    ``QPainterPath`` se cachea en un pixmap y **solo** se regenera cuando entra
    una muestra, jamas a 60 Hz.
    """

    SCRUTINY = True

    def __init__(self, parent: QWidget | None = None, *, ground: bool = True,
                 colors: Sequence[str] | None = None,
                 line_color: str | None = None, unit: str = "",
                 margins: tuple[float, ...] = (0, 8, 0, 0)) -> None:
        super().__init__(parent, ground=ground, margins=margins)
        self._colors = list(colors or [])
        self._line_color = line_color
        self._unit = unit
        self._areas: list[np.ndarray] = []
        self._line: np.ndarray | None = None
        self._hi = 72.0
        self._hi_line = 100.0
        self._cache: QPixmap | None = None
        self._dirty = True

    def set_series(self, areas: Sequence[Sequence[float]],
                   line: Sequence[float] | None = None) -> None:
        self._areas = [np.asarray(a, dtype=np.float32) for a in areas]
        self._line = None if line is None else np.asarray(line, dtype=np.float32)
        picos = [float(a.max()) for a in self._areas if a.size]
        self._hi = max(72.0, max(picos) * 1.12 if picos else 72.0)
        if self._line is not None and self._line.size:
            self._hi_line = max(1.0, float(self._line.max()) * 1.25)
        self._dirty = True
        self.update()

    def invalidate(self) -> None:
        self._dirty = True
        self._cache = None

    def _path(self, serie: np.ndarray, pozo: QRectF, hi: float,
              cerrar: bool) -> QPainterPath:
        """Cubica de Catmull-Rom convertida a Bezier. Suave y sin sobretiros."""
        n = serie.size
        path = QPainterPath()
        if n == 0:
            return path
        dx = pozo.width() / max(1, n - 1)

        def punto(i: int) -> QPointF:
            i = max(0, min(n - 1, i))
            y = pozo.bottom() - min(1.0, float(serie[i]) / hi) * pozo.height()
            return QPointF(pozo.left() + i * dx, y)

        path.moveTo(punto(0))
        for i in range(n - 1):
            p0, p1, p2, p3 = punto(i - 1), punto(i), punto(i + 1), punto(i + 2)
            c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0,
                         p1.y() + (p2.y() - p0.y()) / 6.0)
            c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0,
                         p2.y() - (p3.y() - p1.y()) / 6.0)
            path.cubicTo(c1, c2, p2)
        if cerrar:
            path.lineTo(pozo.right(), pozo.bottom())
            path.lineTo(pozo.left(), pozo.bottom())
            path.closeSubpath()
        return path

    def _regenerate(self) -> None:
        pozo = self.well_rect()
        if pozo.isEmpty():
            return
        dpr = max(1.0, self.devicePixelRatioF())
        pm = QPixmap(int(pozo.width() * dpr), int(pozo.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        r = QRectF(0, 0, pozo.width(), pozo.height())
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for i, serie in enumerate(self._areas):
            color = self._colors[i] if i < len(self._colors) else theme.C.accent
            p.fillPath(self._path(serie, r, self._hi, True),
                       area_gradient(r, color))
            pen = QPen(_c(color, 1.0))
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(self._path(serie, r, self._hi, False))
        if self._line is not None and self._line.size:
            pen = QPen(_c(self._line_color or theme.C.color.warn, 0.95))
            pen.setWidthF(1.5)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(self._path(self._line, r, self._hi_line, False))
        p.end()
        self._cache = pm
        self._dirty = False

    def scrutiny_value(self, x: float) -> tuple[str, str] | None:
        if not self._areas or self._areas[0].size == 0:
            return None
        pozo = self.well_rect()
        serie = self._areas[0]
        k = (x - pozo.left()) / max(1.0, pozo.width())
        i = max(0, min(serie.size - 1, int(round(k * (serie.size - 1)))))
        return ("motor", num(float(serie[i]), 1) + self._unit)

    def paint_chart(self, p: QPainter) -> None:
        pozo = self.well_rect()
        if pozo.isEmpty():
            return
        draw_grid(p, pozo, 0.0, self._hi, unit=self._unit)
        if self._dirty or self._cache is None:
            self._regenerate()
        if self._cache is not None:
            p.drawPixmap(pozo.topLeft(), self._cache)


class Histogram(ChartWidget):
    """Barras con tope redondeado, alturas suavizadas y marcas de percentil.

    Las alturas persiguen su objetivo con ``Smooth(tau)`` y por eso el widget se
    apunta al latido **mientras no esten asentadas**, y solo mientras. Un
    histograma quieto no despierta la CPU.
    """

    BEAT_HZ = motion.HZ_FULL

    def __init__(self, parent: QWidget | None = None, *, ground: bool = True,
                 color: str | None = None, tau: float = motion.TAU_HISTOGRAM,
                 unit: str = "", margins: tuple[float, ...] = (0, 4, 0, 14)
                 ) -> None:
        super().__init__(parent, ground=ground, margins=margins)
        self._color = color
        self._tau = float(tau)
        self._unit = unit
        self._counts = np.zeros(0, dtype=np.float32)
        self._smooth: list[motion.Smooth] = []
        self._lo, self._hi = 0.0, 1.0
        self._marks: list[tuple[float, str]] = []
        self._bands: list[tuple[float, float, str]] = []

    def set_bins(self, counts: Sequence[float], lo: float, hi: float) -> None:
        c = np.asarray(counts, dtype=np.float32)
        if c.size != len(self._smooth):
            self._smooth = [motion.Smooth(0.0, self._tau) for _ in range(c.size)]
        self._counts = c
        self._lo, self._hi = float(lo), float(hi)
        pico = max(1.0, float(c.max()) if c.size else 1.0)
        for s, v in zip(self._smooth, c):
            s.set(float(v) / pico)
        self.animate()
        self.update()

    def set_marks(self, marks: Sequence[tuple[float, str]]) -> None:
        """Marcas verticales con etiqueta: p50, p95, p99, o los umbrales."""
        self._marks = list(marks)
        self.update()

    def set_bands(self, bands: Sequence[tuple[float, float, str]]) -> None:
        """Bandas sombreadas, como la histeresis de pinch al 8 %."""
        self._bands = list(bands)
        self.update()

    def tick(self, dt: float) -> bool:
        vivo = super().tick(dt)
        for s in self._smooth:
            s.step()
        if any(not s.settled for s in self._smooth):
            self.update()
            return True
        return vivo

    def color(self) -> str:
        return self._color or theme.C.color.accent

    def paint_chart(self, p: QPainter) -> None:
        pozo = self.well_rect()
        if pozo.isEmpty() or not self._smooth:
            return
        span = max(1e-6, self._hi - self._lo)

        for x0, x1, color in self._bands:
            a = pozo.left() + (x0 - self._lo) / span * pozo.width()
            b = pozo.left() + (x1 - self._lo) / span * pozo.width()
            p.fillRect(QRectF(a, pozo.top(), b - a, pozo.height()),
                       _c(color, 0.08))

        n = len(self._smooth)
        ancho = pozo.width() / n
        barra = max(1.5, ancho - 1.6)
        color = self.color()
        p.setPen(Qt.PenStyle.NoPen)
        for i, s in enumerate(self._smooth):
            alto = max(0.0, s.value) * pozo.height()
            if alto < 0.4:
                continue
            r = QRectF(pozo.left() + i * ancho + (ancho - barra) / 2.0,
                       pozo.bottom() - alto, barra, alto)
            p.fillPath(_rounded_top(r, barra / 2.0), _c(color, area_alpha()))

        p.setFont(tipo.font("axis"))
        for valor, etiqueta in self._marks:
            x = pozo.left() + (valor - self._lo) / span * pozo.width()
            pen = QPen(_c(theme.C.ink.secondary, 0.85))
            pen.setWidthF(1.0)
            pen.setCosmetic(True)
            pen.setDashPattern([3.0, 3.0])
            p.setPen(pen)
            p.drawLine(QPointF(round(x) + 0.5, pozo.top()),
                       QPointF(round(x) + 0.5, pozo.bottom()))
            p.setPen(QColor(theme.C.ink.secondary))
            ancho_txt = tipo.metrics("axis").horizontalAdvance(etiqueta) + 6
            izq = min(x + 3, pozo.right() - ancho_txt)
            p.drawText(QRectF(izq, pozo.bottom() + 1, ancho_txt, 12),
                       int(Qt.AlignmentFlag.AlignLeft), etiqueta)


class Donut(ChartWidget):
    """Reloj de modos: arcos gruesos con hueco, y el dominante en el centro."""

    THICKNESS = 14.0
    RADIUS = 62.0
    GAP_PX = 3.0

    def __init__(self, parent: QWidget | None = None, *, ground: bool = True
                 ) -> None:
        super().__init__(parent, ground=ground)
        self._slices: list[tuple[str, float, str]] = []      # nombre, peso, color
        self._smooth: list[motion.Smooth] = []

    def set_slices(self, slices: Sequence[tuple[str, float, str]]) -> None:
        total = sum(max(0.0, s[1]) for s in slices) or 1.0
        if len(slices) != len(self._smooth):
            self._smooth = [motion.Smooth(0.0, motion.TAU_DONUT)
                            for _ in range(len(slices))]
        self._slices = list(slices)
        for s, (_, peso, _c2) in zip(self._smooth, slices):
            s.set(max(0.0, peso) / total)
        self.animate()
        self.update()

    def tick(self, dt: float) -> bool:
        for s in self._smooth:
            s.step()
        if any(not s.settled for s in self._smooth):
            self.update()
            return True
        return False

    def paint_chart(self, p: QPainter) -> None:
        r = self.well_rect()
        if r.isEmpty() or not self._slices:
            return
        radio = min(self.RADIUS, min(r.width(), r.height()) / 2.0 - 2.0)
        centro = r.center()
        caja = QRectF(centro.x() - radio + self.THICKNESS / 2.0,
                      centro.y() - radio + self.THICKNESS / 2.0,
                      (radio - self.THICKNESS / 2.0) * 2.0,
                      (radio - self.THICKNESS / 2.0) * 2.0)
        hueco = math.degrees(self.GAP_PX / max(1.0, radio))
        angulo = 90.0
        for (nombre, _peso, color), s in zip(self._slices, self._smooth):
            barrido = s.value * 360.0
            if barrido <= hueco:
                continue
            pen = QPen(_c(color, 0.95))
            pen.setWidthF(self.THICKNESS)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(caja, int((angulo - barrido + hueco / 2) * 16),
                      int((barrido - hueco) * 16))
            angulo -= barrido

        dom = max(range(len(self._slices)),
                  key=lambda i: self._smooth[i].value)
        nombre, _p, color = self._slices[dom]
        p.setFont(tipo.font("metric"))
        p.setPen(QColor(theme.C.ink.primary))
        p.drawText(QRectF(centro.x() - radio, centro.y() - 26, radio * 2, 34),
                   int(Qt.AlignmentFlag.AlignCenter),
                   num(self._smooth[dom].value * 100.0, 0) + " %")
        p.setFont(tipo.font("overline"))
        p.setPen(QColor(color))
        p.drawText(QRectF(centro.x() - radio, centro.y() + 10, radio * 2, 16),
                   int(Qt.AlignmentFlag.AlignCenter),
                   tipo.text("overline", nombre))


class Scatter(ChartWidget):
    """Nube de puntos de 4 px sobre un eje horizontal, con reglas verticales.

    El desplazamiento vertical de cada punto es **determinista** (sale del
    indice, no de un aleatorio): con un aleatorio la nube bailaba en cada
    repintado y parecia que llegaban datos nuevos cuando no llegaba ninguno.
    """

    DOT = 4.0

    def __init__(self, parent: QWidget | None = None, *, ground: bool = True,
                 lo: float = 0.0, hi: float = 1.0,
                 margins: tuple[float, ...] = (0, 2, 0, 12)) -> None:
        super().__init__(parent, ground=ground, margins=margins)
        self._x = np.zeros(0, dtype=np.float32)
        self._cat = np.zeros(0, dtype=np.int8)
        self._colors: list[str] = []
        self._lo, self._hi = float(lo), float(hi)
        self._rules: list[tuple[float, str]] = []

    def set_points(self, values: Sequence[float], categories: Sequence[int],
                   colors: Sequence[str]) -> None:
        self._x = np.asarray(values, dtype=np.float32)
        self._cat = np.asarray(categories, dtype=np.int8)
        self._colors = list(colors)
        self.update()

    def set_rules(self, rules: Sequence[tuple[float, str]]) -> None:
        self._rules = list(rules)
        self.update()

    def paint_chart(self, p: QPainter) -> None:
        pozo = self.well_rect()
        if pozo.isEmpty():
            return
        span = max(1e-6, self._hi - self._lo)

        p.setFont(tipo.font("axis"))
        for valor, etiqueta in self._rules:
            x = pozo.left() + (valor - self._lo) / span * pozo.width()
            pen = QPen(_c(theme.C.ink.secondary, 0.8))
            pen.setWidthF(1.0)
            pen.setCosmetic(True)
            pen.setDashPattern([3.0, 3.0])
            p.setPen(pen)
            p.drawLine(QPointF(round(x) + 0.5, pozo.top()),
                       QPointF(round(x) + 0.5, pozo.bottom()))
            p.setPen(QColor(theme.C.ink.tertiary))
            ancho = tipo.metrics("axis").horizontalAdvance(etiqueta) + 6
            p.drawText(QRectF(min(x + 3, pozo.right() - ancho),
                              pozo.bottom() + 1, ancho, 12),
                       int(Qt.AlignmentFlag.AlignLeft), etiqueta)

        p.setPen(Qt.PenStyle.NoPen)
        alto = pozo.height() - self.DOT
        for i in range(self._x.size):
            k = (float(self._x[i]) - self._lo) / span
            if not 0.0 <= k <= 1.0:
                continue
            # dispersion vertical estable: sucesion de Van der Corput base 2,
            # que reparte mejor que un modulo y no repite bandas
            j, frac, base = i + 1, 0.0, 0.5
            while j:
                frac += (j & 1) * base
                j >>= 1
                base *= 0.5
            y = pozo.top() + self.DOT / 2.0 + frac * alto
            cat = int(self._cat[i]) if i < self._cat.size else 0
            color = self._colors[cat] if cat < len(self._colors) else theme.C.accent
            p.setBrush(_c(color, 0.88))
            p.drawEllipse(QPointF(pozo.left() + k * pozo.width(), y),
                          self.DOT / 2.0, self.DOT / 2.0)


class Strip(ChartWidget):
    """Barra apilada horizontal de radio completo. Reparto de un total."""

    HEIGHT = 10.0

    def __init__(self, parent: QWidget | None = None, *, ground: bool = False
                 ) -> None:
        super().__init__(parent, ground=ground)
        self._parts: list[tuple[str, float, str]] = []

    def set_parts(self, parts: Sequence[tuple[str, float, str]]) -> None:
        self._parts = list(parts)
        self.update()

    def paint_chart(self, p: QPainter) -> None:
        r = self.well_rect()
        total = sum(max(0.0, v) for _, v, _c2 in self._parts)
        if r.isEmpty() or total <= 0.0:
            return
        alto = min(self.HEIGHT, r.height())
        caja = QRectF(r.left(), r.center().y() - alto / 2.0, r.width(), alto)
        p.save()
        p.setClipPath(glass.rounded_path(caja, alto / 2.0))
        x = caja.left()
        for _nombre, valor, color in self._parts:
            w = caja.width() * max(0.0, valor) / total
            p.fillRect(QRectF(x, caja.top(), w + 0.5, alto), _c(color, 0.90))
            x += w
        p.restore()


class Sparkline(ChartWidget):
    """Micrografico de 60x28 sin ejes. Va dentro de una ficha, no sola."""

    def __init__(self, parent: QWidget | None = None, *, ground: bool = False,
                 color: str | None = None) -> None:
        super().__init__(parent, ground=ground, margins=(1, 3, 1, 3))
        self._color = color
        self._values = np.zeros(0, dtype=np.float32)
        self.setFixedSize(60, 28)

    def set_values(self, values: Sequence[float]) -> None:
        self._values = np.asarray(values, dtype=np.float32)
        self.update()

    def paint_chart(self, p: QPainter) -> None:
        r = self.well_rect()
        v = self._values
        if r.isEmpty() or v.size < 2:
            return
        lo, hi = float(v.min()), float(v.max())
        span = max(1e-6, hi - lo)
        dx = r.width() / (v.size - 1)
        path = QPainterPath()
        for i, valor in enumerate(v):
            y = r.bottom() - (float(valor) - lo) / span * r.height()
            punto = QPointF(r.left() + i * dx, y)
            path.moveTo(punto) if i == 0 else path.lineTo(punto)
        color = self._color or theme.C.color.accent
        pen = QPen(_c(color, 0.95))
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(color, 1.0))
        p.drawEllipse(path.currentPosition(), 1.8, 1.8)


# --------------------------------------------------------------------------- #
# calculo de las tarjetas de analisis (apartado 6.3 y 8.5)
# --------------------------------------------------------------------------- #

class Outcome(IntEnum):
    """Desenlace de un cierre de pinch. El orden fija el color y la leyenda."""

    CLICK = 0
    DRAG = 1
    SCROLL = 2
    ABORT = 3


def outcome_colors() -> list[str]:
    t = theme.C.tokens
    return [theme.C.color.ok,
            t.mode_color(Mode.DRAGGING),
            t.mode_color(Mode.SCROLLING),
            theme.C.ink.quiet]


OUTCOME_NAMES = ("clic", "arrastre", "scroll", "abortado")


def tremor(points: np.ndarray) -> float:
    """Temblor del puntero: media de ``|p[t] - 2*p[t-1] + p[t-2]|`` en px.

    Es la segunda diferencia, o sea el residuo de alta frecuencia: mide lo que
    tiembla la mano y **no** lo que se mueve el puntero. Una definicion mas
    comoda (la desviacion tipica de la posicion, por ejemplo) daria un numero
    enorme por mover el raton de un lado a otro de la pantalla, que es
    justamente lo que no queremos medir. Apartado 6.3.
    """
    p = np.asarray(points, dtype=np.float64)
    if p.ndim != 2 or p.shape[0] < 3:
        return 0.0
    p = p[-TREMOR_WINDOW:]
    d2 = p[2:] - 2.0 * p[1:-1] + p[:-2]
    return float(np.hypot(d2[:, 0], d2[:, 1]).mean())


#: Veredictos del apartado 8.5.7. Una palabra, en px de temblor.
TREMOR_VERDICTS = ((0.8, "FIRME"), (1.8, "ESTABLE"), (3.2, "INQUIETO"))


def tremor_verdict(value: float) -> tuple[str, str]:
    """(palabra, color) del temblor. El color significa (principio 3)."""
    colores = (theme.C.color.ok, theme.C.color.ok, theme.C.color.warn)
    for i, (corte, palabra) in enumerate(TREMOR_VERDICTS):
        if value < corte:
            return palabra, colores[i]
    return "TEMBLOROSO", theme.C.color.danger


@dataclass(frozen=True)
class Advice:
    """Una frase calculada y, si procede, el valor que aplicaria un boton."""

    text: str
    value: float | None = None


def closure_advice(minima: Sequence[float], outcomes: Sequence[int],
                   pinch_on: float) -> Advice:
    """La frase del apartado 8.5.6, calculada sobre los cierres de verdad.

    La regla es la de la especificacion: si la mediana del minimo alcanzado por
    los cierres **abortados** cae entre el umbral y el umbral + 0.04, es que el
    dedo se queda a las puertas y lo que sobra es umbral, no pulso. Fuera de esa
    ventana no se sugiere nada: se cuenta lo que hay. Inventar una sugerencia
    cuando los datos no la sostienen es peor que no dar ninguna.
    """
    m = np.asarray(minima, dtype=np.float64)
    o = np.asarray(outcomes, dtype=np.int16)
    if m.size == 0:
        return Advice("Sin cierres registrados todavía.")
    abortados = m[o == int(Outcome.ABORT)] if o.size == m.size else m[:0]
    if abortados.size >= 4:
        mediana = float(np.median(abortados))
        if pinch_on <= mediana <= pinch_on + 0.04:
            nuevo = round(mediana + 0.01, 2)
            return Advice(
                f"Tu pinch se queda en {num(mediana, 2)} de media y el umbral "
                f"está en {num(pinch_on, 2)}: sube el cierre a {num(nuevo, 2)}",
                nuevo)
    fallidos = int((o == int(Outcome.ABORT)).sum()) if o.size == m.size else 0
    return Advice(
        f"{m.size} cierres · {fallidos} abortados · mínimo mediano "
        f"{num(float(np.median(m)), 2)}. El umbral no te está estorbando.")


# --------------------------------------------------------------------------- #
# las tres tarjetas de analisis (apartado 8.5, fichas 3, 6 y 7)
# --------------------------------------------------------------------------- #

class _AnalysisCard(Sheet):
    """Base de las tres tarjetas: titulo, nota de calculo y hueco de grafico.

    Las tarjetas son laminas E2 y pintan el grafico **sobre su propia
    superficie**, no dentro de un recuadro: el principio 2 dice que el grafico
    *es* el fondo de la lamina. El velo del apartado 4.3 se pone a mano donde el
    texto cae encima, porque ``paint_sheet`` solo lo pone cuando la lamina lleva
    sangrado y estas no lo llevan: el grafico va a opacidad plena porque aqui se
    lee, no decora.

    La nota de 11 px con la formula no es un adorno: el principio 4 obliga a que
    toda metrica derivada diga como se calcula. Es la diferencia entre un panel
    que informa y uno que impresiona.
    """

    #: Alto de la ficha del apartado 8.5: 2 columnas x 190 px.
    CARD_SIZE = QSize(272, 190)

    TITLE = ""
    FOOTNOTE = ""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, elevation="E2", radius=R_LG,
                         padding=SHEET_PADDING, interactive=True)

    def sizeHint(self) -> QSize:      # noqa: N802 (API de Qt)
        """``CARD_SIZE`` es el tamano del **vidrio**; el widget suma su reserva.

        Quien coloca la tarjeta a mano usa ``place()``, que hace la misma cuenta
        al reves. Confundir las dos medidas deja la ficha descuadrada respecto
        de sus vecinas por unos 30 px, que es justo lo bastante para que parezca
        un fallo de maquetacion y no de sombra.
        """
        m = self.reserve()
        return QSize(int(self.CARD_SIZE.width() + m.left() + m.right()),
                     int(self.CARD_SIZE.height() + m.top() + m.bottom()))

    def title_rect(self, content: QRectF) -> QRectF:
        return QRectF(content.left(), content.top(), content.width(), 14.0)

    def footnote_rect(self, content: QRectF) -> QRectF:
        return QRectF(content.left(), content.bottom() - 13.0,
                      content.width(), 13.0)

    def paint_header(self, p: QPainter, content: QRectF) -> None:
        p.setFont(tipo.font("overline"))
        p.setPen(QColor(theme.C.ink.tertiary))
        p.drawText(self.title_rect(content),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   tipo.text("overline", self.TITLE))

    def paint_footnote(self, p: QPainter, content: QRectF) -> None:
        p.setFont(tipo.font("caption", size=11))
        p.setPen(QColor(theme.C.ink.tertiary))
        p.drawText(self.footnote_rect(content),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   self.FOOTNOTE)


class LatencyBudget(_AnalysisCard):
    """PRESUPUESTO DE RETARDO (apartado 8.5.3).

    Area apilada en el tiempo con los tres tramos que componen el retardo que se
    siente -- captura, vision y resto del periodo --, la media y el porcentaje
    de cada uno a la derecha, y la regla de objetivo a 100 ms.

    Los tres tramos son los que fija la especificacion, y el orden importa:
    captura abajo porque es el que no depende de nosotros, vision encima porque
    es el que se puede bajar, y el resto arriba en filo de pelo porque es tiempo
    que el bucle no gasta en nada. El apilado usa blit desplazado: una columna
    apilada son tres trapecios y el pozo se desplaza solo.
    """

    TITLE = "presupuesto de retardo"
    FOOTNOTE = "captura + visión + resto del periodo · objetivo 100 ms"

    LEGEND_W = 96.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._trace = StackedTrace(
            self, ground=False, step=2.0,
            colors=[theme.C.color.info, theme.C.color.accent,
                    theme.C.ink.tertiary],
            labels=["captura", "visión", "resto"], hi=140.0)
        self._trace.set_rule(BUDGET_TARGET_MS)
        self._trace.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def push(self, capture_ms: float, vision_ms: float,
             period_ms: float) -> None:
        """Una muestra de ``stats_ready``. El resto sale del periodo real."""
        resto = max(0.0, period_ms - vision_ms)
        self._trace.push((capture_ms, vision_ms, resto))
        self.update()

    def on_theme(self) -> None:
        super().on_theme()
        self._trace._colors = [theme.C.color.info, theme.C.color.accent,
                               theme.C.ink.tertiary]
        self._trace.invalidate()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        c = self.content_rect()
        pozo = QRectF(c.left(), c.top() + 20.0,
                      c.width() - self.LEGEND_W - 12.0,
                      c.height() - 20.0 - 18.0)
        self._trace.setGeometry(pozo.toRect())

    def paint_content(self, p: QPainter, content: QRectF) -> None:
        self.paint_header(p, content)
        medias = self._trace.means()
        total = max(1e-6, float(medias.sum()))
        colores = [theme.C.color.info, theme.C.color.accent, theme.C.ink.tertiary]
        etiquetas = ("captura", "visión", "resto")

        x = content.right() - self.LEGEND_W
        y = content.top() + 24.0
        for i, nombre in enumerate(etiquetas):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(colores[i], 0.92))
            p.drawRoundedRect(QRectF(x, y + 4.0, 8.0, 8.0), 2.0, 2.0)
            p.setFont(tipo.font("caption"))
            p.setPen(QColor(theme.C.ink.secondary))
            p.drawText(QRectF(x + 14.0, y, self.LEGEND_W - 14.0, 15.0),
                       int(Qt.AlignmentFlag.AlignLeft), nombre)
            p.setFont(tipo.font("body-fuerte"))
            p.setPen(QColor(theme.C.ink.primary))
            p.drawText(QRectF(x + 14.0, y + 15.0, self.LEGEND_W - 14.0, 17.0),
                       int(Qt.AlignmentFlag.AlignLeft),
                       f"{num(float(medias[i]), 0)} ms")
            p.setFont(tipo.font("axis"))
            p.setPen(QColor(theme.C.ink.tertiary))
            p.drawText(QRectF(x + 14.0, y + 15.0, self.LEGEND_W - 14.0, 17.0),
                       int(Qt.AlignmentFlag.AlignRight),
                       f"{num(float(medias[i]) / total * 100.0, 0)} %")
            y += 40.0

        self.paint_footnote(p, content)


class Closures(_AnalysisCard):
    """CIERRES (apartado 8.5.6).

    Cada cierre de pinch de la sesion es un punto colocado en el ``pinch_ratio``
    minimo que alcanzo, coloreado por su desenlace. Es el grafico que contesta
    "por que a veces no me hace clic" sin tener que adivinar: si la nube de
    abortados se amontona justo a la derecha del umbral, el problema es el
    umbral.

    ``advice`` lleva la frase calculada y, cuando los datos la sostienen, el
    valor que escribiria el boton «Aplicar». La pagina es quien pone el boton;
    la tarjeta no toca la configuracion.
    """

    TITLE = "cierres"
    FOOTNOTE = "mínimo de pinch alcanzado en cada cierre · color = desenlace"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scatter = Scatter(self, ground=False, lo=0.0, hi=0.7)
        self._scatter.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._advice = Advice("Sin cierres registrados todavía.")
        self._counts = [0, 0, 0, 0]

    @property
    def advice(self) -> Advice:
        return self._advice

    def set_closures(self, minima: Sequence[float], outcomes: Sequence[int],
                     pinch_on: float, pinch_off: float) -> None:
        self._scatter.set_points(minima, outcomes, outcome_colors())
        self._scatter.set_rules([(pinch_on, "cierre " + num(pinch_on, 2)),
                                 (pinch_off, "apertura " + num(pinch_off, 2))])
        self._advice = closure_advice(minima, outcomes, pinch_on)
        self._counts = [int((np.asarray(outcomes) == i).sum())
                        for i in range(4)]
        self.update()

    def on_theme(self) -> None:
        super().on_theme()
        self._scatter._colors = outcome_colors()
        self._scatter.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        c = self.content_rect()
        self._scatter.setGeometry(
            QRectF(c.left(), c.top() + 20.0, c.width(), 72.0).toRect())

    def paint_content(self, p: QPainter, content: QRectF) -> None:
        self.paint_header(p, content)

        # leyenda: cuatro puntos con su cuenta, en una fila
        colores = outcome_colors()
        x = content.left()
        y = content.top() + 100.0
        p.setFont(tipo.font("axis"))
        for i, nombre in enumerate(OUTCOME_NAMES):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(colores[i], 0.90))
            p.drawEllipse(QPointF(x + 3.0, y + 6.0), 3.0, 3.0)
            texto = f"{nombre} {self._counts[i]}"
            ancho = tipo.metrics("axis").horizontalAdvance(texto)
            p.setPen(QColor(theme.C.ink.tertiary))
            p.drawText(QRectF(x + 10.0, y, ancho + 2, 13.0),
                       int(Qt.AlignmentFlag.AlignLeft), texto)
            x += ancho + 22.0

        frase = tipo.Parrafo(self._advice.text, "caption")
        frase.set_width(content.width())
        y = content.bottom() - 16.0 - frase.height()
        p.setPen(QColor(theme.C.ink.primary if self._advice.value is not None
                        else theme.C.ink.secondary))
        frase.draw(p, content.left(), y)
        self.paint_footnote(p, content)


class PointerStability(_AnalysisCard):
    """ESTABILIDAD DEL PUNTERO (apartado 8.5.7).

    El temblor es la media de ``|p[t] - 2*p[t-1] + p[t-2]|``, o sea el residuo
    de alta frecuencia del recorrido. Al lado, la huella: las ultimas 600
    posiciones superpuestas en 120x120 px, que es lo que convierte un numero en
    algo que se entiende de un vistazo -- una nube apretada es una mano firme y
    una nube desperdigada no hay que explicarla.
    """

    TITLE = "estabilidad del puntero"
    FOOTNOTE = "temblor = media de |p−2p′+p″| · 300 muestras apuntando"

    FOOTPRINT = 120.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._trace = Trace(self, ground=False, step=2.0, fill=True,
                            width=1.4, lo=0.0, hi=6.0, autoscale=True,
                            unit=" px", grid=False, margins=(0, 0, 0, 0))
        self._trace.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._points = np.zeros((0, 2), dtype=np.float32)
        self._tremor = 0.0

    @property
    def tremor(self) -> float:
        return self._tremor

    def set_points(self, points: np.ndarray) -> None:
        """Recorrido del puntero en px de pantalla. Ultimas 600 para la huella."""
        p = np.asarray(points, dtype=np.float32)
        self._points = p[-FOOTPRINT_POINTS:] if p.ndim == 2 else self._points
        self._tremor = tremor(p)
        self._trace.push(self._tremor)
        self.update()

    def on_theme(self) -> None:
        super().on_theme()
        self._trace.invalidate()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        c = self.content_rect()
        ancho = c.width() - self.FOOTPRINT - 16.0
        self._trace.setGeometry(
            QRectF(c.left(), c.bottom() - 62.0, ancho, 44.0).toRect())

    def _paint_footprint(self, p: QPainter, caja: QRectF) -> None:
        glass.paint_sheet(p, caja, "E1", R_MD,
                          canvas_origin=self.mapTo(self.window(), QPoint(0, 0)))
        pts = self._points
        if pts.shape[0] < 2:
            return
        centro = pts.mean(axis=0)
        rel = pts - centro
        alcance = float(np.abs(rel).max()) or 1.0
        # se topa la escala: sin tope, un solo salto grande encoge la nube hasta
        # convertirla en un punto y la huella deja de decir nada
        escala = (caja.width() / 2.0 - 6.0) / max(alcance, 24.0)
        cx, cy = caja.center().x(), caja.center().y()
        p.save()
        p.setClipPath(glass.rounded_path(caja, R_MD))
        p.setPen(Qt.PenStyle.NoPen)
        color = theme.C.tokens.mode_color(Mode.POINTING)
        p.setBrush(_c(color, 0.10 if theme.C.dark else 0.16))
        for x, y in rel:
            p.drawEllipse(QPointF(cx + float(x) * escala, cy + float(y) * escala),
                          1.6, 1.6)
        p.setBrush(_c(theme.C.color.accent, 0.95))
        p.drawEllipse(QPointF(cx + float(rel[-1][0]) * escala,
                              cy + float(rel[-1][1]) * escala), 2.4, 2.4)
        p.restore()

    def paint_content(self, p: QPainter, content: QRectF) -> None:
        self.paint_header(p, content)
        caja = QRectF(content.right() - self.FOOTPRINT,
                      content.top() + 20.0, self.FOOTPRINT, self.FOOTPRINT)
        self._paint_footprint(p, caja)

        palabra, color = tremor_verdict(self._tremor)
        p.setFont(tipo.font("metric"))
        p.setPen(QColor(theme.C.ink.primary))
        cifra = num(self._tremor, 1)
        p.drawText(QRectF(content.left(), content.top() + 26.0,
                          content.width() - self.FOOTPRINT - 16.0, 38.0),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   cifra)
        ancho = tipo.metrics("metric").horizontalAdvance(cifra)
        p.setFont(tipo.font("caption"))
        p.setPen(QColor(theme.C.ink.tertiary))
        p.drawText(QRectF(content.left() + ancho + 6.0, content.top() + 26.0,
                          40.0, 38.0),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   "px")
        p.setFont(tipo.font("overline"))
        p.setPen(QColor(color))
        p.drawText(QRectF(content.left(), content.top() + 62.0,
                          content.width() - self.FOOTPRINT - 16.0, 14.0),
                   int(Qt.AlignmentFlag.AlignLeft), tipo.text("overline", palabra))
        self.paint_footnote(p, content)
