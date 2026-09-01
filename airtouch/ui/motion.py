"""El movimiento de toda la interfaz: un solo latido, cuatro curvas, dos integradores.

La pieza importante es ``Beat``. Antes habia siete temporizadores sueltos (Dot,
SegmentedControl, PinchGauge, NavRail, GestureIndicator, Ring, StepDots), cada
uno despertando la CPU por su cuenta a su propio ritmo: en un portatil flojo eso
se nota con la ventana quieta y sin nada que animar. Aqui hay un unico QTimer de
16 ms al que los widgets se apuntan con ``beat.join(self)`` y del que se dan de
baja en ``hideEvent`` con ``beat.leave(self)``. Cada participante expone
``tick(dt) -> bool``; mientras nadie devuelva True el latido se afloja y se para
solo.

Para animar datos en vivo estan ``Smooth`` (suavizado exponencial) y ``Spring``
(integrador con velocidad). Nunca ``QPropertyAnimation``: el objetivo cambia
antes de que la animacion termine y se ve el tiron.
"""
from __future__ import annotations

import math
import time
import weakref
from typing import Callable, Protocol

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QObject, QPointF, QPropertyAnimation,
    QRectF, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

# --------------------------------------------------------------------------- #
# curvas (5.2)
# --------------------------------------------------------------------------- #

# entradas de lamina y transiciones de pagina: arranca muy rapido y se asienta
# largo, que es lo que hace que un objeto pesado parezca pesado
EASE_GLASS = QEasingCurve(QEasingCurve.Type.OutQuint)
# reflujos de layout, cambios de tamanyo, barridos. Nunca para entradas
EASE_SOFT = QEasingCurve(QEasingCurve.Type.InOutCubic)
# todo lo que se acerca al usuario. El sobrepaso por defecto de Qt (1.70) es de
# dibujos animados; con 1.12 se nota como un aterrizaje, no como un muelle
EASE_LIFT = QEasingCurve(QEasingCurve.Type.OutBack)
EASE_LIFT.setOvershoot(1.12)
# las salidas: un objeto que se va no merece atencion
EASE_EXIT = QEasingCurve(QEasingCurve.Type.InQuad)

# --------------------------------------------------------------------------- #
# duraciones (5.4) y constantes de tiempo (5.3)
# --------------------------------------------------------------------------- #

MICRO_IN, MICRO_OUT = 120, 90          # hover, pulsacion, perilla, filo
ELEMENT = 200                          # alzado de lamina, badge, tooltip, chip
SECTION_IN, SECTION_OUT = 340, 200     # cambio de pagina del panel
SECTION_OVERLAP = 120                  # la entrante arranca antes de irse la otra
HERO = 520                             # pagina del asistente, tarjeta a pagina
CELEBRATION = 900
SWEEP = 620                            # barrido especular
BREATH = 3200                          # respiracion del Nucleo
DRIFT_MIN, DRIFT_MAX = 8000, 14000     # deriva de las manchas del lienzo

STAGGER_STEP = 45                      # retardo entre hijos
STAGGER_DUR = 380
STAGGER_MAX = 6                        # del septimo en adelante entran con el sexto
STAGGER_RISE = 14.0                    # px que sube cada hijo al entrar

# tau en segundos. Los medidores van lentos a proposito: mas rapido tiemblan y
# la interfaz parece rota aunque el dato sea correcto
TAU_MINIMAP = 0.055
TAU_PINCH = 0.045
TAU_CATAPULT = 0.06
TAU_METER = 0.28
TAU_MODE_COLOR = 0.13
TAU_RING = 0.20
TAU_HISTOGRAM = 0.35
TAU_DONUT = 0.25
TAU_CAPSULE = 0.12
TAU_CURSOR = 0.055
TAU_OVERLAY_PINCH = 0.07
TAU_WINDOW_BAR = 0.10
TAU_KEYBOARD = 0.38

# compuertas de frecuencia del Beat (5.1)
HZ_FULL = 60      # cursor, arrastre, deriva de valores
HZ_GLOW = 20      # respiraciones y glows
HZ_CANVAS = 10    # lienzo
HZ_STATS = 4      # agregados de estadisticas

