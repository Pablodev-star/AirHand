"""Ventana principal: el panel de control de AirTouch.

Estructura: identidad y navegacion a la izquierda, cabecera contextual arriba
y contenido en una pila con transiciones. Los datos en vivo se ven de un
vistazo (metricas grandes con historial) en vez de como una lista de numeros.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from ..config import Config
from ..core.controller import Controller
from ..gestures.engine import EngineOutput
from ..gestures.events import EventType, Mode
from ..net.updates import UpdateChecker
from ..version import __version__
from . import theme
from .airlink_panel import AirLinkPanel
from .anim import AnimatedStack, fade
from .compact import CompactPanel
from .live_preview import LivePreview
from .settings.panel import SettingsPanel
from .widgets import (
    Badge, Banner, Card, Dot, GestureIndicator, Hr, NavItem, NavRail,
    PinchGauge, SegmentedControl, SettingRow, StatRow, StatTile, Toggle, label,
)

_NAV = [
    NavItem("resumen", "Resumen", "◎"),
    NavItem("camara", "Cámara", "▣"),
    NavItem("gestos", "Gestos", "✥"),
    NavItem("ajustes", "Ajustes", "⚙"),
    NavItem("registro", "Registro", "≡"),
]

_PAGE_TITLES = {
    "resumen": ("Resumen", "Estado del sistema y control principal"),
    "camara": ("Cámara", "Lo que ve AirTouch en tiempo real"),
    "gestos": ("Gestos", "Practica y comprueba la detección"),
    "ajustes": ("Ajustes", "Afina el comportamiento a tu gusto"),
    "registro": ("Registro", "Eventos y diagnóstico"),
}

_GESTURES = [
    ("pointer", "Puntero", "Dedo índice extendido"),
    ("click", "Clic", "Pinch corto: pulgar + índice"),
    ("scroll", "Scroll", "Mantén el pinch y mueve arriba o abajo"),
    ("right", "Clic derecho", "Catapulta: curva el índice y suéltalo de golpe"),
    ("zoom", "Zoom", "Pinch con las dos manos y sepáralas"),
    ("window", "Mover ventana", "Pinch en la barra bajo la ventana"),
    ("resize", "Redimensionar", "Pinch en la esquina inferior derecha"),
    ("keyboard", "Teclado", "Pinch sobre las teclas"),
]

_THEME_MODES = ["system", "light", "dark"]


class Dashboard(QMainWindow):
    def __init__(self, cfg: Config, controller: Controller) -> None:
        super().__init__()
        self.cfg = cfg
        self.ctl = controller
        self.setWindowTitle("AirTouch")
        self.resize(1180, 800)
        self.setMinimumSize(980, 660)

        self._cool_at = 0.0
        self._last_stats = 0.0
        self._low_res = False
        self._auto_compact = False
        self.updates = UpdateChecker()

        # dos vistas: el panel completo y el compacto que sale con el motor en
        # marcha. Se alternan sin destruir nada.
        self.views = QStackedWidget()
        self.setCentralWidget(self.views)

        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())
        outer.addWidget(self._build_content(), 1)
        self.views.addWidget(root)

        self.compact = CompactPanel()
        self.views.addWidget(self.compact)
        self._compact_active = False
        self._normal_geometry = None
        self.compact.pause_requested.connect(self._compact_pause)
        self.compact.resume_requested.connect(self._compact_resume)
        self.compact.finish_requested.connect(self._compact_finish)
        self.compact.expand_requested.connect(self.exit_compact)

        self._wire()
        self._sync_theme_control()

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(400)
        self._ui_timer.timeout.connect(self._cool_indicators)
        self._ui_timer.start()

        # se comprueba al abrir, con un respiro para no competir con el arranque
        QTimer.singleShot(2500, self._check_updates)

    # ------------------------------------------------------------ estructura
    def _build_sidebar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedWidth(232)
        bar.setObjectName("sidebar")

        def _restyle(*_a) -> None:
            # el selector por id evita que los hijos hereden el borde
            try:
                bar.setStyleSheet(
                    f"QWidget#sidebar {{ background: {theme.C.surface_sunken};"
                    f" border-right: 1px solid {theme.C.border}; }}")
            except RuntimeError:
                pass

        def _unsubscribe(*_a) -> None:
            theme.unsubscribe(_restyle)

        _restyle()
        theme.signals.changed.connect(_restyle)
        bar.destroyed.connect(_unsubscribe)

        lay = QVBoxLayout(bar)
        lay.setContentsMargins(12, 20, 12, 16)
        lay.setSpacing(14)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.setContentsMargins(10, 0, 0, 0)
        self.brand_dot = Dot("text_faint", 12)
        brand.addWidget(self.brand_dot)
        name_box = QVBoxLayout()
        name_box.setSpacing(0)
        name = label("AirTouch", wrap=False)
        name.setStyleSheet("font-size: 17px; font-weight: 650;")
        name_box.addWidget(name)
        self.brand_state = label("Detenido", "faint", wrap=False)
        name_box.addWidget(self.brand_state)
        brand.addLayout(name_box, 1)
        lay.addLayout(brand)

        lay.addSpacing(4)
        self.nav = NavRail(_NAV)
        self.nav.setFixedHeight(len(_NAV) * NavRail.ROW_H + 12)
        lay.addWidget(self.nav)
        lay.addStretch(1)

        lay.addWidget(label("APARIENCIA", "h3", wrap=False))
        self.theme_control = SegmentedControl(["Auto", "Claro", "Oscuro"], 0)
        self.theme_control.changed.connect(self._on_theme_changed)
        lay.addWidget(self.theme_control)

        lay.addSpacing(6)
        lay.addWidget(label("Esc mantenido = pausa", "faint", wrap=False))
        lay.addWidget(label(f"v{__version__}", "faint", wrap=False))
        return bar

    def _build_content(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(26, 20, 26, 20)
        lay.setSpacing(16)

        lay.addLayout(self._build_header())

        self.stack = AnimatedStack()
        lay.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_overview())
        self.stack.addWidget(self._build_camera())
        self.stack.addWidget(self._build_gestures())
        self.settings = SettingsPanel(self.cfg)
        self.stack.addWidget(self.settings)
        self.stack.addWidget(self._build_log())
        return wrap

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        box = QVBoxLayout()
        box.setSpacing(2)
        self.page_title = label("Resumen", "h1", wrap=False)
        self.page_sub = label(_PAGE_TITLES["resumen"][1], "dim", wrap=False)
        box.addWidget(self.page_title)
        box.addWidget(self.page_sub)
        row.addLayout(box)
        row.addStretch(1)

        self.status_badge = Badge("detenido", "text_dim")
        row.addWidget(self.status_badge)

        self.btn_engine = QPushButton("Iniciar motor")
        self.btn_engine.setProperty("role", "primary")
        self.btn_engine.setMinimumWidth(140)
        self.btn_engine.clicked.connect(self._toggle_engine)
        row.addWidget(self.btn_engine)
        return row

    @staticmethod
    def _scroll(inner: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(inner)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return area

    # -------------------------------------------------------------- resumen
    def _build_overview(self) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 10, 10)
        lay.setSpacing(16)

        self.banner = Banner()
        lay.addWidget(self.banner)

        # --- metricas ---
        metrics = Card("Rendimiento en vivo",
                       "Latencia total desde que la cámara capta hasta que se "
                       "interpreta el gesto")
        grid = QGridLayout()
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(6)
        self.tile_cam = StatTile("FPS de cámara", "fps", spark=True, token="info")
        self.tile_engine = StatTile("FPS del motor", "fps", spark=True, token="accent")
        self.tile_latency = StatTile("Latencia", "ms", spark=True, token="warn")
        self.tile_detect = StatTile("Detección", "ms", spark=True, token="ok")
        for i, tile in enumerate((self.tile_cam, self.tile_engine,
                                  self.tile_latency, self.tile_detect)):
            grid.addWidget(tile, 0, i)
            grid.setColumnStretch(i, 1)
        metrics.add_layout(grid)
        lay.addWidget(metrics)

        # --- control + estado ---
        cols = QHBoxLayout()
        cols.setSpacing(16)

        control = Card("Control del sistema")
        self.control_toggle = Toggle(self.cfg.safety.control_enabled)
        self.control_toggle.toggled.connect(self._on_control_toggle)
        control.add(SettingRow(
            "Inyectar clics y movimiento reales",
            "Con esto apagado nada toca tu escritorio",
            self.control_toggle))
        control.add(Hr())
        self.control_hint = label("", "dim")
        control.add(self.control_hint)
        control.body.addStretch(1)
        cols.addWidget(control, 3)

        live = Card("Ahora mismo")
        self.st_mode = StatRow("Modo", "—")
        self.st_hands = StatRow("Manos", "0")
        self.st_face = StatRow("Usuario delante", "no")
        self.st_res = StatRow("Resolución", "—")
        self.st_camera = StatRow("Cámara", "—")
        for w in (self.st_mode, self.st_hands, self.st_face, self.st_res,
                  self.st_camera):
            live.add(w)
        live.body.addStretch(1)
        cols.addWidget(live, 2)
        lay.addLayout(cols)

        # --- acciones ---
        # --- actualizaciones ---
        self.update_card = Card("Actualizaciones")
        self.update_state = label("Comprobando…", "dim")
        self.update_card.add(self.update_state)
        row_up = QHBoxLayout()
        row_up.setSpacing(10)
        self.btn_update = QPushButton("Descargar la nueva versión")
        self.btn_update.setProperty("role", "primary")
        self.btn_update.clicked.connect(self._open_update)
        self.btn_update.setVisible(False)
        row_up.addWidget(self.btn_update)
        self.btn_check = QPushButton("Comprobar ahora")
        self.btn_check.setProperty("role", "ghost")
        self.btn_check.clicked.connect(self._check_updates)
        row_up.addWidget(self.btn_check)
        row_up.addStretch(1)
        self.update_card.add_layout(row_up)
        lay.addWidget(self.update_card)

        quick = Card("Acciones rápidas")
        row = QHBoxLayout()
        row.setSpacing(10)
        for text, slot in [
            ("Teclado virtual", self.ctl.toggle_keyboard),
            ("Calibrar esquinas", lambda: self.open_calibration()),
            ("Configuración guiada", lambda: self.open_wizard()),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        quick.add_layout(row)
        lay.addWidget(quick)

        lay.addStretch(1)
        return self._scroll(host)

    # --------------------------------------------------------------- camara
    def _build_camera(self) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 10, 10)
        lay.setSpacing(14)

        self.airlink_panel = AirLinkPanel(self.ctl)
        lay.addWidget(self.airlink_panel)

        card = Card(compact=True)
        card.body.setContentsMargins(12, 12, 12, 12)
        self.preview = LivePreview()
        self.preview.setMinimumHeight(300)
        card.add(self.preview)
        lay.addWidget(card, 1)

        controls = Card(compact=True)
        row = QHBoxLayout()
        row.setSpacing(14)

        self.cam_dot = Dot("text_faint", 10)
        row.addWidget(self.cam_dot)
        self.cam_status = label("Cámara no iniciada", "dim", wrap=False)
        row.addWidget(self.cam_status)
        row.addStretch(1)

        self.t_skel = Toggle(True)
        self.t_skel.toggled.connect(self._on_skeleton)
        row.addWidget(label("Esqueleto", "dim", wrap=False))
        row.addWidget(self.t_skel)

        self.t_region = Toggle(True)
        self.t_region.toggled.connect(self._on_region)
        row.addWidget(label("Región activa", "dim", wrap=False))
        row.addWidget(self.t_region)

        btn = QPushButton("Reconectar")
        btn.clicked.connect(self.ctl.restart_camera)
        row.addWidget(btn)
        controls.add_layout(row)
        controls.add(label(
            "Si el esqueleto sigue bien a tus dedos, la detección funciona. Si "
            "parpadea o salta: más luz, o acerca las manos a la cámara.", "faint"))
        lay.addWidget(controls)
        return self._scroll(host)

    # --------------------------------------------------------------- gestos
    def _build_gestures(self) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 10, 10)
        lay.setSpacing(16)

        gauge_card = Card(
            "Distancia de pinch",
            "La aguja eres tú. Verde = cerrado, naranja = zona de histéresis")
        self.gauge = PinchGauge()
        gauge_card.add(self.gauge)
        gauge_card.add(label(
            "Ajusta los umbrales en Ajustes hasta que la aguja cruce a verde justo "
            "cuando tus dedos se tocan.", "faint"))
        lay.addWidget(gauge_card)

        card = Card("Gestos reconocidos",
                    "Cada fila se ilumina al detectarse. El contador delata los "
                    "gestos que se disparan solos")
        btn = QPushButton("Reiniciar")
        btn.setProperty("role", "ghost")
        btn.clicked.connect(self._reset_counters)
        card.add_action(btn)
        card.add(Hr())

        self.indicators: dict[str, GestureIndicator] = {}
        for key, name, desc in _GESTURES:
            ind = GestureIndicator(name, desc)
            self.indicators[key] = ind
            card.add(ind)
        lay.addWidget(card)
        lay.addStretch(1)
        return self._scroll(host)

    # ------------------------------------------------------------- registro
    def _build_log(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setPlaceholderText("Todavía no hay eventos.")
        lay.addWidget(self.log, 1)

        row = QHBoxLayout()
        clear = QPushButton("Limpiar")
        clear.clicked.connect(self.log.clear)
        row.addWidget(clear)
        row.addStretch(1)
        row.addWidget(label(
            "El archivo completo está en logs\\airtouch.log", "faint", wrap=False))
        lay.addLayout(row)
        return page

    # ------------------------------------------------------------ conexiones
    def _wire(self) -> None:
        q = Qt.ConnectionType.QueuedConnection
        self.ctl.output_ready.connect(self._on_output, q)
        self.ctl.frame_ready.connect(self._on_frame, q)
        self.ctl.stats_ready.connect(self._on_stats, q)
        self.ctl.status_changed.connect(self._on_status, q)
        self.ctl.log_line.connect(self._append_log, q)
        self.ctl.error.connect(self._on_error, q)

        self.nav.selected.connect(self._on_nav)
        self.settings.changed.connect(self._on_settings_changed)
        self.settings.camera_changed.connect(self._on_camera_changed)
        self.settings.calibrate_requested.connect(lambda: self.open_calibration())
        self.settings.reset_requested.connect(self._reset_settings)
        self.settings.theme_changed.connect(self._apply_theme_from_config)

        self._refresh_control_hint()
        self._refresh_banner()

    # ----------------------------------------------------------------- tema
    def _sync_theme_control(self) -> None:
        try:
            idx = _THEME_MODES.index(self.cfg.ui.theme)
        except ValueError:
            idx = 0
        self.theme_control.set_index(idx)

    def _on_theme_changed(self, index: int) -> None:
        self.cfg.ui.theme = _THEME_MODES[index]
        self._apply_theme_from_config()
        self.cfg.save()

    def _apply_theme_from_config(self) -> None:
        from PySide6.QtWidgets import QApplication

        theme.apply(self.cfg.ui.theme)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.qss())
        self._sync_theme_control()
        for w in (self.log,):
            w.update()

    # ------------------------------------------------------------- slots UI
    def _on_nav(self, index: int) -> None:
        key = _NAV[index].key
        title, sub = _PAGE_TITLES[key]
        self.page_title.setText(title)
        self.page_sub.setText(sub)
        fade(self.page_title, 0.35, 1.0, 200)
        fade(self.page_sub, 0.2, 1.0, 240)
        self.stack.go_to(index)
        self.ctl.preview_enabled = (key == "camara")
        if key != "camara":
            self.preview.clear()

    def _on_skeleton(self, v: bool) -> None:
        self.preview.show_skeleton = v
        self.preview.update()

    def _on_region(self, v: bool) -> None:
        self.preview.show_region = v
        self.preview.update()

    def _on_frame(self, payload) -> None:
        frame, state = payload
        m = self.cfg.mapping
        self.preview.region = (m.region_x0, m.region_y0, m.region_x1, m.region_y1)
        self.preview.pinch_on = self.cfg.gestures.pinch_on
        self.preview.set_frame(frame, state)

    def _on_output(self, out: EngineOutput) -> None:
        g0 = self.cfg.gestures
        if self._compact_active:
            self.compact.on_output(out, g0.pinch_on, g0.pinch_off)
            return                      # el panel completo esta oculto: no gastar
        self.st_mode.set(out.mode.value)
        self.st_hands.set(str(out.hands))
        g = self.cfg.gestures
        self.gauge.set_thresholds(g.pinch_on, g.pinch_off)
        self.gauge.set_value(out.pinch_ratio, out.pinching)

        ind = self.indicators
        ind["pointer"].set_active(out.pointer is not None)
        ind["scroll"].set_active(out.mode is Mode.SCROLLING)
        ind["zoom"].set_active(out.mode is Mode.ZOOMING)
        ind["window"].set_active(out.mode is Mode.WINDOW_MOVE)
        ind["resize"].set_active(out.mode is Mode.WINDOW_RESIZE)
        ind["keyboard"].set_active(out.mode is Mode.KEYBOARD)

        for ev in out.events:
            if ev.type in (EventType.CLICK, EventType.DOUBLE_CLICK):
                ind["click"].flash()
            elif ev.type is EventType.RIGHT_CLICK:
                ind["right"].flash()
            elif ev.type is EventType.SCROLL:
                ind["scroll"].flash()
            elif ev.type is EventType.ZOOM:
                ind["zoom"].flash()
            elif ev.type in (EventType.KEY_TEXT, EventType.KEY_VK):
                ind["keyboard"].flash()
            elif ev.type is EventType.WINDOW_BOUNDS:
                ind["window" if out.mode is Mode.WINDOW_MOVE else "resize"].flash()
        if out.events:
            self._cool_at = time.perf_counter() + 0.5

    def _on_stats(self, s: dict) -> None:
        if self._compact_active:
            self.compact.on_stats(s)
            return
        # el móvil acaba de conectar: ahora sí tiene sentido encogerse
        if self._auto_compact and s.get("connected") and self.ctl.running:
            self._auto_compact = False
            self.enter_compact()
            return
        self.tile_cam.set(f"{s['camera_fps']:.0f}")
        self.tile_cam.push(s["camera_fps"])
        self.tile_engine.set(f"{s['pipeline_fps']:.0f}")
        self.tile_engine.push(s["pipeline_fps"])

        lat = s["latency_ms"]
        self.tile_latency.set(
            f"{lat:.0f}",
            "ok" if lat < 90 else "warn" if lat < 180 else "danger")
        self.tile_latency.push(lat)

        self.tile_detect.set(f"{s['process_ms']:.1f}")
        self.tile_detect.push(s["process_ms"])

        self.st_res.set(s["resolution"], "warn" if s.get("low_res") else None)
        if s.get("low_res", False) != self._low_res:
            self._low_res = s.get("low_res", False)
            self._refresh_banner()
        self.st_face.set("sí" if s["face"] else "no",
                         "ok" if s["face"] else "text_dim")
        connected = s["connected"]
        self.st_camera.set("conectada" if connected else "sin señal",
                           "ok" if connected else "danger")
        self.cam_dot.set_token("ok" if connected else "danger")
        self.cam_status.setText(
            f"Conectada · {s['resolution']} · {s['camera_fps']:.0f} FPS"
            if connected else "Sin señal de cámara")

    def _on_status(self, text: str) -> None:
        running = self.ctl.running
        control = self.cfg.safety.control_enabled
        paused = "pausa" in text.lower()

        if not running:
            token, short = "text_dim", "detenido"
        elif paused:
            token, short = "danger", "en pausa"
        elif control:
            token, short = "ok", "control activo"
        else:
            token, short = "warn", "modo seguro"

        if self._compact_active:
            self._refresh_compact()

        self.status_badge.set(short, token)
        self.brand_dot.set_token(token)
        self.brand_dot.set_pulsing(running and control and not paused)
        self.brand_state.setText(text if running else "Detenido")
        self._refresh_banner(text)

    def _refresh_banner(self, status: str = "") -> None:
        if self._low_res and self.ctl.running:
            self.banner.set(
                "La cámara está enviando poca resolución. Sube la calidad en la "
                "app de iVCam del móvil (720p o más): por debajo de eso los "
                "dedos se detectan con mucho ruido y el puntero tiembla.",
                "warn", "!")
            return
        if not self.ctl.running:
            self.banner.set(
                "El motor está parado. Pulsa «Iniciar motor» para empezar a "
                "detectar tus manos.", "info", "i")
        elif not self.cfg.safety.control_enabled:
            self.banner.set(
                "Modo seguro: ves el puntero y los gestos, pero nada toca tu "
                "escritorio. Actívalo abajo cuando quieras control real.",
                "warn", "!")
        elif "pausa" in status.lower():
            self.banner.set(
                f"Control en pausa · {status}. Mantén Esc para reanudar.",
                "danger", "!")
        else:
            self.banner.set(
                "Control activo. Mantén Esc un segundo, mueve el ratón físico o "
                "abre la palma para recuperar el control.", "ok", "✓")

    def _append_log(self, line: str) -> None:
        self.log.appendPlainText(line)

    def _on_error(self, message: str) -> None:
        self._append_log("ERROR: " + message)
        QMessageBox.critical(self, "AirTouch", message)

    # -------------------------------------------------------------- acciones
    def _toggle_engine(self) -> None:
        if self.ctl.running:
            self.ctl.stop()
            self.btn_engine.setText("Iniciar motor")
            self.preview.clear()
            self.exit_compact()
        else:
            if self.ctl.start():
                self.btn_engine.setText("Detener motor")
                if self.ctl.source_connected:
                    self._on_nav(self.nav.index())
                    self.enter_compact()
                else:
                    # Sin vídeo todavía: encogerse ahora dejaría al usuario
                    # atrapado sin poder llegar al QR. Se va a Cámara y se
                    # encoge solo cuando el móvil conecte.
                    self._auto_compact = True
                    self.nav.set_index(1)
        self._on_status(self.ctl.safety.status_text())

    def _on_control_toggle(self, enabled: bool) -> None:
        if enabled:
            answer = QMessageBox.question(
                self, "Activar control real",
                "A partir de ahora tus gestos moverán el ratón y harán clics de "
                "verdad.\n\nPara recuperar el control al instante: mantén Esc un "
                "segundo, mueve el ratón físico, o abre la palma de la mano.\n\n"
                "¿Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if answer != QMessageBox.StandardButton.Yes:
                self.control_toggle.setChecked(False)
                return
        self.ctl.set_control_enabled(enabled)
        self._refresh_control_hint()
        self._on_status(self.ctl.safety.status_text())

    def _refresh_control_hint(self) -> None:
        if self.cfg.safety.control_enabled:
            self.control_hint.setText(
                "<b>Control activo.</b> Los gestos actúan sobre el sistema.")
        else:
            self.control_hint.setText(
                "<b>Modo seguro.</b> Verás el puntero y los gestos en pantalla, "
                "pero no se inyecta nada. Ideal para practicar y calibrar.")

    def _on_settings_changed(self) -> None:
        self.ctl.retune()
        self.cfg.save()

    def _on_camera_changed(self) -> None:
        self.ctl.restart_camera()
        self.cfg.save()

    def _reset_settings(self) -> None:
        answer = QMessageBox.question(
            self, "Restablecer", "¿Volver a los valores por defecto?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        keep_theme = self.cfg.ui.theme
        for section in ("vision", "filter", "mapping", "gestures", "safety", "ui"):
            self.cfg.reset_section(section)
        self.cfg.ui.theme = keep_theme
        self.settings.refresh_from_config()
        self.ctl.retune()
        self.cfg.save()
        self._append_log("Ajustes restablecidos")

    def _reset_counters(self) -> None:
        for ind in self.indicators.values():
            ind.reset()

    def _cool_indicators(self) -> None:
        if self._cool_at and time.perf_counter() > self._cool_at:
            self._cool_at = 0.0
            for ind in self.indicators.values():
                ind.cool()

    # ------------------------------------------------------ actualizaciones
    def _check_updates(self) -> None:
        self.update_state.setText("Comprobando…")
        self.btn_check.setEnabled(False)
        # la respuesta llega desde otro hilo: se vuelve al de la interfaz con
        # un temporizador de cero, que es la forma segura en Qt
        self.updates.check_async(
            lambda _c: QTimer.singleShot(0, self._show_update_result))

    def _show_update_result(self) -> None:
        self.btn_check.setEnabled(True)
        self.update_state.setText(self.updates.summary())
        self.btn_update.setVisible(self.updates.available)
        if self.updates.available and self.updates.latest:
            rel = self.updates.latest
            extra = f" · {rel.size_mb:.0f} MB" if rel.size_mb else ""
            self.btn_update.setText(f"Descargar {rel.version}{extra}")
            self._append_log(f"Actualización disponible: {rel.version}")

    def _open_update(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        rel = self.updates.latest
        if rel is None:
            return
        QDesktopServices.openUrl(QUrl(rel.download or rel.url))

    # ------------------------------------------------------- modo compacto
    def enter_compact(self) -> None:
        """Se encoge a la esquina inferior derecha con lo imprescindible."""
        if self._compact_active:
            return
        from PySide6.QtGui import QGuiApplication

        self._compact_active = True
        self._normal_geometry = self.geometry()
        self._normal_min = self.minimumSize()

        self.setMinimumSize(300, 300)
        self.views.setCurrentIndex(1)
        self._refresh_compact()

        w, h = 372, 380
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            a = screen.availableGeometry()
            self.setGeometry(a.right() - w - 24, a.bottom() - h - 24, w, h)
        else:
            self.resize(w, h)

        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.show()
        self.raise_()
        self._append_log("Panel compacto")

    def exit_compact(self) -> None:
        if not self._compact_active:
            return
        self._compact_active = False
        self.views.setCurrentIndex(0)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.setMinimumSize(self._normal_min)
        if self._normal_geometry is not None:
            self.setGeometry(self._normal_geometry)
        self.show()
        self.raise_()
        self._append_log("Panel completo")

    def _refresh_compact(self) -> None:
        self.compact.set_state(
            running=self.ctl.running,
            control=self.cfg.safety.control_enabled,
            paused=self.ctl.safety.state.paused)

    def _compact_pause(self) -> None:
        self.ctl.set_control_enabled(False)
        self.control_toggle.setChecked(False)
        self._refresh_control_hint()
        self._refresh_compact()
        self._on_status(self.ctl.safety.status_text())

    def _compact_resume(self) -> None:
        self.ctl.safety.resume()
        self.ctl.set_control_enabled(True)
        self.control_toggle.setChecked(True)
        self._refresh_control_hint()
        self._refresh_compact()
        self._on_status(self.ctl.safety.status_text())

    def _compact_finish(self) -> None:
        self.ctl.set_control_enabled(False)
        self.control_toggle.setChecked(False)
        self.ctl.stop()
        self.btn_engine.setText("Iniciar motor")
        self.preview.clear()
        self.exit_compact()
        self._refresh_control_hint()
        self._on_status(self.ctl.safety.status_text())

    # sobrescritos por app.py
    def open_calibration(self) -> None:
        pass

    def open_wizard(self) -> None:
        pass

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.cfg.save()
        event.accept()
