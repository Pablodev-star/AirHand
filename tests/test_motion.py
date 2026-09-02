"""Pruebas de airtouch/ui/motion.py sin abrir ninguna ventana.

Todo lo que se comprueba aqui es aritmetica de reloj, asi que no hace falta ni
bucle de eventos ni pantalla: ``Beat.advance(now)``, ``Spring.step(dt)`` y
``Smooth.step(now)`` aceptan el instante por parametro justamente para esto. Si
hubiera que dejar correr un QTimer de verdad, una prueba del reparto a 4 Hz
tardaria varios segundos y ademas seria irrepetible.

    .venv\\Scripts\\python.exe tests\\test_motion.py
"""
from __future__ import annotations

import gc
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Sin pantalla: la maquina de integracion no tiene ninguna y aqui no se pinta.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QTimer          # noqa: E402

from airtouch.ui import motion                               # noqa: E402

# QTimer.start() necesita un despachador de eventos en el hilo o Qt avisa por
# consola y isActive() deja de ser fiable. No se llega a arrancar el bucle: los
# temporizadores no llegan a disparar y el reparto se conduce a mano.
_APP = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])

MARCO = motion.Beat.INTERVAL / 1000.0   # 16 ms, el latido nominal


class Contador:
    """Participante que siempre quiere seguir animando."""

    def __init__(self) -> None:
        self.n = 0
        self.dt = 0.0

    def tick(self, dt: float) -> bool:
        self.n += 1
        self.dt += dt
        return True


class Inerte:
    """Participante que nunca tiene nada que animar."""

    def __init__(self) -> None:
        self.n = 0

    def tick(self, dt: float) -> bool:
        self.n += 1
        return False


class Zombi:
    """Envoltorio de Python cuyo objeto de C++ ya no existe.

    Es el caso que describe el propio comentario de ``advance``: la ventana se
    cierra sin pasar por hideEvent y el widget sigue apuntado al latido.
    """

    def tick(self, dt: float) -> bool:
        raise RuntimeError("Internal C++ object already deleted.")


class Expulsor:
    """Al animarse da de baja a otro participante.

    Pasa de verdad: una tarjeta que cambia de estado oculta a sus hijos, y el
    hideEvent de cada hijo llama a ``beat.leave``, todo dentro del tick.
    """

    def __init__(self, latido: motion.Beat, victima: object) -> None:
        self._latido = latido
        self._victima = victima

    def tick(self, dt: float) -> bool:
        self._latido.leave(self._victima)
        return False


def avanzar(latido: motion.Beat, marcos: int, paso: float = MARCO) -> float:
    """Corre ``marcos`` latidos con reloj ficticio. Devuelve el tiempo simulado.

    El origen sale del reloj interno del latido y no de perf_counter: dos
    llamadas seguidas con origenes distintos producirian un dt negativo, el
    latido lo recortaria a cero y se perderia un aviso justo en la frontera.
    """
    t = latido._last
    for i in range(1, marcos + 1):
        latido.advance(t + i * paso)
    return marcos * paso


def sincronizar(s: motion.Smooth) -> float:
    """Pone el reloj interno de un Smooth en el instante que se devuelve.

    Smooth arranca su reloj en el constructor, asi que un origen tomado despues
    mete unos microsegundos de mas en el primer paso: poco para verse, bastante
    para que dos recorridos que deberian ser identicos no lo sean. Este paso en
    falso no mueve nada porque valor y objetivo aun coinciden.
    """
    t0 = time.perf_counter()
    s.step(t0)
    return t0


# --------------------------------------------------------------------------- #
# 5.1 el latido
# --------------------------------------------------------------------------- #

def test_beat_un_solo_temporizador() -> None:
    b = motion.Beat()
    assert b._timer is None, "no debe haber temporizador antes del primer join"

    a, c, d = Contador(), Contador(), Contador()
    b.join(a)
    primero = b._timer
    assert primero is not None and b.running, "join tiene que arrancar el latido"

    b.join(c, motion.HZ_GLOW)
    b.join(d, motion.HZ_CANVAS)
    b.leave(c)
    b.wake()
    b.join(c, motion.HZ_STATS)

    assert b._timer is primero, "join/leave/wake no pueden crear otro QTimer"
    hijos = b.findChildren(QTimer)
    assert len(hijos) == 1, f"el latido tiene {len(hijos)} QTimer, deberia tener 1"
    print("  OK  el latido usa un unico QTimer para toda la ventana")


