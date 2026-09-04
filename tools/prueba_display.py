"""Muestra de `kit/display.py`: las seis piezas con datos sintéticos realistas.

    .venv\\Scripts\\python.exe tools\\prueba_display.py <carpeta-destino>

Pantalla desechable, como `prueba_cristal.py`. Contesta a mano lo que el código
no delata: ¿la cifra en vivo se queda quieta de ancho?, ¿la traza sale continua
después de doscientos desplazamientos?, ¿los puntos conductores del recibo caen
en columna?, ¿el anillo y las chapas sobreviven al modo claro?

Además mide lo que hay que medir: los anchos de dígito con la fuente de la
métrica (si "111111" y "000000" no miden lo mismo, no hay cifras tabulares y
todo lo demás da igual), la marca de agua de la caja de la cifra y el coste real
de una muestra por blit desplazado frente a repintar la traza entera.

Detalle que costó una tanda de capturas: aquí los hijos se colocan a mano, y la
reserva de sombra de una lámina **cambia con el tema** (en claro las sombras van
al 60 %). Por eso `colocar()` se vuelve a llamar en cada cambio de tema; una
pantalla de verdad usa layouts y no tiene este problema.
"""
from __future__ import annotations

import math
import random
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from PySide6.QtCore import QPointF, QRectF                       # noqa: E402
from PySide6.QtGui import QColor, QPainter                       # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget              # noqa: E402

from airtouch.ui import glass, motion, theme, tipo               # noqa: E402
from airtouch.ui.kit import Inset, Sheet                         # noqa: E402
from airtouch.ui.kit.display import (Badge, Dot, LeaderLine,     # noqa: E402
                                     Metric, Ring, Sparkline)
from airtouch.ui.tokens import R_LG                              # noqa: E402

ANCHO, ALTO = 1180, 790
FILA = 26.0                       # alto de una fila de punto + rótulo


class Tarjeta(Sheet):
    """Lámina E2 con un rótulo en `overline`: el marco de todas las muestras."""

    def __init__(self, parent: QWidget, titulo: str) -> None:
        super().__init__(parent, elevation="E2", radius=R_LG, padding=20)
        self._titulo = titulo
        #: rótulos sueltos (texto, dy) que pinta la propia tarjeta. Van aquí y
        #: no en la ventana porque Qt pinta al hijo *después* del padre: escritos
        #: fuera, la lámina los tapa.
        self.filas: list[tuple[str, float]] = []

    def paint_content(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QColor(theme.C.ink.tertiary))
        painter.setFont(tipo.font("overline"))
        painter.drawText(QPointF(rect.left(),
                                 rect.top() + tipo.metrics("overline").ascent()),
                         tipo.text("overline", self._titulo))
        if not self.filas:
            return
        h = self.hueco()
        painter.setPen(QColor(theme.C.ink.secondary))
        painter.setFont(tipo.font("caption"))
        mc = tipo.metrics("caption")
        for texto, dy in self.filas:
            painter.drawText(QPointF(h.left() + 22.0,
                                     h.top() + dy + mc.ascent()), texto)

    def hueco(self) -> QRectF:
        """El contenido por debajo del rótulo."""
        r = self.content_rect()
        return r.adjusted(0.0, tipo.metrics("overline").height() + 12.0, 0.0, 0.0)


def serie_fps(n: int) -> list[float]:
    """Una tanda de fps de verdad: 58 de crucero con dos caídas de carga."""
    rnd = random.Random(7)
    out = []
    for i in range(n):
        v = 58.4 + rnd.gauss(0.0, 0.7) + 1.2 * math.sin(i / 19.0)
        if 62 < i < 74:
            v -= 14.0 + rnd.random() * 4.0
        if 150 < i < 158:
            v -= 8.0
        out.append(max(18.0, v))
    return out


def serie_lat(n: int) -> list[float]:
    rnd = random.Random(11)
    return [max(24.0, 41.0 + rnd.gauss(0.0, 3.2) + 9.0 * math.sin(i / 31.0))
            for i in range(n)]


GUARDAS = [("cara", "ok", False), ("ratón físico", "quiet", False),
           ("palma abierta", "warn", False), ("Esc", "danger", True)]

RECIBO = [("cámara", "iPhone · 1920×1080 · 60 fps"),
          ("tu pinch", "0,31 / 0,38"),
          ("región activa", "68 % del encuadre · 4 esquinas"),
          ("retardo medio", "74 ms"),
          ("gestos probados", "3 de 3")]


