"""Que ajustes hay, donde vive cada uno y que se nota al tocarlo (8.7).

Aqui no se construye ni un widget: esto es la **declaracion** de las ocho
secciones de Ajustes. ``panel.py`` la lee y fabrica los mandos. Separarlo tiene
un motivo practico: la lista de ajustes cambia cada vez que el motor gana una
opcion, y no queria que anyadir una fila obligase a tocar la maquetacion.

Tres cosas que hay que entender antes de anyadir una fila:

* **La ruta es la verdad.** ``"filter.min_cutoff"`` apunta a un campo real de
  ``airtouch/config.py``. De la ruta salen el valor, el valor por defecto (de
  ``_DEFECTOS``, un ``Config`` recien hecho) y por tanto el punto de acento de
  "modificado". No hay forma de declarar un ajuste que no exista.
* **La pista se pinta en UNA linea.** ``SettingRow`` no parte el texto de
  ``hint``: lo que no cabe se corta. Con un deslizador el mando se lleva media
  fila, asi que la pista tiene sitio para unos 65 caracteres y ni uno mas. Lo
  que hay que explicar de verdad va al **pie de consecuencia** de la seccion,
  que si se compone con ``tipo.Parrafo`` y respira.
* **El pie dice que notaras tu, no que hace el parametro.** Es el requisito
  central del apartado 8.7 y la diferencia entre unos ajustes y una lista de
  variables. "Bajar el corte suaviza el puntero pero anyade unos 20 ms de
  retardo", no "min_cutoff: frecuencia de corte del filtro One Euro".

**Ajustes que existen en ``config.py`` y NO se exponen, y por que.** No es un
olvido; ensenyar un mando que no hace nada es peor que no ensenyarlo:

* ``camera.mirror`` — no es un ajuste, es el valor derivado de ``mirror_mode``
  que escribe ``Controller`` cuando el movil dice que camara esta usando.
* ``camera.friendly_name`` — lo rellena el asistente con el nombre de la fuente
  que encontro; escribirlo a mano no cambia nada.
* ``safety.control_enabled`` — es el interruptor del Nucleo del panel (8.9).
  Con dos duenyos acabaria desincronizado con la bandeja y con el atajo de Esc.
* ``app.first_run``, ``app.version`` — estado interno de la migracion.
* ``app.language`` — un solo idioma; una lista de una opcion no es un ajuste.
* ``ui.accent``, ``ui.mica``, ``ui.overlay_opacity``,
  ``ui.show_debug_skeleton``, ``gestures.key_dwell_ms`` — **nadie los lee**.
  Estan en la configuracion y no hay una sola linea del motor ni de la interfaz
  que los consulte (comprobado con una busqueda por todo el arbol). Un mando
  para ellos seria un mando que miente.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...config import Config

__all__ = [
    "Espec", "Grupo", "Seccion", "SECCIONES", "leer", "escribir", "defecto",
    "coherencia", "iguales",
]

#: Los valores de fabrica. Un ``Config()`` pelado, sin ``load`` ni ``_migrate``:
#: lo unico que se le pide es que cada campo tenga su default de dataclass.
_DEFECTOS = Config()

#: Tolerancia para decidir si un flotante sigue en su valor por defecto. Por
#: debajo del paso mas fino de cualquier deslizador de aqui (0.002 en beta).
_EPS = 5e-4


# --------------------------------------------------------------------------- #
# acceso por ruta
# --------------------------------------------------------------------------- #

def _partes(ruta: str) -> tuple[str, str]:
    grupo, _, campo = ruta.partition(".")
    return grupo, campo


def leer(cfg: Config, ruta: str) -> Any:
    grupo, campo = _partes(ruta)
    return getattr(getattr(cfg, grupo), campo)


def escribir(cfg: Config, ruta: str, valor: Any) -> None:
    grupo, campo = _partes(ruta)
    setattr(getattr(cfg, grupo), campo, valor)


def defecto(ruta: str) -> Any:
    return leer(_DEFECTOS, ruta)


def iguales(a: Any, b: Any) -> bool:
    """Comparacion que no se cree que 0.6000000000000001 sea otro numero."""
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= _EPS
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(iguales(x, y) for x, y in zip(a, b))
    return a == b


# --------------------------------------------------------------------------- #
# una fila
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Espec:
    """Una fila de ajustes. ``clase`` decide que mando le pone el panel."""

    ruta: str
    label: str
    clase: str = "slider"       # slider | toggle | opciones | texto | accion
    hint: str = ""
    keywords: str = ""
    senal: str = "changed"      # changed | camara | tema | movimiento
    lo: float = 0.0
    hi: float = 1.0
    paso: float = 0.0
    decimales: int = 2
    unidad: str = ""
    entero: bool = False
    etiquetas: tuple[str, ...] = ()
    valores: tuple[Any, ...] = ()
    par: str = ""               # segunda ruta, para un valor de dos campos
    placeholder: str = ""
    boton: str = ""
    variante: str = "normal"
    accion: str = ""            # metodo del panel que dispara el boton
    activo_si: str = ""         # "ruta" (cierto) o "ruta=valor"

    # -- valor --------------------------------------------------------------
    def valor(self, cfg: Config) -> Any:
        if self.par:
            return (leer(cfg, self.ruta), leer(cfg, self.par))
        return leer(cfg, self.ruta)

    def poner(self, cfg: Config, valor: Any) -> None:
        if self.par:
            escribir(cfg, self.ruta, valor[0])
            escribir(cfg, self.par, valor[1])
        else:
            escribir(cfg, self.ruta, valor)

    def por_defecto(self) -> Any:
        if self.par:
            return (defecto(self.ruta), defecto(self.par))
        return defecto(self.ruta)

    def modificada(self, cfg: Config) -> bool:
        """El punto de acento de 4 px del borde izquierdo (8.7)."""
        if self.clase == "accion":
            return False
        return not iguales(self.valor(cfg), self.por_defecto())

    def restablecer(self, cfg: Config) -> None:
        if self.clase != "accion":
            self.poner(cfg, self.por_defecto())

    # -- dependencias -------------------------------------------------------
    def habilitada(self, cfg: Config) -> bool:
        """Una fila que depende de otra se apaga en vez de desaparecer.

        Esconderla haria saltar la lista cada vez que cambias la fuente de
        video, y el usuario perderia el sitio. Apagada sigue diciendo que
        existe y por que ahora no aplica.
        """
        if not self.activo_si:
            return True
        ruta, sep, esperado = self.activo_si.partition("=")
        actual = leer(cfg, ruta)
        if not sep:
            return bool(actual)
        return str(actual) == esperado

    # -- buscador -----------------------------------------------------------
    def texto_busqueda(self) -> str:
        return f"{self.label} {self.hint} {self.keywords} {self.ruta}"


def _sl(ruta: str, label: str, lo: float, hi: float, **kw: Any) -> Espec:
    return Espec(ruta, label, "slider", lo=lo, hi=hi, **kw)


def _tg(ruta: str, label: str, **kw: Any) -> Espec:
    return Espec(ruta, label, "toggle", **kw)


def _op(ruta: str, label: str, etiquetas: tuple[str, ...],
        valores: tuple[Any, ...], **kw: Any) -> Espec:
    return Espec(ruta, label, "opciones", etiquetas=etiquetas,
                 valores=valores, **kw)


def _tx(ruta: str, label: str, **kw: Any) -> Espec:
    return Espec(ruta, label, "texto", **kw)


def _ac(label: str, boton: str, accion: str, **kw: Any) -> Espec:
    return Espec("", label, "accion", boton=boton, accion=accion, **kw)


# --------------------------------------------------------------------------- #
# grupos y secciones
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Grupo:
    """Un bloque con rotulo dentro de una seccion.

    ``instrumento`` es el injerto de Pulso del apartado 8.7: el grupo ancla
    arriba el aparato con el que se mide lo que estas tocando, y ese aparato no
    se va de la pantalla mientras arrastras el deslizador.
    """

    titulo: str
    filas: tuple[Espec, ...]
    instrumento: str = ""       # "" | "pinch" | "puntero"


@dataclass(frozen=True)
class Seccion:
    nombre: str
    titulo: str
    grupos: tuple[Grupo, ...]
    pie: str
    completas: tuple[str, ...] = ()

    @property
    def filas(self) -> tuple[Espec, ...]:
        return tuple(f for g in self.grupos for f in g.filas)

    def restablecer(self, cfg: Config) -> None:
        """Devuelve la seccion a fabrica.

        Las secciones que poseen entera una dataclass de ``config.py`` usan
        ``Config.reset_section``, que es el contrato de la especificacion. Las
        otras no pueden: *Gestos* y *Teclado* se reparten ``GestureConfig``, y
        *Puntero* comparte ``FilterConfig`` con *Gestos* y ``MappingConfig`` con
        *Avanzado*. Ahi se restablecen campo a campo, que es ademas lo que el
        usuario espera de un boton que dice "seccion": vuelven las filas que
        esta viendo y ninguna mas.
        """
        for nombre in self.completas:
            cfg.reset_section(nombre)
        for fila in self.filas:
            grupo, _ = _partes(fila.ruta)
            if grupo and grupo not in self.completas:
                fila.restablecer(cfg)
        coherencia(cfg)

    def modificadas(self, cfg: Config) -> int:
        return sum(1 for f in self.filas if f.modificada(cfg))


# --------------------------------------------------------------------------- #
# reglas que la configuracion se garantiza a si misma
# --------------------------------------------------------------------------- #

def coherencia(cfg: Config) -> tuple[str, ...]:
    """Aplica los invariantes de ``Config._migrate`` y devuelve que ha tocado.

    El panel los tiene que aplicar tambien, y no "por si acaso": la banda de
    histeresis del pinch es la que se pago con el fallo de que seguias clicando
    con los dedos ya abiertos, y la region activa con los ejes cruzados manda el
    puntero al reves. Se corrige al escribir, y la fila corregida se recarga
    para que el numero de la pantalla sea el numero que se ha guardado.
    """
    tocadas: list[str] = []

    g = cfg.gestures
    off = min(max(g.pinch_off, g.pinch_on + 0.03), g.pinch_on + 0.14)
    if not iguales(off, g.pinch_off):
        g.pinch_off = round(off, 3)
        tocadas.append("gestures.pinch_off")

    # la region activa necesita un lado de al menos 0.10, y en el orden bueno
    m = cfg.mapping
    for bajo, alto in (("region_x0", "region_x1"), ("region_y0", "region_y1")):
        a, b = getattr(m, bajo), getattr(m, alto)
        if b - a < 0.10:
            nb = min(1.0, a + 0.10)
            na = max(0.0, nb - 0.10)
            if not iguales(na, a):
                setattr(m, bajo, round(na, 3))
                tocadas.append(f"mapping.{bajo}")
            if not iguales(nb, b):
                setattr(m, alto, round(nb, 3))
                tocadas.append(f"mapping.{alto}")

    return tuple(tocadas)


# --------------------------------------------------------------------------- #
# las ocho secciones
# --------------------------------------------------------------------------- #

_ASPECTO = Seccion(
    "aspecto", "Aspecto", (
        Grupo("Tema", (
            _op("ui.theme", "Tema",
                ("Auto", "Claro", "Oscuro"), ("system", "light", "dark"),
                senal="tema", hint="El automático sigue al de Windows",
                keywords="tema color claro oscuro noche apariencia"),
            _tg("ui.reduce_motion", "Movimiento reducido",
                senal="movimiento",
                hint="Acorta todas las animaciones al 35 %",
                keywords="animacion movimiento accesibilidad mareo"),
        )),
        Grupo("Sobre el escritorio", (
            _tg("ui.overlay_enabled", "Capa sobre el escritorio",
                hint="Cursor, cápsula de estado, barras y teclado",
                keywords="overlay superposicion capa escritorio"),
            _tg("ui.show_cursor", "Cursor propio",
                hint="El punto luminoso que sigue a tu índice",
                keywords="cursor puntero punto raton"),
            _tg("ui.show_hud", "Cápsula de estado",
                hint="La pastilla que dice en qué modo estás",
                keywords="hud capsula pastilla modo estado"),
        )),
        Grupo("Arranque", (
            _tg("app.start_with_windows", "Arrancar con Windows",
                keywords="inicio arranque windows automatico sesion"),
            _tg("app.start_minimized", "Empezar minimizado",
                hint="Directo a la bandeja, sin abrir el panel",
                keywords="minimizado bandeja tray oculto"),
        )),
    ),
    "Nada de esto toca al motor: puedes cambiarlo con el control activo y sin "
    "perder el seguimiento ni un fotograma. Apagar la capa sobre el escritorio "
    "no apaga los gestos, solo deja de dibujarlos: el puntero seguirá moviendo "
    "cosas aunque tú no lo veas.",
    completas=("ui",),
)


_CAMARA = Seccion(
    "camara", "Cámara", (
        Grupo("Fuente", (
            _op("camera.source_type", "Fuente",
                ("AirLink", "Webcam", "URL"), ("airlink", "index", "url"),
                senal="camara",
                hint="AirLink usa tu móvil por WiFi, sin apps de terceros",
                keywords="fuente airlink webcam url movil iphone ivcam"),
            _sl("camera.index", "Índice de la webcam", 0, 10, paso=1,
                decimales=0, entero=True, senal="camara",
                activo_si="camera.source_type=index",
                keywords="webcam indice numero camara sistema"),
            _tx("camera.url", "Dirección del stream", senal="camara",
                placeholder="http://…", activo_si="camera.source_type=url",
                keywords="url stream direccion http rtsp red"),
            _op("camera.backend", "Motor de captura",
                ("Auto", "DirectShow", "Media Foundation"),
                ("auto", "dshow", "msmf"), senal="camara",
                hint="Cámbialo si la webcam no abre o va a tirones",
                keywords="backend dshow msmf captura driver windows"),
        )),
        Grupo("Encuadre", (
            _op("camera.width", "Resolución",
                ("640×360", "960×540", "1280×720", "1920×1080"),
                ((640, 360), (960, 540), (1280, 720), (1920, 1080)),
                par="camera.height", senal="camara",
                keywords="resolucion tamano pixeles hd calidad"),
            _op("camera.fps", "Fotogramas por segundo",
                ("30", "60"), (30, 60), senal="camara",
                keywords="fps fotogramas velocidad fluidez"),
            _op("camera.mirror_mode", "Modo espejo",
                ("Auto", "No invertido", "Invertido"), ("auto", "off", "on"),
                hint="En Auto lo decide la cámara del móvil que uses",
                keywords="espejo invertir mirror reves lateral"),
            _tg("camera.hide_source_window", "Apartar la ventana de la fuente",
                hint="La saca de la pantalla; minimizarla la haría parar",
                keywords="ivcam ventana ocultar apartar estorba"),
        )),
    ),
    "Más resolución no da más puntería: el modelo recorta la mano y la analiza "
    "a 384 px la mire como la mire. Lo que sí vas a notar al subirla es más "
    "latencia y más ventilador. Cambiar la fuente o el encuadre reabre la "
    "cámara, así que el seguimiento se corta un segundo.",
    completas=("camera",),
)


_PUNTERO = Seccion(
    "puntero", "Puntero", (
        Grupo("Suavizado", (
            _sl("filter.min_cutoff", "Corte del suavizado", 0.30, 4.00,
                paso=0.05,
                hint="Menos corte = más estable y con más retardo",
                keywords="suavizado corte cutoff estable temblor retardo lag"),
            _sl("filter.beta", "Reactividad al movimiento", 0.000, 0.060,
                paso=0.002, decimales=3,
                hint="Medido: 0,020 deja 10 px de deriva; 0,060 sube a 17",
                keywords="beta reactividad velocidad deriva temblor ruido"),
            _sl("filter.prediction_ms", "Compensar latencia", 0, 40, paso=1,
                decimales=0, unidad=" ms",
                hint="Adelanta el puntero hacia donde vas. 0 = apagado",
                keywords="prediccion latencia adelanto retardo pesado"),
        ), instrumento="puntero"),
        Grupo("Alcance", (
            _op("mapping.mode", "Modo",
                ("Apuntar", "Como un ratón"), ("absolute", "relative"),
                hint="Apuntar va a donde señalas; el otro desplaza",
                keywords="absoluto relativo modo apuntar raton"),
            _op("mapping.monitor", "Monitores",
                ("Principal", "Todos"), ("primary", "virtual"),
                keywords="monitor pantalla alcance multiple virtual"),
            _sl("mapping.relative_gain", "Ganancia", 0.8, 5.0, paso=0.05,
                activo_si="mapping.mode=relative",
                hint="Cuánta pantalla recorre un centímetro de mano",
                keywords="ganancia sensibilidad relativo velocidad"),
            _sl("mapping.relative_accel", "Aceleración", 1.0, 3.0, paso=0.05,
                activo_si="mapping.mode=relative",
                hint="Mover rápido llega más lejos que mover despacio",
                keywords="aceleracion relativo curva"),
            _sl("mapping.dead_zone_px", "Zona muerta", 0.0, 6.0, paso=0.5,
                decimales=1, unidad=" px",
                hint="Por debajo de esto el puntero no se mueve",
                keywords="zona muerta deadzone quieto microtemblor"),
        )),
        Grupo("Calibración", (
            _ac("Calibrar las cuatro esquinas", "Calibrar", "calibrar",
                hint="Corrige el ángulo y el gran angular del móvil",
                keywords="calibrar esquinas homografia angulo"),
            _ac("Calibración personalizada", "Borrar", "borrar_calibracion",
                variante="ghost",
                keywords="calibracion borrar quitar homografia"),
        )),
    ),
    "Bajar el corte suaviza el puntero pero añade retardo: con 0,60 la mano "
    "quieta arrastra unos 265 ms, y a 500 px/s el propio filtro lo baja a 15. "
    "La reactividad es lo que devuelve ese retardo cuando te mueves, a cambio "
    "de dejar pasar más temblor: el ruido se parece a la velocidad, así que un "
    "valor alto se realimenta. El medidor de arriba enseña las dos mitades del "
    "trato mientras arrastras.",
)


_GESTOS = Seccion(
    "gestos", "Gestos", (
        Grupo("Pinch", (
            _sl("gestures.pinch_on", "Umbral de cierre", 0.15, 0.60,
                paso=0.01,
                hint="Por debajo de esto, el pinch cuenta como cerrado",
                keywords="pinch pellizco cierre umbral clic dedos"),
            _sl("gestures.pinch_off", "Umbral de apertura", 0.18, 0.74,
                paso=0.01,
                hint="Siempre entre 0,03 y 0,14 por encima del cierre",
                keywords="pinch apertura umbral histeresis soltar"),
            _sl("filter.pinch_smoothing", "Suavizado del pinch", 0.0, 0.90,
                paso=0.05,
                hint="Estabiliza la distancia medida entre los dedos",
                keywords="pinch suavizado ema estable parpadeo"),
            _sl("gestures.pinch_grace_ms", "Ventana muerta al pinzar",
                0, 400, paso=10, decimales=0, unidad=" ms",
                hint="Mientras dura, ningún modo puede cambiar",
                keywords="gracia ventana muerta pinch arranque"),
        ), instrumento="pinch"),
        Grupo("Clic, arrastre y scroll", (
            _sl("gestures.click_max_ms", "Duración máxima de un clic",
                120, 600, paso=10, decimales=0, unidad=" ms",
                hint="Más tiempo pinzando ya no es un clic",
                keywords="clic duracion tiempo corto"),
            _sl("gestures.click_max_travel_px", "Recorrido máximo de un clic",
                60, 400, paso=10, decimales=0, unidad=" px",
                hint="Se mide con la palma: 1 cm de mano son ~200 px",
                keywords="clic recorrido viaje travel palma scroll"),
            _sl("gestures.scroll_arm_ms", "Tiempo hasta armar el scroll",
                150, 800, paso=10, decimales=0, unidad=" ms",
                hint="Antes de esto un clic no puede volverse scroll",
                keywords="scroll armar tiempo clic espera"),
            _sl("gestures.drag_min_travel_px", "Recorrido para arrastrar",
                60, 400, paso=10, decimales=0, unidad=" px",
                keywords="arrastre drag recorrido seleccionar"),
            _op("gestures.pinch_drag_mode", "Pinch y mover",
                ("Scroll", "Arrastrar"), ("scroll", "drag"),
                hint="Qué hace pinzar y desplazar sobre contenido normal",
                keywords="pinch arrastrar scroll seleccionar mover"),
            _sl("gestures.scroll_gain", "Velocidad de scroll", 0.4, 5.0,
                paso=0.05,
                keywords="scroll velocidad ganancia rueda"),
            _tg("gestures.scroll_invert", "Invertir el scroll",
                hint="Como el trackpad del Mac: el contenido sigue la mano",
                keywords="scroll invertir natural direccion"),
            _tg("gestures.hscroll_enabled", "Scroll horizontal",
                keywords="scroll horizontal lateral"),
        )),
        Grupo("Zoom y catapulta", (
            _tg("gestures.zoom_enabled", "Zoom a dos manos",
                hint="Separar y juntar las dos manos hace zoom",
                keywords="zoom dos manos ampliar acercar"),
            _sl("gestures.zoom_gain", "Velocidad de zoom", 0.3, 3.0,
                paso=0.05, activo_si="gestures.zoom_enabled",
                keywords="zoom velocidad ganancia"),
            _sl("gestures.zoom_min_delta_px", "Umbral de zoom", 4, 40,
                paso=1, decimales=0, unidad=" px",
                activo_si="gestures.zoom_enabled",
                hint="Cuánto hay que separar las manos para que empiece",
                keywords="zoom umbral minimo delta"),
            _tg("gestures.flick_enabled", "Catapulta = clic derecho",
                hint="Índice curvado contra el pulgar y estirón adelante",
                keywords="catapulta flick clic derecho contextual"),
            _sl("gestures.flick_min_speed", "Velocidad de la catapulta",
                1.0, 6.0, paso=0.05, activo_si="gestures.flick_enabled",
                hint="Si se dispara sola súbelo; si no sale nunca bájalo",
                keywords="catapulta flick velocidad disparo"),
            _sl("gestures.flick_min_delta", "Estirón mínimo", 0.05, 0.50,
                paso=0.01, activo_si="gestures.flick_enabled",
                hint="Cuánto tiene que estirarse el dedo al salir",
                keywords="catapulta flick estiron extension"),
        )),
        Grupo("Ventanas", (
            _tg("gestures.window_chrome_enabled",
                "Mover y redimensionar ventanas",
                hint="Barras bajo el borde inferior de cada ventana",
                keywords="ventanas mover redimensionar barras chrome"),
            _sl("gestures.window_grab_band_px", "Banda de agarre", 20, 90,
                paso=2, decimales=0, unidad=" px",
                activo_si="gestures.window_chrome_enabled",
                keywords="ventana banda agarre borde inferior"),
            _sl("gestures.window_corner_px", "Esquina de redimensionar",
                30, 120, paso=2, decimales=0, unidad=" px",
                activo_si="gestures.window_chrome_enabled",
                keywords="ventana esquina redimensionar tamano"),
        )),
    ),
    "Los dos umbrales son una histéresis. Juntos de más, el clic parpadea; "
    "separados de más, sigues clicando con los dedos ya abiertos, y por eso la "
    "apertura se queda siempre entre 0,03 y 0,14 por encima del cierre aunque "
    "arrastres más lejos. El recorrido máximo del clic y el tiempo de armado "
    "son lo único que separa un clic de un scroll: bájalos y cualquier clic se "
    "te irá en scroll, que es exactamente el fallo por el que hoy valen 190 px "
    "y 360 ms.",
)


_TECLADO = Seccion(
    "teclado", "Teclado", (
        Grupo("Teclado virtual", (
            _tg("gestures.keyboard_enabled", "Aparece solo",
                hint="Al enfocar un campo de texto",
                keywords="teclado virtual escribir teclas aparece"),
            _sl("gestures.key_repeat_ms", "Repetición al mantener",
                120, 800, paso=10, decimales=0, unidad=" ms",
                hint="Solo afecta a borrar y al espacio",
                keywords="repeticion mantener borrar espacio velocidad"),
        )),
    ),
    "Catapulta encima de una tecla para ver sus variantes (á, à, ä…): las que "
    "las tienen llevan un punto en la esquina. Bajar la repetición hace que "
    "borrar un párrafo sea un gesto y no una tarea; bajarla de más te comerá "
    "la palabra que querías conservar.",
)


_SEGURIDAD = Seccion(
    "seguridad", "Seguridad", (
        Grupo("Guardas", (
            _tg("safety.pause_on_no_face", "Pausar si no hay nadie",
                hint="Cuando deja de verse tu cara delante",
                keywords="cara rostro pausa ausente levantarse"),
            _sl("safety.no_face_timeout_ms", "Espera sin cara",
                1000, 8000, paso=250, decimales=0, unidad=" ms",
                activo_si="safety.pause_on_no_face",
                keywords="cara espera tiempo pausa"),
            _tg("safety.mouse_override", "Ceder al ratón físico",
                hint="Mover el ratón de verdad aparta a AirTouch",
                keywords="raton fisico ceder mouse override"),
            _sl("safety.mouse_override_px", "Recorrido para ceder", 5, 80,
                paso=1, decimales=0, unidad=" px",
                activo_si="safety.mouse_override",
                keywords="raton fisico recorrido umbral"),
            _tg("safety.open_palm_pause", "Palma abierta",
                hint="Mantén la mano abierta para pausar o reanudar",
                keywords="palma mano abierta pausa reanudar"),
            _sl("safety.open_palm_ms", "Tiempo de palma", 600, 3000,
                paso=100, decimales=0, unidad=" ms",
                activo_si="safety.open_palm_pause",
                keywords="palma tiempo espera"),
            _sl("safety.esc_hold_ms", "Esc mantenido", 300, 2000, paso=50,
                decimales=0, unidad=" ms",
                hint="Funciona siempre, aunque falle todo lo demás",
                keywords="esc escape teclado pausa emergencia"),
        )),
    ),
    "Para recuperar el control: mantén Esc, mueve el ratón físico, o abre la "
    "palma. Las tres cortan la inyección al instante y ninguna depende de que "
    "el seguimiento vaya bien; la cara es la única que actúa sola, cuando te "
    "levantas de la silla. Si apagas las otras tres, Esc es lo único que te "
    "queda: no lo olvides antes de irte.",
    completas=("safety",),
)


_AIRLINK = Seccion(
    "airlink", "AirLink", (
        Grupo("Servidor", (
            _tg("airlink.enabled", "Servidor de AirLink",
                hint="La cámara por WiFi, sin apps de terceros",
                keywords="airlink servidor wifi movil camara"),
            _tg("airlink.auto_start", "Levantarlo con el motor",
                activo_si="airlink.enabled",
                keywords="arranque automatico servidor motor"),
            _tx("airlink.port", "Puerto", placeholder="8443",
                activo_si="airlink.enabled",
                hint="Cambiarlo obliga a volver a emparejar el móvil",
                keywords="puerto port red tcp https"),
            _tx("airlink.web_root", "Carpeta web",
                placeholder="la que viene con el programa",
                keywords="web root carpeta desarrollo estatico"),
        )),
        Grupo("Emparejamiento", (
            _ac("Código de emparejamiento", "Generar otro", "renovar_token",
                hint="El móvil tendrá que volver a escanear el código",
                keywords="codigo emparejar token qr movil"),
        )),
    ),
    "El código se guarda a propósito: si cambiara en cada arranque, el móvil "
    "que lo recuerda llegaría siempre con el viejo y el servidor lo rechazaría "
    "sin decir por qué. Generar uno nuevo o cambiar el puerto rompe el "
    "emparejamiento actual, así que tendrás el móvil en la mano y el código en "
    "pantalla otra vez.",
    completas=("airlink",),
)


_AVANZADO = Seccion(
    "avanzado", "Avanzado", (
        Grupo("Visión", (
            _op("vision.max_hands", "Manos a seguir",
                ("Una", "Dos"), (1, 2),
                hint="Con una sola no hay zoom a dos manos",
                keywords="manos numero dos una"),
            _tg("vision.face_enabled", "Detectar la cara",
                hint="Solo hace falta si algo la usa; si no, es tiempo tirado",
                keywords="cara rostro deteccion presencia"),
            _sl("vision.face_every_n_frames", "Cara cada N fotogramas",
                1, 20, paso=1, decimales=0,
                activo_si="vision.face_enabled",
                keywords="cara frecuencia fotogramas coste"),
            _sl("vision.min_hand_detection_confidence",
                "Confianza para detectar", 0.10, 0.90, paso=0.05,
                keywords="confianza deteccion umbral modelo"),
            _sl("vision.min_hand_presence_confidence",
                "Confianza de presencia", 0.10, 0.90, paso=0.05,
                keywords="confianza presencia umbral modelo"),
            _sl("vision.min_tracking_confidence",
                "Confianza de seguimiento", 0.10, 0.90, paso=0.05,
                keywords="confianza seguimiento umbral modelo"),
            _op("vision.downscale_width", "Anchura de análisis",
                ("512", "640", "768", "960"), (512, 640, 768, 960),
                hint="Solo cuando hay que mirar el fotograma entero",
                keywords="downscale anchura analisis coste cpu"),
        )),
        Grupo("Recorte de seguimiento", (
            _tg("vision.roi_enabled", "Seguir por recorte",
                hint="Más rápido y más preciso: la mano llena la entrada",
                keywords="roi recorte seguimiento precision"),
            _op("vision.roi_size", "Lado del recorte",
                ("256", "320", "384", "448"), (256, 320, 384, 448),
                activo_si="vision.roi_enabled",
                keywords="roi tamano lado recorte"),
            _sl("vision.roi_margin", "Margen del recorte", 0.40, 1.60,
                paso=0.05, activo_si="vision.roi_enabled",
                hint="Cuánto se agranda la caja de la mano",
                keywords="roi margen caja holgura"),
            _sl("vision.roi_max_misses", "Fotogramas sin mano", 1, 20,
                paso=1, decimales=0,
                activo_si="vision.roi_enabled",
                hint="Antes de volver a mirar el fotograma entero",
                keywords="roi perdida fotogramas reintento"),
        )),
        Grupo("Puntero fino", (
            _sl("filter.d_cutoff", "Corte de la derivada", 0.5, 3.0,
                paso=0.1, decimales=1,
                hint="Subirlo empeora mucho el temblor",
                keywords="derivada corte dcutoff temblor velocidad"),
            _sl("filter.prediction_max_px", "Tope del adelanto", 10, 120,
                paso=2, decimales=0, unidad=" px",
                hint="Evita el rebote al frenar de golpe",
                keywords="prediccion tope maximo rebote"),
            _sl("filter.prediction_min_speed", "Velocidad de entrada",
                100, 900, paso=10, decimales=0,
                hint="Por debajo, el adelanto no entra (px/s)",
                keywords="prediccion velocidad minima entrada"),
            _sl("filter.prediction_full_speed", "Velocidad de adelanto pleno",
                400, 2000, paso=20, decimales=0,
                hint="A partir de aquí se aplica entero (px/s)",
                keywords="prediccion velocidad plena maxima"),
        )),
        Grupo("Región activa del encuadre", (
            _sl("mapping.region_x0", "Borde izquierdo", 0.00, 0.45,
                paso=0.01, keywords="region encuadre izquierda margen"),
            _sl("mapping.region_y0", "Borde superior", 0.00, 0.45,
                paso=0.01, keywords="region encuadre arriba margen"),
            _sl("mapping.region_x1", "Borde derecho", 0.55, 1.00,
                paso=0.01, keywords="region encuadre derecha margen"),
            _sl("mapping.region_y1", "Borde inferior", 0.55, 1.00,
                paso=0.01, keywords="region encuadre abajo margen"),
        )),
        Grupo("Catapulta fina", (
            _sl("gestures.flick_load_curl", "Curvatura de carga", 0.40, 1.00,
                paso=0.01, keywords="catapulta curvatura carga curl"),
            _sl("gestures.flick_contact_ratio", "Contacto con el pulgar",
                0.30, 1.00, paso=0.01,
                keywords="catapulta contacto pulgar cerca"),
            _sl("gestures.flick_release_curl", "Curvatura de liberación",
                0.50, 1.20, paso=0.01,
                keywords="catapulta curvatura liberacion recto"),
            _sl("gestures.flick_min_load_ms", "Tiempo mínimo cargado",
                20, 300, paso=10, decimales=0, unidad=" ms",
                keywords="catapulta tiempo carga minimo"),
            _sl("gestures.flick_max_contact_ms", "Tiempo máximo cargado",
                300, 2000, paso=50, decimales=0, unidad=" ms",
                hint="Más tiempo cargado ya no era una catapulta",
                keywords="catapulta tiempo contacto maximo"),
            _sl("gestures.flick_max_release_ms", "Tiempo máximo de salida",
                100, 600, paso=10, decimales=0, unidad=" ms",
                keywords="catapulta salida liberacion tiempo"),
            _sl("gestures.flick_guard_ms", "Espera del clic izquierdo",
                0, 400, paso=10, decimales=0, unidad=" ms",
                hint="El clic espera por si era una catapulta",
                keywords="catapulta guarda clic izquierdo espera"),
        )),
        Grupo("Ventanas finas", (
            _sl("gestures.window_min_size", "Tamaño mínimo de ventana",
                120, 600, paso=10, decimales=0, unidad=" px",
                keywords="ventana tamano minimo redimensionar"),
        )),
        Grupo("Restablecer", (
            _ac("Volver a los valores por defecto", "Restablecer todo",
                "reset_total", variante="ghost",
                hint="Se conservan la cámara y el tema",
                keywords="restablecer reset defecto fabrica todo"),
        )),
    ),
    "Aquí abajo están los números que casi nunca hay que tocar y que más fácil "
    "es romper sin enterarse: el corte de la derivada dispara el temblor, y "
    "una región activa estrecha multiplica cualquier movimiento de la mano. Si "
    "algo deja de funcionar y no sabes por qué, restablece la sección antes de "
    "seguir bajando valores.",
    completas=("vision",),
)


SECCIONES: tuple[Seccion, ...] = (
    _ASPECTO, _CAMARA, _PUNTERO, _GESTOS, _TECLADO, _SEGURIDAD, _AIRLINK,
    _AVANZADO,
)
