"""Overlay transparente que cubre todo el escritorio (apartado 10).

Una sola ventana sin marco, translucida y atravesable por el raton, sobre la que
se dibuja todo: el cursor, la capsula de estado, la barra y la esquina de las
ventanas, el teclado virtual y la pildora de modo.

Tres cosas importantes de este archivo:

* **Coordenadas.** El motor trabaja en pixeles fisicos (los que usa SendInput).
  Qt dibuja en logicos. Con la pantalla al 150 % no son lo mismo, asi que todo
  lo que entra se convierte con ``_to_local`` / ``_sc``.

* **Disciplina de dano (10.1), que es la restriccion dura del proyecto.**
  Repintar 2560x1440 translucidos a 60 Hz cuesta CPU y GPU de verdad. Aqui cada
  elemento del HUD declara su tamano como **constante** en ``style.py`` y
  ``_current_region()`` devuelve **rectangulos sueltos, nunca su envolvente**.
  Ningun elemento puede tener una region que dependa del ancho de la pantalla ni
  del ancho de una ventana: la barra de mover una ventana de 1200 px costaba
  132 000 px y ahora cuesta 15 800, y en ventanas anchas mucho mas.
  Ademas cada elemento lleva su ``_static_since``: si no ha cambiado nada en dos
  fotogramas **sale de la region sucia**. Una capsula quieta cuesta cero, no
  cuesta "poco".

* **Un solo latido.** No hay ningun ``QTimer`` aqui: el overlay se apunta al
  ``Beat`` de ``motion.py`` y se da de baja en ``hideEvent``. Lo que solo
  respira se actualiza a 20 Hz con una compuerta temporal en ``tick``; a 60 Hz
  no se distingue y cuesta el triple.

El contador de pixeles danados que exige el apartado 10.1.7 esta siempre en
marcha (``damage_report()``): es barato y es la unica forma honesta de dar por
terminado el overlay. La tecla F9 no puede llegar hasta aqui -la ventana es
``WS_EX_TRANSPARENT`` y ``WS_EX_NOACTIVATE``, no recibe teclado-, asi que quien
quiera encenderlo llama a ``toggle_debug()``; ``tools/prueba_overlay.py`` mide
con el mismo contador sin depender de una tecla.
"""
from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFontMetricsF, QPainter,
                           QPainterPath, QPen, QRegion)
from PySide6.QtWidgets import QWidget

from ..config import Config
from ..core.screen import virtual_screen
from ..gestures.engine import EngineOutput
from ..gestures.events import Mode
from ..ui import motion
from . import style as S

#: Modos que no merecen pildora inferior: apuntar es el reposo, inactivo no
#: tiene nada que decir y la pausa ya la grita la capsula de arriba.
_SIN_PILDORA = (Mode.POINTING, Mode.IDLE, Mode.PAUSED)

#: Motivo de pausa con temporizador: es el unico que produce cuenta atras.
_PAUSA_CON_RELOJ = "no se detecta al usuario"


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #

def _caja(cx: float, cy: float, w: float, h: float) -> QRect:
    """Rectangulo de tamano constante centrado en un punto."""
    return QRect(int(round(cx - w / 2.0)), int(round(cy - h / 2.0)),
                 int(round(w)), int(round(h)))


def _mezcla(a: QColor, b: QColor, k: float) -> QColor:
    k = max(0.0, min(1.0, k))
    return QColor(int(a.red() + (b.red() - a.red()) * k),
                  int(a.green() + (b.green() - a.green()) * k),
                  int(a.blue() + (b.blue() - a.blue()) * k))


