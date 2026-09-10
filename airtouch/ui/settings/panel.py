"""Ajustes 2.0: dos paneles, buscador en vivo y pie de consecuencia (8.7).

La version 1.0 era una columna de tarjetas con veinte mandos puestos en el
orden en que se fueron escribiendo. Encontrar algo era leerlo todo. Esto es lo
que cambia, y por que:

* **Dos paneles.** Lista de secciones de 200 px a la izquierda y contenido a la
  derecha. La lista dice de un vistazo cuantas cosas has cambiado en cada sitio
  -el punto de acento- y, mientras buscas, cuantas coincidencias hay en cada
  seccion, para que no tengas que entrar a mirar.
* **Buscador que filtra filas, no secciones.** Cada fila lleva palabras clave
  (y su propia ruta de configuracion), asi que "raton" encuentra el suavizado
  del puntero y "filter.beta" encuentra la reactividad. Lo que no casa se funde
  en 120 ms y **encoge su hueco a la vez**, para que las filas de abajo suban
  en el mismo movimiento en vez de dar un salto. Un grupo sin filas visibles
  desaparece entero, rotulo e instrumento incluidos.
* **El instrumento va anclado arriba del grupo.** El osciloscopio del pinch y
  el medidor del puntero (``instrumentos.py``) viven dentro del grupo al que
  pertenecen, y el panel se asegura de traerlos a la pantalla en cuanto tocas
  un mando de ese grupo: la especificacion pide que veas la regla moverse bajo
  tu dedo, y eso solo vale si la regla esta a la vista.
* **Cada seccion termina diciendo que vas a notar tu**, no que hace el
  parametro. Las frases estan en ``sections.py``, junto a los ajustes que
  explican.

Cuatro decisiones de implementacion que conviene entender antes de tocar nada:

* **Todo se construye al abrir el panel, las ocho secciones.** Son unas noventa
  filas; construirlas cuesta una vez y a cambio ``refresh_from_config()`` -que
  es contrato con ``app.py``- no tiene que adivinar que secciones existen ya.
  Una vista que no se ve no pinta, no anima y sus mandos se dan de baja del
  latido solos (``Beating.hideEvent``).
* **Un solo latido para todo el panel.** El panel es el unico participante del
  ``Beat``: reparte el paso a la vista visible, que mueve los fundidos del
  buscador y el desplazamiento. Ningun ``QTimer``, ninguna animacion propia en
  las filas.
* **El fundido de una fila se hace con ``QGraphicsOpacityEffect``.** Es la
  unica forma de bajarle la opacidad a un widget entero -y a su mando- sin
  reescribirle el ``paintEvent``. El efecto se apaga en cuanto el fundido
  termina, porque un efecto activo obliga a Qt a pintar el widget en un pixmap
  aparte y eso solo se paga mientras dure.
* **Los deslizadores van sin burbuja dentro de una fila.** ``Slider`` reserva
  44 px por encima del canal para la burbuja, y dentro de una ``SettingRow`` el
  mando se centra en vertical: con la burbuja puesta, el canal cae 22 px por
  debajo del rotulo y la fila se lee torcida. Es la misma composicion que
  ensenya ``tools/galeria.py`` para una fila de ajustes. El valor sigue a la
  derecha en ``mono`` tabular y las diez subdivisiones siguen apareciendo al
  arrastrar.

**Los dos numeros con historia** (``filter.beta`` y
``gestures.click_max_travel_px``) llevan su medida escrita en la pista de su
fila y la explicacion entera en el pie de su seccion. No se redondean ni se les
cambia el rango: el beta se realimenta porque el ruido se parece a la
velocidad, y el recorrido del clic es lo unico que impide que un clic se
convierta en scroll.
"""
from __future__ import annotations

import math
import secrets
from collections import deque
from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGraphicsOpacityEffect, QSizePolicy, QWidget

from ...config import Config
from ...gestures.events import Mode
from .. import glass, motion, theme, tipo
from ..kit.base import Beating, Sheet, ThemeAware
from ..kit.controls import (RING, Button, Field, Phase, Segmented, SettingRow,
                            Slider, Toggle)
from ..tokens import (GAP_SAME, GROUP_GAP, ROW_GAP, ROW_HEIGHT_COMPACT,
                      SETTINGS_LIST_W, SHEET_PADDING_LARGE, WINDOW_MARGIN)
from .instrumentos import MedidorPuntero, Osciloscopio
from .sections import SECCIONES, Espec, Seccion, coherencia

__all__ = ["SettingsPanel"]

#: Fundido del buscador (8.7). Es corto a proposito: escribir en el campo
#: dispara uno por pulsacion, y con 200 ms se pisan entre si.
FUNDIDO_MS = 120

#: Alto de un item de la lista de secciones: la fila de lista compacta (3.4).
ALTO_ITEM = ROW_HEIGHT_COMPACT

#: Carril reservado a la barra de posicion, a la derecha del contenido. La
#: barra se pinta en la lamina y las filas viven dentro del marco, que es mas
#: estrecho: asi ninguna fila pasa por debajo de la barra.
CARRIL = 14
BARRA_W = 3.0

#: Cuanto desplaza una muesca de rueda. Es el mismo de las paginas profundas.
PASO_RUEDA = 68.0

#: Alto de la cabecera del panel derecho: titulo de seccion y boton fantasma.
ALTO_CABECERA = 44

