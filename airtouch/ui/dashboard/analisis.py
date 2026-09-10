"""Pagina profunda ANALISIS (apartado 8.5).

Es la respuesta a "análisis de estadísticas": nueve fichas que cuentan cosas que
hoy no se sabian, no nueve maneras de repetir los 59 fps. Cada una nace de una
pregunta que un usuario se hace de verdad:

* *¿por qué a veces se siente pegajoso?* — el **p95** del retardo, no la media,
  con el veredicto escrito al lado;
* *¿dónde se me va el retardo?* — el **presupuesto**, partido en captura, vision
  y resto del periodo;
* *¿por qué a veces no me hace clic?* — los **cierres**, cada pinza de la sesion
  colocada en el minimo que alcanzo y coloreada por su desenlace;
* *¿dónde pongo el umbral?* — el valle entre los dos picos de la **curva de
  pinch**, con un boton que lo escribe.

Tres reglas que gobiernan el archivo:

* **Ningun numero se inventa.** Todo agregado de ``telemetry.py`` trae su
  bandera ``enough``; cuando es falsa se pinta un guion y se dice cuantas
  muestras faltan. Un cero en un percentil se lee como "va perfecto" y es la
  peor mentira que puede contar esta pagina.
* **Las tres fichas que ya existen se usan tal cual.** ``LatencyBudget``,
  ``Closures`` y ``PointerStability`` viven en ``charts.py``, probadas y
  medidas. Las otras seis heredan de su misma base para que la pagina se lea
  como una sola pagina y no como dos.
* **Los agregados solo se calculan aqui.** ``al_entrar`` abre la compuerta de
  ``Telemetry.set_analysis_visible`` y ``al_salir`` la cierra. Fuera de esta
  pagina el acopio sigue -es barato- y el numpy no.
"""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ...gestures.events import EventType, Mode
from ...version import __version__
from .. import charts, glass, theme, tipo
from ..charts import num
# La base de las tres fichas que ``charts.py`` ya trae hechas. Se hereda en vez
# de copiarla: si las seis de aqui tuviesen su propio titulo y su propia nota,
# la pagina se veria como dos maquetaciones distintas pegadas, que es
# exactamente lo que pasaba en el panel anterior.
from ..charts import _AnalysisCard as Ficha
from ..kit.base import Sheet
from ..kit.controls import Button, Segmented
from ..kit.display import Metric
from ..telemetry import (ABORTED, CLICK, DRAG, MIN_PINCH, PINCH_BINS,
                         PINCH_MAX, RIGHT, SCROLL, Telemetry)
from ..tokens import GUTTER, R_LG, SHEET_PADDING
from .comun import PaginaDesplazable, reloj, texto

__all__ = ["PaginaAnalisis", "RANGOS"]

#: Los tres rangos del apartado 8.5, con el nivel del anillo en cascada que les
#: corresponde: 4 Hz -> 0,5 Hz -> 0,1 Hz.
RANGOS: tuple[tuple[str, int], ...] = (("2 min", 0), ("20 min", 1), ("2 h", 2))

#: Alturas de las cinco filas de la pagina.
ALTO_CABECERA = 44.0
ALTO_CIFRAS = 112.0
ALTO_TIEMPO = 260.0
ALTO_FICHA = 220.0
ALTO_BUCLE = 120.0
ALTO_SALUD = 132.0

COLUMNAS = 6

#: Por debajo de este p95 el puntero se siente pegado al dedo (apartado 8.5.2).
P95_BUENO = 130.0

#: Desenlaces de un cierre traducidos al orden de leyenda de ``charts``.
_DESENLACE = {ABORTED: int(charts.Outcome.ABORT), CLICK: int(charts.Outcome.CLICK),
              DRAG: int(charts.Outcome.DRAG), SCROLL: int(charts.Outcome.SCROLL),
              RIGHT: int(charts.Outcome.CLICK)}


def _cifra(valor: float, decimales: int = 0) -> str:
    return "—" if not math.isfinite(valor) else num(valor, decimales)


