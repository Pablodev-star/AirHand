"""Deteccion de manos y cara con MediaPipe Tasks.

Se procesa a resolucion reducida (los landmarks son normalizados, asi que no
perdemos precision relativa) y la cara solo cada N frames.
"""
from __future__ import annotations

import logging
import math
import time

import cv2
import numpy as np

from ..config import VisionConfig
from . import models as model_store
from .frame_state import FaceState, FrameState, HandState

log = logging.getLogger(__name__)


class VisionEngine:
    def __init__(self, cfg: VisionConfig, mirrored: bool = True) -> None:
        self.cfg = cfg
        self.mirrored = mirrored
        self._hand = None
        self._face = None
        self._frame_index = 0
        self._last_face = FaceState()
        self._last_ts_ms = -1
        self.ready = False
        self.error: str | None = None
        # seguimiento por recorte
        self._roi: tuple[float, float, float, float] | None = None
        self._misses = 0
        self.using_roi = False
        #: lo pone el controlador: si nada usa la cara, no se detecta
        self.face_needed = True

    # ---------------- inicializacion ----------------
    def start(self) -> bool:
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision

            self._mp = mp
            self._mp_vision = mp_vision

            hand_opts = mp_vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(
                    model_asset_path=str(model_store.model_path("hand_landmarker.task"))
                ),
                running_mode=mp_vision.RunningMode.VIDEO,
                num_hands=self.cfg.max_hands,
                min_hand_detection_confidence=self.cfg.min_hand_detection_confidence,
                min_hand_presence_confidence=self.cfg.min_hand_presence_confidence,
                min_tracking_confidence=self.cfg.min_tracking_confidence,
            )
            self._hand = mp_vision.HandLandmarker.create_from_options(hand_opts)

            if self.cfg.face_enabled and model_store.is_available("face_landmarker.task"):
                face_opts = mp_vision.FaceLandmarkerOptions(
                    base_options=mp_python.BaseOptions(
                        model_asset_path=str(model_store.model_path("face_landmarker.task"))
                    ),
                    running_mode=mp_vision.RunningMode.VIDEO,
                    num_faces=1,
                    output_facial_transformation_matrixes=True,
                )
                self._face = mp_vision.FaceLandmarker.create_from_options(face_opts)

            self.ready = True
            # Deja constancia del arranque correcto: sin esta linea el registro
            # solo habla cuando algo falla, y no habia forma de distinguir
            # "MediaPipe cargado" de "MediaPipe ni se intento". La prueba de
            # humo de build.py la busca para dar por bueno un ejecutable.
            log.info("Vision lista (cara: %s)", "si" if self._face else "no")
            return True
        except Exception as exc:  # pragma: no cover
            self.error = f"No se pudo inicializar MediaPipe: {exc}"
            log.exception("Fallo al inicializar MediaPipe")
            return False

    def close(self) -> None:
        for obj in (self._hand, self._face):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        self._hand = self._face = None
        self.ready = False

    # ---------------- proceso ----------------
    # ---------------- region de interes ----------------
    def _roi_from_hands(self, state: FrameState) -> tuple[float, float, float, float] | None:
        """Caja que engloba todas las manos, en coordenadas normalizadas."""
        if not state.hands:
            return None
        xs, ys = [], []
        for hand in state.hands:
            xs.extend(hand.lm[:, 0].tolist())
            ys.extend(hand.lm[:, 1].tolist())
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        # cuadrado, para no deformar la mano al reescalar
        half = max(x1 - x0, y1 - y0) * (0.5 + self.cfg.roi_margin)
        half = max(half, 0.09)
        return cx - half, cy - half, cx + half, cy + half

    def _prepare(self, frame_bgr: np.ndarray) -> tuple[np.ndarray, tuple[float, float, float, float]]:
        """Devuelve (imagen RGB para el modelo, mapeo a coords normalizadas).

        El mapeo es (offset_x, offset_y, escala_x, escala_y): convierte un punto
        normalizado del recorte a normalizado del frame completo.
        """
        h, w = frame_bgr.shape[:2]
        roi = self._roi if self.cfg.roi_enabled else None

        if roi is not None:
            x0 = int(max(0.0, roi[0]) * w)
            y0 = int(max(0.0, roi[1]) * h)
            x1 = int(min(1.0, roi[2]) * w)
            y1 = int(min(1.0, roi[3]) * h)
            if x1 - x0 >= 64 and y1 - y0 >= 64:
                crop = frame_bgr[y0:y1, x0:x1]
                side = self.cfg.roi_size
                # el recorte suele ser mas pequeno que el destino: interpolacion
                # lineal, que es la barata para ampliar
                interp = cv2.INTER_LINEAR if (x1 - x0) < side else cv2.INTER_AREA
                small = cv2.resize(crop, (side, side), interpolation=interp)
                rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                return rgb, (x0 / w, y0 / h, (x1 - x0) / w, (y1 - y0) / h)

        target_w = min(self.cfg.downscale_width, w)
        if target_w < w:
            scale = target_w / w
            small = cv2.resize(frame_bgr, (target_w, int(h * scale)),
                               interpolation=cv2.INTER_AREA)
        else:
            small = frame_bgr
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        return rgb, (0.0, 0.0, 1.0, 1.0)

    def process(self, frame_bgr: np.ndarray, t: float, frame_id: int) -> FrameState:
        t0 = time.perf_counter()
        h, w = frame_bgr.shape[:2]

        rgb, mapping = self._prepare(frame_bgr)
        self.using_roi = mapping != (0.0, 0.0, 1.0, 1.0)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)

        # los timestamps deben ser estrictamente crecientes en modo VIDEO
        ts_ms = int(t * 1000)
        if ts_ms <= self._last_ts_ms:
            ts_ms = self._last_ts_ms + 1
        self._last_ts_ms = ts_ms

        state = FrameState(t=t, frame_id=frame_id, width=w, height=h)

        try:
            res = self._hand.detect_for_video(mp_image, ts_ms)
        except Exception as exc:
            log.debug("Fallo de deteccion de manos: %s", exc)
            res = None

        ox, oy, sx, sy = mapping
        if res is not None and res.hand_landmarks:
            for i, lms in enumerate(res.hand_landmarks):
                lm = np.array([[p.x, p.y, p.z] for p in lms], dtype=np.float64)
                # del recorte de vuelta al frame completo
                lm[:, 0] = ox + lm[:, 0] * sx
                lm[:, 1] = oy + lm[:, 1] * sy
                if i < len(res.hand_world_landmarks):
                    wl = res.hand_world_landmarks[i]
                    world = np.array([[p.x, p.y, p.z] for p in wl], dtype=np.float64)
                else:
                    world = lm.copy()

                label, score = "Right", 0.0
                if i < len(res.handedness) and res.handedness[i]:
                    cat = res.handedness[i][0]
                    label, score = cat.category_name, float(cat.score)
                # con imagen en espejo MediaPipe invierte la lateralidad
                if self.mirrored:
                    label = "Left" if label == "Right" else "Right"

                state.hands.append(HandState.build(label, score, lm, world))

        # --- actualizar la region de interes para el siguiente frame ---
        if self.cfg.roi_enabled:
            if state.hands:
                self._roi = self._roi_from_hands(state)
                self._misses = 0
            else:
                self._misses += 1
                if self._misses >= self.cfg.roi_max_misses:
                    self._roi = None          # se vuelve a mirar el frame entero

        # cara: presencia y pose, a menor frecuencia y solo si hace falta.
        # Con recorte activo el modelo de cara necesita el frame completo, asi
        # que se le prepara aparte y muy de vez en cuando.
        self._frame_index += 1
        if self._face is not None and self.face_needed \
                and self._frame_index % max(1, self.cfg.face_every_n_frames) == 0:
            if self.using_roi:
                fw = min(384, w)
                fsmall = cv2.resize(frame_bgr, (fw, int(h * fw / w)),
                                    interpolation=cv2.INTER_AREA)
                face_img = self._mp.Image(
                    image_format=self._mp.ImageFormat.SRGB,
                    data=cv2.cvtColor(fsmall, cv2.COLOR_BGR2RGB))
            else:
                face_img = mp_image
            self._last_face = self._detect_face(face_img, ts_ms)
        elif not self.face_needed:
            self._last_face = FaceState(present=True)
        state.face = self._last_face

        state.process_ms = (time.perf_counter() - t0) * 1000.0
        state.capture_latency_ms = max(0.0, (time.perf_counter() - t) * 1000.0)
        return state

    def _detect_face(self, mp_image, ts_ms: int) -> FaceState:
        try:
            res = self._face.detect_for_video(mp_image, ts_ms)
        except Exception:
            return FaceState()
        if not res or not res.face_landmarks:
            return FaceState()

        pts = res.face_landmarks[0]
        center = np.array([
            float(np.mean([p.x for p in pts])),
            float(np.mean([p.y for p in pts])),
        ])
        yaw = pitch = roll = 0.0
        mats = getattr(res, "facial_transformation_matrixes", None)
        if mats:
            m = np.asarray(mats[0], dtype=np.float64).reshape(4, 4)
            r = m[:3, :3]
            sy = math.hypot(r[0, 0], r[1, 0])
            if sy > 1e-6:
                pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
                yaw = math.degrees(math.atan2(-r[2, 0], sy))
                roll = math.degrees(math.atan2(r[1, 0], r[0, 0]))
        return FaceState(present=True, center=center, yaw=yaw, pitch=pitch, roll=roll)
