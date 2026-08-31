"""Controlador: une captura, vision, gestos, seguridad y actuacion.

Corre en su propio hilo y publica el estado por senales de Qt. Es el unico
sitio donde se decide si un evento llega de verdad al sistema operativo.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

from PySide6.QtCore import QObject, Signal

from ..actuators import input_win as inp
from ..actuators import windows_mgr as wm
from ..actuators.safety import SafetyGuard
from ..actuators.text_field import TextFieldDetector
from ..config import Config
from ..gestures.engine import EngineOutput, GestureEngine
from ..gestures.events import EventType, GestureEvent, Mode
from .capture import CaptureThread
from .filters import EMA
from ..net.airlink import AirLinkServer
from .frame_state import FrameState
from .mapping import PointerMapper
from .vision import VisionEngine

log = logging.getLogger(__name__)

_VK = {
    "backspace": inp.VK_BACK,
    "enter": inp.VK_RETURN,
    "tab": inp.VK_TAB,
    "escape": inp.VK_ESCAPE,
    "left": inp.VK_LEFT,
    "right": inp.VK_RIGHT,
    "up": inp.VK_UP,
    "down": inp.VK_DOWN,
    "delete": inp.VK_DELETE,
}


class Controller(QObject):
    # senales hacia la UI (conexiones en cola: seguras entre hilos)
    output_ready = Signal(object)        # EngineOutput
    frame_ready = Signal(object)         # (numpy BGR, FrameState)
    stats_ready = Signal(dict)
    status_changed = Signal(str)
    log_line = Signal(str)
    error = Signal(str)

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        # AirLink es nuestra propia camara por WiFi. Expone el mismo read() que
        # CaptureThread, asi que el resto del programa no distingue una de otra.
        self.airlink = AirLinkServer(cfg.airlink)
        self.capture = CaptureThread(cfg.camera)
        self.vision = VisionEngine(cfg.vision, mirrored=cfg.camera.mirror)
        self.mapper = PointerMapper(cfg.mapping, cfg.filter)
        self.engine = GestureEngine(cfg, self.mapper)
        self.safety = SafetyGuard(cfg.safety)
        self.text_fields = TextFieldDetector()

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False

        self.preview_enabled = False
        self._preview_every = 2
        self._frame_n = 0

        self.pipeline_fps = EMA(0.1, 0.0)
        self.latency_ms = EMA(0.1, 0.0)
        self._last_loop_t = 0.0
        self._focus_check_at = 0.0
        self._kb_recheck_at = 0.0
        self._recent = deque(maxlen=200)
        self._last_status = ""

        # el motor nunca debe intentar manipular nuestras propias ventanas
        self.engine.ignore_hwnds = set()

    # ---------------- ciclo de vida ----------------
    @property
    def running(self) -> bool:
        return self._running

    @property
    def using_airlink(self) -> bool:
        return self.cfg.camera.source_type == "airlink"

    @property
    def source(self):
        """La fuente de video activa. Las dos exponen read()/snapshot()."""
        return self.airlink if self.using_airlink else self.capture

    @property
    def source_connected(self) -> bool:
        return (self.airlink.phone_connected if self.using_airlink
                else self.capture.connected)

    @property
    def source_error(self) -> str | None:
        return self.airlink.error if self.using_airlink else self.capture.error

    @property
    def effective_mirror(self) -> bool:
        """Si hay que invertir la imagen en horizontal.

        En "auto" manda la cámara que esté usando el móvil: la frontal es la
        vista de espejo a la que todo el mundo está acostumbrado, la trasera es
        la vista "real" y no se invierte.
        """
        mode = getattr(self.cfg.camera, "mirror_mode", "auto")
        if mode == "on":
            return True
        if mode == "off":
            return False
        if self.using_airlink:
            facing = self.airlink.facing
            if facing == "environment":
                return False
            if facing == "user":
                return True
        return True          # webcam del sistema, o aún sin saberlo

    def start(self) -> bool:
        if self._running:
            return True
        if not self.vision.ready and not self.vision.start():
            self.error.emit(self.vision.error or "Fallo al iniciar la vision")
            return False
        self._stop.clear()

        if self.using_airlink:
            # normalmente ya esta en marcha desde que abrio la app
            if not self.airlink.running and not self.airlink.start():
                self.error.emit(self.airlink.error or "AirLink no pudo arrancar")
                return False
        else:
            # un threading.Thread solo se puede arrancar una vez: tras un stop
            # hay que fabricar uno nuevo o el segundo arranque revienta
            if self.capture.ident is not None or self.capture.is_alive():
                self.capture = CaptureThread(self.cfg.camera)
        self.engine.reset()
        self.safety.resume()
        self._last_loop_t = 0.0
        self._frame_n = 0
        if not self.using_airlink:
            self.capture.start()          # con AirLink no se toca la webcam
        self._thread = threading.Thread(target=self._loop, name="AirTouch-Pipeline", daemon=True)
        self._thread.start()
        self._running = True
        if not self.using_airlink:
            self._stash_camera_app()
        self._emit_log("Motor iniciado")
        return True

    # ---------------- ventana de la app de camara ----------------
    def _stash_camera_app(self) -> None:
        """Aparta la ventana de iVCam de la vista mientras AirTouch trabaja."""
        if not self.cfg.camera.hide_source_window:
            return
        try:
            for name in ("ivcam", "camo", "epoccam", "droidcam"):
                for w in wm.find_windows_by_title(name):
                    if wm.stash_window(w.hwnd):
                        self.engine.ignore_hwnds.add(w.hwnd)
                        self._emit_log(f"Ventana «{w.title}» apartada de la vista")
        except Exception as exc:
            log.warning("No se pudo apartar la ventana de la camara: %s", exc)

    def _restore_camera_app(self) -> None:
        try:
            for hwnd in wm.stashed_hwnds():
                self.engine.ignore_hwnds.discard(hwnd)
            wm.restore_stashed()
        except Exception:
            pass

    def stop(self) -> None:
        if not self._running:
            return
        self._stop.set()
        self.capture.stop()
        # AirLink NO se para aqui: sigue escuchando para que puedas emparejar
        # el movil con el motor apagado. Se cierra al salir de la aplicacion.
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._release_everything()
        self._restore_camera_app()
        self.vision.close()
        self._running = False
        self._emit_log("Motor detenido")

    def restart_camera(self) -> None:
        if self.using_airlink:
            self.airlink.stop()
            if self._running:
                self.airlink.start()
            self._emit_log("AirLink reiniciado")
            return
        self.capture.reconfigure(self.cfg.camera)
        self.vision.mirrored = self.cfg.camera.mirror
        self._emit_log("Camara reconfigurada")

    def retune(self) -> None:
        """Aplica cambios de configuracion en caliente."""
        self.mapper.retune()
        self.engine.retune()
        self.vision.cfg = self.cfg.vision
        self._emit_log("Ajustes aplicados")

    # ---------------- bucle ----------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            frame, t, fid = self.source.read(timeout=0.4)
            if frame is None:
                err = self.source_error
                if err:
                    self._set_status(err)
                elif self.using_airlink and not self.airlink.phone_connected:
                    self._set_status("Esperando al móvil…")
                continue

            now = time.perf_counter()
            if self._last_loop_t:
                dt = now - self._last_loop_t
                if dt > 0:
                    self.pipeline_fps.update(1.0 / dt)
            self._last_loop_t = now

            # la cara solo se analiza si algo la usa de verdad
            self.vision.face_needed = self.cfg.safety.pause_on_no_face
            # el espejo puede cambiar en caliente (ajuste, o cámara distinta)
            mirror = self.effective_mirror
            if mirror != self.cfg.camera.mirror:
                self.cfg.camera.mirror = mirror
                self._emit_log(
                    f"Modo espejo: {'invertido' if mirror else 'sin invertir'}")
            self.airlink.mirror = mirror
            self.vision.mirrored = mirror
            try:
                fs = self.vision.process(frame, t, fid)
            except Exception as exc:  # pragma: no cover
                log.exception("Fallo en vision")
                self._set_status(f"Error de vision: {exc}")
                continue

            self.latency_ms.update(fs.capture_latency_ms)

            safety = self.safety.check(fs, now)
            self.engine.paused = safety.paused
            out = self.engine.update(fs)

            if self.safety.may_inject():
                self._actuate(out)
            self._maybe_toggle_keyboard(out, now)

            self.output_ready.emit(out)
            self._frame_n += 1
            if self.preview_enabled and self._frame_n % self._preview_every == 0:
                self.frame_ready.emit((frame, fs))

            if self._frame_n % 15 == 0:
                self._emit_stats(fs)
            self._set_status(self.safety.status_text())

    # ---------------- actuacion ----------------
    def _actuate(self, out: EngineOutput) -> None:
        for ev in out.events:
            try:
                self._apply(ev)
            except Exception as exc:  # pragma: no cover
                log.warning("Fallo al aplicar %s: %s", ev, exc)
        if out.note:
            self._remember(out.note)

    def _apply(self, ev: GestureEvent) -> None:
        t = ev.type
        d = ev.data
        if t is EventType.MOVE:
            inp.move_to(d["x"], d["y"])
            self.safety.note_injected_cursor(d["x"], d["y"])
        elif t is EventType.CLICK:
            inp.left_click()
        elif t is EventType.DOUBLE_CLICK:
            inp.double_click()
        elif t is EventType.LEFT_DOWN:
            inp.left_down()
        elif t is EventType.LEFT_UP:
            inp.left_up()
        elif t is EventType.RIGHT_CLICK:
            inp.right_click()
        elif t is EventType.SCROLL:
            inp.scroll(d["notches"])
        elif t is EventType.HSCROLL:
            inp.hscroll(d["notches"])
        elif t is EventType.ZOOM:
            inp.zoom(d["notches"])
        elif t is EventType.WINDOW_BOUNDS:
            # coordenadas visuales: el motor razona con lo que se ve
            wm.set_visual_bounds(d["hwnd"], d["left"], d["top"], d["width"], d["height"])
        elif t is EventType.KEY_TEXT:
            inp.type_unicode(d["text"])
        elif t is EventType.KEY_VK:
            vk = _VK.get(d.get("key", ""))
            if vk:
                inp.tap(vk)

    def _release_everything(self) -> None:
        """Nunca dejar un boton pulsado si el motor se para a media accion."""
        try:
            inp.left_up()
        except Exception:
            pass

    # ---------------- teclado automatico ----------------
    def _maybe_toggle_keyboard(self, out: EngineOutput, now: float) -> None:
        if not self.cfg.gestures.keyboard_enabled:
            if self.engine.keyboard_visible:
                self.engine.show_keyboard(False)
            return

        # tras un clic, el foco tarda un poco en asentarse
        for ev in out.events:
            if ev.type in (EventType.CLICK, EventType.DOUBLE_CLICK):
                self._focus_check_at = now + 0.28

        if self._focus_check_at and now >= self._focus_check_at:
            self._focus_check_at = 0.0
            if self.text_fields.focused_is_text_field():
                if not self.engine.keyboard_visible:
                    self.engine.show_keyboard(True)
                    self._emit_log("Campo de texto detectado: teclado visible")
            self._kb_recheck_at = now + 1.5

        # si ya no hay campo de texto con el foco, se retira solo
        if self.engine.keyboard_visible and self._kb_recheck_at and now >= self._kb_recheck_at:
            self._kb_recheck_at = now + 1.5
            if self.engine.mode is not Mode.KEYBOARD and \
                    not self.text_fields.focused_is_text_field():
                self.engine.show_keyboard(False)
                self._emit_log("Teclado oculto")

    def toggle_keyboard(self) -> None:
        self.engine.show_keyboard(not self.engine.keyboard_visible)

    # ---------------- estado ----------------
    def set_control_enabled(self, enabled: bool) -> None:
        self.cfg.safety.control_enabled = enabled
        if not enabled:
            self._release_everything()
        self.safety.resume()
        self._emit_log("Control real ACTIVADO" if enabled else "Modo seguro (simulacion)")
        self._set_status(self.safety.status_text(), force=True)

    def _emit_stats(self, fs: FrameState) -> None:
        self.stats_ready.emit({
            "camera_fps": round(self.pipeline_fps.value or 0.0, 1) if self.using_airlink
                          else round(self.capture.fps.value or 0.0, 1),
            "pipeline_fps": round(self.pipeline_fps.value or 0.0, 1),
            "latency_ms": round(self.latency_ms.value or 0.0, 1),
            "process_ms": round(fs.process_ms, 1),
            "hands": len(fs.hands),
            "face": fs.face.present,
            "resolution": f"{fs.width}x{fs.height}",
            "low_res": fs.width < 960,
            # por debajo de esto los landmarks salen tan ruidosos que ningun
            # filtro lo arregla: hay que avisar
            "low_res": fs.width < 960,
            "connected": self.source_connected,
            "control": self.cfg.safety.control_enabled,
            "paused": self.safety.state.paused,
        })

    def _set_status(self, text: str, force: bool = False) -> None:
        if force or text != self._last_status:
            self._last_status = text
            self.status_changed.emit(text)

    def _emit_log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_line.emit(f"[{stamp}] {text}")

    def _remember(self, note: str) -> None:
        if not self._recent or self._recent[-1] != note:
            self._recent.append(note)
            self._emit_log(note)
