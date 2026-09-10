"""Los dos aparatos que Ajustes ancla encima del grupo que estas tocando (8.7).

Es el injerto de Pulso, y es la diferencia entre unos ajustes y un formulario:
mientras arrastras `pinch_on` la regla de umbral se mueve **bajo tu dedo** por
delante de la senyal de verdad, y mientras arrastras el corte del suavizado
tienes en la misma pantalla las dos mitades del trato -suavidad y retardo- en
vez de tener que ir a probarlo y volver.

Dos reglas que estos dos aparatos respetan a rajatabla:

* **Nada inventado (principio 4).** La traza sale de ``EngineOutput.pinch_ratio``
  y el temblor de las posiciones de puntero que de verdad han pasado. Sin motor
  en marcha no se dibuja una onda bonita: se dice que no hay senyal y se ensenya
  solo lo que si es cierto, que son los umbrales que estas poniendo tu. Y el
  retardo lleva escrita la cuenta con la que sale, en ``caption``.
* **Ningun QTimer y ningun latido en balde (ley 2).** No hay animacion que
  mantener: la traza se repinta cuando llega una muestra y las reglas cuando
  mueves el deslizador. Un aparato que no recibe nada no pinta nada y no pide
  latido. Los dos heredan de ``Inset``, o sea que el pozo E1 y su filo invertido
  los pinta ``glass.py`` y aqui solo se dibuja dentro.

El retardo del suavizado es una cuenta, no una medida, y por eso se ensenya con
la formula al lado. ``core/filters.py`` filtra en **pixeles de pantalla**: el
corte efectivo es ``min_cutoff + beta * velocidad`` en px/s, y un paso bajo de
primer orden con corte ``fc`` arrastra ``tau = 1 / (2*pi*fc)`` segundos. De ahi
salen los dos numeros: el de la mano quieta y el de la mano moviendose.
"""
from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from .. import theme, tipo
from ..kit.base import Inset
from ..tokens import R_MD

__all__ = ["Osciloscopio", "MedidorPuntero", "VELOCIDAD_REF"]

#: Velocidad de mano a la que se ensenya el segundo numero del retardo. 500 px/s
#: es un gesto normal de apuntar en una pantalla de 2560: media pantalla en un
#: segundo. Con la referencia mas alta el numero sale precioso y no se parece a
#: lo que haces.
VELOCIDAD_REF = 500.0

#: Alto de los dos aparatos. El osciloscopio son los 180 px del apartado 8.7.
ALTO_OSC = 180
ALTO_MEDIDOR = 132

#: Techo del eje del osciloscopio. El pinch abierto se va por encima de 1.0 y no
#: aporta nada: lo que se juzga esta entre el cierre y la apertura.
PINCH_TECHO = 0.90
MUESTRAS = 260


def _tenue(hex_color: str, alfa: float) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alfa)))
    return c


