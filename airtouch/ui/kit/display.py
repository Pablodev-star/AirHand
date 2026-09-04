"""Las piezas que **muestran** un dato: cifra, traza, punto, chapa, anillo y guia.

Ninguna de estas seis se puede pulsar. Su unico trabajo es contar lo que esta
pasando, y por eso el archivo entero gira alrededor de tres decisiones que en la
interfaz vieja estan tomadas al reves:

* **La cifra en vivo no puede bailar.** Un ``QLabel`` con la fuente por defecto
  y ``f"{v:.1f}"`` mide distinto con "58,1" que con "11,1", asi que a 4 Hz la
  unidad de al lado tiembla y el panel entero parece mal hecho. Aqui la cifra
  sale de ``tipo.py`` (rol ``metric``, con ``tnum`` de verdad, comprobado
  midiendo) **y ademas** la caja de la cifra es una marca de agua que solo crece:
  las cifras tabulares arreglan el ancho de cada digito, pero no el salto de
  ganar o perder uno.
* **Una traza temporal no se repinta entera.** El apartado 7 lo prohibe: se
  guarda un ``QPixmap``, cada muestra hace ``scroll`` y se pinta **solo la
  columna nueva**. Un osciloscopio de 420x110 repintado entero son 46 kpx por
  fotograma; con ``step`` 2 son 220. La trampa que se lleva el ahorro por
  delante es el autoescalado: si el rango se recalcula en cada muestra hay que
  reconstruir el pixmap en cada muestra y el blit no sirve de nada. Por eso el
  rango tiene histeresis (ver ``Sparkline._fit``).
* **Nadie tiene temporizador propio.** Lo que respira o rueda se apunta al
  ``Beat`` con la compuerta de frecuencia que le toca (20 Hz para glows, 60 Hz
  para valores en movimiento) y se da de baja sola en cuanto se asienta.

Ninguna pieza de aqui es una ``Sheet``: son cromo *dentro* de una lamina. Una
chapa de 20 px que proyectase la sombra de una E4 tendria que reservarse 50 px
de hueco por lado para pintar su propia sombra, y eso no es un badge, es un
menu flotante.
"""
from __future__ import annotations

import math
import re
import time
from collections import deque

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .. import motion, theme, tipo
from .base import Beating, ThemeAware

__all__ = [
    "Metric", "Sparkline", "Dot", "Badge", "Ring", "LeaderLine",
    "tone_color", "format_number",
]

#: Cadencia por encima de la cual una cifra deja de rodar (apartado 5.5.5).
LIVE_PERIOD = 0.25

#: Reserva a la derecha de una traza para que quepa entero el punto de cabeza.
HEAD_PAD = 3.0

#: Respiracion del anillo del Nucleo: alfa 0.24 a 0.40 (apartado 8.1).
BREATH_LO, BREATH_HI = 0.24, 0.40

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def tone_color(tone: str) -> str:
    """Un tono del sistema a color. Acepta tambien un hex literal.

    Los tonos son los de la paleta -no colores sueltos- porque el principio 3
    dice que el color significa: ``ok``, ``warn``, ``danger``, ``info`` y
    ``accent`` son estados; ``neutral`` y ``quiet`` son cromo.
    """
    if tone.startswith("#"):
        return tone
    if tone == "neutral":
        return theme.C.ink.secondary
    if tone == "quiet":
        return theme.C.ink.tertiary
    return getattr(theme.C.color, tone)


def _q(tone: str, alpha: float = 1.0) -> QColor:
    c = QColor(tone_color(tone))
    if alpha < 1.0:
        c.setAlphaF(alpha)
    return c


def format_number(value: float, decimals: int = 1) -> str:
    """Numero con las convenciones de la interfaz: coma decimal, punto de millar.

    La interfaz esta en espanyol y "58.1" es otro numero. Se hace a mano porque
    ``locale`` depende de como este configurado el equipo, y una cifra que
    cambia de separador segun el ordenador no es un dato honesto.
    """
    s = f"{abs(value):,.{decimals}f}"
    s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return ("-" if value < 0 else "") + s


# --------------------------------------------------------------------------- #
# punto y chapa
# --------------------------------------------------------------------------- #

