"""P5: la pantalla entera se convierte en la interfaz.

Es el compas de magia del asistente (apartado 9.3, P5). El dialogo baja su
cuerpo al 12 % y esta ventana toma el monitor completo: cuatro esquinas que
respiran y, sin cambiar de pantalla, tres dianas que hay que apuntar y pinchar.

Dos cosas que no son adorno y que hay que respetar al tocar esto:

* **El objetivo siguiente viaja, no se teletransporta.** 420 ms por una
  trayectoria curva, para que la vista lo siga hasta la esquina. Un salto seco
  obliga a buscar el objetivo con los ojos, y buscar es lo contrario de que te
  lleven de la mano.
* **Hay que abrir la mano entre esquina y esquina.** Sin esa condicion, mantener
  el pinch encadena las cuatro capturas de golpe y la calibracion sale con los
  cuatro puntos en el mismo sitio. Es un fallo real de la version anterior.

Esta ventana esta **fuera** del lienzo vivo de la aplicacion, asi que su vidrio
es autoiluminado: se pinta con el color base de la paleta a alfa alta, nunca
recortando el lienzo (apartado 12.1).
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ...config import Config
from ...core.mapping import PointerMapper
from ...core.screen import primary_screen
from ...gestures.engine import EngineOutput
from .. import motion, theme
from ..kit.base import Beating, ThemeAware
from . import piezas

#: Las esquinas no van pegadas al borde: apuntar al pixel del canto es incomodo
#: y ademas la homografia sale mejor con los puntos un poco hacia dentro.
INSET = 0.055

#: Permanencia del pinch sobre una esquina antes de capturarla (9.3, P5).
PERMANENCIA_S = 0.9

#: Lo que tarda el objetivo siguiente en viajar hasta su esquina.
VIAJE_MS = 420.0

#: Respiracion del objetivo: escala 1.00 <-> 1.06 en 2,2 s.
RESPIRO_S = 2.2
RESPIRO_ESCALA = 0.06

#: La implosion de una diana acertada.
IMPLOSION_MS = 240.0

RADIO_DIANA = 46.0
DIANAS = 3

_ESQUINAS = ("arriba a la izquierda", "arriba a la derecha",
             "abajo a la derecha", "abajo a la izquierda")


def _pos_esquina(i: int) -> tuple[float, float]:
    x = INSET if i in (0, 3) else 1.0 - INSET
    y = INSET if i in (0, 1) else 1.0 - INSET
    return x, y


class PantallaPunteria(ThemeAware, Beating, QWidget):
    """Cuatro esquinas y tres dianas, a pantalla completa.

    ``progreso`` va de 0 a 1 dentro del tramo que le toca a P5 en el hilo:
    cuatro esquinas y tres dianas son siete sub-objetivos, y el hilo avanza con
    cada uno. El usuario ve la barra crecer porque mueve la mano.
    """

    BEAT_HZ = motion.HZ_FULL

    progreso = Signal(float)
    terminada = Signal(bool)

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(None)
        self.cfg = cfg
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        pantalla = QGuiApplication.primaryScreen()
        if pantalla is not None:
            self.setGeometry(pantalla.geometry())
        else:
            s = primary_screen()
            self.setGeometry(s.x, s.y, s.w, s.h)

        self.fase = "esquinas"          # esquinas | dianas | hecho
        self.paso = 0
        self.aciertos = 0
        self.muestras: list[tuple[float, float]] = []

        self._respiro = 0.0
        self._permanencia = 0.0
        self._viaje = piezas.Progresion(1.0, int(VIAJE_MS), motion.EASE_SOFT)
        self._desde = _pos_esquina(0)
        self._pulso = 1.0               # el rectangulo pulsa al cerrarse
        self._implosion = 1.0
        self._entrada = piezas.Progresion(0.0, motion.HERO)

        self._raw: tuple[float, float] | None = None
        self._punt: tuple[float, float] | None = None
        self._pinch = False
        self._soltar = False            # hay que abrir la mano antes de seguir
        self._modo_color = theme.C.tokens.color.accent

        self._dianas: list[tuple[float, float]] = []
        self.chispas = piezas.Chispas(self, gravedad=140.0)

    # ------------------------------------------------------------------ API
    def empezar(self) -> None:
        self.fase = "esquinas"
        self.paso = 0
        self.aciertos = 0
        self.muestras.clear()
        self._permanencia = 0.0
        self._soltar = False
        self._entrada.jump(0.0)
        self._entrada.set(1.0)
        self._dianas = self._sortear_dianas()
        self.showFullScreen()
        self.chispas.setGeometry(self.rect())
        self.raise_()
        self.activateWindow()
        self.animate()

    def on_output(self, out: EngineOutput) -> None:
        self._raw = out.raw_pointer
        self._punt = out.pointer
        self._pinch = out.pinching
        self._modo_color = theme.C.tokens.mode_color(out.mode)

    # -------------------------------------------------------------- logica
    def _sortear_dianas(self) -> list[tuple[float, float]]:
        """Tres dianas repartidas, ninguna en el borde ni sobre otra."""
        rng = random.Random(4)          # reproducible: las capturas comparan
        puntos: list[tuple[float, float]] = []
        while len(puntos) < DIANAS:
            p = (rng.uniform(0.22, 0.78), rng.uniform(0.24, 0.72))
            if all(math.dist(p, q) > 0.26 for q in puntos):
                puntos.append(p)
        return puntos

    def _objetivo(self) -> tuple[float, float]:
        if self.fase == "esquinas":
            destino = _pos_esquina(self.paso)
            k = self._viaje.value
            if k >= 1.0:
                return destino
            # trayectoria curva: se desvia hacia el centro a mitad de camino
            t = motion.ease(k, motion.EASE_SOFT)
            x = self._desde[0] + (destino[0] - self._desde[0]) * t
            y = self._desde[1] + (destino[1] - self._desde[1]) * t
            comba = math.sin(t * math.pi) * 0.10
            return x + (0.5 - x) * comba, y + (0.5 - y) * comba
        if self.aciertos < len(self._dianas):
            return self._dianas[self.aciertos]
        return 0.5, 0.5

    def _avisar_progreso(self) -> None:
        hechos = self.paso + self.aciertos
        self.progreso.emit(min(1.0, hechos / float(4 + DIANAS)))

    def tick(self, dt: float) -> bool:
        self._entrada.step(dt)
        self._viaje.step(dt)
        self._respiro = (self._respiro + dt / RESPIRO_S) % 1.0
        if self._pulso < 1.0:
            self._pulso = min(1.0, self._pulso + dt * 1000.0 / motion.dur(420))
        if self._implosion < 1.0:
            self._implosion = min(
                1.0, self._implosion + dt * 1000.0 / motion.dur(int(IMPLOSION_MS)))

        if not self._pinch:
            self._soltar = False

        if self.fase == "esquinas":
            self._paso_esquinas(dt)
        elif self.fase == "dianas":
            self._paso_dianas()
        self.update()
        return self.fase != "hecho"

    def _paso_esquinas(self, dt: float) -> None:
        listo = (self._pinch and not self._soltar and self._raw is not None
                 and self._viaje.settled)
        if listo:
            self._permanencia = min(PERMANENCIA_S, self._permanencia + dt)
            if self._permanencia >= PERMANENCIA_S:
                self._capturar_esquina()
        else:
            self._permanencia = max(0.0, self._permanencia - dt * 2.0)

    def _capturar_esquina(self) -> None:
        assert self._raw is not None
        self.muestras.append(self._raw)
        self._permanencia = 0.0
        self._soltar = True
        self._implosion = 0.0
        self._desde = _pos_esquina(self.paso)
        self.paso += 1
        self._avisar_progreso()
        if self.paso >= 4:
            self._pulso = 0.0
            self._cerrar_region()
            self.fase = "dianas"
        else:
            self._viaje.jump(0.0)
            self._viaje.set(1.0)

    def _cerrar_region(self) -> None:
        """Guarda la homografia. Si cv2 se queja, se sigue sin calibrar."""
        try:
            h = PointerMapper.compute_homography(self.muestras, primary_screen())
        except Exception:
            return
        self.cfg.mapping.homography = h
        self.cfg.save()

    def _paso_dianas(self) -> None:
        if self.aciertos >= len(self._dianas) or self._punt is None:
            return
        if not self._pinch or self._soltar:
            return
        cx, cy = self._dianas[self.aciertos]
        sx, sy = self._punt
        pantalla = primary_screen()
        # el puntero llega en coordenadas de pantalla fisica; esta ventana esta
        # en coordenadas logicas de Qt, asi que se compara en fraccion
        fx = (sx - pantalla.x) / max(1.0, float(pantalla.w))
        fy = (sy - pantalla.y) / max(1.0, float(pantalla.h))
        dist = math.hypot((fx - cx) * self.width(), (fy - cy) * self.height())
        if dist > RADIO_DIANA * 1.5:
            return
        self._soltar = True
        self._implosion = 0.0
        self.chispas.estallar(12, QPointF(cx * self.width(), cy * self.height()),
                              color=self._modo_color, lado=3.0, rapidez=240.0)
        self.aciertos += 1
        self._avisar_progreso()
        if self.aciertos >= len(self._dianas):
            self.fase = "hecho"
            self.progreso.emit(1.0)
            self._terminar(True)

    def _terminar(self, ok: bool) -> None:
        self.rest()
        self.hide()
        self.terminada.emit(ok)

    def keyPressEvent(self, event) -> None:                 # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.fase = "hecho"
            self._terminar(False)

    # ------------------------------------------------------------- pintado
    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())

        # vidrio autoiluminado: aqui no hay lienzo que recortar (12.1)
        fondo = QColor(t.canvas.base)
        fondo.setAlphaF(0.94 * max(0.15, self._entrada.value))
        p.fillRect(self.rect(), fondo)
        p.setOpacity(self._entrada.value)

        self._pintar_region(p, t, w, h)

        if self.fase == "esquinas":
            self._pintar_esquinas(p, t, w, h)
        elif self.fase == "dianas":
            self._pintar_dianas(p, t, w, h)

        self._pintar_puntero(p, t, w, h)
        self._pintar_textos(p, t, w, h)
        p.end()

    def _pintar_region(self, p: QPainter, t, w: float, h: float) -> None:
        """El rectangulo se va dibujando lado a lado y pulsa al cerrarse."""
        if not self.muestras:
            return
        pts = [QPointF(*_pos_esquina(i)) for i in range(min(self.paso, 4))]
        pts = [QPointF(q.x() * w, q.y() * h) for q in pts]
        color = QColor(t.color.accent)
        if self._pulso < 1.0:
            k = motion.ease(self._pulso, motion.EASE_GLASS)
            color.setAlphaF(0.35 + 0.65 * (1.0 - k))
        else:
            color.setAlphaF(0.35)
        pluma = QPen(color)
        pluma.setWidthF(2.0 if self._pulso >= 1.0 else 3.0)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        camino = QPainterPath()
        camino.moveTo(pts[0])
        for q in pts[1:]:
            camino.lineTo(q)
        if self.paso >= 4:
            camino.closeSubpath()
        p.drawPath(camino)

    def _pintar_esquinas(self, p: QPainter, t, w: float, h: float) -> None:
        # las ya capturadas, colapsadas a un punto
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.color.ok))
        for i in range(self.paso):
            x, y = _pos_esquina(i)
            p.drawEllipse(QPointF(x * w, y * h), 6.0, 6.0)

        if self.paso >= 4:
            return
        ox, oy = self._objetivo()
        c = QPointF(ox * w, oy * h)
        respiro = 1.0 + RESPIRO_ESCALA * (
            0.5 - 0.5 * math.cos(self._respiro * 2.0 * math.pi))
        if motion.reduce_motion():
            respiro = 1.0
        radio = RADIO_DIANA * respiro
        if self._implosion < 1.0:
            radio *= 1.0 - 0.7 * motion.ease(self._implosion, motion.EASE_GLASS)

        aro = QColor(t.text.secondary)
        aro.setAlphaF(0.45)
        pluma = QPen(aro)
        pluma.setWidthF(1.6)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, radio, radio)

        k = self._permanencia / PERMANENCIA_S
        if k > 0.001:
            pluma = QPen(QColor(t.color.accent))
            pluma.setWidthF(5.0)
            pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pluma)
            p.drawArc(QRectF(c.x() - radio, c.y() - radio, 2 * radio, 2 * radio),
                      90 * 16, -int(k * 360 * 16))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.text.primary))
        p.drawEllipse(c, 7.0, 7.0)

    def _pintar_dianas(self, p: QPainter, t, w: float, h: float) -> None:
        for i, (cx, cy) in enumerate(self._dianas):
            c = QPointF(cx * w, cy * h)
            if i < self.aciertos:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(t.color.ok))
                p.drawEllipse(c, 6.0, 6.0)
                continue
            if i > self.aciertos:
                aro = QColor(t.text.quiet)
                aro.setAlphaF(0.35)
                pluma = QPen(aro)
                pluma.setWidthF(1.2)
                p.setPen(pluma)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, RADIO_DIANA * 0.5, RADIO_DIANA * 0.5)
                continue
            respiro = 1.0 + RESPIRO_ESCALA * (
                0.5 - 0.5 * math.cos(self._respiro * 2.0 * math.pi))
            radio = RADIO_DIANA * (1.0 if motion.reduce_motion() else respiro)
            if self._implosion < 1.0:
                radio *= 1.0 - 0.7 * motion.ease(self._implosion, motion.EASE_GLASS)
            pluma = QPen(QColor(self._modo_color))
            pluma.setWidthF(2.0)
            p.setPen(pluma)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, radio, radio)
            p.drawEllipse(c, radio * 0.45, radio * 0.45)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self._modo_color))
            p.drawEllipse(c, 5.0, 5.0)

    def _pintar_puntero(self, p: QPainter, t, w: float, h: float) -> None:
        """El puntero en crudo: la prueba de que te esta siguiendo."""
        if self.fase == "esquinas":
            punto = self._raw
            if punto is None:
                return
            c = QPointF(punto[0] * w, punto[1] * h)
        else:
            if self._punt is None:
                return
            s = primary_screen()
            c = QPointF((self._punt[0] - s.x) / max(1.0, float(s.w)) * w,
                        (self._punt[1] - s.y) / max(1.0, float(s.h)) * h)
        color = QColor(self._modo_color)
        color.setAlphaF(0.85 if self._pinch else 0.45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(c, 7.0, 7.0)

    def _pintar_textos(self, p: QPainter, t, w: float, h: float) -> None:
        if self.fase == "esquinas":
            titulo = f"Esquina {min(self.paso + 1, 4)} de 4"
            detalle = (f"Apunta {_ESQUINAS[min(self.paso, 3)]} y junta los dedos "
                       "hasta que el anillo se cierre.")
            if self._soltar:
                detalle = "Abre la mano antes de la siguiente esquina."
        else:
            titulo = f"Diana {min(self.aciertos + 1, DIANAS)} de {DIANAS}"
            detalle = "Apunta al círculo y junta los dedos."
        piezas.texto(p, QRectF(0, h * 0.42, w, 44), "title", titulo,
                     t.text.primary,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        piezas.texto(p, QRectF(0, h * 0.42 + 46, w, 24), "body", detalle,
                     t.text.secondary,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        piezas.texto(p, QRectF(0, h - 56, w, 22), "overline",
                     "Esc para volver al asistente", t.text.quiet,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
