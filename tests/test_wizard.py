"""Pruebas del asistente inicial, sin camara y sin tocar el escritorio.

Existe por un fallo concreto que estuvo publicado: la pagina de camara del
asistente era la de iVCam, y al salir de ella dejaba
``camera.source_type = "index"``. Es decir, completar la configuracion inicial
apagaba AirLink y devolvia la aplicacion a la webcam del sistema, en silencio.
Quien instalase de cero terminaba el asistente y se quedaba sin camara.

Se comprueba lo que de verdad importa de esa pagina: que deja la camara en
AirLink, y que no deja seguir hasta que el movil manda imagen (las paginas
siguientes miden la mano; sin imagen no miden nada y el asistente parece
colgado).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Igual que en test_engine: una pantalla fija, para no depender del monitor de
# quien ejecute esto. Hay que hacerlo antes de importar lo que la consulta.
from airtouch.core import screen as _screen                # noqa: E402

_FAKE_SCREEN = _screen.Rect(0, 0, 2560, 1440)
_screen.primary_screen = lambda: _FAKE_SCREEN
_screen.virtual_screen = lambda: _FAKE_SCREEN

from PySide6.QtWidgets import QApplication                 # noqa: E402

from airtouch.config import Config                         # noqa: E402
from airtouch.core.controller import Controller            # noqa: E402
from airtouch.ui import theme                              # noqa: E402
from airtouch.ui.wizard.wizard import CameraPage, SetupWizard  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wizard() -> tuple[SetupWizard, Config, Controller]:
    cfg = Config()
    # puerto distinto del habitual: si hay un AirTouch de verdad abierto, no se
    # pelean por el 8443 y la prueba no depende de que la maquina este ociosa
    cfg.airlink.port = 8551
    ctl = Controller(cfg)
    return SetupWizard(cfg, ctl), cfg, ctl


def test_camera_page_deja_airlink() -> None:
    """El fallo original: salir de la pagina volvia a la camara del sistema."""
    _app()
    wiz, cfg, _ctl = _wizard()
    page = next(p for p in wiz.pages if isinstance(p, CameraPage))

    cfg.camera.source_type = "index"          # como si vinieras de una v1
    page.on_leave()

    assert cfg.camera.source_type == "airlink", \
        f"el asistente dejo la camara en {cfg.camera.source_type!r}"
    print("  OK  el asistente deja la camara en AirLink")


def test_camera_page_espera_al_movil() -> None:
    """No se puede continuar con el movil sin conectar."""
    _app()
    wiz, _cfg, ctl = _wizard()
    page = next(p for p in wiz.pages if isinstance(p, CameraPage))

    ctl.airlink.phone_connected = False
    ctl.airlink.frames_received = 0
    page._comprobar()
    assert not page.can_advance(), "deja seguir sin movil conectado"

    # conectado pero con dos fotogramas: aun no. La primera imagen llega antes
    # de que el movil estabilice la camara.
    ctl.airlink.phone_connected = True
    ctl.airlink.frames_received = 2
    page._comprobar()
    assert not page.can_advance(), "se fia del primer fotograma"

    ctl.airlink.frames_received = 120
    page._comprobar()
    assert page.can_advance(), "no deja seguir con el movil ya emitiendo"
    print("  OK  espera a que el movil emita de verdad")


def test_sin_rastro_de_ivcam() -> None:
    """Ningun texto visible puede seguir hablando de iVCam."""
    _app()
    wiz, _cfg, _ctl = _wizard()
    page = next(p for p in wiz.pages if isinstance(p, CameraPage))

    from PySide6.QtWidgets import QLabel

    textos = [w.text() for w in page.findChildren(QLabel)]
    malos = [t for t in textos if "ivcam" in t.lower()]
    assert not malos, f"quedan textos con iVCam: {malos}"
    print(f"  OK  ningun texto menciona iVCam ({len(textos)} etiquetas revisadas)")


def main() -> int:
    print("Pruebas del asistente inicial\n")
    pruebas = [
        test_camera_page_deja_airlink,
        test_camera_page_espera_al_movil,
        test_sin_rastro_de_ivcam,
    ]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
        except AssertionError as exc:
            fallos += 1
            print(f"  FALLO  {fn.__name__}: {exc}")
        except Exception as exc:
            fallos += 1
            print(f"  ERROR  {fn.__name__}: {type(exc).__name__}: {exc}")
    print()
    if fallos:
        print(f"{fallos} de {len(pruebas)} pruebas han fallado")
    else:
        print(f"Las {len(pruebas)} pruebas han pasado")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
