"""Piezas compartidas del panel 2.0: iconos de linea, filas y bases de pagina.

Aqui vive lo que usan a la vez la columna viva, el mosaico y las paginas
profundas, y nada mas. Tres decisiones del archivo que conviene entender antes
de tocarlo:

* **El texto lo pinta quien lo tiene.** Igual que en el asistente: ni un
  ``QLabel`` en todo el panel. Con el texto pintado, la tipografia sale entera
  de ``tipo.py`` -tracking incluido, que es lo que el QSS no sabe expresar- y un
  escalonado de entrada es una multiplicacion en el ``paintEvent``.
* **Las paginas son hijas de la ventana entera, no del area del mosaico.** Una
  lamina guarda dentro de si misma el hueco de su sombra (``Sheet.reserve()``),
  asi que una pagina recortada al area cortaria a canto recto la sombra de toda
  tarjeta pegada al borde. Las paginas ocupan la ventana, se declaran
  transparentes al raton -sus hijos siguen recibiendo eventos- y colocan su
  contenido dentro de ``self.area``.
* **El desplazamiento vertical es propio y no un ``QScrollArea``.** La pagina de
  analisis coloca sus laminas a mano con ``place()``; meterlas en un
  ``QScrollArea`` obligaria a un widget interior de alto calculado, a pelearse
  con el fondo del viewport y a que el recorte del lienzo se descuadrase al
  desplazar. Un desplazamiento propio son treinta lineas y no tiene ninguno de
  los tres problemas.

Los iconos son de linea fina de 1,5 px (apartado 8.2) y se describen en
coordenadas de caja unidad, para que el mismo glifo sirva a 20 px en una
tarjeta y a 18 en la barra inferior sin dibujarlo dos veces.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .. import motion, theme, tipo
from ..kit.base import Beating, ThemeAware
from ..tokens import R_SM
from ..wizard.piezas import Progresion, texto, texto_ajustado

__all__ = [
    "GROSOR_ICONO", "icono", "ICONOS", "reloj", "Pagina", "PaginaDesplazable",
    "FilaCompacta", "FilaFantasma", "Progresion", "texto", "texto_ajustado",
    "MARGEN_PAGINA",
]

#: Los iconos del mosaico y de la barra son de linea fina (apartado 8.2). El
#: grosor no escala con el icono a proposito: una linea de 1,5 px es la firma, y
#: engordarla en la tarjeta grande la convertiria en otra cosa.
GROSOR_ICONO = 1.5

#: Margen interior de una pagina profunda respecto del area del mosaico.
MARGEN_PAGINA = 32.0


# --------------------------------------------------------------------------- #
# iconos de linea
# --------------------------------------------------------------------------- #

#: Cada icono es una lista de primitivas en coordenadas de caja unidad:
#: ``("l", [(x, y), ...])`` polilinea · ``("c", cx, cy, r)`` circulo ·
#: ``("r", x, y, w, h, radio)`` rectangulo redondeado.
ICONOS: dict[str, tuple] = {
    "rendimiento": (
        ("l", [(0.04, 0.62), (0.26, 0.62), (0.38, 0.20),
               (0.54, 0.88), (0.66, 0.46), (0.96, 0.46)]),
    ),
    "mano": (
        ("l", [(0.26, 0.48), (0.26, 0.16)]),
        ("l", [(0.42, 0.44), (0.42, 0.06)]),
        ("l", [(0.58, 0.44), (0.58, 0.12)]),
        ("l", [(0.72, 0.50), (0.72, 0.24)]),
        ("l", [(0.13, 0.58), (0.21, 0.44)]),
        ("l", [(0.13, 0.58), (0.15, 0.78), (0.30, 0.93), (0.56, 0.94),
               (0.73, 0.81), (0.78, 0.60), (0.78, 0.48)]),
    ),
    "gestos": (
        ("l", [(0.09, 0.20), (0.33, 0.46), (0.09, 0.72)]),
        ("l", [(0.91, 0.20), (0.67, 0.46), (0.91, 0.72)]),
        ("c", 0.50, 0.46, 0.095),
    ),
    "seguridad": (
        ("l", [(0.50, 0.05), (0.86, 0.21), (0.86, 0.52),
               (0.50, 0.95), (0.14, 0.52), (0.14, 0.21), (0.50, 0.05)]),
    ),
    "enlace": (
        ("r", 0.30, 0.05, 0.40, 0.90, 0.10),
        ("l", [(0.44, 0.82), (0.56, 0.82)]),
        ("l", [(0.44, 0.18), (0.56, 0.18)]),
    ),
    "novedad": (
        ("c", 0.50, 0.50, 0.40),
        ("l", [(0.50, 0.44), (0.50, 0.72)]),
        ("c", 0.50, 0.30, 0.035),
    ),
    "analisis": (
        ("l", [(0.13, 0.90), (0.13, 0.52)]),
        ("l", [(0.38, 0.90), (0.38, 0.20)]),
        ("l", [(0.62, 0.90), (0.62, 0.64)]),
        ("l", [(0.87, 0.90), (0.87, 0.38)]),
    ),
    # -- barra inferior ----------------------------------------------------
    "nav-mosaico": (
        ("r", 0.08, 0.08, 0.42, 0.42, 0.10),
        ("r", 0.58, 0.08, 0.34, 0.42, 0.10),
        ("r", 0.08, 0.58, 0.34, 0.34, 0.10),
        ("r", 0.50, 0.58, 0.42, 0.34, 0.10),
    ),
    "nav-camara": (
        ("l", [(0.28, 0.24), (0.36, 0.10), (0.64, 0.10), (0.72, 0.24)]),
        ("r", 0.06, 0.24, 0.88, 0.66, 0.14),
        ("c", 0.50, 0.57, 0.17),
    ),
    "nav-gestos": (
        ("l", [(0.09, 0.20), (0.33, 0.46), (0.09, 0.72)]),
        ("l", [(0.91, 0.20), (0.67, 0.46), (0.91, 0.72)]),
        ("c", 0.50, 0.46, 0.095),
    ),
    "nav-ajustes": (
        ("l", [(0.08, 0.32), (0.92, 0.32)]),
        ("c", 0.36, 0.32, 0.105),
        ("l", [(0.08, 0.72), (0.92, 0.72)]),
        ("c", 0.64, 0.72, 0.105),
    ),
    "nav-registro": (
        ("l", [(0.10, 0.26), (0.90, 0.26)]),
        ("l", [(0.10, 0.50), (0.90, 0.50)]),
        ("l", [(0.10, 0.74), (0.66, 0.74)]),
    ),
    # -- catalogo de gestos -------------------------------------------------
    "puntero": (
        ("l", [(0.30, 0.08), (0.30, 0.78), (0.46, 0.63),
               (0.58, 0.92), (0.70, 0.86), (0.58, 0.58), (0.78, 0.55),
               (0.30, 0.08)]),
    ),
    "clic": (
        ("c", 0.50, 0.56, 0.24),
        ("l", [(0.50, 0.06), (0.50, 0.22)]),
        ("l", [(0.16, 0.20), (0.26, 0.32)]),
        ("l", [(0.84, 0.20), (0.74, 0.32)]),
    ),
    "doble": (
        ("c", 0.36, 0.56, 0.20),
        ("c", 0.68, 0.56, 0.20),
        ("l", [(0.36, 0.10), (0.36, 0.26)]),
        ("l", [(0.68, 0.10), (0.68, 0.26)]),
    ),
    "derecho": (
        ("l", [(0.10, 0.72), (0.42, 0.40)]),
        ("l", [(0.42, 0.40), (0.90, 0.28)]),
        ("l", [(0.74, 0.16), (0.90, 0.28), (0.78, 0.44)]),
    ),
    "scroll": (
        ("r", 0.30, 0.06, 0.40, 0.88, 0.20),
        ("l", [(0.50, 0.24), (0.50, 0.42)]),
        ("l", [(0.40, 0.68), (0.50, 0.80), (0.60, 0.68)]),
    ),
    "hscroll": (
        ("l", [(0.06, 0.50), (0.94, 0.50)]),
        ("l", [(0.20, 0.36), (0.06, 0.50), (0.20, 0.64)]),
        ("l", [(0.80, 0.36), (0.94, 0.50), (0.80, 0.64)]),
    ),
    "arrastrar": (
        ("r", 0.08, 0.22, 0.50, 0.50, 0.12),
        ("l", [(0.46, 0.60), (0.90, 0.60)]),
        ("l", [(0.76, 0.48), (0.90, 0.60), (0.76, 0.72)]),
    ),
    "zoom": (
        ("c", 0.42, 0.42, 0.30),
        ("l", [(0.64, 0.64), (0.92, 0.92)]),
        ("l", [(0.28, 0.42), (0.56, 0.42)]),
        ("l", [(0.42, 0.28), (0.42, 0.56)]),
    ),
    "ventana": (
        ("r", 0.06, 0.16, 0.88, 0.68, 0.10),
        ("l", [(0.06, 0.36), (0.94, 0.36)]),
        ("l", [(0.40, 0.60), (0.60, 0.60)]),
    ),
    "redimensionar": (
        ("r", 0.06, 0.06, 0.60, 0.60, 0.10),
        ("l", [(0.44, 0.94), (0.94, 0.44)]),
        ("l", [(0.70, 0.94), (0.94, 0.70)]),
    ),
    "teclado": (
        ("r", 0.04, 0.26, 0.92, 0.48, 0.10),
        ("l", [(0.20, 0.42), (0.80, 0.42)]),
        ("l", [(0.32, 0.60), (0.68, 0.60)]),
    ),
    "pausa": (
        ("c", 0.50, 0.50, 0.42),
        ("l", [(0.40, 0.34), (0.40, 0.66)]),
        ("l", [(0.60, 0.34), (0.60, 0.66)]),
    ),
}


def _pt(caja: QRectF, x: float, y: float) -> QPointF:
    return QPointF(caja.left() + caja.width() * x, caja.top() + caja.height() * y)


def icono(p: QPainter, caja: QRectF, nombre: str, color: str,
          grosor: float = GROSOR_ICONO, alpha: float = 1.0) -> None:
    """Pinta un icono de linea fina inscrito en ``caja``.

    Se dibuja con un solo ``QPainterPath`` y una sola pluma: cada primitiva
    suelta con su propio ``drawLine`` costaba tres veces mas en la pagina de
    gestos, que llega a tener doce iconos a la vista.
    """
    piezas = ICONOS.get(nombre)
    if not piezas or caja.isEmpty():
        return
    camino = QPainterPath()
    for prim in piezas:
        if prim[0] == "l":
            puntos = prim[1]
            camino.moveTo(_pt(caja, *puntos[0]))
            for u in puntos[1:]:
                camino.lineTo(_pt(caja, *u))
        elif prim[0] == "c":
            _o, cx, cy, r = prim
            centro = _pt(caja, cx, cy)
            rx, ry = caja.width() * r, caja.height() * r
            camino.addEllipse(centro, rx, ry)
        elif prim[0] == "r":
            _o, x, y, w, h, rad = prim
            caja_r = QRectF(caja.left() + caja.width() * x,
                            caja.top() + caja.height() * y,
                            caja.width() * w, caja.height() * h)
            camino.addRoundedRect(caja_r, caja.width() * rad, caja.height() * rad)
    tinta = QColor(color)
    tinta.setAlphaF(tinta.alphaF() * max(0.0, min(1.0, alpha)))
    pluma = QPen(tinta, grosor)
    pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
    pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(pluma)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(camino)
    p.restore()


def reloj(segundos: float) -> str:
    """``h:mm:ss`` o ``m:ss``. Es como se lee un tiempo de sesion, no en ms."""
    s = max(0, int(segundos))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# --------------------------------------------------------------------------- #
# bases de pagina
# --------------------------------------------------------------------------- #

class Pagina(ThemeAware, Beating, QWidget):
    """Una pagina del panel: ocupa la ventana y coloca dentro de ``area``.

    Ocupar la ventana entera y no el area del mosaico no es un descuido: es lo
    que deja sitio a las sombras de las laminas pegadas al borde del area. La
    pagina se declara transparente al raton, asi que la columna viva que queda
    por debajo sigue recibiendo sus clics; sus propios hijos, no.
    """

    #: Lo que la barra inferior escribe como titulo de la pagina.
    TITULO = ""

    #: Si la pagina quiere el margen de 32 del apartado 3.4 en vez del de 0
    #: (el mosaico llena su area entera; las paginas profundas respiran).
    MARGEN = MARGEN_PAGINA

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.area = QRectF()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    # -- geometria ----------------------------------------------------------
    def set_area(self, area: QRectF) -> None:
        """El area del mosaico dentro de la ventana. La fija el armazon."""
        if area == self.area:
            return
        self.area = QRectF(area)
        self.colocar()

    def caja(self) -> QRectF:
        """El area menos el margen de la pagina: donde va el contenido."""
        m = self.MARGEN
        r = QRectF(self.area).adjusted(m, m, -m, -m)
        return r if r.width() > 40.0 and r.height() > 40.0 else QRectF(self.area)

    def colocar(self) -> None:
        """Gancho: reparte los hijos. Se llama al cambiar el area o el tamano."""

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        self.colocar()

    # -- ciclo --------------------------------------------------------------
    def al_entrar(self) -> None:
        """La pagina pasa a estar delante."""

    def al_salir(self) -> None:
        """La pagina deja de estar delante. Obligatorio soltar lo caro aqui."""

    # -- datos --------------------------------------------------------------
    # El armazon reparte a ciegas: llama a los tres en la pagina que esta
    # delante y en ninguna otra. Estan aqui vacios para que una pagina que solo
    # quiere fotogramas no tenga que escribir los otros dos.
    def on_output(self, out) -> None:
        """Un ``EngineOutput``. Llega a 60 Hz: aqui no se hace nada caro."""

    def on_stats(self, stats: dict) -> None:
        """Un ``stats_ready``. Llega a ~4 Hz."""

    def on_frame(self, frame, estado) -> None:
        """Un ``frame_ready``: imagen BGR y ``FrameState``."""

    def on_theme(self) -> None:
        self.colocar()
        self.update()


class PaginaDesplazable(Pagina):
    """Pagina con desplazamiento vertical propio y recorte al area.

    El contenido no cabe (la de analisis mide mas de 1300 px de alto), asi que
    los hijos viven dentro de ``marco``, un widget colocado exactamente en el
    area que **si** recorta. Es lo que separa esta base de ``Pagina``: aqui el
    recorte se quiere, porque una lamina desplazada hacia arriba no puede
    pintarse encima de la columna viva.
    """

    #: Ancho de la barrita de posicion. No es un ``QScrollBar``: es una marca
    #: de 3 px que aparece al desplazar y se desvanece sola.
    BARRA_W = 3.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.marco = _Marco(self)
        self._off = 0.0
        self._alto = 0.0
        self._visible = Progresion(0.0, motion.MICRO_OUT, motion.EASE_GLASS)
        self._quieto = 0.0

    # -- API para las subclases ---------------------------------------------
    def contenido(self) -> QRectF:
        """La caja donde se colocan los hijos, ya con el desplazamiento puesto.

        Va en coordenadas de ``marco``, que es donde viven los hijos.
        """
        m = self.MARGEN
        return QRectF(m, m - self._off,
                      max(40.0, self.area.width() - 2.0 * m), 0.0)

    def set_alto(self, alto: float) -> None:
        """Alto real del contenido. Fija hasta donde se puede desplazar."""
        self._alto = max(0.0, float(alto))
        self._clamp()

    @property
    def desplazamiento(self) -> float:
        return self._off

    def _max_off(self) -> float:
        return max(0.0, self._alto - self.area.height())

    def _clamp(self) -> None:
        self._off = max(0.0, min(self._max_off(), self._off))

    # -- geometria ----------------------------------------------------------
    def set_area(self, area: QRectF) -> None:
        super().set_area(area)
        self.marco.setGeometry(QRectF(area).toRect())
        self._clamp()

    def colocar(self) -> None:
        self.marco.setGeometry(QRectF(self.area).toRect())

    # -- desplazamiento -----------------------------------------------------
    def wheelEvent(self, event) -> None:                    # noqa: N802
        if self._max_off() <= 0.0:
            event.ignore()
            return
        paso = event.angleDelta().y() / 120.0 * 68.0
        antes = self._off
        self._off -= paso
        self._clamp()
        if abs(self._off - antes) > 0.01:
            self._visible.jump(1.0)
            self._quieto = 0.0
            self.animate()
            self.colocar()
            self.marco.update()
            self.update()
        event.accept()

    def tick(self, dt: float) -> bool:
        self._quieto += dt
        if self._quieto < 0.9:
            return True
        self._visible.set(0.0)
        vivo = self._visible.step(dt)
        self.update()
        return vivo

    def al_salir(self) -> None:
        super().al_salir()
        self.rest()

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, event) -> None:                    # noqa: N802
        k = self._visible.value
        tope = self._max_off()
        if k <= 0.01 or tope <= 0.0 or self.area.isEmpty():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pista = QRectF(self.area.right() - 10.0, self.area.top() + 8.0,
                       self.BARRA_W, self.area.height() - 16.0)
        frac = self.area.height() / max(1.0, self._alto)
        alto = max(36.0, pista.height() * frac)
        y = pista.top() + (pista.height() - alto) * (self._off / tope)
        color = QColor(theme.C.ink.tertiary)
        color.setAlphaF(0.55 * k)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(pista.left(), y, pista.width(), alto),
                          self.BARRA_W / 2.0, self.BARRA_W / 2.0)
        p.end()


class _Marco(QWidget):
    """El recorte de una pagina desplazable. No pinta: solo recorta a sus hijos."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)