class Muestra(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.resize(ANCHO, ALTO)
        self.canvas = glass.CanvasSource(theme.C.tokens)
        self.canvas.resize(ANCHO, ALTO)
        glass.set_active_canvas(self.canvas)

        # --- fichas de cabecera de la página de análisis (apartado 8.5) ---
        datos = [
            ("fps del motor", "fps", 1, "pipeline_fps", True, serie_fps(40)),
            ("retardo de captura p95", "ms", 0,
             "percentil 95 de fs.capture_latency_ms", False, serie_lat(40)),
            ("detección", "ms", 1, "media de process_ms", False,
             [6.4 + 0.5 * math.sin(i / 5.0) for i in range(40)]),
            ("manos vistas", "%", 0, "muestras con hands > 0", True,
             [92 + 4 * math.sin(i / 9.0) for i in range(40)]),
        ]
        self.tarjetas_ficha: list[Tarjeta] = []
        self.fichas: list[Metric] = []
        for etiqueta, unidad, dec, nota, arriba, serie in datos:
            t = Tarjeta(self, "ficha")
            m = Metric(etiqueta, t, unit=unidad, decimals=dec, note=nota,
                       higher_is_better=arriba,
                       tone="accent" if arriba else "info")
            for v in serie:
                m.push(v)
            self.tarjetas_ficha.append(t)
            self.fichas.append(m)

        # --- la traza grande en su pozo E1: el caso del apartado 7 ---
        self.tarjeta_traza = Tarjeta(self, "traza de fps · blit desplazado")
        self.pozo = Inset(self.tarjeta_traza,
                          radius=self.tarjeta_traza.child_radius())
        self.traza = Sparkline(self.pozo, width=420, height=110, step=2.0,
                               tone="accent")
        for v in serie_fps(210):
            self.traza.push(v)

        # --- puntos de guarda y chapas ---
        self.tarjeta_estado = Tarjeta(self, "puntos y chapas")
        self.tarjeta_estado.filas = [(n, i * FILA) for i, (n, _, _)
                                     in enumerate(GUARDAS)]
        self.puntos = [Dot(self.tarjeta_estado, size=8, tone=t, pulse=p)
                       for _, t, p in GUARDAS]
        self.chapas = [
            Badge("v2.0", self.tarjeta_estado, tone="neutral"),
            Badge("control activo", self.tarjeta_estado, tone="ok", dot=True),
            Badge("ahorro", self.tarjeta_estado, tone="warn"),
            Badge("en pausa", self.tarjeta_estado, tone="danger", dot=True),
        ]

        # --- anillos: el de arranque y el que respira mientras corre ---
        self.tarjeta_anillos = Tarjeta(self, "anillos")
        self.anillo_carga = Ring(self.tarjeta_anillos, diameter=72,
                                 thickness=4, tone="accent")
        self.anillo_carga.set_progress(0.36)
        self.anillo_vivo = Ring(self.tarjeta_anillos, diameter=72, thickness=4,
                                tone="ok", progress=1.0, breathing=True)

        # --- el recibo del asistente ---
        self.tarjeta_recibo = Tarjeta(self, "recibo de configuración")
        self.recibo = [LeaderLine(e, v, self.tarjeta_recibo) for e, v in RECIBO]

        self.colocar()

    def colocar(self) -> None:
        """Coloca todo contra el vidrio, no contra el widget.

        Hay que rehacerlo en cada cambio de tema: la reserva de sombra de una
        lámina depende de la paleta, así que el mismo `place()` deja el vidrio
        en el mismo sitio pero el hueco interior cae en otro.
        """
        for i, (t, m) in enumerate(zip(self.tarjetas_ficha, self.fichas)):
            t.place(QRectF(56 + i * 272, 84, 248, 156))
            h = t.hueco()
            m.setGeometry(int(h.left()), int(h.top()),
                          int(h.width()), int(h.height()))

        self.tarjeta_traza.place(QRectF(56, 244, 660, 190))
        self.pozo.place(self.tarjeta_traza.hueco())
        ph = self.pozo.content_rect()
        self.traza.move(int(ph.left() + (ph.width() - self.traza.width()) / 2.0),
                        int(ph.top() + (ph.height() - self.traza.height()) / 2.0))

        self.tarjeta_estado.place(QRectF(740, 244, 384, 190))
        h = self.tarjeta_estado.hueco()
        for i, d in enumerate(self.puntos):
            d.move(int(h.left() - Dot.HALO + 4),
                   int(h.top() + i * FILA - Dot.HALO + 4))
        x, y = h.left() + 172, h.top()
        for ch in self.chapas:
            s = ch.sizeHint()
            if x + s.width() > h.right():
                x, y = h.left() + 172, y + s.height() + 8
            ch.setGeometry(int(x), int(y), s.width(), s.height())
            x += s.width() + 8

        self.tarjeta_anillos.place(QRectF(56, 462, 284, 200))
        h = self.tarjeta_anillos.hueco()
        self.anillo_carga.move(int(h.left() + 10), int(h.top() + 12))
        self.anillo_vivo.move(int(h.left() + 118), int(h.top() + 12))

        self.tarjeta_recibo.place(QRectF(364, 462, 760, 200))
        h = self.tarjeta_recibo.hueco()
        alto = self.recibo[0].sizeHint().height()
        for i, ln in enumerate(self.recibo):
            ln.setGeometry(int(h.left()), int(h.top() + i * (alto + 6)),
                           int(h.width()), alto)

    def retema(self) -> None:
        self.canvas.set_tokens(theme.C.tokens)
        self.colocar()
        self.update()

    def contar(self) -> None:
        for i, ln in enumerate(self.recibo):
            ln.reveal(i)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.canvas.paint(p)
        p.setPen(QColor(theme.C.ink.primary))
        p.setFont(tipo.font("title"))
        p.drawText(QPointF(56, 56), "Piezas de display")
        p.end()


def medir_tabulares() -> None:
    """La comprobación que decide si la cifra en vivo vale algo."""
    m = tipo.metrics("metric")
    unos, ceros = m.horizontalAdvance("111111"), m.horizontalAdvance("000000")
    print(f"  tnum métrica   '111111'={unos:7.2f}  '000000'={ceros:7.2f}  "
          f"delta={abs(unos - ceros):.3f} px  -> "
          f"{'TABULAR' if abs(unos - ceros) < 0.5 else 'NO TABULAR'}")
    anchos = {t: m.horizontalAdvance(t) for t in ("58,1", "11,1", "99,9", "40,0")}
    disp = "  ".join(f"{k}={v:.2f}" for k, v in anchos.items())
    print(f"  mismos dígitos {disp}  -> "
          f"{'ESTABLE' if max(anchos.values()) - min(anchos.values()) < 0.5 else 'BAILA'}")
    mm = tipo.metrics("mono")
    print(f"  tnum recibo    '111111'={mm.horizontalAdvance('111111'):7.2f}  "
          f"'000000'={mm.horizontalAdvance('000000'):7.2f}")


def medir_marca(ficha: Metric) -> None:
    """La caja de la cifra no puede encoger, o la unidad da un salto."""
    for v in (118.0, 9.0, 58.4):
        ficha.set_value(v)
        ficha.grab()                       # fuerza el paintEvent, que es quien mide
        print(f"  tras {v:6.1f} -> texto '{ficha._text}'  caja {ficha._box:6.2f} px")


def medir_blit(traza: Sparkline) -> None:
    serie = serie_fps(400)
    for v in serie[:200]:
        traza.push(v)
    t0 = time.perf_counter()
    for v in serie[200:]:
        traza.push(v)
    t1 = time.perf_counter()
    n = len(serie) - 200
    t2 = time.perf_counter()
    for _ in range(50):
        traza._rebuild()
    t3 = time.perf_counter()
    franja = (traza._step + 8.0) * traza.height()
    entera = traza.width() * traza.height()
    print(f"  muestra por blit {(t1 - t0) * 1000.0 / n:.3f} ms   "
          f"repintado entero {(t3 - t2) * 1000.0 / 50:.3f} ms")
    print(f"  píxeles dañados por muestra {franja:.0f}  frente a {entera} "
          f"de la traza entera  ({entera / franja:.0f}x)")


def reposar(app: QApplication, segundos: float) -> None:
    fin = time.time() + segundos
    while time.time() < fin:
        app.processEvents()
        time.sleep(0.008)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    destino = Path(argv[1])
    destino.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv[:1])
    w = Muestra()
    w.show()

    for tema in ("dark", "light"):
        theme.apply(tema)
        app.setStyleSheet(theme.qss())
        w.retema()
        w.contar()
        reposar(app, 1.4)
        pm = w.grab()
        pm.save(str(destino / f"display-{tema}.png"))
        print(f"{tema:5}  display-{tema}.png  {pm.width()}x{pm.height()}")

        # y un fotograma a mitad del conteo del recibo: es donde se ve si las
        # cifras que suben desde cero mantienen el ancho y si el retardo de
        # 90 ms por línea se nota
        w.contar()
        reposar(app, 0.34)
        pm = w.grab()
        pm.save(str(destino / f"display-{tema}-contando.png"))
        reposar(app, 1.2)

    print("\nmedidas")
    medir_tabulares()
    medir_marca(w.fichas[0])
    medir_blit(w.traza)
    print(f"  participantes en el latido tras reposar: {motion.beat.participants}"
          f"  (latido {'en marcha' if motion.beat.running else 'parado'})")
    w.hide()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
