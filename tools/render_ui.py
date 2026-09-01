"""Renderiza la interfaz a imágenes para poder mirarla sin abrir el programa.

    .venv\\Scripts\\python.exe tools\\render_ui.py <carpeta-destino> [--tema dark|light|ambos]

Saca una imagen de cada pantalla: el panel, cada página del asistente y el
overlay con sus estados. Existe porque una interfaz no se verifica leyendo el
código: hay que verla. Y porque abrir el programa a mano para revisar catorce
pantallas en dos temas es media hora cada vez.

Detalle que cuesta descubrir: las páginas entran con una animación de opacidad,
así que hay que dejar correr el reloj de verdad antes de capturar. Con
processEvents() a secas salen en blanco.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Pantalla fija: si no, cada equipo produce capturas de distinto tamaño y no se
# pueden comparar entre sí. Hay que hacerlo antes de importar lo que la consulta.
from airtouch.core import screen as _screen                      # noqa: E402

_PANTALLA = _screen.Rect(0, 0, 2560, 1440)
_screen.primary_screen = lambda: _PANTALLA
_screen.virtual_screen = lambda: _PANTALLA

from PySide6.QtCore import QTimer                                # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget              # noqa: E402

from airtouch.config import Config                               # noqa: E402
from airtouch.core.controller import Controller                  # noqa: E402
from airtouch.ui import theme                                    # noqa: E402


def reposar(app: QApplication, segundos: float = 1.6) -> None:
    """Deja correr el reloj de verdad: las animaciones necesitan tiempo real."""
    fin = time.time() + segundos
    while time.time() < fin:
        app.processEvents()
        time.sleep(0.01)


def capturar(app: QApplication, w: QWidget, destino: Path, nombre: str,
             espera: float = 1.6) -> None:
    reposar(app, espera)
    pm = w.grab()
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / f"{nombre}.png"
    pm.save(str(ruta))
    print(f"  {nombre:38} {pm.width()}x{pm.height()}")


def render_tema(app: QApplication, cfg: Config, ctl: Controller,
                destino: Path, tema: str) -> None:
    print(f"\n=== tema {tema} ===")
    theme.apply(tema)
    app.setStyleSheet(theme.qss())
    fuera = destino / tema

    # ---- panel ----
    try:
        from airtouch.ui.dashboard import Dashboard

        dash = Dashboard(cfg, ctl)
        dash.resize(1180, 860)
        dash.show()
        capturar(app, dash, fuera, "00-panel")

        # con el motor "en marcha": es el estado en el que más se vive
        try:
            ctl.stats_ready.emit({
                "camera_fps": 59.4, "pipeline_fps": 58.1, "latency_ms": 42.0,
                "process_ms": 6.9, "hands": 1, "face": True,
                "resolution": "1920x1080", "low_res": False,
                "connected": True, "control": True, "paused": False,
            })
            capturar(app, dash, fuera, "01-panel-con-datos", espera=0.9)
        except Exception as exc:
            print(f"  (sin datos simulados: {exc})")

        dash.hide()
    except Exception as exc:
        print(f"  PANEL FALLA: {type(exc).__name__}: {exc}")

    # ---- asistente ----
    try:
        from airtouch.ui.wizard.wizard import SetupWizard

        wiz = SetupWizard(cfg, ctl)
        wiz.resize(980, 860)
        wiz.show()
        for i, page in enumerate(wiz.pages):
            wiz._goto(i)
            capturar(app, wiz, fuera, f"1{i}-asistente-{type(page).__name__}")
        wiz.hide()
    except Exception as exc:
        print(f"  ASISTENTE FALLA: {type(exc).__name__}: {exc}")

    # ---- overlay ----
    try:
        from airtouch.overlay import style as overlay_style
        from airtouch.overlay.canvas import OverlayCanvas

        overlay_style.apply_theme(theme.C.dark)
        ov = OverlayCanvas(cfg)
        ov.engine_ref = ctl.engine
        ov.show()
        capturar(app, ov, fuera, "20-overlay", espera=1.0)
        ov.hide()
    except Exception as exc:
        print(f"  OVERLAY FALLA: {type(exc).__name__}: {exc}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    destino = Path(argv[1])
    tema_arg = "ambos"
    if "--tema" in argv:
        tema_arg = argv[argv.index("--tema") + 1]
    temas = ["dark", "light"] if tema_arg == "ambos" else [tema_arg]

    app = QApplication(sys.argv[:1])
    cfg = Config()
    # puerto propio: así no se pelea con un AirTouch de verdad abierto
    cfg.airlink.port = 8552
    cfg.airlink.auto_start = False
    ctl = Controller(cfg)

    for tema in temas:
        render_tema(app, cfg, ctl, destino, tema)

    print(f"\nImágenes en {destino}")
    # os._exit: hay hilos de cámara y de red que no siempre se cierran solos, y
    # aquí no importa: es una herramienta de usar y tirar.
    QTimer.singleShot(0, lambda: None)
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
