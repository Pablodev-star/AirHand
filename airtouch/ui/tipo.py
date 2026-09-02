"""Fabrica de tipografia: tracking real, cifras tabulares y interlineado real.

Existe porque Qt **ignora** ``letter-spacing`` y ``line-height`` en las hojas de
estilo. ``theme.py`` las escribia y no ocurria nada: media especificacion
tipografica del apartado 3.3 era decorativa. Aqui el tracking se aplica con
``QFont.setLetterSpacing(AbsoluteSpacing, px)``, el interlineado con la clase
``Parrafo`` (``QTextLayout``, que si deja colocar cada linea a mano) y las cifras
tabulares con ``QFont.setFeature(QFont.Tag("tnum"), 1)``.

Tres cosas que se descubrieron midiendo en este equipo y que condicionan el
codigo:

* Qt **no** ve "Segoe UI Variable Display/Text/Small" como familias sueltas: la
  fuente variable de Windows 11 aparece como una unica familia "Segoe UI
  Variable". Por eso la cadena de respaldo lleva ese escalon intermedio, y por
  eso ``TYPE_NO_VARIABLE`` (la rebaja para Windows 10) no se activa aqui.
* ``setWeight()`` a secas engorda a saltos: 620 y 650 caen los dos en el
  Semibold instalado. Con ``setVariableAxis(Tag("wght"), 650)`` el eje variable
  si responde, y los pesos raros de la escala se obtienen de verdad.
* El motor de fuentes de Windows redondea el cuerpo a pixeles enteros: pedir
  13,5 px por ``setPointSizeF`` da exactamente lo mismo que pedir 14 px. Se
  redondea aqui, a la vista, en vez de fingir decimales que no existen.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QPainter,
    QTextLayout, QTextOption,
)
from PySide6.QtWidgets import QWidget

from . import tokens
from .tokens import TypeSpec

log = logging.getLogger(__name__)

#: Escalon que hay que meter en la cadena: es como Qt nombra a la variable.
FAMILY_VARIABLE = "Segoe UI Variable"


@dataclass(frozen=True)
class Familias:
    """Lo que de verdad hay instalado, resuelto una vez y registrado."""

    display: str
    text: str
    small: str
    mono: str
    variable: bool          # la familia grande es una fuente variable
    tabular: bool           # tnum funciona de verdad, medido con anchos


_familias: Familias | None = None
_compacta = False
_fuentes: dict[tuple, QFont] = {}
_metricas: dict[tuple, QFontMetricsF] = {}


def _elegir(cadena: tuple[str, ...], disponibles: set[str], rol: str) -> str:
    """Primera familia de la cadena que exista de verdad. Deja constancia."""
    for familia in cadena:
        if familia in disponibles:
            if familia != cadena[0]:
                log.info("tipo: %s: '%s' no esta instalada, se cae a '%s'",
                         rol, cadena[0], familia)
            return familia
    log.warning("tipo: %s: no hay ninguna de %s; se deja '%s' a la sustitucion "
                "de Qt", rol, cadena, cadena[-1])
    return cadena[-1]


def _tabulares(familia: str) -> bool:
    """Comprueba tnum midiendo, no preguntando.

    ``setFeature`` acepta cualquier etiqueta aunque la fuente no la lleve, asi
    que la unica prueba honesta es comparar el ancho de "111111" con el de
    "000000": si el uno sigue siendo mas estrecho, no hay cifras tabulares.
    """
    try:
        sonda = QFont(familia)
        sonda.setPixelSize(32)
        sonda.setFeature(QFont.Tag("tnum"), 1)
    except Exception as exc:                        # Qt < 6.7 no trae QFont.Tag
        log.warning("tipo: sin QFont.setFeature (%s); las cifras en vivo iran "
                    "en monoespaciada", exc)
        return False
    m = QFontMetricsF(sonda)
    return abs(m.horizontalAdvance("111111") - m.horizontalAdvance("000000")) < 0.5


def familias(recalcular: bool = False) -> Familias:
    """Resuelve la cadena de respaldo contra ``QFontDatabase.families()``."""
    global _familias
    if _familias is not None and not recalcular:
        return _familias
    if QGuiApplication.instance() is None:
        raise RuntimeError("tipo.familias() necesita una QApplication viva: "
                           "sin ella QFontDatabase devuelve una lista vacia")

    disponibles = set(QFontDatabase.families())
    grande = (tokens.FAMILY_DISPLAY, FAMILY_VARIABLE, *tokens.FALLBACKS)
    medio = (tokens.FAMILY_TEXT, FAMILY_VARIABLE, *tokens.FALLBACKS)
    pequeno = (tokens.FAMILY_SMALL, FAMILY_VARIABLE, *tokens.FALLBACKS)
    display = _elegir(grande, disponibles, "display")
    _familias = Familias(
        display=display,
        text=_elegir(medio, disponibles, "text"),
        small=_elegir(pequeno, disponibles, "small"),
        mono=_elegir((tokens.FAMILY_MONO, *tokens.FALLBACKS_MONO), disponibles,
                     "mono"),
        variable="Variable" in display,
        tabular=_tabulares(display),
    )
    log.info("tipo: display=%r text=%r small=%r mono=%r variable=%s tnum=%s",
             _familias.display, _familias.text, _familias.small,
             _familias.mono, _familias.variable, _familias.tabular)
    return _familias


def family_for(size: float) -> str:
    """Talla optica: la familia depende del cuerpo, no del rol."""
    f = familias()
    if size >= 16:
        return f.display
    if size >= 12:
        return f.text
    return f.small


# --------------------------------------------------------------------------- #
# las dos escalas, con histeresis
# --------------------------------------------------------------------------- #

def set_window_width(width: float) -> bool:
    """Elige escala normal o compacta. Devuelve True si ha cambiado.

    La histeresis de 40 px no es un adorno: sin ella, arrastrar el borde de la
    ventana justo por el punto de corte hace que los titulares salten de tamano
    a cada pixel de movimiento.
    """
    global _compacta
    limite = tokens.SCALE_BREAKPOINT + (tokens.SCALE_HYSTERESIS if _compacta else 0)
    nuevo = width < limite
    if nuevo == _compacta:
        return False
    _compacta = nuevo
    _fuentes.clear()
    _metricas.clear()
    log.info("tipo: escala %s a %.0f px de ancho",
             "compacta" if nuevo else "normal", width)
    return True


def compacta() -> bool:
    return _compacta


def spec(role: str) -> TypeSpec:
    """Fila de la escala vigente para ese rol."""
    fila = tokens.TYPE[role]
    if _compacta:
        # La escala compacta ya es mas pequena que la rebaja de Windows 10, asi
        # que manda ella sola: encadenar las dos volveria a agrandar el titular.
        return tokens.TYPE_COMPACT.get(role, fila)
    if not familias().variable:
        return tokens.TYPE_NO_VARIABLE.get(role, fila)
    return fila


# --------------------------------------------------------------------------- #
# la fabrica
# --------------------------------------------------------------------------- #

def font(role: str, *, weight: int | None = None, size: float | None = None,
         mono: bool = False) -> QFont:
    """QFont del rol, con tracking y cifras ya aplicados. Se cachea."""
    clave = (role, weight, size, mono)
    guardada = _fuentes.get(clave)
    if guardada is not None:
        return QFont(guardada)

    fila = spec(role)
    cuerpo = fila.size if size is None else size
    peso = fila.weight if weight is None else weight
    fams = familias()
    quiere_mono = mono or role == "mono"
    tabular = fila.tabular or quiere_mono
    # Respaldo del apartado 3.3: sin tnum de verdad, la etiqueta que cambia en
    # vivo se va a la monoespaciada antes que dejar bailar los digitos.
    if tabular and not quiere_mono and not fams.tabular:
        quiere_mono = True

    familia = fams.mono if quiere_mono else family_for(cuerpo)
    f = QFont(familia)
    # Windows redondea el cuerpo a pixel entero de todas formas; se hace aqui
    # para que el que lea el codigo sepa que 13,5 px acaba siendo 14.
    f.setPixelSize(int(cuerpo + 0.5))
    f.setWeight(QFont.Weight(peso))
    if fams.variable and not quiere_mono:
        # setWeight solo alcanza las instancias instaladas (620 y 650 caen los
        # dos en Semibold); el eje variable si distingue.
        f.setVariableAxis(QFont.Tag("wght"), float(peso))
    if fila.tracking:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, fila.tracking)
    if tabular:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)
        except Exception:                           # ya avisado en _tabulares
            pass
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

    _fuentes[clave] = f
    return QFont(f)


def metrics(role: str) -> QFontMetricsF:
    """Metricas del rol. En float: a 13,5 px las enteras mienten 1 px por linea."""
    clave = (role, _compacta)
    m = _metricas.get(clave)
    if m is None:
        m = QFontMetricsF(font(role))
        _metricas[clave] = m
    return m


def leading(role: str) -> float:
    """Alto de linea en pixeles, que es lo que QSS no sabe expresar."""
    fila = spec(role)
    return fila.size * fila.leading


def text(role: str, value: str) -> str:
    """Aplica la caja del rol. Las mayusculas son del rol, no de quien llama."""
    return value.upper() if spec(role).upper else value


def apply(widget: QWidget, role: str, **kwargs) -> QWidget:
    """Pone la fuente del rol en un widget y devuelve el widget."""
    widget.setFont(font(role, **kwargs))
    return widget


def default_family() -> str:
    """Lo unico tipografico que puede ir en el QSS: la familia por defecto."""
    return familias().text


# --------------------------------------------------------------------------- #
# parrafos
# --------------------------------------------------------------------------- #

class Parrafo:
    """Texto de varias lineas con el interlineado del apartado 3.3.

    QLabel reparte las lineas con el alto natural de la fuente y no hay forma de
    tocarlo desde la hoja de estilo. Con QTextLayout cada linea se coloca a mano
    en ``y += leading``, que es la unica manera de que ``body`` respire a 1.35 y
    ``metric`` quede pegado a 1.00.
    """

    def __init__(self, value: str, role: str = "body", *,
                 align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
                 max_lines: int = 0) -> None:
        self.role = role
        self.max_lines = max_lines
        self._align = align
        self._width = 0.0
        self._height = 0.0
        self._natural = 0.0
        self._layout = QTextLayout()
        self._layout.setCacheEnabled(True)
        self.set_text(value)

    def set_text(self, value: str) -> None:
        self._layout.setText(text(self.role, value))
        self._layout.setFont(font(self.role))
        opt = QTextOption(self._align)
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self._layout.setTextOption(opt)
        if self._width:
            self.set_width(self._width)

    def set_width(self, width: float) -> float:
        """Recompone y devuelve el alto ocupado."""
        self._width = float(width)
        salto = leading(self.role)
        alto_linea = metrics(self.role).height()
        y = 0.0
        lineas = 0
        self._natural = 0.0
        self._layout.beginLayout()
        while True:
            # El tope se mira antes de crear la linea: una linea creada y sin
            # setLineWidth se queda a medias dentro del layout y Qt la pinta
            # encima de la primera.
            if self.max_lines and lineas >= self.max_lines:
                break
            line = self._layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(self._width)
            line.setPosition(QPointF(0.0, y))
            self._natural = max(self._natural, line.naturalTextWidth())
            y += salto
            lineas += 1
        self._layout.endLayout()
        self._height = max(0.0, y - salto) + alto_linea if lineas else 0.0
        return self._height

    def height(self) -> float:
        return self._height

    def natural_width(self) -> float:
        """Ancho del texto ya compuesto, con el tracking dentro."""
        return self._natural

    def draw(self, painter: QPainter, x: float, y: float,
             color: QColor | str | None = None) -> None:
        painter.save()
        if color is not None:
            painter.setPen(QColor(color))
        self._layout.draw(painter, QPointF(x, y))
        painter.restore()

    def draw_in(self, painter: QPainter, rect: QRectF,
                color: QColor | str | None = None) -> None:
        """Compone al ancho del rectangulo y pinta dentro de el."""
        if abs(rect.width() - self._width) > 0.5:
            self.set_width(rect.width())
        self.draw(painter, rect.x(), rect.y(), color)


__all__ = [
    "FAMILY_VARIABLE", "Familias", "Parrafo", "apply", "compacta",
    "default_family", "familias", "family_for", "font", "leading", "metrics",
    "set_window_width", "spec", "text",
]