_REDUCE = False


def set_reduce_motion(value: bool) -> None:
    """Lo llama la aplicacion al arrancar y al cambiar ``cfg.ui.reduce_motion``."""
    global _REDUCE
    _REDUCE = bool(value)


def reduce_motion() -> bool:
    return _REDUCE


def dur(ms: int) -> int:
    """Duracion efectiva. Con reduce_motion todo se encoge al 35 %."""
    return max(1, int(ms * 0.35)) if _REDUCE else int(ms)


def exit_of(ms_in: int) -> int:
    """Salida = 0.6 x entrada. Regla general cuando la spec no da el par."""
    return dur(int(round(ms_in * 0.6)))


def ease(t: float, curve: QEasingCurve = EASE_GLASS) -> float:
    return curve.valueForProgress(max(0.0, min(1.0, t)))


# --------------------------------------------------------------------------- #
# el latido (5.1)
# --------------------------------------------------------------------------- #

class Ticker(Protocol):
    def tick(self, dt: float) -> bool: ...


class _Seat:
    """Sitio de un participante en el latido, con su compuerta de frecuencia."""

    __slots__ = ("ref", "period", "acc", "busy")

    def __init__(self, obj: object, period: float) -> None:
        self.ref = weakref.ref(obj)
        self.period = period
        self.acc = 0.0
        self.busy = True


class Beat(QObject):
    """El unico temporizador animado de la ventana.

    ``advance()`` es publico a proposito: asi se puede comprobar el reparto sin
    levantar un bucle de eventos. El QTimer se limita a llamarlo con el reloj de
    verdad.
    """

    saving_changed = Signal(bool)

    INTERVAL = 16
    IDLE_INTERVAL = 33
    IDLE_STOP = 0.5

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._seats: list[_Seat] = []
        self._timer: QTimer | None = None
        self._last = time.perf_counter()
        self._idle_since: float | None = None
        self._saving = False
        self._low_since: float | None = None
        self._high_since: float | None = None

    # -- participantes ------------------------------------------------------
    def join(self, obj: Ticker, hz: int = HZ_FULL) -> None:
        """Apunta un widget al latido.

        Se guarda una referencia debil: un widget que muere sin pasar por
        ``hideEvent`` no puede quedarse enganchado aqui manteniendose vivo.
        """
        for seat in self._seats:
            if seat.ref() is obj:
                seat.period = 1.0 / max(1, hz)
                return
        self._seats.append(_Seat(obj, 1.0 / max(1, hz)))
        self.wake()

    def leave(self, obj: object) -> None:
        self._seats = [s for s in self._seats if s.ref() is not obj]

    def wake(self) -> None:
        """Vuelve a 16 ms. Lo llama quien empieza a animar despues de un rato
        quieto: si no, el latido sigue parado y no se pinta nada."""
        self._idle_since = None
        self._last = time.perf_counter()
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._on_timeout)
        self._timer.start(self.IDLE_INTERVAL if self._saving else self.INTERVAL)

    @property
    def participants(self) -> int:
        return len(self._seats)

    @property
    def running(self) -> bool:
        return self._timer is not None and self._timer.isActive()

    def _on_timeout(self) -> None:
        self.advance()

    # -- reparto ------------------------------------------------------------
    def advance(self, now: float | None = None) -> None:
        now = time.perf_counter() if now is None else now
        dt = min(max(now - self._last, 0.0), 0.25)
        self._last = now
        # media trama de tolerancia: sin ella una compuerta de 60 Hz (16.67 ms)
        # nunca llega a tiempo en un latido de 16 ms y se queda en 30 Hz
        tol = self.INTERVAL / 2000.0
        busy = False
        muertos: list[_Seat] = []
        for seat in self._seats:
            obj = seat.ref()
            if obj is None:
                muertos.append(seat)
                continue
            seat.acc += dt
            if seat.acc + tol < seat.period:
                busy = busy or seat.busy
                continue
            paso, seat.acc = seat.acc, 0.0
            try:
                seat.busy = bool(obj.tick(paso))
            except RuntimeError:
                # el objeto de C++ ya no existe pero el envoltorio de Python si:
                # pasa al cerrar la ventana sin pasar por hideEvent
                muertos.append(seat)
                continue
            busy = busy or seat.busy
        for seat in muertos:
            self._seats.remove(seat)

        if self._timer is None:
            return
        if busy:
            self._idle_since = None
            objetivo = self.IDLE_INTERVAL if self._saving else self.INTERVAL
            if self._timer.interval() != objetivo:
                self._timer.start(objetivo)
        elif self._idle_since is None:
            self._idle_since = now
            self._timer.start(self.IDLE_INTERVAL)
        elif now - self._idle_since >= self.IDLE_STOP:
            self._timer.stop()

    # -- modo ahorro (5.6) --------------------------------------------------
    @property
    def saving(self) -> bool:
        return self._saving

    def report_fps(self, fps: float, now: float | None = None) -> bool:
        """Alimenta la histeresis con ``pipeline_fps``.

        Entra en ahorro por debajo de 24 fps sostenidos 3 s y sale por encima de
        30 sostenidos 5 s. La banda muerta entre 24 y 30 existe para que un
        equipo que ronda el umbral no entre y salga cada segundo: el parpadeo de
        la interfaz cambiando de modo se ve peor que quedarse en ahorro.
        """
        now = time.perf_counter() if now is None else now
        if not self._saving:
            self._high_since = None
            if fps >= 24.0:
                self._low_since = None
            elif self._low_since is None:
                self._low_since = now
            elif now - self._low_since >= 3.0:
                self._set_saving(True)
        else:
            self._low_since = None
            if fps <= 30.0:
                self._high_since = None
            elif self._high_since is None:
                self._high_since = now
            elif now - self._high_since >= 5.0:
                self._set_saving(False)
        return self._saving

    def _set_saving(self, value: bool) -> None:
        self._saving = value
        self._low_since = self._high_since = None
        if self._timer is not None and self._timer.isActive():
            self._timer.start(self.IDLE_INTERVAL if value else self.INTERVAL)
        self.saving_changed.emit(value)