class Dot(ThemeAware, Beating, QWidget):
    """Punto de estado: indicador de guarda, chip de la barra, lampara.

    Cambia de color **cruzando**, nunca de golpe: tau 0.13 es la constante del
    cruce de modo del apartado 5.3, y es lo que hace que la rampa de modo se lea
    como un solo objeto que cambia de temperatura y no como siete puntos
    distintos parpadeando.
    """

    BEAT_HZ = motion.HZ_GLOW          # es un glow: 20 Hz, no 60

    #: Hueco por lado para el halo. Fijo aunque no lata: encender la pulsacion
    #: no puede reordenar la fila en la que vive el punto.
    HALO = 6

    def __init__(self, parent: QWidget | None = None, *, size: int = 8,
                 tone: str = "quiet", pulse: bool = False) -> None:
        super().__init__(parent)
        self._size = int(size)
        self._tone = tone
        self._from = QColor(tone_color(tone))
        self._cross = motion.Smooth(1.0, motion.TAU_MODE_COLOR)
        self._pulse = bool(pulse)
        self._phase = 0.0
        self.setFixedSize(self._size + 2 * self.HALO, self._size + 2 * self.HALO)
        if self._pulse:
            self.animate()

    def set_tone(self, tone: str) -> None:
        if tone == self._tone:
            return
        self._from = self._current()
        self._tone = tone
        self._cross.jump(0.0)
        self._cross.set(1.0)
        self.animate()

    def set_pulse(self, value: bool) -> None:
        if bool(value) == self._pulse:
            return
        self._pulse = bool(value)
        if self._pulse:
            self.animate()
        else:
            self.update()

    def _current(self) -> QColor:
        k = self._cross.value
        if k >= 1.0:
            return QColor(tone_color(self._tone))
        a, b = self._from, QColor(tone_color(self._tone))
        return QColor(round(a.red() + (b.red() - a.red()) * k),
                      round(a.green() + (b.green() - a.green()) * k),
                      round(a.blue() + (b.blue() - a.blue()) * k))

    def tick(self, dt: float) -> bool:
        busy = False
        if not self._cross.settled:
            self._cross.step()
            busy = True
        if self._pulse and not motion.reduce_motion():
            self._phase = (self._phase + dt * 1000.0 / motion.BREATH) % 1.0
            busy = True
        self.update()
        if not busy:
            self.rest()
        return busy

    def on_theme(self) -> None:
        # el color de partida es de la paleta vieja: cruzar hacia el nuevo desde
        # un color que ya no existe pintaria un tono que no esta en ninguna
        self._cross.jump(1.0)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = self._current()
        centro = QPointF(self.width() / 2.0, self.height() / 2.0)
        r = self._size / 2.0
        if self._pulse:
            k = 0.5 - 0.5 * math.cos(self._phase * 2.0 * math.pi)
            halo = QColor(c)
            halo.setAlphaF(BREATH_LO + (BREATH_HI - BREATH_LO) * k)
            p.setBrush(halo)
            p.setPen(Qt.PenStyle.NoPen)
            rh = r + self.HALO * (0.55 + 0.45 * k)
            p.drawEllipse(centro, rh, rh)
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(centro, r, r)
        p.end()


class Badge(ThemeAware, Beating, QWidget):
    """Chapa: version, "ahorro", "control activo", aviso fechado.

    Aparece con el pop del apartado 5.4 (200 ms, ``EASE_LIFT`` con sobrepaso
    1.12) y el pop escala **la chapa entera**, filo incluido: una chapa cuyo
    texto crece dentro de una pildora quieta se lee como un error de layout.
    """

    PAD_H, PAD_V = 10, 4

    def __init__(self, text: str = "", parent: QWidget | None = None, *,
                 tone: str = "neutral", role: str = "overline",
                 dot: bool = False) -> None:
        super().__init__(parent)
        self._text = text
        self._tone = tone
        self._role = role
        self._dot = bool(dot)
        self._pop = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_text(self, text: str, tone: str | None = None) -> None:
        if text == self._text and (tone is None or tone == self._tone):
            return
        self._text = text
        if tone is not None:
            self._tone = tone
        self.updateGeometry()
        self.update()

    def pop(self) -> None:
        """La chapa acaba de aparecer. Una sola vez, al aparecer de verdad."""
        self._pop = 0.0
        self.animate()

    def _dot_size(self) -> float:
        return 6.0 if self._dot else 0.0

    def sizeHint(self) -> QSize:                       # noqa: N802 (API de Qt)
        m = tipo.metrics(self._role)
        ancho = m.horizontalAdvance(tipo.text(self._role, self._text))
        if self._dot:
            ancho += self._dot_size() + 6.0
        return QSize(int(math.ceil(ancho)) + 2 * self.PAD_H,
                     int(math.ceil(m.height())) + 2 * self.PAD_V)

    def minimumSizeHint(self) -> QSize:                # noqa: N802 (API de Qt)
        return self.sizeHint()

    def tick(self, dt: float) -> bool:
        self._pop = min(1.0, self._pop + dt * 1000.0 / motion.dur(motion.ELEMENT))
        self.update()
        if self._pop >= 1.0:
            self.rest()
            return False
        return True

    def on_theme(self) -> None:
        self.updateGeometry()
        self.update()

    def paintEvent(self, event) -> None:
        if not self._text and not self._dot:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._pop < 1.0:
            k = motion.ease(self._pop, motion.EASE_LIFT)
            s = 1.0 - 0.12 * (1.0 - k)
            c = QPointF(self.width() / 2.0, self.height() / 2.0)
            p.translate(c)
            p.scale(s, s)
            p.translate(-c)
            p.setOpacity(min(1.0, self._pop * 2.5))

        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radio = r.height() / 2.0
        neutro = self._tone in ("neutral", "quiet")
        p.setBrush(_q(self._tone, 0.10 if neutro
                      else (0.16 if theme.C.dark else 0.12)))
        p.setPen(QPen(_q(self._tone, 0.20 if neutro else 0.28), 1.0))
        p.drawRoundedRect(r, radio, radio)

        x = r.left() + self.PAD_H
        if self._dot:
            d = self._dot_size()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_q(self._tone))
            p.drawEllipse(QPointF(x + d / 2.0, r.center().y()), d / 2.0, d / 2.0)
            x += d + 6.0
        p.setPen(QColor(theme.C.ink.secondary if neutro else tone_color(self._tone)))
        p.setFont(tipo.font(self._role))
        m = tipo.metrics(self._role)
        base = r.center().y() + (m.ascent() - m.descent()) / 2.0
        p.drawText(QPointF(x, base), tipo.text(self._role, self._text))
        p.end()


