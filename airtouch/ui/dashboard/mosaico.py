"""Zona B: la rejilla del mosaico y el reparto de datos (apartado 8.2).

Seis columnas, canalon 16, y **dos alturas de fila distintas**: 300 arriba y 190
abajo. Esa diferencia es toda la jerarquia de la pantalla; no hay ni un color ni
una linea haciendo de titulo de seccion.

La pagina no guarda datos: reparte. Recibe ``output_ready``, ``stats_ready`` y
``frame_ready`` del armazon y se los pasa a la tarjeta que sabe que hacer con
cada uno. Una tarjeta que no quiere un dato simplemente no implementa su gancho.

La rejilla se **encoge proporcionalmente** cuando el area no da de si. Es lo que
permite que el panel siga siendo el panel en un portatil de 1366x768 sin tener
que inventar una segunda maquetacion: las tarjetas se acercan, las cifras no
cambian de tamaño (de eso ya se encarga la segunda escala de ``tipo.py``), y la
franja de novedades es la primera en irse porque es la unica que puede faltar.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Signal
from PySide6.QtWidgets import QWidget

from ..telemetry import Telemetry
from ..tokens import GUTTER
from .comun import Pagina
from .tarjetas import (ALTO_FILA_1, ALTO_FILA_2, ALTO_NOVEDADES, COLUMNAS,
                       FranjaNovedades, TarjetaEnlace, TarjetaGestos,
                       TarjetaMano, TarjetaRendimiento, TarjetaSeguridad)

__all__ = ["Mosaico"]

#: Alto minimo al que se deja encoger una fila antes de dejar de encoger. Por
#: debajo de esto una tarjeta con titulo de 38 px deja de tener sitio para el
#: titulo, y lo que se veria seria una lamina rota.
ALTO_MINIMO_1 = 200.0
ALTO_MINIMO_2 = 140.0


class Mosaico(Pagina):
    """La pagina de portada. El mosaico llena su area entera, sin margen."""

    TITULO = "Mosaico"
    MARGEN = 0.0

    abrir = Signal(str, QRectF)          # destino, vidrio de la tarjeta origen

    def __init__(self, cfg, ctl, tele: Telemetry,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.ctl = ctl
        self.tele = tele

        self.rendimiento = TarjetaRendimiento(tele, self)
        self.mano = TarjetaMano(ctl, self)
        self.gestos = TarjetaGestos(tele, self)
        self.seguridad = TarjetaSeguridad(ctl, self)
        self.enlace = TarjetaEnlace(ctl, self)
        self.novedades = FranjaNovedades(self)
        self.novedades.hide()

        self.tarjetas = (self.rendimiento, self.mano, self.gestos,
                         self.seguridad, self.enlace)
        for tarjeta in self.tarjetas:
            tarjeta.pulsada.connect(self._pulsada)

    # -- navegacion ---------------------------------------------------------
    def _pulsada(self, destino: str) -> None:
        """Pasa el vidrio de la tarjeta: la pagina profunda nace de el (8.4)."""
        origen = self.sender()
        caja = QRectF()
        if isinstance(origen, QWidget):
            caja = origen.glass_box().translated(origen.pos())
        self.abrir.emit(destino, caja)

    # -- datos --------------------------------------------------------------
    def on_output(self, out) -> None:
        self.mano.on_output(out)

    def on_stats(self, stats: dict) -> None:
        self.rendimiento.on_stats(stats)
        self.seguridad.on_stats(stats)
        self.enlace.on_stats(stats)
        self.gestos.update()

    def on_frame(self, frame, estado) -> None:
        self.mano.on_frame(frame, estado)

    def set_cuentas(self, cuentas: dict[str, int]) -> None:
        self.gestos.set_cuentas(cuentas)

    def set_novedades(self, items) -> None:
        self.novedades.set_items(items)
        self.colocar()

    # -- geometria ----------------------------------------------------------
    def caja_de(self, destino: str) -> QRectF:
        """El vidrio de la tarjeta que abre ``destino``, en coordenadas propias.

        Lo usa el armazon para volver del zoom: la pagina profunda se encoge
        hasta la tarjeta de la que salio, no hasta el centro de la pantalla.
        """
        for tarjeta in self.tarjetas:
            if tarjeta.ABRE == destino:
                return tarjeta.glass_box().translated(tarjeta.pos())
        return QRectF(self.area)

    def _alturas(self) -> tuple[float, float, float]:
        """Las tres alturas de fila, ya encogidas a lo que hay."""
        hay_novedades = bool(self.novedades.items)
        alto_3 = ALTO_NOVEDADES if hay_novedades else 0.0
        huecos = GUTTER * (2 if hay_novedades else 1)
        libre = self.area.height() - huecos - alto_3
        pedido = ALTO_FILA_1 + ALTO_FILA_2
        if pedido <= 0.0:
            return ALTO_FILA_1, ALTO_FILA_2, alto_3
        if libre >= pedido:
            # Y tambien CRECEN. Con alturas fijas, en una ventana alta sobraba
            # medio panel vacio debajo de las tarjetas y la jerarquia por
            # tamanyo -que es toda la idea del mosaico- se perdia en el hueco.
            # Se topa en 1.6 para que una pantalla muy alta no las estire hasta
            # dejarlas ridiculas.
            k = min(1.6, libre / pedido)
            return ALTO_FILA_1 * k, ALTO_FILA_2 * k, alto_3
        k = max(0.0, libre) / pedido
        return (max(ALTO_MINIMO_1, ALTO_FILA_1 * k),
                max(ALTO_MINIMO_2, ALTO_FILA_2 * k), alto_3)

    def _columna(self, x0: float, primera: int, cuantas: int,
                 ancho_col: float) -> tuple[float, float]:
        izq = x0 + primera * (ancho_col + GUTTER)
        return izq, cuantas * ancho_col + (cuantas - 1) * GUTTER

    def colocar(self) -> None:
        if self.area.isEmpty():
            return
        x0, y = self.area.left(), self.area.top()
        ancho_col = (self.area.width() - GUTTER * (COLUMNAS - 1)) / COLUMNAS
        h1, h2, h3 = self._alturas()

        izq, w = self._columna(x0, 0, 4, ancho_col)
        self.rendimiento.place(QRectF(izq, y, w, h1))
        izq, w = self._columna(x0, 4, 2, ancho_col)
        self.mano.place(QRectF(izq, y, w, h1))
        y += h1 + GUTTER

        for i, tarjeta in enumerate((self.gestos, self.seguridad, self.enlace)):
            izq, w = self._columna(x0, i * 2, 2, ancho_col)
            tarjeta.place(QRectF(izq, y, w, h2))
        y += h2 + GUTTER

        if h3:
            self.novedades.place(QRectF(x0, y, self.area.width(), h3))