def test_beat_patrones_sin_temporizador_propio() -> None:
    """Stagger y SpecularSweep tienen que ir montados en el latido, no aparte."""
    antes = motion.beat.participants

    sweep = motion.SpecularSweep(lambda: None)
    sweep.start()
    escalonado = motion.Stagger(4, lambda: None)
    escalonado.start()

    assert motion.beat.participants == antes + 2, \
        "los patrones deben apuntarse al latido compartido"
    for obj in (sweep, escalonado):
        propios = [v for v in vars(obj).values() if isinstance(v, QTimer)]
        assert not propios, f"{type(obj).__name__} se ha creado un QTimer propio"

    escalonado.stop()
    motion.beat.leave(sweep)
    assert motion.beat.participants == antes
    print("  OK  Stagger y SpecularSweep no crean temporizadores sueltos")


def test_beat_join_y_leave() -> None:
    b = motion.Beat()
    a, c = Contador(), Contador()

    b.join(a)
    b.join(c)
    assert b.participants == 2, "join no ha dado de alta"
    b.join(a)
    assert b.participants == 2, "join dos veces no puede duplicar el asiento"

    avanzar(b, 5)
    assert a.n == 5 and c.n == 5, f"reparto irregular: {a.n} y {c.n} de 5"

    b.leave(a)
    assert b.participants == 1, "leave no ha dado de baja"
    avanzar(b, 5)
    assert a.n == 5, "un participante dado de baja no puede seguir recibiendo avisos"
    assert c.n == 10, f"el que sigue apuntado ha recibido {c.n} avisos de 10"

    # referencia debil: un widget que muere sin pasar por hideEvent no puede
    # quedarse enganchado al latido manteniendose vivo
    huerfano = Contador()
    b.join(huerfano)
    assert b.participants == 2
    del huerfano
    gc.collect()
    avanzar(b, 1)
    assert b.participants == 1, "el asiento de un objeto muerto no se ha recogido"
    print("  OK  join da de alta, leave da de baja y los muertos se recogen")


def test_beat_compuertas_de_frecuencia() -> None:
    b = motion.Beat()
    full, glow, lienzo, stats = Contador(), Contador(), Contador(), Contador()
    b.join(full, motion.HZ_FULL)
    b.join(glow, motion.HZ_GLOW)
    b.join(lienzo, motion.HZ_CANVAS)
    b.join(stats, motion.HZ_STATS)

    marcos = 625                       # 10 s de reloj ficticio a 16 ms
    segundos = avanzar(b, marcos)

    assert full.n == marcos, \
        f"un cliente a 60 Hz debe recibir todos los latidos ({full.n} de {marcos})"
    # el enunciado del reparto: 20 Hz recibe aproximadamente un tercio de 60 Hz
    razon = glow.n / full.n
    assert 0.30 <= razon <= 0.36, f"20 Hz recibe {razon:.3f} de los avisos, no ~1/3"
    assert 0.14 <= lienzo.n / full.n <= 0.19, "el lienzo no va a ~1/6"
    assert 0.055 <= stats.n / full.n <= 0.075, "las estadisticas no van a ~1/15"

    # y en Hz de verdad, que es lo que dice la spec
    assert 19.0 <= glow.n / segundos <= 21.5
    assert 9.5 <= lienzo.n / segundos <= 11.0
    assert 3.5 <= stats.n / segundos <= 4.2

    # el dt que recibe cada uno es el suyo, no el del latido: si no, un medidor
    # a 4 Hz integraria 16 ms cuando han pasado 250
    assert abs(full.dt - segundos) < 0.05
    assert abs(stats.dt - segundos) < 0.30
    print("  OK  las compuertas reparten a 60 / 20 / 10 / 4 Hz")