# --------------------------------------------------------------------------- #
# anillo
# --------------------------------------------------------------------------- #

class Ring(ThemeAware, Beating, QWidget):
    """Anillo de progreso: arranque del motor, permanencia, cuenta atras.

    Mientras el progreso se mueve late a 60 Hz (es una deriva de valor); en
    cuanto se asienta y solo queda la respiracion baja a 20 Hz, que es la
    compuerta que el apartado 5.1 le pone a los glows. El cambio de compuerta se
    hace con ``beat.join`` sobre un asiento que ya existe: ahi solo cambia el
    periodo, no se anyade un participante.
    """

    BEAT_HZ = motion.HZ_FULL

    def __init__(self, parent: QWidget | None = None, *, diameter: int = 72,
                 thickness: float = 4.0, tone: str = "accent",
                 progress: float = 0.0, breathing: bool = False) -> None:
        super().__init__(parent)
        self._thickness = float(thickness)
        self._tone = tone
        self._progress = motion.Smooth(progress, motion.TAU_RING)
        self._breathing = bool(breathing)
        self._phase = 0.0
        self._hz = motion.HZ_FULL
        self.setFixedSize(diameter, diameter)
        if self._breathing:
            self.animate()

    @property
    def progress(self) -> float:
        return self._progress.value

    def set_progress(self, value: float, *, immediate: bool = False) -> None:
        v = max(0.0, min(1.0, value))
        if immediate:
            self._progress.jump(v)
            self.update()
            return
        self._progress.set(v)
        self.animate()

    def set_breathing(self, value: bool) -> None:
        if bool(value) == self._breathing:
            return
        self._breathing = bool(value)
        if self._breathing:
            self.animate()
        else:
            self.update()

    def set_tone(self, tone: str) -> None:
        if tone != self._tone:
            self._tone = tone
            self.update()

    def _rate(self, hz: int) -> None:
        """Cambia la compuerta de frecuencia sin salirse del latido."""
        if self._beating and hz != self._hz:
            motion.beat.join(self, hz)
            self._hz = hz

    def tick(self, dt: float) -> bool:
        busy = False
        if not self._progress.settled:
            self._progress.step()
            busy = True
        respira = self._breathing and not motion.reduce_motion()
        if respira:
            self._phase = (self._phase + dt * 1000.0 / motion.BREATH) % 1.0
            busy = True
        self.update()
        if not busy:
            self.rest()
            return False
        self._rate(motion.HZ_FULL if not self._progress.settled
                   else motion.HZ_GLOW)
        return True

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        d = self._thickness
        r = QRectF(self.rect()).adjusted(d / 2.0, d / 2.0, -d / 2.0, -d / 2.0)

        # la pista es el propio anillo apagado: cualquier otro color obliga a
        # elegir uno distinto en cada tema y a los dos les queda sucio
        p.setPen(QPen(_q(self._tone, 0.14), d))
        p.drawEllipse(r)

        k = self._progress.value
        if k > 0.0:
            alfa = 1.0
            if self._breathing and not motion.reduce_motion():
                b = 0.5 - 0.5 * math.cos(self._phase * 2.0 * math.pi)
                alfa = BREATH_LO + (BREATH_HI - BREATH_LO) * b
            pluma = QPen(_q(self._tone, alfa), d)
            pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pluma)
            # arranca arriba y gira como un reloj: al reves se lee como que algo
            # se deshace, y esto siempre cuenta algo que se llena
            p.drawArc(r, 90 * 16, -int(round(k * 360 * 16)))
        p.end()