#: Muestras de puntero con las que se mide el temblor, y minimo para ensenyarlo.
#: Son los de ``telemetry.py`` (``MIN_TREMOR`` y la ventana de 300 puntos): el
#: medidor tiene que decir el mismo numero que la pagina de analisis.
TEMBLOR_N = 300
TEMBLOR_MIN = 60

#: Cada cuantas salidas del motor se rehace la media del temblor. A 60 Hz son
#: unas siete veces por segundo, de sobra para un numero que se mueve despacio.
PASO_TEMBLOR = 8


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #

def _formato(esp: Espec) -> Callable[[float], str]:
    """Readout del deslizador: coma decimal y unidad pegada.

    Con coma porque el resto de la interfaz esta en espanyol y un "0.34" en
    medio de una frase con comas canta. ``Slider`` mide el ancho del readout
    con este mismo formato aplicado a los extremos, asi que el canal no cambia
    de largo mientras arrastras.
    """
    dec, unidad = esp.decimales, esp.unidad

    def fmt(v: float) -> str:
        if dec <= 0:
            return f"{v:.0f}{unidad}"
        return f"{v:.{dec}f}".replace(".", ",") + unidad

    return fmt


def _opacidad(w: QWidget, k: float) -> None:
    """Deja el widget al ``k`` de opacidad, y lo esconde del todo en 0.

    El efecto se crea la primera vez que hace falta y se desactiva -no se
    destruye- al terminar el fundido: crearlo y tirarlo en cada pulsacion del
    buscador seria basura para el recolector cada 16 ms.
    """
    if k <= 0.001:
        if not w.isHidden():
            w.hide()
        return
    if w.isHidden():
        w.show()
    eff = w.graphicsEffect()
    if k >= 0.999:
        if eff is not None and eff.isEnabled():
            eff.setEnabled(False)
        return
    if eff is None:
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
    eff.setEnabled(True)
    eff.setOpacity(max(0.0, min(1.0, k)))


def _texto(p: QPainter, caja: QRectF, rol: str, valor: str, color: str,
           alineacion: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft) -> None:
    """Una linea de texto con la fuente de ``tipo.py`` y nada mas."""
    p.setFont(tipo.font(rol))
    p.setPen(QColor(color))
    p.drawText(caja, int(alineacion | Qt.AlignmentFlag.AlignVCenter),
               tipo.text(rol, valor))


# --------------------------------------------------------------------------- #
# panel izquierdo: la lista de secciones
# --------------------------------------------------------------------------- #

class _Lista(Sheet):
    """Las ocho secciones, con lo que has cambiado y lo que el buscador ve.

    No es una lista de Qt: son ocho rectangulos pintados. Un ``QListWidget``
    traeria su propio delegado, su propio fondo opaco y su propia tipografia, y
    habria que pelearse con los tres para que se pareciese a esto.
    """

    seleccionada = Signal(int)

    def __init__(self, secciones: tuple[Seccion, ...],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent, padding=12)
        self._secciones = secciones
        self._indice = 0
        self._sobre = -1
        self._modificados = [0] * len(secciones)
        self._coincidencias: list[int] | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- API ----------------------------------------------------------------
    @property
    def indice(self) -> int:
        return self._indice

    def alto_util(self) -> float:
        """Alto del vidrio para que quepan los ocho items justos."""
        return len(self._secciones) * ALTO_ITEM + 2 * self.padding

    def seleccionar(self, i: int, *, avisar: bool = True) -> None:
        i = max(0, min(len(self._secciones) - 1, int(i)))
        if i == self._indice:
            return
        self._indice = i
        self.flash()
        self.update()
        if avisar:
            self.seleccionada.emit(i)

    def set_modificados(self, cuentas: list[int]) -> None:
        if cuentas == self._modificados:
            return
        self._modificados = list(cuentas)
        self.update()

    def set_coincidencias(self, cuentas: list[int] | None) -> None:
        if cuentas == self._coincidencias:
            return
        self._coincidencias = None if cuentas is None else list(cuentas)
        self.update()

    # -- geometria ----------------------------------------------------------
    def _caja(self, i: int) -> QRectF:
        c = self.content_rect()
        return QRectF(c.left(), c.top() + i * ALTO_ITEM, c.width(), ALTO_ITEM)

    def _en(self, punto: QPointF) -> int:
        c = self.content_rect()
        if not c.contains(punto):
            return -1
        i = int((punto.y() - c.top()) // ALTO_ITEM)
        return i if 0 <= i < len(self._secciones) else -1

    # -- interaccion --------------------------------------------------------
    def mouseMoveEvent(self, e) -> None:                    # noqa: N802
        i = self._en(e.position())
        if i != self._sobre:
            self._sobre = i
            self.update()

    def leaveEvent(self, e) -> None:                        # noqa: N802
        if self._sobre != -1:
            self._sobre = -1
            self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:                   # noqa: N802
        i = self._en(e.position())
        if i >= 0:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.seleccionar(i)

    def keyPressEvent(self, e) -> None:                     # noqa: N802
        if e.key() in (Qt.Key.Key_Down, Qt.Key.Key_Right):
            self.seleccionar(self._indice + 1)
        elif e.key() in (Qt.Key.Key_Up, Qt.Key.Key_Left):
            self.seleccionar(self._indice - 1)
        elif e.key() == Qt.Key.Key_Home:
            self.seleccionar(0)
        elif e.key() == Qt.Key.Key_End:
            self.seleccionar(len(self._secciones) - 1)
        else:
            super().keyPressEvent(e)

    # -- pintado ------------------------------------------------------------
    def paint_content(self, painter: QPainter, rect: QRectF) -> None:
        t = theme.C.tokens
        radio = self.child_radius()
        m_cap = tipo.metrics("caption")
        for i, sec in enumerate(self._secciones):
            caja = self._caja(i)
            activa = i == self._indice
            coincide = (self._coincidencias is None
                        or self._coincidencias[i] > 0)

            if activa:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glass.qcolor(t.color.accent_soft))
                painter.drawRoundedRect(caja, radio, radio)
            elif i == self._sobre:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glass.qcolor(t.edge.hair))
                painter.drawRoundedRect(caja, radio, radio)

            if activa:
                color = t.color.accent
            elif coincide:
                color = t.text.secondary
            else:
                color = t.text.quiet

            x = caja.left() + 12.0
            if self._modificados[i]:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(t.color.accent))
                painter.drawEllipse(
                    QRectF(caja.left() + 4.0, caja.center().y() - 2.0,
                           4.0, 4.0))
            _texto(painter, QRectF(x, caja.top(), caja.width() - 52.0,
                                   caja.height()),
                   "body-fuerte" if activa else "body", sec.titulo, color)

            if self._coincidencias is not None:
                n = self._coincidencias[i]
                _texto(painter,
                       QRectF(caja.right() - 44.0,
                              caja.center().y() - m_cap.height() / 2.0,
                              36.0, m_cap.height()),
                       "caption", str(n) if n else "—",
                       t.color.accent if n else t.text.quiet,
                       Qt.AlignmentFlag.AlignRight)


