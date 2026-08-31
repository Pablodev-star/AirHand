"""Comprobacion de actualizaciones.

Diseñado para no tener que tocarse nunca: pregunta a la API de GitHub cual es
la ultima publicacion, compara el numero de version y coge el primer archivo
instalable que traiga. Publicar una version nueva es lo unico que hace falta;
ni esta clase ni la pagina web necesitan cambios.

La comprobacion corre en un hilo aparte y falla en silencio: quedarse sin
internet no puede impedirte usar el programa.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.request
from dataclasses import dataclass

from ..version import RELEASES_API, RELEASES_URL, __version__, is_newer

log = logging.getLogger(__name__)

TIMEOUT = 8
_INSTALLABLE = (".exe", ".zip", ".msi")


@dataclass
class Release:
    version: str
    url: str                 # pagina de la publicacion
    download: str            # archivo directo, si lo hay
    notes: str
    size: int = 0

    @property
    def size_mb(self) -> float:
        return self.size / 1024 / 1024 if self.size else 0.0


class UpdateChecker:
    """Consulta la ultima version publicada, sin bloquear la interfaz."""

    def __init__(self) -> None:
        self.latest: Release | None = None
        self.checked = False
        self.error: str | None = None
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return self.latest is not None and is_newer(self.latest.version)

    def check_async(self, on_done=None) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._check, args=(on_done,), name="AirTouch-Updates",
            daemon=True)
        self._thread.start()

    def _check(self, on_done) -> None:
        try:
            req = urllib.request.Request(
                RELEASES_API,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"AirHand/{__version__}",
                },
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            asset = None
            for a in data.get("assets") or []:
                if str(a.get("name", "")).lower().endswith(_INSTALLABLE):
                    asset = a
                    break

            self.latest = Release(
                version=str(data.get("tag_name") or ""),
                url=str(data.get("html_url") or RELEASES_URL),
                download=str(asset.get("browser_download_url")) if asset else "",
                notes=str(data.get("body") or "")[:2000],
                size=int(asset.get("size", 0)) if asset else 0,
            )
            log.info("Última versión publicada: %s (la tuya: %s)",
                     self.latest.version, __version__)
        except Exception as exc:
            # sin internet, sin publicaciones aun, o GitHub limitando: da igual
            self.error = str(exc)
            log.info("No se pudo comprobar actualizaciones: %s", exc)
        finally:
            self.checked = True
            if on_done is not None:
                try:
                    on_done(self)
                except Exception:
                    pass

    def summary(self) -> str:
        if not self.checked:
            return "Comprobando actualizaciones…"
        if self.available and self.latest:
            return (f"Hay una versión nueva: {self.latest.version} "
                    f"(tienes la {__version__})")
        if self.error:
            return "No se pudo comprobar si hay actualizaciones"
        return f"Estás en la última versión ({__version__})"