beat = Beat()


# --------------------------------------------------------------------------- #
# valores continuos (5.3)
# --------------------------------------------------------------------------- #

class Smooth:
    """Valor que persigue a un objetivo con constante de tiempo fija.

    Interpolacion exponencial, asi que da igual el framerate: el mismo recorrido
    a 30 y a 144 fps.
    """

    __slots__ = ("value", "target", "tau", "_t")

    def __init__(self, value: float = 0.0, tau: float = 0.14) -> None:
        self.value = value
        self.target = value
        self.tau = tau
        self._t = time.perf_counter()

    def set(self, target: float) -> None:
        self.target = target

    def jump(self, value: float) -> None:
        self.value = self.target = value

    def step(self, now: float | None = None) -> float:
        now = now if now is not None else time.perf_counter()
        dt = min(max(now - self._t, 0.0), 0.1)
        self._t = now
        if self.tau <= 0:
            self.value = self.target
        else:
            a = 1.0 - math.exp(-dt / self.tau)
            self.value += (self.target - self.value) * a
        return self.value

    @property
    def settled(self) -> bool:
        return abs(self.target - self.value) < 1e-3


class Spring:
    """Integrador critico-subamortiguado (zeta 0.80, omega 15 rad/s).

    Se asienta en ~340 ms. Va donde el objeto parte con velocidades distintas:
    perilla del interruptor, pildora de navegacion, tarjeta que se levanta. Ahi
    no vale OutBack, porque rebota igual salga de donde salga; el muelle conserva
    la velocidad que ya llevaba y por eso no se ve el corte cuando el usuario
    cambia de idea a mitad del gesto. Con reduce_motion zeta pasa a 1.0 y deja de
    rebasar.

    ``eps`` es la distancia a la que se da por asentado. El valor por defecto
    sirve para fracciones 0..1; en pixeles hay que subirlo (0.25 px) o el muelle
    mantiene el latido despierto un segundo entero persiguiendo milesimas que no
    se ven.
    """

    SUBSTEP = 1.0 / 240.0

    __slots__ = ("value", "target", "velocity", "zeta", "omega", "eps")

    def __init__(self, value: float = 0.0, zeta: float = 0.80,
                 omega: float = 15.0, eps: float = 1e-3) -> None:
        self.value = value
        self.target = value
        self.velocity = 0.0
        self.zeta = zeta
        self.omega = omega
        self.eps = eps

    def set(self, target: float) -> None:
        self.target = target

    def jump(self, value: float) -> None:
        self.value = self.target = value
        self.velocity = 0.0

    def step(self, dt: float) -> float:
        # subpasos fijos: con dt de 33 ms la integracion explicita amortigua de
        # mas y el muelle se comportaria distinto segun los fps de cada equipo
        zeta = 1.0 if _REDUCE else self.zeta
        restante = min(max(dt, 0.0), 0.1)
        while restante > 1e-9:
            h = min(self.SUBSTEP, restante)
            restante -= h
            a = (-2.0 * zeta * self.omega * self.velocity
                 - self.omega * self.omega * (self.value - self.target))
            self.velocity += a * h
            self.value += self.velocity * h
        if self.settled:
            self.value = self.target
            self.velocity = 0.0
        return self.value

    @property
    def settled(self) -> bool:
        return (abs(self.target - self.value) < self.eps
                and abs(self.velocity) < self.eps * self.omega)