# --------------------------------------------------------------------------- #
# una fila viva
# --------------------------------------------------------------------------- #

class _Fila:
    """La fila del kit mas lo que el buscador necesita saber de ella."""

    __slots__ = ("esp", "row", "grupo", "vis")

    def __init__(self, esp: Espec, row: SettingRow, grupo: int) -> None:
        self.esp = esp
        self.row = row
        self.grupo = grupo
        #: 1 = casa con la busqueda. Mueve a la vez el fundido y el hueco.
        #: Sin ``EASE_LIFT``: su sobrepaso a 1.12 haria que el hueco de la fila
        #: se pasase de largo y la lista rebotase en cada pulsacion.
        self.vis = Phase(FUNDIDO_MS, FUNDIDO_MS, motion.EASE_GLASS,
                         motion.EASE_EXIT)
        self.vis.jump(True)


class _GrupoVivo:
    """Un bloque con rotulo, su instrumento y sus filas ya colocados."""

    __slots__ = ("titulo", "instrumento", "filas", "y", "k")

    def __init__(self, titulo: str, instrumento: QWidget | None) -> None:
        self.titulo = titulo
        self.instrumento = instrumento
        self.filas: list[_Fila] = []
        self.y = 0.0
        self.k = 1.0


# --------------------------------------------------------------------------- #
# panel derecho: el contenido de una seccion
# --------------------------------------------------------------------------- #