# --------------------------------------------------------------------------- #
# traza
# --------------------------------------------------------------------------- #

class Sparkline(ThemeAware, QWidget):
    """Traza temporal con blit desplazado (apartado 7).

    No se apunta al latido: **solo repinta cuando llega una muestra**, y de esa
    muestra repinta la columna nueva, no el widget. El historial vive en un
    ``QPixmap`` propio que se desplaza con ``QPixmap.scroll``.

    El pixmap se guarda en pixeles de dispositivo y con la escala aplicada a
    mano en el pintor. Es a proposito: ``scroll`` mueve pixeles crudos, y
    mezclarlo con ``devicePixelRatio`` deja medio pixel de desfase por muestra
    que a los treinta desplazamientos ya es un diente de sierra visible.
    """

    def __init__(self, parent: QWidget | None = None, *, width: int = 60,
                 height: int = 28, step: float = 2.0, tone: str = "accent",
                 fill: bool = True, lo: float | None = None,
                 hi: float | None = None) -> None:
        super().__init__(parent)
        self._step = float(step)
        self._tone = tone
        self._fill = bool(fill)
        self._fixed = lo is not None and hi is not None
        self._lo = 0.0 if lo is None else float(lo)
        self._hi = 1.0 if hi is None else float(hi)
        self._pm: QPixmap | None = None
        self._dpr = 1.0
        columnas = int(math.ceil((width - HEAD_PAD) / max(0.5, self._step))) + 2
        # antes del setFixedSize: fijar el tamanyo ya dispara resizeEvent, y
        # alli se reconstruye el pixmap leyendo este buffer
        self._buf: deque[float] = deque(maxlen=columnas)
        self.setFixedSize(int(width), int(height))

    # -- datos --------------------------------------------------------------
    def push(self, value: float) -> None:
        """Una muestra nueva. Es la unica via caliente de esta clase."""
        self._buf.append(float(value))
        if len(self._buf) < 2 or self._fit():
            self._rebuild()
            self.update()
            return
        self._scroll_in()
        # solo la columna nueva mas el halo del punto de cabeza (apartado 7)
        ancho = self._step + HEAD_PAD + 8.0
        x = max(0, int(self._plot_w() - ancho))
        self.update(QRect(x, 0, self.width() - x, self.height()))

    def set_values(self, values) -> None:
        """Recarga entera. Para rellenar de historial, no para ir en vivo."""
        self._buf.clear()
        self._buf.extend(float(v) for v in values)
        self._fit(force=True)
        self._rebuild()
        self.update()

    def clear(self) -> None:
        self._buf.clear()
        self._rebuild()
        self.update()

    @property
    def values(self) -> list[float]:
        return list(self._buf)

    def _plot_w(self) -> float:
        return self.width() - HEAD_PAD

    def _fit(self, *, force: bool = False) -> bool:
        """Reajusta el rango vertical. ``True`` si hay que reconstruir.

        La histeresis es la pieza que hace viable el blit: con autoescalado
        estricto, cada muestra que roza el minimo o el maximo cambia el mapeo y
        obliga a repintar el pixmap entero, o sea justo lo que el apartado 7
        prohibe. Aqui el rango solo se rehace cuando el dato **sale** de el o
        cuando la senyal se ha encogido a menos de la mitad.
        """
        if self._fixed or not self._buf:
            return force
        dmin, dmax = min(self._buf), max(self._buf)
        span = self._hi - self._lo
        if not (force or span <= 0.0 or dmin < self._lo or dmax > self._hi
                or (dmax - dmin) < 0.55 * span):
            return False
        margen = max((dmax - dmin) * 0.12, abs(dmax) * 0.02, 1e-6)
        self._lo, self._hi = dmin - margen, dmax + margen
        return True

    def _y(self, value: float) -> float:
        k = (value - self._lo) / max(1e-9, self._hi - self._lo)
        borde = 1.5                       # media pluma: si no, la cresta se corta
        return self.height() - borde - max(0.0, min(1.0, k)) * (self.height() - 2 * borde)

    # -- pixmap -------------------------------------------------------------
    def _ensure(self) -> QPixmap | None:
        if self.width() <= 0 or self.height() <= 0:
            return None
        dpr = max(1.0, self.devicePixelRatioF())
        ancho = int(round(self.width() * dpr))
        alto = int(round(self.height() * dpr))
        if (self._pm is None or self._dpr != dpr
                or self._pm.width() != ancho or self._pm.height() != alto):
            self._dpr = dpr
            self._pm = QPixmap(ancho, alto)
            self._pm.fill(Qt.GlobalColor.transparent)
            return None                   # nuevo y vacio: hay que reconstruir
        return self._pm

    def _painter(self, pm: QPixmap) -> QPainter:
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.scale(self._dpr, self._dpr)
        return p

    def _pen(self) -> QPen:
        pluma = QPen(_q(self._tone), 1.5)
        pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
        pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pluma

    def _gradient(self) -> QLinearGradient:
        g = QLinearGradient(0.0, 0.0, 0.0, float(self.height()))
        g.setColorAt(0.0, _q(self._tone, 0.26))
        g.setColorAt(1.0, _q(self._tone, 0.0))
        return g

    def _rebuild(self) -> None:
        """Repinta el historial entero. Solo al cambiar rango, tema o tamanyo."""
        self._ensure()
        pm = self._pm
        if pm is None:
            return
        pm.fill(Qt.GlobalColor.transparent)
        if len(self._buf) < 2:
            return
        vals = list(self._buf)
        n = len(vals)
        x0 = self._plot_w() - (n - 1) * self._step
        pts = [QPointF(x0 + i * self._step, self._y(v)) for i, v in enumerate(vals)]
        p = self._painter(pm)
        if self._fill:
            camino = [QPointF(pts[0].x(), float(self.height()))] + pts + \
                     [QPointF(pts[-1].x(), float(self.height()))]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._gradient())
            p.drawPolygon(camino)
        p.setPen(self._pen())
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(pts)
        p.end()

    def _scroll_in(self) -> None:
        """Desplaza el pixmap y pinta unicamente el segmento nuevo."""
        pm = self._ensure()
        if pm is None:
            self._rebuild()               # pixmap recien creado: no hay historial
            return
        d = int(round(self._step * self._dpr))
        pm.scroll(-d, 0, pm.rect())

        x1 = self._plot_w()
        x0 = x1 - self._step
        y0, y1 = self._y(self._buf[-2]), self._y(self._buf[-1])
        franja = QRectF(x0, 0.0, self._step + HEAD_PAD, float(self.height()))
        p = self._painter(pm)
        # el desplazamiento arrastra basura desde el borde derecho: la franja se
        # vacia antes de pintarla, y con Clear para no dejar un cerco opaco
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(franja, Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setClipRect(franja)
        if self._fill:
            alto = float(self.height())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._gradient())
            p.drawPolygon([QPointF(x0, y0), QPointF(x1, y1),
                           QPointF(x1, alto), QPointF(x0, alto)])
        p.setPen(self._pen())
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        p.end()

    # -- ciclo de vida ------------------------------------------------------
    def resizeEvent(self, event) -> None:                # noqa: N802 (API de Qt)
        self._ensure()
        self._rebuild()
        super().resizeEvent(event)

    def on_theme(self) -> None:
        self._rebuild()
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._pm is None:
            self._ensure()
            self._rebuild()
        if self._pm is not None:
            p.drawPixmap(QRectF(self.rect()), self._pm, QRectF(self._pm.rect()))
        if self._buf:
            # el punto de cabeza va aqui y no en el pixmap: dentro se
            # desplazaria con el historial y dejaria un rastro de puntos
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_q(self._tone))
            p.drawEllipse(QPointF(self._plot_w(), self._y(self._buf[-1])), 2.0, 2.0)
        p.end()