def test_beat_afloja_y_se_para() -> None:
    b = motion.Beat()
    inerte = Inerte()
    b.join(inerte)
    assert b._timer.interval() == motion.Beat.INTERVAL

    t0 = time.perf_counter()
    b.advance(t0 + MARCO)
    assert b._timer.interval() == motion.Beat.IDLE_INTERVAL, \
        "sin nadie animando el latido tiene que aflojar a 33 ms"
    assert b.running, "no puede pararse en el mismo momento de aflojar"

    b.advance(t0 + MARCO + motion.Beat.IDLE_STOP)
    assert not b.running, "a los 500 ms quietos el temporizador tiene que pararse"

    b.wake()
    assert b.running and b._timer.interval() == motion.Beat.INTERVAL, \
        "wake tiene que devolver el latido a 16 ms"
    print("  OK  el latido afloja a 33 ms, se para a los 500 ms y wake lo revive")


def test_beat_baja_desde_dentro_del_tick() -> None:
    """Un leave() dentro de un tick no puede romper el reparto de ese latido."""
    b = motion.Beat()
    zombi = Zombi()
    testigo = Contador()
    # el latido guarda referencias debiles, asi que el expulsor tiene que vivir
    # en una variable o se lo lleva el recolector antes del primer aviso
    expulsor = Expulsor(b, zombi)
    b.join(expulsor)                   # va primero: expulsa antes de que toque
    b.join(zombi)
    b.join(testigo)

    avanzar(b, 1)

    assert testigo.n == 1, "el resto de participantes se ha quedado sin latido"
    assert b.participants == 2, "el asiento del zombi tenia que desaparecer"
    print("  OK  darse de baja desde dentro de tick no rompe el latido")


# --------------------------------------------------------------------------- #
# 5.6 modo ahorro
# --------------------------------------------------------------------------- #

def test_ahorro_entra_a_los_3s() -> None:
    b = motion.Beat()
    avisos: list[bool] = []
    b.saving_changed.connect(avisos.append)
    t = 1000.0

    b.report_fps(18.0, t)
    b.report_fps(18.0, t + 2.9)
    assert not b.saving, "2.9 s por debajo de 24 fps no bastan"

    b.report_fps(60.0, t + 2.95)
    b.report_fps(18.0, t + 3.0)
    b.report_fps(18.0, t + 5.9)
    assert not b.saving, "un fotograma bueno tiene que reiniciar la cuenta"

    b.report_fps(18.0, t + 6.0)
    assert b.saving, "3 s seguidos por debajo de 24 fps tienen que entrar en ahorro"
    assert avisos == [True], "saving_changed no ha avisado exactamente una vez"

    # 24 fps clavados no son "por debajo de 24"
    b2 = motion.Beat()
    for i in range(20):
        b2.report_fps(24.0, t + i * 0.5)
    assert not b2.saving, "24.0 fps exactos no pueden entrar en ahorro"
    print("  OK  el ahorro entra a los 3 s por debajo de 24 fps, no antes")


def test_ahorro_sale_a_los_5s() -> None:
    b = motion.Beat()
    t = 1000.0
    b.report_fps(10.0, t)
    b.report_fps(10.0, t + 3.0)
    assert b.saving

    avisos: list[bool] = []
    b.saving_changed.connect(avisos.append)

    b.report_fps(45.0, t + 3.0)
    b.report_fps(45.0, t + 7.9)
    assert b.saving, "4.9 s por encima de 30 fps no bastan para salir"

    b.report_fps(28.0, t + 7.95)
    b.report_fps(45.0, t + 8.0)
    b.report_fps(45.0, t + 12.9)
    assert b.saving, "un fotograma flojo tiene que reiniciar la cuenta de salida"

    b.report_fps(45.0, t + 13.0)
    assert not b.saving, "5 s seguidos por encima de 30 fps tienen que salir del ahorro"
    assert avisos == [False]

    # 30 fps clavados caen en la banda muerta: ni entra ni sale
    b2 = motion.Beat()
    b2.report_fps(10.0, t)
    b2.report_fps(10.0, t + 3.0)
    assert b2.saving
    for i in range(40):
        b2.report_fps(30.0, t + 3.0 + i * 0.5)
    assert b2.saving, "30.0 fps exactos no pueden sacar del ahorro"
    print("  OK  el ahorro sale a los 5 s por encima de 30 fps, con banda muerta")


