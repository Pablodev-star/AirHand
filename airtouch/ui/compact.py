"""Panel compacto: lo que se ve mientras estas usando el control gestual.

Cuando el motor arranca no quieres un panel de 1200 px tapandote la pantalla:
quieres saber si te esta viendo, a que va, y poder pausar. Eso y nada mas.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ..gestures.engine import EngineOutput
from . import theme
from .widgets import Badge, Dot, PinchGauge, label


class _Metric(QWidget):
    """Numero grande con etiqueta pequena debajo."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.value = label("—", wrap=False)
        self.value.setStyleSheet("font-size: 19px; font-weight: 620;")
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap = label(caption.upper(), "h3", wrap=False)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.value)
        lay.addWidget(cap)

    def set(self, text: str, token: str | None = None) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(
            "font-size: 19px; font-weight: 620;"
            + (f"color: {getattr(theme.C, token)};" if token else ""))


class CompactPanel(QWidget):
    """Vista reducida con lo esencial y los controles de pausa."""

    pause_requested = Signal()
    resume_requested = Signal()
    finish_requested = Signal()
    expand_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        # --- cabecera ---
        head = QHBoxLayout()
        head.setSpacing(9)
        self.dot = Dot("text_faint", 11)
        head.addWidget(self.dot)
        name = label("AirTouch", wrap=False)
        name.setStyleSheet("font-size: 15px; font-weight: 650;")
        head.addWidget(name)
        head.addStretch(1)
        self.badge = Badge("detenido", "text_dim")
        head.addWidget(self.badge)
        # Salida al panel completo SIN parar el motor. Sin esto, la única forma
        # de volver era «Terminar», que apagaba todo — incluido AirLink.
        self.btn_expand = QPushButton("⤢")
        self.btn_expand.setProperty("role", "ghost")
        self.btn_expand.setFixedSize(34, 30)
        self.btn_expand.setToolTip("Volver al panel completo")
        self.btn_expand.clicked.connect(self.expand_requested.emit)
        head.addWidget(self.btn_expand)
        lay.addLayout(head)

        # --- modo actual ---
        self.mode = label("—", wrap=False)
        self.mode.setStyleSheet("font-size: 25px; font-weight: 640;")
        lay.addWidget(self.mode)

        # --- medidor de pinch ---
        self.gauge = PinchGauge()
        lay.addWidget(self.gauge)

        # --- metricas ---
        row = QHBoxLayout()
        row.setSpacing(6)
        self.m_fps = _Metric("fps")
        self.m_lat = _Metric("latencia")
        self.m_hands = _Metric("manos")
        for m in (self.m_fps, self.m_lat, self.m_hands):
            row.addWidget(m, 1)
        lay.addLayout(row)

        lay.addStretch(1)

        # --- botones ---
        self.btn_pause = QPushButton("Pausar")
        self.btn_pause.setProperty("role", "primary")
        self.btn_pause.setMinimumHeight(40)
        self.btn_pause.clicked.connect(self.pause_requested.emit)
        lay.addWidget(self.btn_pause)

        self.paused_row = QWidget()
        prow = QHBoxLayout(self.paused_row)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.setSpacing(9)
        self.btn_resume = QPushButton("Reanudar")
        self.btn_resume.setProperty("role", "primary")
        self.btn_resume.setMinimumHeight(40)
        self.btn_resume.clicked.connect(self.resume_requested.emit)
        prow.addWidget(self.btn_resume, 1)
        self.btn_finish = QPushButton("Terminar")
        self.btn_finish.setMinimumHeight(40)
        self.btn_finish.clicked.connect(self.finish_requested.emit)
        prow.addWidget(self.btn_finish, 1)
        lay.addWidget(self.paused_row)

        self.hint = label("Mantén Esc un segundo para pausar", "faint", wrap=False)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.hint)

        self.set_state(running=False, control=False, paused=False)

    # ---------------- entrada de datos ----------------
    def set_state(self, running: bool, control: bool, paused: bool) -> None:
        active = running and control and not paused
        self.btn_pause.setVisible(active)
        self.paused_row.setVisible(not active)

        if not running:
            self.badge.set("detenido", "text_dim")
            self.dot.set_token("text_faint")
        elif active:
            self.badge.set("control activo", "ok")
            self.dot.set_token("ok")
        else:
            self.badge.set("modo seguro", "warn")
            self.dot.set_token("warn")
        self.dot.set_pulsing(active)
        self.hint.setText(
            "Mantén Esc un segundo para pausar" if active
            else "En modo seguro no se toca tu escritorio")

    def on_output(self, out: EngineOutput, pinch_on: float, pinch_off: float) -> None:
        self.mode.setText(out.mode.value.capitalize())
        self.m_hands.set(str(out.hands), "ok" if out.hands else "text_dim")
        self.gauge.set_thresholds(pinch_on, pinch_off)
        self.gauge.set_value(out.pinch_ratio, out.pinching)

    def on_stats(self, s: dict) -> None:
        self.m_fps.set(f"{s['pipeline_fps']:.0f}")
        lat = s["latency_ms"]
        self.m_lat.set(
            f"{lat:.0f}",
            "ok" if lat < 90 else "warn" if lat < 180 else "danger")