# --------------------------------------------------------------------------- #
# cifra
# --------------------------------------------------------------------------- #

class Metric(ThemeAware, Beating, QWidget):
    """La cifra grande con su etiqueta, su unidad, su tendencia y su traza.

    Es la ficha del apartado 8.5: etiqueta en ``overline``, cifra en ``metric``
    34/300, unidad en ``caption``, flecha de tendencia de 3 px y microsparkline.

    Dos detalles que se ven al medirlos y no al leerlos:

    * la cifra usa ``tnum``, asi que todos los digitos miden lo mismo, **y** la
      caja de la cifra es una marca de agua que solo crece: sin ella, pasar de
      "9,8" a "10,2" empuja la unidad 20 px a la derecha cuatro veces por
      segundo;
    * si las muestras llegan mas de cuatro veces por segundo la cifra deja de
      rodar y salta (apartado 5.5.5). Interpolar algo que cambia mas rapido que
      la interpolacion no es suavizar, es mentir con retardo.
    """

    BEAT_HZ = motion.HZ_FULL

    LABEL_GAP = 6.0
    NOTE_GAP = 6.0
    UNIT_GAP = 6.0
    ARROW_GAP = 10.0

    def __init__(self, label: str = "", parent: QWidget | None = None, *,
                 unit: str = "", value: float = 0.0, decimals: int = 1,
                 note: str = "", role: str = "metric", tone: str = "accent",
                 spark: bool = True, spark_size: tuple[int, int] = (60, 28),
                 higher_is_better: bool = True) -> None:
        super().__init__(parent)
        self._label = label
        self._unit = unit
        self._note = note
        self._role = role
        self._tone = tone
        self._decimals = int(decimals)
        self._better_up = bool(higher_is_better)
        self._smooth = motion.Smooth(value, motion.TAU_METER)
        self._text = self._format(value)
        self._box = 0.0                   # marca de agua del ancho de la cifra
        self._trend = 0
        self._trend_fijo = False
        self._llegadas: deque[float] = deque(maxlen=4)
        self._ultima = 0.0
        self._spark: Sparkline | None = None
        if spark:
            self._spark = Sparkline(self, width=spark_size[0],
                                    height=spark_size[1], tone=tone)

    # -- datos --------------------------------------------------------------
    @property
    def value(self) -> float:
        return self._smooth.target

    @property
    def spark(self) -> Sparkline | None:
        return self._spark

    def set_value(self, value: float) -> None:
        ahora = time.perf_counter()
        if self._ultima:
            self._llegadas.append(ahora - self._ultima)
        self._ultima = ahora
        self._smooth.set(float(value))
        if self._en_vivo() or motion.reduce_motion():
            self._smooth.jump(float(value))
            self._refresh()
        else:
            self.animate()

    def push(self, value: float) -> None:
        """Cifra y traza de una sola vez: es como llega un dato de verdad."""
        self.set_value(value)
        if self._spark is not None:
            self._spark.push(value)
            if not self._trend_fijo:
                self._auto_trend()

    def set_trend(self, trend: int | None) -> None:
        """``None`` devuelve la tendencia al calculo automatico de la traza."""
        self._trend_fijo = trend is not None
        nuevo = 0 if trend is None else max(-1, min(1, int(trend)))
        if nuevo != self._trend:
            self._trend = nuevo
            self.update()

    def set_note(self, note: str) -> None:
        if note != self._note:
            self._note = note
            self.updateGeometry()
            self.update()

    def _en_vivo(self) -> bool:
        """Mas de cuatro muestras por segundo de media en las ultimas cuatro."""
        if len(self._llegadas) < self._llegadas.maxlen:
            return False
        return sum(self._llegadas) / len(self._llegadas) < LIVE_PERIOD

    def _auto_trend(self) -> None:
        vals = self._spark.values if self._spark else []
        if len(vals) < 6:
            return
        corte = len(vals) // 3
        viejo = sum(vals[-3 * corte:-corte]) / max(1, 2 * corte)
        nuevo = sum(vals[-corte:]) / corte
        umbral = max(abs(viejo) * 0.02, 1e-9)
        t = 0 if abs(nuevo - viejo) < umbral else (1 if nuevo > viejo else -1)
        if t != self._trend:
            self._trend = t
            self.update()

    def _format(self, value: float) -> str:
        return format_number(value, self._decimals)

    def _refresh(self) -> None:
        nuevo = self._format(self._smooth.value)
        if nuevo != self._text:
            self._text = nuevo
            self.update()

    def tick(self, dt: float) -> bool:
        self._smooth.step()
        # update() solo cuando cambia el texto **ya formateado** (apartado 5.5.5)
        self._refresh()
        if self._smooth.settled:
            self.rest()
            return False
        return True

    # -- geometria ----------------------------------------------------------
    def _rows(self) -> tuple[float, float, float]:
        """Altos de las tres filas: etiqueta, cifra y nota."""
        return (tipo.metrics("overline").height(),
                tipo.metrics(self._role).height(),
                tipo.metrics("caption").height() if self._note else 0.0)

    def sizeHint(self) -> QSize:                       # noqa: N802 (API de Qt)
        h_lab, h_val, h_note = self._rows()
        alto = h_lab + self.LABEL_GAP + h_val
        if h_note:
            alto += self.NOTE_GAP + h_note
        ancho = max(tipo.metrics("overline").horizontalAdvance(
                        tipo.text("overline", self._label)),
                    self._value_row_width())
        if self._note:
            ancho = max(ancho, tipo.metrics("caption").horizontalAdvance(self._note))
        return QSize(int(math.ceil(ancho)), int(math.ceil(alto)))

    def minimumSizeHint(self) -> QSize:                # noqa: N802 (API de Qt)
        return self.sizeHint()

    def _value_row_width(self) -> float:
        ancho = max(self._box, tipo.metrics(self._role).horizontalAdvance(self._text))
        if self._unit:
            ancho += self.UNIT_GAP + tipo.metrics("caption").horizontalAdvance(self._unit)
        if self._trend:
            ancho += self.ARROW_GAP + 10.0
        if self._spark is not None:
            ancho += 16.0 + self._spark.width()
        return ancho

    def _place_spark(self) -> None:
        if self._spark is None:
            return
        h_lab, h_val, _ = self._rows()
        y = h_lab + self.LABEL_GAP + (h_val - self._spark.height()) / 2.0
        self._spark.move(self.width() - self._spark.width(), int(round(y)))

    def resizeEvent(self, event) -> None:                # noqa: N802 (API de Qt)
        self._place_spark()
        super().resizeEvent(event)

    def on_theme(self) -> None:
        # la marca de agua esta medida con la fuente de antes; si el cambio de
        # tema ha traido otra escala tipografica, ese ancho ya no significa nada
        self._box = 0.0
        self.updateGeometry()
        self.update()

    # -- pintado ------------------------------------------------------------
    def _paint_trend(self, p: QPainter, x: float, cy: float) -> float:
        if not self._trend:
            return x
        bien = (self._trend > 0) == self._better_up
        pluma = QPen(_q("ok" if bien else "warn"), 3.0)
        pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
        pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        a, d = 10.0, 4.5 * (-1 if self._trend > 0 else 1)
        p.drawPolyline([QPointF(x, cy - d), QPointF(x + a / 2.0, cy + d),
                        QPointF(x + a, cy - d)])
        return x + a

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        m_lab, m_val = tipo.metrics("overline"), tipo.metrics(self._role)
        m_cap = tipo.metrics("caption")
        h_lab, h_val, h_note = self._rows()

        ancho = float(self.width())
        if self._label:
            p.setPen(QColor(theme.C.ink.tertiary))
            p.setFont(tipo.font("overline"))
            p.drawText(QPointF(0.0, m_lab.ascent()),
                       m_lab.elidedText(tipo.text("overline", self._label),
                                        Qt.TextElideMode.ElideRight, ancho))

        base = h_lab + self.LABEL_GAP + m_val.ascent()
        p.setPen(QColor(theme.C.ink.primary))
        p.setFont(tipo.font(self._role))
        p.drawText(QPointF(0.0, base), self._text)
        # marca de agua: la caja de la cifra nunca encoge, asi la unidad no se
        # mueve cuando el numero gana o pierde un digito
        self._box = max(self._box, m_val.horizontalAdvance(self._text))
        x = self._box

        if self._unit:
            x += self.UNIT_GAP
            p.setPen(QColor(theme.C.ink.secondary))
            p.setFont(tipo.font("caption"))
            p.drawText(QPointF(x, base), self._unit)
            x += m_cap.horizontalAdvance(self._unit)
        if self._trend:
            x = self._paint_trend(p, x + self.ARROW_GAP,
                                  base - m_val.xHeight() / 2.0)

        if self._note:
            y = h_lab + self.LABEL_GAP + h_val + self.NOTE_GAP + m_cap.ascent()
            p.setPen(QColor(theme.C.ink.tertiary))
            p.setFont(tipo.font("caption"))
            # la nota dice como se calcula la cifra (principio 4): es larga y
            # vale mas recortada que empujando el ancho de la ficha
            p.drawText(QPointF(0.0, y),
                       m_cap.elidedText(self._note, Qt.TextElideMode.ElideRight,
                                        ancho))
        p.end()