class _Vista(ThemeAware, QWidget):
    """Las filas de una seccion, su instrumento y su pie de consecuencia.

    Se coloca a mano, sin layout: los huecos de los grupos se encogen con el
    fundido del buscador y un ``QVBoxLayout`` no sabe interpolar un hueco.
    """

    def __init__(self, sec: Seccion, panel: "SettingsPanel",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sec = sec
        self._panel = panel
        self._pie = tipo.Parrafo(sec.pie, "caption")
        self._alto = 0.0
        self._vacia = False
        self.grupos: list[_GrupoVivo] = []
        self.filas: list[_Fila] = []
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        for i, g in enumerate(sec.grupos):
            inst = self._instrumento(g.instrumento)
            grupo = _GrupoVivo(g.titulo, inst)
            for esp in g.filas:
                fila = _Fila(esp, self._fila(esp), i)
                grupo.filas.append(fila)
                self.filas.append(fila)
            self.grupos.append(grupo)

    # -- construccion -------------------------------------------------------
    def _instrumento(self, nombre: str) -> QWidget | None:
        if nombre == "pinch":
            return Osciloscopio(self)
        if nombre == "puntero":
            return MedidorPuntero(self)
        return None

    def _fila(self, esp: Espec) -> SettingRow:
        mando = self._panel.crear_mando(esp)
        # la ruta entra en las palabras clave: quien sabe que ajuste busca lo
        # escribe tal cual ("filter.beta") y lo encuentra a la primera
        row = SettingRow(esp.label, mando, hint=esp.hint,
                         keywords=f"{esp.keywords} {esp.ruta}", parent=self)
        return row

    # -- estado -------------------------------------------------------------
    def actualizar(self) -> None:
        """Recarga los mandos desde la configuracion y repinta los puntos."""
        for fila in self.filas:
            self._panel.cargar_mando(fila.esp, fila.row.control)
            self._panel.rotular(fila.esp, fila.row)
            fila.row.set_modified(fila.esp.modificada(self._panel.cfg))
            fila.row.setEnabled(fila.esp.habilitada(self._panel.cfg))
        self.update()

    def recargar(self, ruta: str) -> None:
        """Recarga una sola fila: la ha corregido ``coherencia``."""
        for fila in self.filas:
            if fila.esp.ruta == ruta or fila.esp.par == ruta:
                self._panel.cargar_mando(fila.esp, fila.row.control)
                fila.row.set_modified(fila.esp.modificada(self._panel.cfg))

    def dependencias(self) -> None:
        """Reevalua ``activo_si``: una fila que no aplica se apaga, no se va."""
        for fila in self.filas:
            fila.row.setEnabled(fila.esp.habilitada(self._panel.cfg))

    def marcar(self) -> int:
        """Repasa los puntos de modificado y devuelve cuantos hay."""
        n = 0
        for fila in self.filas:
            mod = fila.esp.modificada(self._panel.cfg)
            fila.row.set_modified(mod)
            n += int(mod)
        return n

    # -- buscador -----------------------------------------------------------
    def contar(self, consulta: str) -> int:
        return sum(1 for f in self.filas if f.row.matches(consulta))

    def filtrar(self, consulta: str) -> bool:
        """Fija el destino de cada fila. ``True`` si algo tiene que moverse."""
        movimiento = False
        for fila in self.filas:
            casa = fila.row.matches(consulta)
            if casa != fila.vis.on:
                fila.vis.set(casa)
                movimiento = True
        return movimiento

    def saltar_filtro(self, consulta: str) -> None:
        """Igual que ``filtrar`` pero sin animar: la vista no se esta viendo."""
        for fila in self.filas:
            fila.vis.jump(fila.row.matches(consulta))

    # -- latido -------------------------------------------------------------
    def tick(self, dt: float) -> bool:
        vivo = False
        for fila in self.filas:
            fila.vis.step(dt)
            vivo = vivo or not fila.vis.settled
        if vivo:
            self.colocar(self.width())
        return vivo

    # -- maquetacion --------------------------------------------------------
    def colocar(self, ancho: int) -> float:
        """Coloca todo a ``ancho`` y devuelve el alto total del contenido."""
        ancho = max(240, int(ancho))
        y = 0.0
        alto_rot = tipo.metrics("overline").height()
        primero = True
        visibles = 0

        for grupo in self.grupos:
            grupo.k = max((f.vis.value for f in grupo.filas), default=0.0)
            k = grupo.k
            if k > 0.001 and not primero:
                y += GROUP_GAP * k
            grupo.y = y
            if k > 0.001:
                primero = False
            y += (alto_rot + 12.0) * k

            if grupo.instrumento is not None:
                alto = grupo.instrumento.height()
                grupo.instrumento.setGeometry(0, int(round(y)), ancho, alto)
                _opacidad(grupo.instrumento, k)
                y += (alto + GAP_SAME) * k

            for fila in grupo.filas:
                kf = fila.vis.value
                alto = fila.row.height()
                fila.row.setGeometry(0, int(round(y)), ancho, alto)
                _opacidad(fila.row, kf)
                if kf > 0.001:
                    visibles += 1
                y += (alto + ROW_GAP) * kf

        self._vacia = visibles == 0
        if self._vacia:
            y += tipo.metrics("body").height() + 12.0

        # el pie de consecuencia se queda siempre: es lo que la seccion viene a
        # decir, y esconderlo por una busqueda seria esconder la respuesta
        y += GROUP_GAP
        y += tipo.metrics("overline").height() + 8.0
        y += self._pie.set_width(min(720.0, ancho))
        self._alto = y + 8.0
        self.resize(ancho, int(math.ceil(self._alto)))
        self.update()
        return self._alto

    @property
    def alto(self) -> float:
        return self._alto

    # -- pintado ------------------------------------------------------------
    def on_theme(self) -> None:
        self.colocar(self.width())

    def paintEvent(self, event) -> None:                    # noqa: N802
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        alto_rot = tipo.metrics("overline").height()
        ancho = float(self.width())

        for grupo in self.grupos:
            if grupo.k <= 0.01:
                continue
            p.setOpacity(min(1.0, grupo.k))
            _texto(p, QRectF(0.0, grupo.y, ancho, alto_rot), "overline",
                   grupo.titulo, t.text.quiet)
        p.setOpacity(1.0)

        y = self._alto - 8.0 - self._pie.height() - alto_rot - 8.0
        if self._vacia:
            alto_msg = tipo.metrics("body").height()
            _texto(p, QRectF(0.0, y - GROUP_GAP - 12.0 - alto_msg, ancho,
                             alto_msg), "body",
                   "Nada de esta sección casa con lo que buscas.", t.text.quiet)
        _texto(p, QRectF(0.0, y, ancho, alto_rot), "overline",
               "Qué vas a notar", t.color.accent)
        self._pie.draw(p, 0.0, y + alto_rot + 8.0, QColor(t.text.tertiary))
        p.end()


class _Marco(QWidget):
    """Recorta la vista desplazada. No pinta: solo recorta a sus hijos."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)


class _Contenido(Sheet):
    """La lamina derecha: cabecera fija y contenido con desplazamiento propio.

    El desplazamiento es propio y no un ``QScrollArea`` por lo mismo que en las
    paginas profundas del panel: el area de vision de un ``QScrollArea`` pinta
    su propio fondo opaco, y aqui debajo hay vidrio.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, padding=SHEET_PADDING_LARGE)
        self.marco = _Marco(self)
        self.boton = Button("Restablecer sección", "ghost", self)
        self.vista: _Vista | None = None
        self._off = 0.0
        self._titulo = ""
        self._cuenta = 0

    # -- API ----------------------------------------------------------------
    def set_vista(self, vista: _Vista, titulo: str) -> None:
        if self.vista is vista:
            self._titulo = titulo
            self.update()
            return
        if self.vista is not None:
            self.vista.hide()
        self.vista = vista
        self._titulo = titulo
        self._off = 0.0
        vista.setParent(self.marco)
        vista.move(0, 0)
        vista.show()
        self.colocar()

    def set_cuenta(self, n: int) -> None:
        if n == self._cuenta:
            return
        self._cuenta = n
        self.boton.setVisible(n > 0)
        self.update()

    # -- desplazamiento -----------------------------------------------------
    def _tope(self) -> float:
        if self.vista is None:
            return 0.0
        return max(0.0, self.vista.alto - self.marco.height())

    def _clamp(self) -> None:
        self._off = max(0.0, min(self._tope(), self._off))

    def desplazar(self, delta: float) -> None:
        antes = self._off
        self._off += delta
        self._clamp()
        if abs(self._off - antes) > 0.01:
            self._aplicar()

    def asegurar(self, y: float, alto: float) -> None:
        """Trae a la vista una banda del contenido, si no se ve entera."""
        alto_marco = float(self.marco.height())
        if y < self._off:
            self._off = y
        elif y + alto > self._off + alto_marco:
            self._off = y + alto - alto_marco
        self._clamp()
        self._aplicar()

    def sincronizar(self) -> None:
        """El contenido ha cambiado de alto: recorta el desplazamiento."""
        self._clamp()
        self._aplicar()

    def _aplicar(self) -> None:
        if self.vista is not None:
            self.vista.move(0, int(-round(self._off)))
        self.update()

    def wheelEvent(self, event) -> None:                    # noqa: N802
        if self._tope() <= 0.0:
            event.ignore()
            return
        self.desplazar(-event.angleDelta().y() / 120.0 * PASO_RUEDA)
        event.accept()

    # -- maquetacion --------------------------------------------------------
    def colocar(self) -> None:
        c = self.content_rect()
        if c.width() < 80.0 or c.height() < 80.0:
            return
        s = self.boton.sizeHint()
        self.boton.place(QRectF(c.right() - s.width() + 2 * RING,
                                c.top() + (ALTO_CABECERA - Button.HEIGHT) / 2.0,
                                s.width() - 2 * RING, Button.HEIGHT))
        arriba = c.top() + ALTO_CABECERA + GAP_SAME
        self.marco.setGeometry(int(c.left()), int(arriba),
                               int(c.width() - CARRIL),
                               int(max(40.0, c.bottom() - arriba)))
        if self.vista is not None:
            self.vista.colocar(self.marco.width())
            self._clamp()
            self._aplicar()

    def resizeEvent(self, e) -> None:                       # noqa: N802
        super().resizeEvent(e)
        self.colocar()

    def on_theme(self) -> None:
        super().on_theme()
        self.colocar()

    # -- pintado ------------------------------------------------------------
    def paint_content(self, painter: QPainter, rect: QRectF) -> None:
        t = theme.C.tokens
        m_h1 = tipo.metrics("h1")
        _texto(painter, QRectF(rect.left(),
                               rect.top() + (ALTO_CABECERA - m_h1.height()) / 2.0,
                               rect.width() * 0.6, m_h1.height()),
               "h1", self._titulo, t.text.primary)

        m_cap = tipo.metrics("caption")
        x = self.boton.x() + RING if self.boton.isVisible() else rect.right()
        caja = QRectF(rect.left() + rect.width() * 0.6,
                      rect.top() + (ALTO_CABECERA - m_cap.height()) / 2.0,
                      max(40.0, x - 12.0 - rect.left() - rect.width() * 0.6),
                      m_cap.height())
        if self._cuenta:
            texto = ("1 ajuste modificado" if self._cuenta == 1
                     else f"{self._cuenta} ajustes modificados")
            _texto(painter, caja, "caption", texto, t.color.accent,
                   Qt.AlignmentFlag.AlignRight)
        else:
            _texto(painter, caja, "caption", "Todo como viene de fábrica",
                   t.text.quiet, Qt.AlignmentFlag.AlignRight)

        tope = self._tope()
        if tope <= 0.0 or self.vista is None:
            return
        pista = QRectF(rect.right() - BARRA_W, self.marco.y() + 4.0, BARRA_W,
                       self.marco.height() - 8.0)
        alto = max(36.0, pista.height() * self.marco.height()
                   / max(1.0, self.vista.alto))
        y = pista.top() + (pista.height() - alto) * (self._off / tope)
        color = QColor(t.text.tertiary)
        color.setAlphaF(0.45)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(pista.left(), y, pista.width(), alto),
                                BARRA_W / 2.0, BARRA_W / 2.0)


