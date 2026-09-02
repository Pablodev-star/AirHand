"""La capa de pintado de CRISTAL VIVO: lienzo vivo, atlas de sombras y laminas.

Son las lineas que no producen nada visible por si mismas y de las que depende
que la direccion se sienta como cristal en vez de degenerar en "tarjetas planas
con un degradado". Tres piezas:

* ``CanvasSource`` es el fondo. Un QImage minusculo (320x180 como techo) con la
  base y cuatro manchas radiales que derivan despacio. El truco de toda la
  direccion vive aqui: **como el fondo lo pinta la propia aplicacion, una lamina
  no necesita desenfocar lo que tiene detras, le basta con recortar el lienzo
  pequenyo y dejar que el reescalado haga de desenfoque**. En Qt no hay backdrop
  blur y no hace ninguna falta. El precio es que solo funciona dentro de la
  ventana: lo que salga de ella (overlay, menus desbordados) usa vidrio
  autoiluminado, no translucidez.
* ``ShadowAtlas`` cachea cada sombra desenfocada como un tile 9-slice. Una sombra
  de desenfoque 64 recalculada por fotograma cuesta mas que todo lo demas junto,
  y ``QGraphicsDropShadowEffect`` -que es lo que hacia la interfaz vieja en cada
  ``Card``- ademas fuerza un render fuera de pantalla del subarbol entero y mata
  el ClearType. Queda prohibido en todo el proyecto.
* ``paint_sheet`` pinta una lamina en el orden exacto del apartado 4.3. El orden
  no es negociable: el velo antes que los filos y los filos antes que el
  contenido, o el vidrio se ve sucio por arriba y romo por los bordes.

El modo claro no es el oscuro invertido y aqui casi no se nota, porque
``tokens.py`` ya trae las sombras al 60 % de geometria y entintadas de azul
(#1F2947) y los filos con el dominante abajo-derecha. Lo unico que este modulo
decide por tema es el color del velo.
"""
from __future__ import annotations

import ctypes
import math
import sys
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QWidget

from . import motion, theme
from .tokens import R_FULL, R_LG, Blob, Elevation, Ink, Shadow, Tokens

# --------------------------------------------------------------------------- #
# utilidades de color
# --------------------------------------------------------------------------- #

#: Alfas del filo claro que responden al estado (4.3). Son absolutas en la escala
#: de la paleta oscura; ``paint_sheet`` las traduce a la razon que toque, porque
#: en claro ``edge.light`` vale 0.95 y un 0.18 absoluto seria un filo mas debil
#: que el de reposo, justo al reves de lo que se pide.
EDGE_REST = 0.14
EDGE_HOVER = 0.18
EDGE_ACTIVE = 0.24
EDGE_FLASH = 0.30

#: Tope duro del sangrado del grafico de fondo (4.3.4). No es ajustable: por
#: encima de esto el grafico deja de ser material de la lamina y pasa a ser una
#: imagen dentro de una caja, que es exactamente lo que la direccion evita.
BLEED_ALPHA = 0.45

#: El velo obligatorio bajo un sangrado (4.3.5).
VEIL_BAND = 0.55
VEIL_DARK = QColor(0, 0, 0, round(0.62 * 255))
VEIL_LIGHT = QColor(255, 255, 255, round(0.72 * 255))


def qcolor(ink: Ink) -> QColor:
    """``Ink`` -> ``QColor``. El unico puente entre tokens y QPainter."""
    c = QColor(ink.hex)
    c.setAlphaF(max(0.0, min(1.0, ink.alpha)))
    return c


def luminance(hex_color: str) -> float:
    """Luminancia percibida 0..1 de un hex opaco."""
    c = QColor(hex_color)
    return (0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()) / 255.0


def wash_luminance_step(tokens: Tokens | None = None) -> float:
    """Escalon de luminancia entre el lienzo y una lamina E2, en tanto por uno.

    El apartado 11.1 lo fija en el 4 %: ni mas (se ve la caja) ni menos
    (desaparece). Existe como funcion y no como constante porque es la primera
    medida que hay que mirar cuando alguien toca la paleta clara.
    """
    t = tokens or theme.C.tokens
    return abs(luminance(t.glass.wash.solid) - luminance(t.canvas.base))


def _snap(rect: QRectF) -> QRectF:
    """Lleva un rectangulo a coordenadas enteras + 0.5.

    Sin esto, un filo cosmetico de 1 px cae a caballo entre dos pixeles a DPR
    1.25 o 1.5 y sale como una banda gris de 2 px: el sintoma es que las laminas
    parecen tener borde en vez de filo.
    """
    x = math.floor(rect.x()) + 0.5
    y = math.floor(rect.y()) + 0.5
    w = max(1.0, round(rect.width()) - 1.0)
    h = max(1.0, round(rect.height()) - 1.0)
    return QRectF(x, y, w, h)


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    """Camino redondeado. ``R_FULL`` (o cualquier negativo) da una pildora."""
    r = radius
    if r <= R_FULL:
        r = min(rect.width(), rect.height()) / 2.0
    r = max(0.0, min(r, min(rect.width(), rect.height()) / 2.0))
    path = QPainterPath()
    path.addRoundedRect(rect, r, r)
    return path