def _colocar_boton(boton: Button, caja: QRectF) -> None:
    """El «Aplicar» abajo a la derecha, colocado por su **vidrio**.

    ``sizeHint`` de un boton incluye la reserva de su sombra, que en E2 son 34 px
    por abajo. Colocarlo con ``setGeometry`` y ese alto deja el rotulo flotando
    a media ficha; ``place()`` hace la cuenta al reves y pone el vidrio donde se
    pide, que es lo que se ve.
    """
    m = boton.reserve()
    ancho = boton.sizeHint().width() - m.left() - m.right()
    boton.place(QRectF(caja.right() - ancho,
                       caja.bottom() - 18.0 - Button.HEIGHT,
                       ancho, float(Button.HEIGHT)))


# --------------------------------------------------------------------------- #
# fichas propias
# --------------------------------------------------------------------------- #

def _ficha_cifra(etiqueta: str, unidad: str, parent: QWidget | None = None,
                 *, decimales: int = 0, mejor_arriba: bool = True) -> Sheet:
    """Una de las cuatro fichas de cabecera: una ``Metric`` dentro de su lamina.

    Es una fabrica y no una subclase de ``Sheet`` a proposito. Siendo subclase,
    la metrica se creaba dentro del ``__init__`` de la propia lamina -cuando la
    lamina ya esta dada de alta en el latido pero su objeto de Python sigue a
    medio construir- y el evento de pintado que eso provoca tumbaba el proceso
    con una violacion de acceso, sin traza ninguna. Construyendo la lamina
    entera primero y colgandole el hijo despues, no hay ventana a medio hacer.
    """
    hoja = Sheet(parent, elevation="E2", radius=R_LG, padding=SHEET_PADDING)
    metric = Metric(etiqueta, hoja, unit=unidad, decimals=decimales,
                    higher_is_better=mejor_arriba)
    metric.setGeometry(hoja.content_rect().toRect())

    def _recolocar(event, _h=hoja, _m=metric) -> None:
        Sheet.resizeEvent(_h, event)
        _m.setGeometry(_h.content_rect().toRect())

    hoja.resizeEvent = _recolocar
    hoja.metric = metric
    return hoja


class _LineaDeTiempo(Ficha):
    """8.5.1 — dos areas superpuestas y el retardo como linea fina encima."""

    TITLE = "línea de tiempo"
    FOOTNOTE = ("motor y cámara sobre el eje izquierdo · retardo sobre el "
                "derecho · el hueco entre las dos áreas son los fotogramas "
                "que el motor no llegó a procesar")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grafico = charts.AreaChart(
            self, ground=False,
            colors=[theme.C.color.accent, theme.C.color.info],
            line_color=theme.C.color.warn, unit=" fps")
        self.grafico.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def on_theme(self) -> None:
        super().on_theme()
        self.grafico._colors = [theme.C.color.accent, theme.C.color.info]
        self.grafico._line_color = theme.C.color.warn
        self.grafico.invalidate()

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        c = self.content_rect()
        self.grafico.setGeometry(QRectF(c.left(), c.top() + 22.0, c.width(),
                                        c.height() - 22.0 - 18.0).toRect())

    def paint_content(self, p: QPainter, content: QRectF) -> None:
        self.paint_header(p, content)
        t = theme.C
        leyenda = (("motor", t.color.accent), ("cámara", t.color.info),
                   ("retardo", t.color.warn))
        x = content.right()
        for nombre, color in reversed(leyenda):
            ancho = tipo.metrics("caption").horizontalAdvance(nombre)
            x -= ancho
            texto(p, QRectF(x, content.top(), ancho, 14.0), "caption", nombre,
                  t.ink.secondary)
            x -= 10.0
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x, content.top() + 3.0, 8.0, 8.0), 2.0, 2.0)
            x -= 16.0
        self.paint_footnote(p, content)


