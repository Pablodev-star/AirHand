"""Contraprueba del apartado 7: los gráficos con datos sintéticos realistas.

    .venv\\Scripts\\python.exe tools\\prueba_charts.py <carpeta-destino>

Pantalla desechable, como `prueba_cristal.py`. Contesta dos preguntas que el
código no contesta:

1. **¿Se leen?** Un gráfico que no falla pero sale ilegible no vale. Por eso
   saca las dos hojas (primitivas y las tres tarjetas de análisis) en los dos
   temas, y hay que MIRAR los PNG.
2. **¿Cuánto cuesta el blit desplazado?** Mide el coste de meter una muestra en
   una traza con `QPixmap.scroll` y el de regenerar el mismo pozo entero, que es
   lo que costaría sin él. Los dos números se imprimen; no se estiman.

Los datos son sintéticos pero con la forma de los de verdad: `stats_ready` llega
a ~4 Hz, el retardo de captura ronda los 40 ms con colas, y los cierres de pinch
se amontonan cerca del umbral, que es precisamente el caso que la tarjeta de
CIERRES tiene que saber contar.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from PySide6.QtCore import QPoint, QRectF, Qt                      # noqa: E402
from PySide6.QtGui import QColor, QPainter                         # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget                # noqa: E402

from airtouch.gestures.events import Mode                          # noqa: E402
from airtouch.ui import charts, glass, theme, tipo                 # noqa: E402
from airtouch.ui.tokens import R_LG                                # noqa: E402

ANCHO, ALTO = 1180, 760
SEMILLA = 20260904


# --------------------------------------------------------------------------- #
# datos sintéticos con la forma de los de verdad
# --------------------------------------------------------------------------- #

def datos() -> dict:
    r = np.random.default_rng(SEMILLA)
    n = 240                                    # 60 s a 4 Hz

    # el motor se cae dos veces por debajo de 50 fps, como pasa de verdad
    fps = 58.0 + r.normal(0, 0.9, n)
    fps[90:104] -= 12.0
    fps[180:188] -= 7.0
    cam = np.clip(fps + r.normal(0, 1.4, n), 20, 61)

    # retardo de captura: lognormal, que es la forma que tiene de verdad
    lat = 34.0 + r.lognormal(1.9, 0.45, n)
    lat[90:104] += 55.0

    proc = 6.4 + r.gamma(2.0, 0.9, n)
    periodo = 1000.0 / np.clip(fps, 12, 90)

    # frame_dt: 60 Hz con saltos, que es lo que mide el latido
    dt = 16.7 + r.gamma(1.4, 0.9, 900)
    dt[r.random(900) < 0.03] += 22.0

    # pinch: dos picos (mano abierta y mano cerrada) y el valle entre ellos
    pinch = np.concatenate([r.normal(0.86, 0.10, 1200),
                            r.normal(0.22, 0.07, 600)])
    hist, _ = np.histogram(np.clip(pinch, 0, 1.4), bins=64, range=(0.0, 1.4))

    # histograma de latencia, 48 bins en [0, 300] ms (apartado 6.3)
    hist_lat, _ = np.histogram(lat, bins=48, range=(0.0, 300.0))

    # cierres: la mayoría llega, pero los abortados se quedan justo encima del
    # umbral. Es el caso que la frase calculada tiene que saber leer
    n_c = 96
    minimos = np.concatenate([r.normal(0.24, 0.05, 62),
                              r.normal(0.355, 0.018, 34)])
    desenlaces = np.concatenate([
        r.choice([0, 0, 0, 1, 2], 62),
        np.full(34, int(charts.Outcome.ABORT))]).astype(np.int16)
    orden = r.permutation(n_c)

    # recorrido del puntero: deriva lenta más temblor de alta frecuencia
    pasos = r.normal(0, 0.55, (700, 2)) + np.stack([
        np.sin(np.linspace(0, 9, 700)) * 1.9,
        np.cos(np.linspace(0, 6, 700)) * 1.4], axis=1)
    puntero = np.cumsum(pasos, axis=0) + np.array([1280.0, 720.0])

    return dict(fps=fps, cam=cam, lat=lat, proc=proc, periodo=periodo, dt=dt,
                hist=hist, hist_lat=hist_lat,
                minimos=minimos[orden], desenlaces=desenlaces[orden],
                puntero=puntero.astype(np.float32))


D = datos()
PINCH_ON, PINCH_OFF = 0.34, 0.42


def p_lat(q: float) -> float:
    return float(np.percentile(D["lat"], q))


# --------------------------------------------------------------------------- #
# hoja 1: las primitivas
# --------------------------------------------------------------------------- #

class HojaPrimitivas(QWidget):
    """Cada primitiva del apartado 7 dentro de su pozo E1, con su rótulo."""

    def __init__(self) -> None:
        super().__init__()
        self.resize(ANCHO, ALTO)
        self.canvas = glass.CanvasSource(theme.C.tokens)
        self.canvas.resize(ANCHO, ALTO)
        glass.set_active_canvas(self.canvas)

        self.trace = charts.Trace(self, step=2.0, unit=" fps", lo=0.0, hi=72.0,
                                  autoscale=False)
        self.stack = charts.StackedTrace(
            self, step=2.0, hi=140.0,
            colors=[theme.C.color.info, theme.C.color.accent,
                    theme.C.ink.tertiary])
        self.stack.set_rule(charts.BUDGET_TARGET_MS)
        self.area = charts.AreaChart(
            self, colors=[theme.C.color.accent, theme.C.color.info],
            line_color=theme.C.color.warn, unit=" fps")
        self.hist = charts.Histogram(self, unit=" ms")
        self.donut = charts.Donut(self)
        self.scatter = charts.Scatter(self, lo=0.0, hi=0.7)
        self.beat = charts.Heartbeat(self)
        self.strip = charts.Strip(self, ground=True)
        self.spark = charts.Sparkline(self)
        self.cargar()

    def cargar(self) -> None:
        for v in D["fps"]:
            self.trace.push(float(v))
        for i in range(len(D["lat"])):
            self.stack.push((float(D["lat"][i]), float(D["proc"][i]),
                             max(0.0, float(D["periodo"][i] - D["proc"][i]))))
        self.area.set_series([D["fps"][-120:], D["cam"][-120:]],
                             D["lat"][-120:])
        self.hist.set_bins(D["hist_lat"], 0.0, 300.0)
        self.hist.set_marks([(p_lat(50), "p50"), (p_lat(95), "p95"),
                             (p_lat(99), "p99")])
        self.donut.set_slices(self.reparto())
        self.scatter.set_points(D["minimos"], D["desenlaces"],
                                charts.outcome_colors())
        self.scatter.set_rules([(PINCH_ON, "cierre"), (PINCH_OFF, "apertura")])
        for v in D["dt"]:
            self.beat.push(float(v))
        self.strip.set_parts([("manos", 62.0, theme.C.color.ok),
                              ("sin manos", 24.0, theme.C.ink.tertiary),
                              ("pausa", 14.0, theme.C.color.danger)])
        self.spark.set_values(D["fps"][-40:])

    def reparto(self) -> list[tuple[str, float, str]]:
        t = theme.C.tokens
        return [("apuntando", 46.0, t.mode_color(Mode.POINTING)),
                ("inactivo", 22.0, t.mode_color(Mode.IDLE)),
                ("scroll", 14.0, t.mode_color(Mode.SCROLLING)),
                ("arrastrando", 11.0, t.mode_color(Mode.DRAGGING)),
                ("zoom", 7.0, t.mode_color(Mode.ZOOMING))]

    def retema(self) -> None:
        self.canvas.set_tokens(theme.C.tokens)
        self.trace._color = None
        self.stack._colors = [theme.C.color.info, theme.C.color.accent,
                              theme.C.ink.tertiary]
        self.stack.invalidate()
        self.area._colors = [theme.C.color.accent, theme.C.color.info]
        self.area._line_color = theme.C.color.warn
        self.area.invalidate()
        self.donut.set_slices(self.reparto())
        self.scatter._colors = charts.outcome_colors()
        self.strip.set_parts([("manos", 62.0, theme.C.color.ok),
                              ("sin manos", 24.0, theme.C.ink.tertiary),
                              ("pausa", 14.0, theme.C.color.danger)])
        for w in self.findChildren(charts.ChartWidget):
            w.on_theme()

    # -- maquetación --------------------------------------------------------
    def celdas(self) -> list[tuple[str, QWidget, QRectF]]:
        m, g = 28.0, 20.0
        col = (ANCHO - 2 * m - 2 * g) / 3.0
        f1, f2, f3 = 78.0, 288.0, 498.0
        alto = 150.0
        return [
            ("Trace · blit desplazado, paso 2 px",
             self.trace, QRectF(m, f1, col, alto)),
            ("StackedTrace · presupuesto apilado",
             self.stack, QRectF(m + col + g, f1, col, alto)),
            ("AreaChart · cúbica cacheada + eje derecho",
             self.area, QRectF(m + 2 * (col + g), f1, col, alto)),
            ("Histogram · 48 bins, marcas de percentil",
             self.hist, QRectF(m, f2, col, alto)),
            ("Donut · reloj de modos",
             self.donut, QRectF(m + col + g, f2, col, alto)),
            ("Scatter · cierres por desenlace",
             self.scatter, QRectF(m + 2 * (col + g), f2, col, alto)),
            ("Heartbeat · 900 ticks, 1 px por fotograma",
             self.beat, QRectF(m, f3, col * 2 + g, 92.0)),
            ("Strip · reparto de la sesión",
             self.strip, QRectF(m + 2 * (col + g), f3, col, 44.0)),
            ("Sparkline · 60×28",
             self.spark, QRectF(m + 2 * (col + g), f3 + 62.0, 60.0, 28.0)),
        ]

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for _rotulo, w, r in self.celdas():
            if isinstance(w, charts.Sparkline):
                w.move(int(r.left()), int(r.top()))
            else:
                w.setGeometry(r.adjusted(1, 1, -1, -1).toRect())

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.canvas.paint(p)

        p.setFont(tipo.font("title"))
        p.setPen(QColor(theme.C.ink.primary))
        p.drawText(QRectF(28, 24, 800, 34), int(Qt.AlignmentFlag.AlignLeft),
                   "Gráficos · QPainter")
        p.setFont(tipo.font("caption"))
        p.setPen(QColor(theme.C.ink.tertiary))
        p.drawText(QRectF(28, 54, 900, 16), int(Qt.AlignmentFlag.AlignLeft),
                   "datos sintéticos con la forma de los reales · "
                   f"tema {theme.C.name}")

        for rotulo, w, r in self.celdas():
            if not isinstance(w, charts.Sparkline):
                glass.paint_sheet(p, r, "E1", 14, canvas=self.canvas,
                                  canvas_origin=QPoint(0, 0))
            p.setFont(tipo.font("axis"))
            p.setPen(QColor(theme.C.ink.tertiary))
            p.drawText(QRectF(r.left(), r.top() - 16, r.width() + 90, 13),
                       int(Qt.AlignmentFlag.AlignLeft),
                       tipo.text("axis", rotulo))
        p.setFont(tipo.font("caption"))
        p.setPen(QColor(theme.C.ink.secondary))
        p.drawText(QRectF(28, 620, ANCHO - 56, 18),
                   int(Qt.AlignmentFlag.AlignLeft), self.beat.summary())
        p.end()


# --------------------------------------------------------------------------- #
# hoja 2: las tres tarjetas de análisis
# --------------------------------------------------------------------------- #

class HojaTarjetas(QWidget):
    """Las fichas 3, 6 y 7 del apartado 8.5, a su tamaño de verdad."""

    def __init__(self) -> None:
        super().__init__()
        self.resize(ANCHO, 460)
        self.canvas = glass.CanvasSource(theme.C.tokens)
        self.canvas.resize(ANCHO, 460)
        glass.set_active_canvas(self.canvas)

        self.budget = charts.LatencyBudget(self)
        self.closures = charts.Closures(self)
        self.pointer = charts.PointerStability(self)
        self.cargar()

    def cargar(self) -> None:
        for i in range(len(D["lat"])):
            self.budget.push(float(D["lat"][i]), float(D["proc"][i]),
                             float(D["periodo"][i]))
        self.closures.set_closures(D["minimos"], D["desenlaces"],
                                   PINCH_ON, PINCH_OFF)
        for i in range(120, len(D["puntero"]), 6):
            self.pointer.set_points(D["puntero"][:i])

    def retema(self) -> None:
        self.canvas.set_tokens(theme.C.tokens)
        for w in (self.budget, self.closures, self.pointer):
            w.on_theme()
        self.closures.set_closures(D["minimos"], D["desenlaces"],
                                   PINCH_ON, PINCH_OFF)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        ancho, alto, hueco = 272.0, 190.0, 24.0
        x = 28.0
        for w in (self.budget, self.closures, self.pointer):
            w.place(QRectF(x, 96.0, ancho, alto))
            x += ancho + hueco

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.canvas.paint(p)
        p.setFont(tipo.font("title"))
        p.setPen(QColor(theme.C.ink.primary))
        p.drawText(QRectF(28, 30, 900, 34), int(Qt.AlignmentFlag.AlignLeft),
                   "Análisis · las tres tarjetas")
        p.setFont(tipo.font("caption"))
        p.setPen(QColor(theme.C.ink.tertiary))
        p.drawText(QRectF(28, 62, 900, 16), int(Qt.AlignmentFlag.AlignLeft),
                   "presupuesto de retardo · cierres · estabilidad del puntero")

        p.setFont(tipo.font("body"))
        p.setPen(QColor(theme.C.ink.secondary))
        consejo = self.closures.advice
        sugerido = ("aplicaría " + charts.num(consejo.value, 2)
                    if consejo.value is not None else "sin sugerencia")
        p.drawText(QRectF(28, 320, ANCHO - 56, 20),
                   int(Qt.AlignmentFlag.AlignLeft),
                   f"frase calculada: {consejo.text}")
        p.drawText(QRectF(28, 344, ANCHO - 56, 20),
                   int(Qt.AlignmentFlag.AlignLeft),
                   f"botón «Aplicar»: {sugerido}   ·   temblor "
                   f"{charts.num(self.pointer.tremor, 2)} px")
        p.end()


# --------------------------------------------------------------------------- #
# medición: blit desplazado contra regeneración completa
# --------------------------------------------------------------------------- #

def medir() -> tuple[float, float, int, float]:
    """Coste de una muestra con blit y sin él, sobre el mismo pozo.

    "Sin blit" no es un hombre de paja: es exactamente lo que hay que hacer para
    meter una muestra si no se puede desplazar el pixmap, o sea redibujar el
    pozo entero desde el anillo. Es el camino que `Trace` ya recorre al cambiar
    de tema o de tamaño, así que el número sale del mismo código.
    """
    t = charts.Trace(step=2.0, lo=0.0, hi=72.0, autoscale=False)
    t.resize(420, 110)
    for v in D["fps"]:
        t.push(float(v))
    muestras = np.tile(D["fps"], 4)

    t.push(float(muestras[0]))                       # calentar el pozo
    t0 = time.perf_counter()
    for v in muestras:
        t.push(float(v))
    con = (time.perf_counter() - t0) * 1000.0 / muestras.size

    t._ensure()
    t0 = time.perf_counter()
    for _ in range(120):
        t.invalidate()
        t._ensure()
    sin = (time.perf_counter() - t0) * 1000.0 / 120.0

    ancho_dano = int(t._buf.step + charts.HEAD_HALO + 2)
    return con, sin, ancho_dano, t._buf.step


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    destino = Path(argv[1])
    destino.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv[:1])
    hojas = [("primitivas", HojaPrimitivas()), ("tarjetas", HojaTarjetas())]

    for tema in ("dark", "light"):
        theme.apply(tema)
        app.setStyleSheet(theme.qss())
        for nombre, w in hojas:
            glass.set_active_canvas(w.canvas)
            w.retema()
            w.show()
            w.update()
            fin = time.time() + 0.9
            while time.time() < fin:
                app.processEvents()
                time.sleep(0.01)
            pm = w.grab()
            ruta = destino / f"charts-{nombre}-{tema}.png"
            pm.save(str(ruta))
            print(f"{tema:5}  {ruta.name:34} {pm.width()}x{pm.height()}")
            w.hide()

    theme.apply("dark")
    con, sin, dano, paso = medir()
    print(f"\nTraza de 420x110, paso {paso:.0f} px logico:")
    print(f"  con blit desplazado : {con:.3f} ms por muestra "
          f"({dano} px de ancho dañado)")
    print(f"  sin blit (regenerar): {sin:.3f} ms por muestra "
          f"(420 px de ancho dañado)")
    print(f"  factor              : x{sin / max(1e-6, con):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
