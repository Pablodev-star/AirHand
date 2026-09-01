"""Panel de ajustes.

Todo se aplica en caliente: cada cambio escribe en el objeto Config y avisa al
controlador para que lo recoja sin reiniciar el motor.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from ...config import Config
from ..widgets import (
    Card, Hr, LabeledSlider, SegmentedControl, SettingRow, Toggle, label,
)

_THEME_MODES = ["system", "light", "dark"]
_MIRROR_MODES = ["auto", "off", "on"]


class SettingsPanel(QWidget):
    changed = Signal()                 # ajustes aplicables en caliente
    camera_changed = Signal()          # requiere reabrir la camara
    theme_changed = Signal()
    calibrate_requested = Signal()
    reset_requested = Signal()

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        host = QWidget()
        self.lay = QVBoxLayout(host)
        self.lay.setContentsMargins(0, 0, 12, 20)
        self.lay.setSpacing(16)
        scroll.setWidget(host)

        self._build_appearance()
        self._build_camera()
        self._build_pointer()
        self._build_gestures()
        self._build_keyboard()
        self._build_safety()
        self._build_reset()
        self.lay.addStretch(1)

    # ---------------------------------------------------------- apariencia
    def _build_appearance(self) -> None:
        c = Card("Apariencia", "El tema automático sigue al de Windows")
        u = self.cfg.ui

        self.theme_seg = SegmentedControl(["Auto", "Claro", "Oscuro"], 0)
        try:
            self.theme_seg.set_index(_THEME_MODES.index(u.theme))
        except ValueError:
            pass
        self.theme_seg.changed.connect(self._on_theme)
        c.add(SettingRow("Tema", "Claro, oscuro o el del sistema", self.theme_seg))
        c.add(Hr())

        self.t_overlay = Toggle(u.overlay_enabled)
        self.t_cursor = Toggle(u.show_cursor)
        self.t_hud = Toggle(u.show_hud)
        for t in (self.t_overlay, self.t_cursor, self.t_hud):
            t.toggled.connect(self._on_ui)
        c.add(SettingRow("Overlay sobre el escritorio",
                         "Barras de ventana, cursor y teclado", self.t_overlay))
        c.add(SettingRow("Cursor propio",
                         "El punto luminoso que sigue a tu índice", self.t_cursor))
        c.add(SettingRow("HUD de estado",
                         "La pastilla que indica el modo actual", self.t_hud))
        self.lay.addWidget(c)

    # ------------------------------------------------------------- camara
    def _build_camera(self) -> None:
        c = Card("Cámara")
        cfg = self.cfg.camera
        form = QFormLayout()
        form.setSpacing(10)

        self.source = QComboBox()
        self.source.addItems(["AirLink · iPhone por WiFi (recomendado)",
                              "Cámara del sistema (webcam o app virtual)",
                              "Stream por URL"])
        self.source.setCurrentIndex(
            {"airlink": 0, "index": 1, "url": 2}.get(cfg.source_type, 0))
        self.source.currentIndexChanged.connect(self._on_source)
        form.addRow("Fuente", self.source)

        self.cam_index = QSpinBox()
        self.cam_index.setRange(0, 10)
        self.cam_index.setValue(cfg.index)
        self.cam_index.valueChanged.connect(self._on_camera)
        form.addRow("Índice", self.cam_index)

        self.res = QComboBox()
        self.res.addItems(["1280 x 720", "960 x 540", "1920 x 1080", "640 x 360"])
        self.res.setCurrentText(f"{cfg.width} x {cfg.height}")
        self.res.currentTextChanged.connect(self._on_camera)
        form.addRow("Resolución", self.res)
        c.add_layout(form)

        self.mirror = SegmentedControl(["Auto", "No invertido", "Invertido"], 0)
        try:
            self.mirror.set_index(_MIRROR_MODES.index(cfg.mirror_mode))
        except ValueError:
            pass
        self.mirror.changed.connect(self._on_mirror)
        c.add(SettingRow(
            "Modo espejo",
            "En Auto se adapta a la cámara del móvil: la frontal se invierte "
            "(vista de espejo) y la trasera no. Cámbialo si notas que el "
            "puntero va al revés que tu mano.", self.mirror))
        self.lay.addWidget(c)

    # ------------------------------------------------------------ puntero
    def _build_pointer(self) -> None:
        c = Card("Puntero")
        m = self.cfg.mapping
        f = self.cfg.filter

        form = QFormLayout()
        form.setSpacing(10)
        self.mode = QComboBox()
        self.mode.addItems(["Absoluto (apuntar)", "Relativo (como un ratón)"])
        self.mode.setCurrentIndex(0 if m.mode == "absolute" else 1)
        self.mode.currentIndexChanged.connect(self._on_pointer)
        form.addRow("Modo", self.mode)

        self.monitor = QComboBox()
        self.monitor.addItems(["Solo monitor principal", "Todos los monitores"])
        self.monitor.setCurrentIndex(0 if m.monitor == "primary" else 1)
        self.monitor.currentIndexChanged.connect(self._on_pointer)
        form.addRow("Alcance", self.monitor)
        c.add_layout(form)

        self.smooth = LabeledSlider(
            "Suavizado", 0.3, 4.0, f.min_cutoff, 2,
            hint="Menos valor = más estable pero con más retardo")
        self.smooth.valueChanged.connect(self._on_pointer)
        c.add(self.smooth)

        self.react = LabeledSlider(
            "Reactividad", 0.0, 0.08, f.beta, 3,
            hint="Cuánto deja de suavizar cuando mueves la mano rápido")
        self.react.valueChanged.connect(self._on_pointer)
        c.add(self.react)

        self.gain = LabeledSlider(
            "Ganancia", 0.8, 5.0, m.relative_gain, 2,
            hint="Solo en modo relativo")
        self.gain.valueChanged.connect(self._on_pointer)
        c.add(self.gain)

        self.predict = LabeledSlider(
            "Compensar latencia", 0.0, 40.0, f.prediction_ms, 0, " ms",
            hint="Adelanta el puntero hacia donde vas. Quita sensación de "
                 "retardo, pero a cambio tiembla algo más. 0 = desactivado")
        self.predict.valueChanged.connect(self._on_pointer)
        c.add(self.predict)

        c.add(Hr())
        row = QHBoxLayout()
        row.setSpacing(10)
        btn = QPushButton("Recalibrar las 4 esquinas")
        btn.clicked.connect(self.calibrate_requested.emit)
        row.addWidget(btn)
        self.clear_cal = QPushButton("Borrar calibración")
        self.clear_cal.setProperty("role", "ghost")
        self.clear_cal.clicked.connect(self._clear_calibration)
        row.addWidget(self.clear_cal)
        row.addStretch(1)
        c.add_layout(row)
        self.cal_state = label("", "faint")
        c.add(self.cal_state)
        self._refresh_cal_state()
        self.lay.addWidget(c)

    # ------------------------------------------------------------- gestos
    def _build_gestures(self) -> None:
        c = Card("Gestos",
                 "Mira la aguja en la pestaña Gestos mientras ajustas los umbrales")
        g = self.cfg.gestures

        self.pinch_on = LabeledSlider(
            "Umbral de cierre", 0.15, 0.60, g.pinch_on, 2,
            hint="Por debajo de este valor, el pinch cuenta como cerrado")
        self.pinch_on.valueChanged.connect(self._on_gestures)
        c.add(self.pinch_on)

        self.pinch_off = LabeledSlider(
            "Umbral de apertura", 0.20, 0.80, g.pinch_off, 2,
            hint="Por encima se abre. La separación entre ambos evita parpadeos")
        self.pinch_off.valueChanged.connect(self._on_gestures)
        c.add(self.pinch_off)

        form = QFormLayout()
        form.setSpacing(10)
        self.drag_mode = QComboBox()
        self.drag_mode.addItems(["Scroll", "Arrastrar / seleccionar"])
        self.drag_mode.setCurrentIndex(0 if g.pinch_drag_mode == "scroll" else 1)
        self.drag_mode.currentIndexChanged.connect(self._on_gestures)
        form.addRow("Pinch + mover", self.drag_mode)
        c.add_layout(form)

        self.scroll_gain = LabeledSlider("Velocidad de scroll", 0.4, 5.0,
                                         g.scroll_gain, 2)
        self.scroll_gain.valueChanged.connect(self._on_gestures)
        c.add(self.scroll_gain)

        self.zoom_gain = LabeledSlider("Velocidad de zoom", 0.3, 3.0, g.zoom_gain, 2)
        self.zoom_gain.valueChanged.connect(self._on_gestures)
        c.add(self.zoom_gain)

        self.flick_speed = LabeledSlider(
            "Velocidad mínima de la catapulta", 1.0, 6.0, g.flick_min_speed, 2,
            hint="Si se dispara sola, sube este valor. Si no sale nunca, bájalo")
        self.flick_speed.valueChanged.connect(self._on_gestures)
        c.add(self.flick_speed)

        c.add(Hr())
        self.t_zoom = Toggle(g.zoom_enabled)
        self.t_flick = Toggle(g.flick_enabled)
        self.t_chrome = Toggle(g.window_chrome_enabled)
        self.t_hscroll = Toggle(g.hscroll_enabled)
        for t in (self.t_zoom, self.t_flick, self.t_chrome, self.t_hscroll):
            t.toggled.connect(self._on_gestures)
        c.add(SettingRow("Zoom a dos manos", "", self.t_zoom))
        c.add(SettingRow("Catapulta = clic derecho", "", self.t_flick))
        c.add(SettingRow("Mover y redimensionar ventanas", "", self.t_chrome))
        c.add(SettingRow("Scroll horizontal", "", self.t_hscroll))
        self.lay.addWidget(c)

    # ------------------------------------------------------------ teclado
    def _build_keyboard(self) -> None:
        c = Card("Teclado virtual")
        g = self.cfg.gestures
        self.t_kb = Toggle(g.keyboard_enabled)
        self.t_kb.toggled.connect(self._on_gestures)
        c.add(SettingRow("Aparece solo",
                         "Al enfocar un campo de texto", self.t_kb))
        self.kb_repeat = LabeledSlider(
            "Repetición al mantener", 120, 800, g.key_repeat_ms, 0, " ms",
            hint="Solo afecta a borrar y espacio")
        self.kb_repeat.valueChanged.connect(self._on_gestures)
        c.add(self.kb_repeat)
        c.add(label(
            "Catapulta encima de una tecla para ver sus variantes (á, à, ä…). "
            "Las teclas con variantes llevan un punto en la esquina.", "faint"))
        self.lay.addWidget(c)

    # ---------------------------------------------------------- seguridad
    def _build_safety(self) -> None:
        c = Card("Seguridad", "Cuatro formas de recuperar el control al instante")
        s = self.cfg.safety
        self.t_face = Toggle(s.pause_on_no_face)
        self.t_mouse = Toggle(s.mouse_override)
        self.t_palm = Toggle(s.open_palm_pause)
        for t in (self.t_face, self.t_mouse, self.t_palm):
            t.toggled.connect(self._on_safety)
        c.add(SettingRow("Pausar sin usuario",
                         "Si no se detecta tu cara durante 3 segundos",
                         self.t_face))
        c.add(SettingRow("Ceder al ratón físico",
                         "Mover el ratón de verdad aparta a AirTouch",
                         self.t_mouse))
        c.add(SettingRow("Palma abierta",
                         "Mantén la mano abierta para pausar o reanudar",
                         self.t_palm))
        c.add(Hr())
        c.add(label(
            "Mantén <b>Esc</b> pulsado un segundo para pausar o reanudar. Esto "
            "funciona siempre, aunque falle todo lo demás.", "faint"))
        self.lay.addWidget(c)

    def _build_reset(self) -> None:
        c = Card("Restablecer")
        row = QHBoxLayout()
        btn = QPushButton("Volver a los valores por defecto")
        btn.setProperty("role", "danger")
        btn.clicked.connect(self.reset_requested.emit)
        row.addWidget(btn)
        row.addStretch(1)
        c.add_layout(row)
        c.add(label("Se conservan la cámara y el tema.", "faint"))
        self.lay.addWidget(c)

    # ----------------------------------------------------------- handlers
    def _on_theme(self, index: int) -> None:
        self.cfg.ui.theme = _THEME_MODES[index]
        self.theme_changed.emit()

    def _on_source(self) -> None:
        self.cfg.camera.source_type = ["airlink", "index", "url"][self.source.currentIndex()]
        self.camera_changed.emit()

    def _on_camera(self, *_a) -> None:
        cfg = self.cfg.camera
        cfg.index = self.cam_index.value()
        w, h = self.res.currentText().split(" x ")
        cfg.width, cfg.height = int(w), int(h)
        self.camera_changed.emit()

    def _on_mirror(self, index: int) -> None:
        self.cfg.camera.mirror_mode = _MIRROR_MODES[index]
        self.changed.emit()

    def _on_pointer(self, *_a) -> None:
        m, f = self.cfg.mapping, self.cfg.filter
        m.mode = "absolute" if self.mode.currentIndex() == 0 else "relative"
        m.monitor = "primary" if self.monitor.currentIndex() == 0 else "virtual"
        m.relative_gain = self.gain.value()
        f.min_cutoff = self.smooth.value()
        f.beta = self.react.value()
        f.prediction_ms = self.predict.value()
        self.changed.emit()

    def _on_gestures(self, *_a) -> None:
        g = self.cfg.gestures
        g.pinch_on = self.pinch_on.value()
        # la banda entre cerrar y abrir tiene que ser estrecha: si es ancha,
        # sigues "clicando" con los dedos ya separados
        g.pinch_off = min(max(self.pinch_off.value(), g.pinch_on + 0.03),
                          g.pinch_on + 0.14)
        self.pinch_off.set_value(g.pinch_off)
        g.pinch_drag_mode = "scroll" if self.drag_mode.currentIndex() == 0 else "drag"
        g.scroll_gain = self.scroll_gain.value()
        g.zoom_gain = self.zoom_gain.value()
        g.zoom_enabled = self.t_zoom.isChecked()
        g.flick_enabled = self.t_flick.isChecked()
        g.flick_min_speed = self.flick_speed.value()
        g.window_chrome_enabled = self.t_chrome.isChecked()
        g.hscroll_enabled = self.t_hscroll.isChecked()
        g.keyboard_enabled = self.t_kb.isChecked()
        g.key_repeat_ms = int(self.kb_repeat.value())
        self.changed.emit()

    def _on_safety(self, *_a) -> None:
        s = self.cfg.safety
        s.pause_on_no_face = self.t_face.isChecked()
        s.mouse_override = self.t_mouse.isChecked()
        s.open_palm_pause = self.t_palm.isChecked()
        self.changed.emit()

    def _on_ui(self, *_a) -> None:
        u = self.cfg.ui
        u.overlay_enabled = self.t_overlay.isChecked()
        u.show_cursor = self.t_cursor.isChecked()
        u.show_hud = self.t_hud.isChecked()
        self.changed.emit()

    def _clear_calibration(self) -> None:
        self.cfg.mapping.homography = None
        self._refresh_cal_state()
        self.changed.emit()

    def _refresh_cal_state(self) -> None:
        if self.cfg.mapping.homography:
            self.cal_state.setText("Calibración personalizada activa.")
        else:
            self.cal_state.setText(
                "Sin calibrar: se usa la región central del encuadre.")

    def refresh_from_config(self) -> None:
        """Recarga los controles tras un reset o una calibración."""
        g, m, f, u = (self.cfg.gestures, self.cfg.mapping, self.cfg.filter,
                      self.cfg.ui)
        self.pinch_on.set_value(g.pinch_on)
        self.pinch_off.set_value(g.pinch_off)
        self.scroll_gain.set_value(g.scroll_gain)
        self.zoom_gain.set_value(g.zoom_gain)
        self.flick_speed.set_value(g.flick_min_speed)
        self.kb_repeat.set_value(g.key_repeat_ms)
        self.smooth.set_value(f.min_cutoff)
        self.react.set_value(f.beta)
        self.gain.set_value(m.relative_gain)
        self.predict.set_value(f.prediction_ms)
        for tog, val in (
            (self.t_zoom, g.zoom_enabled), (self.t_flick, g.flick_enabled),
            (self.t_chrome, g.window_chrome_enabled),
            (self.t_hscroll, g.hscroll_enabled), (self.t_kb, g.keyboard_enabled),
            (self.t_overlay, u.overlay_enabled), (self.t_cursor, u.show_cursor),
            (self.t_hud, u.show_hud),
        ):
            tog.setChecked(val)
        try:
            self.mirror.set_index(_MIRROR_MODES.index(self.cfg.camera.mirror_mode))
        except ValueError:
            pass
        try:
            self.theme_seg.set_index(_THEME_MODES.index(u.theme))
        except ValueError:
            pass
        self._refresh_cal_state()
