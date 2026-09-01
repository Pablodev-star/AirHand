"""Captura de video.

Un hilo dedicado que lee siempre el frame mas reciente y descarta los viejos.
En control gestual la latencia importa mucho mas que no perder frames.
"""
from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np

from ..config import CameraConfig
from .filters import EMA

log = logging.getLogger(__name__)

_BACKENDS = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "any": cv2.CAP_ANY,
}


def list_camera_indices(max_index: int = 8) -> list[int]:
    """Indices de camara que responden. DirectShow es el mas fiable en Windows."""
    found: list[int] = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        try:
            if cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    found.append(i)
        finally:
            cap.release()
    return found


def list_camera_names() -> list[str]:
    """Nombres legibles de las camaras (via DirectShow). Puede fallar sin drama."""
    names: list[str] = []
    try:
        from pygrabber.dshow_graph import FilterGraph  # type: ignore

        names = FilterGraph().get_input_devices()
    except Exception:
        pass
    return names


class CaptureThread(threading.Thread):
    """Lee de la camara y publica el ultimo frame disponible."""

    def __init__(self, cfg: CameraConfig) -> None:
        super().__init__(name="AirTouch-Capture", daemon=True)
        self.cfg = cfg
        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_t: float = 0.0
        self._frame_id: int = 0
        self._stop = threading.Event()
        self._new_frame = threading.Event()

        self.fps = EMA(0.1, 0.0)
        self.error: str | None = None
        self.connected = False
        self.actual_size: tuple[int, int] = (0, 0)

    # ---------------- ciclo de vida ----------------
    def _open(self) -> bool:
        self.error = None
        try:
            if self.cfg.source_type == "url":
                if not self.cfg.url:
                    self.error = "No se ha configurado la URL del stream."
                    return False
                cap = cv2.VideoCapture(self.cfg.url)
            else:
                backend = _BACKENDS.get(self.cfg.backend, cv2.CAP_DSHOW)
                cap = cv2.VideoCapture(int(self.cfg.index), backend)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
                cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)

            # buffer minimo: queremos el frame de AHORA, no una cola
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

            if not cap.isOpened():
                self.error = (
                    "No se pudo abrir la camara del sistema. Comprueba que "
                    "ninguna otra app la este usando (Zoom, Teams, Chrome, otra "
                    "copia de AirTouch...). Si querias usar el movil, cambia el "
                    "origen a AirLink en Ajustes."
                )
                cap.release()
                return False

            ok, frame = cap.read()
            if not ok or frame is None:
                self.error = "La camara se abrio pero no envia imagen."
                cap.release()
                return False

            self._cap = cap
            self.actual_size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
            self.connected = True
            log.info("Camara abierta: %s @ %s", self.actual_size, cap.get(cv2.CAP_PROP_FPS))
            return True
        except Exception as exc:  # pragma: no cover - depende del hardware
            self.error = f"Error al abrir la camara: {exc}"
            return False

    def run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            if self._cap is None:
                if not self._open():
                    self.connected = False
                    if self._stop.wait(backoff):
                        break
                    backoff = min(backoff * 1.6, 5.0)
                    continue
                backoff = 0.5

            t0 = time.perf_counter()
            ok, frame = self._cap.read()  # type: ignore[union-attr]
            if not ok or frame is None:
                log.warning("Frame perdido; reconectando")
                self._release()
                continue

            if self.cfg.mirror:
                frame = cv2.flip(frame, 1)

            now = time.perf_counter()
            dt = now - self._frame_t if self._frame_t else 0.0
            if dt > 0:
                self.fps.update(1.0 / dt)

            with self._lock:
                self._frame = frame
                self._frame_t = now
                self._frame_id += 1
            self._new_frame.set()
            _ = t0

        self._release()

    def _release(self) -> None:
        self.connected = False
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def stop(self) -> None:
        self._stop.set()
        self._new_frame.set()

    # ---------------- consumo ----------------
    def read(self, timeout: float = 0.5) -> tuple[np.ndarray | None, float, int]:
        """Devuelve (frame, timestamp, frame_id). Bloquea hasta que haya uno nuevo."""
        if not self._new_frame.wait(timeout):
            return None, 0.0, -1
        with self._lock:
            self._new_frame.clear()
            if self._frame is None:
                return None, 0.0, -1
            return self._frame, self._frame_t, self._frame_id

    def snapshot(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def reconfigure(self, cfg: CameraConfig) -> None:
        """Cambia de fuente en caliente."""
        self.cfg = cfg
        self._release()