def test_ahorro_afloja_el_latido() -> None:
    b = motion.Beat()
    b.join(Contador())
    assert b._timer.interval() == motion.Beat.INTERVAL

    t = 2000.0
    b.report_fps(10.0, t)
    b.report_fps(10.0, t + 3.0)
    assert b.saving
    assert b._timer.interval() == motion.Beat.IDLE_INTERVAL, \
        "en ahorro el latido tiene que ir a 33 ms"

    # y ahi se queda aunque haya trabajo: avanzar no puede devolverlo a 16 ms
    avanzar(b, 4)
    assert b._timer.interval() == motion.Beat.IDLE_INTERVAL
    print("  OK  en ahorro el latido baja a 33 ms y se queda")


# --------------------------------------------------------------------------- #
# 5.3 valores continuos
# --------------------------------------------------------------------------- #

def test_spring_converge_sin_oscilar() -> None:
    s = motion.Spring(0.0)
    assert s.zeta == 0.80 and s.omega == 15.0, "la spec fija zeta 0.80 y omega 15"
    s.set(1.0)

    valores = [s.step(MARCO) for _ in range(125)]        # 2 s
    assert s.settled, "el muelle no se ha asentado en 2 s"
    assert s.value == 1.0 and s.velocity == 0.0, \
        "al asentarse tiene que clavarse en el objetivo, no quedarse cerca"
    assert valores[-30:] == [1.0] * 30, "sigue moviendose despues de asentarse"

    pico = max(valores)
    assert 1.002 <= pico <= 1.05, \
        f"rebasamiento {pico - 1.0:.4f}: tiene que rebasar un poco, no como un dibujo"

    # se asienta en ~340 ms (criterio del 2 %), que es lo que promete la spec
    s2 = motion.Spring(0.0)
    s2.set(1.0)
    for _ in range(int(round(0.34 / MARCO))):
        s2.step(MARCO)
    assert abs(s2.value - 1.0) <= 0.02, \
        f"a los 340 ms va por {s2.value:.4f}, deberia estar dentro del 2 %"

    # el paso de integracion es fijo: los mismos 500 ms a 16 y a 33 ms de latido
    # tienen que llevar al mismo sitio, o el muelle se comportaria distinto en
    # cada equipo
    a = motion.Spring(0.0)
    a.set(1.0)
    for _ in range(30):
        a.step(1.0 / 60.0)
    c = motion.Spring(0.0)
    c.set(1.0)
    for _ in range(15):
        c.step(1.0 / 30.0)
    assert abs(a.value - c.value) < 5e-3, \
        f"depende del framerate: {a.value:.5f} a 60 fps contra {c.value:.5f} a 30"
    print("  OK  Spring converge, rebasa poco y no depende del framerate")


def test_spring_conserva_velocidad() -> None:
    """Cambiar de objetivo a mitad de camino no puede producir un corte."""
    s = motion.Spring(0.0)
    s.set(1.0)
    for _ in range(8):
        s.step(MARCO)
    v = s.velocity
    assert v > 0.0
    s.set(0.0)
    s.step(MARCO)
    assert s.velocity < v, "el muelle tiene que frenar, no saltar"
    assert s.value > 0.0, "no puede teletransportarse al nuevo objetivo"
    for _ in range(200):
        s.step(MARCO)
    assert s.value == 0.0
    print("  OK  Spring conserva la velocidad al cambiar de objetivo")


def test_spring_reduce_motion() -> None:
    motion.set_reduce_motion(True)
    try:
        s = motion.Spring(0.0)
        s.set(1.0)
        pico = max(s.step(MARCO) for _ in range(125))
        assert pico <= 1.0005, f"con reduce_motion zeta es 1.0 y no rebasa (pico {pico})"
        assert s.settled and s.value == 1.0
    finally:
        motion.set_reduce_motion(False)
    print("  OK  con reduce_motion el muelle deja de rebasar")


