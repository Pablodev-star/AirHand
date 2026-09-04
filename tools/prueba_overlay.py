"""Mira y **mide** el overlay: sus estados en los dos temas y su coste real.

    .venv\\Scripts\\python.exe tools\\prueba_overlay.py <carpeta> [--tema dark|light|ambos]

Dos trabajos, y el segundo es el que no se puede saltar. El apartado 10.7 fija
un presupuesto de píxeles repintados por fotograma y el 10.1.7 dice que hay que
verificarlo con el contador, no suponerlo. `OverlayCanvas.damage_report()` ya
lleva ese contador siempre encendido; aquí se le pone delante cada situación de
la tabla durante unos segundos y se imprime lo que sale, con su veredicto.

Cómo funciona sin apoderarse de la pantalla: el overlay **no se muestra**. Se le
llama a `tick()` con tiempo real —las animaciones son exponenciales y de
duración fija, así que necesitan segundos de verdad— y se le pide `grab()` para
las imágenes. El contador de daño se alimenta en `tick()`, o sea que mide lo
mismo que mediría con la ventana encima del escritorio.

Las imágenes van compuestas sobre un escritorio de mentira, porque el vidrio del
overlay es autoiluminado y sobre transparencia no se puede juzgar (apartado 10).
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Pantalla fija: el presupuesto del apartado 10.7 esta escrito para 2560x1440 y
# el anillo de pausa es el unico elemento cuyo coste depende del tamano de la
# pantalla. Medir en otra y comparar con esa tabla no diria nada.
from airtouch.core import screen as _screen                      # noqa: E402

ANCHO, ALTO = 2560, 1440
_PANTALLA = _screen.Rect(0, 0, ANCHO, ALTO)
_screen.primary_screen = lambda: _PANTALLA
_screen.virtual_screen = lambda: _PANTALLA

from PySide6.QtCore import QPointF, QRect, QRectF, Qt            # noqa: E402
from PySide6.QtGui import (QColor, QLinearGradient, QPainter,    # noqa: E402
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import QApplication                       # noqa: E402

from airtouch.config import Config                               # noqa: E402
from airtouch.core.keyboard_layout import KeyboardLayout         # noqa: E402
from airtouch.gestures.engine import ChromeTarget, EngineOutput  # noqa: E402
from airtouch.gestures.events import Mode                        # noqa: E402
from airtouch.overlay import style as S                          # noqa: E402
from airtouch.overlay.canvas import OverlayCanvas                # noqa: E402
from airtouch.ui import theme                                    # noqa: E402

#: Presupuesto del apartado 10.7, en megapixeles por fotograma.
PRESUPUESTO = {
    "reposo apuntando": 0.010,
    "pausa": 0.026,
    "arrastrando ventana": 0.022,
    "teclado abierto": 0.300,
}


# --------------------------------------------------------------------------- #
# el escritorio de mentira
# --------------------------------------------------------------------------- #

def escritorio(w: int, h: int, claro: bool) -> QPixmap:
    """Un fondo cualquiera. El overlay flota sobre contenido que no controla, y
    sobre un liso plano el vidrio autoiluminado no se puede juzgar."""
    pm = QPixmap(w, h)
    p = QPainter(pm)
    grad = QLinearGradient(0, 0, w, h)
    if claro:
        grad.setColorAt(0.0, QColor("#EDEFF4"))
        grad.setColorAt(0.5, QColor("#D6DCE8"))
        grad.setColorAt(1.0, QColor("#F6F7FA"))
    else:
        grad.setColorAt(0.0, QColor("#1B2030"))
        grad.setColorAt(0.5, QColor("#0E1420"))
        grad.setColorAt(1.0, QColor("#242C3E"))
    p.fillRect(0, 0, w, h, grad)
    # unas manchas: sirven para ver si el glow del overlay se lee sobre claro y
    # sobre oscuro dentro de la misma imagen
    for fx, fy, r, hexa in ((0.22, 0.30, 0.30, "#5B6BA8"),
                            (0.78, 0.68, 0.34, "#2E6A5E"),
                            (0.55, 0.12, 0.22, "#8A5B6B")):
        radial = QRadialGradient(QPointF(w * fx, h * fy), max(w, h) * r)
        c = QColor(hexa)
        c.setAlphaF(0.30 if not claro else 0.16)
        fin = QColor(c)
        fin.setAlpha(0)
        radial.setColorAt(0.0, c)
        radial.setColorAt(1.0, fin)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(radial)
        p.drawRect(0, 0, w, h)
    p.end()
    return pm


class Motor:
    """El minimo que el overlay consulta del motor.

    ``_Teclado`` no se fia de que ``out.keyboard`` traiga teclas: exige que el
    motor diga que el teclado esta abierto. Sin este objeto el panel no se pinta
    y la medida del teclado sale a cero, que fue lo que paso la primera vez.
    """

    keyboard_visible = False


class Guardia:
    """El minimo que ``safety_ref`` necesita: el motivo real de la pausa."""

    class _Estado:
        paused = False
        reason = ""

    def __init__(self) -> None:
        self.state = Guardia._Estado()


# --------------------------------------------------------------------------- #
# conducir el overlay
# --------------------------------------------------------------------------- #

def salida(mode: Mode = Mode.POINTING, *, x: float = 1180.0, y: float = 760.0,
           ratio: float = 0.90, pinching: bool = False,
           flick: float = 0.0, chrome: ChromeTarget | None = None,
           keyboard: KeyboardLayout | None = None,
           nota: str = "") -> EngineOutput:
    return EngineOutput(mode=mode, pointer=(x, y), raw_pointer=(0.5, 0.5),
                        pinch_ratio=ratio, pinching=pinching, hands=1,
                        flick_charge=flick, chrome=chrome, keyboard=keyboard,
                        note=nota)


def correr(ov: OverlayCanvas, segundos: float, *, hz: float = 60.0,
           guion=None) -> None:
    """Deja correr el overlay en tiempo real.

    El tiempo tiene que ser real: ``Smooth`` y ``_Tween`` leen el reloj, y el
    colapso de la capsula de modo seguro son 4 s de reloj de pared, no cuatro
    segundos de un contador de fotogramas.

    ``guion(t)`` devuelve la salida del motor en el segundo ``t``. Sin guion, el
    overlay se queda con la ultima salida que le dieron.
    """
    fin = time.time() + segundos
    t0 = time.time()
    ultimo = time.perf_counter()
    while time.time() < fin:
        if guion is not None:
            ov.set_output(guion(time.time() - t0))
        ahora = time.perf_counter()
        ov.tick(max(0.001, ahora - ultimo))
        ultimo = ahora
        QApplication.processEvents()
        time.sleep(1.0 / hz)


def medir(ov: OverlayCanvas, nombre: str, segundos: float = 3.0,
          guion=None, tope: float | None = None) -> dict:
    """Mide el dano por fotograma de una situacion y la compara con la tabla."""
    ov.reset_damage()
    correr(ov, segundos, guion=guion)
    r = ov.damage_report()
    media = r["media"] / 1e6
    pico = r["pico"] / 1e6
    tope = PRESUPUESTO.get(nombre) if tope is None else tope
    veredicto = ""
    if tope is not None:
        veredicto = "DENTRO" if media <= tope else "SE PASA"
        veredicto += f" (tope {tope:.3f})"
    fot = int(r["fotogramas"])
    print(f"  {nombre:26} media {media:7.4f} Mpx/f   pico {pico:7.4f} Mpx   "
          f"{fot:4d} f   {veredicto}")
    return {"nombre": nombre, "media": media, "pico": pico, "tope": tope}


# --------------------------------------------------------------------------- #
# guiones: lo que hace el usuario en cada situacion medida
# --------------------------------------------------------------------------- #

def paseo(modo: Mode, **kw):
    """El puntero paseando: es el reposo real, nadie tiene la mano clavada."""
    def guion(t: float) -> EngineOutput:
        return salida(modo, x=1180.0 + 130.0 * math.cos(t * 0.7),
                      y=760.0 + 80.0 * math.sin(t * 0.7), **kw)
    return guion


def arrastre(chrome: ChromeTarget):
    """Arrastrando una ventana: la ventana **se mueve**, que es el caso caro."""
    x0, y0, x1, y1 = chrome.rect
    def guion(t: float) -> EngineOutput:
        dx = int(120.0 * math.cos(t * 0.8))
        dy = int(60.0 * math.sin(t * 0.8))
        movida = ChromeTarget(chrome.hwnd,
                              (x0 + dx, y0 + dy, x1 + dx, y1 + dy),
                              chrome.zone, chrome.title)
        return salida(Mode.WINDOW_MOVE, x=(x0 + x1) / 2.0 + dx,
                      y=float(y1 + dy) + 30.0, ratio=0.24, pinching=True,
                      chrome=movida)
    return guion


def tecleo(teclado: KeyboardLayout):
    """Tecleando: el puntero recorre el teclado y va cambiando de tecla.

    Es la unica medida honesta del teclado, y tiene dos partes que no se pueden
    saltar. Una: mover el puntero, porque con la mano quieta no se repinta ni
    una tecla y saldria un cero que no significa nada. Y dos: **calcular la
    tecla bajo el puntero** y ponerla en ``key_hover``, que es lo que hace el
    motor de verdad; sin eso el overlay no tiene ninguna tecla que tocar y la
    medida vuelve a no significar nada.
    """
    x0, y0, w, h = teclado.rect

    def guion(t: float) -> EngineOutput:
        x = x0 + w * (0.5 + 0.42 * math.cos(t * 1.6))
        y = y0 + h * (0.5 + 0.30 * math.sin(t * 1.1))
        hover = ""
        for key in teclado.keys:
            if key.x <= x <= key.x + key.w and key.y <= y <= key.y + key.h:
                hover = key.ident
                break
        out = salida(Mode.KEYBOARD, x=x, y=y, keyboard=teclado)
        out.key_hover = hover
        # una pulsacion cada segundo: es lo que dispara el anillo de la tecla
        if hover and (t % 1.0) < 0.12:
            out.key_active = hover
        return out
    return guion


# --------------------------------------------------------------------------- #
# imagenes
# --------------------------------------------------------------------------- #

def capa_de(ov: OverlayCanvas) -> tuple[QPixmap, float]:
    """El overlay pintado, y el factor de pixeles fisicos por pixel logico.

    ``grab()`` devuelve el pixmap a la escala del monitor de quien ejecuta esto
    —en un portatil al 150 % son 3840x2160 para una ventana de 2560x1440— con
    su ``devicePixelRatio`` puesto. Si no se neutraliza, los recortes salen
    desplazados y con el trozo equivocado: fue exactamente el primer fallo de
    esta herramienta, y no daba ningun error, solo imagenes vacias.
    """
    capa = ov.grab()
    factor = capa.width() / float(max(1, ov.width()))
    capa.setDevicePixelRatio(1.0)
    return capa, factor


def _escalar(caja: QRect, k: float) -> QRect:
    return QRect(int(caja.x() * k), int(caja.y() * k),
                 int(caja.width() * k), int(caja.height() * k))


def recorte(ov: OverlayCanvas, fondos: dict, caja: QRect, destino: Path,
            nombre: str, zoom: float = 1.0) -> None:
    """El overlay compuesto sobre el escritorio, recortado a lo interesante.

    ``zoom`` amplia el resultado. El cursor mide 60 px de anillo: a tamano real
    no se distingue si el arco del medidor de pinch esta o no esta, que es
    justamente lo que hay que mirar.
    """
    capa, k = capa_de(ov)
    fondo = fondos[round(k, 3)]
    r = _escalar(caja, k)
    pm = QPixmap(int(r.width() * zoom), int(r.height() * zoom))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.drawPixmap(QRectF(pm.rect()), fondo, QRectF(r))
    p.drawPixmap(QRectF(pm.rect()), capa, QRectF(r))
    p.end()
    destino.mkdir(parents=True, exist_ok=True)
    pm.save(str(destino / f"{nombre}.png"))
    print(f"  {nombre:34} {pm.width()}x{pm.height()}")


def completa(ov: OverlayCanvas, fondos: dict, destino: Path,
             nombre: str, escala: int = 3) -> None:
    """La pantalla entera reducida: la unica forma de ver el anillo de pausa."""
    capa, k = capa_de(ov)
    fondo = fondos[round(k, 3)]
    pm = QPixmap(fondo.size())
    p = QPainter(pm)
    p.drawPixmap(0, 0, fondo)
    p.drawPixmap(0, 0, capa)
    p.end()
    pm = pm.scaled(pm.width() // escala, pm.height() // escala,
                   Qt.AspectRatioMode.KeepAspectRatio,
                   Qt.TransformationMode.SmoothTransformation)
    destino.mkdir(parents=True, exist_ok=True)
    pm.save(str(destino / f"{nombre}.png"))
    print(f"  {nombre:34} {pm.width()}x{pm.height()}")


#: Los tres recortes de interes, en coordenadas de la pantalla de referencia.
CAJA_CAPSULA = QRect(ANCHO // 2 - 340, 0, 680, 190)
CAJA_CURSOR = QRect(1180 - 90, 760 - 90, 180, 180)
CAJA_PILDORA = QRect(ANCHO // 2 - 340, ALTO - 190, 680, 190)
CAJA_BARRA = QRect(700, 900, 900, 320)


# --------------------------------------------------------------------------- #
# el guion
# --------------------------------------------------------------------------- #

def ensayar(app: QApplication, destino: Path, tema: str) -> list[dict]:
    print(f"\n=== tema {tema} ===")
    theme.apply(tema)
    S.apply_theme(theme.C.dark)
    fuera = destino / tema

    cfg = Config()
    cfg.airlink.auto_start = False
    # umbrales redondos: asi el arco del medidor de pinch cae en 0, en la mitad
    # y en el tope, que es lo que hace falta ver
    cfg.gestures.pinch_on = 0.35
    cfg.gestures.pinch_off = 0.55
    ov = OverlayCanvas(cfg)
    # la ventana no se muestra, asi que hay que fijarle a mano la geometria de
    # referencia: refresh_geometry() se la habria pedido al monitor de verdad
    ov.setGeometry(0, 0, ANCHO, ALTO)
    ov._origin = (0, 0)
    ov._dpr = 1.0
    guardia = Guardia()
    ov.safety_ref = guardia
    motor = Motor()
    ov.engine_ref = motor
    # el escritorio de mentira, a la escala fisica que devuelva grab()
    _capa, factor = capa_de(ov)
    fondos = {round(factor, 3): escritorio(int(ANCHO * factor),
                                           int(ALTO * factor),
                                           not theme.C.dark)}

    # ---- 1. modo seguro, recien entrado: la capsula expandida con su rayado
    cfg.safety.control_enabled = False
    ov.set_output(salida(Mode.POINTING))
    correr(ov, 1.2)
    recorte(ov, fondos, CAJA_CAPSULA, fuera, "10-seguro-expandida")

    # ---- 2. modo seguro a los 4 s: colapsada a un circulo con solo el glifo
    correr(ov, 4.0)
    recorte(ov, fondos, CAJA_CAPSULA, fuera, "11-seguro-colapsada")
    medidas = [medir(ov, "reposo apuntando", 3.0, paseo(Mode.POINTING))]

    # ---- 3. en pausa: capsula que respira, motivo real y anillo de pantalla
    cfg.safety.control_enabled = True
    guardia.state.paused = True
    guardia.state.reason = "no se detecta al usuario"
    ov.set_output(salida(Mode.PAUSED))
    correr(ov, 1.6)
    recorte(ov, fondos, CAJA_CAPSULA, fuera, "12-pausa-capsula")
    completa(ov, fondos, fuera, "13-pausa-anillo-de-pantalla")
    # la pausa con temporizador es el caso caro: la hairline de cuenta atras
    # cambia cada fotograma, asi que la capsula entera sale sucia siempre
    medidas.append(medir(ov, "pausa", 3.0, paseo(Mode.PAUSED)))
    guardia.state.reason = "Esc"          # pausa manual: sin cuenta atras
    correr(ov, 0.4)
    medir(ov, "pausa manual (sin reloj)", 3.0, paseo(Mode.PAUSED),
          tope=PRESUPUESTO["pausa"])
    guardia.state.reason = "no se detecta al usuario"

    # ---- 4. control activo: sin capsula, solo la lampara
    guardia.state.paused = False
    ov.set_output(salida(Mode.POINTING))
    correr(ov, 1.4)
    recorte(ov, fondos, CAJA_CAPSULA, fuera, "14-control-activo-sin-capsula")

    # ---- 5. el cursor en sus modos
    for nombre, out in (
            ("20-cursor-apuntando", salida(Mode.POINTING, ratio=0.90)),
            ("21-cursor-pinch-a-medias",
             salida(Mode.PINCH_PENDING, ratio=0.45)),
            ("22-cursor-pinchado",
             salida(Mode.DRAGGING, ratio=0.24, pinching=True)),
            ("23-cursor-flick", salida(Mode.SCROLLING, ratio=0.70, flick=0.62)),
    ):
        ov.set_output(out)
        correr(ov, 0.9)
        recorte(ov, fondos, CAJA_CURSOR, fuera, nombre, zoom=2.0)

    # ---- 6. la pildora inferior de modo
    ov.set_output(salida(Mode.SCROLLING, ratio=0.70, nota="dos dedos"))
    correr(ov, 1.0)
    recorte(ov, fondos, CAJA_PILDORA, fuera, "30-pildora-inferior")

    # ---- 7. arrastrando una ventana
    chrome = ChromeTarget(hwnd=1, rect=(620, 320, 1940, 1010), zone="move",
                          title="Explorador")
    ov.set_output(salida(Mode.WINDOW_MOVE, x=1150.0, y=1020.0, ratio=0.24,
                         pinching=True, chrome=chrome))
    correr(ov, 1.2)
    recorte(ov, fondos, CAJA_BARRA, fuera, "31-barra-de-ventana")
    medidas.append(medir(ov, "arrastrando ventana", 3.0, arrastre(chrome)))

    # ---- 8. el teclado abierto
    teclado = KeyboardLayout()
    teclado.build(ANCHO * 0.18, ALTO * 0.58, ANCHO * 0.64, ALTO * 0.34)
    motor.keyboard_visible = True
    ov.set_output(salida(Mode.KEYBOARD, x=1280.0, y=1120.0, keyboard=teclado))
    # el panel entra con tau 0,38 s: hasta que la opacidad no se asienta, el
    # rectangulo del panel entero esta sucio cada fotograma. Medir antes seria
    # medir la apertura, no "el teclado abierto" de la tabla del 10.7
    correr(ov, 3.6, guion=tecleo(teclado))
    completa(ov, fondos, fuera, "40-teclado", escala=2)
    medidas.append(medir(ov, "teclado abierto", 3.0, tecleo(teclado)))

    ov.hide()
    ov.deleteLater()
    return medidas


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1].startswith("-"):
        print(__doc__)
        return 2
    destino = Path(argv[1])
    tema_arg = argv[argv.index("--tema") + 1] if "--tema" in argv else "ambos"
    temas = ["dark", "light"] if tema_arg == "ambos" else [tema_arg]

    app = QApplication(sys.argv[:1])
    todo: dict[str, list[dict]] = {}
    for tema in temas:
        todo[tema] = ensayar(app, destino, tema)

    print("\n=== presupuesto del apartado 10.7 ===")
    print(f"  {'situación':24} {'tope':>9} " + "".join(
        f"{t:>12}" for t in temas) + "   veredicto")
    peor = 0
    for i, nombre in enumerate(PRESUPUESTO):
        tope = PRESUPUESTO[nombre]
        valores = [todo[t][i]["media"] for t in temas]
        ok = all(v <= tope for v in valores)
        peor += 0 if ok else 1
        print(f"  {nombre:24} {tope:9.3f} "
              + "".join(f"{v:12.4f}" for v in valores)
              + ("   dentro" if ok else "   SE PASA"))
    print(f"\nImágenes en {destino}")
    if peor:
        print(f"{peor} situaciones se salen del presupuesto")
    else:
        print("Todas las situaciones caben en el presupuesto")

    import os

    os._exit(1 if peor else 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
