"""Punto de entrada de la aplicacion: monta todas las piezas."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .config import LOGS_DIR, Config
from .core import models
from .core.controller import Controller
from .core.screen import enable_dpi_awareness
from .overlay import style as overlay_style
from .overlay.canvas import OverlayCanvas
from .ui import theme
from .ui.calibration import CalibrationWindow
from .ui.dashboard import Dashboard
from .ui.tray import Tray, build_icon
from .ui.wizard.wizard import SetupWizard

log = logging.getLogger("airtouch")


def setup_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOGS_DIR / "airtouch.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler(sys.stdout))


_MUTEX_NAME = "AirTouch.SingleInstance.v1"
_mutex_handle = None


def acquire_single_instance() -> bool:
    """Solo una instancia: dos a la vez se pelean por la camara y la segunda
    falla con un error confuso."""
    global _mutex_handle
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _mutex_handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        return ctypes.get_last_error() != 183      # ERROR_ALREADY_EXISTS
    except Exception:
        return True                                # ante la duda, dejar arrancar


def set_autostart(enabled: bool) -> None:
    """Entrada en HKCU\\...\\Run. Solo afecta al usuario actual."""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        with key:
            if enabled:
                target = f'"{sys.executable}" -m airtouch --minimized'
                if getattr(sys, "frozen", False):
                    target = f'"{sys.executable}" --minimized'
                winreg.SetValueEx(key, "AirTouch", 0, winreg.REG_SZ, target)
            else:
                try:
                    winreg.DeleteValue(key, "AirTouch")
                except FileNotFoundError:
                    pass
    except Exception as exc:
        log.warning("No se pudo cambiar el arranque automatico: %s", exc)


class Application:
    def __init__(self, argv: list[str]) -> None:
        enable_dpi_awareness()
        self.qt = QApplication(argv)
        self.qt.setApplicationName("AirTouch")
        self.qt.setQuitOnLastWindowClosed(False)

        self.cfg = Config.load()
        self.cfg.save()          # persiste las migraciones de versión
        theme.apply(self.cfg.ui.theme)
        self.qt.setStyleSheet(theme.qss())
        self.qt.setWindowIcon(build_icon(False))
        theme.signals.changed.connect(self._on_theme_changed)
        overlay_style.apply_theme(theme.C.dark)

        # el tema "auto" debe seguir a Windows aunque cambie con la app abierta
        self._theme_watch = QTimer()
        self._theme_watch.setInterval(4000)
        self._theme_watch.timeout.connect(self._poll_system_theme)
        self._theme_watch.start()
        self._system_dark = not theme.windows_prefers_light()
        self.controller = Controller(self.cfg)

        self.overlay = OverlayCanvas(self.cfg)
        self.overlay.engine_ref = self.controller.engine

        self.dashboard = Dashboard(self.cfg, self.controller)
        self.dashboard.open_calibration = self.open_calibration
        self.dashboard.open_wizard = self.open_wizard

        self.tray = Tray()
        self._wire_tray()

        self.controller.output_ready.connect(
            self.overlay.set_output, Qt.ConnectionType.QueuedConnection)

        self._tray_timer = QTimer()
        self._tray_timer.setInterval(900)
        self._tray_timer.timeout.connect(self._refresh_tray)
        self._tray_timer.start()

        self._calibration: CalibrationWindow | None = None

    # ---------------- arranque ----------------
    def run(self, minimized: bool = False) -> int:
        # si la sesion anterior murio de golpe, puede haber dejado la ventana
        # de la camara fuera de pantalla: se recupera antes de nada
        from .actuators import windows_mgr as wm

        n = wm.restore_from_previous_run()
        if n:
            log.info("Recuperadas %d ventanas apartadas por una sesion anterior", n)

        # El servidor de AirLink se levanta con la aplicación, no con el motor:
        # tienes que poder emparejar el móvil antes de encender nada.
        if self.cfg.airlink.enabled and self.cfg.camera.source_type == "airlink":
            if self.controller.airlink.start():
                log.info("AirLink en %s", self.controller.airlink.url)
            else:
                log.warning("AirLink no arrancó: %s", self.controller.airlink.error)

        self.tray.show()

        missing = models.missing_models()
        if missing:
            if not self._download_models(missing):
                return 1

        if self.cfg.app.first_run:
            self.dashboard.show()
            QTimer.singleShot(200, self.open_wizard)
        else:
            self.controller.start()
            self._show_overlay()
            if not (minimized or self.cfg.app.start_minimized):
                self.dashboard.show()
            else:
                self.tray.showMessage(
                    "AirTouch", "En marcha en la bandeja del sistema.",
                    build_icon(True), 2500)
        return self.qt.exec()

    def _download_models(self, missing: list[str]) -> bool:
        box = QMessageBox(self.dashboard)
        box.setWindowTitle("AirTouch")
        box.setText("Descargando los modelos de detección (unos 12 MB)…")
        box.setStandardButtons(QMessageBox.StandardButton.NoButton)
        box.show()
        self.qt.processEvents()
        try:
            models.ensure_models()
            box.close()
            return True
        except Exception as exc:
            box.close()
            QMessageBox.critical(
                None, "AirTouch",
                f"No se pudieron descargar los modelos:\n{exc}\n\n"
                "Comprueba tu conexión a internet y vuelve a abrir la aplicación.")
            return False

    # ---------------- tema ----------------
    def _on_theme_changed(self, _name: str) -> None:
        overlay_style.apply_theme(theme.C.dark)
        self.overlay.update()

    def _poll_system_theme(self) -> None:
        if self.cfg.ui.theme != "system":
            return
        dark = not theme.windows_prefers_light()
        if dark != self._system_dark:
            self._system_dark = dark
            theme.apply("system")
            self.qt.setStyleSheet(theme.qss())

    # ---------------- overlay ----------------
    def _show_overlay(self) -> None:
        if not self.cfg.ui.overlay_enabled:
            return
        self.overlay.refresh_geometry()
        self.overlay.show_overlay()
        self.overlay.raise_()
        hwnd = self.overlay.hwnd()
        if hwnd:
            self.controller.engine.ignore_hwnds.add(hwnd)

    def _ensure_overlay(self) -> None:
        """El overlay debe estar visible siempre que el motor corra.

        Se comprueba periodicamente en vez de confiar en que cada camino
        (asistente, boton del panel, bandeja) se acuerde de mostrarlo: antes
        bastaba con parar y arrancar el motor para quedarse sin cursor.
        """
        want = self.controller.running and self.cfg.ui.overlay_enabled
        if want and not self.overlay.isVisible():
            self._show_overlay()
        elif not want and self.overlay.isVisible():
            self.overlay.hide_overlay()

    # ---------------- dialogos ----------------
    def open_wizard(self) -> None:
        if not self.controller.running:
            self.controller.start()
        self._show_overlay()
        wizard = SetupWizard(self.cfg, self.controller, self.dashboard)
        wizard.completed.connect(self._on_wizard_done)
        wizard.exec()

    def _on_wizard_done(self, want_control: bool) -> None:
        set_autostart(self.cfg.app.start_with_windows)
        self.dashboard.settings.refresh_from_config()
        self.controller.retune()
        if not self.controller.running:
            self.controller.start()
        self._show_overlay()
        if want_control:
            self.dashboard.control_toggle.setChecked(True)
            self.controller.set_control_enabled(True)
            self.dashboard._refresh_control_hint()
        self.dashboard.show()
        self.dashboard.btn_engine.setText("Detener motor")
        # el motor ya esta en marcha: el panel debe encogerse, igual que
        # cuando lo arrancas desde el boton
        self.dashboard.enter_compact()
        self.dashboard.raise_()

    def open_calibration(self) -> None:
        if not self.controller.running:
            self.controller.start()
        win = CalibrationWindow(self.cfg)
        self._calibration = win
        self.controller.output_ready.connect(
            win.on_output, Qt.ConnectionType.QueuedConnection)

        def _done(ok: bool) -> None:
            try:
                self.controller.output_ready.disconnect(win.on_output)
            except (RuntimeError, TypeError):
                pass
            self.controller.mapper.refresh_calibration()
            self.dashboard.settings.refresh_from_config()
            self._calibration = None
            if ok:
                self.dashboard._append_log("Calibración guardada")

        win.finished.connect(_done)
        win.begin()

    # ---------------- bandeja ----------------
    def _wire_tray(self) -> None:
        self.tray.show_dashboard.connect(self._show_dashboard)
        self.tray.toggle_engine.connect(self._toggle_engine)
        self.tray.toggle_control.connect(self._toggle_control)
        self.tray.toggle_keyboard.connect(self.controller.toggle_keyboard)
        self.tray.quit_app.connect(self.quit)

    def _show_dashboard(self) -> None:
        self.dashboard.show()
        self.dashboard.setWindowState(
            self.dashboard.windowState() & ~Qt.WindowState.WindowMinimized)
        self.dashboard.raise_()
        self.dashboard.activateWindow()

    def _toggle_engine(self) -> None:
        self.dashboard._toggle_engine()
        self._ensure_overlay()

    def _toggle_control(self) -> None:
        new = not self.cfg.safety.control_enabled
        self.dashboard.control_toggle.setChecked(new)
        self.controller.set_control_enabled(new)
        self.dashboard._refresh_control_hint()

    def _refresh_tray(self) -> None:
        self.tray.refresh(self.controller.running, self.cfg.safety.control_enabled)
        self._ensure_overlay()

    # ---------------- salida ----------------
    def quit(self) -> None:
        self.cfg.save()
        self.controller.stop()
        self.controller.airlink.stop()      # ahora si: se cierra al salir
        self.overlay.hide_overlay()
        self.tray.hide()
        self.qt.quit()


def selftest() -> int:
    """Comprueba una instalacion sin abrir la interfaz. `AirTouch.exe --selftest`.

    Existe porque compilar sin errores no demuestra nada: los fallos de
    empaquetado (una ruta que cambia al congelar, un modulo que PyInstaller no
    ve, una dependencia excluida de mas) solo se manifiestan al ejecutar el
    binario, y varios ni siquiera impiden que se abra la ventana. Hubo uno asi:
    la aplicacion arrancaba, se veia el panel, y MediaPipe no habia llegado a
    cargar, de modo que no detectaba ni una mano.

    Se ejecuta antes de publicar y tambien sirve al usuario si algo va raro.
    """
    from .config import Config, MODELS_DIR, PROJECT_ROOT
    from .core import models as model_store

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, fn) -> None:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        checks.append((name, ok, detail))

    def _models():
        missing = model_store.missing_models()
        if missing:
            return False, f"faltan {', '.join(missing)} en {MODELS_DIR}"
        return True, str(MODELS_DIR)

    def _web():
        root = PROJECT_ROOT / "airlink-web"
        index = root / "index.html"
        if not index.exists():
            return False, f"no esta {index}"
        n = len(list(root.rglob("*")))
        return True, f"{n} archivos"

    def _vision():
        # Lo que de verdad importa: que MediaPipe cargue con los modelos que
        # viajan dentro del paquete.
        from .core.vision import VisionEngine

        engine = VisionEngine(Config().vision)
        ok = engine.start()
        detail = "MediaPipe cargado" if ok else (engine.error or "sin detalle")
        engine.close()
        return ok, detail

    def _qt():
        from PySide6 import QtCore
        return True, f"Qt {QtCore.__version__}"

    def _net():
        import aiortc, av                                   # noqa: F401
        from .net.certs import preferred_ip
        return True, f"WebRTC listo, IP {preferred_ip()}"

    check("Modelos", _models)
    check("Web de AirLink", _web)
    check("Qt", _qt)
    check("Red y WebRTC", _net)
    check("Vision", _vision)

    from .version import __version__

    def emit(line: str) -> None:
        # Compilado con --noconsole no hay salida estandar (PyInstaller deja
        # sys.stdout en None), asi que el registro es el canal fiable; el print
        # es para cuando si hay consola.
        log.info("%s", line)
        try:
            print(line)
        except Exception:
            pass

    emit(f"AirTouch {__version__} - autodiagnostico")
    emit(f"  {'compilado' if getattr(sys, 'frozen', False) else 'desde codigo'}"
         f" - {PROJECT_ROOT}")
    for name, ok, detail in checks:
        emit(f"  [{'OK ' if ok else 'MAL'}] {name}: {detail}")

    failed = [n for n, ok, _ in checks if not ok]
    if failed:
        emit(f"AUTODIAGNOSTICO FALLIDO: {', '.join(failed)}")
        return 1
    emit("AUTODIAGNOSTICO CORRECTO")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    setup_logging()
    if "--selftest" in argv:
        return selftest()
    minimized = "--minimized" in argv
    if not acquire_single_instance():
        from PySide6.QtWidgets import QApplication as _QApp

        _QApp(argv[:1])
        QMessageBox.information(
            None, "AirTouch",
            "AirTouch ya se está ejecutando.\n\n"
            "Búscalo en la bandeja del sistema (junto al reloj): haz doble clic "
            "en su icono para abrir el panel.")
        return 0
    try:
        app = Application([a for a in argv if a != "--minimized"])
        return app.run(minimized=minimized)
    except Exception as exc:  # pragma: no cover
        log.exception("Fallo fatal")
        try:
            QMessageBox.critical(None, "AirTouch", f"Error fatal:\n{exc}")
        except Exception:
            pass
        return 1
