"""Configuracion inicial.

Un teclado funciona sin configurar. Un sistema de gestos no: tu mano, tu
camara, tu luz y tu distancia a la pantalla son distintas a las de cualquier
otro. Esto lo mide una vez y lo deja guardado.

La idea de diseno: una idea por pantalla, tipografia grande, y **ensenar el
gesto antes de pedirlo**. Nadie entiende "calibra tu pinch" leyendolo; todo el
mundo lo entiende viendo dos circulos que se juntan cuando juntas los dedos.
"""
from __future__ import annotations

import statistics
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from ...config import Config
from ...core.controller import Controller
from ...gestures.engine import EngineOutput
from ...gestures.events import EventType
from .. import theme
from ..airlink_panel import AirLinkPanel
from ..anim import fade, tween
from ..calibration import CalibrationWindow
from ..celebrate import Confetti, Pulse, SuccessMark
from ..handart import GestureArt, PinchMeterArt
from ..live_preview import LivePreview
from ..widgets import Card, Dot, Hr, Ring, SettingRow, Toggle, label


# ----------------------------------------------------------------- indicador
class StepDots(QWidget):
    """Puntos de progreso. Menos burocratico que una barra."""

    def __init__(self, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.count = count
        self.index = 0
        self._shown = 0.0
        self.setFixedHeight(20)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        theme.signals.changed.connect(lambda *_a: self.update())

    def set_step(self, i: int) -> None:
        self.index = i
        self._timer.start()
        self.update()

    # compatibilidad con el codigo que trataba esto como una barra
    def setValue(self, i: int) -> None:  # noqa: N802
        self.set_step(i)

    def _tick(self) -> None:
        self._shown += (self.index - self._shown) * 0.22
        self.update()
        if abs(self.index - self._shown) < 0.01:
            self._timer.stop()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        gap = 13.0
        total = (self.count - 1) * gap
        x0 = (self.width() - total) / 2
        cy = self.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(self.count):
            done = i <= self.index
            col = QColor(c.accent if done else c.border_strong)
            near = max(0.0, 1.0 - abs(self._shown - i))
            r = 3.0 + 2.4 * near
            if near > 0.4:
                halo = QColor(c.accent)
                halo.setAlpha(int(90 * near))
                p.setBrush(halo)
                p.drawEllipse(QPointF(x0 + i * gap, cy), r + 4, r + 4)
            p.setBrush(col)
            p.drawEllipse(QPointF(x0 + i * gap, cy), r, r)
        p.end()


# --------------------------------------------------------------------- base
class Page(QWidget):
    ready_changed = Signal()

    #: si es True, la barra de navegacion se oculta en esta pagina
    full_bleed = False

    def __init__(self, title: str = "", subtitle: str = "") -> None:
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        if title:
            self.title_label = label(title, "display", wrap=False)
            self.lay.addWidget(self.title_label)
        if subtitle:
            self.subtitle_label = label(subtitle, "dim")
            self.lay.addWidget(self.subtitle_label)
        if title or subtitle:
            self.lay.addSpacing(10)

    def on_enter(self) -> None:
        pass

    def on_leave(self) -> None:
        pass

    def on_output(self, out: EngineOutput) -> None:
        pass

    def can_advance(self) -> bool:
        return True

    def next_label(self) -> str:
        return "Continuar"


def _stagger(widgets: list[QWidget], step: int = 90, duration: int = 420) -> None:
    """Aparicion escalonada. Es lo que hace que algo parezca cuidado."""
    for i, w in enumerate(widgets):
        effect = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        QTimer.singleShot(i * step, lambda w=w, d=duration: fade(w, 0.0, 1.0, d))


# --------------------------------------------------------------- 0. bienvenida
class IntroPage(Page):
    full_bleed = True

    def __init__(self) -> None:
        super().__init__()
        self.lay.setContentsMargins(0, 10, 0, 0)
        self.lay.addStretch(1)

        self.art = GestureArt("pinch", period=2.8)
        # altura fija: si se deja expandir, se come el resto de la pagina
        self.art.setFixedHeight(240)
        self.lay.addWidget(self.art)
        self.lay.addSpacing(16)

        self.kicker = label("BIENVENIDO", "h3", wrap=False)
        self.kicker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lay.addWidget(self.kicker)

        self.big = label("Tus manos son el ratón", wrap=False)
        self.big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big.setStyleSheet(
            "font-size: 40px; font-weight: 680; letter-spacing: -1px;")
        self.lay.addWidget(self.big)

        self.sub = label(
            "Apunta con el índice. Junta los dedos para hacer clic.\n"
            "En tres minutos lo tienes funcionando.")
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub.setStyleSheet("font-size: 15px;")
        self.sub.setProperty("role", "dim")
        self.lay.addWidget(self.sub)

        self.lay.addSpacing(26)

        row = QHBoxLayout()
        row.addStretch(1)
        holder = QWidget()
        holder.setFixedSize(230, 62)
        self.pulse = Pulse(holder)
        self.pulse.setGeometry(0, 6, 230, 50)
        self.btn = QPushButton("Empezar", holder)
        self.btn.setProperty("role", "primary")
        self.btn.setGeometry(15, 6, 200, 50)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(holder)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.lay.addStretch(2)

    def on_enter(self) -> None:
        _stagger([self.art, self.kicker, self.big, self.sub], step=120)
        self.btn.parentWidget().setGraphicsEffect(None)
        QTimer.singleShot(560, lambda: fade(self.btn.parentWidget(), 0.0, 1.0, 400))


# ------------------------------------------------------------------ 1. camara
class CameraPage(Page):
    """Emparejamiento con el movil por AirLink.

    Antes esta pagina pedia instalar iVCam y elegir una webcam del sistema, y
    al salir dejaba ``source_type = "index"``. Es decir: terminar el asistente
    apagaba AirLink y devolvia la aplicacion a la camara que precisamente
    habiamos dejado de usar, sin decir nada. Ahora empareja de verdad.

    No se deja continuar hasta que llegan fotogramas: las paginas siguientes
    miden tu mano y tu encuadre, y sin imagen no miden nada. Avanzar sin
    camara solo llevaria a tres pantallas que no responden.
    """

    #: fotogramas que hay que recibir antes de dar la conexion por buena. Con
    #: uno o dos basta para que "phone_connected" sea cierto, pero la primera
    #: imagen suele llegar antes de que el movil estabilice la camara.
    _MIN_FRAMES = 15

    def __init__(self, cfg: Config, ctl: Controller) -> None:
        super().__init__("Conecta el iPhone",
                         "Tu móvil hace de cámara. El vídeo va directo a este "
                         "PC por tu WiFi: no pasa por internet.")
        self.cfg = cfg
        self.ctl = ctl
        self._connected = False

        pasos = Card("Cómo se hace")
        for i, texto in enumerate([
            "El móvil y el PC, en la <b>misma red</b>. Las redes de invitados "
            "no valen: aíslan los dispositivos entre sí.",
            "Abre la <b>cámara del iPhone</b>, apúntala al código y toca el "
            "aviso que sale.",
            "Safari dirá que la conexión no es privada. Es lo esperado: el "
            "certificado lo firma tu propio PC y no sale de casa. Pulsa "
            "<b>Mostrar detalles</b> y luego <b>Visitar este sitio web</b>.",
            "Dale permiso a la cámara y elige <b>1080p</b>.",
        ], 1):
            fila = QHBoxLayout()
            fila.setSpacing(12)
            n = label(str(i), "mono", wrap=False)
            n.setFixedWidth(16)
            fila.addWidget(n)
            fila.addWidget(label(texto), 1)
            pasos.add_layout(fila)
        self.lay.addWidget(pasos)

        # El mismo panel que el escritorio: QR, codigo, estado y el aviso del
        # cortafuegos. Se refresca solo, asi que aqui no hay nada que mantener.
        # la nota al pie del panel repite los pasos de arriba: alli sobra
        self.panel = AirLinkPanel(ctl, show_help=False)
        self.lay.addWidget(self.panel)
        self.lay.addStretch(1)

        self._vigila = QTimer(self)
        self._vigila.setInterval(400)
        self._vigila.timeout.connect(self._comprobar)

    def on_enter(self) -> None:
        if not self.ctl.airlink.running:
            self.ctl.airlink.start()
        self._vigila.start()
        self._comprobar()

    def on_leave(self) -> None:
        self._vigila.stop()
        # Lo esencial: la camara queda en AirLink. Nunca en "index".
        self.cfg.camera.source_type = "airlink"
        self.cfg.camera.friendly_name = "AirLink"
        self.cfg.save()

    def _comprobar(self) -> None:
        link = self.ctl.airlink
        ok = bool(link.phone_connected
                  and link.frames_received > self._MIN_FRAMES)
        if ok != self._connected:
            self._connected = ok
            self.ready_changed.emit()

    def can_advance(self) -> bool:
        return self._connected

    def next_label(self) -> str:
        return "Continuar" if self._connected else "Esperando al móvil…"


# ---------------------------------------------------------------- 2. encuadre
class FramingPage(Page):
    def __init__(self, cfg: Config, ctl: Controller) -> None:
        super().__init__("Coloca la cámara",
                         "El móvil encima del monitor, en horizontal, mirándote a ti.")
        self.cfg = cfg
        self.ctl = ctl
        self.preview = LivePreview()
        self.preview.setMinimumHeight(250)
        self.lay.addWidget(self.preview, 1)

        checks = Card()
        checks.body.setSpacing(4)
        self.c_signal = self._check(checks, "Hay señal de cámara")
        self.c_hand = self._check(checks, "Se ve tu mano")
        self.c_face = self._check(checks, "Se te ve la cara")
        self.c_light = self._check(checks, "Luz suficiente")
        self.lay.addWidget(checks)

        self.lay.addWidget(label(
            "Levanta una mano a la altura del pecho, a medio metro de la cámara. "
            "Con señal y mano detectada ya puedes seguir.", "faint"))
        self._state = {"signal": False, "face": False, "hand": False, "light": False}

    def _check(self, card: Card, text: str):
        row = QHBoxLayout()
        row.setSpacing(11)
        dot = Dot("border_strong", 10)
        lb = label(text, "dim", wrap=False)
        row.addWidget(dot)
        row.addWidget(lb, 1)
        card.add_layout(row)
        return dot, lb

    def on_enter(self) -> None:
        self.ctl.preview_enabled = True
        self.ctl.frame_ready.connect(self._on_frame, Qt.ConnectionType.QueuedConnection)

    def on_leave(self) -> None:
        try:
            self.ctl.frame_ready.disconnect(self._on_frame)
        except (RuntimeError, TypeError):
            pass
        self.ctl.preview_enabled = False

    def _on_frame(self, payload) -> None:
        frame, state = payload
        self.preview.set_frame(frame, state)
        mean = float(frame.mean())
        self._set("signal", True)
        self._set("face", state.face.present)
        self._set("hand", len(state.hands) > 0)
        self._set("light", 45 < mean < 215)
        if mean <= 45:
            self.c_light[1].setText("Poca luz: la imagen está muy oscura")
        elif mean >= 215:
            self.c_light[1].setText("Contraluz: la imagen está quemada")
        else:
            self.c_light[1].setText("Luz suficiente")

    def _set(self, key: str, ok: bool) -> None:
        dots = {"signal": self.c_signal, "face": self.c_face,
                "hand": self.c_hand, "light": self.c_light}
        if self._state.get(key) != ok:
            self._state[key] = ok
            dots[key][0].set_token("ok" if ok else "border_strong")
            self.ready_changed.emit()

    def can_advance(self) -> bool:
        return self._state["signal"] and self._state["hand"]


# -------------------------------------------------------------- 3. el gesto
class LearnPinchPage(Page):
    """Ensena el pinch ANTES de medirlo.

    Sin esto, "calibra tu pinch" no significa nada. Aqui haces el gesto tres
    veces y ves que funciona; despues medir es evidente.
    """

    GOAL = 3

    def __init__(self, cfg: Config) -> None:
        super().__init__("Este es el gesto",
                         "Junta el pulgar y el índice, como si cogieras algo pequeño.")
        self.cfg = cfg
        self.count = 0
        self._was_closed = False
        self._lo: float | None = None      # rango de pinch observado
        self._hi: float | None = None

        row = QHBoxLayout()
        row.setSpacing(20)

        art_card = Card(compact=True)
        self.art = GestureArt("click", period=2.4)
        self.art.setMinimumHeight(210)
        art_card.add(self.art)
        art_card.add(label("Así se hace", "faint"))
        row.addWidget(art_card, 1)

        live = Card(compact=True)
        self.meter = PinchMeterArt()
        self.meter.setMinimumHeight(210)
        live.add(self.meter)
        live.add(label("Tu mano ahora", "faint"))
        row.addWidget(live, 1)
        self.lay.addLayout(row, 1)

        prog = Card()
        head = QHBoxLayout()
        head.setSpacing(14)
        self.ring = Ring(58, "ok")
        head.addWidget(self.ring)
        box = QVBoxLayout()
        box.setSpacing(2)
        self.headline = label("Hazlo 3 veces", "h2", wrap=False)
        self.hint = label("Ponte de frente a la cámara y junta los dedos.", "dim")
        box.addWidget(self.headline)
        box.addWidget(self.hint)
        head.addLayout(box, 1)
        prog.add_layout(head)
        self.lay.addWidget(prog)
        self.ring.set_progress(0.0, "0/3")

    def on_output(self, out: EngineOutput) -> None:
        if not out.hands:
            self.meter.label = "No se ve ninguna mano"
            self.meter.set_gap(1.0, False)
            return

        # Aqui todavia NO hay calibracion, asi que usar los umbrales guardados
        # no vale: si no coinciden con tu mano, el medidor se queda en verde
        # permanente y nunca cuenta una repeticion. Se aprende el rango sobre
        # la marcha con el minimo y el maximo que se van viendo.
        r = out.pinch_ratio
        self._lo = r if self._lo is None else min(self._lo, r)
        self._hi = r if self._hi is None else max(self._hi, r)
        span = (self._hi - self._lo) if self._hi is not None else 0.0

        if span < 0.14:                      # aun no te ha visto abrir y cerrar
            self.meter.label = "Abre y cierra los dedos"
            self.meter.set_gap(0.55, False)
            self._was_closed = False
            return

        norm = (r - self._lo) / span
        closed = norm < (0.30 if not self._was_closed else 0.48)   # histeresis
        self.meter.set_gap(max(0.04, min(norm, 1.0)), closed)
        self.meter.label = ""

        if closed and not self._was_closed and self.count < self.GOAL:
            self.count += 1
            left = self.GOAL - self.count
            self.ring.set_progress(self.count / self.GOAL,
                                   f"{self.count}/{self.GOAL}")
            if left == 0:
                self.headline.setText("¡Perfecto!")
                self.hint.setText("Ya dominas el gesto más importante. Sigamos.")
            else:
                self.headline.setText(
                    f"¡Bien! Falta {left}" if left == 1 else f"¡Bien! Faltan {left}")
                self.hint.setText("Abre la mano y vuelve a juntar los dedos.")
            self.ready_changed.emit()
        self._was_closed = closed

    def can_advance(self) -> bool:
        return True

    def next_label(self) -> str:
        return "Continuar" if self.count >= self.GOAL else "Saltar por ahora"


# ----------------------------------------------------------- 4. medir el pinch
class PinchPage(Page):
    _OPEN_S = 2.4
    _CLOSED_S = 2.4

    def __init__(self, cfg: Config) -> None:
        super().__init__("Ahora medimos tu mano",
                         "Cada mano es distinta. Dos poses y queda ajustado a la tuya.")
        self.cfg = cfg
        self.phase = "idle"     # idle|ready_open|open|ready_closed|closed|done
        self._seen_lo: float | None = None
        self._seen_hi: float | None = None
        self._samples: list[float] = []
        self._open_v = 0.0
        self._closed_v = 0.0
        self._t0 = 0.0

        card = Card()
        head = QHBoxLayout()
        head.setSpacing(18)
        self.ring = Ring(72)
        head.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(4)
        self.instruction = label("Pulsa «Medir» para empezar", "h2", wrap=False)
        self.hint = label(
            "Te pediré dos cosas: primero la mano abierta, después los dedos juntos.",
            "dim")
        box.addWidget(self.instruction)
        box.addWidget(self.hint)
        head.addLayout(box, 1)
        card.add_layout(head)
        card.add(Hr())

        self.meter = PinchMeterArt()
        self.meter.setMinimumHeight(160)
        card.add(self.meter)

        row = QHBoxLayout()
        self.btn = QPushButton("Medir")
        self.btn.setProperty("role", "primary")
        self.btn.setMinimumWidth(150)
        self.btn.clicked.connect(self.start)
        row.addWidget(self.btn)
        row.addStretch(1)
        self.readout = label("", "mono", wrap=False)
        row.addWidget(self.readout)
        card.add_layout(row)
        self.lay.addWidget(card)

        self.result = Card("Resultado")
        self.result_text = label("Sin medir todavía.", "dim")
        self.result.add(self.result_text)
        self.lay.addWidget(self.result)
        self.lay.addStretch(1)

    _READY_S = 2.0          # tiempo para colocar la mano antes de medir

    def start(self) -> None:
        self.phase = "ready_open"
        self._samples.clear()
        self._t0 = time.perf_counter()
        self.btn.setEnabled(False)
        self.instruction.setText("1 · Abre la mano")
        self.hint.setText("Separa el pulgar del índice todo lo que puedas, "
                          "de frente a la cámara. Empiezo a medir en…")

    def on_output(self, out: EngineOutput) -> None:
        if out.hands:
            # rango observado durante esta pantalla, no umbrales guardados
            r = out.pinch_ratio
            self._seen_lo = r if self._seen_lo is None else min(self._seen_lo, r)
            self._seen_hi = r if self._seen_hi is None else max(self._seen_hi, r)
            span = max((self._seen_hi - self._seen_lo), 0.18)
            norm = (r - self._seen_lo) / span
            self.meter.set_gap(max(0.04, min(norm, 1.0)), norm < 0.34)
            self.meter.label = ""
        else:
            self.meter.label = "No se ve ninguna mano"

        if self.phase in ("idle", "done") or out.hands == 0:
            return
        now = time.perf_counter()
        self.readout.setText(f"{out.pinch_ratio:.3f}")

        # fases de preparacion: cuenta atras sin medir nada todavia
        if self.phase in ("ready_open", "ready_closed"):
            left = self._READY_S - (now - self._t0)
            self.ring.set_progress(1.0 - max(left, 0.0) / self._READY_S,
                                   str(max(1, int(left) + 1)))
            if left <= 0:
                self.phase = "open" if self.phase == "ready_open" else "closed"
                self._samples.clear()
                self._t0 = now
                self.hint.setText("Ahora no te muevas.")
            return

        self._samples.append(out.pinch_ratio)

        if self.phase == "open":
            frac = (now - self._t0) / self._OPEN_S
            self.ring.set_progress(min(frac, 1.0), f"{max(0, int((1-frac)*self._OPEN_S)+1)}")
            if frac >= 1.0:
                self._open_v = statistics.median(self._samples[-40:] or [1.0])
                self._samples.clear()
                self.phase = "ready_closed"
                self._t0 = now
                self.instruction.setText("2 · Junta los dedos")
                self.hint.setText("Pellizca como si cogieras un grano de arroz. "
                                  "Empiezo a medir en…")
        elif self.phase == "closed":
            frac = (now - self._t0) / self._CLOSED_S
            self.ring.set_progress(min(frac, 1.0),
                                   f"{max(0, int((1-frac)*self._CLOSED_S)+1)}")
            if frac >= 1.0:
                self._closed_v = statistics.median(self._samples[-40:] or [0.2])
                self._finish()

    def _finish(self) -> None:
        self.phase = "done"
        self.btn.setEnabled(True)
        self.btn.setText("Repetir")
        self.ring.set_progress(1.0, "✓")
        span = self._open_v - self._closed_v

        if span < 0.22:
            self.result_text.setText(
                f"<b>Medición poco fiable</b> (abierto {self._open_v:.2f}, cerrado "
                f"{self._closed_v:.2f}). Suele pasar si la mano estaba de perfil o "
                "muy lejos. Ponte de frente y repite.")
            self.instruction.setText("Vamos a repetirlo")
            self.hint.setText("De frente a la cámara y con la mano bien visible.")
            return

        g = self.cfg.gestures
        # el umbral de apertura va MUY pegado al de cierre: si se separa mucho,
        # sigues "clicando" con los dedos ya abiertos
        g.pinch_on = round(self._closed_v + span * 0.32, 3)
        g.pinch_off = round(self._closed_v + span * 0.44, 3)
        self.cfg.save()
        self.result_text.setText(
            f"Abierto <b>{self._open_v:.2f}</b> · cerrado <b>{self._closed_v:.2f}</b>. "
            f"Umbrales ajustados a <b>{g.pinch_on:.2f}</b> / <b>{g.pinch_off:.2f}</b>. "
            "Podrás afinarlos luego en Ajustes.")
        self.instruction.setText("Ajustado a tu mano")
        self.hint.setText("El clic debería ir mucho más fino a partir de ahora.")

    def next_label(self) -> str:
        return "Continuar" if self.phase == "done" else "Saltar"


# ------------------------------------------------------------- 5. calibracion
class CornersPage(Page):
    def __init__(self, cfg: Config, ctl: Controller) -> None:
        super().__init__("Apunta con precisión",
                         "Cuatro esquinas para que el puntero caiga donde miras.")
        self.cfg = cfg
        self.ctl = ctl
        self._done = bool(cfg.mapping.homography)
        self._window: CalibrationWindow | None = None

        card = Card()
        self.art = GestureArt("point", period=3.0)
        self.art.setFixedHeight(190)
        card.add(self.art)
        card.add(Hr())
        card.add(label(
            "Saldrá una pantalla oscura con un círculo en cada esquina. Apunta con "
            "el índice y <b>mantén el pinch</b> hasta que el anillo se complete. "
            "Cuatro veces."))

        row = QHBoxLayout()
        self.btn = QPushButton("Calibrar ahora")
        self.btn.setProperty("role", "primary")
        self.btn.setMinimumWidth(170)
        self.btn.clicked.connect(self.start)
        row.addWidget(self.btn)
        self.state = label("", "faint")
        row.addWidget(self.state, 1)
        card.add_layout(row)
        self.lay.addWidget(card)
        self.lay.addStretch(1)
        self._refresh()

    def _refresh(self) -> None:
        if self._done:
            self.state.setText("Calibrado. Puedes repetirlo si quieres.")
            self.btn.setText("Repetir calibración")
        else:
            self.state.setText("Puedes saltártelo, pero apuntar será menos preciso.")

    def start(self) -> None:
        win = CalibrationWindow(self.cfg)
        self._window = win
        self.ctl.output_ready.connect(win.on_output, Qt.ConnectionType.QueuedConnection)

        def _finish(ok: bool) -> None:
            try:
                self.ctl.output_ready.disconnect(win.on_output)
            except (RuntimeError, TypeError):
                pass
            self.ctl.mapper.refresh_calibration()
            self._done = self._done or ok
            self._window = None
            self._refresh()
            self.ready_changed.emit()

        win.finished.connect(_finish)
        win.begin()

    def next_label(self) -> str:
        return "Continuar" if self._done else "Saltar por ahora"


# ---------------------------------------------------------------- 6. practicar
class TrainingPage(Page):
    _GOALS = {"click": 3, "scroll": 2, "right": 2}
    _INFO = {
        "click": ("Clic", "Pinch corto: junta y suelta", "click"),
        "scroll": ("Scroll", "Mantén el pinch y mueve la mano", "scroll"),
        "right": ("Clic derecho", "Curva el índice contra el pulgar y suéltalo", "flick"),
    }

    def __init__(self) -> None:
        super().__init__("Pruébalos",
                         "Estás en modo seguro: nada de esto toca tu escritorio.")
        self.counts = {k: 0 for k in self._GOALS}
        self.focus = "click"

        row = QHBoxLayout()
        row.setSpacing(20)

        art_card = Card(compact=True)
        self.art = GestureArt("click", period=2.4)
        self.art.setMinimumHeight(220)
        art_card.add(self.art)
        self.art_caption = label("Clic", "faint")
        art_card.add(self.art_caption)
        row.addWidget(art_card, 1)

        list_card = Card(compact=True)
        self.rows: dict[str, tuple[Ring, QLabel, QLabel]] = {}
        for key, (name, desc, _g) in self._INFO.items():
            r = QHBoxLayout()
            r.setSpacing(13)
            ring = Ring(46, "ok")
            ring.set_progress(0.0, f"0/{self._GOALS[key]}")
            r.addWidget(ring)
            box = QVBoxLayout()
            box.setSpacing(1)
            title = label(name, wrap=False)
            sub = label(desc, "faint", wrap=False)
            box.addWidget(title)
            box.addWidget(sub)
            r.addLayout(box, 1)
            list_card.add_layout(r)
            self.rows[key] = (ring, title, sub)
        row.addWidget(list_card, 1)
        self.lay.addLayout(row, 1)

        self.lay.addWidget(label(
            "Si alguno no te sale, sigue adelante: los umbrales se pueden afinar "
            "después en Ajustes. La catapulta es la más difícil.", "faint"))

    def on_output(self, out: EngineOutput) -> None:
        for ev in out.events:
            if ev.type in (EventType.CLICK, EventType.DOUBLE_CLICK):
                self._bump("click")
            elif ev.type is EventType.RIGHT_CLICK:
                self._bump("right")
            elif ev.type is EventType.SCROLL:
                self._bump("scroll")

    def _bump(self, key: str) -> None:
        goal = self._GOALS[key]
        if self.counts[key] >= goal:
            return
        self.counts[key] += 1
        ring, _title, _sub = self.rows[key]
        ring.set_progress(self.counts[key] / goal, f"{self.counts[key]}/{goal}")
        if self.counts[key] >= goal:
            self._advance_focus()
        self.ready_changed.emit()

    def _advance_focus(self) -> None:
        for key in self._GOALS:
            if self.counts[key] < self._GOALS[key]:
                self.focus = key
                self.art.set_gesture(self._INFO[key][2])
                self.art_caption.setText(self._INFO[key][0])
                return
        self.art_caption.setText("Todos conseguidos")

    def next_label(self) -> str:
        if all(self.counts[k] >= v for k, v in self._GOALS.items()):
            return "Continuar"
        return "Continuar de todas formas"


# ------------------------------------------------------------------ 7. listo
class FinishPage(Page):
    # OJO: aqui la barra de navegacion es obligatoria; es donde esta el boton
    # que cierra el asistente. Sin ella te quedas encerrado en esta pagina.
    full_bleed = False

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self._played = False
        self.lay.setContentsMargins(0, 6, 0, 0)
        self.lay.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.mark = SuccessMark(112)
        row.addWidget(self.mark)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.lay.addSpacing(18)

        self.big = label("¡Ya está!", wrap=False)
        self.big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.big.setStyleSheet(
            "font-size: 42px; font-weight: 680; letter-spacing: -1px;")
        self.lay.addWidget(self.big)

        self.sub = label("AirTouch está ajustado a tu mano y a tu cámara.", "dim")
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub.setStyleSheet("font-size: 15px;")
        self.lay.addWidget(self.sub)
        self.lay.addSpacing(24)

        card = Card()
        self.t_control = Toggle(False)
        card.add(SettingRow(
            "Activar el control real ahora",
            "Tus gestos moverán el ratón de verdad. Puedes cambiarlo cuando quieras.",
            self.t_control))
        card.add(Hr())
        self.t_autostart = Toggle(cfg.app.start_with_windows)
        card.add(SettingRow("Arrancar con Windows", "", self.t_autostart))
        self.t_minimized = Toggle(cfg.app.start_minimized)
        card.add(SettingRow("Empezar en la bandeja", "", self.t_minimized))
        self.lay.addWidget(card)

        warn = Card()
        warn.add(label("PARA RECUPERAR EL CONTROL", "h3", wrap=False))
        for text in [
            "Mantén <b>Esc</b> un segundo.",
            "Mueve el ratón físico: AirTouch se aparta solo.",
            "Abre la palma y mantenla un momento.",
        ]:
            r = QHBoxLayout()
            r.setSpacing(11)
            r.addWidget(Dot("warn", 8))
            r.addWidget(label(text), 1)
            warn.add_layout(r)
        self.lay.addWidget(warn)
        self.lay.addStretch(1)

    def on_enter(self) -> None:
        if self._played:
            return
        self._played = True
        self.mark.play()
        _stagger([self.big, self.sub], step=150)
        parent = self.window()
        confetti = getattr(parent, "confetti", None)
        if confetti is not None:
            QTimer.singleShot(280, lambda: confetti.burst(110))

    def on_leave(self) -> None:
        self.cfg.app.start_with_windows = self.t_autostart.isChecked()
        self.cfg.app.start_minimized = self.t_minimized.isChecked()
        self.cfg.save()

    def commit(self) -> None:
        """Solo al TERMINAR: si no, volver atras daria la configuracion por hecha."""
        self.on_leave()
        self.cfg.app.first_run = False
        self.cfg.save()

    def next_label(self) -> str:
        return "Empezar a usarlo"


# --------------------------------------------------------------------- dialogo
class SetupWizard(QDialog):
    completed = Signal(bool)          # True si quiere el control activado

    def __init__(self, cfg: Config, ctl: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.ctl = ctl
        self.setWindowTitle("Configuración de AirTouch")
        self.setModal(True)
        self.resize(880, 800)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(46, 26, 46, 22)
        lay.setSpacing(16)

        self.progress = StepDots(8)
        lay.addWidget(self.progress)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        self.pages: list[Page] = [
            IntroPage(),
            CameraPage(cfg, ctl),
            FramingPage(cfg, ctl),
            LearnPinchPage(cfg),
            PinchPage(cfg),
            CornersPage(cfg, ctl),
            TrainingPage(),
            FinishPage(cfg),
        ]
        for p in self.pages:
            self.stack.addWidget(p)
            p.ready_changed.connect(self._refresh_buttons)

        self.nav = QWidget()
        nav = QHBoxLayout(self.nav)
        nav.setContentsMargins(0, 0, 0, 0)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setProperty("role", "ghost")
        self.btn_cancel.clicked.connect(self.reject)
        nav.addWidget(self.btn_cancel)
        nav.addStretch(1)
        self.btn_back = QPushButton("Atrás")
        self.btn_back.clicked.connect(self._back)
        nav.addWidget(self.btn_back)
        self.btn_next = QPushButton("Continuar")
        self.btn_next.setProperty("role", "primary")
        self.btn_next.setMinimumWidth(150)
        self.btn_next.clicked.connect(self._next)
        nav.addWidget(self.btn_next)
        lay.addWidget(self.nav)

        # capa de confeti por encima de todo
        self.confetti = Confetti(self)
        self.confetti.setGeometry(self.rect())
        self.confetti.hide()

        self.pages[0].btn.clicked.connect(self._next)
        self.ctl.output_ready.connect(self._on_output, Qt.ConnectionType.QueuedConnection)
        self._goto(0)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        self.confetti.setGeometry(self.rect())
        super().resizeEvent(ev)

    # ---------------- navegacion ----------------
    def _goto(self, index: int) -> None:
        current = self.stack.currentWidget()
        if isinstance(current, Page):
            current.on_leave()
        self.stack.setCurrentIndex(index)
        page = self.pages[index]
        page.on_enter()
        self.progress.set_step(index)
        self.nav.setVisible(not page.full_bleed)
        self._refresh_buttons()
        fade(page, 0.0, 1.0, 260)

        # el motor hace falta a partir del encuadre
        if index >= 2 and not self.ctl.running:
            self.ctl.start()

    def _next(self) -> None:
        i = self.stack.currentIndex()
        if i >= len(self.pages) - 1:
            self.pages[i].commit()                       # type: ignore[attr-defined]
            want = self.pages[-1].t_control.isChecked()  # type: ignore[attr-defined]
            self.completed.emit(want)
            self.accept()
            return
        self._goto(i + 1)

    def _back(self) -> None:
        i = self.stack.currentIndex()
        if i > 0:
            self._goto(i - 1)

    def _refresh_buttons(self) -> None:
        i = self.stack.currentIndex()
        page = self.pages[i]
        self.btn_back.setEnabled(i > 0)
        self.btn_next.setText(page.next_label())
        self.btn_next.setEnabled(page.can_advance())

    def _on_output(self, out: EngineOutput) -> None:
        page = self.stack.currentWidget()
        if isinstance(page, Page):
            page.on_output(out)

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.ctl.output_ready.disconnect(self._on_output)
        except (RuntimeError, TypeError):
            pass
        current = self.stack.currentWidget()
        if isinstance(current, Page):
            current.on_leave()
        super().closeEvent(event)