# --------------------------------------------------------------------------- #
# patrones (5.5)
# --------------------------------------------------------------------------- #

class Stagger:
    """Entrada escalonada: 45 ms entre hijos, 380 ms cada uno, EASE_GLASS.

    Es solo el reloj; quien pinta decide que hace con la opacidad y el
    desplazamiento. Solo al entrar en una pagina, jamas al actualizar datos: un
    dato que llega escalonado parece un fallo, no una animacion.
    """

    def __init__(self, count: int, on_frame: Callable[[], None]) -> None:
        self.count = max(0, count)
        self._on_frame = on_frame
        self._t = 0.0
        self._running = False

    def start(self) -> None:
        # con reduce_motion y en ahorro no hay escalonado: entra todo ya puesto
        quieto = _REDUCE or beat.saving
        self._t = self.total / 1000.0 if quieto else 0.0
        self._running = not quieto
        if self._running:
            beat.join(self, HZ_FULL)
        self._on_frame()

    def stop(self) -> None:
        self._running = False
        beat.leave(self)

    @property
    def total(self) -> int:
        ultimo = min(max(self.count - 1, 0), STAGGER_MAX - 1)
        return ultimo * STAGGER_STEP + STAGGER_DUR

    def delay(self, index: int) -> int:
        """Del septimo hijo en adelante todos entran junto al sexto."""
        return min(max(index, 0), STAGGER_MAX - 1) * STAGGER_STEP

    def state(self, index: int) -> tuple[float, float]:
        """Devuelve (opacidad, desplazamiento en Y) del hijo ``index``."""
        t = (self._t * 1000.0 - self.delay(index)) / STAGGER_DUR
        p = ease(t, EASE_GLASS)
        return p, (1.0 - p) * STAGGER_RISE

    def tick(self, dt: float) -> bool:
        if not self._running:
            return False
        self._t += dt
        self._on_frame()
        if self._t * 1000.0 >= self.total:
            self._running = False
            beat.leave(self)
            return False
        return True

    @property
    def done(self) -> bool:
        return not self._running