# --------------------------------------------------------------------------- #
# el temblor, medido aqui
# --------------------------------------------------------------------------- #

class _Temblor:
    """Residuo de alta frecuencia del puntero: media de |p-2p'+p''|.

    Es la misma definicion de ``telemetry.Telemetry._tremor`` y tiene que serlo:
    el medidor de Ajustes y la pagina de analisis no pueden decir dos numeros
    distintos del mismo temblor. Se mide aqui, y no pidiendoselo a la
    telemetria, para que el panel funcione con solo el motor enganchado.

    El hueco entre dos recorridos se marca con ``None``: sin el, la segunda
    diferencia cruzaria el salto de un recorrido a otro y lo leeria como un
    temblor enorme.
    """

    def __init__(self) -> None:
        self._pts: deque[tuple[float, float] | None] = deque(maxlen=TEMBLOR_N)
        self._hueco = True

    def push(self, punto: tuple[float, float] | None) -> None:
        if punto is None:
            if self._hueco:
                return
            self._hueco = True
            self._pts.append(None)
        else:
            self._hueco = False
            self._pts.append((float(punto[0]), float(punto[1])))

    def limpiar(self) -> None:
        self._pts.clear()
        self._hueco = True

    def medir(self) -> tuple[float, int]:
        total, n = 0.0, 0
        pts = list(self._pts)          # indexar una deque es recorrerla
        for i in range(2, len(pts)):
            a, b, c = pts[i - 2], pts[i - 1], pts[i]
            if a is None or b is None or c is None:
                continue
            total += math.hypot(c[0] - 2.0 * b[0] + a[0],
                                c[1] - 2.0 * b[1] + a[1])
            n += 1
        if n < TEMBLOR_MIN:
            return float("nan"), n
        return total / n, n