# --------------------------------------------------------------------------- #
# filas
# --------------------------------------------------------------------------- #

class FilaCompacta(ThemeAware, QWidget):
    """Fila de 40 px: etiqueta a la izquierda, cifra tabular a la derecha.

    Es la fila de SESION (apartado 8.1, A3). No es interactiva y no late: la
    cifra la escribe quien la tiene cuando le llega el dato, sin interpolar,
    porque un contador acumulado que rueda hacia atras al reiniciarse se lee
    como un fallo.
    """

    ALTO = 36

    def __init__(self, etiqueta: str, parent: QWidget | None = None, *,
                 valor: str = "—", nota: str = "") -> None:
        super().__init__(parent)
        self._etiqueta = etiqueta
        self._valor = valor
        self._nota = nota
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(self.ALTO)

    def set_valor(self, valor: str) -> None:
        if valor != self._valor:
            self._valor = valor
            self.update()

    def paintEvent(self, event) -> None:                    # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = theme.C
        r = QRectF(self.rect())
        ancho = r.width() * 0.62
        if self._nota:
            # El principio 4 obliga a que toda metrica derivada diga como se
            # calcula. Con nota, la etiqueta sube y la cuenta va debajo en
            # 11 px; sin ella, la etiqueta se queda centrada y no sobra hueco.
            texto(p, QRectF(r.left(), r.top() + 3.0, ancho, 16.0),
                  "caption", self._etiqueta, t.ink.secondary)
            p.setFont(tipo.font("caption", size=11))
            p.setPen(QColor(t.ink.quiet))
            p.drawText(QRectF(r.left(), r.top() + 19.0, ancho, 13.0),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter), self._nota)
        else:
            texto(p, QRectF(r.left(), r.top(), ancho, r.height()),
                  "caption", self._etiqueta, t.ink.secondary)
        texto(p, r, "body-fuerte", self._valor, t.ink.primary,
              Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        p.end()


class FilaFantasma(ThemeAware, Beating, QWidget):
    """Fila de atajo sin fondo (apartado 8.1, A4).

    Sin lamina y sin borde: solo el rotulo, su icono y un lavado que crece al
    pasar por encima. Es el nivel mas bajo de la jerarquia -abre otra ventana,
    no cambia el estado- y por eso no se le da una caja.
    """

    ALTO = 38
    pulsada = Signal()

    def __init__(self, etiqueta: str, glifo: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._etiqueta = etiqueta
        self._glifo = glifo
        self._hover = motion.Smooth(0.0, 0.10)
        self.setFixedHeight(self.ALTO)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def tick(self, dt: float) -> bool:
        self._hover.step()
        self.update()
        return not self._hover.settled

    def event(self, e) -> bool:
        if e.type() == e.Type.HoverEnter:
            self._hover.set(1.0)
            self.animate()
        elif e.type() == e.Type.HoverLeave:
            self._hover.set(0.0)
            self.animate()
        return super().event(e)

    def mouseReleaseEvent(self, e) -> None:                 # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.pos()):
            self.pulsada.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, event) -> None:                    # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = theme.C
        k = max(0.0, min(1.0, self._hover.value))
        r = QRectF(self.rect())
        if k > 0.005:
            lavado = QColor(t.tokens.glass.raised.ink.hex)
            lavado.setAlphaF(t.tokens.glass.raised.ink.alpha * k)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(lavado)
            p.drawRoundedRect(r, R_SM, R_SM)
        if self._glifo:
            icono(p, QRectF(r.left() + 10.0, r.center().y() - 8.0, 16.0, 16.0),
                  self._glifo, t.ink.secondary)
        texto(p, QRectF(r.left() + 36.0, r.top(), r.width() - 60.0, r.height()),
              "body", self._etiqueta,
              theme.mix(t.ink.secondary, t.ink.primary, k))
        # el chevron viaja 3 px al pasar por encima: dice "aqui se sale"
        cx = r.right() - 16.0 + 3.0 * k
        pluma = QPen(QColor(t.ink.tertiary), GROSOR_ICONO)
        pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
        pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cy = r.center().y()
        camino = QPainterPath(QPointF(cx - 3.0, cy - 4.0))
        camino.lineTo(QPointF(cx + 1.0, cy))
        camino.lineTo(QPointF(cx - 3.0, cy + 4.0))
        p.drawPath(camino)
        p.end()
