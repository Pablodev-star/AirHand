"""Icono de bandeja: siempre accesible aunque el dashboard este cerrado."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import theme


def build_icon(active: bool = False) -> QIcon:
    """Icono dibujado a mano: un circulo con un punto, como el cursor."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # la bandeja sigue al tema de Windows, asi que usamos el color de texto
    color = QColor(theme.C.ok if active else theme.C.text)

    pen = QPen(color)
    pen.setWidthF(4.5)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(10, 10, 44, 44))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QRectF(24, 24, 16, 16))
    p.end()
    return QIcon(pix)


class Tray(QSystemTrayIcon):
    show_dashboard = Signal()
    toggle_engine = Signal()
    toggle_control = Signal()
    toggle_keyboard = Signal()
    quit_app = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(build_icon(False), parent)
        self.setToolTip("AirTouch")

        menu = QMenu()
        self.act_dash = QAction("Abrir panel", menu)
        self.act_dash.triggered.connect(self.show_dashboard.emit)
        menu.addAction(self.act_dash)

        menu.addSeparator()
        self.act_engine = QAction("Iniciar motor", menu)
        self.act_engine.triggered.connect(self.toggle_engine.emit)
        menu.addAction(self.act_engine)

        self.act_control = QAction("Activar control real", menu)
        self.act_control.setCheckable(True)
        self.act_control.triggered.connect(self.toggle_control.emit)
        menu.addAction(self.act_control)

        self.act_kb = QAction("Teclado virtual", menu)
        self.act_kb.triggered.connect(self.toggle_keyboard.emit)
        menu.addAction(self.act_kb)

        menu.addSeparator()
        act_quit = QAction("Salir", menu)
        act_quit.triggered.connect(self.quit_app.emit)
        menu.addAction(act_quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_dashboard.emit()

    def refresh(self, running: bool, control: bool) -> None:
        self.act_engine.setText("Detener motor" if running else "Iniciar motor")
        self.act_control.setChecked(control)
        self.setIcon(build_icon(running and control))
        state = "control activo" if (running and control) else \
                "modo seguro" if running else "detenido"
        self.setToolTip(f"AirTouch · {state}")
