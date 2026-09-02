"""Configuracion persistente de AirTouch.

Se guarda en %APPDATA%\AirTouch\config.json. Todo son dataclasses para que
el resto del codigo trabaje con atributos y no con diccionarios sueltos.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict, fields, is_dataclass
from pathlib import Path
from typing import Any


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    d = Path(base) / "AirTouch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _bundle_root() -> Path:
    """Carpeta donde estan los datos que viajan con el programa.

    Compilado, PyInstaller los deja junto al ejecutable (en ``_internal``) y lo
    apunta con ``sys._MEIPASS``. Ejecutando desde el codigo, es la raiz del
    proyecto.
    """
    if _is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _bundle_root()
MODELS_DIR = PROJECT_ROOT / "models"
# Los registros van a AppData cuando esta compilado: la carpeta del programa
# puede estar en un sitio sin permiso de escritura (Archivos de programa).
LOGS_DIR = (app_data_dir() / "logs") if _is_frozen() else (PROJECT_ROOT / "logs")
CONFIG_PATH = app_data_dir() / "config.json"


@dataclass
class CameraConfig:
    source_type: str = "airlink"        # "airlink" | "index" | "url"
    index: int = 0
    url: str = ""
    backend: str = "auto"               # "auto" | "dshow" | "msmf"
    width: int = 1280
    height: int = 720
    fps: int = 60
    # Espejo: que mover la mano a la derecha lleve el puntero a la derecha.
    #   "auto"  -> lo decide la cámara que uses en el móvil (frontal = espejo)
    #   "off"   -> nunca invertir
    #   "on"    -> invertir siempre
    mirror_mode: str = "auto"
    mirror: bool = True                 # valor efectivo, derivado de mirror_mode
    friendly_name: str = ""
    # aparta la ventana de iVCam fuera de la pantalla mientras el motor corre.
    # No se minimiza: minimizarla haria que dejase de retransmitir.
    hide_source_window: bool = True


@dataclass
class AirLinkConfig:
    """Nuestra propia camara por WiFi, para no depender de iVCam."""

    enabled: bool = True
    port: int = 8443
    # El codigo se guarda: si cambiara en cada arranque, un movil que recuerda
    # el emparejamiento (o la app en la pantalla de inicio) llegaria siempre
    # con el codigo viejo y seria rechazado. Se renueva solo si tu lo pides.
    token: str = ""
    web_root: str = ""                  # vacio = la carpeta airlink-web del proyecto
    auto_start: bool = True             # levantar el servidor con el motor


@dataclass
class VisionConfig:
    max_hands: int = 2
    min_hand_detection_confidence: float = 0.5
    min_hand_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    face_enabled: bool = True
    # Se procesa a esta anchura cuando hay que mirar el frame entero.
    downscale_width: int = 768
    # Seguimiento por recorte: una vez localizada la mano, solo se analiza su
    # entorno. Es mas rapido (menos pixeles) y ademas MAS preciso, porque la
    # mano ocupa toda la entrada del modelo en vez de una esquina.
    roi_enabled: bool = True
    roi_size: int = 384                 # lado del recorte que se envia al modelo
    roi_margin: float = 0.85            # cuanto se agranda la caja de la mano
    roi_max_misses: int = 6             # frames sin mano antes de volver al full
    # La cara solo hace falta si algo la usa; si no, es tiempo tirado.
    face_every_n_frames: int = 6


@dataclass
class FilterConfig:
    min_cutoff: float = 0.60            # One Euro: menos = mas suave, mas lag
    # OJO: beta es el que manda en el temblor. Multiplica la velocidad, y el
    # ruido parece velocidad, asi que un beta alto se realimenta y deja pasar
    # mas ruido. Medido: 0.06 -> 17 px de deriva; 0.02 -> 10 px, con el mismo
    # retardo. No subirlo sin volver a medir.
    beta: float = 0.020
    d_cutoff: float = 1.0               # subirlo empeora mucho el temblor
    # Extrapolacion hacia delante para compensar la latencia de la camara.
    # Desactivada por defecto: medido, aporta poco retardo menos y en cambio
    # mete picos de temblor. Se puede activar en Ajustes si el puntero se
    # siente pesado.
    prediction_ms: float = 0.0
    prediction_max_px: float = 46.0
    # la prediccion no entra hasta que te mueves de verdad (px/s)
    prediction_min_speed: float = 380.0
    prediction_full_speed: float = 1100.0
    pinch_smoothing: float = 0.45       # EMA sobre la distancia de pinch


@dataclass
class MappingConfig:
    mode: str = "absolute"              # "absolute" | "relative"
    # region activa dentro del encuadre de la camara (0..1)
    region_x0: float = 0.15
    region_y0: float = 0.15
    region_x1: float = 0.85
    region_y1: float = 0.85
    # homografia de calibracion (3x3 aplanada) o None
    homography: list[float] | None = None
    relative_gain: float = 2.2
    relative_accel: float = 1.6
    dead_zone_px: float = 1.0
    monitor: str = "primary"            # "primary" | "virtual"


@dataclass
class GestureConfig:
    # pinch (histeresis: cierra por debajo de _on, abre por encima de _off)
    pinch_on: float = 0.34
    # muy pegado al de cierre: un umbral de apertura alto hace que sigas
    # "clicando" aunque ya hayas separado los dedos
    pinch_off: float = 0.40
    click_max_ms: int = 340
    # El scroll no se arma hasta pasado este tiempo con el pinch mantenido, de
    # modo que un clic no pueda convertirse en scroll jamas.
    scroll_arm_ms: int = 360
    # El recorrido se mide con la PALMA, no con la yema: al pinzar el dedo se
    # mueve solo. Y en umbrales generosos: un centimetro de mano son ~200 px de
    # pantalla, asi que un margen pequeno convierte cualquier clic en scroll.
    click_max_travel_px: float = 190.0
    drag_min_travel_px: float = 190.0
    # ventana muerta al empezar el pinch: ningun modo puede cambiar todavia
    pinch_grace_ms: int = 130
    # que hace pinch + arrastrar sobre contenido normal
    pinch_drag_mode: str = "scroll"     # "scroll" | "drag"
    scroll_gain: float = 1.9
    scroll_invert: bool = False
    hscroll_enabled: bool = True
    # zoom a dos manos
    zoom_enabled: bool = True
    zoom_gain: float = 1.0
    zoom_min_delta_px: float = 12.0
    # catapulta -> clic derecho.
    # El gesto: indice curvado hacia atras y apoyado contra el pulgar (cerca,
    # pero poco tiempo), y salida rapida hacia delante hasta quedar recto.
    flick_enabled: bool = True
    flick_load_curl: float = 0.75       # dedo cargado (curvado) por debajo de esto
    flick_contact_ratio: float = 0.60   # y ademas cerca del pulgar
    flick_release_curl: float = 0.80    # liberado por encima de esto
    flick_min_load_ms: int = 60
    flick_max_contact_ms: int = 900     # mas tiempo cargado = no era catapulta
    flick_max_release_ms: int = 260
    flick_min_speed: float = 1.5        # unidades de extension por segundo
    flick_min_delta: float = 0.20       # cuanto tiene que estirarse
    # el clic izquierdo espera un pelin por si era una catapulta
    flick_guard_ms: int = 130
    # gestion de ventanas
    window_chrome_enabled: bool = True
    window_grab_band_px: int = 46       # banda bajo el borde inferior
    window_corner_px: int = 58          # zona de la esquina inferior derecha
    window_min_size: int = 240
    # teclado virtual
    keyboard_enabled: bool = True
    key_dwell_ms: int = 0               # 0 = solo por pinch
    key_repeat_ms: int = 320


@dataclass
class SafetyConfig:
    control_enabled: bool = False       # MODO SEGURO por defecto
    pause_on_no_face: bool = True
    no_face_timeout_ms: int = 3000
    mouse_override: bool = True         # mover el raton fisico cede el control
    mouse_override_px: int = 30
    open_palm_pause: bool = True
    open_palm_ms: int = 1400
    esc_hold_ms: int = 800


@dataclass
class UIConfig:
    theme: str = "system"               # "system" | "light" | "dark"
    reduce_motion: bool = False
    # backdrop del sistema. Apagado: en Windows 10 falla y la direccion no
    # depende de el, el lienzo pintado es el camino principal
    mica: bool = False
    overlay_enabled: bool = True
    show_cursor: bool = True
    show_hud: bool = True
    show_debug_skeleton: bool = False
    accent: str = "#FFFFFF"
    overlay_opacity: float = 0.92


@dataclass
class AppConfig:
    first_run: bool = True
    start_with_windows: bool = False
    start_minimized: bool = False
    language: str = "es"
    version: int = 2


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    airlink: AirLinkConfig = field(default_factory=AirLinkConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    filter: FilterConfig = field(default_factory=FilterConfig)
    mapping: MappingConfig = field(default_factory=MappingConfig)
    gestures: GestureConfig = field(default_factory=GestureConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    app: AppConfig = field(default_factory=AppConfig)

    # ---------------- persistencia ----------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: Path | None = None) -> None:
        p = path or CONFIG_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        p = path or CONFIG_PATH
        cfg = cls()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                _merge(cfg, data)
            except Exception:
                # config corrupta: se ignora y se usan valores por defecto
                pass
        cfg._migrate()
        return cfg

    def _migrate(self) -> None:
        """Corrige valores guardados por versiones anteriores."""
        g = self.gestures
        # las primeras versiones dejaban una banda de histeresis enorme, y con
        # ella el pinch seguia contando como cerrado con los dedos ya abiertos
        g.pinch_off = min(max(g.pinch_off, g.pinch_on + 0.03), g.pinch_on + 0.14)

        # v1 -> v2: se abandona iVCam en favor de AirLink. Sin esto, una
        # instalacion antigua seguiria abriendo la webcam del sistema y
        # mostrando el "Please run iVCam" de siempre.
        # el codigo de emparejamiento se genera aqui, antes del primer guardado:
        # si se creara mas tarde no llegaria a persistirse y cambiaria en cada
        # arranque, rompiendo los moviles que lo recuerdan
        if not self.airlink.token:
            import secrets

            alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
            self.airlink.token = "".join(secrets.choice(alphabet) for _ in range(6))

        if self.app.version < 2:
            if self.camera.source_type == "index":
                self.camera.source_type = "airlink"
            self.app.version = 2

    def reset_section(self, name: str) -> None:
        f = {fl.name: fl for fl in fields(self)}[name]
        setattr(self, name, f.default_factory())  # type: ignore[misc]


def _merge(obj: Any, data: dict[str, Any]) -> None:
    """Aplica un dict sobre una dataclass ignorando claves desconocidas."""
    known = {fl.name: fl for fl in fields(obj)}
    for key, value in data.items():
        if key not in known:
            continue
        current = getattr(obj, key)
        if is_dataclass(current) and isinstance(value, dict):
            _merge(current, value)
        else:
            setattr(obj, key, value)