class _Latencia(Ficha):
    """8.5.2 — el histograma con p50, p95 y p99, y el veredicto escrito."""

    TITLE = "histograma de latencia"
    FOOTNOTE = "48 tramos en [0, 300] ms · marcas en p50, p95 y p99"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grafico = charts.Histogram(self, ground=False, unit=" ms")
        self.grafico.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._veredicto = "sin muestras suficientes todavía"

    def set_datos(self, hist, cuantiles) -> None:
        self.grafico.set_bins(hist.counts, hist.lo, hist.hi)
        if cuantiles.enough:
            self.grafico.set_marks([(cuantiles.p50, "p50"),
                                    (cuantiles.p95, "p95"),
                                    (cuantiles.p99, "p99")])
            self._veredicto = (
                f"p95 = {num(cuantiles.p95, 0)} ms · "
                + ("por debajo de 130 ms el puntero se siente pegado al dedo"
                   if cuantiles.p95 < P95_BUENO
                   else "por encima de 130 ms el puntero se siente arrastrado"))
        else:
            self.grafico.set_marks(())
            self._veredicto = (f"{cuantiles.n} muestras: hacen falta 100 para "
                               f"que un p95 signifique algo")
        self.update()

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        c = self.content_rect()
        self.grafico.setGeometry(QRectF(c.left(), c.top() + 22.0, c.width(),
                                        c.height() - 22.0 - 40.0).toRect())

    def paint_content(self, p: QPainter, content: QRectF) -> None:
        self.paint_header(p, content)
        parrafo = tipo.Parrafo(self._veredicto, "caption", max_lines=2)
        parrafo.set_width(content.width())
        parrafo.draw(p, content.left(), content.bottom() - 36.0,
                     QColor(theme.C.ink.secondary))
        self.paint_footnote(p, content)