def test_smooth_converge() -> None:
    s = motion.Smooth(0.0, tau=0.14)
    t0 = sincronizar(s)
    s.set(1.0)
    for i in range(1, 91):                              # 1.44 s
        s.step(t0 + i * MARCO)
    assert s.settled, f"Smooth no converge: {s.value:.6f}"
    assert abs(s.value - 1.0) < 1e-3

    # independencia del framerate: es la razon de ser de la interpolacion
    # exponencial, y lo que separa a Smooth de un lerp por frame
    rapido = motion.Smooth(0.0, tau=0.14)
    t0 = sincronizar(rapido)
    rapido.set(1.0)
    for i in range(1, 25):
        rapido.step(t0 + i * 0.01)
    lento = motion.Smooth(0.0, tau=0.14)
    t0 = sincronizar(lento)
    lento.set(1.0)
    for i in range(1, 7):
        lento.step(t0 + i * 0.04)
    assert abs(rapido.value - lento.value) < 1e-9, \
        f"depende del framerate: {rapido.value:.9f} contra {lento.value:.9f}"
    print("  OK  Smooth converge y da igual el framerate")


def test_integradores_aguantan_el_paso_de_la_compuerta_lenta() -> None:
    """Un paso de 250 ms de la compuerta de 4 Hz tiene que integrarse entero.

    Es la costura entre 5.1 y 5.3, y por eso no la veia ninguna prueba de una
    sola pieza: el recorte de dt estaba en 0.1 s, asi que un medidor de fps
    (tau 0.28, que la spec pone justo en la compuerta de estadisticas) se comia
    el 60 % de cada paso y tardaba 2.5 s en cruzar en vez de 1.
    """
    assert motion.MAX_STEP >= 1.0 / motion.HZ_STATS, \
        "el techo de integracion no puede ser menor que el paso de la compuerta mas lenta"

    rapido = motion.Smooth(0.0, tau=motion.TAU_METER)
    t0 = sincronizar(rapido)
    rapido.set(1.0)
    for i in range(1, 63):                              # 1 s a 60 Hz
        rapido.step(t0 + i * MARCO)

    lento = motion.Smooth(0.0, tau=motion.TAU_METER)
    t0 = sincronizar(lento)
    lento.set(1.0)
    for i in range(1, 5):                               # el mismo segundo a 4 Hz
        lento.step(t0 + i * 0.25)

    assert abs(rapido.value - lento.value) < 0.02, \
        f"el mismo segundo da {rapido.value:.4f} a 60 Hz y {lento.value:.4f} a 4 Hz"

    # y el muelle igual: mismo destino en el mismo tiempo, vaya en la compuerta
    # que vaya
    s60 = motion.Spring(0.0)
    s60.set(1.0)
    for _ in range(60):
        s60.step(1.0 / 60.0)
    s4 = motion.Spring(0.0)
    s4.set(1.0)
    for _ in range(4):
        s4.step(0.25)
    assert abs(s60.value - s4.value) < 0.02, \
        f"Spring llega a {s60.value:.4f} a 60 Hz y a {s4.value:.4f} a 4 Hz"

    # un tiron de verdad (ventana arrastrada, depurador) si se recorta: mas vale
    # comerse el salto que dar un brinco en pantalla
    tiron = motion.Smooth(0.0, tau=0.05)
    t0 = sincronizar(tiron)
    tiron.set(1.0)
    tiron.step(t0 + 5.0)
    assert tiron.value < 1.0, "un salto de 5 s no puede integrarse entero"
    print("  OK  los integradores aguantan el paso de 250 ms de la compuerta de 4 Hz")


def test_smooth_reduce_motion() -> None:
    def recorrido(reducido: bool) -> float:
        motion.set_reduce_motion(reducido)
        s = motion.Smooth(0.0, tau=0.14)
        t0 = sincronizar(s)
        s.set(1.0)
        for i in range(1, 26):                          # 0.4 s
            s.step(t0 + i * MARCO)
        return s.value

    try:
        normal = recorrido(False)
        reducido = recorrido(True)
    finally:
        motion.set_reduce_motion(False)

    assert reducido > normal, \
        f"con reduce_motion Smooth tiene que llegar antes ({reducido:.4f} contra {normal:.4f})"
    assert reducido > 0.99, f"a los 400 ms deberia estar ya puesto, va por {reducido:.4f}"
    assert normal < 0.96, "sin reduce_motion no puede llegar tan rapido"
    print("  OK  Smooth respeta reduce_motion")


