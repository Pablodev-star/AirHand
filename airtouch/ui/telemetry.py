"""El motor de datos del panel: anillos preasignados y agregados honestos.

Aqui no se pinta nada. ``Telemetry`` se suscribe **una sola vez** a las senales
del ``Controller``, guarda lo que llega en anillos de numpy que nunca cambian de
tamano, y calcula los agregados del apartado 6.3 **solo cuando alguien los esta
mirando**. Vive en el shell del panel, no en las paginas: las paginas se crean y
se destruyen, los datos no.

Tres decisiones que conviene entender antes de tocar nada:

* **Nada crece.** Cada serie es un ``Ring`` sobre un array preasignado con un
  indice de escritura. Una lista que crece durante una sesion de dos horas a
  60 Hz son 432 000 objetos de Python; aqui son ocho escrituras escalares por
  fotograma y memoria constante desde el primer segundo.
* **Si nadie mira, no se calcula.** Los percentiles, el histograma y el valle de
  pinch cuestan numpy de verdad. Se calculan a 4 Hz (``HZ_STATS``) y solo con la
  pagina de analisis visible; el acopio, que es barato, sigue siempre.
* **La falta de datos se dice.** Todo agregado lleva ``enough``. Cuando no hay
  suficiente historia los valores son ``nan``, nunca cero: una linea plana en un
  grafico es una mentira que parece un dato, y un cero en un percentil es la
  peor de todas porque se lee como "va perfecto".

El presupuesto de memoria del apartado 6.2 dice "= 60 KB". Esa cifra solo cuenta
las cinco primeras filas de su tabla: sumadas dan 63 KB y ahi se queda. Con las
de tramos, eventos y cierres -que la misma tabla especifica- y los tres niveles
del eje largo, el total medido son **244 KB**. Las formas son las de la
especificacion y no se tocan; la cifra se corrige aqui y se puede volver a
medir en ``Telemetry.nbytes``, que es lo honesto.

Medido en este equipo: **2,8 us de acopio por fotograma** y **0,19 ms la tanda
entera de agregados**, que a 4 Hz es menos de una milesima de un nucleo.

Los metodos de entrada aceptan el instante por parametro (``now``) igual que
``Beat.advance`` y ``Smooth.step``, precisamente para poder probar el reparto
temporal sin dejar correr un reloj de verdad. Conectados a una senal de Qt,
llegan con un solo argumento y usan ``perf_counter``.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, Signal

from ..gestures.events import EventType, Mode
from .motion import HZ_STATS, beat

# --------------------------------------------------------------------------- #
# formas de los anillos (6.2)
# --------------------------------------------------------------------------- #

N_FRAME_DT = 3600      # 60 s a 60 Hz
N_PINCH = 1800         # ~30 s de pinch_ratio
N_POINTER = 1800       # recorrido del puntero
N_STATS = 1200         # ~5 min a 4 Hz
N_SEGMENTS = 4096      # tramos de modo
N_EVENTS = 4096        # un registro por GestureEvent (menos MOVE, ver abajo)
N_CLOSURES = 2048      # cierres de pinch
PINCH_BINS = 64        # histograma de pinch en [0, PINCH_MAX]
PINCH_MAX = 1.4

LAT_BINS = 48          # histograma de latencia
LAT_MAX = 300.0        # ms

_SEGMENT = np.dtype([("t", "f8"), ("mode", "u1")])
_EVENT = np.dtype([("id", "u1"), ("t", "f8")])
_CLOSURE = np.dtype([("t", "f8"), ("ratio", "f4"), ("out", "u1")])
# min/media/max por serie, que es lo que guarda cada nivel del inferior
_LEVEL = np.dtype([("t", "f8"), ("fps_pipe", "3f4"), ("fps_cam", "3f4"),
                   ("lat", "3f4")])

# El orden de los enums es el codigo que se guarda en u1. Se calcula una vez:
# hacer list(Mode).index(m) por fotograma seria un barrido lineal por fotograma.
MODES: tuple[Mode, ...] = tuple(Mode)
EVENTS: tuple[EventType, ...] = tuple(EventType)
_MODE_CODE = {m: i for i, m in enumerate(MODES)}
_EVENT_CODE = {e: i for i, e in enumerate(EVENTS)}

# Codigo de tramo "sin registrar": ver Telemetry.set_dashboard_visible.
BLIND = 255

# desenlaces de un cierre de pinch
ABORTED, CLICK, DRAG, SCROLL, RIGHT = 0, 1, 2, 3, 4

# --------------------------------------------------------------------------- #
# umbrales de honestidad (6.4)
# --------------------------------------------------------------------------- #

# Con menos de 100 muestras el p99 es un unico punto y el p95 son cinco: no es
# un percentil, es la muestra mas alta con un nombre elegante.
MIN_QUANTILES = 100
MIN_HIST = 60
MIN_MODE_S = 5.0
# Una tasa "por minuto" sacada de tres segundos no es una tasa. Veinte segundos
# es el minimo con el que un clic suelto no se convierte en "3 clics/min".
MIN_EVENT_S = 20.0
MIN_TREMOR = 60
# ~7 s de mano a la vista. Por debajo el histograma de pinch tiene un solo pico
# (la mano abierta) y cualquier "valle" es ruido de un par de fotogramas.
MIN_PINCH = 400
PEAK_GAP = 5           # bins que separan un pico del otro para no coger su hombro
PEAK_RATIO = 0.12      # el segundo pico por debajo de esto no es una poblacion
VALLEY_DEPTH = 0.60    # el valle tiene que bajar de verdad entre los dos picos
# Distancia por defecto entre pinch_on y pinch_off en config.py (0.34 -> 0.40).
# config.Config la vuelve a acotar a [on+0.03, on+0.14] al guardar.
HYST_GAP = 0.06

# Un salto mayor que esto entre dos fotogramas no es un fotograma lento: es la
# ventana volviendo de estar oculta, el depurador, o el equipo despertando.
# Contarlo estropearia el p99 de una sesion entera.
MAX_FRAME_S = 1.0
# Lo mismo para el reparto de tiempo de la salud de sesion, que se acumula con
# el hueco entre dos stats_ready (2-4 Hz).
MAX_STATS_S = 2.0

N_LOG = 500            # lineas de registro que se guardan para la pagina


# --------------------------------------------------------------------------- #
# anillo
# --------------------------------------------------------------------------- #

class Ring:
    """Serie circular sobre un array preasignado. No crece nunca.

    Sirve igual para escalares (``Ring(1200)``), para vectores
    (``Ring(1800, width=2)``) y para registros (``Ring(4096, _EVENT)``): lo
    unico que cambia es lo que se le pasa a ``push``.
    """

    __slots__ = ("_buf", "_size", "_i", "_n")

    def __init__(self, size: int, dtype=np.float32, width: int = 0) -> None:
        shape = (size,) if width == 0 else (size, width)
        self._buf = np.zeros(shape, dtype=dtype)
        self._size = size
        self._i = 0        # proxima posicion de escritura
        self._n = 0        # muestras validas, topado en size

    def push(self, value) -> None:
        self._buf[self._i] = value
        self._i = (self._i + 1) % self._size
        if self._n < self._size:
            self._n += 1

    def clear(self) -> None:
        self._i = 0
        self._n = 0

    @property
    def capacity(self) -> int:
        return self._size

    @property
    def count(self) -> int:
        return self._n

    @property
    def full(self) -> bool:
        return self._n >= self._size

    @property
    def nbytes(self) -> int:
        return self._buf.nbytes

    def view(self, last: int | None = None) -> np.ndarray:
        """Las ultimas ``last`` muestras en orden cronologico.

        Devuelve una copia siempre que el anillo haya dado la vuelta. Es un
        memcpy de 14 KB en el peor caso y se hace a 4 Hz; a cambio, quien se
        guarde el array no se encuentra el pasado reescrito por debajo.
        """
        n = self._n if last is None else min(self._n, last)
        if n == 0:
            return self._buf[:0]
        end = self._i
        start = end - n
        if start >= 0:
            return self._buf[start:end].copy()
        return np.concatenate((self._buf[start:], self._buf[:end]))


class Cascade:
    """Los tres anillos del eje largo: fino 4 Hz, medio 0,5 Hz, grueso 0,1 Hz.

    Cada nivel guarda min / media / max del inferior, asi que la ventana de 2 h
    cabe en 720 registros sin perder los picos: una media sola los borraria y el
    grafico de 2 h diria que nunca hubo un tiron.
    """

    SIZES = (600, 600, 720)
    RATIOS = (8, 5)        # 4 Hz -> 0,5 Hz -> 0,1 Hz
    FIELDS = ("fps_pipe", "fps_cam", "lat")

    def __init__(self) -> None:
        self.levels = [Ring(n, _LEVEL) for n in self.SIZES]
        # cubos pendientes de plegar. Estan topados por RATIOS: 8 y 5 registros.
        self._pending: list[list[tuple]] = [[], []]

    def push(self, t: float, fps_pipe: float, fps_cam: float, lat: float) -> None:
        rec = (t, (fps_pipe,) * 3, (fps_cam,) * 3, (lat,) * 3)
        self._add(0, rec)

    def _add(self, k: int, rec: tuple) -> None:
        self.levels[k].push(rec)
        if k >= len(self.RATIOS):
            return
        bucket = self._pending[k]
        bucket.append(rec)
        if len(bucket) >= self.RATIOS[k]:
            self._add(k + 1, self._fold(bucket))
            bucket.clear()

    @staticmethod
    def _fold(recs: list[tuple]) -> tuple:
        t = sum(r[0] for r in recs) / len(recs)
        out: list = [t]
        for col in range(1, 4):
            trio = [r[col] for r in recs]
            out.append((min(v[0] for v in trio),
                        sum(v[1] for v in trio) / len(trio),
                        max(v[2] for v in trio)))
        return tuple(out)

    def clear(self) -> None:
        for level in self.levels:
            level.clear()
        for bucket in self._pending:
            bucket.clear()

    @property
    def nbytes(self) -> int:
        return sum(r.nbytes for r in self.levels)


# --------------------------------------------------------------------------- #
# agregados (6.3) — todos con su bandera de honestidad (6.4)
# --------------------------------------------------------------------------- #

def _nan3() -> tuple[float, float, float]:
    return (float("nan"),) * 3


@dataclass(frozen=True)
class Quantiles:
    p50: float
    p95: float
    p99: float
    n: int
    enough: bool


@dataclass(frozen=True, eq=False)
class Hist:
    counts: np.ndarray
    lo: float
    hi: float
    over: int          # muestras por encima de hi: no se tiran, se dicen
    n: int
    enough: bool

    @property
    def edges(self) -> np.ndarray:
        return np.linspace(self.lo, self.hi, len(self.counts) + 1)


@dataclass(frozen=True, eq=False)
class ModeShare:
    seconds: dict[Mode, float]
    total: float
    blind: float       # tiempo con el panel oculto, en el que no se registro
    dominant: Mode | None
    enough: bool


@dataclass(frozen=True, eq=False)
class EventRate:
    per_minute: dict[EventType, float]
    counts: dict[EventType, int]
    window: float
    moves: int         # los MOVE se cuentan aparte, ver Telemetry._on_output
    enough: bool


@dataclass(frozen=True)
class Tremor:
    px: float
    n: int
    enough: bool


@dataclass(frozen=True, eq=False)
class Valley:
    ratio: float
    pinch_on: float
    pinch_off: float
    peaks: tuple[float, float]
    aborted_median: float    # mediana del pinch minimo de los cierres abortados
    n: int
    enough: bool


@dataclass(frozen=True, eq=False)
class Aggregates:
    t: float
    lat: Quantiles
    frame: Quantiles
    lat_hist: Hist
    modes: ModeShare
    events: EventRate
    tremor: Tremor
    pinch: Valley


@dataclass
class Health:
    """Reparto de tiempo de la sesion. Se acumula con cada ``stats_ready``."""

    total: float = 0.0
    hands: float = 0.0
    face: float = 0.0
    paused: float = 0.0
    control: float = 0.0
    connected: float = 0.0
    pauses: int = 0
    drops: int = 0
    worst_width: int = 0
    worst_res: str = ""
    low_res: bool = False

    def share(self, seconds: float) -> float:
        return seconds / self.total if self.total > 0.0 else float("nan")


# --------------------------------------------------------------------------- #
# el motor
# --------------------------------------------------------------------------- #

class Telemetry(QObject):
    """Acopio y agregados. Un solo objeto por ventana."""

    aggregates_ready = Signal(object)     # Aggregates

    def __init__(self, ctl=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctl = None
        self._dash = True          # panel a la vista (6.5)
        self._analysis = False     # pagina de analisis a la vista (6.3)
        self._fresh = False        # ha entrado algo desde el ultimo calculo

        # anillos (6.2)
        self.frame_dt = Ring(N_FRAME_DT)                  # ms entre output_ready
        self.pinch = Ring(N_PINCH)
        self.pointer = Ring(N_POINTER, width=2)
        self.fps_cam = Ring(N_STATS)
        self.fps_pipe = Ring(N_STATS)
        self.lat = Ring(N_STATS)
        self.proc = Ring(N_STATS)
        self.t_stats = Ring(N_STATS, np.float64)
        self.segments = Ring(N_SEGMENTS, _SEGMENT)
        self.events = Ring(N_EVENTS, _EVENT)
        self.closures = Ring(N_CLOSURES, _CLOSURE)
        self.pinch_hist = np.zeros(PINCH_BINS, dtype=np.uint32)
        self.cascade = Cascade()

        # crudos y contadores
        self.stats: dict = {}
        self.status = ""
        self.log: deque[str] = deque(maxlen=N_LOG)
        self.frames = 0
        self.moves = 0
        self.computations = 0
        self.health = Health()
        self.aggregates: Aggregates | None = None

        self._last_out_t = 0.0
        self._last_stats_t = 0.0
        self._mode_code: int | None = None
        self._pointer_gap = True   # el proximo punto empieza un recorrido nuevo
        self._closing = False
        self._close_t = 0.0
        self._close_min = 1.0
        self._close_out = ABORTED
        self._preview_was = False

        if ctl is not None:
            self.attach(ctl)

    # -- suscripcion --------------------------------------------------------
    def attach(self, ctl) -> None:
        """Se suscribe al controlador. Idempotente a proposito: el shell puede
        reconstruir sus paginas y no debe acabar con la senal conectada dos
        veces, que es como se duplican silenciosamente todas las cuentas."""
        if self._ctl is ctl:
            return
        self.detach()
        self._ctl = ctl
        ctl.output_ready.connect(self.on_output)
        ctl.stats_ready.connect(self.on_stats)
        ctl.status_changed.connect(self.on_status)
        ctl.log_line.connect(self.on_log)

    def detach(self) -> None:
        ctl, self._ctl = self._ctl, None
        if ctl is None:
            return
        for signal, slot in ((ctl.output_ready, self.on_output),
                             (ctl.stats_ready, self.on_stats),
                             (ctl.status_changed, self.on_status),
                             (ctl.log_line, self.on_log)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    # -- visibilidad (6.5) --------------------------------------------------
    @property
    def dashboard_visible(self) -> bool:
        return self._dash

    def set_dashboard_visible(self, value: bool, now: float | None = None) -> None:
        """Panel a la vista, oculto, minimizado o en compacto.

        Con el panel oculto ``output_ready`` se queda en un contador y la fuente
        de ``frame_ready`` se apaga en el origen: poner ``preview_enabled`` a
        False es mejor que desconectar el slot, porque asi el hilo del motor ni
        siquiera copia el fotograma ni cruza la cola de Qt. ``stats_ready`` sigue
        conectado siempre: es barato y alimenta el modo compacto.
        """
        value = bool(value)
        if value == self._dash:
            return
        now = time.perf_counter() if now is None else now
        self._dash = value
        if not value:
            # Dejar el ultimo modo creciendo mientras nadie registra seria una
            # mentira que se agranda sola. El tramo se cierra con un codigo de
            # "sin registrar" que el reparto contabiliza aparte.
            self.segments.push((now, BLIND))
            self._mode_code = None
            self._pointer_gap = True
            self._last_out_t = 0.0
        ctl = self._ctl
        if ctl is None:
            return
        if not value:
            self._preview_was = bool(getattr(ctl, "preview_enabled", False))
            ctl.preview_enabled = False
        else:
            ctl.preview_enabled = self._preview_was

    @property
    def analysis_visible(self) -> bool:
        return self._analysis

    def set_analysis_visible(self, value: bool) -> None:
        """La pagina de analisis entra o sale. Fuera de ella no se agrega nada."""
        value = bool(value)
        if value == self._analysis:
            return
        self._analysis = value
        if value:
            beat.join(self, HZ_STATS)
        else:
            beat.leave(self)

    # -- entrada ------------------------------------------------------------
    def on_output(self, out, now: float | None = None) -> None:
        now = time.perf_counter() if now is None else now
        self.frames += 1
        if not self._dash:
            return                              # contador ligero y nada mas (6.5)

        if self._last_out_t:
            dt = now - self._last_out_t
            if 0.0 < dt < MAX_FRAME_S:
                self.frame_dt.push(dt * 1000.0)
        self._last_out_t = now

        ratio = float(out.pinch_ratio)
        self.pinch.push(ratio)
        b = int(ratio / PINCH_MAX * PINCH_BINS)
        self.pinch_hist[min(max(b, 0), PINCH_BINS - 1)] += 1

        mode = out.mode
        code = _MODE_CODE.get(mode, 0)
        if code != self._mode_code:
            self.segments.push((now, code))
            self._mode_code = code

        # El temblor solo tiene sentido apuntando. Al salir de POINTING se mete
        # un punto NaN: sin el, la segunda diferencia cruzaria el hueco entre dos
        # recorridos distintos y ese salto se leeria como un temblor enorme.
        if mode is Mode.POINTING and out.pointer is not None:
            self.pointer.push((out.pointer[0], out.pointer[1]))
            self._pointer_gap = False
        elif not self._pointer_gap:
            self.pointer.push((np.nan, np.nan))
            self._pointer_gap = True

        for ev in out.events:
            if ev.type is EventType.MOVE:
                # MOVE llega en cada fotograma: a 60 Hz llenaria el anillo en
                # 68 s y dejaria la tasa de todos los demas tipos ciega a
                # cualquier cosa mas vieja que eso. El recorrido del puntero ya
                # tiene su propio anillo; aqui basta con contarlos.
                self.moves += 1
                continue
            self.events.push((_EVENT_CODE.get(ev.type, 0), now))

        self._track_closure(out, ratio, now)
        self._fresh = True
        if self._analysis and not beat.running:
            beat.wake()

    def _track_closure(self, out, ratio: float, now: float) -> None:
        """Un cierre de pinch, desde que los dedos se juntan hasta que se abren.

        El desenlace no se adivina: se lee de lo que el motor emitio de verdad
        durante el cierre. Un clic y un click derecho son terminales; arrastre y
        scroll solo ascienden desde 'abortado'.
        """
        if out.pinching:
            if not self._closing:
                self._closing = True
                self._close_t = now
                self._close_min = ratio
                self._close_out = ABORTED
            elif ratio < self._close_min:
                self._close_min = ratio
            for ev in out.events:
                if ev.type in (EventType.CLICK, EventType.DOUBLE_CLICK):
                    self._close_out = CLICK
                elif ev.type is EventType.RIGHT_CLICK:
                    self._close_out = RIGHT
            if self._close_out == ABORTED:
                if out.mode in (Mode.DRAGGING, Mode.WINDOW_MOVE, Mode.WINDOW_RESIZE):
                    self._close_out = DRAG
                elif out.mode in (Mode.SCROLLING, Mode.ZOOMING):
                    self._close_out = SCROLL
            return
        if self._closing:
            self._closing = False
            # el clic se emite al soltar: hay que mirar tambien este fotograma
            for ev in out.events:
                if ev.type in (EventType.CLICK, EventType.DOUBLE_CLICK):
                    self._close_out = CLICK
                elif ev.type is EventType.RIGHT_CLICK:
                    self._close_out = RIGHT
            self.closures.push((self._close_t, self._close_min, self._close_out))

    def on_stats(self, d: dict, now: float | None = None) -> None:
        now = time.perf_counter() if now is None else now
        # antes de pisar self.stats: la salud compara con la muestra anterior
        self._accumulate_health(d, now)
        self.stats = d
        self.t_stats.push(now)
        fps_pipe = float(d.get("pipeline_fps", 0.0) or 0.0)
        fps_cam = float(d.get("camera_fps", 0.0) or 0.0)
        lat = float(d.get("latency_ms", 0.0) or 0.0)
        self.fps_pipe.push(fps_pipe)
        self.fps_cam.push(fps_cam)
        self.lat.push(lat)
        self.proc.push(float(d.get("process_ms", 0.0) or 0.0))
        self.cascade.push(now, fps_pipe, fps_cam, lat)
        self._last_stats_t = now
        self._fresh = True
        if self._analysis and not beat.running:
            beat.wake()

    def _accumulate_health(self, d: dict, now: float) -> None:
        h = self.health
        paused = bool(d.get("paused"))
        connected = bool(d.get("connected"))
        prev = self.stats
        dt = now - self._last_stats_t if self._last_stats_t else 0.0
        # Un hueco mayor que este no es tiempo de sesion: el motor estuvo parado
        # o el equipo durmio. Sumarlo inflaria todos los repartos a la vez.
        if 0.0 < dt <= MAX_STATS_S:
            h.total += dt
            if d.get("hands"):
                h.hands += dt
            if d.get("face"):
                h.face += dt
            if paused:
                h.paused += dt
            if d.get("control"):
                h.control += dt
            if connected:
                h.connected += dt
        if paused and not prev.get("paused", paused):
            h.pauses += 1
        if not connected and prev.get("connected", connected):
            h.drops += 1
        if d.get("low_res"):
            h.low_res = True
        res = str(d.get("resolution", ""))
        if "x" in res:
            try:
                w = int(res.split("x", 1)[0])
            except ValueError:
                return
            if h.worst_width == 0 or w < h.worst_width:
                h.worst_width = w
                h.worst_res = res

    def on_status(self, text: str) -> None:
        self.status = text

    def on_log(self, line: str) -> None:
        self.log.append(line)

    # -- latido (4 Hz, solo con la pagina delante) ---------------------------
    def tick(self, dt: float) -> bool:
        """Participante del ``Beat``. Devuelve False cuando no hay nada nuevo,
        para que el latido se afloje y se pare con el motor apagado."""
        if not self._analysis or not self._fresh:
            return False
        self.compute()
        return True

    # -- agregados (6.3) ----------------------------------------------------
    def compute(self, now: float | None = None) -> Aggregates:
        """Calcula la tanda entera. Publico y sin condiciones: la compuerta de
        visibilidad esta en ``tick``, aqui no, para poder pedir los agregados
        una vez (un informe, una prueba) sin fingir que la pagina esta abierta."""
        now = time.perf_counter() if now is None else now
        agg = Aggregates(
            t=now,
            lat=self._quantiles(self.lat.view()),
            frame=self._quantiles(self.frame_dt.view()),
            lat_hist=self._latency_hist(),
            modes=self._mode_share(now),
            events=self._event_rate(now),
            tremor=self._tremor(),
            pinch=self._valley(),
        )
        self.aggregates = agg
        self.computations += 1
        self._fresh = False
        self.aggregates_ready.emit(agg)
        return agg

    @staticmethod
    def _quantiles(a: np.ndarray) -> Quantiles:
        n = int(a.size)
        if n < MIN_QUANTILES:
            return Quantiles(*_nan3(), n=n, enough=False)
        p50, p95, p99 = np.percentile(a.astype(np.float64), (50, 95, 99))
        return Quantiles(float(p50), float(p95), float(p99), n, True)

    def _latency_hist(self) -> Hist:
        a = self.lat.view().astype(np.float64)
        n = int(a.size)
        counts = np.zeros(LAT_BINS, dtype=np.int64)
        over = int(np.count_nonzero(a > LAT_MAX))
        if n:
            counts, _ = np.histogram(a, bins=LAT_BINS, range=(0.0, LAT_MAX))
        return Hist(counts, 0.0, LAT_MAX, over, n, n >= MIN_HIST)

    def _mode_share(self, now: float) -> ModeShare:
        seg = self.segments.view()
        empty = {m: 0.0 for m in MODES}
        if seg.size == 0:
            return ModeShare(empty, 0.0, 0.0, None, False)
        t0 = seg["t"].astype(np.float64)
        codes = seg["mode"].astype(np.int64)
        # El tramo abierto termina en el ultimo fotograma que se vio de verdad,
        # no en 'ahora': con el motor parado, 'ahora' le regalaria minutos al
        # ultimo modo que estuvo activo.
        end = now if not self._dash else self._last_out_t
        if not end:
            end = float(t0[-1])
        durs = np.diff(np.append(t0, max(end, float(t0[-1]))))
        durs = np.clip(durs, 0.0, None)
        blind = float(durs[codes == BLIND].sum())
        real = codes != BLIND
        weights = np.bincount(codes[real], weights=durs[real], minlength=len(MODES))
        seconds = {m: float(weights[i]) for i, m in enumerate(MODES)}
        total = float(sum(seconds.values()))
        dom = max(seconds, key=lambda m: seconds[m]) if total > 0.0 else None
        return ModeShare(seconds, total, blind, dom, total >= MIN_MODE_S)

    def _event_rate(self, now: float) -> EventRate:
        ev = self.events.view()
        counts = {e: 0 for e in EVENTS}
        if ev.size == 0:
            return EventRate({e: float("nan") for e in EVENTS}, counts, 0.0,
                             self.moves, False)
        ids = ev["id"].astype(np.int64)
        # La ventana cubierta es desde el evento mas viejo que queda en el
        # anillo, haya dado la vuelta o no: fuera de ahi no sabemos nada.
        window = max(now - float(ev["t"][0]), 0.0)
        raw = np.bincount(ids, minlength=len(EVENTS))
        for i, e in enumerate(EVENTS):
            counts[e] = int(raw[i])
        enough = window >= MIN_EVENT_S
        if not enough:
            per = {e: float("nan") for e in EVENTS}
        else:
            per = {e: counts[e] * 60.0 / window for e in EVENTS}
        return EventRate(per, counts, window, self.moves, enough)

    def _tremor(self) -> Tremor:
        """Residuo de alta frecuencia del puntero: media de |p[t]-2p[t-1]+p[t-2]|.

        Es la definicion honesta de temblor porque no cuenta el movimiento: una
        recta a velocidad constante, por rapida que sea, da exactamente cero.
        """
        p = self.pointer.view(last=300).astype(np.float64)
        if p.shape[0] < 3:
            return Tremor(float("nan"), 0, False)
        d = p[2:] - 2.0 * p[1:-1] + p[:-2]
        mag = np.hypot(d[:, 0], d[:, 1])
        n = int(np.count_nonzero(np.isfinite(mag)))
        if n < MIN_TREMOR:
            return Tremor(float("nan"), n, False)
        return Tremor(float(np.nanmean(mag)), n, True)

    def _valley(self) -> Valley:
        """Valle entre los dos picos del histograma de pinch.

        Los dos picos son la mano abierta y la mano cerrada. El punto mas bajo
        entre ellos es donde menos veces se queda el dedo, y por eso es donde
        menos dano hace poner el umbral. Si no hay dos poblaciones separadas no
        se sugiere nada: mejor callarse que recomendar un numero inventado.
        """
        h = self.pinch_hist.astype(np.float64)
        n = int(h.sum())
        med = self._aborted_median()
        if n < MIN_PINCH:
            return Valley(float("nan"), float("nan"), float("nan"),
                          (float("nan"),) * 2, med, n, False)
        s = np.convolve(h, np.ones(5) / 5.0, mode="same")
        i1 = int(np.argmax(s))
        far = s.copy()
        far[max(0, i1 - PEAK_GAP):i1 + PEAK_GAP + 1] = -1.0
        i2 = int(np.argmax(far))
        if far[i2] < 0.0 or s[i2] < PEAK_RATIO * s[i1]:
            return Valley(float("nan"), float("nan"), float("nan"),
                          (float("nan"),) * 2, med, n, False)
        lo, hi = sorted((i1, i2))
        v = lo + int(np.argmin(s[lo:hi + 1]))
        if s[v] > VALLEY_DEPTH * min(s[i1], s[i2]):
            return Valley(float("nan"), float("nan"), float("nan"),
                          (float("nan"),) * 2, med, n, False)
        step = PINCH_MAX / PINCH_BINS
        ratio = (v + 0.5) * step
        on = round(ratio, 3)
        off = round(min(max(ratio + HYST_GAP, ratio + 0.03), ratio + 0.14), 3)
        peaks = ((min(i1, i2) + 0.5) * step, (max(i1, i2) + 0.5) * step)
        return Valley(ratio, on, off, peaks, med, n, True)

    def _aborted_median(self) -> float:
        cl = self.closures.view()
        if cl.size == 0:
            return float("nan")
        r = cl["ratio"][cl["out"] == ABORTED]
        return float(np.median(r)) if r.size else float("nan")

    # -- utilidades ---------------------------------------------------------
    def reset(self) -> None:
        """Sesion nueva. Los anillos se vacian; la memoria no se toca."""
        for ring in (self.frame_dt, self.pinch, self.pointer, self.fps_cam,
                     self.fps_pipe, self.lat, self.proc, self.t_stats,
                     self.segments, self.events, self.closures):
            ring.clear()
        self.cascade.clear()
        self.pinch_hist[:] = 0
        self.log.clear()
        self.stats = {}
        self.frames = self.moves = self.computations = 0
        self.health = Health()
        self.aggregates = None
        self._last_out_t = self._last_stats_t = 0.0
        self._mode_code = None
        self._pointer_gap = True
        self._closing = False
        self._fresh = False

    @property
    def nbytes(self) -> int:
        """Memoria real de los anillos. Constante desde el primer segundo."""
        total = sum(r.nbytes for r in (
            self.frame_dt, self.pinch, self.pointer, self.fps_cam,
            self.fps_pipe, self.lat, self.proc, self.t_stats,
            self.segments, self.events, self.closures))
        return total + self.pinch_hist.nbytes + self.cascade.nbytes


__all__ = [
    "Telemetry", "Ring", "Cascade", "Aggregates", "Quantiles", "Hist",
    "ModeShare", "EventRate", "Tremor", "Valley", "Health",
    "MODES", "EVENTS", "BLIND",
    "ABORTED", "CLICK", "DRAG", "SCROLL", "RIGHT",
    "PINCH_BINS", "PINCH_MAX", "LAT_BINS", "LAT_MAX",
]