class _RelojDeModos(Ficha):
    """8.5.4 — la dona del tiempo de permanencia y su lista ordenada."""

    TITLE = "reloj de modos"
    FOOTNOTE = "tiempo de permanencia por modo · rampa compartida con el overlay"

    LISTA_W = 132.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.dona = charts.Donut(self, ground=False)
        self.dona.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._filas: list[tuple[str, float, float, str]] = []
        self._ciego = 0.0

    def set_reparto(self, reparto) -> None:
        t = theme.C.tokens
        vivos = [(m, s) for m, s in reparto.seconds.items() if s > 0.01]
        vivos.sort(key=lambda par: par[1], reverse=True)
        total = max(1e-6, reparto.total)
        self.dona.set_slices([(m.value, s, t.mode_color(m)) for m, s in vivos])
        self._filas = [(m.value, s, s / total * 100.0, t.mode_color(m))
                       for m, s in vivos[:6]]
        self._ciego = reparto.blind
        self.update()

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        c = self.content_rect()
        lado = min(c.height() - 22.0 - 18.0, c.width() - self.LISTA_W - 12.0)
        self.dona.setGeometry(QRectF(c.left(), c.top() + 22.0, lado,
                                     lado).toRect())

    def paint_content(self, p: QPainter, content: QRectF) -> None:
        self.paint_header(p, content)
        # el centro de la dona lo escribe la propia dona (modo dominante y su
        # porcentaje): aqui solo va la lista ordenada de la derecha
        t = theme.C
        x = content.right() - self.LISTA_W
        y = content.top() + 24.0
        for nombre, segundos, pct, color in self._filas:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x, y + 4.0, 8.0, 8.0), 2.0, 2.0)
            texto(p, QRectF(x + 14.0, y, self.LISTA_W - 56.0, 15.0), "caption",
                  nombre, t.ink.secondary)
            texto(p, QRectF(x, y, self.LISTA_W, 15.0), "axis",
                  f"{reloj(segundos)} · {num(pct, 0)} %", t.ink.tertiary,
                  Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            y += 18.0
        if self._ciego > 1.0:
            texto(p, QRectF(x, y, self.LISTA_W, 14.0), "axis",
                  f"sin registrar {reloj(self._ciego)}", t.ink.quiet)
        self.paint_footnote(p, content)


class _CurvaDePinch(Ficha):
    """8.5.5 — el histograma de la pinza, sus dos umbrales y la sugerencia.

    Es el grafico que justifica la pagina entera: convierte el ajuste de los
    umbrales de adivinar a leer. El boton solo aparece cuando el valle existe de
    verdad; sin dos poblaciones separadas no se sugiere nada, porque un numero
    inventado con aspecto de recomendacion es peor que no dar ninguna.
    """

    TITLE = "curva de pinch"
    FOOTNOTE = "64 tramos de pinch_ratio · banda sombreada = histéresis"

    aplicar = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grafico = charts.Histogram(self, ground=False)
        self.grafico.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.boton = Button("Aplicar", "primary", self)
        self.boton.hide()
        self.boton.clicked.connect(self._aplicar)
        self._frase = "Cierra la mano unas cuantas veces y aquí saldrá tu curva."
        self._sugerido: tuple[float, float] | None = None

    def set_curva(self, hist: np.ndarray, valle, pinch_on: float,
                  pinch_off: float) -> None:
        self.grafico.set_bins(hist, 0.0, PINCH_MAX)
        self.grafico.set_marks([(pinch_on, "cierre"), (pinch_off, "apertura")])
        self.grafico.set_bands([(pinch_on, pinch_off, theme.C.color.accent)])
        if valle.enough:
            self._sugerido = (valle.pinch_on, valle.pinch_off)
            self._frase = (f"sugerido: {num(valle.pinch_on, 2)} / "
                           f"{num(valle.pinch_off, 2)} · el valle entre tus dos "
                           f"picos cae en {num(valle.ratio, 2)}")
            self.boton.show()
        else:
            self._sugerido = None
            self._frase = (f"{valle.n} muestras de pinza: con menos de "
                           f"{MIN_PINCH} el valle es ruido")
            self.boton.hide()
        self._colocar()
        self.update()

    def _aplicar(self) -> None:
        if self._sugerido is not None:
            self.aplicar.emit(*self._sugerido)

    def _colocar(self) -> None:
        c = self.content_rect()
        self.grafico.setGeometry(QRectF(c.left(), c.top() + 22.0, c.width(),
                                        c.height() - 22.0 - 46.0).toRect())
        _colocar_boton(self.boton, c)

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        self._colocar()

    def paint_content(self, p: QPainter, content: QRectF) -> None:
        self.paint_header(p, content)
        ancho = content.width() - (self.boton.width() + 8.0
                                   if self.boton.isVisible() else 0.0)
        parrafo = tipo.Parrafo(self._frase, "caption", max_lines=2)
        parrafo.set_width(max(60.0, ancho))
        parrafo.draw(p, content.left(), content.bottom() - 42.0,
                     QColor(theme.C.ink.secondary))
        self.paint_footnote(p, content)


class _Cierres(charts.Closures):
    """8.5.6 — la ficha de ``charts.py`` con su boton «Aplicar» encima."""

    aplicar = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.boton = Button("Aplicar", "primary", self)
        self.boton.hide()
        self.boton.clicked.connect(self._aplicar)

    def set_closures(self, minima, outcomes, pinch_on: float,
                     pinch_off: float) -> None:
        super().set_closures(minima, outcomes, pinch_on, pinch_off)
        self.boton.setVisible(self.advice.value is not None)
        _colocar_boton(self.boton, self.content_rect())

    def _aplicar(self) -> None:
        valor = self.advice.value
        if valor is not None:
            self.aplicar.emit(float(valor))

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        _colocar_boton(self.boton, self.content_rect())


class _Bucle(Ficha):
    """8.5.8 — la tira de latido a un tick por fotograma y su frase."""

    TITLE = "estabilidad del bucle"
    FOOTNOTE = "un tick por fotograma · verde ≤20 ms · ámbar ≤33 ms · rojo >33 ms"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tira = charts.Heartbeat(self, ground=False)
        self.tira.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def push(self, dt_ms: float) -> None:
        self.tira.push(dt_ms)

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        c = self.content_rect()
        self.tira.setGeometry(QRectF(c.left(), c.top() + 20.0, c.width(),
                                     c.height() - 20.0 - 34.0).toRect())

    def paint_content(self, p: QPainter, content: QRectF) -> None:
        self.paint_header(p, content)
        texto(p, QRectF(content.left(), content.bottom() - 32.0,
                        content.width(), 15.0), "caption", self.tira.summary(),
              theme.C.ink.secondary)
        self.paint_footnote(p, content)


class _Salud(Ficha):
    """8.5.9 — la tira de fichas del reparto de tiempo de la sesion."""

    TITLE = "salud de la sesión"
    FOOTNOTE = "acumulado desde que arrancó el motor · fuente: stats_ready"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.barra = charts.Strip(self, ground=False)
        self.barra.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._fichas: list[tuple[str, str]] = []

    def set_salud(self, salud) -> None:
        t = theme.C
        def parte(segundos: float) -> str:
            k = salud.share(segundos)
            return "—" if not math.isfinite(k) else f"{num(k * 100.0, 0)} %"

        self._fichas = [
            ("con manos", parte(salud.hands)),
            ("con cara", parte(salud.face)),
            ("en pausa", f"{salud.pauses} · {reloj(salud.paused)}"),
            ("cortes de cámara", str(salud.drops)),
            ("peor resolución", salud.worst_res or "—"),
            ("control real", parte(salud.control)),
        ]
        seguro = max(0.0, salud.total - salud.control)
        self.barra.set_parts([("control real", salud.control, t.color.ok),
                              ("modo seguro", seguro, t.ink.tertiary)])
        self.update()

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        c = self.content_rect()
        self.barra.setGeometry(QRectF(c.left(), c.bottom() - 34.0, c.width(),
                                      12.0).toRect())

    def paint_content(self, p: QPainter, content: QRectF) -> None:
        self.paint_header(p, content)
        if not self._fichas:
            return
        t = theme.C
        ancho = content.width() / len(self._fichas)
        y = content.top() + 26.0
        for i, (nombre, valor) in enumerate(self._fichas):
            x = content.left() + i * ancho
            texto(p, QRectF(x, y, ancho, 14.0), "overline", nombre,
                  t.ink.tertiary)
            texto(p, QRectF(x, y + 16.0, ancho, 22.0), "h2", valor,
                  t.ink.primary)
        self.paint_footnote(p, content)


# --------------------------------------------------------------------------- #
# la pagina
# --------------------------------------------------------------------------- #

class PaginaAnalisis(PaginaDesplazable):
    """Las nueve fichas, la cabecera de rango y el boton «Informe»."""

    TITULO = "Análisis"

    ajustes_cambiados = Signal()
    reconstruir = Signal()

    def on_theme(self) -> None:
        """No se retematiza: el panel la reconstruye entera.

        Esta pagina lleva nueve fichas y varias guardan mapas de pixeles
        cacheados para el blit desplazado. Retematizarlas en vivo tumbaba el
        proceso con una violacion de acceso al repintar, sin traza de Python
        porque ocurre dentro de una llamada de C++, y no bastaba ni aplazarlo
        un ciclo ni topar las cajas vacias. Cambiar de tema es raro y ya cuesta
        mas que un fotograma: construir la pagina de cero es barato al lado de
        perseguir cada cache.
        """
        self.reconstruir.emit()

    def _retematizar(self) -> None:
        try:
            super().on_theme()
        except RuntimeError:
            # la pagina pudo morir entre el aviso y este ciclo
            return
        self.update()

    def __init__(self, cfg, ctl, tele: Telemetry,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.ctl = ctl
        self.tele = tele
        self._t0 = time.perf_counter()
        self._rango = 0
        self._informe = ""
        self._ultimo_frame = 0.0

        m = self.marco
        self.rango = Segmented([nombre for nombre, _n in RANGOS], 0, m)
        self.rango.changed.connect(self._set_rango)
        self.boton_informe = Button("Informe", "normal", m)
        self.boton_informe.clicked.connect(self._copiar_informe)

        self.fps = _ficha_cifra("fps del motor", "", m)
        self.retardo = _ficha_cifra("retardo p95", "ms", m, mejor_arriba=False)
        self.deteccion = _ficha_cifra("detección", "ms", m, decimales=1,
                                     mejor_arriba=False)
        self.manos = _ficha_cifra("manos vistas", "%", m)

        self.tiempo = _LineaDeTiempo(m)
        self.latencia = _Latencia(m)
        self.presupuesto = charts.LatencyBudget(m)
        self.modos = _RelojDeModos(m)
        self.pinch = _CurvaDePinch(m)
        self.cierres = _Cierres(m)
        self.puntero = charts.PointerStability(m)
        self.bucle = _Bucle(m)
        self.salud = _Salud(m)

        self.pinch.aplicar.connect(self._aplicar_umbrales)
        self.cierres.aplicar.connect(lambda v: self._aplicar_umbrales(v, None))
        self.tele.aggregates_ready.connect(self._on_aggregates)

    # -- ciclo --------------------------------------------------------------
    def al_entrar(self) -> None:
        self._t0 = time.perf_counter()
        self.tele.set_analysis_visible(True)
        if self.tele.aggregates is not None:
            self._on_aggregates(self.tele.aggregates)
        self._refrescar_series()

    def al_salir(self) -> None:
        super().al_salir()
        self.tele.set_analysis_visible(False)

    # -- datos --------------------------------------------------------------
    def on_stats(self, stats: dict) -> None:
        self.fps.metric.push(float(stats.get("pipeline_fps", 0.0) or 0.0))
        self.deteccion.metric.push(float(stats.get("process_ms", 0.0) or 0.0))
        periodo = 1000.0 / max(1.0, float(stats.get("pipeline_fps", 0.0) or 1.0))
        self.presupuesto.push(float(stats.get("latency_ms", 0.0) or 0.0),
                              float(stats.get("process_ms", 0.0) or 0.0),
                              periodo)
        self._refrescar_series()
        self.update()

    def on_output(self, out) -> None:
        """El latido va por fotograma: es la unica serie que no pasa por stats.

        El hueco se mide aqui y no releyendo el anillo de ``telemetry`` porque
        lo que la tira cuenta es el periodo **de los fotogramas que han llegado
        a esta pagina**; con la pagina cerrada no hay tira que alimentar.
        """
        ahora = time.perf_counter()
        if self._ultimo_frame:
            dt = (ahora - self._ultimo_frame) * 1000.0
            if 0.0 < dt < 1000.0:
                self.bucle.push(dt)
        self._ultimo_frame = ahora

    def _on_aggregates(self, agg) -> None:
        self.retardo.metric.push(agg.lat.p95 if agg.lat.enough else 0.0)
        self.latencia.set_datos(agg.lat_hist, agg.lat)
        self.modos.set_reparto(agg.modes)
        g = self.cfg.gestures
        self.pinch.set_curva(self.tele.pinch_hist, agg.pinch,
                             g.pinch_on, g.pinch_off)
        cl = self.tele.closures.view()
        if cl.size:
            self.cierres.set_closures(
                cl["ratio"].tolist(),
                [_DESENLACE.get(int(o), int(charts.Outcome.ABORT))
                 for o in cl["out"]],
                g.pinch_on, g.pinch_off)
        self.puntero.set_points(self.tele.pointer.view())
        self.salud.set_salud(self.tele.health)
        salud = self.tele.health
        vistas = salud.share(salud.hands)
        self.manos.metric.push(0.0 if not math.isfinite(vistas)
                               else vistas * 100.0)
        self._informe = self._componer_informe(agg)
        self.update()

    def _refrescar_series(self) -> None:
        """La linea de tiempo lee el nivel de la cascada que pide el rango."""
        nivel = self.tele.cascade.levels[RANGOS[self._rango][1]]
        datos = nivel.view()
        if datos.size < 2:
            return
        self.tiempo.grafico.set_series(
            [datos["fps_pipe"][:, 1], datos["fps_cam"][:, 1]],
            datos["lat"][:, 1])

    def _set_rango(self, indice: int) -> None:
        self._rango = indice
        self._refrescar_series()

    # -- acciones -----------------------------------------------------------
    def _aplicar_umbrales(self, on: float, off: float | None = None) -> None:
        g = self.cfg.gestures
        g.pinch_on = float(on)
        g.pinch_off = float(off) if off is not None else max(
            g.pinch_off, float(on) + 0.03)
        self.ctl.retune()
        self.ajustes_cambiados.emit()
        self.pinch.grafico.set_marks([(g.pinch_on, "cierre"),
                                      (g.pinch_off, "apertura")])
        self.update()

    def _componer_informe(self, agg) -> str:
        """El resumen en texto plano del apartado 8.5, para pegar en un aviso."""
        s = self.tele.stats
        salud = self.tele.health
        lineas = [
            f"AirTouch {__version__} — informe de sesión",
            f"cámara: {s.get('resolution', '?')} · peor vista: "
            f"{salud.worst_res or '?'}",
            f"fps motor {num(float(s.get('pipeline_fps', 0.0) or 0.0), 1)} · "
            f"cámara {num(float(s.get('camera_fps', 0.0) or 0.0), 1)}",
            f"retardo p50/p95/p99: {_cifra(agg.lat.p50)}/"
            f"{_cifra(agg.lat.p95)}/{_cifra(agg.lat.p99)} ms "
            f"({agg.lat.n} muestras)",
            f"temblor: {num(self.puntero.tremor, 2)} px",
            f"umbrales: cierre {num(self.cfg.gestures.pinch_on, 2)} · "
            f"apertura {num(self.cfg.gestures.pinch_off, 2)}",
            f"bucle: {self.bucle.tira.summary()}",
            f"sesión: {reloj(salud.total)} · {salud.pauses} pausas · "
            f"{salud.drops} cortes de cámara",
            f"gestos: {agg.events.counts.get(EventType.CLICK, 0)} clics · "
            f"{agg.events.counts.get(EventType.SCROLL, 0)} scrolls",
        ]
        return "\n".join(lineas)

    def _copiar_informe(self) -> None:
        cb = QGuiApplication.clipboard()
        if cb is not None and self._informe:
            cb.setText(self._informe)
            self.boton_informe.setText("Copiado")

    # -- maquetacion --------------------------------------------------------
    def _fila(self, y: float, x0: float, ancho_col: float,
              piezas, alto: float) -> float:
        """Coloca una fila de laminas por numero de columnas. Devuelve la y."""
        x = x0
        for widget, cols in piezas:
            w = cols * ancho_col + (cols - 1) * GUTTER
            widget.place(QRectF(x, y, w, alto))
            x += w + GUTTER
        return y + alto + GUTTER

    def colocar(self) -> None:
        super().colocar()
        if self.area.isEmpty():
            return
        caja = self.contenido()
        x0, y = caja.left(), caja.top()
        ancho = caja.width()
        ancho_col = (ancho - GUTTER * (COLUMNAS - 1)) / COLUMNAS

        h = self.rango.sizeHint()
        self.rango.setGeometry(int(x0), int(y + (ALTO_CABECERA - h.height()) / 2),
                               h.width(), h.height())
        b = self.boton_informe.sizeHint()
        self.boton_informe.setGeometry(
            int(x0 + ancho - b.width()),
            int(y + (ALTO_CABECERA - b.height()) / 2), b.width(), b.height())
        y += ALTO_CABECERA + GUTTER

        y = self._fila(y, x0, ancho_col,
                       ((self.fps, 1), (self.retardo, 2), (self.deteccion, 2),
                        (self.manos, 1)), ALTO_CIFRAS)
        y = self._fila(y, x0, ancho_col,
                       ((self.tiempo, 4), (self.latencia, 2)), ALTO_TIEMPO)
        y = self._fila(y, x0, ancho_col,
                       ((self.presupuesto, 2), (self.modos, 2), (self.pinch, 2)),
                       ALTO_FICHA)
        y = self._fila(y, x0, ancho_col,
                       ((self.cierres, 3), (self.puntero, 3)), ALTO_FICHA)
        y = self._fila(y, x0, ancho_col, ((self.bucle, 6),), ALTO_BUCLE)
        y = self._fila(y, x0, ancho_col, ((self.salud, 6),), ALTO_SALUD)
        self.set_alto(y - caja.top() + self.desplazamiento + self.MARGEN)

    def paintEvent(self, event) -> None:                    # noqa: N802
        super().paintEvent(event)
        if self.area.isEmpty():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        caja = self.contenido().translated(self.area.topLeft())
        texto(p, QRectF(caja.left(), caja.top(), caja.width(), ALTO_CABECERA),
              "caption", f"sesión {reloj(time.perf_counter() - self._t0)}",
              theme.C.ink.tertiary,
              Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        p.end()