def test_duraciones_y_curvas() -> None:
    assert motion.dur(200) == 200
    assert motion.exit_of(200) == 120, "salida = 0.6 x entrada"
    motion.set_reduce_motion(True)
    try:
        assert motion.dur(200) == 70, "con reduce_motion todo se encoge al 35 %"
        assert motion.dur(1) >= 1, "ninguna duracion puede quedarse en cero"
    finally:
        motion.set_reduce_motion(False)

    # el sobrepaso de Qt por defecto (1.70) es de dibujos animados
    assert abs(motion.EASE_LIFT.overshoot() - 1.12) < 1e-6
    assert motion.ease(0.0) == 0.0 and abs(motion.ease(1.0) - 1.0) < 1e-9
    assert motion.ease(-5.0) == 0.0 and abs(motion.ease(9.0) - 1.0) < 1e-9, \
        "ease tiene que recortar fuera de 0..1"
    # EASE_GLASS arranca muy rapido: a mitad de camino ya ha hecho la mayor parte
    assert motion.ease(0.5, motion.EASE_GLASS) > 0.9
    print("  OK  duraciones, salidas y curvas siguen la spec")


def test_stagger() -> None:
    marcos: list[int] = []
    s = motion.Stagger(9, lambda: marcos.append(1))
    assert s.delay(0) == 0
    assert s.delay(5) == 5 * motion.STAGGER_STEP
    assert s.delay(8) == s.delay(5), "del septimo en adelante entran con el sexto"
    assert s.total == 5 * motion.STAGGER_STEP + motion.STAGGER_DUR

    s.start()
    assert not s.done
    for _ in range(200):
        if not s.tick(MARCO):
            break
    assert s.done, "el escalonado no termina"
    op, dy = s.state(8)
    assert abs(op - 1.0) < 1e-9 and abs(dy) < 1e-9, "el ultimo hijo no acaba puesto"
    assert marcos, "no ha pedido ni un repintado"

    # con reduce_motion no hay escalonado: entra todo ya puesto y de una vez
    motion.set_reduce_motion(True)
    try:
        r = motion.Stagger(6, lambda: None)
        r.start()
        assert r.done, "con reduce_motion el escalonado no puede llegar a correr"
        assert r.state(5)[0] == 1.0
    finally:
        motion.set_reduce_motion(False)
    print("  OK  Stagger escalona 6 hijos y se apaga con reduce_motion")


# --------------------------------------------------------------------------- #
# la interfaz vieja sigue viva mientras dure la transicion
# --------------------------------------------------------------------------- #

def test_anim_reexporta_sin_duplicar() -> None:
    from airtouch.ui import anim

    # lo que importan hoy dashboard.py, widgets.py y wizard/wizard.py
    for nombre in ("AnimatedStack", "fade", "tween", "Smooth", "shake",
                   "EASE_OUT", "EASE_IN_OUT", "EASE_SPRING", "FAST", "NORMAL",
                   "SLOW", "ease", "Qt"):
        assert hasattr(anim, nombre), f"anim.{nombre} ha desaparecido"

    for nombre in ("Smooth", "fade", "tween", "ease"):
        assert getattr(anim, nombre) is getattr(motion, nombre), \
            f"anim.{nombre} es una copia y no lo de motion.py"
    print("  OK  anim.py reexporta motion.py sin duplicar codigo")


def main() -> int:
    tests = [
        test_beat_un_solo_temporizador,
        test_beat_patrones_sin_temporizador_propio,
        test_beat_join_y_leave,
        test_beat_compuertas_de_frecuencia,
        test_beat_afloja_y_se_para,
        test_beat_baja_desde_dentro_del_tick,
        test_ahorro_entra_a_los_3s,
        test_ahorro_sale_a_los_5s,
        test_ahorro_afloja_el_latido,
        test_spring_converge_sin_oscilar,
        test_spring_conserva_velocidad,
        test_spring_reduce_motion,
        test_smooth_converge,
        test_integradores_aguantan_el_paso_de_la_compuerta_lenta,
        test_smooth_reduce_motion,
        test_duraciones_y_curvas,
        test_stagger,
        test_anim_reexporta_sin_duplicar,
    ]
    print("Pruebas del movimiento (sin ventana)\n")
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
