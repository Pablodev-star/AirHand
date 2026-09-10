"""El panel: ensambla las tres zonas del apartado 8 y habla con el controlador.

La 1.0 era un cuadro de mando generico -barra lateral, tarjetas todas del mismo
peso, y "59 fps" como todo analisis-. Aqui la jerarquia la marca el TAMANYO: una
columna viva fija a la izquierda con lo que esta pasando ahora mismo, un mosaico
de tarjetas grandes en el centro donde la importancia se lee por el area que
ocupa cada una, y una barra flotante abajo.

Este modulo no pinta casi nada: pinta el lienzo de fondo y coloca. Las piezas
viven en live.py (columna), mosaico.py y tarjetas.py (centro), barra.py (abajo)
y analisis.py (la pagina profunda). El paquete sustituye al modulo
``dashboard.py`` de la 1.0, que no podia convivir con el: un modulo y un paquete
con el mismo nombre se pelean por el import y gana el modulo.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import QMainWindow, QMessageBox, QWidget

from ...config import Config
from ...core.controller import Controller
from ...gestures.events import Mode
from .. import glass, motion, theme
from ..settings.panel import SettingsPanel
from ..telemetry import Telemetry
from .analisis import PaginaAnalisis
from .barra import DESTINOS, MARGEN_INFERIOR, BarraInferior
from ..kit.base import ThemeAware
from .comun import Pagina, PaginaDesplazable
from .live import LIVE_COLUMN_W, ColumnaViva
from .mosaico import Mosaico

__all__ = ["Dashboard"]

#: Aire entre la columna viva y el mosaico, y del mosaico al canto derecho.
CANAL = 20.0
MARGEN = 22.0

#: Tamanyo del panel encogido, abajo a la derecha.
COMPACTO = (372, 392)


class _PaginaSimple(Pagina):
    """Envuelve un widget suelto -los ajustes, el registro- como pagina.

    Las paginas se colocan a mano con ``set_area``; un QWidget normal no sabe
    hacerlo. En vez de obligar a cada widget a heredar de Pagina, se envuelve.
    """

    def __init__(self, titulo: str, interior: QWidget,
                 parent: QWidget | None = None) -> None:
        self.TITULO = titulo
        super().__init__(parent)
        self.interior = interior
        interior.setParent(self)

    def colocar(self) -> None:
        caja = self.caja()
        self.interior.setGeometry(int(caja.x()), int(caja.y()),
                                  int(caja.width()), int(caja.height()))


class Dashboard(ThemeAware, QMainWindow):
    """El panel entero. Los nombres publicos son contrato con ``app.py`` (8.9)."""

    cerrado = Signal()

    def __init__(self, cfg: Config, ctl: Controller,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.ctl = ctl
        self.setWindowTitle("AirTouch")
        self.resize(1240, 880)
        self.setMinimumSize(940, 620)

        # ganchos que app.py asigna despues de construirnos
        self.open_calibration = lambda: None
        self.open_wizard = lambda: None

        self._compacto = False
        self._geometria_normal = None
        self._auto_compacto = False
        self._registro: list[str] = []

        # -- lienzo propio: de el recortan todas las laminas de dentro -------
        self.canvas = glass.CanvasSource(theme.C.tokens)

        central = QWidget(self)
        central.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setCentralWidget(central)
        self._central = central

        self.tele = Telemetry()

        # -- zona A: la columna viva ----------------------------------------
        self.columna = ColumnaViva(central)
        self.columna.calibrar.connect(lambda: self.open_calibration())
        self.columna.asistente.connect(lambda: self.open_wizard())
        self.columna.teclado.connect(self.ctl.toggle_keyboard)

        # Contrato con app.py: estos dos nombres los toca desde fuera.
        self.btn_engine = self.columna.boton
        self.control_toggle = self.columna.control
        self.btn_engine.pulsado.connect(self._toggle_engine)
        self.control_toggle.toggled.connect(self._on_control_toggle)

        # -- zona B: las paginas --------------------------------------------
        self.settings = SettingsPanel(cfg, ctl=ctl)
        self.mosaico = Mosaico(cfg, ctl, self.tele, central)
        # El analisis se construye la primera vez que se abre. Son nueve fichas
        # con mapas de pixeles cacheados y no hacen falta para ver la portada.
        self.analisis: PaginaAnalisis | None = None
        self.pagina_ajustes = _PaginaSimple("Ajustes", self.settings, central)

        self.paginas: dict[str, Pagina] = {
            "mosaico": self.mosaico,
            "camara": self.mosaico,
            "gestos": self.mosaico,
            "ajustes": self.pagina_ajustes,
            "registro": self.pagina_ajustes,
        }
        self._orden = ("mosaico", "analisis", "ajustes")
        self._actual = "mosaico"
        for clave in self._orden:
            pagina = self.paginas.get(clave)
            if pagina is not None:
                pagina.setVisible(clave == self._actual)

        self.mosaico.abrir.connect(self._abrir_desde_tarjeta)

        # -- zona C: la barra flotante --------------------------------------
        self.barra = BarraInferior(central)
        self.barra.navegar.connect(self._navegar)

        # -- controlador ------------------------------------------------------
        q = Qt.ConnectionType.QueuedConnection
        ctl.output_ready.connect(self._on_output, q)
        ctl.frame_ready.connect(self._on_frame, q)
        ctl.stats_ready.connect(self._on_stats, q)
        ctl.status_changed.connect(self._on_status, q)
        ctl.log_line.connect(self._append_log, q)
        ctl.error.connect(self._on_error, q)

        self.settings.changed.connect(self._on_settings_changed)
        self.settings.camera_changed.connect(lambda: self.ctl.restart_camera())
        self.settings.calibrate_requested.connect(lambda: self.open_calibration())
        self.settings.theme_changed.connect(self._aplicar_tema)

        self._refresh_control_hint()
        self._colocar()

    # ------------------------------------------------------------------ vida
    def showEvent(self, event) -> None:                     # noqa: N802
        self._canvas_previo = glass.active_canvas()
        glass.set_active_canvas(self.canvas)
        self.canvas.resize(self.width(), self.height())
        self.canvas.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:                     # noqa: N802
        # Sin esto el lienzo sigue latiendo con la ventana escondida en la
        # bandeja, que es justo el gasto que motivo todo motion.py.
        self.canvas.stop()
        glass.set_active_canvas(getattr(self, "_canvas_previo", None))
        super().hideEvent(event)

    def closeEvent(self, event) -> None:                    # noqa: N802
        # Cerrar el panel no cierra AirTouch: sigue en la bandeja. Si cerrarlo
        # matara el programa, el motor se pararia al quitarlo de en medio.
        event.ignore()
        self.hide()
        self.cerrado.emit()

    def resizeEvent(self, event) -> None:                   # noqa: N802
        self.canvas.resize(self.width(), self.height())
        self._colocar()
        super().resizeEvent(event)

    def on_theme(self) -> None:
        """El lienzo guarda SUS tokens: hay que darle los nuevos.

        Sin esto, cambiar de tema con el panel abierto revienta el proceso con
        una violacion de acceso al repintar. El lienzo se queda con la paleta
        vieja mientras el resto de la ventana ya usa la nueva.
        """
        self.canvas.set_tokens(theme.C.tokens)
        self.update()

    def _rehacer_analisis(self) -> None:
        """Cambia el tema: se tira la pagina de analisis y se hace otra."""
        vieja = self.analisis
        visible = self._actual == "analisis"
        self.analisis = PaginaAnalisis(self.cfg, self.ctl, self.tele,
                                       self._central)
        self.paginas["analisis"] = self.analisis
        self.analisis.setVisible(visible)
        vieja.setParent(None)
        vieja.deleteLater()
        self._colocar()

    def paintEvent(self, event) -> None:                    # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.canvas.paint(p, QRectF(self.rect()))
        p.end()

    # -------------------------------------------------------------- colocar
    def _colocar(self) -> None:
        w, h = self._central.width(), self._central.height()
        if w <= 0 or h <= 0:
            return

        if self._compacto:
            self.columna.setGeometry(0, 0, w, h)
            for clave in self._orden:
                pagina = self.paginas.get(clave)
                if pagina is not None:
                    pagina.hide()
            self.barra.hide()
            return

        # Lo que la barra ocupa de verdad: su alto MAS su margen. Confundir
        # MARGEN_INFERIOR con el alto dejaba la barra con 0 px y no se veia.
        reserva = self.barra.ALTO + 2 * MARGEN_INFERIOR

        # La columna tampoco baja hasta el suelo: si no, sus atajos quedan a la
        # misma altura que la barra y se leen como una sola cosa revuelta.
        self.columna.setGeometry(MARGEN, MARGEN, LIVE_COLUMN_W,
                                 h - MARGEN - reserva)
        self.columna.show()

        x = MARGEN + LIVE_COLUMN_W + CANAL
        area = QRectF(x, MARGEN, w - x - MARGEN, h - MARGEN - reserva)
        for clave in self._orden:
            pagina = self.paginas.get(clave)
            if pagina is None:
                continue
            pagina.setGeometry(0, 0, w, h)
            pagina.set_area(area)

        self.barra.show()
        self.barra.raise_()
        # Centrada sobre el AREA DE CONTENIDO, no sobre la ventana: centrada en
        # la ventana se metia debajo de la columna viva y las dos se pisaban.
        ancho = self.barra.ancho_pedido()
        centro = area.center().x()
        self.barra.setGeometry(int(centro - ancho / 2.0),
                               int(h - MARGEN_INFERIOR - self.barra.ALTO),
                               int(ancho), int(self.barra.ALTO))

    def rect_mosaico(self) -> QRectF:
        """Donde aterriza el asistente al terminar (9.3-P6).

        Lo pedia calculando fracciones de la ventana. Que lo pregunte.
        """
        return self.mosaico.caja()

    # ----------------------------------------------------------- navegacion
    def _asegurar_analisis(self) -> PaginaAnalisis:
        if self.analisis is None:
            self.analisis = PaginaAnalisis(self.cfg, self.ctl, self.tele,
                                           self._central)
            self.analisis.reconstruir.connect(self._rehacer_analisis)
            self.paginas["analisis"] = self.analisis
        return self.analisis

    def _navegar(self, clave: str) -> None:
        if clave == "analisis":
            self._asegurar_analisis()
        destino = clave if clave in self._orden else (
            "ajustes" if clave in ("ajustes", "registro") else "mosaico")
        if destino == self._actual:
            return
        self.paginas[self._actual].hide()
        self._actual = destino
        pagina = self.paginas[destino]
        pagina.show()
        pagina.al_entrar()
        self._colocar()
        self.barra.set_destino(clave)

    def _abrir_desde_tarjeta(self, destino: str, _vidrio: QRectF) -> None:
        self._navegar(destino if destino in self._orden else "mosaico")

    # ------------------------------------------------------------- el motor
    def _toggle_engine(self) -> None:
        if self.ctl.running:
            self.ctl.stop()
            self.btn_engine.setText("Iniciar motor")
            self.btn_engine.set_running(False)
            self.exit_compact()
        else:
            if self.ctl.start():
                self.btn_engine.setText("Detener motor")
                self.btn_engine.set_running(True)
                if self.ctl.source_connected:
                    self.enter_compact()
                else:
                    # Sin video todavia: encogerse ahora dejaria al usuario
                    # atrapado sin poder llegar al QR de emparejamiento.
                    self._auto_compacto = True
                    self._navegar("mosaico")
        self._on_status(self.ctl.safety.status_text())

    def _on_control_toggle(self, activo: bool) -> None:
        if activo:
            respuesta = QMessageBox.question(
                self, "Activar control real",
                "A partir de ahora tus gestos moverán el ratón y harán clics "
                "de verdad.\n\nPara recuperar el control al instante: mantén "
                "Esc un segundo, mueve el ratón físico, o abre la palma de la "
                "mano.\n\n¿Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if respuesta != QMessageBox.StandardButton.Yes:
                self.control_toggle.setChecked(False)
                return
        self.ctl.set_control_enabled(activo)
        self._refresh_control_hint()
        self._on_status(self.ctl.safety.status_text())

    def _refresh_control_hint(self) -> None:
        activo = self.cfg.safety.control_enabled
        self.columna.set_escape(
            "Esc mantenido · ratón físico · palma abierta" if activo
            else "Modo seguro: no se inyecta nada")
        self.barra.set_control(activo, Mode.IDLE,
                               self.ctl.safety.state.paused)

    # ------------------------------------------------------------- entradas
    def _on_output(self, out) -> None:
        self.tele.on_output(out)
        self.mosaico.mano.on_output(out)
        if self._actual == "analisis" and self.analisis is not None:
            self.analisis.on_output(out)
        self.barra.set_control(self.cfg.safety.control_enabled, out.mode,
                               self.ctl.safety.state.paused)

    def _on_frame(self, payload) -> None:
        self.tele.on_frame(payload)
        self.mosaico.mano.on_frame(payload)

    def _on_stats(self, stats: dict) -> None:
        self.tele.on_stats(stats)
        self.mosaico.rendimiento.on_stats(stats)
        self.mosaico.enlace.on_stats(stats)
        if self._auto_compacto and stats.get("connected"):
            self._auto_compacto = False
            self.enter_compact()

    def _on_status(self, texto: str) -> None:
        self.columna.nucleo.set_estado(
            "En marcha" if self.ctl.running else "Detenido", texto)

    def _on_error(self, texto: str) -> None:
        self._append_log(f"Error: {texto}")

    def _append_log(self, linea: str) -> None:
        self._registro.append(linea)
        del self._registro[:-500]

    def _on_settings_changed(self) -> None:
        self.ctl.retune()
        self._refresh_control_hint()

    def _aplicar_tema(self) -> None:
        theme.apply(self.cfg.ui.theme)
        app = QGuiApplication.instance()
        if app is not None and hasattr(app, "setStyleSheet"):
            app.setStyleSheet(theme.qss())

    # -------------------------------------------------------------- compacto
    def enter_compact(self) -> None:
        """Se encoge a la esquina con lo imprescindible: nucleo y motor."""
        if self._compacto:
            return
        self._compacto = True
        self._geometria_normal = self.geometry()
        self._minimo_normal = self.minimumSize()

        self.setMinimumSize(300, 300)
        w, h = COMPACTO
        pantalla = QGuiApplication.primaryScreen()
        if pantalla is not None:
            a = pantalla.availableGeometry()
            self.setGeometry(a.right() - w - 24, a.bottom() - h - 24, w, h)
        else:
            self.resize(w, h)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.show()
        self.raise_()
        self._colocar()
        self._append_log("Panel compacto")

    def exit_compact(self) -> None:
        if not self._compacto:
            return
        self._compacto = False
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.setMinimumSize(self._minimo_normal)
        if self._geometria_normal is not None:
            self.setGeometry(self._geometria_normal)
        self.show()
        self._colocar()