class SpecularSweep:
    """Banda de luz que cruza una lamina cuando cambia de estado de verdad.

    Una sola vez y nunca en bucle: en bucle deja de significar "ha pasado algo"
    y pasa a ser decoracion, que es justo lo que esta direccion no quiere.
    """

    WIDTH = 120.0
    ALPHA = 0.22
    TILT = 20.0    # grados respecto de la vertical

    def __init__(self, on_frame: Callable[[], None]) -> None:
        self._on_frame = on_frame
        self._t = 0.0
        self._running = False

    def start(self) -> None:
        if _REDUCE or beat.saving:
            return
        self._t = 0.0
        self._running = True
        beat.join(self, HZ_FULL)

    def tick(self, dt: float) -> bool:
        if not self._running:
            return False
        self._t += dt
        self._on_frame()
        if self._t * 1000.0 >= SWEEP:
            self._running = False
            beat.leave(self)
            return False
        return True

    @property
    def active(self) -> bool:
        return self._running

    def paint(self, p: QPainter, rect: QRectF, radius: float) -> None:
        if not self._running or rect.isEmpty():
            return
        t = ease(self._t * 1000.0 / SWEEP, EASE_SOFT)
        x = rect.left() - self.WIDTH + t * (rect.width() + 2.0 * self.WIDTH)
        cy = rect.center().y()
        rad = math.radians(self.TILT)
        # el degradado corre perpendicular a la banda; inclinarlo respecto de la
        # vertical es lo que lo hace parecer un reflejo y no un limpiaparabrisas
        nx = math.cos(rad) * self.WIDTH / 2.0
        ny = math.sin(rad) * self.WIDTH / 2.0
        grad = QLinearGradient(QPointF(x - nx, cy - ny), QPointF(x + nx, cy + ny))
        grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.5, QColor(255, 255, 255, int(self.ALPHA * 255)))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(rect, radius, radius)
        p.restore()


# --------------------------------------------------------------------------- #
# animacion de widgets (lo que absorbe de anim.py)
# --------------------------------------------------------------------------- #

def fade(widget: QWidget, start: float, end: float, duration: int = ELEMENT,
         on_done: Callable[[], None] | None = None) -> QPropertyAnimation:
    """Anima la opacidad de un widget.

    Al llegar a opacidad plena se retira el efecto: un QGraphicsEffect activo
    cuesta rendimiento y ademas impide que el widget aparezca en capturas.
    """
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(start)

    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(dur(duration))
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(EASE_GLASS if end >= start else EASE_EXIT)

    def _cleanup() -> None:
        if end >= 0.999:
            try:
                widget.setGraphicsEffect(None)
            except RuntimeError:
                pass
        if on_done is not None:
            on_done()

    anim.finished.connect(_cleanup)
    widget._fade_anim = anim  # type: ignore[attr-defined]
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
    return anim


def tween(start: float, end: float, duration: int,
          on_value: Callable[[float], None], parent: QObject | None = None,
          curve: QEasingCurve | QEasingCurve.Type = EASE_GLASS) -> QVariantAnimation:
    """Interpola un numero y llama a on_value en cada paso.

    Para datos en vivo no sirve: usa Smooth o Spring. Esto es para recorridos con
    principio y final conocidos.
    """
    anim = QVariantAnimation(parent)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(dur(duration))
    anim.setEasingCurve(curve)
    anim.valueChanged.connect(lambda v: on_value(float(v)))
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


__all__ = [
    "Beat", "beat", "Ticker", "Smooth", "Spring", "Stagger", "SpecularSweep",
    "EASE_GLASS", "EASE_SOFT", "EASE_LIFT", "EASE_EXIT", "ease",
    "MICRO_IN", "MICRO_OUT", "ELEMENT", "SECTION_IN", "SECTION_OUT",
    "SECTION_OVERLAP", "HERO", "CELEBRATION", "SWEEP", "BREATH",
    "DRIFT_MIN", "DRIFT_MAX", "STAGGER_STEP", "STAGGER_DUR", "STAGGER_MAX",
    "STAGGER_RISE", "HZ_FULL", "HZ_GLOW", "HZ_CANVAS", "HZ_STATS",
    "TAU_MINIMAP", "TAU_PINCH", "TAU_CATAPULT", "TAU_METER", "TAU_MODE_COLOR",
    "TAU_RING", "TAU_HISTOGRAM", "TAU_DONUT", "TAU_CAPSULE", "TAU_CURSOR",
    "TAU_OVERLAY_PINCH", "TAU_WINDOW_BAR", "TAU_KEYBOARD",
    "dur", "exit_of", "reduce_motion", "set_reduce_motion", "fade", "tween",
]
