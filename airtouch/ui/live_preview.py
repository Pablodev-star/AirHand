"""Vista de la camara con la deteccion superpuesta.

Es la herramienta de diagnostico mas util de toda la app: si aqui el esqueleto
de la mano sigue bien a tus dedos, el problema esta en los ajustes; si no, esta
en la camara, la luz o el encuadre.
"""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme
from ..core.frame_state import (
    FINGER_TIPS, HAND_CONNECTIONS, INDEX_TIP, THUMB_TIP, FrameState,
)

def _bone() -> QColor:
    # el esqueleto va sobre una foto, no sobre el tema: siempre blanco
    return QColor(255, 255, 255, 200)


def _joint() -> QColor:
    return QColor(255, 255, 255, 238)


_BONE = QColor(255, 255, 255, 170)
_JOINT = QColor(255, 255, 255, 225)
_TIP = QColor(150, 200, 255, 240)
_PINCH_OK = QColor(126, 231, 165)
_PINCH_NO = QColor(255, 255, 255, 130)


class LivePreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pix: QPixmap | None = None
        self._state: FrameState | None = None
        self.show_skeleton = True
        self.show_region = True
        self.region: tuple[float, float, float, float] | None = None
        self.pinch_on = 0.34
        self.placeholder = "Sin señal de cámara"

    def set_frame(self, frame_bgr: np.ndarray, state: FrameState) -> None:
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(img)
        self._state = state
        self.update()

    def clear(self) -> None:
        self._pix = None
        self._state = None
        self.update()

    # ---------------- pintado ----------------
    def _fit_rect(self) -> QRectF:
        if self._pix is None:
            return QRectF(self.rect())
        pw, ph = self._pix.width(), self._pix.height()
        if pw == 0 or ph == 0:
            return QRectF(self.rect())
        scale = min(self.width() / pw, self.height() / ph)
        w, h = pw * scale, ph * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.C.surface_sunken))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)

        if self._pix is None:
            p.setPen(QColor(theme.C.text_faint))
            f = QFont("Segoe UI", 12)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder)
            p.end()
            return

        r = self._fit_rect()
        p.drawPixmap(r, self._pix, QRectF(self._pix.rect()))

        if self.show_region and self.region:
            x0, y0, x1, y1 = self.region
            pen = QPen(QColor(255, 255, 255, 70))
            pen.setWidthF(1.4)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(
                QRectF(r.x() + x0 * r.width(), r.y() + y0 * r.height(),
                       (x1 - x0) * r.width(), (y1 - y0) * r.height()), 8, 8)

        if self.show_skeleton and self._state:
            self._paint_hands(p, r)
        p.end()

    def _paint_hands(self, p: QPainter, r: QRectF) -> None:
        assert self._state is not None
        for hand in self._state.hands:
            pts = [QPointF(r.x() + float(x) * r.width(), r.y() + float(y) * r.height())
                   for x, y, _z in hand.lm]

            pen = QPen(_bone())
            pen.setWidthF(2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            for a, b in HAND_CONNECTIONS:
                p.drawLine(pts[a], pts[b])

            p.setPen(Qt.PenStyle.NoPen)
            for i, pt in enumerate(pts):
                if i in FINGER_TIPS:
                    p.setBrush(_TIP)
                    p.drawEllipse(pt, 4.2, 4.2)
                else:
                    p.setBrush(_joint())
                    p.drawEllipse(pt, 2.4, 2.4)

            # linea del pinch, verde cuando esta cerrado
            closed = hand.pinch_ratio < self.pinch_on
            pen = QPen(_PINCH_OK if closed else _PINCH_NO)
            pen.setWidthF(2.6 if closed else 1.4)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(pts[THUMB_TIP], pts[INDEX_TIP])

            mid = QPointF((pts[THUMB_TIP].x() + pts[INDEX_TIP].x()) / 2,
                          (pts[THUMB_TIP].y() + pts[INDEX_TIP].y()) / 2)
            p.setPen(QColor(255, 255, 255, 200))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(QRectF(mid.x() - 30, mid.y() - 24, 60, 16),
                       Qt.AlignmentFlag.AlignCenter, f"{hand.pinch_ratio:.2f}")

            label = "Izq" if hand.label == "Left" else "Der"
            wrist = pts[0]
            p.setPen(QColor(255, 255, 255, 180))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            p.drawText(QRectF(wrist.x() - 26, wrist.y() + 6, 52, 16),
                       Qt.AlignmentFlag.AlignCenter, label)
