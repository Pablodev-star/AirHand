"""Descarga y localizacion de los modelos de MediaPipe."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from ..config import MODELS_DIR

log = logging.getLogger(__name__)

MODEL_URLS = {
    "hand_landmarker.task":
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
        "hand_landmarker/float16/1/hand_landmarker.task",
    "face_landmarker.task":
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task",
}


def model_path(name: str) -> Path:
    return MODELS_DIR / name


def is_available(name: str) -> bool:
    p = model_path(name)
    return p.exists() and p.stat().st_size > 1024


def missing_models() -> list[str]:
    return [n for n in MODEL_URLS if not is_available(n)]


def download_model(name: str, progress: Callable[[int, int], None] | None = None) -> Path:
    """Descarga un modelo si falta. Devuelve la ruta local."""
    import requests

    dest = model_path(name)
    if is_available(name):
        return dest

    url = MODEL_URLS[name]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("Descargando modelo %s", name)

    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if not chunk:
                    continue
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    tmp.replace(dest)
    return dest


def ensure_models(progress: Callable[[str, int, int], None] | None = None) -> None:
    for name in MODEL_URLS:
        if is_available(name):
            continue
        download_model(name, (lambda d, t, n=name: progress(n, d, t)) if progress else None)
