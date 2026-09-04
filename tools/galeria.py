"""Galería del kit de CRISTAL VIVO: todo el sistema junto, en una pantalla.

    .venv\\Scripts\\python.exe tools\\galeria.py <carpeta-destino>
                              [--tema dark|light|ambos] [--solo <sección>]
                              [--sin-recortes]

Saca ``galeria-<tema>.png`` con las láminas E1..E4, los ocho mandos en sus
cinco estados, los seis indicadores, la escala tipográfica entera y los
gráficos con datos sintéticos realistas; y además un PNG por sección, porque
una lámina de 2600 px se mira entera para juzgar el conjunto y por trozos para
juzgar un detalle de 10 px.

**Esto no es una prueba desechable como las ``prueba_*.py``.** Es la
herramienta con la que las fases siguientes miran lo que ya existe antes de
tocarlo. Ampliarla es añadir una clase ``Seccion`` y meterla en ``COLUMNAS``:
la maquetación, el recorte, el cambio de tema y la baja del latido ya están
resueltos aquí.

Tres cosas que hay que saber antes de tocar la maquetación:

* **La reserva de sombra de una lámina depende del tema** (en claro las sombras
  van al 60 %), así que ``colocar()`` se vuelve a llamar entera en cada cambio
  de tema. Una pantalla de verdad usa layouts y no tiene este problema; aquí
  todo se coloca a mano a propósito, para poder decidir el píxel.
* **Los hijos cuelgan de la ventana, no de la sección.** Qt recorta un hijo al
  rectángulo de su padre, y una lámina metida dentro de otra saldría con la
  sombra cortada a canto recto. Las secciones son objetos de maquetación, no
  widgets.
* **Los estados se falsifican tocando el estado interno** (``_hover.jump``,
  ``_press.jump``...). Es lo único razonable: no hay manera de tener cinco
  botones pulsados a la vez con un solo ratón.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from PySide6.QtCore import QPoint, QRect, QRectF, Qt              # noqa: E402
from PySide6.QtGui import QColor, QPainter                        # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget               # noqa: E402

from airtouch.gestures.events import Mode                         # noqa: E402
from airtouch.ui import charts, glass, motion, theme, tipo         # noqa: E402
from airtouch.ui.kit import (Button, Chip, Field, Inset, Segmented,  # noqa: E402
                             SettingRow, Sheet, Slider, Toggle)
from airtouch.ui.kit.display import (Badge, Dot, LeaderLine,      # noqa: E402
                                     Metric, Ring, Sparkline)
from airtouch.ui.tokens import R_LG, R_SM, R_XL                   # noqa: E402

# --------------------------------------------------------------------------- #
# retícula
# --------------------------------------------------------------------------- #

MARGEN = 40                 # del borde del lienzo al vidrio de la primera lámina
HUECO = 24                  # entre secciones, de vidrio a vidrio
PAD = 20                    # padding interior de una sección con marco
ROTULO = 30                 # alto reservado al rótulo overline de la sección

#: Los cinco estados que tiene que saber enseñar cualquier mando.
ESTADOS = ("reposo", "sobre", "pulsado", "deshabilitado", "foco")


def reposar(app: QApplication, segundos: float) -> None:
    """Deja correr el reloj de verdad: las animaciones necesitan tiempo real."""
    fin = time.time() + segundos
    while time.time() < fin:
        app.processEvents()
        time.sleep(0.008)


# --------------------------------------------------------------------------- #
# datos sintéticos con la forma de los de verdad
# --------------------------------------------------------------------------- #

SEMILLA = 20260904


def datos() -> dict:
    """Una sesión falsa pero verosímil: 60 s a 4 Hz con dos caídas de carga.

    La forma importa más que los números. Un gráfico alimentado con ruido
    uniforme sale bonito y no enseña nada; estos datos tienen las dos cosas que
    de verdad pasan -- el motor se hunde dos veces y los pinch abortados se
    amontonan justo encima del umbral -- que son los casos que los gráficos
    tienen que saber contar.
    """
    r = np.random.default_rng(SEMILLA)
    n = 240

    fps = 58.0 + r.normal(0, 0.9, n)
    fps[90:104] -= 12.0
    fps[180:188] -= 7.0
    cam = np.clip(fps + r.normal(0, 1.4, n), 20, 61)

    lat = 34.0 + r.lognormal(1.9, 0.45, n)      # lognormal: la forma real
    lat[90:104] += 55.0
    proc = 6.4 + r.gamma(2.0, 0.9, n)
    periodo = 1000.0 / np.clip(fps, 12, 90)

    dt = 16.7 + r.gamma(1.4, 0.9, 900)          # el latido a 60 Hz con saltos
    dt[r.random(900) < 0.03] += 22.0

    # el histograma de latencia se acota al rango donde de verdad hay datos: con
    # 0..300 ms toda la sesion cabe en el 15 % izquierdo y no se lee nada
    hist_lat, _ = np.histogram(lat, bins=48, range=(0.0, 160.0))

    # cierres: la mayoria llega, y los abortados se quedan justo encima del
    # umbral. Es el caso que la frase calculada tiene que saber leer
    minimos = np.concatenate([r.normal(0.24, 0.05, 62),
                              r.normal(0.355, 0.018, 34)])
    desenlaces = np.concatenate([
        r.choice([0, 0, 0, 1, 2], 62),
        np.full(34, int(charts.Outcome.ABORT))]).astype(np.int16)
    orden = r.permutation(minimos.size)

    pasos = r.normal(0, 0.55, (700, 2)) + np.stack([
        np.sin(np.linspace(0, 9, 700)) * 1.9,
        np.cos(np.linspace(0, 6, 700)) * 1.4], axis=1)
    puntero = np.cumsum(pasos, axis=0) + np.array([1280.0, 720.0])

    return dict(fps=fps, cam=cam, lat=lat, proc=proc, periodo=periodo, dt=dt,
                hist_lat=hist_lat, hist_lo=0.0, hist_hi=160.0,
                minimos=minimos[orden], desenlaces=desenlaces[orden],
                puntero=puntero.astype(np.float32))


D = datos()
PINCH_ON, PINCH_OFF = 0.34, 0.42


def p_lat(q: float) -> float:
    return float(np.percentile(D["lat"], q))


# --------------------------------------------------------------------------- #
# la sección: un objeto de maquetación, no un widget
# --------------------------------------------------------------------------- #

class Seccion:
    """Un bloque de la galería: rótulo, marco opcional y una tanda de hijos.

    Los hijos cuelgan de la **ventana**, no de la sección: una lámina metida
    dentro de otra sale con la sombra cortada, porque Qt recorta cada hijo a su
    rectángulo. La sección solo dice dónde va cada cosa.

    Para añadir una sección nueva: heredar, rellenar ``NOMBRE``/``TITULO``/
    ``ALTO``, escribir ``construir`` (crea los hijos), ``colocar`` (los mueve
    dentro del hueco) y, si hace falta, ``pintar`` (rótulos sueltos). Y meterla
    en ``COLUMNAS``.
    """

    NOMBRE = "seccion"           # nombre del archivo del recorte
    TITULO = ""                  # rótulo overline
    NOTA = ""                    # una línea de caption bajo el rótulo
    ALTO = 200
    MARCO: str | None = "E2"     # None deja la sección sobre el lienzo desnudo

    def __init__(self, ventana: "Galeria") -> None:
        self.v = ventana
        self.caja = QRectF()     # vidrio del marco, en coordenadas de ventana
        self.hijos: list[QWidget] = []
        self.construir()

    # -- ganchos ------------------------------------------------------------
    def construir(self) -> None:
        """Crea los hijos. Se llama una vez."""

    def colocar(self, hueco: QRectF) -> None:
        """Coloca los hijos. Se llama en cada cambio de tema."""

    def pintar(self, p: QPainter, hueco: QRectF) -> None:
        """Rótulos y adornos que pinta la ventana por debajo de los hijos."""

    def retema(self) -> None:
        for w in self.hijos:
            gancho = getattr(w, "on_theme", None)
            if callable(gancho):
                gancho()

    # -- infraestructura ----------------------------------------------------
    def adopta(self, *widgets: QWidget) -> None:
        """Cuelga los hijos de la ventana y los registra para el retema."""
        for w in widgets:
            w.setParent(self.v)
            w.show()
            self.hijos.append(w)

    def hueco(self) -> QRectF:
        """Donde va el contenido: el vidrio menos el padding y el rótulo."""
        r = self.caja
        if self.MARCO is None:
            return QRectF(r.left(), r.top() + ROTULO,
                          r.width(), r.height() - ROTULO)
        return QRectF(r.left() + PAD, r.top() + PAD + ROTULO,
                      r.width() - 2 * PAD, r.height() - 2 * PAD - ROTULO)

    def pintar_marco(self, p: QPainter) -> None:
        if self.MARCO is not None:
            glass.paint_sheet(p, self.caja, self.MARCO, R_XL,
                              canvas=self.v.canvas, canvas_origin=QPoint(0, 0))
        x = self.caja.left() + (0 if self.MARCO is None else PAD)
        y = self.caja.top() + (0 if self.MARCO is None else PAD)
        p.setFont(tipo.font("overline"))
        p.setPen(QColor(theme.C.ink.tertiary))
        p.drawText(QRectF(x, y, self.caja.width(), 14),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                   tipo.text("overline", self.TITULO))
        if self.NOTA:
            p.setFont(tipo.font("caption"))
            p.setPen(QColor(theme.C.ink.secondary))
            p.drawText(QRectF(x, y + 15, self.caja.width() - 2 * PAD, 15),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                       self.NOTA)

    # -- utilidades de pintado ----------------------------------------------
    def etiqueta(self, p: QPainter, x: float, y: float, texto: str,
                 rol: str = "axis", tono: str | None = None) -> None:
        p.setFont(tipo.font(rol))
        p.setPen(QColor(tono or theme.C.ink.tertiary))
        p.drawText(QRectF(x, y, 460, tipo.metrics(rol).height() + 2),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                   tipo.text(rol, texto))


# --------------------------------------------------------------------------- #
# 1. láminas E1..E4
# --------------------------------------------------------------------------- #

class Muestra(Sheet):
    """Una lámina de la escalera, con su nombre y su descripción dentro.

    El texto lo pinta la lámina y no la ventana porque Qt pinta al hijo
    **después** del padre: escrito desde fuera, el vidrio lo taparía.
    """

    def __init__(self, nivel: str, nota: str, **kwargs) -> None:
        super().__init__(elevation=nivel, radius=R_LG, padding=PAD, **kwargs)
        self.nivel = nivel
        self.nota = nota

    def paint_content(self, painter: QPainter, rect: QRectF) -> None:
        painter.setFont(tipo.font("h2"))
        painter.setPen(QColor(theme.C.ink.primary))
        painter.drawText(QRectF(rect.left(), rect.top(), rect.width(), 22),
                         int(Qt.AlignmentFlag.AlignLeft), self.nivel)
        parrafo = tipo.Parrafo(self.nota, "body")
        parrafo.set_width(rect.width())
        parrafo.draw(painter, rect.left(), rect.top() + 28,
                     QColor(theme.C.ink.secondary))


class SecLaminas(Seccion):
    """La escalera de elevación, sobre el lienzo desnudo.

    Sin marco a propósito: una E2 encima de otra E2 no dice nada. Aquí las
    cuatro láminas se apoyan en el lienzo, que es donde viven de verdad, y
    dentro de la E2 va un rebaje E1 con el radio concéntrico para que se vea
    que el vidrio parece fabricado y no recortado.
    """

    NOMBRE = "laminas"
    TITULO = "láminas · escalera de elevación"
    NOTA = ("cada lámina reserva dentro de sí misma el hueco de su sombra; "
            "por eso dos vecinas se colocan con gap_between()")
    ALTO = 268
    MARCO = None

    ANCHO_L, ALTO_L = 236, 168

    NIVELES = (("E1", "rebaje: filo invertido, sin sombra"),
               ("E2", "tarjeta con un rebaje dentro"),
               ("E3", "el nivel al que sube una E2 en hover"),
               ("E4", "barra flotante y menús"))

    def construir(self) -> None:
        self.laminas = [Muestra(n, nota, interactive=n == "E2")
                        for n, nota in self.NIVELES]
        self.adopta(*self.laminas)
        # la E2 va en reposo a proposito: alzada se pinta ya como una E3 y la
        # escalera dejaba de ser una escalera. El alzado se mira en los botones
        self.e2 = self.laminas[1]
        self.pozo = Inset(radius=self.e2.child_radius(), padding=10)
        self.adopta(self.pozo)

    def colocar(self, h: QRectF) -> None:
        for i, hoja in enumerate(self.laminas):
            hoja.place(QRectF(h.left() + i * (self.ANCHO_L + HUECO), h.top(),
                              self.ANCHO_L, self.ALTO_L))
        c = self.e2.content_rect().translated(
            QRectF(self.e2.geometry()).topLeft())
        self.pozo.place(QRectF(c.left(), c.bottom() - 46, c.width(), 46))

    def pintar(self, p: QPainter, h: QRectF) -> None:
        for i, hoja in enumerate(self.laminas):
            m = hoja.reserve()
            self.etiqueta(p, h.left() + i * (self.ANCHO_L + HUECO),
                          h.top() + self.ALTO_L + 10,
                          f"reserva {m.left():.0f}/{m.top():.0f}/"
                          f"{m.right():.0f}/{m.bottom():.0f} px  ·  radio "
                          f"{hoja.radius:.0f}, hijo {hoja.child_radius()}")


# --------------------------------------------------------------------------- #
# 2. los mandos en sus cinco estados
# --------------------------------------------------------------------------- #

def congelar(w: QWidget, estado: str) -> QWidget:
    """Deja el mando quieto en uno de los cinco estados, sin animación."""
    if estado == "sobre":
        if isinstance(w, Sheet):
            w.set_hover(True)
            w._lift.jump(1.0)
        else:
            w._hover.jump(True)
    elif estado == "pulsado":
        w._press.jump(True)
        if isinstance(w, Sheet):
            w.set_hover(True)
            w._lift.jump(1.0)
        else:
            w._hover.jump(True)
    elif estado == "deshabilitado":
        w.setEnabled(False)
    elif estado == "foco":
        w._focus.jump(True)
    return w


class SecMandos(Seccion):
    """La matriz: ocho mandos por cinco estados.

    Es la sección que contesta la única pregunta que importa de un mando: ¿se
    distingue de sí mismo? Si «sobre» y «pulsado» salen iguales en la captura,
    el mando no tiene retroalimentación por mucho que el código diga que sí.
    """

    NOMBRE = "mandos"
    TITULO = "mandos · los cinco estados"
    NOTA = "toda la fila es el mismo mando; solo cambia el estado"
    ALTO = 690

    COL = 190
    ETIQUETA = 130
    FILA = 76

    FABRICAS = (
        ("Toggle", lambda: Toggle(False)),
        ("Toggle activado", lambda: Toggle(True)),
        ("Button primario", lambda: Button("Continuar", "primary")),
        ("Button normal", lambda: Button("Elegir carpeta")),
        ("Button fantasma", lambda: Button("Restablecer", "ghost")),
        ("Chip neutro", lambda: Chip("ahorro")),
        ("Chip con tono", lambda: Chip("conectado", "ok", checkable=True,
                                       checked=True)),
        ("Segmented", lambda: Segmented(["2 min", "20 min", "2 h"], 1)),
    )

    def construir(self) -> None:
        self.rejilla: list[list[QWidget]] = []
        for _nombre, fabrica in self.FABRICAS:
            fila = [congelar(fabrica(), e) for e in ESTADOS]
            self.adopta(*fila)
            self.rejilla.append(fila)

    def colocar(self, h: QRectF) -> None:
        y0 = h.top() + 22
        for f, fila in enumerate(self.rejilla):
            y = y0 + f * self.FILA
            for c, w in enumerate(fila):
                x = h.left() + self.ETIQUETA + c * self.COL
                s = w.sizeHint()
                if isinstance(w, Button):
                    m = w.reserve()
                    w.place(QRect(int(x), int(y),
                                  int(s.width() - m.left() - m.right()),
                                  Button.HEIGHT))
                else:
                    if s.isValid():
                        w.resize(s)
                    w.move(int(x), int(y + (Button.HEIGHT - w.height()) / 2))

    def pintar(self, p: QPainter, h: QRectF) -> None:
        for c, estado in enumerate(ESTADOS):
            self.etiqueta(p, h.left() + self.ETIQUETA + c * self.COL, h.top(),
                          estado, "overline")
        for f, (nombre, _fab) in enumerate(self.FABRICAS):
            self.etiqueta(p, h.left(), h.top() + 30 + f * self.FILA, nombre,
                          "caption", theme.C.ink.secondary)


# --------------------------------------------------------------------------- #
# 3. los mandos anchos
# --------------------------------------------------------------------------- #

class SecCampos(Seccion):
    """Field, Slider y SettingRow: los que ocupan una fila entera.

    No caben en la matriz de cinco columnas, así que van aquí en pares: a la
    izquierda en reposo, a la derecha en el estado interesante.
    """

    NOMBRE = "campos"
    TITULO = "mandos anchos · reposo y estado vivo"
    ALTO = 472

    def construir(self) -> None:
        self.campo = Field("Buscar en ajustes")
        self.campo_foco = Field("Buscar en ajustes", "puntero")
        self.desliz = Slider(0.0, 1.0, 0.34, decimals=2, bubble=False)
        self.desliz_vivo = Slider(0.0, 1.0, 0.62, decimals=2)
        self.desliz_vivo._hover.jump(True)
        self.desliz_vivo._subs.jump(True)
        self.desliz_vivo._bubble.jump(True)
        self.fila_a = SettingRow(
            "Suavizado del puntero", Slider(0.0, 1.0, 0.45, bubble=False),
            hint="Bajar el corte suaviza el puntero pero añade unos 20 ms "
                 "de retardo",
            keywords="raton cursor temblor")
        self.fila_b = SettingRow("Mostrar el teclado virtual", Toggle(True),
                                 keywords="teclas escribir")
        self.fila_b.set_modified(True)
        self.fila_b._modified.jump(True)
        self.adopta(self.campo, self.campo_foco, self.desliz, self.desliz_vivo,
                    self.fila_a, self.fila_b)

        # la materialización del botón primario, congelada en su recorrido
        self.nacimientos = []
        for k in (0.12, 0.35, 0.65, 1.0):
            b = Button("Perfecto, seguir", "primary", born=False)
            b._born = True
            b._birth = k
            b._birth_scale.jump(0.96 + 0.04 * k)
            self.nacimientos.append(b)
        self.adopta(*self.nacimientos)

    def colocar(self, h: QRectF) -> None:
        col = (h.width() - HUECO) / 2.0
        y = h.top() + 18
        self.campo.setGeometry(int(h.left()), int(y), int(col),
                               self.campo.height())
        self.campo_foco.setGeometry(int(h.left() + col + HUECO), int(y),
                                    int(col), self.campo_foco.height())
        y += 82
        self.desliz.setGeometry(int(h.left()), int(y), int(col),
                                self.desliz.height())
        # sin desplazarlo hacia arriba: la burbuja se pinta por encima del
        # canal, dentro del propio widget, y subirlo la metia en el rótulo
        self.desliz_vivo.setGeometry(int(h.left() + col + HUECO), int(y),
                                     int(col), self.desliz_vivo.height())
        y += 96
        self.fila_a.setGeometry(int(h.left()), int(y), int(h.width()),
                                self.fila_a.height())
        self.fila_b.setGeometry(int(h.left()), int(y + 62), int(h.width()),
                                self.fila_b.height())
        y += 152
        self.y_nacimiento = y
        paso = (h.width() - 20) / 4.0
        for i, b in enumerate(self.nacimientos):
            m = b.reserve()
            ancho = b.sizeHint().width() - m.left() - m.right()
            b.place(QRect(int(h.left() + i * paso), int(y), int(ancho),
                          Button.HEIGHT))

    def pintar(self, p: QPainter, h: QRectF) -> None:
        col = (h.width() - HUECO) / 2.0
        for x, texto in ((h.left(), "Field · reposo"),
                         (h.left() + col + HUECO, "Field · con foco")):
            self.etiqueta(p, x, h.top(), texto, "overline")
        for x, texto in ((h.left(), "Slider · reposo"),
                         (h.left() + col + HUECO,
                          "Slider · sobre, con burbuja y subdivisiones")):
            self.etiqueta(p, x, h.top() + 82, texto, "overline")
        self.etiqueta(p, h.left(), h.top() + 178, "SettingRow · con pista y "
                      "modificada", "overline")
        self.etiqueta(p, h.left(), self.y_nacimiento - 22,
                      "Button primario materializándose", "overline")


# --------------------------------------------------------------------------- #
# 4. indicadores
# --------------------------------------------------------------------------- #

GUARDAS = (("cara", "ok", False), ("ratón físico", "quiet", False),
           ("palma abierta", "warn", False), ("Esc", "danger", True))

CHAPAS = (("v2.0", "neutral", False), ("control activo", "ok", True),
          ("ahorro", "warn", False), ("en pausa", "danger", True))


class SecIndicadores(Seccion):
    """Punto, chapa, anillo y traza: el cromo que dice en qué estado estamos."""

    NOMBRE = "indicadores"
    TITULO = "indicadores · punto, chapa, anillo, traza"
    ALTO = 306
    FILA = 27.0

    def construir(self) -> None:
        self.puntos = [Dot(size=8, tone=t, pulse=pu) for _n, t, pu in GUARDAS]
        self.chapas = [Badge(n, tone=t, dot=d) for n, t, d in CHAPAS]
        self.anillo_carga = Ring(diameter=64, thickness=4, tone="accent")
        self.anillo_carga.set_progress(0.36, immediate=True)
        self.anillo_vivo = Ring(diameter=64, thickness=4, tone="ok",
                                progress=1.0, breathing=True)
        self.traza = Sparkline(width=180, height=44, step=2.0, tone="accent")
        for v in D["fps"][-90:]:
            self.traza.push(float(v))
        self.adopta(*self.puntos, *self.chapas, self.anillo_carga,
                    self.anillo_vivo, self.traza)

    def colocar(self, h: QRectF) -> None:
        for i, d in enumerate(self.puntos):
            d.move(int(h.left() - Dot.HALO + 4),
                   int(h.top() + 18 + i * self.FILA - Dot.HALO + 4))
        x, y = h.left() + 150, h.top() + 16
        for ch in self.chapas:
            s = ch.sizeHint()
            if x + s.width() > h.right():
                x, y = h.left() + 150, y + s.height() + 8
            ch.setGeometry(int(x), int(y), s.width(), s.height())
            x += s.width() + 8
        y = h.top() + 160
        self.anillo_carga.move(int(h.left()), int(y))
        self.anillo_vivo.move(int(h.left() + 80), int(y))
        self.traza.move(int(h.right() - self.traza.width()), int(y + 10))

    def pintar(self, p: QPainter, h: QRectF) -> None:
        p.setFont(tipo.font("caption"))
        p.setPen(QColor(theme.C.ink.secondary))
        mc = tipo.metrics("caption")
        for i, (nombre, _t, _pu) in enumerate(GUARDAS):
            p.drawText(QRectF(h.left() + 22, h.top() + 14 + i * self.FILA,
                              140, mc.height() + 4),
                       int(Qt.AlignmentFlag.AlignLeft), nombre)
        self.etiqueta(p, h.left(), h.top() + 142,
                      "Ring · carga y respiración", "overline")
        self.etiqueta(p, h.right() - self.traza.width(), h.top() + 142,
                      "Sparkline · blit", "overline")


# --------------------------------------------------------------------------- #
# 5. cifras
# --------------------------------------------------------------------------- #

RECIBO = (("cámara", "iPhone · 1920×1080 · 60 fps"),
          ("tu pinch", "0,31 / 0,38"),
          ("retardo medio", "74 ms"))


class SecCifras(Seccion):
    """Metric y LeaderLine: donde se ve si las cifras tabulares funcionan.

    Las dos fichas llevan la misma cantidad de dígitos a propósito: si la caja
    de la cifra encogiera al bajar el valor, la unidad daría un salto y aquí se
    vería de un vistazo.
    """

    NOMBRE = "cifras"
    TITULO = "cifras · ficha en vivo y recibo"
    ALTO = 300

    def construir(self) -> None:
        self.fichas = [
            Metric("fps del motor", unit="fps", decimals=1,
                   note="pipeline_fps", higher_is_better=True, tone="accent"),
            Metric("retardo de captura p95", unit="ms", decimals=0,
                   note="percentil 95 de fs.capture_latency_ms",
                   higher_is_better=False, tone="info"),
        ]
        for v in D["fps"][-40:]:
            self.fichas[0].push(float(v))
        for v in D["lat"][-40:]:
            self.fichas[1].push(float(v))
        self.recibo = [LeaderLine(e, val) for e, val in RECIBO]
        self.adopta(*self.fichas, *self.recibo)

    def colocar(self, h: QRectF) -> None:
        col = (h.width() - HUECO) / 2.0
        for i, m in enumerate(self.fichas):
            m.setGeometry(int(h.left() + i * (col + HUECO)), int(h.top()),
                          int(col), 120)
        y = h.top() + 150
        alto = self.recibo[0].sizeHint().height()
        for i, ln in enumerate(self.recibo):
            ln.setGeometry(int(h.left()), int(y + i * (alto + 6)),
                           int(h.width()), alto)

    def pintar(self, p: QPainter, h: QRectF) -> None:
        self.etiqueta(p, h.left(), h.top() + 128,
                      "LeaderLine · el recibo del asistente", "overline")

    def contar(self) -> None:
        """Relanza el conteo escalonado del recibo."""
        for i, ln in enumerate(self.recibo):
            ln.reveal(i)


# --------------------------------------------------------------------------- #
# 6. tipografía
# --------------------------------------------------------------------------- #

MUESTRAS_TIPO = (
    ("display", "Ya está"),
    ("title", "Rendimiento"),
    ("h1", "Presupuesto de retardo"),
    ("h2", "Cómo se calcula"),
    ("body", "El puntero sigue la mano con 42 ms de retardo."),
    ("body-fuerte", "El puntero sigue la mano."),
    ("caption", "percentil 95 de fs.capture_latency_ms"),
    ("overline", "estabilidad del puntero"),
    ("metric", "58,1"),
    ("mosaico", "apuntando"),
    ("axis", "0 20 40 60 fps"),
    ("mono", "0,31 / 0,38 · 1920×1080"),
)


class SecTipo(Seccion):
    """La escala entera, a su cuerpo de verdad y con su tracking puesto.

    Existe porque el tracking es exactamente lo que Qt tira a la basura en una
    hoja de estilo, y una escala que se lee bien en la tabla de tokens puede
    salir apelmazada en pantalla. Aquí se mira, no se deduce: al lado de cada
    muestra va el cuerpo, el peso y el tracking que dice ``tipo.spec()``.
    """

    NOMBRE = "tipografia"
    TITULO = "tipografía · la escala a tamaño real"
    NOTA = "cuerpo · peso · tracking, tal y como los aplica tipo.py"
    ALTO = 566

    def pintar(self, p: QPainter, h: QRectF) -> None:
        y = h.top() + 4
        for rol, muestra in MUESTRAS_TIPO:
            fila = tipo.spec(rol)
            m = tipo.metrics(rol)
            p.setFont(tipo.font("axis"))
            p.setPen(QColor(theme.C.ink.tertiary))
            p.drawText(QRectF(h.left(), y, 150, 14),
                       int(Qt.AlignmentFlag.AlignLeft), rol)
            p.drawText(QRectF(h.left(), y + 13, 150, 14),
                       int(Qt.AlignmentFlag.AlignLeft),
                       f"{fila.size:g}px · {fila.weight} · "
                       f"{fila.tracking:+.1f}")
            p.setFont(tipo.font(rol))
            p.setPen(QColor(theme.C.ink.primary))
            p.drawText(QRectF(h.left() + 96, y, h.width() - 96,
                              m.height() + 4),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignTop),
                       tipo.text(rol, muestra))
            y += max(30.0, m.height() + 8.0)


# --------------------------------------------------------------------------- #
# 7. gráficos: las primitivas
# --------------------------------------------------------------------------- #

class SecGraficos(Seccion):
    """Las nueve primitivas del apartado 7, cada una en su pozo.

    Los datos son sintéticos pero con la forma de los de verdad. Un gráfico que
    no falla pero sale ilegible no vale, y eso solo se ve mirando.
    """

    NOMBRE = "graficos"
    TITULO = "gráficos · las primitivas"
    NOTA = "datos sintéticos con la forma de los reales"
    ALTO = 812

    def construir(self) -> None:
        # Todos con ``ground=False`` y el pozo E1 pintado detras por la seccion.
        # Con ``ground=True`` el grafico rellena su rectangulo entero de
        # ``glass.sunken`` y se come las esquinas redondeadas del rebaje: en
        # oscuro sale un agujero negro de cantos rectos, que es justo lo que el
        # apartado 3.6 no quiere. ``ground=True`` solo es honesto cuando el
        # grafico **es** el rectangulo entero.
        self.trace = charts.Trace(ground=False, step=2.0, unit=" fps",
                                  lo=0.0, hi=72.0, autoscale=False)
        self.stack = charts.StackedTrace(ground=False, step=2.0, hi=140.0,
                                         colors=self._c3())
        self.stack.set_rule(charts.BUDGET_TARGET_MS)
        self.area = charts.AreaChart(ground=False,
                                     colors=[theme.C.color.accent,
                                             theme.C.color.info],
                                     line_color=theme.C.color.warn,
                                     unit=" fps")
        self.hist = charts.Histogram(ground=False, unit=" ms")
        self.donut = charts.Donut(ground=False)
        self.scatter = charts.Scatter(ground=False, lo=0.0, hi=0.7)
        self.latido = charts.Heartbeat(ground=False)
        self.tira = charts.Strip()
        self.chispa = charts.Sparkline()
        self.adopta(self.trace, self.stack, self.area, self.hist, self.donut,
                    self.scatter, self.latido, self.tira, self.chispa)
        self.cargar()

    @staticmethod
    def _c3() -> list[str]:
        return [theme.C.color.info, theme.C.color.accent, theme.C.ink.tertiary]

    def _reparto(self) -> list[tuple[str, float, str]]:
        t = theme.C.tokens
        return [("apuntando", 46.0, t.mode_color(Mode.POINTING)),
                ("inactivo", 22.0, t.mode_color(Mode.IDLE)),
                ("scroll", 14.0, t.mode_color(Mode.SCROLLING)),
                ("arrastrando", 11.0, t.mode_color(Mode.DRAGGING)),
                ("zoom", 7.0, t.mode_color(Mode.ZOOMING))]

    def _tira(self) -> list[tuple[str, float, str]]:
        return [("manos", 62.0, theme.C.color.ok),
                ("sin manos", 24.0, theme.C.ink.tertiary),
                ("pausa", 14.0, theme.C.color.danger)]

    def cargar(self) -> None:
        for v in D["fps"]:
            self.trace.push(float(v))
        for i in range(D["lat"].size):
            self.stack.push((float(D["lat"][i]), float(D["proc"][i]),
                             max(0.0, float(D["periodo"][i] - D["proc"][i]))))
        self.area.set_series([D["fps"][-120:], D["cam"][-120:]], D["lat"][-120:])
        self.hist.set_bins(D["hist_lat"], D["hist_lo"], D["hist_hi"])
        self.hist.set_marks([(p_lat(50), "p50"), (p_lat(95), "p95"),
                             (p_lat(99), "p99")])
        self.donut.set_slices(self._reparto())
        self.scatter.set_points(D["minimos"], D["desenlaces"],
                                charts.outcome_colors())
        self.scatter.set_rules([(PINCH_ON, "cierre"), (PINCH_OFF, "apertura")])
        for v in D["dt"]:
            self.latido.push(float(v))
        self.tira.set_parts(self._tira())
        self.chispa.set_values(D["fps"][-40:])

    def retema(self) -> None:
        """Los colores de tema se pasan a mano: no salen de un token vivo."""
        self.trace._color = None
        self.stack._colors = self._c3()
        self.stack.invalidate()
        self.area._colors = [theme.C.color.accent, theme.C.color.info]
        self.area._line_color = theme.C.color.warn
        self.area.invalidate()
        self.donut.set_slices(self._reparto())
        self.scatter._colors = charts.outcome_colors()
        self.tira.set_parts(self._tira())
        super().retema()

    # -- maquetación --------------------------------------------------------
    def celdas(self, h: QRectF) -> list[tuple[str, QWidget, QRectF]]:
        col = (h.width() - HUECO) / 2.0
        izq, der = h.left(), h.left() + col + HUECO
        y = h.top()
        out = []

        def par(a, b, rot_a, rot_b, alto):
            nonlocal y
            y += 16
            out.append((rot_a, a, QRectF(izq, y, col, alto)))
            out.append((rot_b, b, QRectF(der, y, col, alto)))
            y += alto + 12

        def solo(w, rot, alto, ancho=None):
            nonlocal y
            y += 16
            out.append((rot, w, QRectF(izq, y, ancho or h.width(), alto)))
            y += alto + 12

        par(self.trace, self.stack, "Trace · blit desplazado, paso 2 px",
            "StackedTrace · presupuesto apilado", 120)
        par(self.area, self.hist, "AreaChart · cúbica cacheada + eje derecho",
            "Histogram · 48 bins, marcas de percentil", 120)
        par(self.donut, self.scatter, "Donut · reloj de modos",
            "Scatter · cierres por desenlace", 152)
        solo(self.latido, "Heartbeat · 900 ticks, 1 px por fotograma", 88)
        solo(self.tira, "Strip · reparto de la sesión", 40)
        solo(self.chispa, "Sparkline · 60×28", 28, 60)
        return out

    def colocar(self, h: QRectF) -> None:
        self._celdas = self.celdas(h)
        for _rot, w, r in self._celdas:
            if isinstance(w, charts.Sparkline):
                w.move(int(r.left()), int(r.top()))
            else:
                # metido dentro del pozo: pegado al borde, el relleno del area
                # se sale por la esquina redondeada del rebaje
                w.setGeometry(r.adjusted(8, 6, -8, -6).toRect())
        self._resumen_y = max(r.bottom() for _rot, _w, r in self._celdas) + 12

    def pintar(self, p: QPainter, h: QRectF) -> None:
        for _rot, w, r in self.celdas(h):
            if not isinstance(w, charts.Sparkline):
                glass.paint_sheet(p, r, "E1", R_SM, canvas=self.v.canvas,
                                  canvas_origin=QPoint(0, 0))
        for rot, _w, r in self.celdas(h):
            self.etiqueta(p, r.left(), r.top() - 15, rot)
        p.setFont(tipo.font("caption"))
        p.setPen(QColor(theme.C.ink.secondary))
        p.drawText(QRectF(h.left(), self._resumen_y, h.width(), 18),
                   int(Qt.AlignmentFlag.AlignLeft), self.latido.summary())


# --------------------------------------------------------------------------- #
# 8. gráficos: las tres tarjetas de análisis
# --------------------------------------------------------------------------- #

class SecAnalisis(Seccion):
    """Las tres tarjetas del apartado 8.5, a su tamaño de verdad (272x190).

    Sin marco: son láminas E2 y tienen que verse apoyadas en el lienzo, que es
    como salen en la página de análisis. A su tamaño real y no ampliadas,
    porque el problema de estas tarjetas es justamente si el contenido cabe.
    """

    NOMBRE = "analisis"
    TITULO = "análisis · las tres tarjetas, a tamaño real"
    NOTA = "272×190 px de vidrio, el tamaño del apartado 8.5"
    ALTO = 500
    MARCO = None

    def construir(self) -> None:
        self.budget = charts.LatencyBudget()
        self.closures = charts.Closures()
        self.pointer = charts.PointerStability()
        self.adopta(self.budget, self.closures, self.pointer)
        self.cargar()

    def cargar(self) -> None:
        for i in range(D["lat"].size):
            self.budget.push(float(D["lat"][i]), float(D["proc"][i]),
                             float(D["periodo"][i]))
        self.closures.set_closures(D["minimos"], D["desenlaces"],
                                   PINCH_ON, PINCH_OFF)
        for i in range(120, D["puntero"].shape[0], 6):
            self.pointer.set_points(D["puntero"][:i])

    def retema(self) -> None:
        super().retema()
        self.closures.set_closures(D["minimos"], D["desenlaces"],
                                   PINCH_ON, PINCH_OFF)

    def colocar(self, h: QRectF) -> None:
        w, alto = charts._AnalysisCard.CARD_SIZE.width(), \
            charts._AnalysisCard.CARD_SIZE.height()
        self.budget.place(QRectF(h.left(), h.top(), w, alto))
        self.closures.place(QRectF(h.left() + w + HUECO, h.top(), w, alto))
        self.pointer.place(QRectF(h.left(), h.top() + alto + 44, w, alto))
        self._y_frase = h.top() + 2 * alto + 60

    def pintar(self, p: QPainter, h: QRectF) -> None:
        consejo = self.closures.advice
        sugerido = ("aplicaría " + charts.num(consejo.value, 2)
                    if consejo.value is not None else "sin sugerencia")
        p.setFont(tipo.font("caption"))
        p.setPen(QColor(theme.C.ink.secondary))
        for i, linea in enumerate((f"frase calculada: {consejo.text}",
                                   f"botón «Aplicar»: {sugerido} · temblor "
                                   f"{charts.num(self.pointer.tremor, 2)} px")):
            p.drawText(QRectF(h.left(), self._y_frase + i * 18, h.width(), 18),
                       int(Qt.AlignmentFlag.AlignLeft), linea)


# --------------------------------------------------------------------------- #
# la ventana
# --------------------------------------------------------------------------- #

#: Cada columna es (ancho del vidrio, secciones de arriba abajo). Para ampliar
#: la galeria se mete una clase aqui y ya: el resto se apana solo.
COLUMNAS: list[tuple[int, list[type[Seccion]]]] = [
    (1120, [SecLaminas, SecMandos, SecCampos]),
    (680, [SecIndicadores, SecCifras, SecTipo]),
    (720, [SecGraficos, SecAnalisis]),
]


class Galeria(QWidget):
    """El lienzo vivo con todas las secciones encima."""

    def __init__(self) -> None:
        super().__init__()
        ancho = MARGEN * 2 + sum(c[0] for c in COLUMNAS) + HUECO * (len(COLUMNAS) - 1)
        alto = MARGEN * 2 + max(
            sum(s.ALTO for s in col) + HUECO * (len(col) - 1)
            for _w, col in COLUMNAS)
        self.resize(ancho, alto)
        self.canvas = glass.CanvasSource(theme.C.tokens)
        self.canvas.resize(ancho, alto)
        glass.set_active_canvas(self.canvas)

        self.secciones: list[Seccion] = []
        x = MARGEN
        for ancho_col, clases in COLUMNAS:
            y = MARGEN
            for clase in clases:
                s = clase(self)
                s.caja = QRectF(x, y, ancho_col, clase.ALTO)
                self.secciones.append(s)
                y += clase.ALTO + HUECO
            x += ancho_col + HUECO
        self.colocar()

    def por_nombre(self, nombre: str) -> Seccion | None:
        for s in self.secciones:
            if s.NOMBRE == nombre:
                return s
        return None

    def colocar(self) -> None:
        for s in self.secciones:
            s.colocar(s.hueco())

    def retema(self) -> None:
        """Cambio de tema: lienzo, hijos y **de nuevo la maquetación**.

        Lo último no es paranoia: la reserva de sombra de una lámina depende de
        la paleta, así que el mismo ``place()`` deja el vidrio en el mismo sitio
        pero el hueco interior cae en otro.
        """
        self.canvas.set_tokens(theme.C.tokens)
        for s in self.secciones:
            s.retema()
        self.colocar()
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.canvas.paint(p)
        for s in self.secciones:
            s.pintar_marco(p)
            s.pintar(p, s.hueco())
        p.setFont(tipo.font("axis"))
        p.setPen(QColor(theme.C.ink.tertiary))
        p.drawText(QRectF(MARGEN, self.height() - MARGEN + 14,
                          self.width(), 14),
                   int(Qt.AlignmentFlag.AlignLeft),
                   tipo.text("axis", f"AirTouch 2.0 · kit CRISTAL VIVO · tema "
                                     f"{theme.C.name} · {tipo.familias().display}"))
        p.end()


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #

def recortar(pm, caja: QRectF, ruta: Path) -> None:
    """Guarda un trozo de la captura. La caja va en píxeles lógicos."""
    dpr = pm.devicePixelRatio()
    r = QRect(int((caja.left() - MARGEN / 2) * dpr),
              int((caja.top() - MARGEN / 2) * dpr),
              int((caja.width() + MARGEN) * dpr),
              int((caja.height() + MARGEN) * dpr))
    trozo = pm.copy(r.intersected(pm.rect()))
    trozo.save(str(ruta))


def render(app: QApplication, w: Galeria, destino: Path, tema: str,
           recortes: bool, solo: str | None) -> None:
    theme.apply(tema)
    app.setStyleSheet(theme.qss())
    w.retema()
    seccion_cifras = w.por_nombre("cifras")
    if isinstance(seccion_cifras, SecCifras):
        seccion_cifras.contar()
    # El foco de teclado se vuelve a repartir en cada tema y **despues** del
    # retema: ``QApplication.setStyleSheet`` repule el arbol entero y el
    # QLineEdit se queda sin el, asi que el anillo del Field desaparecia de la
    # captura sin que nada mas cambiase.
    campos = w.por_nombre("campos")
    if isinstance(campos, SecCampos):
        w.activateWindow()
        campos.campo_foco._edit.setFocus()
    reposar(app, 1.6)

    pm = w.grab()
    if solo is None:
        ruta = destino / f"galeria-{tema}.png"
        pm.save(str(ruta))
        print(f"{tema:5}  {ruta.name:26} {pm.width()}x{pm.height()}")
    if not recortes:
        return
    for s in w.secciones:
        if solo is not None and s.NOMBRE != solo:
            continue
        ruta = destino / f"galeria-{tema}-{s.NOMBRE}.png"
        recortar(pm, s.caja, ruta)
        print(f"       {ruta.name}")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1].startswith("-"):
        print(__doc__)
        return 2
    destino = Path(argv[1])
    destino.mkdir(parents=True, exist_ok=True)
    tema_arg = argv[argv.index("--tema") + 1] if "--tema" in argv else "ambos"
    temas = ["dark", "light"] if tema_arg == "ambos" else [tema_arg]
    solo = argv[argv.index("--solo") + 1] if "--solo" in argv else None
    recortes = "--sin-recortes" not in argv

    app = QApplication(sys.argv[:1])
    w = Galeria()
    # Sin esto el gestor de ventanas recorta la galería al tamaño de la pantalla
    # y la última sección de cada columna sale cortada. Con WA_DontShowOnScreen
    # el widget se compone entero en el búfer y no hay ventana nativa que lo
    # limite; showEvent y el latido siguen funcionando, y activateWindow() sigue
    # repartiendo el foco de teclado (comprobado: sin ella el anillo del Field
    # no aparece).
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    w.show()
    w.activateWindow()
    for tema in temas:
        render(app, w, destino, tema, recortes, solo)

    vivos = motion.beat.participants
    w.hide()
    reposar(app, 0.1)
    print(f"\nparticipantes en el latido: {vivos} con la ventana visible, "
          f"{motion.beat.participants} tras esconderla "
          f"(latido {'en marcha' if motion.beat.running else 'parado'})")
    print(f"tiles de sombra en el atlas: {glass.ATLAS.built}")
    print(f"imágenes en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
