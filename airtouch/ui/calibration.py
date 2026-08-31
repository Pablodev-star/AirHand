"""Calibracion de las cuatro esquinas.

Apuntas a cada esquina de la pantalla y mantienes el pinch. Con esos cuatro
puntos se calcula una homografia que corrige el angulo de la camara y la
distorsion del gran angular del movil. Es lo que hace que apuntar sea preciso
en vez de aproximado.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..config import Config
from ..core.mapping import PointerMapper
from ..core.screen import primary_screen
from ..gestures.engine import EngineOutput
from ..overlay import style as S

_LABELS = [
    "Arriba a la izquierda",
    "Arriba a la derecha",
    "Abajo a la derecha",
    "Abajo a la izquierda",
]
_HOLD_S = 1.0
_INSET = 0.055          # las dianas no van pegadas al borde: es incomodo apuntar


class CalibrationWindow(QWidget):
    finished = Signal(bool)          # True si se completo

    def __init__(self, cfg: Config, parent: QWidget | None = None) -> None:
        super().__init__(None)
        self.cfg = cfg
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # geometria en unidades de Qt (logicas), no las fisicas de Win32
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        else:
            s = primary_screen()
            self.setGeometry(s.x, s.y, s.w, s.h)

        self.step = 0
        self.samples: list[tuple[float, float]] = []
        self._hold_start: float | None = None
        self._hold = 0.0
        self._raw: tuple[float, float] | None = None
        self._pinching = False
        self._flash_until = 0.0
        self._done = False
        # tras capturar una esquina hay que ABRIR la mano antes de la siguiente;
        # si no, mantener el pinch encadenaba las cuatro de golpe
        self._need_release = False

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # ---------------- API ----------------
    def begin(self) -> None:
        self.step = 0
        self.samples.clear()
        self._hold_start = None
        self._done = False
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self._timer.start()

    def on_output(self, out: EngineOutput) -> None:
        self._raw = out.raw_pointer
        self._pinching = out.pinching

    # ---------------- logica ----------------
    def _target_norm(self) -> tuple[float, float]:
        i = self.step
        x = _INSET if i in (0, 3) else 1.0 - _INSET
        y = _INSET if i in (0, 1) else 1.0 - _INSET
        return x, y

    def _tick(self) -> None:
        now = time.perf_counter()
        if self._done:
            self.update()
            return

        if not self._pinching:
            self._need_release = False

        if self._pinching and not self._need_release and self._raw is not None:
            if self._hold_start is None:
                self._hold_start = now
            self._hold = min((now - self._hold_start) / _HOLD_S, 1.0)
            if self._hold >= 1.0:
                self.samples.append(self._raw)
                self._flash_until = now + 0.35
                self._hold_start = None
                self._hold = 0.0
                self._need_release = True
                self.step += 1
                if self.step >= 4:
                    self._commit()
        else:
            self._hold_start = None
            self._hold = 0.0
        self.update()

    def _commit(self) -> None:
        target = primary_screen()
        try:
            h = PointerMapper.compute_homography(self.samples, target)
        except Exception:
            self._done = True
            QTimer.singleShot(400, lambda: self._close(False))
            return
        self.cfg.mapping.homography = h
        self.cfg.save()
        self._done = True
        QTimer.singleShot(700, lambda: self._close(True))

    def _close(self, ok: bool) -> None:
        self._timer.stop()
        self.close()
        self.finished.emit(ok)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._close(False)

    # ---------------- pintado ----------------
    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(8, 9, 12, 232))

        w, h = self.width(), self.height()

        if self._done:
            p.setFont(S.font(22))
            p.setPen(QColor(126, 231, 165))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Calibración completada")
            p.end()
            return

        # dianas ya capturadas
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(self.step):
            x = _INSET if i in (0, 3) else 1.0 - _INSET
            y = _INSET if i in (0, 1) else 1.0 - _INSET
            p.setBrush(QColor(126, 231, 165, 210))
            p.drawEllipse(QPointF(x * w, y * h), 9, 9)

        tx, ty = self._target_norm()
        cx, cy = tx * w, ty * h

        glow = S.glow_gradient(cx, cy, 90, QColor(255, 255, 255, 40))
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 90, 90)

        pen = QPen(QColor(255, 255, 255, 70))
        pen.setWidthF(1.6)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), 46, 46)

        if self._hold > 0.001:
            pen = QPen(QColor(150, 200, 255, 240))
            pen.setWidthF(5.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(QRectF(cx - 46, cy - 46, 92, 92), 90 * 16,
                      -int(self._hold * 360 * 16))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawEllipse(QPointF(cx, cy), 8, 8)

        # puntero en crudo, para que veas que te esta siguiendo
        if self._raw is not None:
            rx, ry = self._raw[0] * w, self._raw[1] * h
            p.setBrush(QColor(150, 200, 255, 170 if self._pinching else 90))
            p.drawEllipse(QPointF(rx, ry), 7, 7)

        # textos
        p.setFont(S.font(26))
        p.setPen(QColor(255, 255, 255, 240))
        p.drawText(QRectF(0, h * 0.40, w, 44), Qt.AlignmentFlag.AlignCenter,
                   f"{self.step + 1} de 4 · {_LABELS[self.step]}")

        p.setFont(S.font(14))
        if self._need_release:
            p.setPen(QColor(255, 196, 92, 235))
            msg = "Abre la mano antes de la siguiente esquina"
        else:
            p.setPen(QColor(255, 255, 255, 150))
            msg = "Apunta con el índice al círculo y mantén el pinch un segundo"
        p.drawText(QRectF(0, h * 0.40 + 48, w, 30), Qt.AlignmentFlag.AlignCenter, msg)
        p.setPen(QColor(255, 255, 255, 100))
        p.drawText(QRectF(0, h - 60, w, 26), Qt.AlignmentFlag.AlignCenter,
                   "Esc para cancelar")
        p.end()