# --------------------------------------------------------------------------- #
# guia de puntos
# --------------------------------------------------------------------------- #

class LeaderLine(ThemeAware, Beating, QWidget):
    """Una linea del recibo final del asistente (apartado 9.3, P6).

    ``CAMARA ............ iPhone · 1920x1080 · 60 fps``

    Los puntos se colocan en una rejilla anclada al **borde derecho**, no al
    final de la etiqueta: asi las columnas de puntos de todas las lineas caen
    alineadas y el bloque se lee como una hoja de especificaciones compuesta, que
    es exactamente lo que la pagina promete devolver.

    El valor cuenta desde cero en 500 ms. Cuenta cada numero del texto por
    separado, asi que "1920x1080 · 60 fps" crece entero sin que haya que
    trocearlo desde fuera. Por eso el valor va en un rol tabular: un contador con
    digitos de ancho variable tiembla justo mientras se le esta mirando.
    """

    BEAT_HZ = motion.HZ_FULL

    #: Cuenta desde cero (apartado 9.3) y retardo entre lineas del recibo.
    COUNT_MS = 500.0
    LINE_DELAY_MS = 90.0

    DOT_STEP = 6.0
    DOT_R = 1.0
    PAD = 8.0

    def __init__(self, label: str = "", value: str = "",
                 parent: QWidget | None = None, *, label_role: str = "overline",
                 value_role: str = "mono", count: bool = True) -> None:
        super().__init__(parent)
        self._label = label
        self._value = value
        self._label_role = label_role
        self._value_role = value_role
        self._count = bool(count)
        self._k = 1.0
        self._delay = 0.0

    def set_value(self, value: str) -> None:
        if value != self._value:
            self._value = value
            self.updateGeometry()
            self.update()

    def reveal(self, index: int = 0) -> None:
        """Aparece contando. ``index`` es su puesto en el recibo: 90 ms cada uno."""
        self._delay = index * self.LINE_DELAY_MS
        self._k = 0.0 if self._count else 1.0
        if motion.reduce_motion():
            self._delay *= motion.REDUCE_FACTOR
        self.animate()

    def _shown(self) -> str:
        if self._k >= 1.0 or not self._count:
            return self._value
        k = self._k

        def escala(m: re.Match) -> str:
            crudo = m.group(0)
            sep = "," if "," in crudo else ("." if "." in crudo else "")
            dec = len(crudo.split(sep)[1]) if sep else 0
            v = float(crudo.replace(",", ".")) * k
            s = f"{v:.{dec}f}"
            return s.replace(".", sep) if sep else s

        return _NUM.sub(escala, self._value)

    def tick(self, dt: float) -> bool:
        ms = dt * 1000.0
        if self._delay > 0.0:
            self._delay = max(0.0, self._delay - ms)
            return True
        antes = self._shown()
        self._k = min(1.0, self._k + ms / motion.dur(int(self.COUNT_MS)))
        if self._shown() != antes or self._k < 0.5:
            # mientras aparece hay que repintar por la opacidad; despues, solo
            # si el texto formateado cambia de verdad
            self.update()
        if self._k >= 1.0:
            self.update()
            self.rest()
            return False
        return True

    def sizeHint(self) -> QSize:                       # noqa: N802 (API de Qt)
        m_lab = tipo.metrics(self._label_role)
        m_val = tipo.metrics(self._value_role)
        ancho = (m_lab.horizontalAdvance(tipo.text(self._label_role, self._label))
                 + 6 * self.DOT_STEP + 2 * self.PAD
                 + m_val.horizontalAdvance(self._value))
        return QSize(int(math.ceil(ancho)),
                     int(math.ceil(max(m_lab.height(), m_val.height()))))

    def minimumSizeHint(self) -> QSize:                # noqa: N802 (API de Qt)
        return self.sizeHint()

    def on_theme(self) -> None:
        self.updateGeometry()
        self.update()

    def paintEvent(self, event) -> None:
        if self._delay > 0.0:
            return                       # aun no le toca: ni la etiqueta
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._k < 1.0:
            p.setOpacity(min(1.0, self._k * 3.0))

        m_lab = tipo.metrics(self._label_role)
        m_val = tipo.metrics(self._value_role)
        base = (self.height() + m_val.ascent() - m_val.descent()) / 2.0
        etiqueta = tipo.text(self._label_role, self._label)
        p.setPen(QColor(theme.C.ink.secondary))
        p.setFont(tipo.font(self._label_role))
        p.drawText(QPointF(0.0, base), etiqueta)

        texto = self._shown()
        ancho_val = m_val.horizontalAdvance(texto)
        p.setPen(QColor(theme.C.ink.primary))
        p.setFont(tipo.font(self._value_role))
        p.drawText(QPointF(self.width() - ancho_val, base), texto)

        x0 = m_lab.horizontalAdvance(etiqueta) + self.PAD
        x1 = self.width() - ancho_val - self.PAD
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.C.ink.quiet))
        y = base - m_val.xHeight() / 3.0
        x = x1
        while x >= x0:
            p.drawEllipse(QPointF(x, y), self.DOT_R, self.DOT_R)
            x -= self.DOT_STEP
        p.end()
