"""Zona A: la COLUMNA VIVA de 320 px (apartado 8.1).

No es navegacion: es estado. No se mueve al cambiar de pagina y no lleva a
ninguna otra pantalla salvo por los tres atajos del final, que abren ventanas
aparte. Esa es toda la diferencia con el rail lateral que sustituye, y es la
que hace que el panel deje de parecer un cuadro de mando generico: lo que esta
fijo a la izquierda es *lo que esta pasando*, no *donde estas*.

Cuatro bloques:

* **A1 identidad** — la marca dibujada a mano (dos circulos de vidrio solapados
  con un arco especular), el nombre y el chip de version.
* **A2 NUCLEO (E3)** — el unico mando importante de la aplicacion. El boton
  redondo **es** ``btn_engine`` y el interruptor **es** ``control_toggle``: los
  dos contratos de ``app.py`` viven aqui y no en una copia. Debajo, siempre
  visible, la linea de escape que escribe ``_refresh_control_hint()``.
* **A3 SESION (E2)** — cuatro filas con lo que solo se sabe acumulando.
* **A4 ATAJOS** — filas fantasma que llaman a ``open_calibration`` y
  ``open_wizard``, que siguen siendo atributos asignables del panel.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from ...version import __version__
from .. import motion, theme, tipo
from ..kit.base import Beating, Sheet, ThemeAware
from ..kit.controls import Toggle
from ..tokens import GAP_SAME, LIVE_COLUMN_W, R_LG, SHEET_PADDING
from .comun import FilaCompacta, FilaFantasma, texto

__all__ = ["ColumnaViva", "BotonMotor", "Nucleo", "Marca", "Panel"]

#: Diametro del boton redondo del Nucleo (apartado 8.1, A2).
BOTON_D = 72.0

#: Respiracion del anillo mientras el motor corre: alfa 0.24 a 0.40 en 3,2 s.
ANILLO_LO, ANILLO_HI = 0.24, 0.40

#: Grosor del anillo de arranque alrededor del boton.
ANILLO_GROSOR = 3.0

#: Lo que se tarda en dar por arrancado el motor si nadie dice lo contrario. El
#: anillo no miente: se rellena mientras ``ctl.running`` es cierto pero todavia
#: no ha llegado ni un fotograma, y se completa de golpe con el primero.
ARRANQUE_S = 2.6

#: Alto de la cabecera de identidad (A1).
ALTO_IDENTIDAD = 56.0


class Marca(ThemeAware, Beating, QWidget):
    """La marca de AirTouch dibujada a mano: dos circulos y un arco especular.

    No es un PNG ni un glifo de una fuente. Dos circulos de vidrio solapados
    -uno de vidrio alzado, otro relleno de acento a alfa baja- con un arco de
    luz que recorre el de delante. Es la misma gramatica que el resto del
    sistema, y a 32 px una imagen rasterizada se veria sucia en cualquier DPI
    que no fuese el suyo.
    """

    BEAT_HZ = motion.HZ_GLOW
    LADO = 32

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fase = 0.0
        self.setFixedSize(self.LADO, self.LADO)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.animate()

    def tick(self, dt: float) -> bool:
        self._fase = (self._fase + dt / 6.4) % 1.0
        self.update()
        return True

    def paintEvent(self, event) -> None:                    # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = theme.C
        r = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        radio = r.width() * 0.33

        atras = QPointF(r.left() + radio * 1.05, r.center().y() + radio * 0.34)
        p.setPen(QPen(QColor(t.tokens.edge.dominant.over(t.surface)), 1.0))
        p.setBrush(QColor(t.tokens.glass.raised.solid))
        p.drawEllipse(atras, radio, radio)

        frente = QPointF(r.right() - radio * 1.05, r.center().y() - radio * 0.34)
        relleno = QRadialGradient(frente + QPointF(-radio * 0.3, -radio * 0.3),
                                  radio * 1.8)
        c1 = QColor(t.color.accent)
        c1.setAlphaF(0.44 if t.dark else 0.28)
        c2 = QColor(t.color.accent)
        c2.setAlphaF(0.14 if t.dark else 0.09)
        relleno.setColorAt(0.0, c1)
        relleno.setColorAt(1.0, c2)
        p.setBrush(relleno)
        p.setPen(QPen(QColor(t.color.accent), 1.2))
        p.drawEllipse(frente, radio, radio)

        # el arco especular recorre el borde del circulo de delante
        k = self._fase
        caja = QRectF(frente.x() - radio, frente.y() - radio, radio * 2, radio * 2)
        luz = QColor("#FFFFFF" if t.dark else t.ink.primary)
        luz.setAlphaF((0.60 if t.dark else 0.34)
                      * (0.30 + 0.70 * math.sin(math.pi * k)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(luz, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(caja, int((-60.0 - 240.0 * k) * 16), int(-108 * 16))
        p.end()


class BotonMotor(ThemeAware, Beating, QWidget):
    """El boton redondo de 72 px del Nucleo. **Es** ``btn_engine`` (8.9).

    Cumple el contrato con ``.setText(str)`` y lo usa de verdad: el rotulo que
    ``app.py`` escribe ("Iniciar motor" / "Detener motor") es el que anuncia el
    boton al pasar por encima y a las ayudas de accesibilidad. Dentro de un
    circulo de 72 px no cabe un rotulo de catorce caracteres sin romper la
    escala tipografica, y el estado ya se dice a su derecha en ``h2``.

    El anillo hace dos cosas y nunca las dos a la vez: se **rellena** mientras
    el motor arranca y **respira** (alfa 0.24 a 0.40 en 3,2 s, refrescado a
    20 Hz) mientras corre.
    """

    BEAT_HZ = motion.HZ_GLOW

    pulsado = Signal()

    #: Holgura para el anillo. Es la misma cuenta que la reserva de sombra de
    #: una lamina: Qt recorta al rectangulo del widget y un anillo pintado en el
    #: borde sale con un canto recto.
    HOLGURA = ANILLO_GROSOR * 2.0 + 5.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._texto = "Iniciar motor"
        self._corriendo = False
        self._arranque = 0.0
        self._fase = 0.0
        self._hover = motion.Smooth(0.0, 0.10)
        self._press = motion.Smooth(0.0, 0.06)
        self._color = motion.Smooth(0.0, motion.TAU_MODE_COLOR)
        lado = int(BOTON_D + 2.0 * self.HOLGURA)
        self.setFixedSize(lado, lado)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(self._texto)
        self.setAccessibleName(self._texto)

    # -- contrato de app.py -------------------------------------------------
    def setText(self, value: str) -> None:                  # noqa: N802
        if value == self._texto:
            return
        self._texto = value
        self.setToolTip(value)
        self.setAccessibleName(value)
        self.update()

    def text(self) -> str:
        return self._texto

    # -- estado -------------------------------------------------------------
    def set_running(self, value: bool) -> None:
        value = bool(value)
        if value == self._corriendo:
            return
        self._corriendo = value
        self._color.set(1.0 if value else 0.0)
        if value:
            self._arranque = 0.0
        self.animate()

    def marcar_listo(self) -> None:
        """Ha llegado el primer fotograma: el anillo de arranque se completa."""
        if self._corriendo and self._arranque < 1.0:
            self._arranque = 1.0
            self.update()

    @property
    def arranque(self) -> float:
        return self._arranque

    # -- latido -------------------------------------------------------------
    def tick(self, dt: float) -> bool:
        self._hover.step()
        self._press.step()
        self._color.step()
        vivo = not (self._hover.settled and self._press.settled
                    and self._color.settled)
        if self._corriendo:
            self._fase = (self._fase + dt * 1000.0 / motion.BREATH) % 1.0
            if self._arranque < 1.0:
                self._arranque = min(1.0, self._arranque + dt / ARRANQUE_S)
            vivo = True
        self.update()
        return vivo

    # -- eventos ------------------------------------------------------------
    def event(self, e) -> bool:
        if e.type() == e.Type.HoverEnter:
            self._hover.set(1.0)
            self.animate()
        elif e.type() == e.Type.HoverLeave:
            self._hover.set(0.0)
            self.animate()
        return super().event(e)

    def mousePressEvent(self, e) -> None:                   # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press.set(1.0)
            self.animate()

    def mouseReleaseEvent(self, e) -> None:                 # noqa: N802
        self._press.set(0.0)
        self.animate()
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.pos()):
            self.pulsado.emit()

    def keyPressEvent(self, e) -> None:                     # noqa: N802
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.pulsado.emit()
            return
        super().keyPressEvent(e)

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, event) -> None:                    # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = theme.C
        centro = QRectF(self.rect()).center()
        radio = BOTON_D / 2.0 * (1.0 - 0.03 * self._press.value)
        caja = QRectF(centro.x() - radio, centro.y() - radio, radio * 2, radio * 2)

        k = max(0.0, min(1.0, self._color.value))
        relleno = QColor(theme.mix(t.tokens.glass.raised.solid, t.color.accent, k))
        if self._hover.value > 0.0:
            relleno = QColor(theme.mix(
                relleno.name(), "#FFFFFF" if t.dark else t.ink.primary,
                0.10 * self._hover.value))

        # sombra propia no: la lamina E3 que hay debajo ya la pone. Aqui basta
        # el filo del apartado 4.3 para despegar el circulo del vidrio.
        p.setBrush(relleno)
        p.setPen(QPen(QColor(t.tokens.edge.dominant.over(relleno.name())), 1.0))
        p.drawEllipse(caja)

        # el simbolo de encendido: arco abierto arriba y trazo vertical
        tinta = QColor(t.primary_text if k > 0.5 else t.ink.primary)
        p.setPen(QPen(tinta, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        rr = radio * 0.42
        p.drawArc(QRectF(centro.x() - rr, centro.y() - rr + 2.0, rr * 2, rr * 2),
                  int(-245 * 16), int(310 * 16))
        p.drawLine(QPointF(centro.x(), centro.y() - rr - 2.0),
                   QPointF(centro.x(), centro.y() + 1.0))

        # el anillo: se rellena al arrancar y respira mientras corre
        anillo = QRectF(caja).adjusted(-ANILLO_GROSOR - 2.0, -ANILLO_GROSOR - 2.0,
                                       ANILLO_GROSOR + 2.0, ANILLO_GROSOR + 2.0)
        if self._corriendo:
            color = QColor(t.color.accent)
            if self._arranque >= 1.0:
                color.setAlphaF(ANILLO_LO + (ANILLO_HI - ANILLO_LO) * (
                    0.5 - 0.5 * math.cos(2.0 * math.pi * self._fase)))
                p.setPen(QPen(color, ANILLO_GROSOR))
                p.drawEllipse(anillo)
            else:
                pista = QColor(t.color.accent)
                pista.setAlphaF(0.12)
                p.setPen(QPen(pista, ANILLO_GROSOR))
                p.drawEllipse(anillo)
                color.setAlphaF(0.85)
                p.setPen(QPen(color, ANILLO_GROSOR, Qt.PenStyle.SolidLine,
                              Qt.PenCapStyle.RoundCap))
                p.drawArc(anillo, 90 * 16, int(-360 * 16 * self._arranque))

        if self.hasFocus():
            foco = QColor(t.color.accent)
            foco.setAlphaF(0.55)
            p.setPen(QPen(foco, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(anillo).adjusted(-2.5, -2.5, 2.5, 2.5))
        p.end()


class Panel(Sheet):
    """Lamina con un rotulo de seccion en ``overline`` dentro.

    El rotulo se pinta **dentro** de la lamina y no encima de ella desde el
    padre: Qt pinta a los hijos despues del padre, asi que un titulo dibujado
    por la columna quedaria tapado por la propia lamina.
    """

    def __init__(self, titulo: str, parent: QWidget | None = None, *,
                 elevation: str = "E2") -> None:
        super().__init__(parent, elevation=elevation, radius=R_LG,
                         padding=SHEET_PADDING)
        self.titulo = titulo

    #: Alto que se lleva el rotulo dentro del contenido.
    CABECERA = 22.0

    def paint_content(self, p: QPainter, rect: QRectF) -> None:
        if self.titulo:
            texto(p, QRectF(rect.left(), rect.top(), rect.width(),
                            self.CABECERA), "overline", self.titulo,
                  theme.C.ink.tertiary)


class Nucleo(Sheet):
    """A2: la lamina E3 con el boton, el estado y el interruptor de control.

    Es la unica E3 en reposo de todo el panel, y esa es toda su jerarquia: no
    hace falta un color ni un borde para decir que es lo importante de la
    pantalla, basta con que este medio milimetro por encima de lo demas.
    """

    ALTO = 168.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, elevation="E3", radius=R_LG,
                         padding=SHEET_PADDING)
        self.boton = BotonMotor(self)
        self.control = Toggle(False, self)
        self._estado = "Detenido"
        self._linea = "El motor no está en marcha"

    def set_estado(self, estado: str, linea: str) -> None:
        if estado == self._estado and linea == self._linea:
            return
        self._estado = estado
        self._linea = linea
        self.update()

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        c = self.content_rect()
        h = BotonMotor.HOLGURA
        self.boton.move(int(c.left() - h), int(c.top() - h + 2.0))
        self.control.move(int(c.left() - 4.0),
                          int(c.top() + BOTON_D + 12.0))

    def paint_content(self, p: QPainter, rect: QRectF) -> None:
        t = theme.C
        x = rect.left() + BOTON_D + 16.0
        ancho = max(40.0, rect.right() - x)
        texto(p, QRectF(x, rect.top() + 14.0, ancho, 22.0), "h2",
              self._estado, t.ink.primary)
        par = tipo.Parrafo(self._linea, "caption")
        par.set_width(ancho)
        par.draw(p, x, rect.top() + 40.0, QColor(t.ink.secondary))

        # el rotulo del interruptor, a la derecha de su propia perilla
        y = rect.top() + BOTON_D + 12.0
        tx = rect.left() + self.control.width() + 2.0
        texto(p, QRectF(tx, y, max(40.0, rect.right() - tx),
                        float(self.control.height())),
              "body-fuerte",
              "Control real" if self.control.isChecked() else "Modo seguro",
              t.ink.primary)


class ColumnaViva(ThemeAware, QWidget):
    """La columna entera. Ancho fijo de 320 px, colocada por el armazon."""

    calibrar = Signal()
    asistente = Signal()
    teclado = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(LIVE_COLUMN_W)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.marca = Marca(self)
        self.nucleo = Nucleo(self)
        self.sesion = Panel("Sesión", self)
        self.filas = [
            FilaCompacta("Tiempo activo", self.sesion, valor="0:00"),
            FilaCompacta("Gestos realizados", self.sesion, valor="0"),
            FilaCompacta("Clics emitidos", self.sesion, valor="0"),
            FilaCompacta("Recorrido del puntero", self.sesion, valor="0,0 m"),
        ]
        self.atajos = [
            FilaFantasma("Teclado virtual", "teclado", self),
            FilaFantasma("Calibrar esquinas", "nav-camara", self),
            FilaFantasma("Configuración guiada", "gestos", self),
        ]
        self.atajos[0].pulsada.connect(self.teclado.emit)
        self.atajos[1].pulsada.connect(self.calibrar.emit)
        self.atajos[2].pulsada.connect(self.asistente.emit)

        self._escape = ""

    # -- API ----------------------------------------------------------------
    @property
    def boton(self) -> BotonMotor:
        return self.nucleo.boton

    @property
    def control(self) -> Toggle:
        return self.nucleo.control

    def set_sesion(self, tiempo: str, gestos: str, clics: str,
                   recorrido: str) -> None:
        for fila, valor in zip(self.filas, (tiempo, gestos, clics, recorrido)):
            fila.set_valor(valor)

    def set_escape(self, texto_escape: str) -> None:
        """La linea de escape del apartado 8.9, siempre visible bajo A2."""
        if texto_escape != self._escape:
            self._escape = texto_escape
            self._colocar()
            self.update()

    # -- geometria ----------------------------------------------------------
    def _alto_escape(self) -> float:
        if not self._escape:
            return 0.0
        par = tipo.Parrafo(self._escape, "caption")
        par.set_width(max(40.0, self.width() - 4.0))
        return par.height() + 12.0

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        self._colocar()

    def on_theme(self) -> None:
        self._colocar()
        self.update()

    def _colocar(self) -> None:
        w = float(self.width())
        y = ALTO_IDENTIDAD + 12.0
        self.marca.move(0, int((ALTO_IDENTIDAD - Marca.LADO) / 2.0))

        self.nucleo.place(QRectF(0.0, y, w, Nucleo.ALTO))
        y += Nucleo.ALTO + self._alto_escape() + GAP_SAME

        alto = (SHEET_PADDING * 2.0 + Panel.CABECERA + 6.0
                + FilaCompacta.ALTO * len(self.filas))
        self.sesion.place(QRectF(0.0, y, w, alto))
        c = self.sesion.content_rect()
        fy = c.top() + Panel.CABECERA + 6.0
        for fila in self.filas:
            fila.setGeometry(int(c.left()), int(fy), int(c.width()),
                             FilaCompacta.ALTO)
            fy += FilaCompacta.ALTO
        y += alto + GAP_SAME

        # A4: los atajos se anclan al pie cuando sobra sitio. La columna se lee
        # entonces como una pagina y no como una pila apretada contra el techo.
        alto_atajos = 20.0 + FilaFantasma.ALTO * len(self.atajos)
        y = max(y, float(self.height()) - alto_atajos)
        self._y_atajos = y
        ay = y + 20.0
        for atajo in self.atajos:
            atajo.setGeometry(0, int(ay), int(w), FilaFantasma.ALTO)
            ay += FilaFantasma.ALTO

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, event) -> None:                    # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = theme.C
        x = Marca.LADO + 12.0
        texto(p, QRectF(x, 0.0, 160.0, ALTO_IDENTIDAD), "h2", "AirTouch",
              t.ink.primary)

        # el chip de version: pildora de filo, sin relleno de color. Es un dato,
        # no un estado, y el color significa (principio 3)
        etiqueta = tipo.text("overline", __version__)
        m = tipo.metrics("overline")
        caja = QRectF(x + tipo.metrics("h2").horizontalAdvance("AirTouch") + 12.0,
                      ALTO_IDENTIDAD / 2.0 - 9.0,
                      m.horizontalAdvance(etiqueta) + 18.0, 18.0)
        p.setPen(QPen(QColor(t.tokens.edge.dominant.over(t.bg)), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(caja, 9.0, 9.0)
        texto(p, caja, "overline", __version__, t.ink.tertiary,
              Qt.AlignmentFlag.AlignCenter)

        # la linea de escape, entre el Nucleo y SESION
        if self._escape:
            y = self.nucleo.y() + self.nucleo.height() \
                - self.nucleo.reserve().bottom() + 8.0
            par = tipo.Parrafo(self._escape, "caption")
            par.set_width(max(40.0, self.width() - 4.0))
            par.draw(p, 2.0, y, QColor(t.ink.tertiary))

        texto(p, QRectF(0.0, self._y_atajos, float(self.width()), 16.0),
              "overline", "Atajos", t.ink.tertiary)
        p.end()