def _alfa(color: QColor, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _px(region: QRegion) -> int:
    """Pixeles que cubre una region. El contador del apartado 10.1.7."""
    # QRegion.rects() es de Qt5. En PySide6 la region se itera directamente, y
    # llamar a rects() lanza una excepcion en cada fotograma: el contador de
    # dano se convertia en la cosa mas cara del overlay.
    total = 0
    for r in region:
        total += r.width() * r.height()
    return total


class _Tween:
    """Interpolacion con curva y duracion, sin ``QPropertyAnimation``.

    Aqui hay decenas de valores animados y un solo latido; una animacion de Qt
    por valor traeria su propio temporizador, que es justo lo que ``motion.py``
    vino a quitar. ``luego`` encadena una segunda etapa: el anillo del cursor
    vuelve del pinch pasando por 23 antes de asentarse en 20, y eso son dos
    tramos, no una curva con rebote.
    """

    def __init__(self, value: float = 0.0) -> None:
        self._a = self._b = self._v = value
        self._t0 = 0.0
        self._dur = 0.0
        self._curve = motion.EASE_GLASS
        self._cola: tuple[float, int, object] | None = None

    def jump(self, value: float) -> None:
        self._a = self._b = self._v = value
        self._dur = 0.0
        self._cola = None

    def to(self, target: float, ms: int, now: float, curve=None,
           luego: tuple[float, int, object] | None = None) -> None:
        if self._dur > 0.0 and abs(target - self._b) < 1e-4:
            return
        if self._dur <= 0.0 and abs(target - self._v) < 1e-4 and luego is None:
            return
        self._a = self._v
        self._b = target
        self._t0 = now
        self._dur = max(0.001, motion.dur(ms) / 1000.0)
        self._curve = curve if curve is not None else motion.EASE_GLASS
        self._cola = luego

    def step(self, now: float) -> float:
        if self._dur <= 0.0:
            return self._v
        k = (now - self._t0) / self._dur
        if k >= 1.0:
            self._v = self._b
            self._dur = 0.0
            cola, self._cola = self._cola, None
            if cola is not None:
                self.to(cola[0], cola[1], now, cola[2])
            return self._v
        self._v = self._a + (self._b - self._a) * motion.ease(max(0.0, k),
                                                              self._curve)
        return self._v

    @property
    def value(self) -> float:
        return self._v

    @property
    def moving(self) -> bool:
        return self._dur > 0.0


class _Elemento:
    """Base de todo lo que pinta el HUD: rectangulos propios y quietud.

    ``firma`` es el estado visible del elemento redondeado a lo que se nota. Si
    dos fotogramas seguidos dan la misma firma, el elemento **sale de la region
    sucia**; eso es todo el apartado 10.1.2, y por si solo ya baja el reposo del
    overlay por debajo de 0,01 Mpx.
    """

    def __init__(self) -> None:
        self.visible = False
        self.rects: list[QRect] = []
        self.firma: tuple = ()
        self._quieto = 9

    def revisar(self, firma: tuple) -> None:
        self._quieto = 0 if firma != self.firma else min(self._quieto + 1, 9)
        self.firma = firma

    @property
    def sucio(self) -> bool:
        return self.visible and self._quieto < 2

    def intersecta(self, region: QRegion) -> bool:
        return any(region.intersects(r) for r in self.rects)


# --------------------------------------------------------------------------- #
# glifos (22 px, linea fina)
# --------------------------------------------------------------------------- #

def _glifo_escudo(p: QPainter, box: QRectF, color: QColor) -> None:
    """Escudo de linea fina con barra diagonal: el modo seguro."""
    x0, y0, w, h = box.left(), box.top(), box.width(), box.height()
    x1, y1, cx = box.right(), box.bottom(), box.center().x()
    path = QPainterPath()
    path.moveTo(cx, y0)
    path.lineTo(x1, y0 + 0.17 * h)
    path.lineTo(x1, y0 + 0.50 * h)
    path.cubicTo(x1, y0 + 0.80 * h, cx + 0.36 * w, y1, cx, y1)
    path.cubicTo(cx - 0.36 * w, y1, x0, y0 + 0.80 * h, x0, y0 + 0.50 * h)
    path.lineTo(x0, y0 + 0.17 * h)
    path.closeSubpath()
    pen = QPen(color, 1.6)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.setClipPath(path)
    p.drawLine(QPointF(x0 + 0.16 * w, y1 - 0.16 * h),
               QPointF(x1 - 0.16 * w, y0 + 0.24 * h))
    p.setClipping(False)


def _glifo_pausa(p: QPainter, box: QRectF, color: QColor) -> None:
    """Dos barras de 3x12: la pausa."""
    cx, cy = box.center().x(), box.center().y()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for dx in (-3.5, 3.5):
        p.drawRoundedRect(QRectF(cx + dx - 1.5, cy - 6.0, 3.0, 12.0), 1.5, 1.5)


def _glifo_punto(p: QPainter, box: QRectF, color: QColor) -> None:
    """Punto de modo: el glifo de la pildora inferior y de la lampara."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(box.center(), box.width() * 0.20, box.width() * 0.20)


_GLIFOS = {"seguro": _glifo_escudo, "pausa": _glifo_pausa, "modo": _glifo_punto}


# --------------------------------------------------------------------------- #
# la capsula: una sola anatomia para el estado y para la pildora de modo
# --------------------------------------------------------------------------- #

def _ancho_capsula(estado: str, detalle: str) -> float:
    """Ancho natural, ya topado. El tope es lo que hace constante el dano."""
    pad, glifo, g1, g2, g3 = S.CAPSULE_ANATOMY
    fm_e = QFontMetricsF(S.fuente("caption", size=12.5, weight=600, tracking=0.4))
    w = pad + glifo + g1 + 1.0 + g2 + fm_e.horizontalAdvance(estado) + pad
    if detalle:
        fm_d = QFontMetricsF(S.fuente("caption", size=11.0, weight=500))
        w += g3 + fm_d.horizontalAdvance(detalle)
    return max(S.CAPSULE_MIN_W, min(S.CAPSULE_MAX_W, w))


def _pintar_capsula(p: QPainter, rect: QRectF, color: QColor, glifos: dict,
                    estado: str, detalle: str, *, alpha: float,
                    texto_a: float, glow: float, rayado: bool,
                    cuenta: float | None = None) -> None:
    """Pinta la capsula entera: halo, placa, rayado, glifo, filo y texto.

    ``glifos`` es ``{nombre: peso}`` para poder cruzar dos glifos durante la
    transicion de estado; la suma de pesos vale 1.
    """
    if alpha <= 0.004:
        return
    radio = min(S.CAPSULE_R, rect.height() / 2.0)
    p.save()
    p.setOpacity(alpha)

    S.paint_glow(p, rect, radio, color, glow)
    S.paint_plate(p, rect, radio, color)

    camino = QPainterPath()
    camino.addRoundedRect(rect, radio, radio)

    if rayado:
        p.save()
        p.setClipPath(camino)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(S.hatch_brush(_alfa(color, S.P.hatch_alpha)))
        p.drawRect(rect)
        p.restore()

    # el glifo se desliza al centro segun se colapsa la capsula
    pad, glifo_w, g1, g2, g3 = S.CAPSULE_ANATOMY
    k = 0.0
    natural = _ancho_capsula(estado, detalle)
    if natural > S.CAPSULE_H:
        k = max(0.0, min(1.0, (rect.width() - S.CAPSULE_H) /
                         (natural - S.CAPSULE_H)))
    gx = rect.center().x() + (rect.left() + pad + glifo_w / 2.0
                              - rect.center().x()) * k
    caja = QRectF(gx - glifo_w / 2.0, rect.center().y() - glifo_w / 2.0,
                  glifo_w, glifo_w)
    for nombre, peso in glifos.items():
        if peso <= 0.004:
            continue
        p.setOpacity(alpha * peso)
        _GLIFOS[nombre](p, caja, color)
    p.setOpacity(alpha)

    if texto_a > 0.004:
        p.setOpacity(alpha * texto_a)
        x = caja.right() + g1
        filo = QPen(_alfa(S.P.edge, S.P.edge.alphaF() * 1.4), 1.0)
        filo.setCosmetic(True)
        p.setPen(filo)
        cxf = math.floor(x) + 0.5
        p.drawLine(QPointF(cxf, rect.center().y() - 10.0),
                   QPointF(cxf, rect.center().y() + 10.0))
        x = cxf + g2

        fuente_e = S.fuente("caption", size=12.5, weight=600, tracking=0.4)
        p.setFont(fuente_e)
        fm_e = QFontMetricsF(fuente_e)
        base = rect.center().y() + fm_e.ascent() / 2.0 - fm_e.descent() / 4.0
        p.setPen(S.P.text)
        p.drawText(QPointF(x, base), estado)
        x += fm_e.horizontalAdvance(estado) + g3

        if detalle:
            fuente_d = S.fuente("caption", size=11.0, weight=500)
            p.setFont(fuente_d)
            fm_d = QFontMetricsF(fuente_d)
            libre = rect.right() - pad - x
            texto = fm_d.elidedText(detalle, Qt.TextElideMode.ElideRight, libre)
            p.setPen(S.P.text_dim)
            p.drawText(QPointF(x, base), texto)
        p.setOpacity(alpha)

    if cuenta is not None:
        # hairline de cuenta atras pegada al borde inferior interior: se vacia
        # de derecha a izquierda. Llena = pausa manual, no hay reloj corriendo.
        p.save()
        p.setClipPath(camino)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alfa(color, 0.55))
        ancho = (rect.width() - 2.0 * radio) * max(0.0, min(1.0, cuenta))
        p.drawRect(QRectF(rect.left() + radio,
                          rect.bottom() - S.COUNTDOWN_INSET - S.COUNTDOWN_H,
                          ancho, S.COUNTDOWN_H))
        p.restore()
    p.restore()


# --------------------------------------------------------------------------- #
# elementos del HUD
# --------------------------------------------------------------------------- #

class _Cursor(_Elemento):
    """Nucleo, anillo de modo, halo y medidor de pinch (10.2).

    Region **fija** de 68x68: radio maximo 30 mas 4 de margen. Es lo que mas se
    mueve y lo que mas veces se repinta del sistema, asi que su rectangulo no
    puede crecer por nada. Por eso la cola de cometa queda descartada: subia el
    rectangulo a 170x170.
    """

    def __init__(self) -> None:
        super().__init__()
        self.xy = (0.0, 0.0)
        self.alpha = motion.Smooth(0.0, motion.TAU_CURSOR)
        self.anillo = _Tween(S.CURSOR_RING_R)
        self.medidor = motion.Smooth(0.0, motion.TAU_OVERLAY_PINCH)
        self.color = QColor(S.P.core)
        self._destello = -1.0
        self._pinzando = False
        self._cerrado = False
        self.flick = 0.0

    def actualizar(self, canvas: "OverlayCanvas", out: EngineOutput | None,
                   now: float) -> None:
        cfg = canvas.cfg
        quiere = bool(out and out.pointer and cfg.ui.show_cursor)
        self.alpha.set(1.0 if quiere else 0.0)
        a = self.alpha.step(now)
        if out is not None and out.pointer is not None:
            self.xy = canvas._to_local(*out.pointer)

        modo = out.mode if out else Mode.POINTING
        self.flick = out.flick_charge if out else 0.0
        objetivo = S.P.modo(modo, flick=self.flick > 0.0)
        self.color = _mezcla(self.color, objetivo, 0.28)

        # medidor de pinch: 0 con los dedos abiertos, 1 al cruzar el cierre
        g = cfg.gestures
        ratio = out.pinch_ratio if out else 1.0
        span = max(1e-3, g.pinch_off - g.pinch_on)
        valor = max(0.0, min(1.0, (g.pinch_off - ratio) / span))
        if self.flick > 0.0:
            valor = self.flick
        self.medidor.set(valor)
        self.medidor.step(now)

        pinzando = bool(out and out.pinching)
        if pinzando != self._pinzando:
            self._pinzando = pinzando
            if pinzando:
                self.anillo.to(S.CURSOR_RING_PINCH_R, 90, now, motion.EASE_SOFT)
                self._destello = now
            else:
                # vuelve con sobrepaso: 23 en 90 ms y asiento en 20 en 50 mas
                self.anillo.to(S.CURSOR_RING_OVERSHOOT_R, 90, now,
                               motion.EASE_LIFT,
                               luego=(S.CURSOR_RING_R, 50, motion.EASE_SOFT))
        self.anillo.step(now)

        self.visible = a > 0.004
        x, y = self.xy
        w, h = S.CURSOR_DAMAGE
        self.rects = [_caja(x, y, w, h)] if self.visible else []
        self.revisar((round(x, 1), round(y, 1), round(a, 3),
                      round(self.anillo.value, 2), round(self.medidor.value, 3),
                      self.color.rgb(), self._destella(now)))

    def _destella(self, now: float) -> bool:
        return 0.0 <= now - self._destello < S.CURSOR_FLASH_MS / 1000.0

    def pintar(self, p: QPainter, now: float) -> None:
        x, y = self.xy
        a = self.alpha.value
        if a <= 0.004:
            return
        centro = QPointF(x, y)

        # 1) halo: es lo que lo hace visible sobre fondos oscuros
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(S.glow_gradient(x, y, S.CURSOR_GLOW_R,
                                          _alfa(S.P.glow,
                                                S.CURSOR_GLOW_ALPHA * a))))
        p.drawEllipse(centro, S.CURSOR_GLOW_R, S.CURSOR_GLOW_R)

        # 2) anillo de modo
        r = self.anillo.value
        pen = QPen(_alfa(self.color, S.CURSOR_RING_ALPHA * a), 1.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(centro, r, r)

        # 3) medidor de pinch sobre el anillo: informacion, no decoracion
        valor = self.medidor.value
        if valor > 0.004:
            arco = QRectF(x - r, y - r, r * 2.0, r * 2.0)
            tinte = S.P.modo(Mode.PAUSED, flick=True) if self.flick > 0.0 \
                else self.color
            pen = QPen(_alfa(tinte, 0.92 * a), S.CURSOR_ARC_W)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            barrido = 360.0 - S.CURSOR_ARC_GAP_DEG
            signo = 1.0 if self.flick > 0.0 else -1.0
            p.drawArc(arco, int(90 * 16), int(signo * valor * barrido * 16))
            # las dos muescas de umbral, como marcas radiales
            for ang in (90.0 + S.CURSOR_ARC_GAP_DEG / 2.0,
                        90.0 - S.CURSOR_ARC_GAP_DEG / 2.0):
                rad = math.radians(ang)
                ux, uy = math.cos(rad), -math.sin(rad)
                pen = QPen(_alfa(self.color, 0.55 * a), 1.0)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.drawLine(QPointF(x + ux * (r - 4.0), y + uy * (r - 4.0)),
                           QPointF(x + ux * (r + 4.0), y + uy * (r + 4.0)))

        # 4) contorno oscuro: es lo que lo salva sobre fondos claros
        d = S.CURSOR_FLASH_D if self._destella(now) else S.CURSOR_CORE_D
        nucleo = d / 2.0
        pen = QPen(_alfa(S.P.outline, S.P.outline.alphaF() * a), 2.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(centro, nucleo + 1.2, nucleo + 1.2)

        # 5) nucleo
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alfa(S.P.core, S.CURSOR_CORE_ALPHA * a))
        p.drawEllipse(centro, nucleo, nucleo)


class _Estado(_Elemento):
    """La capsula de estado (10.3): modo seguro, pausa, o nada.

    Sustituye a las dos pastillas de texto plano de la version anterior. Las tres
    decisiones que la definen:

    * **MODO SEGURO se colapsa a los 4 s** en un circulo con solo el glifo. Un
      recordatorio permanente tiene que volverse ambiental, y de paso el
      colapsado repinta 8,5 kpx en vez de 29 -y cero mientras esta quieto.
    * **EN PAUSA no se colapsa nunca**: una pausa es un estado que tienes que
      poder ver. Respira a 20 Hz y muestra el motivo real del ``SafetyGuard``.
    * **CONTROL ACTIVO no tiene capsula.** Cuando todo va bien no hay nada que
      decir; la ausencia de insignia es el mensaje.
    """

    def __init__(self) -> None:
        super().__init__()
        self.kind = ""
        self.ancho = motion.Smooth(S.CAPSULE_H, motion.TAU_CAPSULE)
        self.alpha = motion.Smooth(0.0, 0.14)
        self.texto = _Tween(0.0)
        self.color = QColor(S.P.warn)
        self.pesos = {"seguro": 0.0, "pausa": 0.0}
        self.estado_txt = ""
        self.detalle = ""
        self.cuenta: float | None = None
        self.glow = S.CAPSULE_GLOW_ALPHA
        self._expandir_hasta = 0.0
        self._modo = Mode.IDLE
        self._pausa_desde = 0.0
        self._fase = 0.0

    def _leer(self, canvas: "OverlayCanvas",
              out: EngineOutput | None) -> tuple[str, str, str]:
        cfg = canvas.cfg
        guardia = canvas.safety_ref
        pausado = bool(out and out.mode is Mode.PAUSED)
        if guardia is not None:
            pausado = pausado or bool(guardia.state.paused)
        if not cfg.safety.control_enabled:
            return "seguro", "MODO SEGURO", "no se inyecta nada"
        if pausado:
            motivo = guardia.state.reason if guardia is not None else ""
            return "pausa", "EN PAUSA", motivo
        return "", "", ""

    def actualizar(self, canvas: "OverlayCanvas", out: EngineOutput | None,
                   now: float, respira: bool) -> None:
        kind, estado, detalle = self._leer(canvas, out)
        if not canvas.cfg.ui.show_hud:
            kind, estado, detalle = "", "", ""

        modo = out.mode if out else Mode.IDLE
        if modo is not self._modo:
            self._modo = modo
            # cualquier cambio de modo reexpande el recordatorio 2,5 s
            self._expandir_hasta = max(self._expandir_hasta,
                                       now + S.CAPSULE_REEXPAND_MS / 1000.0)
        if kind != self.kind:
            if kind == "seguro":
                self._expandir_hasta = now + S.CAPSULE_COLLAPSE_MS / 1000.0
            if kind == "pausa":
                self._pausa_desde = now
            self.kind = kind
        self.estado_txt = estado or self.estado_txt
        if kind:
            self.detalle = detalle

        for nombre in self.pesos:
            objetivo = 1.0 if nombre == kind else 0.0
            self.pesos[nombre] += (objetivo - self.pesos[nombre]) * 0.16
        if kind == "pausa":
            self.color = _mezcla(self.color, S.P.danger, 0.16)
        elif kind == "seguro":
            self.color = _mezcla(self.color, S.P.warn, 0.16)

        self.alpha.set(1.0 if kind else 0.0)
        a = self.alpha.step(now)

        expandida = kind == "pausa" or (kind == "seguro"
                                        and now < self._expandir_hasta)
        natural = _ancho_capsula(self.estado_txt, self.detalle)
        self.ancho.set(natural if expandida else S.CAPSULE_H)
        w = self.ancho.step(now)
        self.texto.to(1.0 if expandida else 0.0,
                      int(S.CAPSULE_FADE_MS), now, motion.EASE_SOFT)
        self.texto.step(now)

        if kind == "pausa":
            if respira:
                self._fase = (now % (S.BREATH_MS / 1000.0)) / (S.BREATH_MS / 1000.0)
            self.glow = S.BREATH_LOW + (S.BREATH_HIGH - S.BREATH_LOW) \
                * S.breath(self._fase)
            reloj = self.detalle == _PAUSA_CON_RELOJ
            if reloj:
                total = max(0.2, canvas.cfg.safety.no_face_timeout_ms / 1000.0)
                self.cuenta = max(0.0, 1.0 - (now - self._pausa_desde) / total)
            else:
                self.cuenta = 1.0
        else:
            self.glow = S.CAPSULE_GLOW_ALPHA
            self.cuenta = None

        self.visible = a > 0.004
        cx = canvas.width() / 2.0
        cy = S.CAPSULE_Y + S.CAPSULE_H / 2.0
        dw = (S.CAPSULE_DAMAGE if w > S.CAPSULE_H + 1.0
              else S.CAPSULE_DAMAGE_SMALL)
        self.rects = [_caja(cx, cy, dw[0], dw[1])] if self.visible else []
        self.revisar((kind, round(a, 3), round(w, 1), round(self.texto.value, 2),
                      round(self.glow, 3), self.color.rgb(),
                      round(self.cuenta or 0.0, 3), self.detalle))

    def rect_capsula(self, canvas: "OverlayCanvas") -> QRectF:
        w = self.ancho.value
        return QRectF(canvas.width() / 2.0 - w / 2.0, S.CAPSULE_Y,
                      w, S.CAPSULE_H)

    def pintar(self, p: QPainter, canvas: "OverlayCanvas") -> None:
        if not self.visible:
            return
        _pintar_capsula(p, self.rect_capsula(canvas), self.color, self.pesos,
                        self.estado_txt, self.detalle,
                        alpha=self.alpha.value, texto_a=self.texto.value,
                        glow=self.glow, rayado=self.kind == "seguro",
                        cuenta=self.cuenta)


class _Lampara(_Elemento):
    """Control activo: sin capsula, solo la lampara al 55 % (10.3).

    El anillo de 34 px se queda quieto; **el punto que respira invalida solo su
    circulo de 24x24**, no la lampara entera. Es la diferencia entre 0,6 kpx y
    16 kpx por fotograma (10.1.5).
    """

    def __init__(self) -> None:
        super().__init__()
        self.alpha = motion.Smooth(0.0, 0.18)
        self.color = QColor(S.P.text)
        self.punto = 1.0
        self._fase = 0.0
        self.rect_punto = QRect()

    def actualizar(self, canvas: "OverlayCanvas", out: EngineOutput | None,
                   now: float, hay_capsula: bool, respira: bool) -> None:
        quiere = bool(canvas.cfg.ui.show_hud and not hay_capsula
                      and out is not None and out.mode is not Mode.IDLE)
        self.alpha.set(S.LAMP_ALPHA if quiere else 0.0)
        a = self.alpha.step(now)
        modo = out.mode if out else Mode.IDLE
        self.color = _mezcla(self.color, S.P.modo(modo), 0.20)
        if respira:
            self._fase = (now % (motion.LAMP / 1000.0)) / (motion.LAMP / 1000.0)
        self.punto = 0.82 + 0.18 * S.breath(self._fase)

        self.visible = a > 0.004
        cx = canvas.width() / 2.0
        cy = S.CAPSULE_Y + S.CAPSULE_H / 2.0
        self.rect_punto = _caja(cx, cy, *S.LAMP_DOT_DAMAGE)
        if not self.visible:
            self.rects = []
        elif self._quieto >= 2:
            # el anillo ya esta pintado y no cambia: solo respira el punto
            self.rects = [self.rect_punto]
        else:
            self.rects = [_caja(cx, cy, *S.LAMP_DAMAGE)]
        self.revisar((round(a, 3), self.color.rgb()))

    def pintar(self, p: QPainter, canvas: "OverlayCanvas") -> None:
        if not self.visible:
            return
        a = self.alpha.value
        cx = canvas.width() / 2.0
        cy = S.CAPSULE_Y + S.CAPSULE_H / 2.0
        pen = QPen(_alfa(self.color, 0.55 * a / S.LAMP_ALPHA), 1.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), S.LAMP_D / 2.0, S.LAMP_D / 2.0)
        r = S.LAMP_DOT_D / 2.0 * self.punto
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alfa(self.color, a))
        p.drawEllipse(QPointF(cx, cy), r, r)


class _Anillo(_Elemento):
    """El anillo de 2 px en el borde de TODA la pantalla durante la pausa.

    Cuatro rectangulos finos: 2 x (2560 + 1440) x 2 = 16 kpx, o sea nada. Es la
    unica region del overlay que depende del tamano de la pantalla, y se sale de
    la regla a proposito: *es* el borde de la pantalla. Se pinta al entrar y al
    salir de la pausa y el resto del tiempo esta quieto, asi que su coste por
    fotograma sostenido es cero.
    """

    def __init__(self) -> None:
        super().__init__()
        self.alpha = motion.Smooth(0.0, 0.20)
        self.color = QColor(S.P.danger)

    def actualizar(self, canvas: "OverlayCanvas", pausado: bool,
                   now: float) -> None:
        self.alpha.set(S.RING_ALPHA if pausado else 0.0)
        a = self.alpha.step(now)
        self.color = S.P.danger
        self.visible = a > 0.004
        w, h, t = canvas.width(), canvas.height(), int(S.RING_THICK)
        self.rects = [QRect(0, 0, w, t), QRect(0, h - t, w, t),
                      QRect(0, t, t, h - 2 * t),
                      QRect(w - t, t, t, h - 2 * t)] if self.visible else []
        self.revisar((round(a, 3),))

    def pintar(self, p: QPainter) -> None:
        if not self.visible:
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alfa(self.color, self.alpha.value))
        for r in self.rects:
            p.drawRect(r)


class _Pildora(_Elemento):
    """Pildora inferior de modo (10.4). Misma anatomia de capsula."""

    def __init__(self) -> None:
        super().__init__()
        self.alpha = motion.Smooth(0.0, motion.TAU_CAPSULE)
        self.subida = motion.Smooth(S.PILL_RISE, motion.TAU_CAPSULE)
        self.color = QColor(S.P.text)
        self.estado_txt = ""
        self.detalle = ""
        self.cy = 0.0

    def actualizar(self, canvas: "OverlayCanvas", out: EngineOutput | None,
                   now: float) -> None:
        modo = out.mode if out else Mode.IDLE
        quiere = bool(out and canvas.cfg.ui.show_hud and modo not in _SIN_PILDORA)
        if quiere:
            self.estado_txt = modo.value
            self.detalle = canvas.nota(now)
        self.alpha.set(1.0 if quiere else 0.0)
        a = self.alpha.step(now)
        self.subida.set(0.0 if quiere else S.PILL_RISE)
        self.subida.step(now)
        self.color = _mezcla(self.color, S.P.modo(modo), 0.20)

        cy = canvas.height() - S.PILL_DY
        techo = canvas.techo_teclado()
        if techo is not None:
            cy = min(cy, techo - 42.0)
        self.cy = cy + self.subida.value

        self.visible = a > 0.004
        self.rects = [_caja(canvas.width() / 2.0, self.cy,
                            *S.PILL_DAMAGE)] if self.visible else []
        self.revisar((round(a, 3), round(self.cy, 1), self.estado_txt,
                      self.detalle, self.color.rgb()))

    def pintar(self, p: QPainter, canvas: "OverlayCanvas") -> None:
        if not self.visible:
            return
        w = _ancho_capsula(self.estado_txt, self.detalle)
        rect = QRectF(canvas.width() / 2.0 - w / 2.0,
                      self.cy - S.CAPSULE_H / 2.0, w, S.CAPSULE_H)
        _pintar_capsula(p, rect, self.color, {"modo": 1.0}, self.estado_txt,
                        self.detalle, alpha=self.alpha.value, texto_a=1.0,
                        glow=S.CAPSULE_GLOW_ALPHA, rayado=False)


class _Chrome(_Elemento):
    """Barra de mover y esquina de redimensionar (10.5).

    Aqui esta la optimizacion mas rentable del rediseno y sale gratis del
    lenguaje visual: la barra tiene **ancho topado a 260 px**, asi que su region
    de dano son tres rectangulos sueltos y constantes -barra (300x44) y dos
    guiones (36x36)- en vez de ``(ancho + 92) x 110``, que en una ventana de
    1200 px son 132 000 px. Reduccion de 8x, y mucho mas en ventanas anchas.
    """

    def __init__(self) -> None:
        super().__init__()
        self.alpha = motion.Smooth(0.0, motion.TAU_WINDOW_BAR)
        self.crece = motion.Smooth(0.0, 0.13)
        self.agarre = _Tween(S.CHROME_GLOW)
        self.geom: tuple[float, float, float, float] | None = None
        self.zona = ""

    def actualizar(self, canvas: "OverlayCanvas", out: EngineOutput | None,
                   now: float) -> None:
        chrome = out.chrome if out else None
        if chrome is not None:
            left, top, right, bottom = chrome.rect
            lx, ly = canvas._to_local(left, top)
            self.geom = (lx, ly, canvas._sc(right - left),
                         canvas._sc(bottom - top))
            self.zona = chrome.zone
        self.alpha.set(1.0 if chrome else 0.0)
        a = self.alpha.step(now)
        self.crece.set(1.0 if chrome else 0.0)
        self.crece.step(now)

        modo = out.mode if out else Mode.IDLE
        sujeta = modo in (Mode.WINDOW_MOVE, Mode.WINDOW_RESIZE)
        self.agarre.to(S.CHROME_GLOW_HELD if sujeta else S.CHROME_GLOW, 120, now,
                       motion.EASE_SOFT)
        self.agarre.step(now)

        self.visible = a > 0.004 and self.geom is not None
        self.rects = []
        if self.visible:
            if self.zona == "move":
                bx, by = self.centro_barra()
                self.rects.append(_caja(bx, by, *S.CHROME_DAMAGE_BAR))
                if sujeta:
                    media = self.ancho_barra() / 2.0 + S.CHROME_DASH_GAP
                    for dx in (-media, media):
                        self.rects.append(_caja(bx + dx, by,
                                                *S.CHROME_DAMAGE_DASH))
            else:
                cx, cy = self.centro_esquina()
                self.rects.append(_caja(cx, cy, *S.CHROME_DAMAGE_CORNER))
        self.revisar((round(a, 3), self.zona, round(self.crece.value, 3),
                      round(self.agarre.value, 3),
                      tuple(round(v, 1) for v in (self.geom or ()))))

    def ancho_barra(self) -> float:
        assert self.geom is not None
        w = self.geom[2]
        lleno = max(S.CHROME_BAR_MIN_W, min(S.CHROME_BAR_MAX_W, w * 0.30))
        return lleno * (0.72 + 0.28 * self.crece.value)

    def centro_barra(self) -> tuple[float, float]:
        assert self.geom is not None
        x, y, w, h = self.geom
        return x + w / 2.0, y + h + S.CHROME_BAR_GAP + S.CHROME_BAR_H / 2.0

    def centro_esquina(self) -> tuple[float, float]:
        assert self.geom is not None
        x, y, w, h = self.geom
        r = S.CHROME_CORNER_R
        return x + w - r * 0.30, y + h - r * 0.30

    def pintar(self, p: QPainter) -> None:
        if not self.visible or self.geom is None:
            return
        a = self.alpha.value
        color = S.P.modo(Mode.WINDOW_MOVE)
        if self.zona == "move":
            bw = self.ancho_barra()
            bx, by = self.centro_barra()
            rect = QRectF(bx - bw / 2.0, by - S.CHROME_BAR_H / 2.0,
                          bw, S.CHROME_BAR_H)
            S.paint_glow(p, rect, S.CHROME_BAR_H / 2.0, color,
                         self.agarre.value * a, S.CHROME_BLUR)
            S.paint_plate(p, rect, S.CHROME_BAR_H / 2.0, color,
                          alpha_placa=0.92 * a, filo=0.0)
            pen = QPen(_alfa(S.P.edge, S.P.edge.alphaF() * 2.0 * a), 1.0)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawLine(QPointF(rect.left() + 3.0, math.floor(rect.top()) + 0.5),
                       QPointF(rect.right() - 3.0, math.floor(rect.top()) + 0.5))
            if self.agarre.value > S.CHROME_GLOW + 0.02:
                k = (self.agarre.value - S.CHROME_GLOW) / \
                    (S.CHROME_GLOW_HELD - S.CHROME_GLOW)
                pen = QPen(_alfa(color, 0.85 * a * k), 1.0)
                pen.setCosmetic(True)
                p.setPen(pen)
                media = bw / 2.0 + S.CHROME_DASH_GAP
                for dx in (-media, media):
                    x = math.floor(bx + dx) + 0.5
                    p.drawLine(QPointF(x, by - S.CHROME_DASH_H / 2.0),
                               QPointF(x, by + S.CHROME_DASH_H / 2.0))
            return

        # esquina de redimensionado: arco de 6 px dentro de un 96x96 constante
        cx, cy = self.centro_esquina()
        r = S.CHROME_CORNER_R * (0.82 + 0.18 * self.crece.value)
        rect = QRectF(cx - r, cy - r, r * 2.0, r * 2.0)
        for grosor, alpha in ((S.CHROME_CORNER_THICK + 10.0, 0.5),
                              (S.CHROME_CORNER_THICK + 4.0, 0.8)):
            pen = QPen(_alfa(color, self.agarre.value * alpha * a), grosor)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(rect, 0, -90 * 16)
        pen = QPen(_alfa(color, 0.92 * a), S.CHROME_CORNER_THICK)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 0, -90 * 16)


class _Teclado(_Elemento):
    """Teclado virtual (10.6).

    **Solo se repinta la tecla afectada** (su rectangulo mas 10 px), nunca el
    panel entero; el rectangulo del panel solo se invalida al abrir, al cerrar o
    al cambiar de layout. Esa es la optimizacion que faltaba: pasar el dedo por
    encima de una tecla repintaba 0,55 Mpx.
    """

    def __init__(self) -> None:
        super().__init__()
        self.alpha = motion.Smooth(0.0, motion.TAU_KEYBOARD)
        self.popup = motion.Smooth(0.0, 0.13)
        self.panel: QRectF | None = None
        self.teclas: dict[str, tuple[QRectF, str]] = {}
        self.estado: dict[str, list[float]] = {}
        self._hover = ""
        self._activa = ""
        self._firma_layout: tuple = ()

    def actualizar(self, canvas: "OverlayCanvas", out: EngineOutput | None,
                   now: float, dt: float) -> None:
        kb = out.keyboard if out else None
        abierto = bool(kb and kb.keys and out is not None
                       and out.mode is not Mode.PAUSED
                       and canvas.cfg.gestures.keyboard_enabled
                       and getattr(canvas.engine_ref, "keyboard_visible", False))
        self.alpha.set(1.0 if abierto else 0.0)
        a = self.alpha.step(now)
        self.popup.set(1.0 if (out and out.accent_popup) else 0.0)
        self.popup.step(now)
        self.visible = a > 0.004 and kb is not None and bool(kb.keys)
        if not self.visible:
            self.rects = []
            self.teclas.clear()
            self.estado.clear()
            self._hover = self._activa = ""
            self.revisar((0.0,))
            return

        x, y, w, h = kb.rect
        lx, ly = canvas._to_local(x, y)
        lw, lh = canvas._sc(w), canvas._sc(h)
        dy = (1.0 - a) * 40.0
        pad = lw * 0.014
        self.panel = QRectF(lx - pad, ly - pad + dy, lw + pad * 2, lh + pad * 2)

        self.teclas = {}
        for key in kb.keys:
            kx, ky = canvas._to_local(key.x, key.y)
            self.teclas[key.ident] = (
                QRectF(kx, ky + dy, canvas._sc(key.w), canvas._sc(key.h)),
                key.label)

        hover = (out.key_hover or "") if out else ""
        activa = (out.key_active or "") if out else ""
        tocadas: set[str] = set()
        for ident in (self._hover, hover, self._activa, activa):
            if ident:
                tocadas.add(ident)
        if activa and activa != self._activa:
            self.estado.setdefault(activa, [0.0, 0.0, -1.0])[2] = now
        self._hover, self._activa = hover, activa

        # las animaciones de tecla son de 90 ms: se integran a mano y solo
        # ensucian mientras corren
        for ident in list(self.estado) + list(tocadas):
            st = self.estado.setdefault(ident, [0.0, 0.0, -1.0])
            paso = min(1.0, dt / (S.KEY_FADE_MS / 1000.0))
            st[0] += ((1.0 if ident == hover else 0.0) - st[0]) * paso
            st[1] += ((1.0 if ident == activa else 0.0) - st[1]) * paso
            vivo = st[0] > 0.004 or st[1] > 0.004 or \
                (st[2] >= 0.0 and now - st[2] < S.KEY_RING_MS / 1000.0)
            if vivo:
                tocadas.add(ident)
            elif ident not in (hover, activa):
                self.estado.pop(ident, None)

        layout = (round(self.panel.x(), 1), round(self.panel.y(), 1),
                  round(self.panel.width(), 1), len(self.teclas),
                  bool(kb.shift), bool(kb.symbols))
        panel_sucio = layout != self._firma_layout or self.alpha.value < 0.999
        self._firma_layout = layout

        self.rects = []
        if panel_sucio:
            self.rects.append(self.panel.adjusted(-6, -6, 6, 6).toAlignedRect())
        for ident in tocadas:
            r = self.teclas.get(ident)
            if r is not None:
                self.rects.append(r[0].adjusted(-S.KEY_PAD, -S.KEY_PAD,
                                                S.KEY_PAD, S.KEY_PAD)
                                  .toAlignedRect())
        if self.popup.value > 0.004 and canvas.engine_ref is not None:
            geom = canvas.engine_ref.accent_popup_geometry()
            if geom is not None and out is not None and out.accent_popup:
                x0, py, cell, ph, n = geom
                px_, py_ = canvas._to_local(x0, py)
                self.rects.append(QRectF(px_ - 10, py_ - 16,
                                         canvas._sc(cell) * n + 20,
                                         canvas._sc(ph) + 26).toAlignedRect())
        # el teclado nunca sale de la region sucia por quietud: sus rectangulos
        # ya son los minimos y el panel solo entra cuando de verdad cambia
        self._quieto = 0

    def pintar(self, p: QPainter, canvas: "OverlayCanvas",
               out: EngineOutput | None, now: float) -> None:
        if not self.visible or self.panel is None or out is None:
            return
        a = self.alpha.value
        S.paint_glow(p, self.panel, S.PANEL_RADIUS, S.P.modo(Mode.KEYBOARD),
                     0.10 * a, S.CHROME_BLUR)
        S.paint_plate(p, self.panel, S.PANEL_RADIUS, S.P.modo(Mode.KEYBOARD),
                      alpha_placa=0.92 * a, filo=0.0)

        alto = 0.0
        for rect, _label in self.teclas.values():
            alto = rect.height()
            break
        fuente = S.fuente("caption", size=max(10.0, alto * 0.36), weight=600)
        p.setFont(fuente)
        for ident, (rect, label) in self.teclas.items():
            st = self.estado.get(ident, (0.0, 0.0, -1.0))
            hover, act = st[0], st[1]
            r = rect.translated(0.0, -S.KEY_LIFT * hover)
            relleno = _mezcla(S.P.key_fill, S.P.key_hover, hover)
            relleno = _mezcla(relleno, S.P.key_active, act)
            alfa = (S.P.key_fill.alphaF()
                    + (S.P.key_hover.alphaF() - S.P.key_fill.alphaF()) * hover)
            alfa += (S.P.key_active.alphaF() - alfa) * act
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_alfa(relleno, alfa * a))
            p.drawRoundedRect(r, S.KEY_RADIUS, S.KEY_RADIUS)

            # filo claro arriba-izquierda: es lo que hace que un teclado plano
            # parezca un teclado
            pen = QPen(_alfa(S.P.key_edge, S.P.key_edge.alphaF() * a * (1.0 - act)),
                       1.0)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            camino = QPainterPath()
            camino.moveTo(r.left() + 0.5, r.bottom() - S.KEY_RADIUS)
            camino.arcTo(QRectF(r.left() + 0.5, r.top() + 0.5,
                                S.KEY_RADIUS * 2, S.KEY_RADIUS * 2), 180, -90)
            camino.lineTo(r.right() - S.KEY_RADIUS, r.top() + 0.5)
            p.drawPath(camino)

            p.setPen(_alfa(_mezcla(S.P.key_text, S.P.key_text_active, act), a))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)

            t0 = st[2]
            if t0 >= 0.0:
                k = (now - t0) / (S.KEY_RING_MS / 1000.0)
                if 0.0 <= k < 1.0:
                    crece = S.KEY_RING * k
                    pen = QPen(_alfa(S.P.key_edge, (1.0 - k) * a), 1.0)
                    pen.setCosmetic(True)
                    p.setPen(pen)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(r.adjusted(-crece, -crece, crece, crece),
                                      S.KEY_RADIUS + crece, S.KEY_RADIUS + crece)

        if out.accent_popup is not None and canvas.engine_ref is not None:
            self._pintar_acentos(p, canvas, out)

    def _pintar_acentos(self, p: QPainter, canvas: "OverlayCanvas",
                        out: EngineOutput) -> None:
        geom = canvas.engine_ref.accent_popup_geometry()
        if geom is None or out.accent_popup is None:
            return
        x0, y, cell, h, _n = geom
        cell, h = canvas._sc(cell), canvas._sc(h)
        _key, opciones, idx = out.accent_popup
        a = self.popup.value
        lx, ly = canvas._to_local(x0, y)
        ly -= (1.0 - a) * 10.0
        # tira horizontal con la misma anatomia de capsula
        tira = QRectF(lx - 6, ly - 6, cell * len(opciones) + 12, h + 12)
        radio = min(S.CAPSULE_R, tira.height() / 2.0)
        color = S.P.modo(Mode.KEYBOARD)
        p.setOpacity(a)
        S.paint_glow(p, tira, radio, color, 0.14)
        S.paint_plate(p, tira, radio, color, alpha_placa=0.94, filo=0.0)
        p.setFont(S.fuente("caption", size=max(11.0, h * 0.42), weight=600))
        for i, opt in enumerate(opciones):
            celda = QRectF(lx + i * cell, ly, cell, h)
            if i == idx:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_alfa(S.P.key_active, S.P.key_active.alphaF()))
                p.drawRoundedRect(celda.adjusted(2, 2, -2, -2), S.KEY_RADIUS,
                                  S.KEY_RADIUS)
                p.setPen(S.P.key_text_active)
            else:
                p.setPen(S.P.key_text)
            p.drawText(celda, Qt.AlignmentFlag.AlignCenter, opt)
        p.setOpacity(1.0)


class _Zoom(_Elemento):
    """Zoom a dos manos: la linea entre las dos manos y sus dos extremos.

    Su region depende de la separacion de las manos, no de la pantalla ni de
    ninguna ventana, asi que no infringe la regla dura; y solo existe mientras
    dura el gesto.
    """

    def __init__(self) -> None:
        super().__init__()
        self.span: tuple[tuple[float, float], tuple[float, float]] | None = None

    def actualizar(self, canvas: "OverlayCanvas",
                   out: EngineOutput | None) -> None:
        self.span = None
        self.visible = False
        self.rects = []
        if out is None or not out.zoom_span:
            self.revisar(())
            return
        (ax, ay), (bx, by) = out.zoom_span
        a = canvas._to_local(ax, ay)
        b = canvas._to_local(bx, by)
        self.span = (a, b)
        self.visible = True
        pad = S.ZOOM_PAD
        self.rects = [QRect(int(min(a[0], b[0]) - pad), int(min(a[1], b[1]) - pad),
                            int(abs(b[0] - a[0]) + pad * 2),
                            int(abs(b[1] - a[1]) + pad * 2))]
        self.revisar((round(a[0], 1), round(a[1], 1),
                      round(b[0], 1), round(b[1], 1)))

    def pintar(self, p: QPainter) -> None:
        if not self.visible or self.span is None:
            return
        (ax, ay), (bx, by) = self.span
        color = S.P.modo(Mode.ZOOMING)
        pen = QPen(_alfa(color, 0.60), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(ax, ay), QPointF(bx, by))
        p.setPen(Qt.PenStyle.NoPen)
        for x, y in ((ax, ay), (bx, by)):
            p.setBrush(_alfa(color, 0.28))
            p.drawEllipse(QPointF(x, y), 13.0, 13.0)
            p.setBrush(_alfa(color, 0.95))
            p.drawEllipse(QPointF(x, y), 6.0, 6.0)


# --------------------------------------------------------------------------- #
# la ventana
# --------------------------------------------------------------------------- #

class OverlayCanvas(QWidget):
    """La ventana del overlay. Contratos con ``app.py``: ``engine_ref``,
    ``set_output``, ``refresh_geometry``, ``show_overlay``, ``hide_overlay``,
    ``hwnd`` y ``update``.

    ``safety_ref`` es opcional y solo sirve para leer el **motivo real** de la
    pausa (``SafetyGuard.state.reason``). Sin el, la capsula de pausa sale sin
    detalle en vez de inventarse uno.
    """

    #: Compuerta del apartado 10.1.4: lo que solo respira va a 20 Hz.
    HZ_RESPIRA = motion.HZ_GLOW

    def __init__(self, cfg: Config) -> None:
        super().__init__(None)
        self.cfg = cfg
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._origin = (0, 0)
        self._dpr = 1.0
        self.refresh_geometry()

        self.out: EngineOutput | None = None
        self.engine_ref = None
        self.safety_ref = None

        self.cursor_el = _Cursor()
        self.estado_el = _Estado()
        self.lampara_el = _Lampara()
        self.anillo_el = _Anillo()
        self.pildora_el = _Pildora()
        self.chrome_el = _Chrome()
        self.teclado_el = _Teclado()
        self.zoom_el = _Zoom()
        self._elementos = (self.teclado_el, self.chrome_el, self.zoom_el,
                           self.anillo_el, self.cursor_el, self.estado_el,
                           self.lampara_el, self.pildora_el)

        self._nota = ""
        self._nota_hasta = 0.0
        self._damage = QRegion()
        self._respira_acc = 0.0
        self._latiendo = False

        # contador de pixeles danados (10.1.7)
        self.debug_damage = False
        self._log: deque[tuple[float, int]] = deque()
        self._fotogramas = 0

    # ---------------- ciclo de vida ----------------
    def show_overlay(self) -> None:
        self._apply_native_flags()
        self.show()
        self._unirse()

    def hide_overlay(self) -> None:
        self._dejar()
        self.hide()

    def _unirse(self) -> None:
        if not self._latiendo:
            motion.beat.join(self, motion.HZ_FULL)
            self._latiendo = True

    def _dejar(self) -> None:
        if self._latiendo:
            motion.beat.leave(self)
            self._latiendo = False

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._unirse()

    def hideEvent(self, event) -> None:  # noqa: N802
        # obligatorio: un participante escondido despierta la CPU sin pintar
        self._dejar()
        super().hideEvent(event)

    def _apply_native_flags(self) -> None:
        try:
            import ctypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x20
            WS_EX_LAYERED = 0x80000
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x80
            hwnd = int(self.winId())
            get = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            setf = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            ex = get(hwnd, GWL_EXSTYLE)
            setf(hwnd, GWL_EXSTYLE,
                 ex | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE
                 | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def hwnd(self) -> int:
        try:
            return int(self.winId())
        except Exception:
            return 0

    def refresh_geometry(self) -> None:
        from PySide6.QtGui import QGuiApplication

        vs = virtual_screen()
        self._origin = (vs.x, vs.y)
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            self._dpr = float(screen.devicePixelRatio()) or 1.0
            self.setGeometry(screen.virtualGeometry())
        else:
            self._dpr = 1.0
            self.setGeometry(vs.x, vs.y, vs.w, vs.h)

    # ---------------- entrada de datos ----------------
    def set_output(self, out: EngineOutput) -> None:
        self.out = out
        if out.note:
            self._nota = out.note
            self._nota_hasta = time.perf_counter() + S.PILL_NOTE_MS / 1000.0
        if self.isVisible():
            # el latido se para solo tras medio segundo quieto; cada salida del
            # motor lo vuelve a despertar
            motion.beat.wake()

    def nota(self, now: float) -> str:
        return self._nota if now < self._nota_hasta else ""

    def techo_teclado(self) -> float | None:
        """Borde superior del teclado en coordenadas locales, si esta abierto."""
        if not self.teclado_el.visible or self.teclado_el.panel is None:
            return None
        return self.teclado_el.panel.top()

    def _to_local(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self._origin[0]) / self._dpr,
                (y - self._origin[1]) / self._dpr)

    def _sc(self, v: float) -> float:
        return v / self._dpr

    # ---------------- animacion ----------------
    def tick(self, dt: float) -> bool:
        now = time.perf_counter()
        out = self.out

        self._respira_acc += dt
        respira = self._respira_acc >= 1.0 / self.HZ_RESPIRA
        if respira:
            self._respira_acc = 0.0

        self.teclado_el.actualizar(self, out, now, dt)
        self.chrome_el.actualizar(self, out, now)
        self.zoom_el.actualizar(self, out)
        self.cursor_el.actualizar(self, out, now)
        self.estado_el.actualizar(self, out, now, respira)
        self.lampara_el.actualizar(self, out, now, bool(self.estado_el.kind),
                                   respira)
        self.anillo_el.actualizar(self, self.estado_el.kind == "pausa", now)
        self.pildora_el.actualizar(self, out, now)

        region = self._current_region()
        damage = QRegion(region)
        damage += self._damage
        self._damage = region
        self._anotar(now, damage)
        if not damage.isEmpty():
            self.update(damage)
        return any(e.sucio for e in self._elementos)

    def _current_region(self) -> QRegion:
        """Rectangulos **sueltos** de los elementos que han cambiado.

        Nunca la envolvente: dos elementos separados en la pantalla no pueden
        pagar el rectangulo que los abraza. Y nada de lo que hay aqui depende
        del ancho de la pantalla ni del ancho de una ventana; solo el anillo de
        pausa, que es el borde de la pantalla por definicion.
        """
        region = QRegion()
        for elem in self._elementos:
            if not elem.sucio:
                continue
            for r in elem.rects:
                region += r
        return region

    # ---------------- contador de dano (10.1.7) ----------------
    def _anotar(self, now: float, damage: QRegion) -> None:
        self._fotogramas += 1
        self._log.append((now, _px(damage)))
        while self._log and now - self._log[0][0] > 5.0:
            self._log.popleft()

    def damage_report(self) -> dict[str, float]:
        """Media y pico de pixeles danados por fotograma en los ultimos 5 s."""
        if not self._log:
            return {"media": 0.0, "pico": 0.0, "fotogramas": 0}
        valores = [v for _t, v in self._log]
        return {"media": sum(valores) / len(valores),
                "pico": float(max(valores)),
                "fotogramas": len(valores)}

    def reset_damage(self) -> None:
        self._log.clear()

    def toggle_debug(self) -> None:
        """Enciende el contador en pantalla. La ventana es click-through y no
        recibe teclado, asi que la F9 del apartado 10.1.7 la tiene que enrutar
        quien si lo recibe; el contador en si esta siempre midiendo."""
        self.debug_damage = not self.debug_damage
        self.update()

    # ---------------- pintado ----------------
    def paintEvent(self, ev) -> None:  # noqa: N802
        out = self.out
        now = time.perf_counter()
        region = ev.region()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # Se pinta todo elemento que **toque** la region, no solo el que la
        # ensucio: Qt limpia a transparente el area danada antes de entrar aqui,
        # asi que un vecino que la solape hay que volver a pintarlo.
        if self.teclado_el.intersecta(region):
            self.teclado_el.pintar(p, self, out, now)
        if self.chrome_el.intersecta(region):
            self.chrome_el.pintar(p)
        if self.zoom_el.intersecta(region):
            self.zoom_el.pintar(p)
        if self.anillo_el.intersecta(region):
            self.anillo_el.pintar(p)
        if self.cursor_el.intersecta(region):
            self.cursor_el.pintar(p, now)
        if self.estado_el.intersecta(region):
            self.estado_el.pintar(p, self)
        if self.lampara_el.intersecta(region):
            self.lampara_el.pintar(p, self)
        if self.pildora_el.intersecta(region):
            self.pildora_el.pintar(p, self)
        if self.debug_damage:
            self._pintar_contador(p)
        p.end()

    def _pintar_contador(self, p: QPainter) -> None:
        r = self.damage_report()
        texto = (f"daño  media {r['media'] / 1000.0:7.2f} kpx/f"
                 f"   pico {r['pico'] / 1000.0:7.2f} kpx"
                 f"   {int(r['fotogramas'])} f")
        p.setFont(S.fuente("caption", size=11.0, weight=600))
        fm = QFontMetricsF(p.font())
        caja = QRectF(16.0, self.height() - 46.0,
                      fm.horizontalAdvance(texto) + 24.0, 26.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(S.P.placa(S.P.danger, 0.86))
        p.drawRoundedRect(caja, 13.0, 13.0)
        p.setPen(S.P.text)
        p.drawText(caja, Qt.AlignmentFlag.AlignCenter, texto)
