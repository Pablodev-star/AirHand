"""El armazon del asistente: el cromo permanente del apartado 9.2.

Las siete paginas viven en ``pages.py``; aqui esta lo que las envuelve, que es
justamente lo que convierte un formulario en un acompanamiento:

* **El hilo de progreso** crece de forma continua. Cada pagina emite ``progreso``
  con su fraccion cumplida y el armazon la reparte dentro del tramo que le toca
  (``TRAMOS``). Ver la barra moverse porque mueves la mano, y no porque pulsas
  «Continuar», es el mecanismo mas importante de todo el apartado 9.
* **El boton primario no existe** hasta que la pagina es satisfacible, y entonces
  se materializa. No se deshabilita: no esta. La ausencia es la senal de "te
  estoy guiando" y la aparicion es la recompensa.
* **La estimacion de tiempo esta viva**: se calcula con lo que las paginas ya
  visitadas han tardado de verdad, no con la tabla de duraciones esperadas.
* **Nunca esperas a solas**: arrancar el motor es una espera de varios segundos
  con el modelo de manos cargandose, y se muestra como tres pasos con nombre que
  se van marcando con hechos reales.
* **Salir siempre es posible**, en ``overline`` casi invisible abajo a la
  izquierda.
* **La ultima pagina no se cierra: se expande** hasta el area del mosaico del
  panel. La ultima cosa que ve el usuario es que el asistente y el panel son el
  mismo objeto.

Contratos con ``app.py`` que no se pueden romper: ``SetupWizard(cfg, ctl,
parent=None)``, la senal ``completed(bool)`` y el metodo ``exec()``. Y el
``commit()`` de la configuracion solo se ejecuta al terminar de verdad.

Ni un ``QTimer``: el armazon late con el ``Beat`` como todo lo demas, y
``hideEvent`` de ``Beating`` lo da de baja pase lo que pase.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QDialog, QWidget

from ...config import Config
from ...core.controller import Controller
from ...gestures.engine import EngineOutput
from .. import glass, motion, theme
from ..kit.base import Beating, ThemeAware
from ..kit.controls import Button
from ..tokens import R_LG, R_XL
from . import piezas
from .pages import (AimPage, CameraPage, FinishPage, FramingPage, GesturePage,
                    IntroPage, Pagina, PinchPage)

__all__ = ["SetupWizard", "TRAMOS", "IntroPage", "CameraPage", "FramingPage",
           "GesturePage", "PinchPage", "AimPage", "FinishPage"]

#: Reparto del hilo de progreso entre las siete paginas (9.2.1), en tanto por
#: ciento. No es lineal a proposito: las paginas donde el usuario trabaja mas
#: (camara, encuadre, pinch) se llevan mas recorrido, y asi la barra avanza al
#: ritmo del esfuerzo y no al de los clics.
TRAMOS: tuple[tuple[int, int], ...] = (
    (0, 5), (5, 22), (22, 42), (42, 58), (58, 74), (74, 92), (92, 100))

#: Geometria de la lamina del dialogo (9).
ANCHO = 1040
ALTO = 760

#: Margen del velo alrededor de la lamina cuando el asistente va suelto.
VELO = 40

#: Huecos internos de la lamina.
PAD_X = 56.0
PAD_ARRIBA = 62.0
PAD_ABAJO = 96.0

#: El hilo, pegado al borde superior.
HILO_ALTO = 3.0
HILO_GLOW = 6.0

#: Lo que tarda la lamina en convertirse en el panel (9.3, P6).
EXPANSION_MS = 620

#: Lavado negro del velo. En claro no puede ser el mismo: sobre un lienzo casi
#: blanco un 0.55 lo deja gris plomo y el modo claro se cae (apartado 11).
VELO_ALFA_OSCURO = 0.55
VELO_ALFA_CLARO = 0.24

#: Los tres pasos con nombre del arranque del motor (9.2.5). Cada uno se marca
#: con un hecho comprobable, nunca con un temporizador.
PASOS_MOTOR = ("Abriendo la cámara", "Cargando el modelo de manos", "Listo")


# --------------------------------------------------------------------------- #
# la espera con nombre
# --------------------------------------------------------------------------- #

class EsperaMotor(ThemeAware, Beating, QWidget):
    """La placa que aparece mientras arranca el motor.

    Existe porque cargar el modelo de manos bloquea el hilo de la interfaz uno o
    dos segundos y una ventana congelada sin explicacion es lo peor que le puede
    pasar a alguien que acaba de instalar el programa. Con los pasos pintados
    **antes** de la llamada bloqueante, el usuario ve en que se esta yendo el
    tiempo.
    """

    BEAT_HZ = motion.HZ_GLOW

    ALTO_TITULO = 30.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pasos = piezas.PasosConNombre(list(PASOS_MOTOR), self)
        self._entrada = piezas.Progresion(0.0, motion.SECTION_IN)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def sizeHint(self):                                     # noqa: N802
        return self.pasos.sizeHint()

    def entrar(self) -> None:
        self._entrada.jump(0.0)
        self._entrada.set(1.0)
        for i in range(len(PASOS_MOTOR)):
            self.pasos.set_hecho(i, False)
        self.animate()

    def colocar(self) -> None:
        self.pasos.setGeometry(QRect(28, int(self.ALTO_TITULO + 14),
                                     self.width() - 56, self.pasos.height()))

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        self.colocar()

    def alto_pedido(self) -> int:
        return int(self.ALTO_TITULO + 14 + self.pasos.height() + 26)

    def tick(self, dt: float) -> bool:
        vivo = self._entrada.step(dt)
        self.update()
        if not vivo:
            self.rest()
        return vivo

    def paintEvent(self, event) -> None:                    # noqa: N802
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        k = self._entrada.value
        p.setOpacity(k)
        caja = QRectF(self.rect()).adjusted(0, (1.0 - k) * 10.0, 0, 0)
        glass.paint_sheet(p, caja, "E3", R_LG, tokens=t,
                          canvas_origin=self.mapTo(self.window(), QPoint(0, 0)))
        piezas.texto(p, QRectF(28.0, 16.0, self.width() - 56.0,
                               self.ALTO_TITULO),
                     "h2", "Preparando el motor", t.text.primary)
        p.end()


# --------------------------------------------------------------------------- #
# el asistente
# --------------------------------------------------------------------------- #

class SetupWizard(ThemeAware, Beating, QDialog):
    """Las siete paginas dentro de una sola lamina que al final es el panel."""

    #: True si el usuario quiere el control real activado al salir.
    completed = Signal(bool)

    #: El armazon solo mueve el hilo, el destello, el anillo y la estimacion, y
    #: ninguna de esas cosas se distingue a 60 Hz. Lo que si va a 60 Hz late por
    #: su cuenta: las paginas y el barrido especular.
    BEAT_HZ = motion.HZ_GLOW

    def __init__(self, cfg: Config, ctl: Controller,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.ctl = ctl
        self.setWindowTitle("Configuración de AirTouch")
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog
                            | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        # -- lienzo propio: el velo y el recorte de todas las laminas de dentro
        self.canvas = glass.CanvasSource(theme.C.tokens)
        self._canvas_previo = glass.active_canvas()

        # -- estado del cromo
        self._hilo = piezas.Progresion(0.0, 300, motion.EASE_GLASS)
        self._anillo = 0.0
        self._destello = 0.0
        self._barrido = motion.SpecularSweep(self.update)
        self._indice = 0
        self._resto = 0.0
        self._t_pagina = time.perf_counter()
        self._gastado: dict[int, float] = {}
        self._retardo = 0.0
        self._retardos = 0
        self._limpio = False
        self._expansion: piezas.Progresion | None = None
        self._caja_lamina = QRectF()
        self._visto_output = False
        self._fase_motor = 0
        self._reloj_cierre = 0.0

        # -- las siete paginas
        self.pages: list[Pagina] = [
            IntroPage(self),
            CameraPage(cfg, ctl, self),
            FramingPage(cfg, ctl, self),
            GesturePage(self),
            PinchPage(cfg, self),
            AimPage(cfg, ctl, self),
            FinishPage(cfg, ctl, self),
        ]
        for pagina in self.pages:
            pagina.hide()
            pagina.progreso.connect(self._progreso_de_pagina)
            pagina.estado_cambiado.connect(self._refrescar)
            pagina.pedir_avance.connect(self._next)
            pagina.pedir_destello.connect(self._flash)
            pagina.pedir_barrido.connect(self._barrido.start)
            pagina.anillo.connect(self._set_anillo)
        self.pages[0].empezar.connect(self._next)           # type: ignore[attr-defined]
        self.pages[5].apagar.connect(self._apagar)          # type: ignore[attr-defined]

        # -- cromo
        self.espera = EsperaMotor(self)
        self.espera.hide()
        self.salir = piezas.Enlace("Salir del asistente", self)
        self.salir.pulsado.connect(self._salir)
        # «Atras» va con «Salir» y no junto al primario a proposito: la esquina
        # derecha es del boton que se materializa, y meterle un vecino que
        # aparece y desaparece le robaria justo la senal que lo hace funcionar
        self.atras = piezas.Enlace("Atrás", self)
        self.atras.pulsado.connect(self._back)
        self.boton: Button | None = None
        self._rehacer_boton(False, "Continuar")

        self.resize(ANCHO + 2 * VELO, ALTO + 2 * VELO)
        if parent is not None:
            self.setGeometry(parent.geometry())

        self.ctl.output_ready.connect(self._on_output,
                                      Qt.ConnectionType.QueuedConnection)
        self.ctl.frame_ready.connect(self._on_frame,
                                     Qt.ConnectionType.QueuedConnection)
        self.ctl.stats_ready.connect(self._on_stats,
                                     Qt.ConnectionType.QueuedConnection)
        self._goto(0)

    # ------------------------------------------------------------- geometria
    @property
    def pagina(self) -> Pagina:
        return self.pages[self._indice]

    def lamina(self) -> QRectF:
        """La lamina E4 dentro de la ventana, centrada sobre el velo.

        Mide 1040x760 siempre que quepa con su velo alrededor; en una ventana
        mas justa se encoge en vez de salirse, porque el asistente tambien se
        abre en portatiles de 1366x768.
        """
        w, h = float(self.width()), float(self.height())
        ancho = min(float(ANCHO), max(320.0, w - 2.0 * VELO))
        alto = min(float(ALTO), max(260.0, h - 2.0 * VELO))
        return QRectF(round((w - ancho) / 2.0), round((h - alto) / 2.0),
                      ancho, alto)

    def _caja_panel(self) -> QRectF:
        """Area del mosaico del panel: adonde viaja la lamina al terminar.

        Zona A del apartado 8.1 son 320 px fijos a la izquierda y la zona C es
        la barra flotante inferior; el mosaico es lo que queda.
        """
        base = QRectF(self.rect())
        padre = self.parentWidget()
        if padre is not None:
            base = QRectF(padre.rect())
            base.translate(QPointF(padre.mapToGlobal(QPoint(0, 0))
                                   - self.mapToGlobal(QPoint(0, 0))))
        izquierda = 320.0 + 24.0 if base.width() > 900.0 else 24.0
        return QRectF(base.left() + izquierda, base.top() + 24.0,
                      max(240.0, base.width() - izquierda - 24.0),
                      max(200.0, base.height() - 24.0 - 96.0))

    def _colocar(self) -> None:
        r = self.lamina() if self._expansion is None else self._caja_lamina
        self._caja_lamina = r
        pagina = self.pagina
        if pagina.SIN_CROMO:
            caja = r.adjusted(44.0, 34.0, -44.0, -34.0)
        else:
            caja = QRectF(r.left() + PAD_X, r.top() + PAD_ARRIBA,
                          max(200.0, r.width() - 2.0 * PAD_X),
                          max(160.0, r.height() - PAD_ARRIBA - PAD_ABAJO))
        pagina.setGeometry(caja.toRect())

        alto = self.espera.alto_pedido()
        self.espera.setGeometry(int(caja.left() + caja.width() * 0.18),
                                int(caja.center().y() - alto / 2.0),
                                int(max(280.0, caja.width() * 0.64)), alto)

        s = self.salir.sizeHint()
        self.salir.setGeometry(int(r.left() + PAD_X),
                               int(r.bottom() - 40.0), s.width(), s.height())
        b = self.atras.sizeHint()
        self.atras.setGeometry(int(r.left() + PAD_X + s.width() + 24.0),
                               int(r.bottom() - 40.0), b.width(), b.height())
        if self.boton is not None:
            g = self.boton.sizeHint()
            self.boton.setGeometry(int(r.right() - PAD_X - g.width()),
                                   int(r.bottom() - PAD_ABAJO + 22.0),
                                   g.width(), g.height())

    def resizeEvent(self, event) -> None:                   # noqa: N802
        super().resizeEvent(event)
        self.canvas.resize(self.width(), self.height())
        self._colocar()

    def showEvent(self, event) -> None:                     # noqa: N802
        glass.set_active_canvas(self.canvas)
        self.canvas.resize(self.width(), self.height())
        self.canvas.start()
        super().showEvent(event)
        self.animate()
        self._colocar()

    def hideEvent(self, event) -> None:                     # noqa: N802
        self.canvas.stop()
        # el barrido se apunta al latido por su cuenta: hay que agotarlo o
        # queda una banda congelada y un asiento vivo en el Beat
        self._barrido.tick(10.0)
        super().hideEvent(event)

    def on_theme(self) -> None:
        self.canvas.set_tokens(theme.C.tokens)
        self._colocar()
        self.update()

    # ------------------------------------------------------------ navegacion
    def _goto(self, index: int) -> None:
        index = max(0, min(len(self.pages) - 1, index))
        anterior = self.pages[self._indice]
        if index != self._indice:
            self._gastado[self._indice] = (self._gastado.get(self._indice, 0.0)
                                           + time.perf_counter() - self._t_pagina)
            anterior.on_leave()
            anterior.rest()
            anterior.hide()

        self._indice = index
        self._t_pagina = time.perf_counter()
        self._anillo = 0.0
        pagina = self.pages[index]
        if self._fase_motor:
            self._quitar_espera()

        lo, _hi = TRAMOS[index]
        if self._hilo.target * 100.0 < lo:
            self._hilo.set(lo / 100.0)

        cromo = not pagina.SIN_CROMO
        self.salir.setVisible(cromo)
        self.atras.setVisible(cromo and 0 < index < len(self.pages) - 1)
        self._rehacer_boton(pagina.can_advance(), pagina.next_label())
        if self.boton is not None:
            self.boton.setVisible(cromo)

        if isinstance(pagina, PinchPage):
            gesto = self.pages[3]
            pagina.set_medidas(gesto.minimos, gesto.abierto)  # type: ignore[attr-defined]
        elif isinstance(pagina, FinishPage):
            # el recibo no inventa nada: sale de lo que el armazon ha visto
            # pasar de verdad por las senales del controlador
            pagina.retardo_ms = self._retardo
            pagina.gestos_ok = len(self.pages[3].minimos)     # type: ignore[attr-defined]

        pagina.show()
        pagina.on_enter()
        self._colocar()
        self.update()

        if pagina.NECESITA_MOTOR and not self.ctl.running:
            self._arrancar_motor()
        self.animate()

    def _next(self) -> None:
        if self._expansion is not None:
            return
        if not self.pagina.can_advance():
            return
        if self._indice >= len(self.pages) - 1:
            self._terminar()
            return
        self._goto(self._indice + 1)

    def _back(self) -> None:
        if self._expansion is None and self._indice > 0:
            self._goto(self._indice - 1)

    def _salir(self) -> None:
        """Salir siempre es posible, y salir no da la vuelta por hecha."""
        self.pagina.on_leave()
        self.reject()

    def _terminar(self) -> None:
        """La ultima pagina no se cierra: se expande hasta el panel."""
        final = self.pages[-1]
        final.on_leave()
        final.commit()                                      # type: ignore[attr-defined]
        quiere = bool(final.quiere_control())               # type: ignore[attr-defined]
        # se avisa antes de la animacion: asi el panel se levanta *detras* y la
        # lamina aterriza sobre el mosaico ya montado (9.3, P6)
        self.completed.emit(quiere)
        self._hilo.set(1.0)                 # el hilo se cierra al entrar, no antes
        self._caja_lamina = self.lamina()
        self._expansion = piezas.Progresion(0.0, EXPANSION_MS, motion.EASE_SOFT)
        self._expansion.set(1.0)
        for w in (self.salir, self.atras):
            w.hide()
        if self.boton is not None:
            self.boton.hide()
        final.rest()
        final.hide()
        self.animate()

    # ----------------------------------------------------------- el arranque
    #: Lo que se espera al video antes de quitar la placa. Si a los 5 s el motor
    #: corre pero no llega nada, el problema no es la espera: es que no hay
    #: camara, y la propia pagina ya lo explica en su estado vacio. Dejar la
    #: placa puesta indefinidamente taparia el unico texto que ayuda.
    ESPERA_MAX_S = 5.0

    def _arrancar_motor(self) -> None:
        if self._fase_motor:
            return
        self._fase_motor = 1
        self._reloj_cierre = 0.0
        self._visto_output = False
        self.espera.entrar()
        self.espera.show()
        self.espera.raise_()

    def _paso_motor(self, dt: float) -> None:
        pasos = self.espera.pasos
        if self._fase_motor == 1:
            # un fotograma pintado antes de la llamada que bloquea: si no, el
            # usuario ve la ventana congelada sin saber por que
            self._fase_motor = 2
            return
        if self._fase_motor == 2:
            self.ctl.start()
            self._fase_motor = 3
            self._reloj_cierre = 0.0
        pasos.set_hecho(0, bool(self.ctl.airlink.running
                                or self.ctl.source_connected
                                or self.ctl.running))
        pasos.set_hecho(1, bool(getattr(self.ctl.vision, "ready", False)))
        self._reloj_cierre += dt
        if self._visto_output:
            pasos.set_hecho(2, True)
            self._fase_motor = 4
            self._reloj_cierre = 0.0
        elif self._reloj_cierre >= self.ESPERA_MAX_S:
            self._quitar_espera()

    def _cerrar_espera(self, dt: float) -> None:
        self._reloj_cierre += dt
        if self._reloj_cierre >= 0.6:
            self._quitar_espera()

    def _quitar_espera(self) -> None:
        self._fase_motor = 0
        self.espera.rest()
        self.espera.hide()

    # -------------------------------------------------------------- el cromo
    def _rehacer_boton(self, nacido: bool, rotulo: str) -> None:
        """El boton primario se rehace por pagina.

        No se puede reutilizar: ``materialize()`` es de un solo sentido, y la
        gracia del apartado 9.2.3 es justamente que en la pagina siguiente el
        boton **vuelve a no existir**.
        """
        viejo = self.boton
        if viejo is not None:
            viejo.hide()
            viejo.deleteLater()
        self.boton = Button(rotulo, "primary", self, born=nacido)
        self.boton.clicked.connect(self._next)
        self.boton.show()

    def _refrescar(self) -> None:
        pagina = self.pagina
        boton = self.boton
        if boton is None:
            return
        boton.setText(pagina.next_label())
        if pagina.can_advance() and not boton.born:
            boton.materialize()
        self._colocar()
        self.update()

    def _progreso_de_pagina(self, fraccion: float) -> None:
        lo, hi = TRAMOS[self._indice]
        k = max(0.0, min(1.0, float(fraccion)))
        self._hilo.set((lo + (hi - lo) * k) / 100.0)
        self.animate()

    def _set_anillo(self, k: float) -> None:
        self._anillo = max(0.0, min(1.0, float(k)))
        self.update()

    def _flash(self) -> None:
        self._destello = 1.0
        self.animate()

    def _apagar(self, opacidad: float) -> None:
        """P5 pide que el dialogo se aparte mientras la pantalla es la interfaz."""
        self.setWindowOpacity(max(0.05, min(1.0, float(opacidad))))

    # --------------------------------------------------------- tiempo honesto
    def _estimar(self) -> float:
        """Segundos que quedan, con el ritmo real de quien esta delante."""
        esperado = sum(self.pages[i].SEGUNDOS for i in self._gastado)
        real = sum(self._gastado.values())
        factor = 1.0
        if esperado > 1.0 and real > 0.0:
            factor = max(0.6, min(2.2, real / esperado))
        resto = sum(p.SEGUNDOS for p in self.pages[self._indice + 1:]) * factor
        aqui = self.pages[self._indice].SEGUNDOS * factor
        resto += max(0.0, aqui - (time.perf_counter() - self._t_pagina))
        return resto

    def _texto_tiempo(self) -> str:
        if self._indice >= len(self.pages) - 1:
            return ""                   # ya no queda nada: decirlo seria ruido
        if self._indice == 0:
            total = sum(p.SEGUNDOS for p in self.pages)
            return f"unos {max(1, round(total / 60.0))} minutos"
        if self._resto >= 90.0:
            return f"queda ~{round(self._resto / 60.0)} min"
        segundos = max(5, int(round(self._resto / 5.0)) * 5)
        return f"quedan ~{segundos} s"

    # --------------------------------------------------------------- senales
    def _on_output(self, out: EngineOutput) -> None:
        self._visto_output = True
        if self._expansion is None:
            self.pagina.on_output(out)

    def _on_frame(self, payload) -> None:
        if self._expansion is None and self.pagina.NECESITA_FRAMES:
            self.pagina.on_frame(payload)

    def _on_stats(self, s: dict) -> None:
        valor = float(s.get("latency_ms") or 0.0)
        if valor > 0.0:
            self._retardos += 1
            self._retardo += (valor - self._retardo) / self._retardos
        if self._expansion is None:
            self.pagina.on_stats(s)

    # ---------------------------------------------------------------- latido
    def tick(self, dt: float) -> bool:
        vivo = self._hilo.step(dt)
        if self._destello > 0.0:
            self._destello = max(0.0, self._destello - dt * 1000.0 / 300.0)
            vivo = True
        if self._fase_motor in (1, 2, 3):
            self._paso_motor(dt)
            vivo = True
        elif self._fase_motor == 4:
            self._cerrar_espera(dt)
            vivo = True
        if self._expansion is not None:
            self._expansion.step(dt)
            k = self._expansion.value
            desde, hasta = self.lamina(), self._caja_panel()
            self._caja_lamina = QRectF(
                desde.left() + (hasta.left() - desde.left()) * k,
                desde.top() + (hasta.top() - desde.top()) * k,
                desde.width() + (hasta.width() - desde.width()) * k,
                desde.height() + (hasta.height() - desde.height()) * k)
            self.update()
            if self._expansion.settled:
                self._expansion = None
                self.accept()
            return True
        if self._indice > 0:
            resto = self._estimar()
            # solo baja, salvo que se dispare: si subiera y bajara cada segundo
            # la cifra dejaria de ser informacion y pasaria a ser ruido
            if resto < self._resto or resto > self._resto * 1.25:
                self._resto = resto
                vivo = True
        self.update()
        return True

    # --------------------------------------------------------------- pintado
    def paintEvent(self, event) -> None:                    # noqa: N802
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._pintar_velo(p, t)

        r = self._caja_lamina if not self._caja_lamina.isEmpty() else self.lamina()
        filo = None
        if self._destello > 0.0:
            filo = glass.EDGE_REST + (glass.EDGE_FLASH - glass.EDGE_REST) \
                * self._destello
        camino = glass.paint_sheet(p, r, "E4", R_XL, tokens=t, edge_light=filo)
        if self._barrido.active:
            p.save()
            p.setClipPath(camino)
            self._barrido.paint(p, r, R_XL)
            p.restore()

        if self._expansion is not None:
            self._pintar_marca_de_agua(p, t, r)
            p.end()
            return

        if not self.pagina.SIN_CROMO:
            self._pintar_hilo(p, t, camino, r)
            self._pintar_contador(p, t, r)
            self._pintar_tiempo(p, t, r)
            self._pintar_anillo(p, t)
        p.end()

    def _pintar_velo(self, p: QPainter, t) -> None:
        """El lienzo vivo a 1.6x de brillo con un lavado encima (apartado 9)."""
        self.canvas.paint(p)
        if t.dark:
            p.save()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            p.setOpacity(0.60)
            self.canvas.paint(p)
            p.restore()
        lavado = QColor(0, 0, 0)
        alfa = VELO_ALFA_OSCURO if t.dark else VELO_ALFA_CLARO
        if self._expansion is not None:
            alfa *= 1.0 - self._expansion.value
        lavado.setAlphaF(alfa)
        p.fillRect(self.rect(), lavado)

    def _pintar_hilo(self, p: QPainter, t, camino, r: QRectF) -> None:
        k = max(0.0, min(1.0, self._hilo.value))
        p.save()
        p.setClipPath(camino)
        pista = QColor(t.edge.hair.hex)
        pista.setAlphaF(t.edge.hair.alpha)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), HILO_ALTO), pista)
        if k > 0.0:
            ancho = r.width() * k
            # el glow es un degradado, no un rectangulo: con canto duro el hilo
            # se lee como un taco de color pegado a la esquina en vez de como
            # una luz que corre por el filo
            caja = QRectF(r.left(), r.top(), ancho, HILO_ALTO + HILO_GLOW)
            grad = QLinearGradient(caja.topLeft(), caja.bottomLeft())
            glow = QColor(t.color.accent_glow.hex)
            glow.setAlphaF(t.color.accent_glow.alpha)
            apagado = QColor(glow)
            apagado.setAlpha(0)
            grad.setColorAt(0.0, glow)
            grad.setColorAt(1.0, apagado)
            p.fillRect(caja, grad)
            p.fillRect(QRectF(r.left(), r.top(), ancho, HILO_ALTO),
                       QColor(t.color.accent))
        p.restore()

    def _pintar_contador(self, p: QPainter, t, r: QRectF) -> None:
        piezas.texto(p, QRectF(r.right() - PAD_X - 120.0, r.top() + 24.0,
                               120.0, 16.0), "overline",
                     f"{self._indice + 1} / {len(self.pages)}", t.text.quiet,
                     Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _pintar_tiempo(self, p: QPainter, t, r: QRectF) -> None:
        piezas.texto(p, QRectF(r.left() + PAD_X, r.bottom() - 62.0, 260.0, 16.0),
                     "caption", self._texto_tiempo(), t.text.tertiary)

    def _pintar_anillo(self, p: QPainter, t) -> None:
        """El anillo que se cierra sobre el boton en el auto-avance de P2."""
        if self._anillo <= 0.001 or self.boton is None:
            return
        caja = QRectF(self.boton.geometry()).adjusted(2, 2, -2, -2)
        pluma = QPen(QColor(t.color.accent))
        pluma.setWidthF(2.0)
        pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pluma)
        p.setBrush(Qt.BrushStyle.NoBrush)
        camino = glass.rounded_path(caja, caja.height() / 2.0)
        p.drawPath(piezas.camino_parcial(camino, self._anillo, 80))

    def _pintar_marca_de_agua(self, p: QPainter, t, r: QRectF) -> None:
        """Durante la expansion la lamina se queda vacia y se apaga."""
        if self._expansion is None:
            return
        p.setOpacity(1.0 - motion.ease(self._expansion.value, motion.EASE_SOFT))
        piezas.texto(p, QRectF(r.left(), r.center().y() - 20.0, r.width(), 40.0),
                     "title", "AirTouch", t.text.primary,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        p.setOpacity(1.0)

    # ----------------------------------------------------------------- cierre
    def keyPressEvent(self, event) -> None:                 # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._salir()
            return
        super().keyPressEvent(event)

    def _limpiar(self) -> None:
        """Sueltas las senales del controlador y el lienzo activo.

        Tiene que valer para las dos salidas: ``accept()`` no dispara
        ``closeEvent``, asi que un cierre limpio solo por ``closeEvent`` dejaria
        tres conexiones en cola apuntando a un dialogo muerto justo en el camino
        normal, que es el de terminar el asistente.
        """
        if self._limpio:
            return
        self._limpio = True
        for senal, slot in ((self.ctl.output_ready, self._on_output),
                            (self.ctl.frame_ready, self._on_frame),
                            (self.ctl.stats_ready, self._on_stats)):
            try:
                senal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self.pagina.on_leave()
        self.pagina.rest()
        self.rest()
        if glass.active_canvas() is self.canvas:
            glass.set_active_canvas(self._canvas_previo)

    def done(self, result: int) -> None:
        self._limpiar()
        super().done(result)

    def closeEvent(self, event) -> None:                    # noqa: N802
        self._limpiar()
        super().closeEvent(event)