class Osciloscopio(Inset):
    """La senyal de pinch con las dos reglas de umbral encima.

    El eje vertical va de 0 (dedos juntos) arriba a ``PINCH_TECHO`` abajo, o sea
    **al reves de lo natural**, y a proposito: asi cerrar la mano hace que la
    traza suba hacia las reglas y "cruzar el umbral" se ve como cruzarlo. Con el
    eje al derecho la senyal caia al cerrar y todo el mundo lee eso como que
    algo va a peor.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent, radius=R_MD, padding=14)
        self._on = 0.34
        self._off = 0.40
        self._muestras: deque[float] = deque(maxlen=MUESTRAS)
        self._vivo = False
        self.setFixedHeight(ALTO_OSC)

    # -- entrada ------------------------------------------------------------
    def set_umbrales(self, on: float, off: float) -> None:
        """Sin suavizar: la especificacion pide la regla bajo el dedo, y un
        muelle de por medio la dejaria siempre un poco por detras."""
        if abs(on - self._on) < 1e-6 and abs(off - self._off) < 1e-6:
            return
        self._on, self._off = float(on), float(off)
        self.update()

    def push(self, ratio: float) -> None:
        if not math.isfinite(ratio):
            return
        self._muestras.append(float(ratio))
        self._vivo = True
        self.update()

    def olvidar(self) -> None:
        """El motor se ha parado: la traza vieja dejaria de ser cierta."""
        if not self._muestras:
            return
        self._muestras.clear()
        self._vivo = False
        self.update()

    # -- pintado ------------------------------------------------------------
    def _y(self, rect: QRectF, ratio: float) -> float:
        k = max(0.0, min(1.0, ratio / PINCH_TECHO))
        return rect.bottom() - k * rect.height()

    def paint_content(self, painter: QPainter, rect: QRectF) -> None:
        t = theme.C.tokens
        alto_pie = tipo.metrics("caption").height()
        pozo = QRectF(rect.left(), rect.top(), rect.width(),
                      max(40.0, rect.height() - alto_pie - 6.0))

        y_on = self._y(pozo, self._on)
        y_off = self._y(pozo, self._off)

        # la banda de histeresis: entre las dos reglas el pinch conserva el
        # estado que traia, y esa es la unica razon de que sean dos
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_tenue(t.color.accent, 0.10))
        painter.drawRect(QRectF(pozo.left(), min(y_on, y_off), pozo.width(),
                                abs(y_off - y_on)))

        self._traza(painter, pozo, t)

        # las reglas van por encima de la traza: son lo que estas moviendo
        for y, color, ancho, guion in (
                (y_off, _tenue(t.color.accent, 0.55), 1.0, True),
                (y_on, QColor(t.color.accent), 1.6, False)):
            pluma = QPen(color, ancho)
            if guion:
                pluma.setDashPattern([3.0, 3.0])
            painter.setPen(pluma)
            painter.drawLine(QPointF(pozo.left(), y), QPointF(pozo.right(), y))

        painter.setFont(tipo.font("axis"))
        m = tipo.metrics("axis")
        for y, texto in ((y_on, f"cierra {self._on:.2f}".replace(".", ",")),
                         (y_off, f"abre {self._off:.2f}".replace(".", ","))):
            ancho = m.horizontalAdvance(texto) + 4.0
            painter.setPen(QColor(t.color.accent))
            painter.drawText(
                QRectF(pozo.right() - ancho, y - m.height() - 1.0, ancho,
                       m.height()),
                int(Qt.AlignmentFlag.AlignRight
                    | Qt.AlignmentFlag.AlignVCenter), texto)

        pie = ("Señal en vivo: distancia pulgar-índice ya suavizada"
               if self._vivo else
               "Sin señal: el motor está parado. Las reglas son las tuyas")
        painter.setFont(tipo.font("caption"))
        painter.setPen(QColor(t.text.quiet if not self._vivo
                              else t.text.tertiary))
        painter.drawText(
            QRectF(rect.left(), rect.bottom() - alto_pie, rect.width(),
                   alto_pie),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            pie)

    def _traza(self, painter: QPainter, pozo: QRectF, t) -> None:
        n = len(self._muestras)
        if n < 2:
            return
        paso = pozo.width() / float(MUESTRAS - 1)
        x0 = pozo.right() - (n - 1) * paso
        puntos = QPolygonF([QPointF(x0 + i * paso, self._y(pozo, v))
                            for i, v in enumerate(self._muestras)])
        pluma = QPen(QColor(t.text.secondary), 1.4)
        pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pluma)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(puntos)

        # la ultima muestra en gordo, y en acento si el pinch esta cerrado: es
        # el unico punto de todo el grafico que dice algo del presente
        ultimo = puntos[-1]
        cerrado = self._muestras[-1] <= self._on
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.color.accent if cerrado else t.text.primary))
        painter.drawEllipse(ultimo, 2.8, 2.8)


class MedidorPuntero(Inset):
    """Retardo que anyade el suavizado y temblor que de verdad queda.

    Las dos mitades del trato del apartado 8.7, una al lado de la otra. El
    retardo es una cuenta cerrada y va con su formula debajo; el temblor es una
    medida y solo aparece cuando hay puntos suficientes para que signifique
    algo (misma regla de honestidad que el apartado 6.4).
    """

    MIN_PUNTOS = 60

    def __init__(self, parent=None) -> None:
        super().__init__(parent, radius=R_MD, padding=14)
        self._cutoff = 0.60
        self._beta = 0.020
        self._temblor = float("nan")
        self._puntos = 0
        self.setFixedHeight(ALTO_MEDIDOR)

    # -- entrada ------------------------------------------------------------
    def set_filtro(self, min_cutoff: float, beta: float) -> None:
        if (abs(min_cutoff - self._cutoff) < 1e-9
                and abs(beta - self._beta) < 1e-12):
            return
        self._cutoff = max(1e-3, float(min_cutoff))
        self._beta = max(0.0, float(beta))
        self.update()

    def set_temblor(self, px: float, puntos: int) -> None:
        self._temblor = float(px)
        self._puntos = int(puntos)
        self.update()

    def olvidar(self) -> None:
        if self._puntos == 0:
            return
        self._temblor, self._puntos = float("nan"), 0
        self.update()

    # -- cuentas ------------------------------------------------------------
    @staticmethod
    def _retardo_ms(cutoff: float) -> float:
        return 1000.0 / (2.0 * math.pi * max(cutoff, 1e-6))

    def retardo_quieto(self) -> float:
        return self._retardo_ms(self._cutoff)

    def retardo_moviendo(self) -> float:
        return self._retardo_ms(self._cutoff + self._beta * VELOCIDAD_REF)

    # -- pintado ------------------------------------------------------------
    def paint_content(self, painter: QPainter, rect: QRectF) -> None:
        from ..charts import tremor_verdict

        t = theme.C.tokens
        col = (rect.width() - 24.0) / 2.0
        izq = QRectF(rect.left(), rect.top(), col, rect.height())
        der = QRectF(rect.right() - col, rect.top(), col, rect.height())

        m_over = tipo.metrics("overline")
        m_met = tipo.metrics("metric")
        m_cap = tipo.metrics("caption")

        def rotulo(caja: QRectF, texto: str) -> None:
            painter.setFont(tipo.font("overline"))
            painter.setPen(QColor(t.text.quiet))
            painter.drawText(
                QRectF(caja.left(), caja.top(), caja.width(), m_over.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                tipo.text("overline", texto))

        y_cifra = rect.top() + m_over.height() + 8.0

        # ---- retardo -------------------------------------------------------
        rotulo(izq, "Retardo del suavizado")
        quieto, moviendo = self.retardo_quieto(), self.retardo_moviendo()
        painter.setFont(tipo.font("metric"))
        painter.setPen(QColor(t.text.primary))
        cifra = f"{quieto:.0f}"
        painter.drawText(
            QRectF(izq.left(), y_cifra, izq.width(), m_met.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            cifra)
        ancho = m_met.horizontalAdvance(cifra) + 6.0
        painter.setFont(tipo.font("caption"))
        painter.setPen(QColor(t.text.tertiary))
        painter.drawText(
            QRectF(izq.left() + ancho, y_cifra, izq.width() - ancho,
                   m_met.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            f"ms con la mano quieta · {moviendo:.0f} ms a "
            f"{VELOCIDAD_REF:.0f} px/s")

        y_pie = rect.bottom() - m_cap.height()
        painter.setPen(QColor(t.text.quiet))
        painter.drawText(
            QRectF(izq.left(), y_pie, izq.width(), m_cap.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            "1000 / (2π · corte + β · velocidad)")

        # ---- temblor -------------------------------------------------------
        rotulo(der, "Temblor del puntero")
        hay = self._puntos >= self.MIN_PUNTOS and math.isfinite(self._temblor)
        if hay:
            palabra, color = tremor_verdict(self._temblor)
            cifra = f"{self._temblor:.1f}".replace(".", ",")
            painter.setFont(tipo.font("metric"))
            painter.setPen(QColor(t.text.primary))
            painter.drawText(
                QRectF(der.left(), y_cifra, der.width(), m_met.height()),
                int(Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter), cifra)
            ancho = m_met.horizontalAdvance(cifra) + 6.0
            painter.setFont(tipo.font("caption"))
            painter.setPen(QColor(t.text.tertiary))
            painter.drawText(
                QRectF(der.left() + ancho, y_cifra, der.width() - ancho,
                       m_met.height()),
                int(Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter), "px")
            painter.setFont(tipo.font("overline"))
            painter.setPen(QColor(color))
            painter.drawText(
                QRectF(der.left(), y_pie, der.width(), m_cap.height()),
                int(Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter),
                tipo.text("overline", palabra))
        else:
            painter.setFont(tipo.font("caption"))
            painter.setPen(QColor(t.text.quiet))
            painter.drawText(
                QRectF(der.left(), y_cifra, der.width(), m_met.height()),
                int(Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter),
                "Sin datos: mueve el puntero con el motor en marcha")
            painter.drawText(
                QRectF(der.left(), y_pie, der.width(), m_cap.height()),
                int(Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter),
                "media de |p−2p′+p″| sobre los últimos 300 puntos")
