"""Pruebas del motor de gestos con manos sinteticas.

Permite validar toda la maquina de estados sin camara y sin tocar el sistema:
se fabrican FrameState a mano y se comprueba que salen los eventos correctos.

    python tests\\test_engine.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from airtouch.config import Config                       # noqa: E402
from airtouch.core.frame_state import FaceState, FrameState, HandState  # noqa: E402
from airtouch.core.mapping import PointerMapper          # noqa: E402
from airtouch.gestures.engine import GestureEngine       # noqa: E402
from airtouch.gestures.events import EventType, Mode     # noqa: E402

EXT_REF = 1.72


def make_hand(x: float, y: float, pinch: float, extension: float = 1.0,
              label: str = "Right", tip_drift: float = 0.0) -> HandState:
    """Mano sintetica con pinch y extension del indice controlados.

    ``tip_drift`` desplaza SOLO la yema del indice dejando la palma quieta: es
    lo que pasa de verdad al cerrar el pinch, y lo que provocaba scroll falso.
    """
    world = np.zeros((21, 3), dtype=np.float64)
    world[0] = (0.0, 1.0, 0.0)          # muneca
    world[9] = (0.0, 0.0, 0.0)          # nudillo del corazon  -> escala = 1
    world[5] = (0.0, 0.0, 0.0)          # nudillo del indice
    tip = extension * EXT_REF
    world[8] = (tip, 0.0, 0.0)          # yema del indice
    world[4] = (tip - pinch, 0.0, 0.0)  # yema del pulgar

    lm = np.zeros((21, 3), dtype=np.float64)
    lm[:, 0] = x
    lm[:, 1] = y
    lm[8] = (x, y + tip_drift, 0.0)      # yema del indice
    lm[7] = (x, y + tip_drift, 0.0)      # falange previa (entra en el puntero)
    lm[4] = (x, y + tip_drift, 0.0)      # yema del pulgar
    return HandState.build(label, 0.95, lm, world)


def frame(t: float, *hands: HandState) -> FrameState:
    fs = FrameState(t=t, frame_id=int(t * 60), width=1280, height=720)
    fs.hands = list(hands)
    fs.face = FaceState(present=True)
    return fs


def new_engine() -> tuple[GestureEngine, Config]:
    cfg = Config()
    cfg.mapping.homography = None
    cfg.mapping.mode = "absolute"
    cfg.mapping.region_x0 = cfg.mapping.region_y0 = 0.0
    cfg.mapping.region_x1 = cfg.mapping.region_y1 = 1.0
    cfg.mapping.dead_zone_px = 0.0
    cfg.filter.min_cutoff = 40.0        # sin suavizado: tests deterministas
    cfg.filter.beta = 0.0
    cfg.gestures.window_chrome_enabled = False   # no consultar ventanas reales
    eng = GestureEngine(cfg, PointerMapper(cfg.mapping, cfg.filter))
    return eng, cfg


def types(outs) -> list[EventType]:
    return [e.type for out in outs for e in out.events]


# ---------------------------------------------------------------- casos
def test_click() -> None:
    eng, _ = new_engine()
    outs = []
    t = 0.0
    for _ in range(5):                       # mano abierta
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.9))))
        t += 1 / 60
    for _ in range(6):                       # pinch cerrado, quieto
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.10))))
        t += 1 / 60
    for _ in range(16):                      # suelta (el clic se retiene 130 ms
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.9))))   # por si
        t += 1 / 60                                                   # es catapulta

    assert EventType.CLICK in types(outs), "no se ha generado el clic"
    print("  OK  clic")


def test_no_click_when_held() -> None:
    eng, cfg = new_engine()
    outs = []
    t = 0.0
    for _ in range(3):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.9))))
        t += 1 / 60
    # pinch mantenido mas alla de click_max_ms, sin moverse
    steps = int((cfg.gestures.click_max_ms / 1000.0) * 60) + 8
    for _ in range(steps):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.10))))
        t += 1 / 60
    for _ in range(3):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.9))))
        t += 1 / 60

    assert EventType.CLICK not in types(outs), "un pinch largo no debe ser clic"
    print("  OK  pinch largo no genera clic")


def test_click_does_not_scroll() -> None:
    """Regresion: al cerrar el pinch la yema se desplaza sola. Si el recorrido
    se midiera con la yema (y no con la palma) cada clic saldria como scroll."""
    eng, _ = new_engine()
    outs = []
    t = 0.0
    for _ in range(4):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.9))))
        t += 1 / 60
    # el pinch se cierra y la yema baja 0.05 (unos 100 px) en 5 frames
    for i in range(5):
        drift = 0.01 * (i + 1)
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.10, tip_drift=drift))))
        t += 1 / 60
    for _ in range(16):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.9))))
        t += 1 / 60

    kinds = types(outs)
    assert EventType.SCROLL not in kinds, "un clic no puede generar scroll"
    assert EventType.CLICK in kinds, "y debe seguir generando el clic"
    print("  OK  un clic no se convierte en scroll")


def test_pointer_frozen_while_clicking() -> None:
    """El puntero dibujado no debe irse mientras mantienes el pinch."""
    eng, _ = new_engine()
    t = 0.0
    for _ in range(4):
        eng.update(frame(t, make_hand(0.5, 0.5, 0.9)))
        t += 1 / 60

    # la yema se va desplazando mientras el pinch esta cerrado
    pinched = []
    for i in range(10):
        out = eng.update(frame(t, make_hand(0.5, 0.5, 0.10, tip_drift=0.006 * i)))
        t += 1 / 60
        if out.pinching and out.pointer is not None:
            pinched.append(out.pointer)

    assert len(pinched) >= 3, "el pinch no llego a cerrarse"
    unique = set(pinched)
    assert len(unique) == 1, \
        f"el puntero se ha movido durante el pinch: {sorted(unique)}"
    print(f"  OK  el puntero se ancla mientras clicas ({len(pinched)} frames)")


def test_scroll_direction() -> None:
    eng, _ = new_engine()
    outs = []
    t = 0.0
    for _ in range(3):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.6, 0.9))))
        t += 1 / 60
    # pinch mantenido (el scroll no se arma hasta pasados scroll_arm_ms) y
    # despues subir la mano -> scroll hacia abajo (notches negativos)
    for _ in range(26):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.6, 0.10))))
        t += 1 / 60
    y = 0.6
    for _ in range(30):
        y -= 0.012
        outs.append(eng.update(frame(t, make_hand(0.5, y, 0.10))))
        t += 1 / 60

    scrolls = [e for out in outs for e in out.events if e.type is EventType.SCROLL]
    assert scrolls, "no se ha generado scroll"
    total = sum(e.data["notches"] for e in scrolls)
    assert total < 0, f"subir la mano debe hacer scroll hacia abajo, salio {total}"
    assert any(o.mode is Mode.SCROLLING for o in outs)
    print(f"  OK  scroll ({len(scrolls)} eventos, total {total})")


def test_flick_right_click() -> None:
    eng, _ = new_engine()
    outs = []
    t = 0.0
    for _ in range(3):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.9))))
        t += 1 / 60
    # cargar: indice curvado y en contacto con el pulgar
    for _ in range(12):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.30, extension=0.45))))
        t += 1 / 60
    # soltar de golpe: extension alta en un solo frame
    outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.85, extension=1.05))))

    assert EventType.RIGHT_CLICK in types(outs), "la catapulta no ha disparado"
    print("  OK  catapulta -> clic derecho")


def test_flick_does_not_also_left_click() -> None:
    """Al separar los dedos tras la catapulta el pinch tambien se abre. Si el
    clic no se retuviera, cada clic derecho vendria con uno izquierdo detras."""
    eng, _ = new_engine()
    outs = []
    t = 0.0
    for _ in range(3):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.9))))
        t += 1 / 60
    for _ in range(8):                       # cargado: curvado y cerca
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.25, extension=0.45))))
        t += 1 / 60
    outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.85, extension=1.05))))
    t += 1 / 60
    for _ in range(20):                      # mas alla de la ventana de guarda
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.9))))
        t += 1 / 60

    kinds = types(outs)
    assert EventType.RIGHT_CLICK in kinds, "la catapulta no disparo"
    assert EventType.CLICK not in kinds, "no debe salir tambien un clic izquierdo"
    print("  OK  la catapulta no genera ademas un clic izquierdo")


def test_flick_not_triggered_by_normal_pinch() -> None:
    eng, _ = new_engine()
    outs = []
    t = 0.0
    # pinch normal: el indice esta ESTIRADO todo el rato
    for _ in range(3):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.9, extension=1.0))))
        t += 1 / 60
    for _ in range(8):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.10, extension=1.0))))
        t += 1 / 60
    for _ in range(4):
        outs.append(eng.update(frame(t, make_hand(0.5, 0.5, 0.9, extension=1.0))))
        t += 1 / 60

    assert EventType.RIGHT_CLICK not in types(outs), \
        "un pinch normal no puede generar clic derecho"
    print("  OK  el pinch normal no dispara la catapulta")


def test_zoom() -> None:
    eng, _ = new_engine()
    outs = []
    t = 0.0
    for _ in range(3):
        outs.append(eng.update(frame(
            t, make_hand(0.40, 0.5, 0.9, label="Right"),
            make_hand(0.60, 0.5, 0.9, label="Left"))))
        t += 1 / 60
    # las dos manos pinchan y se separan
    dx = 0.0
    for _ in range(30):
        dx += 0.008
        outs.append(eng.update(frame(
            t, make_hand(0.40 - dx, 0.5, 0.10, label="Right"),
            make_hand(0.60 + dx, 0.5, 0.10, label="Left"))))
        t += 1 / 60

    zooms = [e for out in outs for e in out.events if e.type is EventType.ZOOM]
    assert zooms, "no se ha generado zoom"
    total = sum(e.data["notches"] for e in zooms)
    assert total > 0, f"separar las manos debe ampliar, salio {total}"
    assert any(o.mode is Mode.ZOOMING for o in outs)
    print(f"  OK  zoom ({len(zooms)} eventos, total {total})")


def test_pointer_follows_hand() -> None:
    eng, _ = new_engine()
    from airtouch.core.screen import primary_screen

    s = primary_screen()
    last = None
    t = 0.0
    for i in range(40):
        x = 0.2 + i * 0.015
        out = eng.update(frame(t, make_hand(x, 0.5, 0.9)))
        t += 1 / 60
        last = out.pointer
    assert last is not None
    assert last[0] > s.w * 0.5, f"el puntero deberia haberse ido a la derecha: {last}"
    print(f"  OK  el puntero sigue la mano (x final {last[0]:.0f} de {s.w})")


def test_keyboard_typing() -> None:
    eng, _ = new_engine()
    eng.show_keyboard(True)
    key = next(k for k in eng.keyboard.keys if k.ident == "a")

    from airtouch.core.screen import primary_screen
    s = primary_screen()
    nx = key.cx / s.w
    ny = key.cy / s.h

    outs = []
    t = 0.0
    for _ in range(4):
        outs.append(eng.update(frame(t, make_hand(nx, ny, 0.9))))
        t += 1 / 60
    for _ in range(4):
        outs.append(eng.update(frame(t, make_hand(nx, ny, 0.10))))
        t += 1 / 60

    texts = [e.data["text"] for out in outs for e in out.events
             if e.type is EventType.KEY_TEXT]
    assert "a" in texts, f"no se ha escrito la tecla, salio {texts}"
    print("  OK  teclado virtual escribe")


def test_pause_releases_drag() -> None:
    eng, cfg = new_engine()
    cfg.gestures.pinch_drag_mode = "drag"
    t = 0.0
    eng.update(frame(t, make_hand(0.5, 0.5, 0.9)))
    t += 1 / 60
    # mantener el pinch lo suficiente para armar, y luego arrastrar
    for _ in range(26):
        eng.update(frame(t, make_hand(0.5, 0.5, 0.10)))
        t += 1 / 60
    x = 0.5
    for _ in range(16):
        x += 0.01
        eng.update(frame(t, make_hand(x, 0.5, 0.10)))
        t += 1 / 60
    assert eng._drag_down, "deberia estar arrastrando"

    eng.paused = True
    out = eng.update(frame(t))
    assert EventType.LEFT_UP in [e.type for e in out.events], \
        "al pausar hay que soltar el boton"
    print("  OK  al pausar se suelta el boton del raton")


def main() -> int:
    tests = [
        test_click,
        test_no_click_when_held,
        test_click_does_not_scroll,
        test_pointer_frozen_while_clicking,
        test_scroll_direction,
        test_flick_right_click,
        test_flick_does_not_also_left_click,
        test_flick_not_triggered_by_normal_pinch,
        test_zoom,
        test_pointer_follows_hand,
        test_keyboard_typing,
        test_pause_releases_drag,
    ]
    print("Pruebas del motor de gestos (sin camara)\n")
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