# --------------------------------------------------------------------------- #
# el panel
# --------------------------------------------------------------------------- #

class SettingsPanel(ThemeAware, Beating, QWidget):
    """Los ajustes enteros. Es ``dashboard.settings`` (8.9).

    Contratos que no se pueden romper: ``refresh_from_config()`` con la misma
    firma, y las cinco senyales que el panel escucha. ``attach(ctl)`` es nuevo y
    opcional: sin el, los dos instrumentos dicen que no hay senyal, que es la
    verdad, en vez de dibujar una onda bonita inventada.
    """

    changed = Signal()                 # ajustes aplicables en caliente
    camera_changed = Signal()          # requiere reabrir la camara
    theme_changed = Signal()
    calibrate_requested = Signal()
    reset_requested = Signal()

    def __init__(self, cfg: Config, parent: QWidget | None = None, *,
                 ctl: object | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._ctl: object | None = None
        self._cargando = False
        self._consulta = ""
        self._temblor = _Temblor()
        self._cuenta_out = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

        self._buscador = Field("Buscar en los ajustes", parent=self)
        self._buscador.textChanged.connect(self._on_buscar)
        self._lista = _Lista(SECCIONES, self)
        self._lista.seleccionada.connect(self._on_seccion)
        self._panel = _Contenido(self)
        self._panel.boton.clicked.connect(self._restablecer_seccion)

        self._vistas = [_Vista(sec, self, self._panel.marco)
                        for sec in SECCIONES]
        for v in self._vistas:
            v.hide()
        self._aplicar_movimiento()
        self._panel.set_vista(self._vistas[0], SECCIONES[0].titulo)
        self._refrescar_cuentas()
        if ctl is not None:
            self.attach(ctl)

    # ---------------------------------------------------------------- motor
    def attach(self, ctl: object) -> None:
        """Engancha el motor para que los instrumentos vean la senyal de verdad.

        Es opcional y se puede llamar tarde. La conexion es en cola porque
        ``output_ready`` viaja desde el hilo de la camara.
        """
        if ctl is self._ctl:
            return
        self.detach()
        self._ctl = ctl
        try:
            ctl.output_ready.connect(          # type: ignore[attr-defined]
                self.on_output, Qt.ConnectionType.QueuedConnection)
        except (AttributeError, RuntimeError, TypeError):
            self._ctl = None

    def detach(self) -> None:
        if self._ctl is None:
            return
        try:
            self._ctl.output_ready.disconnect(  # type: ignore[attr-defined]
                self.on_output)
        except (AttributeError, RuntimeError, TypeError):
            pass
        self._ctl = None

    def on_output(self, out) -> None:
        """Una salida del motor. Solo se mira si el instrumento esta a la vista."""
        if not self.isVisible():
            return
        vista = self._panel.vista
        if vista is None:
            return
        for grupo in vista.grupos:
            inst = grupo.instrumento
            if inst is None or inst.isHidden():
                continue
            if isinstance(inst, Osciloscopio):
                inst.push(float(out.pinch_ratio))
            elif isinstance(inst, MedidorPuntero):
                self._temblor.push(out.pointer if out.mode is Mode.POINTING
                                   else None)
                # la media se toma sobre 300 puntos: rehacerla en cada
                # fotograma cambiaria el tercer decimal y repintaria el
                # medidor 60 veces por segundo para nada
                self._cuenta_out += 1
                if self._cuenta_out % PASO_TEMBLOR == 0:
                    inst.set_temblor(*self._temblor.medir())

    def set_temblor(self, px: float, puntos: int) -> None:
        """Deja que el panel reciba el temblor ya medido por la telemetria."""
        vista = self._panel.vista
        if vista is None:
            return
        for grupo in vista.grupos:
            if isinstance(grupo.instrumento, MedidorPuntero):
                grupo.instrumento.set_temblor(px, puntos)

    def motor_parado(self) -> None:
        """El motor se ha parado: la traza vieja dejaria de ser cierta."""
        self._temblor.limpiar()
        for vista in self._vistas:
            for grupo in vista.grupos:
                inst = grupo.instrumento
                if inst is not None:
                    inst.olvidar()

    # ------------------------------------------------------------- mandos
    def crear_mando(self, esp: Espec) -> QWidget:
        """Fabrica el mando que le toca a una fila declarada en ``sections``."""
        if esp.clase == "toggle":
            w = Toggle(bool(esp.valor(self.cfg)))
            w.toggled.connect(lambda v, e=esp: self._escribir(e, bool(v)))
            return w
        if esp.clase == "slider":
            w = Slider(esp.lo, esp.hi, float(esp.valor(self.cfg)),
                       step=esp.paso, decimals=esp.decimales,
                       fmt=_formato(esp), bubble=False)
            w.valueChanged.connect(lambda v, e=esp: self._escribir(e, v))
            return w
        if esp.clase == "opciones":
            w = Segmented(list(esp.etiquetas), self._indice_opcion(esp))
            w.changed.connect(
                lambda i, e=esp: self._escribir(e, e.valores[i]))
            return w
        if esp.clase == "texto":
            w = Field(esp.placeholder, str(esp.valor(self.cfg)))
            w.textChanged.connect(lambda s, e=esp: self._escribir_texto(e, s))
            return w
        boton = Button(esp.boton, esp.variante if esp.variante in
                       ("primary", "normal", "ghost") else "normal")
        boton.clicked.connect(lambda e=esp: self._accion(e))
        return boton

    def _indice_opcion(self, esp: Espec) -> int:
        valor = esp.valor(self.cfg)
        for i, v in enumerate(esp.valores):
            if v == valor:
                return i
        return 0

    def cargar_mando(self, esp: Espec, w: QWidget) -> None:
        """Vuelca la configuracion en el mando, sin emitir nada."""
        antes, self._cargando = self._cargando, True
        try:
            if isinstance(w, Toggle):
                w.setChecked(bool(esp.valor(self.cfg)))
            elif isinstance(w, Slider):
                w.setValue(float(esp.valor(self.cfg)))
            elif isinstance(w, Segmented):
                w.setIndex(self._indice_opcion(esp))
            elif isinstance(w, Field):
                texto = str(esp.valor(self.cfg))
                if texto != w.text():
                    w.setText(texto)
        finally:
            self._cargando = antes

    def rotular(self, esp: Espec, row: SettingRow) -> None:
        """Pistas que dependen del estado y no de la declaracion.

        Son dos: la calibracion, que dice si hay una guardada, y el codigo de
        AirLink, que se ensenya porque es el que hay que teclear en el movil.
        Escribirlas en ``sections.py`` seria mentir en cuanto cambiasen.
        """
        if esp.accion == "borrar_calibracion":
            hay = bool(self.cfg.mapping.homography)
            row.hint = ("Guardada: se usa tu homografía" if hay else
                        "Sin calibrar: se usa la región central del encuadre")
            row.control.setEnabled(hay)
            row.update()
        elif esp.accion == "renovar_token":
            row.hint = f"Código actual: {self.cfg.airlink.token or '—'}"
            row.update()

    # ------------------------------------------------------------ escritura
    def _escribir(self, esp: Espec, valor: Any) -> None:
        if self._cargando:
            return
        por_defecto = esp.por_defecto()
        if isinstance(valor, float) and not esp.par:
            if isinstance(por_defecto, bool):
                valor = bool(valor)
            elif isinstance(por_defecto, int) or esp.entero:
                valor = int(round(valor))
            else:
                valor = round(valor, max(esp.decimales, 3))
        esp.poner(self.cfg, valor)

        # los invariantes de la configuracion se aplican al escribir, y la fila
        # corregida se recarga: el numero de la pantalla tiene que ser el numero
        # que se ha guardado
        vista = self._vista_de(esp)
        for ruta in coherencia(self.cfg):
            for v in self._vistas:
                v.recargar(ruta)
        if vista is not None:
            vista.dependencias()
        self._tras_cambio(esp.senal)
        self._alimentar_instrumentos()
        self._asegurar_instrumento(esp)

    def _escribir_texto(self, esp: Espec, texto: str) -> None:
        if self._cargando:
            return
        actual = esp.valor(self.cfg)
        if isinstance(actual, int) and not isinstance(actual, bool):
            texto = texto.strip()
            if not texto.isdigit():
                return                      # a medio teclear: no se escribe
            self._escribir(esp, int(texto))
            return
        self._escribir(esp, texto)

    def _accion(self, esp: Espec) -> None:
        if esp.accion == "calibrar":
            self.calibrate_requested.emit()
            return
        if esp.accion == "borrar_calibracion":
            self.cfg.mapping.homography = None
            self._tras_cambio("changed")
            return
        if esp.accion == "renovar_token":
            alfabeto = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
            self.cfg.airlink.token = "".join(
                secrets.choice(alfabeto) for _ in range(6))
            self._tras_cambio("changed")
            return
        if esp.accion == "reset_total":
            self.reset_requested.emit()

    def _tras_cambio(self, senal: str) -> None:
        """Repasa puntos y cuentas, y avisa por donde toque."""
        self._refrescar_cuentas()
        vista = self._panel.vista
        if vista is not None:
            vista.dependencias()
            for v in self._vistas:
                v.marcar()
            self._panel.update()
        if senal == "camara":
            self.camera_changed.emit()
        elif senal == "tema":
            self.theme_changed.emit()
            self.changed.emit()
        elif senal == "movimiento":
            self._aplicar_movimiento()
            self.changed.emit()
        else:
            self.changed.emit()

    def _aplicar_movimiento(self) -> None:
        """El panel es quien traduce ``ui.reduce_motion`` al motor de animacion."""
        motion.set_reduce_motion(bool(self.cfg.ui.reduce_motion))

    def _restablecer_seccion(self) -> None:
        sec = SECCIONES[self._lista.indice]
        sec.restablecer(self.cfg)
        self._aplicar_movimiento()
        for v in self._vistas:
            v.actualizar()
        self._refrescar_cuentas()
        for senal in {f.senal for f in sec.filas if f.clase != "accion"}:
            self._tras_cambio(senal)
        self._panel.flash()

    # ------------------------------------------------------------- cuentas
    def _refrescar_cuentas(self) -> None:
        cuentas = [sec.modificadas(self.cfg) for sec in SECCIONES]
        self._lista.set_modificados(cuentas)
        self._panel.set_cuenta(cuentas[self._lista.indice])

    def _vista_de(self, esp: Espec) -> _Vista | None:
        for vista in self._vistas:
            if esp in vista.sec.filas:
                return vista
        return None

    # ------------------------------------------------------------ buscador
    def _on_buscar(self, texto: str) -> None:
        self._consulta = texto
        consulta = texto.strip()
        cuentas = [v.contar(consulta) for v in self._vistas]
        self._lista.set_coincidencias(cuentas if consulta else None)

        # si lo que buscas no esta en la seccion abierta, el panel te lleva a la
        # primera que si lo tiene: buscar y no ver nada no es un resultado
        if consulta and cuentas[self._lista.indice] == 0 and any(cuentas):
            self._lista.seleccionar(
                next(i for i, n in enumerate(cuentas) if n))

        for i, vista in enumerate(self._vistas):
            if vista is self._panel.vista:
                if vista.filtrar(consulta):
                    self.animate()
            else:
                vista.saltar_filtro(consulta)

    def _asegurar_instrumento(self, esp: Espec) -> None:
        """Trae el instrumento del grupo a la pantalla mientras lo usas (8.7)."""
        vista = self._panel.vista
        if vista is None:
            return
        for grupo in vista.grupos:
            if grupo.instrumento is None or grupo.instrumento.isHidden():
                continue
            if any(f.esp is esp for f in grupo.filas):
                self._panel.asegurar(float(grupo.instrumento.y()),
                                     float(grupo.instrumento.height()))
                return

    def _alimentar_instrumentos(self) -> None:
        """Los umbrales y el filtro que los instrumentos tienen que dibujar."""
        vista = self._panel.vista
        if vista is None:
            return
        g, f = self.cfg.gestures, self.cfg.filter
        for grupo in vista.grupos:
            inst = grupo.instrumento
            if isinstance(inst, Osciloscopio):
                inst.set_umbrales(g.pinch_on, g.pinch_off)
            elif isinstance(inst, MedidorPuntero):
                inst.set_filtro(f.min_cutoff, f.beta)

    # ------------------------------------------------------------ secciones
    def _on_seccion(self, i: int) -> None:
        vista = self._vistas[i]
        vista.saltar_filtro(self._consulta.strip())
        self._panel.set_vista(vista, SECCIONES[i].titulo)
        self._panel.set_cuenta(SECCIONES[i].modificadas(self.cfg))
        self._alimentar_instrumentos()

    # --------------------------------------------------------------- latido
    def tick(self, dt: float) -> bool:
        vista = self._panel.vista
        vivo = vista is not None and vista.tick(dt)
        if vivo:
            self._panel.sincronizar()
        if not vivo:
            self.rest()
        return vivo

    # ----------------------------------------------------------- maquetacion
    def _colocar(self) -> None:
        r = QRectF(self.rect())
        if r.width() < 420.0 or r.height() < 260.0:
            return
        ml, mp = self._lista.reserve(), self._panel.reserve()
        izq = max(float(WINDOW_MARGIN), ml.left())
        der = max(float(WINDOW_MARGIN), mp.right())
        arriba = max(float(WINDOW_MARGIN), ml.top(), mp.top())
        abajo = max(float(WINDOW_MARGIN), ml.bottom(), mp.bottom())

        self._buscador.setGeometry(
            int(izq - RING), int(arriba - RING),
            SETTINGS_LIST_W + 2 * RING, self._buscador.height())
        y_lista = arriba + Field.HEIGHT + GAP_SAME
        alto_lista = min(self._lista.alto_util(),
                         max(120.0, r.height() - abajo - y_lista))
        self._lista.place(QRectF(izq, y_lista, SETTINGS_LIST_W, alto_lista))

        x = izq + SETTINGS_LIST_W + GAP_SAME
        self._panel.place(QRectF(x, arriba, max(320.0, r.width() - der - x),
                                 max(200.0, r.height() - abajo - arriba)))

    def resizeEvent(self, e) -> None:                       # noqa: N802
        super().resizeEvent(e)
        self._colocar()

    def on_theme(self) -> None:
        # la reserva de sombra depende del tema: en claro las sombras van al
        # 60 %, asi que el mismo sitio de vidrio cae en otra geometria
        self._colocar()
        self.update()

    def showEvent(self, e) -> None:                         # noqa: N802
        super().showEvent(e)
        self._colocar()
        self._alimentar_instrumentos()

    # ------------------------------------------------------------- contrato
    def refresh_from_config(self) -> None:
        """Recarga todos los mandos desde ``self.cfg``. Contrato con ``app.py``.

        La llaman el asistente al terminar, la calibracion al guardar y el
        boton de restablecer del panel. Tiene que recargar de verdad: no basta
        con repintar, porque lo que ha cambiado es el objeto ``Config``, no la
        pantalla.
        """
        coherencia(self.cfg)
        self._aplicar_movimiento()
        for vista in self._vistas:
            vista.actualizar()
        self._refrescar_cuentas()
        self._alimentar_instrumentos()
        consulta = self._consulta.strip()
        if consulta:
            self._on_buscar(self._consulta)
        self._panel.colocar()
        self.update()
