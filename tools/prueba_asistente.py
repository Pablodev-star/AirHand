"""Ensaya el asistente entero con datos sintéticos y lo saca a imágenes.

    .venv\\Scripts\\python.exe tools\\prueba_asistente.py <carpeta> [--tema dark|light|ambos]

`render_ui.py` saca cada página tal y como se ve **sin cámara**, que es la mitad
de la historia: en esa mitad ninguna página está satisfecha, así que el botón
primario no existe nunca, el histograma está vacío y el recibo sale a ceros.
Justo los estados que hay que mirar son los otros.

Aquí el asistente recibe fotogramas y salidas del motor falsos —una mano que se
abre y se cierra delante de una cámara que no existe— para poder ver lo que un
usuario ve de verdad: los cuatro medidores en verde, las tres fichas llenas, el
umbral deslizándose a su sitio, el botón materializándose y el recibo con sus
números.

Nada de esto entra en el programa: es una herramienta de mirar.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Pantalla fija, como en render_ui: si no, cada equipo saca capturas distintas.
from airtouch.core import screen as _screen                      # noqa: E402

_PANTALLA = _screen.Rect(0, 0, 2560, 1440)
_screen.primary_screen = lambda: _PANTALLA
_screen.virtual_screen = lambda: _PANTALLA

from PySide6.QtWidgets import QApplication                       # noqa: E402

from airtouch.config import Config                               # noqa: E402
from airtouch.core.controller import Controller                  # noqa: E402
from airtouch.core.frame_state import FrameState, HandState      # noqa: E402
from airtouch.gestures.engine import EngineOutput                # noqa: E402
from airtouch.gestures.events import Mode                        # noqa: E402
from airtouch.ui import theme                                    # noqa: E402
from airtouch.ui.wizard import pages as P                        # noqa: E402
from airtouch.ui.wizard.wizard import SetupWizard                # noqa: E402

ANCHO, ALTO = 1180, 880


# --------------------------------------------------------------------------- #
# la mano de mentira
# --------------------------------------------------------------------------- #

def mano(cierre: float, centro=(0.5, 0.5), escala: float = 0.50) -> HandState:
    """Una mano en la pose que haga falta. ``cierre`` va de 0 (abierta) a 1.

    Los 21 puntos no pretenden ser anatómicos: solo tienen que caer donde las
    páginas los miden — la palma para el centrado, los cinco puntos de la base
    para la distancia y el pulgar contra el índice para el pinch.
    """
    lm = np.zeros((21, 3), dtype=np.float32)
    cx, cy = centro
    # muñeca y base de los dedos: es lo que la página del encuadre mide
    base = [(0.0, 0.5), (-0.22, 0.12), (-0.06, 0.05), (0.10, 0.07), (0.24, 0.16)]
    for i, (dx, dy) in zip((0, 5, 9, 13, 17), base):
        lm[i] = (cx + dx * escala, cy + dy * escala, 0.0)
    # pulgar e índice: la distancia entre las puntas es el pinch
    abierto, cerrado = 0.30, 0.02
    d = abierto + (cerrado - abierto) * cierre
    lm[4] = (cx - d * escala * 0.5, cy - 0.30 * escala, 0.0)
    lm[8] = (cx + d * escala * 0.5, cy - 0.34 * escala, 0.0)
    for i in (1, 2, 3, 6, 7, 10, 11, 12, 14, 15, 16, 18, 19, 20):
        lm[i] = (cx, cy, 0.0)
    h = HandState(label="Right", score=0.94, lm=lm, world=lm.copy())
    h.pinch_ratio = 0.88 + (0.24 - 0.88) * cierre
    h.pointer = np.array([cx, cy - 0.34 * escala])
    h.palm = np.array([cx, cy])
    h.pinch_point = h.pointer.copy()
    h.extended = (True, True, True, True, True)
    return h


def fotograma(brillo: int = 120) -> np.ndarray:
    """Un fotograma BGR con una silueta, para que la vista no salga plana."""
    alto, ancho = 540, 960
    img = np.full((alto, ancho, 3), brillo // 3, dtype=np.uint8)
    yy, xx = np.mgrid[0:alto, 0:ancho]
    r = np.hypot((xx - ancho * 0.5) / (ancho * 0.30),
                 (yy - alto * 0.62) / (alto * 0.52))
    silueta = np.clip(1.4 - r, 0.0, 1.0)
    for c, k in enumerate((1.02, 0.96, 0.90)):
        img[:, :, c] = np.clip(brillo // 3 + silueta * brillo * k, 0, 255)
    return img


def estado(cierre: float, centro=(0.5, 0.5)) -> FrameState:
    fs = FrameState(width=960, height=540)
    fs.hands = [mano(cierre, centro)]
    return fs


def salida(cierre: float, modo: Mode = Mode.POINTING) -> EngineOutput:
    h = mano(cierre)
    return EngineOutput(mode=modo, hands=1, pinch_ratio=float(h.pinch_ratio),
                        pinching=cierre > 0.6,
                        pointer=(1280.0, 720.0), raw_pointer=(0.5, 0.44))


# --------------------------------------------------------------------------- #
# el guion
# --------------------------------------------------------------------------- #

def reposar(app: QApplication, segundos: float) -> None:
    fin = time.time() + segundos
    while time.time() < fin:
        app.processEvents()
        time.sleep(0.008)


def bombear(app: QApplication, pagina, segundos: float, hz: float = 30.0,
            ciclo: float = 1.1, frames: bool = False) -> None:
    """Le da de comer a la página una mano que se abre y se cierra."""
    fin = time.time() + segundos
    t0 = time.time()
    while time.time() < fin:
        fase = ((time.time() - t0) / ciclo) % 1.0
        cierre = 0.5 - 0.5 * math.cos(fase * 2.0 * math.pi)
        if frames:
            pagina.on_frame((fotograma(), estado(cierre)))
        pagina.on_output(salida(cierre))
        app.processEvents()
        time.sleep(1.0 / hz)


def capturar(app: QApplication, wiz: SetupWizard, destino: Path,
             nombre: str, espera: float = 1.0) -> None:
    reposar(app, espera)
    pm = wiz.grab()
    destino.mkdir(parents=True, exist_ok=True)
    pm.save(str(destino / f"{nombre}.png"))
    marca = "botón" if (wiz.boton is not None and wiz.boton.born) else "sin botón"
    print(f"  {nombre:34} {pm.width()}x{pm.height()}  hilo "
          f"{wiz._hilo.target * 100:5.1f} %  {marca}")


def ensayar(app: QApplication, cfg: Config, ctl: Controller, destino: Path,
            tema: str) -> None:
    print(f"\n=== tema {tema} ===")
    theme.apply(tema)
    app.setStyleSheet(theme.qss())
    fuera = destino / tema

    wiz = SetupWizard(cfg, ctl)
    wiz.resize(ANCHO, ALTO)
    wiz.show()

    # P0 — la portada, con la lente ya asentada y el ratón dentro
    wiz._goto(0)
    wiz.pages[0].lente.apuntar(wiz.pages[0].lente.rect().center())
    capturar(app, wiz, fuera, "00-bienvenida", 1.6)

    # P1 — el móvil emitiendo: silueta rellena, marca dibujada y confeti
    wiz._goto(1)
    pagina = wiz.pages[1]
    pagina._elegir("airlink")
    reposar(app, 0.5)
    capturar(app, wiz, fuera, "01-camara-eligiendo", 0.6)
    ctl.airlink.phone_connected = True
    ctl.airlink.frames_received = 400
    pagina.on_frame((fotograma(150), estado(0.0)))
    reposar(app, 0.9)
    capturar(app, wiz, fuera, "02-camara-conectada", 0.5)

    # P2 — los cuatro medidores en verde y el anillo cerrándose sobre el botón
    wiz._goto(2)
    pagina = wiz.pages[2]
    wiz._quitar_espera()
    t0 = time.time()
    while time.time() - t0 < 8.0 and not pagina._satisfecha:
        pagina.on_frame((fotograma(120), estado(0.2, (0.5, 0.5))))
        app.processEvents()
        time.sleep(0.03)
    # a media espera del compas: es cuando el anillo se esta cerrando sobre el
    # boton, y ese es justo el fotograma que hay que mirar
    capturar(app, wiz, fuera, "03-encuadre-verde", 0.45)

    # P3 — tres cierres contados (P2 avanza sola, asi que ya podemos estar aqui)
    wiz._goto(3)
    pagina = wiz.pages[3]
    wiz._quitar_espera()
    bombear(app, pagina, 5.0, ciclo=1.0)
    capturar(app, wiz, fuera, "04-gesto-tres", 0.6)

    # P4 — el umbral deslizándose y el histograma construyéndose
    wiz._goto(4)
    pagina = wiz.pages[4]
    wiz._quitar_espera()
    bombear(app, pagina, 6.0, ciclo=0.9)
    capturar(app, wiz, fuera, "05-pinch-ajustado", 0.6)

    # P5 — la vista con la región mapeada, sin abrir la pantalla completa
    wiz._goto(5)
    pagina = wiz.pages[5]
    wiz._quitar_espera()
    pagina._lanzada = True                      # que no se apodere del monitor
    pagina.on_frame((fotograma(140), estado(0.0)))
    pagina.pasos.set_hecho(0, True)
    pagina.pasos.set_hecho(1, True)
    pagina.calibrada = True
    pagina.dianas = 3
    pagina.vista.quad = [(0.08, 0.10), (0.92, 0.12), (0.90, 0.88), (0.10, 0.86)]
    pagina.progreso.emit(1.0)
    pagina.estado_cambiado.emit()
    capturar(app, wiz, fuera, "06-punteria", 0.8)

    # P6 — el recibo con números de verdad
    wiz._retardo = 74.0
    wiz._goto(6)
    capturar(app, wiz, fuera, "07-recibo", 1.4)

    # la expansión: la lámina viajando hacia el área del mosaico
    wiz._terminar()
    reposar(app, 0.30)
    pm = wiz.grab()
    pm.save(str(fuera / "08-expansion.png"))
    print(f"  {'08-expansion':34} {pm.width()}x{pm.height()}  a mitad de viaje")
    reposar(app, 0.6)
    wiz.hide()
    wiz.deleteLater()
    reposar(app, 0.2)


def main(argv: list[str]) -> int:
    destino = Path(argv[1]) if len(argv) > 1 else None
    if destino is None:
        print(__doc__)
        return 2
    tema_arg = argv[argv.index("--tema") + 1] if "--tema" in argv else "ambos"
    temas = ["dark", "light"] if tema_arg == "ambos" else [tema_arg]

    app = QApplication(sys.argv[:1])
    cfg = Config()
    cfg.airlink.port = 8553
    cfg.airlink.auto_start = False
    ctl = Controller(cfg)
    for tema in temas:
        ensayar(app, cfg, ctl, destino, tema)
    print(f"\nImágenes en {destino}")
    import os

    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
