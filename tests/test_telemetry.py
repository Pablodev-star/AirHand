"""Pruebas de airtouch/ui/telemetry.py sin abrir ninguna ventana.

Todo lo que se comprueba aqui es acopio y aritmetica, asi que no hace falta ni
pantalla ni bucle de eventos: ``on_output``, ``on_stats`` y ``compute`` aceptan
el instante por parametro justamente para esto. Un reparto de tiempo de modos
conducido por el reloj de verdad tardaria medio minuto y ademas no repetiria.

Las cuatro cosas que se vigilan, en este orden de importancia:

1. que los anillos **no crecen** por muchas muestras que entren,
2. que los agregados dan lo que tienen que dar con datos conocidos,
3. que sin historia suficiente se marca ``enough=False`` con ``nan`` -y no un
   cero, que en un percentil se lee como "va perfecto"-,
4. que con la pagina de analisis oculta no se calcula nada.

    .venv\\Scripts\\python.exe tests\\test_telemetry.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Sin pantalla: la maquina de integracion no tiene ninguna y aqui no se pinta.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QObject, Signal      # noqa: E402

from airtouch.gestures.engine import EngineOutput                 # noqa: E402
from airtouch.gestures.events import (EventType, GestureEvent,    # noqa: E402
                                      Mode)
from airtouch.ui import telemetry as T                            # noqa: E402

# Las senales de Qt necesitan una aplicacion viva en el hilo. No se arranca el
# bucle: las emisiones son directas y el reparto se conduce a mano.
_APP = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #

class CtlFalso(QObject):
    """Lo minimo del Controller que mira Telemetry: cuatro senales y la
    compuerta de la vista previa."""

    output_ready = Signal(object)
    stats_ready = Signal(dict)
    status_changed = Signal(str)
    log_line = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.preview_enabled = True


def salida(mode: Mode = Mode.POINTING, ratio: float = 1.0,
           pointer: tuple[float, float] | None = None,
           pinching: bool = False,
           events: list[GestureEvent] | None = None) -> EngineOutput:
    return EngineOutput(mode=mode, pointer=pointer, pinching=pinching,
                        pinch_ratio=ratio, events=events or [])


def stats(**kw) -> dict:
    d = {"camera_fps": 60.0, "pipeline_fps": 60.0, "latency_ms": 30.0,
         "process_ms": 8.0, "hands": 1, "face": True, "resolution": "1280x720",
         "low_res": False, "connected": True, "control": False, "paused": False}
    d.update(kw)
    return d


def nueva() -> T.Telemetry:
    return T.Telemetry()


# --------------------------------------------------------------------------- #
# 1. los anillos no crecen
# --------------------------------------------------------------------------- #

def test_anillo_no_crece():
    r = T.Ring(64)
    antes = r.nbytes
    for i in range(20_000):
        r.push(float(i))
    assert r.nbytes == antes, f"el anillo ha crecido: {antes} -> {r.nbytes}"
    assert r.capacity == 64
    assert r.count == 64, f"count={r.count}"
    v = r.view()
    assert v.shape == (64,), v.shape
    esperado = np.arange(19_936, 20_000, dtype=np.float32)
    assert np.array_equal(v, esperado), "el anillo no devuelve las ultimas 64"


def test_anillo_vista_cronologica():
    r = T.Ring(5)
    assert r.view().size == 0, "un anillo vacio tiene que devolver vacio"
    for i in range(3):
        r.push(float(i))
    assert np.array_equal(r.view(), [0, 1, 2]), r.view()
    assert np.array_equal(r.view(last=2), [1, 2]), r.view(last=2)
    for i in range(3, 8):                       # da la vuelta
        r.push(float(i))
    assert np.array_equal(r.view(), [3, 4, 5, 6, 7]), r.view()
    assert np.array_equal(r.view(last=2), [6, 7]), r.view(last=2)
    # una vista entregada no se puede reescribir por debajo
    v = r.view()
    r.push(99.0)
    assert v[0] == 3.0, "la vista comparte memoria con el anillo"


def test_anillo_de_registros():
    r = T.Ring(3, np.dtype([("t", "f8"), ("id", "u1")]))
    for i in range(5):
        r.push((float(i), i))
    v = r.view()
    assert list(v["id"]) == [2, 3, 4], list(v["id"])
    assert list(v["t"]) == [2.0, 3.0, 4.0], list(v["t"])


def test_cascada_pliega_min_media_max():
    c = T.Cascade()
    antes = c.nbytes
    # ocho muestras finas = una media. 4 Hz -> 0,5 Hz.
    for i, v in enumerate([10, 20, 30, 40, 50, 60, 70, 80]):
        c.push(float(i), float(v), 0.0, 0.0)
    assert c.levels[0].count == 8
    assert c.levels[1].count == 1, "el nivel medio no ha plegado"
    med = c.levels[1].view()[0]
    assert med["fps_pipe"][0] == 10.0, med["fps_pipe"]
    assert med["fps_pipe"][1] == 45.0, med["fps_pipe"]
    assert med["fps_pipe"][2] == 80.0, med["fps_pipe"]
    assert med["t"] == 3.5, med["t"]
    # cuarenta finas = cinco medias = una gruesa
    for i in range(8, 40):
        c.push(float(i), 100.0, 0.0, 0.0)
    assert c.levels[2].count == 1, "el nivel grueso no ha plegado"
    grueso = c.levels[2].view()[0]
    assert grueso["fps_pipe"][0] == 10.0, "el nivel grueso ha perdido el minimo"
    assert grueso["fps_pipe"][2] == 100.0, "el nivel grueso ha perdido el pico"
    for _ in range(20_000):
        c.push(0.0, 60.0, 60.0, 30.0)
    assert c.nbytes == antes, "la cascada ha crecido"
    for k, r in enumerate(c.levels):
        assert r.capacity == T.Cascade.SIZES[k], (k, r.capacity)
        assert r.count <= r.capacity, (k, r.count)
    assert c.levels[0].full and c.levels[1].full, "los dos primeros no se llenan"


def test_telemetria_no_crece():
    tel = nueva()
    antes = tel.nbytes
    ev = [GestureEvent(EventType.CLICK)]
    for i in range(9_000):
        tel.on_output(salida(pointer=(float(i), 0.0), events=ev),
                      now=1000.0 + i * 0.016)
        if i % 15 == 0:
            tel.on_stats(stats(), now=1000.0 + i * 0.016)
    assert tel.nbytes == antes, f"la telemetria ha crecido: {antes} -> {tel.nbytes}"
    assert tel.frames == 9_000
    for nombre, ring in (("frame_dt", tel.frame_dt), ("pinch", tel.pinch),
                         ("pointer", tel.pointer), ("events", tel.events)):
        assert ring.full, f"{nombre} deberia estar lleno"
        assert ring.count == ring.capacity, nombre
    assert len(tel.log) <= T.N_LOG


def test_presupuesto_de_memoria():
    """Las formas son las del apartado 6.2. Si alguien cambia una, salta aqui."""
    tel = nueva()
    esperado = (
        T.N_FRAME_DT * 4 + T.N_PINCH * 4 + T.N_POINTER * 2 * 4
        + 4 * T.N_STATS * 4 + T.N_STATS * 8
        + T.N_SEGMENTS * T._SEGMENT.itemsize
        + T.N_EVENTS * T._EVENT.itemsize
        + T.N_CLOSURES * T._CLOSURE.itemsize
        + T.PINCH_BINS * 4
        + sum(T.Cascade.SIZES) * T._LEVEL.itemsize
    )
    assert tel.nbytes == esperado, f"{tel.nbytes} != {esperado}"


# --------------------------------------------------------------------------- #
# 2. los agregados con datos conocidos
# --------------------------------------------------------------------------- #

def test_percentiles_con_datos_conocidos():
    tel = nueva()
    for i in range(200):
        tel.on_stats(stats(latency_ms=float(i)), now=1000.0 + i * 0.25)
    q = tel.compute(now=1100.0).lat
    assert q.enough and q.n == 200, (q.enough, q.n)
    esperado = np.percentile(np.arange(200, dtype=np.float64), (50, 95, 99))
    for got, want, name in zip((q.p50, q.p95, q.p99), esperado, "p50 p95 p99".split()):
        assert abs(got - want) < 1e-6, f"{name}: {got} != {want}"


def test_histograma_de_latencia():
    tel = nueva()
    # 100 muestras a 100 ms (bin 16 de 48 en [0,300]) y 20 por encima del tope
    for i in range(100):
        tel.on_stats(stats(latency_ms=100.0), now=1000.0 + i * 0.25)
    for i in range(20):
        tel.on_stats(stats(latency_ms=520.0), now=1030.0 + i * 0.25)
    h = tel.compute(now=1100.0).lat_hist
    assert h.enough and h.n == 120, (h.enough, h.n)
    assert len(h.counts) == T.LAT_BINS
    assert int(h.counts[16]) == 100, list(h.counts[14:19])
    assert h.over == 20, h.over
    assert int(h.counts.sum()) == 100, "las de fuera de rango no se cuentan dentro"
    bordes = h.edges
    assert len(bordes) == T.LAT_BINS + 1 and bordes[0] == 0.0 and bordes[-1] == T.LAT_MAX
    assert bordes[16] <= 100.0 < bordes[17], (bordes[16], bordes[17])


def test_reparto_de_modos():
    tel = nueva()
    tel.on_output(salida(Mode.POINTING), now=100.0)
    tel.on_output(salida(Mode.POINTING), now=103.0)
    tel.on_output(salida(Mode.SCROLLING), now=103.0)
    tel.on_output(salida(Mode.SCROLLING), now=110.0)
    m = tel.compute(now=200.0).modes       # 'ahora' no le regala tiempo a nadie
    assert m.enough, m
    assert abs(m.seconds[Mode.POINTING] - 3.0) < 1e-6, m.seconds[Mode.POINTING]
    assert abs(m.seconds[Mode.SCROLLING] - 7.0) < 1e-6, m.seconds[Mode.SCROLLING]
    assert abs(m.total - 10.0) < 1e-6, m.total
    assert m.dominant is Mode.SCROLLING, m.dominant
    assert m.blind == 0.0, m.blind


def test_tasa_de_eventos():
    tel = nueva()
    clic = [GestureEvent(EventType.CLICK)]
    for i in range(6):
        tel.on_output(salida(events=clic), now=100.0 + i * 10.0)
    # los MOVE se cuentan aparte y no gastan anillo
    tel.on_output(salida(events=[GestureEvent(EventType.MOVE, {"x": 1, "y": 2})]),
                  now=155.0)
    r = tel.compute(now=160.0).events
    assert r.enough, r
    assert r.counts[EventType.CLICK] == 6, r.counts[EventType.CLICK]
    assert r.counts[EventType.MOVE] == 0, "un MOVE ha entrado en el anillo"
    assert r.moves == 1, r.moves
    assert abs(r.window - 60.0) < 1e-6, r.window
    assert abs(r.per_minute[EventType.CLICK] - 6.0) < 1e-6, r.per_minute[EventType.CLICK]


def test_temblor():
    recta = nueva()
    for i in range(120):
        recta.on_output(salida(Mode.POINTING, pointer=(3.0 * i, 5.0 * i)),
                        now=100.0 + i * 0.016)
    t = recta.compute(now=110.0).tremor
    assert t.enough and t.n == 118, (t.enough, t.n)
    assert abs(t.px) < 1e-6, f"una recta no tiembla, y aqui da {t.px}"

    zigzag = nueva()
    for i in range(120):
        zigzag.on_output(salida(Mode.POINTING, pointer=(float(i % 2), 0.0)),
                         now=100.0 + i * 0.016)
    t = zigzag.compute(now=110.0).tremor
    assert t.enough, t
    assert abs(t.px - 2.0) < 1e-6, f"temblor {t.px}, esperado 2.0"


def test_temblor_no_cruza_dos_recorridos():
    """Al soltar el puntero y volver muy lejos, el salto no es temblor."""
    tel = nueva()
    for i in range(80):
        tel.on_output(salida(Mode.POINTING, pointer=(float(i), 0.0)), now=100.0 + i)
    tel.on_output(salida(Mode.IDLE), now=200.0)                 # se corta
    for i in range(80):
        tel.on_output(salida(Mode.POINTING, pointer=(9000.0 + i, 0.0)),
                      now=300.0 + i)
    t = tel.compute(now=400.0).tremor
    assert t.enough, t
    assert abs(t.px) < 1e-6, f"el hueco se ha colado como temblor: {t.px}"


def test_valle_de_pinch():
    """Histograma bimodal construido a mano: el valle esta en el bin 22."""
    tel = nueva()
    paso = T.PINCH_MAX / T.PINCH_BINS
    cuentas = {}
    for b, c in zip((7, 8, 9, 10, 11), (20, 60, 100, 60, 20)):
        cuentas[b] = c
    for b, c in zip((32, 33, 34, 35, 36), (20, 60, 100, 60, 20)):
        cuentas[b] = c
    # el suelo entre los dos picos baja en V hasta el bin 22. Un unico bin a
    # cero no valdria: una media movil de 5 da el mismo valor en las cinco
    # posiciones que contienen ese cero, y el minimo quedaria empatado.
    for b in range(12, 32):
        cuentas[b] = min(abs(b - 22), 6)
    for b, c in sorted(cuentas.items()):
        for _ in range(c):
            tel.on_output(salida(ratio=(b + 0.5) * paso), now=100.0)
    v = tel.compute(now=200.0).pinch
    assert v.enough, "con dos poblaciones claras tiene que haber sugerencia"
    assert abs(v.ratio - 22.5 * paso) < 1e-6, f"valle en {v.ratio}"
    assert v.pinch_on == round(v.ratio, 3), v.pinch_on
    assert 0.03 <= v.pinch_off - v.pinch_on <= 0.14, (v.pinch_on, v.pinch_off)
    assert v.peaks[0] < v.ratio < v.peaks[1], v.peaks


def test_cierres_de_pinch():
    tel = nueva()
    # un cierre que acaba en clic
    tel.on_output(salida(ratio=0.30, pinching=True), now=100.0)
    tel.on_output(salida(ratio=0.22, pinching=True), now=100.1)
    tel.on_output(salida(ratio=0.50, events=[GestureEvent(EventType.CLICK)]),
                  now=100.2)
    # dos que se quedan a las puertas
    for t0, r in ((110.0, 0.33), (120.0, 0.37)):
        tel.on_output(salida(ratio=r, pinching=True), now=t0)
        tel.on_output(salida(ratio=0.9), now=t0 + 0.2)
    cl = tel.closures.view()
    assert len(cl) == 3, len(cl)
    assert list(cl["out"]) == [T.CLICK, T.ABORTED, T.ABORTED], list(cl["out"])
    assert abs(float(cl["ratio"][0]) - 0.22) < 1e-6, cl["ratio"][0]
    med = tel.compute(now=200.0).pinch.aborted_median
    assert abs(med - 0.35) < 1e-6, f"mediana de abortados {med}"


def test_salud_de_la_sesion():
    tel = nueva()
    for i in range(20):
        tel.on_stats(stats(hands=1, paused=False), now=1000.0 + i * 0.25)
    for i in range(20):
        tel.on_stats(stats(hands=0, paused=True, connected=False,
                           resolution="640x480", low_res=True),
                     now=1005.0 + i * 0.25)
    h = tel.health
    assert abs(h.total - 9.75) < 1e-6, h.total          # 39 huecos de 0,25 s
    assert abs(h.hands - 4.75) < 1e-6, h.hands      # solo el primer bucle
    assert abs(h.paused - 5.0) < 1e-6, h.paused
    assert abs(h.connected - 4.75) < 1e-6, h.connected
    assert h.pauses == 1, h.pauses
    assert h.drops == 1, h.drops
    assert h.worst_res == "640x480", h.worst_res
    assert h.low_res is True
    assert abs(h.share(h.hands) - 4.75 / 9.75) < 1e-9, h.share(h.hands)
    assert np.isnan(T.Health().share(0.0)), "sin tiempo, un reparto es nan, no 0"

    # un hueco de media hora (equipo dormido) no es tiempo de sesion
    tel.on_stats(stats(), now=3000.0)
    assert abs(tel.health.total - 9.75) < 1e-6, tel.health.total


# --------------------------------------------------------------------------- #
# 3. honestidad: sin datos suficientes se dice
# --------------------------------------------------------------------------- #

def test_sin_datos_no_se_inventa_nada():
    a = nueva().compute(now=100.0)
    for nombre, q in (("lat", a.lat), ("frame", a.frame)):
        assert not q.enough, nombre
        assert np.isnan(q.p50) and np.isnan(q.p95) and np.isnan(q.p99), \
            f"{nombre}: un percentil sin datos vale nan, no {q.p50}"
    assert not a.lat_hist.enough and int(a.lat_hist.counts.sum()) == 0
    assert not a.modes.enough and a.modes.dominant is None
    assert not a.events.enough and np.isnan(a.events.per_minute[EventType.CLICK])
    assert not a.tremor.enough and np.isnan(a.tremor.px)
    assert not a.pinch.enough and np.isnan(a.pinch.pinch_on)


def test_datos_a_medias_siguen_siendo_insuficientes():
    """El caso que de verdad importa: hay numeros, pero no bastantes."""
    tel = nueva()
    for i in range(T.MIN_QUANTILES - 1):
        tel.on_stats(stats(latency_ms=30.0), now=1000.0 + i * 0.25)
    for i in range(T.MIN_TREMOR):                 # una diferencia de menos
        tel.on_output(salida(Mode.POINTING, pointer=(float(i), 0.0)),
                      now=1000.0 + i * 0.016)
    a = tel.compute(now=1100.0)
    assert not a.lat.enough, "99 muestras no son un p99"
    assert np.isnan(a.lat.p95), a.lat.p95
    assert a.lat.n == T.MIN_QUANTILES - 1, a.lat.n
    assert not a.tremor.enough, a.tremor
    assert np.isnan(a.tremor.px), a.tremor.px

    # una sola poblacion de pinch (la mano nunca se cerro) no sugiere umbral
    solo = nueva()
    for i in range(T.MIN_PINCH + 100):
        solo.on_output(salida(ratio=0.90), now=1000.0 + i * 0.016)
    v = solo.compute(now=1100.0).pinch
    assert not v.enough, "con un solo pico no hay valle que sugerir"
    assert np.isnan(v.pinch_on)


def test_reparto_de_modos_corto_es_insuficiente():
    tel = nueva()
    tel.on_output(salida(Mode.POINTING), now=100.0)
    tel.on_output(salida(Mode.SCROLLING), now=101.0)
    tel.on_output(salida(Mode.SCROLLING), now=102.0)
    m = tel.compute(now=300.0).modes
    assert not m.enough, f"{m.total} s no dan un reparto"
    assert m.total < T.MIN_MODE_S


# --------------------------------------------------------------------------- #
# 4. si nadie mira, no se calcula
# --------------------------------------------------------------------------- #

def test_pagina_oculta_no_calcula():
    tel = nueva()
    for i in range(400):
        tel.on_output(salida(Mode.POINTING, pointer=(float(i), 0.0)),
                      now=1000.0 + i * 0.016)
        tel.on_stats(stats(), now=1000.0 + i * 0.016)
    assert not tel.analysis_visible
    for _ in range(10):
        assert tel.tick(0.25) is False, "ha calculado con la pagina oculta"
    assert tel.computations == 0, tel.computations
    assert tel.aggregates is None, "hay agregados sin que nadie los mire"

    tel.set_analysis_visible(True)
    assert tel.tick(0.25) is True
    assert tel.computations == 1, tel.computations
    assert tel.aggregates is not None
    # sin datos nuevos no se recalcula y el latido puede pararse
    assert tel.tick(0.25) is False, "recalcula sin datos nuevos"
    assert tel.computations == 1, tel.computations
    tel.on_stats(stats(), now=2000.0)
    assert tel.tick(0.25) is True
    assert tel.computations == 2, tel.computations


def test_pagina_oculta_sigue_acopiando():
    """Ocultar el analisis apaga el calculo, no la recogida."""
    tel = nueva()
    for i in range(200):
        tel.on_output(salida(Mode.POINTING), now=1000.0 + i * 0.016)
    assert tel.pinch.count == 200, tel.pinch.count
    assert tel.computations == 0


# --------------------------------------------------------------------------- #
# 5. desconexion (6.5)
# --------------------------------------------------------------------------- #

def test_panel_oculto_baja_a_contador():
    ctl = CtlFalso()
    tel = T.Telemetry(ctl)
    for i in range(50):
        ctl.output_ready.emit(salida(Mode.POINTING, pointer=(float(i), 0.0)))
    assert tel.frames == 50 and tel.pinch.count == 50

    tel.set_dashboard_visible(False, now=500.0)
    assert ctl.preview_enabled is False, "frame_ready sigue viva con el panel oculto"
    for _ in range(50):
        ctl.output_ready.emit(salida(Mode.SCROLLING, pointer=(1.0, 1.0)))
    assert tel.frames == 100, "el contador ligero tiene que seguir contando"
    assert tel.pinch.count == 50, "se ha seguido acopiando con el panel oculto"
    assert int(tel.segments.view()["mode"][-1]) == T.BLIND, "el tramo sigue abierto"

    # stats_ready se mantiene siempre: alimenta el modo compacto
    ctl.stats_ready.emit(stats())
    assert tel.stats.get("pipeline_fps") == 60.0
    assert tel.fps_pipe.count == 1

    tel.set_dashboard_visible(True, now=560.0)
    assert ctl.preview_enabled is True, "la vista previa no ha vuelto"
    ctl.output_ready.emit(salida(Mode.POINTING))
    assert tel.pinch.count == 51


def test_tiempo_sin_registrar_se_contabiliza_aparte():
    tel = nueva()
    tel.on_output(salida(Mode.POINTING), now=100.0)
    tel.on_output(salida(Mode.POINTING), now=110.0)
    tel.set_dashboard_visible(False, now=110.0)
    m = tel.compute(now=170.0).modes
    assert abs(m.seconds[Mode.POINTING] - 10.0) < 1e-6, m.seconds[Mode.POINTING]
    assert abs(m.blind - 60.0) < 1e-6, f"blind={m.blind}"
    assert abs(m.total - 10.0) < 1e-6, "el tiempo a ciegas se ha colado en el reparto"


def test_suscripcion_una_sola_vez():
    ctl = CtlFalso()
    tel = T.Telemetry(ctl)
    tel.attach(ctl)                       # idempotente
    tel.attach(ctl)
    ctl.output_ready.emit(salida())
    ctl.log_line.emit("[00:00:00] hola")
    assert tel.frames == 1, f"la senal esta conectada {tel.frames} veces"
    assert len(tel.log) == 1, list(tel.log)
    tel.detach()
    ctl.output_ready.emit(salida())
    assert tel.frames == 1, "sigue conectado despues de detach"


def test_reset_no_reasigna_memoria():
    tel = nueva()
    buf = tel.frame_dt._buf
    for i in range(500):
        tel.on_output(salida(), now=1000.0 + i * 0.016)
    tel.reset()
    assert tel.frames == 0 and tel.frame_dt.count == 0
    assert tel.pinch_hist.sum() == 0
    assert tel.frame_dt._buf is buf, "reset ha reasignado el anillo"


# --------------------------------------------------------------------------- #

def main() -> int:
    tests = [
        test_anillo_no_crece,
        test_anillo_vista_cronologica,
        test_anillo_de_registros,
        test_cascada_pliega_min_media_max,
        test_telemetria_no_crece,
        test_presupuesto_de_memoria,
        test_percentiles_con_datos_conocidos,
        test_histograma_de_latencia,
        test_reparto_de_modos,
        test_tasa_de_eventos,
        test_temblor,
        test_temblor_no_cruza_dos_recorridos,
        test_valle_de_pinch,
        test_cierres_de_pinch,
        test_salud_de_la_sesion,
        test_sin_datos_no_se_inventa_nada,
        test_datos_a_medias_siguen_siendo_insuficientes,
        test_reparto_de_modos_corto_es_insuficiente,
        test_pagina_oculta_no_calcula,
        test_pagina_oculta_sigue_acopiando,
        test_panel_oculto_baja_a_contador,
        test_tiempo_sin_registrar_se_contabiliza_aparte,
        test_suscripcion_una_sola_vez,
        test_reset_no_reasigna_memoria,
    ]
    print("Pruebas de la telemetria (sin ventana)\n")
    failed = 0
    for fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"  FALLO  {fn.__name__}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"  ERROR  {fn.__name__}: {type(exc).__name__}: {exc}")
    print()
    if failed:
        print(f"{failed} de {len(tests)} pruebas han fallado")
    else:
        print(f"Las {len(tests)} pruebas han pasado")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