# --------------------------------------------------------------------------- #
# lienzo vivo (4.1)
# --------------------------------------------------------------------------- #

class CanvasSource(QObject):
    """El fondo E0: un buffer minusculo, vivo y congelable.

    El buffer nunca pasa de 320x180 **pase lo que pase**. No es una optimizacion
    prudente: es el mecanismo. Un recorte de un buffer ocho veces menor que la
    ventana, reescalado con ``SmoothTransformation``, *es* el desenfoque de
    fondo. Subir la resolucion del buffer no mejoraria el lienzo, quitaria el
    desenfoque.
    """

    MAX_W = 320
    MAX_H = 180

    #: Periodos de las trayectorias senoidales (4.1). Primos entre si a ojo: con
    #: periodos conmensurables las manchas vuelven a la misma pose cada pocos
    #: segundos y el fondo deja de parecer vivo.
    PERIODS = (23.0, 31.0, 41.0)
    AMPLITUDE = 0.08            # <= 8 % del lado

    #: Un pixel del buffer pequenyo son ~5 de pantalla: por debajo de eso
    #: regenerar es tirar 10 Hz de CPU en un cambio que nadie puede ver.
    MIN_MOVE = 1.0

    PARALLAX_GAIN = 0.03
    PARALLAX_MAX = 10.0
    CURSOR_HZ = 30

    #: Recortes cacheados. Un recorte cuesta 0.34 ms y es, con diferencia, la
    #: parte cara de pintar una lamina; pero el lienzo solo cambia diez veces
    #: por segundo como mucho, asi que recalcularlo en cada repintado es tirar
    #: el trabajo. Cuarenta y ocho entradas cubren un panel entero con sus
    #: insets sin que el diccionario crezca sin freno.
    CROP_CACHE = 48

    changed = Signal()

    def __init__(self, tokens: Tokens | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens or theme.C.tokens
        self._w = 1.0
        self._h = 1.0
        self._buffer: QImage | None = None
        self._phase = 0.0
        self._acc = 0.0
        self._cursor_acc = 0.0
        self._last_centres: tuple[tuple[float, float], ...] = ()
        self._active = True
        self._compact = False
        self._engine_running = False
        self._joined = False
        self._crops: dict[tuple[int, int, int, int], QPixmap] = {}
        # el paralaje se suaviza: leido a pelo, el raton tiembla y el fondo
        # entero tiembla con el, que es peor que no tener paralaje
        self._px = motion.Smooth(0.0, tau=0.12)
        self._py = motion.Smooth(0.0, tau=0.12)

    # -- estado externo -----------------------------------------------------
    def set_tokens(self, tokens: Tokens) -> None:
        if tokens is self._tokens:
            return
        self._tokens = tokens
        self._buffer = None
        self._render()
        self.changed.emit()

    def resize(self, width: float, height: float) -> None:
        """Tamanyo logico de la ventana. El buffer conserva la proporcion."""
        w, h = max(1.0, float(width)), max(1.0, float(height))
        if abs(w - self._w) < 1.0 and abs(h - self._h) < 1.0 and self._buffer:
            return
        self._w, self._h = w, h
        self._buffer = None
        self._render()

    def set_active(self, value: bool) -> None:
        """Compuerta (a): la ventana no esta activa."""
        self._active = bool(value)

    def set_compact(self, value: bool) -> None:
        self._compact = bool(value)

    def set_engine_running(self, value: bool) -> None:
        self._engine_running = bool(value)

    @property
    def frozen(self) -> bool:
        """Las tres compuertas de congelacion del apartado 4.1.

        Sin las tres, el fondo vivo se come el presupuesto que el motor de vision
        necesita, que es el unico presupuesto que el usuario nota de verdad.
        """
        if not self._active:
            return True
        if self._engine_running and self._compact:
            return True
        return motion.reduce_motion()

    # -- latido -------------------------------------------------------------
    def start(self) -> None:
        if not self._joined:
            motion.beat.join(self, motion.HZ_CANVAS)
            self._joined = True

    def stop(self) -> None:
        if self._joined:
            motion.beat.leave(self)
            self._joined = False

    def tick(self, dt: float) -> bool:
        if self.frozen:
            return False
        self._phase += dt
        self._cursor_acc += dt
        moved = False
        if self._cursor_acc >= 1.0 / self.CURSOR_HZ:
            self._cursor_acc = 0.0
            moved = self._sample_cursor()
        if self._render():
            moved = True
        if moved:
            self.changed.emit()
        return True

    def _sample_cursor(self) -> bool:
        """Paralaje: 0.03 x el desplazamiento del cursor, tope +-10 px.

        Se mide contra el centro de la ventana y no acumulando deltas: acumular
        deriva sin retorno y a los cinco minutos el lienzo esta pegado a un
        borde con el raton en el centro.
        """
        pos = QCursor.pos()
        tx = max(-self.PARALLAX_MAX,
                 min(self.PARALLAX_MAX, (pos.x() - self._w / 2.0) * self.PARALLAX_GAIN))
        ty = max(-self.PARALLAX_MAX,
                 min(self.PARALLAX_MAX, (pos.y() - self._h / 2.0) * self.PARALLAX_GAIN))
        self._px.set(tx)
        self._py.set(ty)
        before = (round(self._px.value), round(self._py.value))
        self._px.step()
        self._py.step()
        # solo cuenta como movimiento si el desplazamiento cruza un pixel
        # entero: por debajo de eso nadie lo ve y en cambio invalidaria los
        # recortes cacheados sesenta veces por segundo
        if before == (round(self._px.value), round(self._py.value)):
            return False
        self._crops.clear()
        return True

    def parallax(self) -> QPointF:
        # el tope se vuelve a aplicar aqui y no solo al fijar el objetivo:
        # ``_dest`` desborda el lienzo exactamente PARALLAX_MAX por lado, asi
        # que un desplazamiento mayor descubriria el borde del buffer
        m = self.PARALLAX_MAX
        return QPointF(max(-m, min(m, self._px.value)),
                       max(-m, min(m, self._py.value)))

    # -- generacion ---------------------------------------------------------
    def _buffer_size(self) -> tuple[int, int]:
        k = max(self._w / self.MAX_W, self._h / self.MAX_H, 1.0)
        return max(1, round(self._w / k)), max(1, round(self._h / k))

    def _centres(self) -> tuple[tuple[float, float], ...]:
        """Centros de las cuatro manchas, en fraccion del buffer.

        Cada mancha usa dos periodos distintos para x e y: con el mismo periodo
        en los dos ejes la trayectoria es una recta y se ve el vaiven.
        """
        t = self._phase
        a = self.AMPLITUDE
        p = self.PERIODS
        c = self._tokens.canvas

        def wobble(blob: Blob, ix: int, iy: int, phase: float) -> tuple[float, float]:
            dx = a * math.sin(2.0 * math.pi * t / p[ix] + phase)
            dy = a * math.cos(2.0 * math.pi * t / p[iy] + phase)
            return blob.cx + dx, blob.cy + dy

        out = [wobble(c.light, 0, 1, 0.0),
               wobble(c.cool, 1, 2, 1.7),
               wobble(c.tint, 2, 0, 3.1)]
        if c.vignette is not None:
            # la vinneta esta clavada a la esquina: moverla delataria el truco
            out.append((c.vignette.cx, c.vignette.cy))
        return tuple(out)

    def _render(self, force: bool = False) -> bool:
        """Regenera el buffer si alguna mancha se ha movido mas de 1 px en el."""
        bw, bh = self._buffer_size()
        stale = (self._buffer is None or self._buffer.width() != bw
                 or self._buffer.height() != bh)
        centres = self._centres()
        if not stale and not force and self._last_centres:
            worst = max(
                max(abs(a[0] - b[0]) * bw, abs(a[1] - b[1]) * bh)
                for a, b in zip(centres, self._last_centres))
            if worst < self.MIN_MOVE:
                return False

        img = QImage(bw, bh, QImage.Format.Format_ARGB32_Premultiplied)
        c = self._tokens.canvas
        img.fill(QColor(c.base))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        diag = math.hypot(bw, bh)
        blobs = [c.light, c.cool, c.tint]
        if c.vignette is not None:
            blobs.append(c.vignette)
        for blob, (cx, cy) in zip(blobs, centres):
            centre = QPointF(cx * bw, cy * bh)
            grad = QRadialGradient(centre, blob.radius * diag)
            head = qcolor(blob.ink)
            # Con dos paradas el radial de Qt cae en linea recta y se ve el cono:
            # un circulo con centro marcado y un borde perceptible donde muere.
            # Estas cuatro paradas son un smoothstep, que es lo que hace que la
            # mancha parezca luz y no un objeto.
            for stop, k in ((0.0, 1.0), (0.35, 0.86), (0.70, 0.42), (1.0, 0.0)):
                c_stop = QColor(head)
                c_stop.setAlphaF(head.alphaF() * k)
                grad.setColorAt(stop, c_stop)
            p.setBrush(grad)
            p.drawRect(0, 0, bw, bh)
        p.end()

        self._buffer = img
        self._last_centres = centres
        self._crops.clear()
        return True

    # -- consumo ------------------------------------------------------------
    def canvas_image(self) -> QImage:
        if self._buffer is None:
            self._render(force=True)
        assert self._buffer is not None
        return self._buffer

    def _dest(self) -> QRectF:
        """Rectangulo de ventana que ocupa el buffer, con el paralaje aplicado.

        Se dibuja desbordado ``PARALLAX_MAX`` por lado para que el paralaje no
        descubra un borde vacio. ``paint`` y ``blurred_crop`` derivan los dos de
        aqui: si divergieran, el recorte de una lamina no cuadraria con el fondo
        y el efecto se cae de golpe.
        """
        m = self.PARALLAX_MAX
        r = QRectF(-m, -m, self._w + 2 * m, self._h + 2 * m)
        r.translate(self.parallax())
        return r

    def paint(self, painter: QPainter, rect: QRectF | None = None) -> None:
        """Pinta el lienzo E0. Es lo unico del sistema que se mueve solo."""
        img = self.canvas_image()
        dest = self._dest()
        if rect is not None:
            painter.save()
            painter.setClipRect(rect)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(dest, img)
        if rect is not None:
            painter.restore()

    def blurred_crop(self, rect: QRectF | QRect) -> QPixmap:
        """Recorte del lienzo bajo ``rect``, reescalado. El reescalado es el blur.

        ``rect`` va en coordenadas de la ventana (las mismas que ``resize``).
        El resultado se cachea hasta que el lienzo se regenere o el paralaje
        cruce un pixel entero.
        """
        r = QRectF(rect)
        dw = max(1, int(round(r.width())))
        dh = max(1, int(round(r.height())))
        key = (int(round(r.x())), int(round(r.y())), dw, dh)
        hit = self._crops.get(key)
        if hit is not None:
            return hit
        img = self.canvas_image()
        dest = self._dest()
        sx = img.width() / dest.width()
        sy = img.height() / dest.height()

        # dos pixeles de sangrado en origen: sin ellos el remuestreo suave chupa
        # el borde del buffer y una lamina pegada al borde de la ventana sale con
        # una banda clara de un pixel
        pad = 2
        u0 = int(math.floor((r.left() - dest.left()) * sx)) - pad
        v0 = int(math.floor((r.top() - dest.top()) * sy)) - pad
        u1 = int(math.ceil((r.right() - dest.left()) * sx)) + pad
        v1 = int(math.ceil((r.bottom() - dest.top()) * sy)) + pad
        u0 = max(0, min(u0, img.width() - 1))
        v0 = max(0, min(v0, img.height() - 1))
        u1 = max(u0 + 1, min(u1, img.width()))
        v1 = max(v0 + 1, min(v1, img.height()))

        src = img.copy(QRect(u0, v0, u1 - u0, v1 - v0))
        big_w = max(1, int(round((u1 - u0) / sx)))
        big_h = max(1, int(round((v1 - v0) / sy)))
        big = src.scaled(big_w, big_h, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        ox = int(round(r.left() - (dest.left() + u0 / sx)))
        oy = int(round(r.top() - (dest.top() + v0 / sy)))
        ox = max(0, min(ox, max(0, big_w - dw)))
        oy = max(0, min(oy, max(0, big_h - dh)))
        out = QPixmap.fromImage(big.copy(ox, oy, dw, dh))
        if len(self._crops) >= self.CROP_CACHE:
            # el mas viejo primero: los dict de Python conservan el orden de
            # insercion, asi que esto es una cola sin traerse una libreria
            self._crops.pop(next(iter(self._crops)))
        self._crops[key] = out
        return out


#: Lienzo que usan las laminas cuando no se les pasa uno. Lo publica el armazon
#: de la ventana al crearse; fuera de la ventana (overlay) se queda a None y
#: ``paint_sheet`` cae a relleno plano, que es justamente lo que manda el
#: apartado 12.1 para las superficies que salen de la aplicacion.
_ACTIVE_CANVAS: CanvasSource | None = None


def set_active_canvas(source: CanvasSource | None) -> None:
    global _ACTIVE_CANVAS
    _ACTIVE_CANVAS = source


def active_canvas() -> CanvasSource | None:
    return _ACTIVE_CANVAS


# --------------------------------------------------------------------------- #
# atlas de sombras 9-slice (4.2)
# --------------------------------------------------------------------------- #

def _box1d(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """Media movil de anchura 2r+1 por sumas acumuladas. O(n) por eje."""
    w = 2 * r + 1
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad), axis=axis)
    n = a.shape[axis]
    hi = np.take(c, np.arange(w, w + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) / float(w)


def _rounded_mask(size: int, inset: float, radius: float) -> np.ndarray:
    """Cobertura antialiasada de un rounded-rect, como float 0..1.

    Se dibuja con QPainter y se lee el canal alfa en vez de rasterizar el
    rectangulo a mano: el antialiasing de Qt en las esquinas es exactamente lo
    que hace que la sombra no tenga escalones cuando el desenfoque es pequenyo.
    """
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255))
    body = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    r = max(0.0, min(radius, min(body.width(), body.height()) / 2.0))
    p.drawRoundedRect(body, r, r)
    p.end()
    raw = np.frombuffer(img.constBits(), dtype=np.uint8)
    raw = raw.reshape(img.height(), img.bytesPerLine() // 4, 4)
    return raw[:, :size, 3].astype(np.float32) / 255.0


def _tile_from_mask(mask: np.ndarray, color: QColor) -> QImage:
    h, w = mask.shape
    a = np.clip(mask, 0.0, 1.0) * color.alphaF()
    out = np.empty((h, w, 4), dtype=np.uint8)
    # ARGB32 premultiplicado en little-endian: B, G, R, A
    out[..., 0] = np.round(a * color.blue())
    out[..., 1] = np.round(a * color.green())
    out[..., 2] = np.round(a * color.red())
    out[..., 3] = np.round(a * 255.0)
    img = QImage(out.tobytes(), w, h, 4 * w,
                 QImage.Format.Format_ARGB32_Premultiplied)
    return img.copy()          # el buffer de numpy muere al salir


def _uncovered(area: QRectF, cover: QRectF) -> list[QRectF]:
    """``area`` menos ``cover``, en hasta cuatro tiras que no se solapan.

    No se solapan a proposito: rellenar dos veces la misma tira con una tinta
    translucida la deja al doble de oscura, y en una esquina eso se ve.
    """
    if not area.intersects(cover):
        return [area]
    out: list[QRectF] = []
    top = max(area.top(), min(cover.top(), area.bottom()))
    bottom = min(area.bottom(), max(cover.bottom(), area.top()))
    if top > area.top():
        out.append(QRectF(area.left(), area.top(), area.width(), top - area.top()))
    if bottom < area.bottom():
        out.append(QRectF(area.left(), bottom, area.width(), area.bottom() - bottom))
    left = max(area.left(), min(cover.left(), area.right()))
    right = min(area.right(), max(cover.right(), area.left()))
    if left > area.left():
        out.append(QRectF(area.left(), top, left - area.left(), bottom - top))
    if right < area.right():
        out.append(QRectF(right, top, area.right() - right, bottom - top))
    return [r for r in out if r.width() > 0.01 and r.height() > 0.01]


class ShadowAtlas:
    """Sombras desenfocadas cacheadas por ``(radio, desenfoque, tinta)``.

    ``QGraphicsDropShadowEffect`` queda **prohibido** en todo el proyecto: fuerza
    un render fuera de pantalla de todo el subarbol en cada repintado y desactiva
    el ClearType. Esta clase es su sustituto y la mayor ganancia de rendimiento
    del rehaul.
    """

    #: Techo del tile. Un desenfoque 64 con radio 32 pediria 258 px de lado; se
    #: genera a 128 y se estira al pintar. En una mancha ya desenfocada la
    #: perdida es literalmente invisible, y el atlas entero cabe en 400 KB.
    MAX_TILE = 128

    def __init__(self) -> None:
        self._tiles: dict[tuple, tuple[QImage, float, float]] = {}
        self._built = 0

    @property
    def built(self) -> int:
        """Cuantos tiles se han generado. Sirve para vigilar el cache."""
        return self._built

    def clear(self) -> None:
        self._tiles.clear()

    def tile(self, radius: float, blur: int,
             ink: Ink) -> tuple[QImage, float, float, float]:
        """``(imagen, esquina en origen, esquina en destino, margen)``.

        La tinta entra en la clave aunque el apartado 4.2 solo nombre el alfa:
        hay dos paletas vivas a la vez durante el fundido de cambio de tema, y
        una clave sin color le daria a la clara las sombras negras de la oscura.
        """
        key = (round(float(radius), 1), int(blur), round(ink.alpha, 3), ink.hex)
        hit = self._tiles.get(key)
        if hit is not None:
            return hit

        # Tres pasadas de caja de anchura ~= desenfoque dan sigma ~= blur/2, que
        # es la equivalencia gaussiana habitual.
        #
        # La esquina del 9-slice no es ``radio + margen``, es ``2*margen + radio``,
        # y equivocarse aqui es el fallo que costo la primera version: con la
        # esquina corta el cuerpo del tile queda mas estrecho que el propio
        # desenfoque, la mancha nunca llega a su meseta, y al estirar los lados
        # desde un pico atenuado sale un escalon duro justo donde acaba la
        # esquina. Se ve como una losa gris con borde recto alrededor de la
        # lamina. La meseta empieza a ``margen`` (borde de la forma) mas
        # ``margen`` (alcance del desenfoque), y en la esquina hay que sumar
        # ademas el radio del arco.
        margin = max(1.0, float(blur))
        corner = 2.0 * margin + float(radius)
        natural = 2.0 * corner + 2.0
        scale = min(1.0, self.MAX_TILE / natural)
        size = max(8, int(round(natural * scale)))

        mask = _rounded_mask(size, margin * scale, float(radius) * scale)
        box = int(round(blur * scale / 2.0))
        if box >= 1:
            for _ in range(3):
                mask = _box1d(_box1d(mask, box, 0), box, 1)

        img = _tile_from_mask(mask, qcolor(ink))
        src_corner = float((size - 2) // 2)
        out = (img, src_corner, corner, margin)
        self._tiles[key] = out
        self._built += 1
        return out

    def paint(self, painter: QPainter, rect: QRectF, radius: float,
              shadow: Shadow) -> None:
        """Ocho ``drawImage``: cuatro esquinas y cuatro lados. El centro se salta.

        Saltarse el centro no es un detalle: en una tarjeta de 360x220 el centro
        es el 80 % de los pixeles de la sombra y **esta tapado por la lamina**.

        Ojo con el "esta tapado": la sombra va desplazada ``(dx, dy)``, asi que
        el centro saltado no coincide con la lamina. La tira que sobresale hay
        que rellenarla con el color liso de la meseta o se ve un escalon: con
        E4 (desplazamiento 22) era una banda de 22 px con borde recto debajo de
        cada superficie flotante.
        """
        if shadow.blur <= 0 and shadow.ink.alpha <= 0.0:
            return
        img, sc, dc, margin = self.tile(radius, shadow.blur, shadow.ink)
        # El rectangulo exterior crece el *margen*, no la esquina del 9-slice.
        # Es la unica cuenta de este archivo que hay que hacer despacio: en el
        # tile la silueta esta metida ``margen`` hacia dentro, asi que si el
        # exterior creciera la esquina entera, la silueta caeria ``margen +
        # radio`` por fuera de la lamina y se veria una losa de sombra a alfa
        # plena rodeandola. Las esquinas se siguen dibujando a tamanyo
        # ``esquina``, que se mete bajo la lamina: ahi es donde viven la rampa
        # del desenfoque y el arco.
        outer = QRectF(rect).adjusted(-margin, -margin, margin, margin)
        outer.translate(shadow.dx, shadow.dy)
        if outer.width() <= 0 or outer.height() <= 0:
            return

        c = min(dc, outer.width() / 2.0, outer.height() / 2.0)
        s = sc * (c / dc) if dc > 0 else 0.0
        sw, sh = float(img.width()), float(img.height())
        ml, mt = outer.left(), outer.top()
        mr, mb = outer.right() - c, outer.bottom() - c
        inner_w = outer.width() - 2.0 * c
        inner_h = outer.height() - 2.0 * c
        src_w = sw - 2.0 * s
        src_h = sh - 2.0 * s

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # esquinas
        painter.drawImage(QRectF(ml, mt, c, c), img, QRectF(0, 0, s, s))
        painter.drawImage(QRectF(mr, mt, c, c), img, QRectF(sw - s, 0, s, s))
        painter.drawImage(QRectF(ml, mb, c, c), img, QRectF(0, sh - s, s, s))
        painter.drawImage(QRectF(mr, mb, c, c), img, QRectF(sw - s, sh - s, s, s))
        # lados
        if inner_w > 0.0 and src_w > 0.0:
            painter.drawImage(QRectF(ml + c, mt, inner_w, c),
                              img, QRectF(s, 0, src_w, s))
            painter.drawImage(QRectF(ml + c, mb, inner_w, c),
                              img, QRectF(s, sh - s, src_w, s))
        if inner_h > 0.0 and src_h > 0.0:
            painter.drawImage(QRectF(ml, mt + c, c, inner_h),
                              img, QRectF(0, s, s, src_h))
            painter.drawImage(QRectF(mr, mt + c, c, inner_h),
                              img, QRectF(sw - s, s, s, src_h))
        # centro: solo la parte que la lamina no llega a tapar
        if inner_w > 0.0 and inner_h > 0.0:
            centre = QRectF(ml + c, mt + c, inner_w, inner_h)
            fill = qcolor(shadow.ink)
            for band in _uncovered(centre, QRectF(rect)):
                painter.fillRect(band, fill)
        painter.restore()


ATLAS = ShadowAtlas()


# --------------------------------------------------------------------------- #
# pintor de laminas (4.3)
# --------------------------------------------------------------------------- #

def elevation_of(elevation: str | Elevation,
                 tokens: Tokens | None = None) -> Elevation:
    if isinstance(elevation, Elevation):
        return elevation
    t = tokens or theme.C.tokens
    return t.elevation[elevation]


def sheet_rect(rect: QRectF | QRect, elevation: str | Elevation,
               tokens: Tokens | None = None) -> QRectF:
    """El rectangulo que ocupa de verdad la lamina, con el alzado de E3 aplicado.

    E3 crece un 1.008 respecto de E2. Se hace al pintar y no en el layout a
    proposito: un hover que dispare un relayout cuesta mil veces mas que un
    rectangulo inflado 1.2 px por lado, y ademas arrastraria a los vecinos.
    """
    elev = elevation_of(elevation, tokens)
    r = QRectF(rect)
    if elev.scale != 1.0:
        dw = r.width() * (elev.scale - 1.0) / 2.0
        dh = r.height() * (elev.scale - 1.0) / 2.0
        r.adjust(-dw, -dh, dw, dh)
    return _snap(r)


def paint_sheet(painter: QPainter, rect: QRectF | QRect,
                elevation: str | Elevation, radius: float = R_LG, *,
                edge_light: float | None = None,
                tint: Ink | QColor | None = None,
                bleed: QPixmap | None = None,
                tokens: Tokens | None = None,
                canvas: CanvasSource | None = None,
                canvas_origin: QPoint | QPointF | None = None,
                shadows: bool = True,
                atlas: ShadowAtlas | None = None) -> QPainterPath:
    """Pinta una lamina en el orden del apartado 4.3 y devuelve su camino.

    El orden es sombra -> recorte del lienzo -> lavado -> sangrado -> velo ->
    filos, y el contenido lo pinta quien llama, encima y recortado al camino que
    se devuelve. Cambiar dos pasos de sitio se nota: el velo despues de los
    filos los apaga, y el lavado despues del sangrado deja el grafico crudo.

    ``canvas_origin`` es la posicion del origen del ``painter`` dentro del
    lienzo. Un widget hijo lo pasa como ``self.mapTo(ventana, QPoint(0, 0))``;
    sin el, todas las laminas recortarian la misma esquina del lienzo y el
    truco se vendria abajo en cuanto hubiese dos.
    """
    t = tokens or theme.C.tokens
    elev = elevation_of(elevation, t)
    src = canvas if canvas is not None else _ACTIVE_CANVAS
    at = atlas if atlas is not None else ATLAS

    r = sheet_rect(rect, elev, t)
    rad = radius
    if rad <= R_FULL:
        rad = min(r.width(), r.height()) / 2.0
    path = rounded_path(r, rad)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 1. sombra desde el atlas
    if shadows:
        for sh in elev.shadows:
            at.paint(painter, r, rad, sh)

    surface = getattr(t.glass, elev.fill)

    painter.save()
    painter.setClipPath(path)

    # 2. recorte del lienzo desenfocado (E2/E3/E4) o relleno plano (E1)
    filled = False
    if elev.clip_canvas or elev.name in ("E3", "E4"):
        if src is not None:
            o = QPointF(canvas_origin) if canvas_origin is not None else QPointF()
            crop = src.blurred_crop(QRectF(r.translated(o)))
            if not crop.isNull():
                painter.drawPixmap(r.topLeft(), crop)
                filled = True
        if not filled:
            # fuera de la ventana no hay lienzo que recortar: vidrio
            # autoiluminado, nunca translucidez (apartado 12.1)
            painter.fillRect(r, QColor(surface.solid))
            filled = True

    # 3. lavado del nivel. Con el recorte ya puesto se rellena el rectangulo y
    # no el camino: la forma la da el clip, y rasterizar el rounded-rect otra
    # vez costaba mas que el propio relleno
    painter.fillRect(r, qcolor(surface.ink))

    # 3b. tinte opcional de modo o de estado
    if tint is not None:
        painter.fillRect(r, tint if isinstance(tint, QColor) else qcolor(tint))

    # 4. sangrado: el grafico *es* el fondo de la lamina, no va en un recuadro
    if bleed is not None and not bleed.isNull():
        painter.setOpacity(BLEED_ALPHA)
        painter.drawPixmap(r, bleed, QRectF(bleed.rect()))
        painter.setOpacity(1.0)

        # 5. velo obligatorio. Sin el, el texto de la tarjeta cae sobre la parte
        # viva del grafico y deja de leerse justo cuando hay datos interesantes
        band = QRectF(r.left(), r.bottom() - r.height() * VEIL_BAND,
                      r.width(), r.height() * VEIL_BAND)
        veil = QLinearGradient(band.topLeft(), band.bottomLeft())
        strong = VEIL_DARK if t.dark else VEIL_LIGHT
        clear = QColor(strong)
        clear.setAlpha(0)
        veil.setColorAt(0.0, clear)
        veil.setColorAt(1.0, strong)
        painter.fillRect(band, veil)

    painter.restore()

    # 6. filos
    _paint_edges(painter, r, rad, elev, t, edge_light)
    painter.restore()
    return path


def _edge_inks(elev: Elevation, t: Tokens,
               edge_light: float | None) -> tuple[Ink, Ink]:
    """Los dos filos de la lamina, ya con el estado aplicado.

    ``edge_light`` **sustituye** el alfa de reposo, no lo multiplica: pasar
    ``EDGE_HOVER`` a una E2 tiene que dar exactamente el filo de una E3, o el
    canal de retroalimentacion deja de ser predecible.
    """
    if edge_light is None or elev.name == "E1":
        # E1 lleva el filo invertido (oscuro arriba-izquierda) para leerse como
        # un rebaje; escalarlo con la razon del filo claro no significaria nada
        return elev.edge_tl, elev.edge_br
    return t.edge.light.scaled(edge_light / EDGE_REST), elev.edge_br


def _paint_edges(painter: QPainter, r: QRectF, radius: float,
                 elev: Elevation, t: Tokens, edge_light: float | None) -> None:
    """Filo claro arriba+izquierda, oscuro abajo+derecha.

    Los dos arcos se solapan medio codo en las esquinas neutras (arriba-derecha
    y abajo-izquierda) para que el relevo no deje una muesca visible: con corte
    limpio a 90 grados se ve un punto oscuro en cada una.
    """
    tl, br = _edge_inks(elev, t, edge_light)
    for ink, light_side in ((tl, True), (br, False)):
        if ink.alpha <= 0.0:
            continue
        pen = QPen(qcolor(ink))
        pen.setWidthF(0.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(_edge_path(r, radius, light_side))


def _edge_path(r: QRectF, radius: float, light_side: bool) -> QPainterPath:
    rad = max(0.0, min(radius, min(r.width(), r.height()) / 2.0))
    d = 2.0 * rad
    tl = QRectF(r.left(), r.top(), d, d)
    tr = QRectF(r.right() - d, r.top(), d, d)
    bl = QRectF(r.left(), r.bottom() - d, d, d)
    br = QRectF(r.right() - d, r.bottom() - d, d, d)
    path = QPainterPath()
    if rad <= 0.0:
        if light_side:
            path.moveTo(r.bottomLeft())
            path.lineTo(r.topLeft())
            path.lineTo(r.topRight())
        else:
            path.moveTo(r.topRight())
            path.lineTo(r.bottomRight())
            path.lineTo(r.bottomLeft())
        return path
    if light_side:
        # de media esquina abajo-izquierda a media esquina arriba-derecha
        path.arcMoveTo(bl, 225.0)
        path.arcTo(bl, 225.0, -45.0)
        path.lineTo(r.left(), r.top() + rad)
        path.arcTo(tl, 180.0, -90.0)
        path.lineTo(r.right() - rad, r.top())
        path.arcTo(tr, 90.0, -45.0)
    else:
        path.arcMoveTo(tr, 45.0)
        path.arcTo(tr, 45.0, -45.0)
        path.lineTo(r.right(), r.bottom() - rad)
        path.arcTo(br, 0.0, -90.0)
        path.lineTo(r.left() + rad, r.bottom())
        path.arcTo(bl, 270.0, -45.0)
    return path


@dataclass
class Sheet:
    """Descripcion de pintado de una lamina: lo que un widget guarda y varia.

    El widget vive en ``widgets/base.py``; esto es solo su cara de pintor, para
    que cambiar de hover a activo sea mover un float y no reconstruir nada.
    """

    elevation: str = "E2"
    radius: float = R_LG
    edge: float = EDGE_REST
    tint: Ink | QColor | None = None
    bleed: QPixmap | None = None
    origin: QPoint = field(default_factory=QPoint)

    def paint(self, painter: QPainter, rect: QRectF | QRect,
              **kwargs) -> QPainterPath:
        kwargs.setdefault("edge_light", self.edge)
        kwargs.setdefault("tint", self.tint)
        kwargs.setdefault("bleed", self.bleed)
        kwargs.setdefault("canvas_origin", self.origin)
        return paint_sheet(painter, rect, self.elevation, self.radius, **kwargs)


# --------------------------------------------------------------------------- #
# Mica (4.4): opcional, apagada por defecto
# --------------------------------------------------------------------------- #

_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_MAINWINDOW = 2


def apply_mica(widget: QWidget) -> bool:
    """Intenta el backdrop del sistema. Degrada en silencio, nunca revienta.

    La direccion **no depende de Mica**: el lienzo pintado es el camino
    principal y esto es una mejora para quien la quiera. En Windows 10 la
    llamada devuelve un HRESULT de error y aqui simplemente se dice que no.
    """
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(_DWMSBT_MAINWINDOW)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
            ctypes.c_void_p(hwnd), ctypes.c_uint(_DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(value), ctypes.sizeof(value))
        return res == 0
    except Exception:
        return False
