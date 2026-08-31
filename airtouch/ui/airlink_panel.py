"""Panel de emparejamiento: el QR que conecta el movil con este PC."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ..core.controller import Controller
from ..net import firewall
from . import theme
from .widgets import Badge, Banner, Card, Dot, Hr, label


class AirLinkPanel(Card):
    """QR, código y estado de la conexión con el móvil."""

    def __init__(self, ctl: Controller, parent: QWidget | None = None) -> None:
        super().__init__("Conectar teléfono",
                         "Escanea el código con la cámara del iPhone",
                         parent)
        self.ctl = ctl
        self._last_url = ""
        self._last_warn = ""

        row = QHBoxLayout()
        row.setSpacing(20)

        # --- QR ---
        self.qr = QWidget()
        self.qr.setFixedSize(196, 196)
        self.qr_label = label("", wrap=False)
        self.qr_label.setFixedSize(196, 196)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setStyleSheet("background: #ffffff; border-radius: 14px;")
        row.addWidget(self.qr_label, 0, Qt.AlignmentFlag.AlignTop)

        # --- datos ---
        box = QVBoxLayout()
        box.setSpacing(8)

        state_row = QHBoxLayout()
        state_row.setSpacing(9)
        self.dot = Dot("text_faint", 11)
        state_row.addWidget(self.dot)
        self.state = label("Servidor detenido", "dim", wrap=False)
        state_row.addWidget(self.state, 1)
        self.badge = Badge("", "text_dim")
        state_row.addWidget(self.badge)
        box.addLayout(state_row)

        box.addWidget(Hr())

        box.addWidget(label("CÓDIGO DE EMPAREJAMIENTO", "h3", wrap=False))
        self.token = label("——————", wrap=False)
        self.token.setStyleSheet(
            "font-family: 'Cascadia Mono', Consolas, monospace;"
            "font-size: 30px; font-weight: 700; letter-spacing: 5px;")
        box.addWidget(self.token)

        box.addWidget(label("DIRECCIÓN", "h3", wrap=False))
        self.url = label("—", "mono", wrap=False)
        box.addWidget(self.url)

        buttons = QHBoxLayout()
        buttons.setSpacing(9)
        self.btn_new = QPushButton("Nuevo código")
        self.btn_new.clicked.connect(self._new_token)
        buttons.addWidget(self.btn_new)
        self.btn_copy = QPushButton("Copiar enlace")
        self.btn_copy.setProperty("role", "ghost")
        self.btn_copy.clicked.connect(self._copy)
        buttons.addWidget(self.btn_copy)
        buttons.addStretch(1)
        box.addLayout(buttons)
        box.addStretch(1)

        row.addLayout(box, 1)
        self.add_layout(row)

        # --- cortafuegos: la causa numero uno de "no se encuentra el servidor"
        self.fw_banner = Banner()
        self.add(self.fw_banner)
        fw_row = QHBoxLayout()
        fw_row.setSpacing(9)
        self.btn_fw = QPushButton("Permitir en el cortafuegos")
        self.btn_fw.setProperty("role", "primary")
        self.btn_fw.clicked.connect(self._allow_firewall)
        fw_row.addWidget(self.btn_fw)
        self.fw_state = label("", "faint")
        fw_row.addWidget(self.fw_state, 1)
        self.add_layout(fw_row)

        self.add(label(
            "El móvil y el PC tienen que estar en la misma red. La primera vez "
            "Safari avisará de que el certificado no es de confianza: es normal, lo "
            "genera tu propio PC. Toca «Mostrar detalles → Visitar este sitio web».",
            "faint"))
        self._check_firewall()

        self._timer = QTimer(self)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        theme.signals.changed.connect(lambda *_a: self._draw_qr(force=True))
        self.refresh()

    # ---------------- estado ----------------
    def refresh(self) -> None:
        link = self.ctl.airlink
        self.token.setText(link.token)
        self.url.setText(f"https://{link.ip}:{link.cfg.port}")
        self._draw_qr()

        if link.error:
            self.dot.set_token("danger")
            self.badge.set("error", "danger")
        elif not link.running:
            self.dot.set_token("text_faint")
            self.badge.set("detenido", "text_dim")
        elif link.phone_connected:
            self.dot.set_token("ok")
            w, h = link.size
            self.badge.set(f"{w}×{h}" if w else "conectado", "ok")
        else:
            self.dot.set_token("warn")
            self.badge.set("esperando", "warn")
        self.dot.set_pulsing(link.running and not link.phone_connected)
        self.state.setText(link.status_text())

        # si el vídeo llega, el aviso de calidad manda sobre el del cortafuegos
        warn = link.quality_warning
        if warn:
            self.fw_banner.set(warn, "warn", "!")
            self.btn_fw.setVisible(False)
            self.fw_state.setText("")
        elif link.phone_connected and self._last_warn:
            self._check_firewall()
        self._last_warn = warn

    def _draw_qr(self, force: bool = False) -> None:
        url = self.ctl.airlink.pair_url
        if url == self._last_url and not force:
            return
        self._last_url = url
        try:
            data = self.ctl.airlink.qr_png(scale=6)
        except Exception:
            self.qr_label.setText("QR no disponible")
            return
        pix = QPixmap()
        if pix.loadFromData(data, "PNG"):
            self.qr_label.setPixmap(pix.scaled(
                180, 180, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation))

    # ---------------- acciones ----------------
    def _check_firewall(self) -> None:
        """Avisa antes de que el usuario se pelee con un «no se encuentra»."""
        exists = firewall.rule_exists(self.ctl.airlink.cfg.port)
        public = firewall.network_is_public()

        if exists is True:
            self.fw_banner.set(
                "El cortafuegos ya permite las conexiones del móvil.", "ok", "✓")
            self.btn_fw.setVisible(False)
            self.fw_state.setText("")
            return

        self.btn_fw.setVisible(True)
        if public:
            self.fw_banner.set(
                "Tu red está clasificada como pública, así que Windows bloquea "
                "todo lo que entra. El móvil no podrá encontrar este PC hasta "
                "que le des permiso.", "danger", "!")
        else:
            self.fw_banner.set(
                "Falta darle permiso al cortafuegos para que el móvil pueda "
                "conectarse a este PC.", "warn", "!")
        self.fw_state.setText("Windows pedirá confirmación de administrador.")

    def _allow_firewall(self) -> None:
        self.btn_fw.setEnabled(False)
        self.btn_fw.setText("Confirma en la ventana de Windows…")
        ok = firewall.add_rule(self.ctl.airlink.cfg.port)
        self.btn_fw.setEnabled(True)
        self.btn_fw.setText("Permitir en el cortafuegos")
        if ok:
            # netsh corre elevado y tarda un instante en aplicarse
            QTimer.singleShot(1200, self._check_firewall)
        else:
            self.fw_state.setText("No se pudo crear la regla (¿cancelaste el aviso?).")

    def _new_token(self) -> None:
        self.ctl.airlink.new_token()
        self.refresh()

    def _copy(self) -> None:
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(self.ctl.airlink.pair_url)
            self.btn_copy.setText("¡Copiado!")
            QTimer.singleShot(1400, lambda: self.btn_copy.setText("Copiar enlace"))
