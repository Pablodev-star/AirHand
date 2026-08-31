"""Receptor de AirLink: recibe la camara del movil por WebRTC.

Arquitectura
------------
El servidor vive en su propio hilo con su propio bucle de asyncio, porque
aiortc es asincrono y el resto de AirTouch no lo es. La comunicacion con el
resto del programa es un unico buzon de un frame: el hilo de vision coge
siempre el ultimo disponible y descarta lo viejo, igual que con una webcam.

  movil                         PC (este archivo)
  -----                         -----------------
  getUserMedia
  RTCPeerConnection  --wss-->   /signal   (SDP + ICE, unos 3 KB)
        |                          |
        +------- vídeo WebRTC ---->+  aiortc decodifica -> numpy BGR
                 (directo por WiFi)         |
                                            v
                                     buzon de 1 frame -> CaptureThread

El token de emparejamiento no es decorativo: sin el, cualquiera en la misma red
podria enchufar su movil a este ordenador.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import threading
import time
from pathlib import Path

import numpy as np

from ..config import PROJECT_ROOT, AirLinkConfig
from . import certs

log = logging.getLogger(__name__)

WEB_ROOT = PROJECT_ROOT / "airlink-web"

# Alfabeto sin caracteres que se confunden al leerlos (0/O, 1/I/L).
_TOKEN_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def make_token(length: int = 6) -> str:
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(length))


def _with_bandwidth(sdp: str, kbps: int = 20000) -> str:
    """Anuncia un techo de ancho de banda alto en la respuesta.

    El emisor mira lo que el receptor dice aceptar. Si no se anuncia nada, el
    control de congestion arranca conservador y la imagen sale blanda: justo lo
    que arruina la deteccion de los dedos. En una LAN sobra ancho de banda.
    """
    out: list[str] = []
    in_video = False
    placed = False
    for line in sdp.split("\r\n"):
        if line.startswith("m="):
            in_video = line.startswith("m=video")
            placed = False
        if in_video and not placed and out and out[-1].startswith("c="):
            out.append(f"b=AS:{kbps}")
            out.append(f"b=TIAS:{kbps * 1000}")
            placed = True
        if in_video and line.startswith("b="):
            continue
        out.append(line)
    return "\r\n".join(out)


class AirLinkServer:
    """Servidor HTTPS + senalizacion + receptor de video."""

    def __init__(self, cfg: AirLinkConfig) -> None:
        self.cfg = cfg
        if not cfg.token:
            cfg.token = make_token()
        self.token = cfg.token
        self.ip = certs.preferred_ip()

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner = None
        self._pc = None
        self._web_root = WEB_ROOT
        self._stop = threading.Event()

        # buzon de un frame, protegido por lock
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_t = 0.0
        self._frame_id = 0
        self._new_frame = threading.Event()

        # estado observable desde la interfaz
        self.running = False
        self.phone_connected = False
        self.error: str | None = None
        self.device = ""
        #: "user" (frontal) | "environment" (trasera) | "" si aún no lo sabemos
        self.facing = ""
        #: codec negociado ("H264", "VP8"...)
        self.codec = ""
        self.fps = 0.0
        self.mbps = 0.0
        #: lo fija el controlador; se aplica al decodificar
        self.mirror = True
        self.size: tuple[int, int] = (0, 0)
        self.frames_received = 0
        self.last_frame_at = 0.0

    # ---------------- datos para la interfaz ----------------
    @property
    def url(self) -> str:
        return f"https://{self.ip}:{self.cfg.port}/"

    @property
    def pair_url(self) -> str:
        return (f"https://{self.ip}:{self.cfg.port}/?host={self.ip}"
                f"&port={self.cfg.port}&token={self.token}")

    def new_token(self) -> str:
        self.token = make_token()
        self.cfg.token = self.token
        return self.token

    def status_text(self) -> str:
        if self.error:
            return self.error
        if not self.running:
            return "Servidor detenido"
        if self.phone_connected:
            w, h = self.size
            parts = [f"{w}×{h}"] if w else []
            if self.fps:
                parts.append(f"{self.fps:.0f} fps")
            if self.mbps:
                parts.append(f"{self.mbps:.1f} Mbps")
            if self.codec:
                parts.append(self.codec)
            return "Móvil conectado · " + " · ".join(parts) if parts \
                else "Móvil conectado"
        return "Esperando al móvil…"

    @property
    def quality_warning(self) -> str:
        """Aviso si la señal que llega no da para detectar los dedos bien."""
        if not self.phone_connected or self.frames_received < 60:
            return ""
        if self.size[0] and self.size[0] < 1200:
            return ("Poca resolución. Sube a 1080p en el móvil: por debajo de "
                    "eso los dedos se detectan con mucho ruido.")
        if self.fps and self.fps < 45:
            return ("Pocos fotogramas por segundo. Prueba a bajar la "
                    "resolución en el móvil para que suba a 60 fps.")
        if self.mbps and self.mbps < 4:
            return ("Bitrate bajo: la imagen llega comprimida y los dedos "
                    "pierden definición. Acerca el móvil al router.")
        return ""

    # ---------------- ciclo de vida ----------------
    def start(self) -> bool:
        if self.running:
            return True
        self.error = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="AirLink",
                                        daemon=True)
        self._thread.start()
        # esperamos a que el servidor este escuchando (o falle)
        for _ in range(100):
            if self.running or self.error:
                break
            time.sleep(0.05)
        return self.running

    def stop(self) -> None:
        if not self.running and self._thread is None:
            return
        # El cierre se hace DENTRO de _serve, cuando el bucle ve la bandera. Si
        # se lanzara aparte con run_coroutine_threadsafe, el bucle podria
        # cerrarse antes y dejar la tarea a medias.
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None
        self.running = False
        self.phone_connected = False

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except Exception as exc:  # pragma: no cover - depende del entorno
            self.error = f"AirLink no pudo arrancar: {exc}"
            log.exception("Fallo en el servidor de AirLink")
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            self._loop = None
            self.running = False

    async def _serve(self) -> None:
        from aiohttp import web

        app = web.Application()
        app.router.add_get("/signal", self._handle_signal)
        app.router.add_get("/health", self._handle_health)

        root = Path(self.cfg.web_root) if self.cfg.web_root else WEB_ROOT
        self._web_root = root
        if root.is_dir():
            # OJO: la raiz necesita su propia ruta. El manejador de estaticos,
            # con el listado desactivado, responde 403 a "/" en vez de servir
            # el index — y el QR apunta justo ahi.
            app.router.add_get("/", self._handle_index)
            app.router.add_get("/index.html", self._handle_index)
            app.router.add_static("/", str(root), show_index=False,
                                  follow_symlinks=False)
        else:
            log.warning("No se encuentra la web de AirLink en %s", root)
            app.router.add_get("/", self._handle_missing_web)

        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        self._runner = runner

        site = web.TCPSite(runner, host="0.0.0.0", port=self.cfg.port,
                           ssl_context=certs.ssl_context())
        await site.start()
        self.running = True
        log.info("AirLink escuchando en %s", self.url)

        try:
            while not self._stop.is_set():
                await asyncio.sleep(0.2)
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        await self._close_peer()
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception:
                pass
            self._runner = None

    # ---------------- HTTP ----------------
    async def _handle_health(self, _request):
        from aiohttp import web

        return web.json_response({
            "app": "airtouch-airlink",
            "connected": self.phone_connected,
            "frames": self.frames_received,
        })

    async def _handle_index(self, _request):
        from aiohttp import web

        index = self._web_root / "index.html"
        if not index.is_file():
            return await self._handle_missing_web(_request)
        # sin cache: si actualizo la web, el movil debe verlo al recargar
        return web.FileResponse(index, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
        })

    async def _handle_missing_web(self, _request):
        from aiohttp import web

        return web.Response(
            status=500, content_type="text/plain; charset=utf-8",
            text="No se encuentra la carpeta airlink-web junto a AirTouch.")

    # ---------------- senalizacion ----------------
    async def _handle_signal(self, request):
        from aiohttp import web

        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)

        token = request.query.get("token", "")
        if not secrets.compare_digest(token, self.token):
            log.warning("Conexion rechazada: token incorrecto")
            await ws.send_json({"type": "error",
                                "message": "Código de emparejamiento incorrecto"})
            await ws.close()
            return ws

        log.info("Móvil emparejado desde %s", request.remote)
        await ws.send_json({"type": "welcome", "name": "AirTouch"})

        try:
            async for msg in ws:
                if msg.type != web.WSMsgType.TEXT:
                    continue
                try:
                    data = msg.json()
                except Exception:
                    continue
                await self._on_message(ws, data)
        finally:
            await self._close_peer()
            self.phone_connected = False
            log.info("Móvil desconectado")
        return ws

    async def _on_message(self, ws, data: dict) -> None:
        kind = data.get("type")
        if kind == "hello":
            self.device = str(data.get("device", ""))[:120]
            self.facing = str(data.get("camera", ""))[:20]
            log.info("Móvil dice: cámara %s", self.facing or "?")
        elif kind == "offer":
            await self._answer(ws, data.get("sdp", ""))
        elif kind == "stats":
            try:
                self.mbps = float(data.get("mbps") or 0.0)
            except (TypeError, ValueError):
                pass
        elif kind == "ice":
            await self._add_ice(data.get("candidate"))
        elif kind == "bye":
            await self._close_peer()

    async def _answer(self, ws, sdp: str) -> None:
        from aiortc import RTCPeerConnection, RTCSessionDescription

        await self._close_peer()
        pc = RTCPeerConnection()
        self._pc = pc

        @pc.on("track")
        def _on_track(track):                      # noqa: ANN001
            if track.kind != "video":
                return
            log.info("Pista de vídeo recibida")
            self.phone_connected = True
            asyncio.ensure_future(self._drain(track))

        @pc.on("connectionstatechange")
        async def _on_state():
            log.info("WebRTC: %s", pc.connectionState)
            if pc.connectionState in ("failed", "closed"):
                self.phone_connected = False

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
        self._prefer_h264(pc)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        final_sdp = _with_bandwidth(pc.localDescription.sdp)
        self.codec = self._codec_of(final_sdp)
        log.info("Códec de vídeo negociado: %s", self.codec or "?")
        await ws.send_json({"type": "answer", "sdp": final_sdp})

    @staticmethod
    def _prefer_h264(pc) -> None:
        """Pone H.264 el primero de la lista de codecs.

        El iPhone codifica H.264 por hardware; VP8 lo hace por software, con
        peor calidad a igual bitrate y calentando el telefono. Si no se dice
        nada, la negociacion puede acabar en VP8.
        """
        try:
            from aiortc import RTCRtpReceiver

            caps = RTCRtpReceiver.getCapabilities("video")
            if caps is None:
                return
            h264 = [c for c in caps.codecs if "h264" in c.mimeType.lower()]
            if not h264:
                return
            rest = [c for c in caps.codecs if "h264" not in c.mimeType.lower()]
            for t in pc.getTransceivers():
                if t.kind == "video":
                    t.setCodecPreferences(h264 + rest)
        except Exception as exc:
            log.debug("No se pudo priorizar H.264: %s", exc)

    @staticmethod
    def _codec_of(sdp: str) -> str:
        """Nombre del codec negociado, leyendo el SDP."""
        pt = None
        for line in sdp.split("\r\n"):
            if line.startswith("m=video"):
                parts = line.split()
                if len(parts) > 3:
                    pt = parts[3]
            elif pt and line.startswith(f"a=rtpmap:{pt} "):
                return line.split(" ", 1)[1].split("/")[0]
        return ""

    async def _add_ice(self, candidate: dict | None) -> None:
        if not candidate or self._pc is None:
            return
        try:
            from aiortc import RTCIceCandidate
            from aiortc.sdp import candidate_from_sdp

            raw = candidate.get("candidate", "")
            if not raw:
                return
            ice = candidate_from_sdp(raw.split(":", 1)[1]
                                     if raw.startswith("candidate:") else raw)
            ice.sdpMid = candidate.get("sdpMid")
            ice.sdpMLineIndex = candidate.get("sdpMLineIndex")
            await self._pc.addIceCandidate(ice)
            _ = RTCIceCandidate
        except Exception as exc:
            log.debug("Candidato ICE descartado: %s", exc)

    async def _drain(self, track) -> None:
        """Lee frames de la pista y los deja en el buzon."""
        import av  # noqa: F401  (lo usa aiortc por dentro)

        while True:
            try:
                frame = await track.recv()
            except Exception:
                break
            try:
                img = frame.to_ndarray(format="bgr24")
            except Exception:
                continue
            if self.mirror:
                # el volteo se hace aqui, no en el movil: asi el video viaja
                # tal cual lo capta la camara y solo se invierte una vez
                img = img[:, ::-1].copy()
            with self._lock:
                self._frame = img
                self._frame_t = time.perf_counter()
                self._frame_id += 1
                self.size = (img.shape[1], img.shape[0])
            self.frames_received += 1
            now = time.perf_counter()
            # los fps se miden aqui, que es donde llegan los frames de verdad.
            # El bitrate lo manda el movil: solo el emisor sabe cuanto ocupa
            # el video comprimido, un frame ya decodificado no lo dice.
            if self.last_frame_at:
                dt = now - self.last_frame_at
                if dt > 0:
                    inst = 1.0 / dt
                    self.fps = inst if not self.fps else self.fps * 0.9 + inst * 0.1
            self.last_frame_at = now
            self._new_frame.set()
        self.phone_connected = False

    async def _close_peer(self) -> None:
        if self._pc is not None:
            try:
                await self._pc.close()
            except Exception:
                pass
            self._pc = None

    # ---------------- consumo desde el hilo de vision ----------------
    def read(self, timeout: float = 0.5):
        """Igual que CaptureThread.read: (frame, timestamp, id)."""
        if not self._new_frame.wait(timeout):
            return None, 0.0, -1
        with self._lock:
            self._new_frame.clear()
            if self._frame is None:
                return None, 0.0, -1
            return self._frame, self._frame_t, self._frame_id

    def snapshot(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def qr_png(self, scale: int = 8, dark: str = "#000000",
               light: str = "#ffffff") -> bytes:
        """QR de emparejamiento en PNG. Qt lo carga con loadFromData()."""
        import io

        import segno

        buf = io.BytesIO()
        segno.make(self.pair_url, error="m").save(
            buf, kind="png", scale=scale, border=2, dark=dark, light=light)
        return buf.getvalue()
