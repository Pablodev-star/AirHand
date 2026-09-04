"""Muestra de todos los mandos del kit, en todos sus estados y en los dos temas.

    .venv\\Scripts\\python.exe tools\\prueba_mandos.py <carpeta-destino>

Pantalla desechable, como `prueba_cristal.py`. Existe porque el apartado 11 dice
que el modo claro es donde mueren estos sistemas, y un mando que en oscuro se lee
perfectamente puede desaparecer sobre una lámina blanca sin que el código lo
delate. Aquí no se deduce: se mira el PNG.

Los estados se fuerzan tocando el estado interno de cada mando (`_hover.jump`,
`_press.jump`...). Es lo único razonable: no hay manera de tener cinco botones
pulsados a la vez con un solo ratón.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from PySide6.QtCore import QPoint, QRect, QRectF, Qt           # noqa: E402
from PySide6.QtGui import QColor, QPainter                     # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget            # noqa: E402

from airtouch.ui import glass, motion, theme, tipo             # noqa: E402
from airtouch.ui.kit import (Button, Chip, Field, Segmented, SettingRow,
                             Slider, Toggle)                   # noqa: E402
from airtouch.ui.kit.base import Sheet                         # noqa: E402
from airtouch.ui.tokens import R_XL                            # noqa: E402

ANCHO, ALTO = 1420, 1180
COL_X = (250, 470, 690, 910, 1130)
ESTADOS = ("reposo", "hover", "pulsado", "deshabilitado", "foco")
FILA = 84
Y0 = 108


def estado(w: QWidget, cual: str) -> QWidget:
    """Congela el mando en uno de los cinco estados, sin animación de por medio."""
    if cual == "hover":
        if isinstance(w, Button):
            w.set_hover(True)
            w._lift.jump(1.0)
        else:
            w._hover.jump(True)
    elif cual == "pulsado":
        w._press.jump(True)
        if isinstance(w, Button):
            w.set_hover(True)
            w._lift.jump(1.0)
        else:
            w._hover.jump(True)
    elif cual == "deshabilitado":
        w.setEnabled(False)
    elif cual == "foco":
        w._focus.jump(True)
    return w


class Muestra(QWidget):
    """Lienzo + una lámina E2 grande con todos los mandos encima."""

    def __init__(self) -> None:
        super().__init__()
        self.resize(ANCHO, ALTO)
        self.canvas = glass.CanvasSource(theme.C.tokens)
        self.canvas.resize(ANCHO, ALTO)
        glass.set_active_canvas(self.canvas)
        self.hoja = QRectF(24, 24, ANCHO - 48, ALTO - 48)
        self.hijos: list[QWidget] = []
        self.construir()

    # -- contenido ----------------------------------------------------------
    def fila(self, y: int, fabrica) -> None:
        for x, cual in zip(COL_X, ESTADOS):
            w = estado(fabrica(), cual)
            w.setParent(self)
            s = w.sizeHint()
            if s.isValid():
                w.resize(s)
            if isinstance(w, Button):
                w.place(QRect(x, y, w.sizeHint().width()
                              - int(w.reserve().left() + w.reserve().right()),
                              Button.HEIGHT))
            else:
                w.move(x, y - w.height() // 2 + 12)
            w.show()
            self.hijos.append(w)

    def construir(self) -> None:
        y = Y0
        self.fila(y, lambda: Toggle(False)); y += FILA
        self.fila(y, lambda: Toggle(True)); y += FILA
        self.fila(y, lambda: Button("Continuar", "primary")); y += FILA
        self.fila(y, lambda: Button("Elegir carpeta")); y += FILA
        self.fila(y, lambda: Button("Restablecer", "ghost")); y += FILA
        self.fila(y, lambda: Chip("ahorro")); y += FILA
        self.fila(y, lambda: Chip("conectado", "ok", checkable=True,
                                  checked=True)); y += FILA
        self.fila(y, lambda: Segmented(["2 min", "20 min", "2 h"], 1)); y += FILA

        # los anchos: no caben cinco por fila, así que van dos y dos
        self.anchos = y + 20
        campo = Field("Buscar en ajustes")
        campo.setParent(self)
        campo.setGeometry(250, self.anchos, 380, campo.height())
        campo.show()
        campo2 = Field("Buscar en ajustes", "puntero")
        campo2.setParent(self)
        campo2.setGeometry(690, self.anchos, 380, campo2.height())
        campo2.show()
        campo2._edit.setFocus()
        self.hijos += [campo, campo2]

        y = self.anchos + 70
        s1 = Slider(0.0, 1.0, 0.34, decimals=2, bubble=False)
        s1.setParent(self)
        s1.setGeometry(250, y, 380, s1.height())
        s1.show()
        s2 = Slider(0.0, 1.0, 0.62, decimals=2)
        s2.setParent(self)
        s2.setGeometry(690, y, 380, s2.height())
        s2._hover.jump(True)
        s2._subs.jump(True)
        s2._bubble.jump(True)
        s2.show()
        self.hijos += [s1, s2]

        y += 100
        f1 = SettingRow("Suavizado del puntero", Slider(0.0, 1.0, 0.45,
                                                        bubble=False),
                        hint="Bajar el corte suaviza el puntero pero añade "
                             "unos 20 ms de retardo",
                        keywords="raton cursor temblor")
        f1.setParent(self)
        f1.setGeometry(250, y, 820, f1.height())
        f1.show()
        f2 = SettingRow("Mostrar el teclado virtual", Toggle(True),
                        keywords="teclas escribir")
        f2.setParent(self)
        f2.setGeometry(250, y + 70, 820, f2.height())
        f2.set_modified(True)
        f2._modified.jump(True)
        f2.show()
        self.hijos += [f1, f2]

        # la materialización, congelada en cuatro instantes de su recorrido
        self.nacimiento = y + 160
        for i, k in enumerate((0.12, 0.35, 0.65, 1.0)):
            b = Button("Perfecto, seguir", "primary", born=False)
            b.setParent(self)
            b._born = True
            b._birth = k
            b._birth_scale.jump(0.96 + 0.04 * k)
            b.place(QRect(250 + i * 230, self.nacimiento, 190, Button.HEIGHT))
            b.show()
            self.hijos.append(b)

    def retema(self) -> None:
        self.canvas.set_tokens(theme.C.tokens)
        for w in self.hijos:
            w.on_theme()
        self.update()

    # -- pintado ------------------------------------------------------------
    def paintEvent(self, event) -> None:
        t = theme.C.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.canvas.paint(p)
        glass.paint_sheet(p, self.hoja, "E2", R_XL, canvas=self.canvas,
                          canvas_origin=QPoint(0, 0))

        p.setFont(tipo.font("overline"))
        p.setPen(QColor(t.text.tertiary))
        for x, cual in zip(COL_X, ESTADOS):
            p.drawText(QRectF(x, 62, 210, 18), Qt.AlignmentFlag.AlignLeft,
                       tipo.text("overline", cual))

        etiquetas = ("Toggle", "Toggle activado", "Button primario",
                     "Button normal", "Button fantasma", "Chip neutro",
                     "Chip con tono", "Segmented")
        p.setFont(tipo.font("caption"))
        p.setPen(QColor(t.text.secondary))
        for i, nombre in enumerate(etiquetas):
            p.drawText(QRectF(56, Y0 + i * FILA - 4, 190, 24),
                       Qt.AlignmentFlag.AlignLeft, nombre)

        p.setFont(tipo.font("overline"))
        p.setPen(QColor(t.text.tertiary))
        for y, nombre in ((self.anchos - 26, "Field"),
                          (self.anchos + 44, "Slider"),
                          (self.anchos + 144, "SettingRow"),
                          (self.nacimiento - 26,
                           "Button primario materializándose")):
            p.drawText(QRectF(56, y, 400, 18), Qt.AlignmentFlag.AlignLeft,
                       tipo.text("overline", nombre))
        p.end()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    destino = Path(argv[1])
    destino.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv[:1])
    w = Muestra()
    w.show()
    w.activateWindow()

    for tema in ("dark", "light"):
        theme.apply(tema)
        app.setStyleSheet(theme.qss())
        w.retema()
        fin = time.time() + 0.9
        while time.time() < fin:
            app.processEvents()
            time.sleep(0.01)
        pm = w.grab()
        ruta = destino / f"mandos-{tema}.png"
        pm.save(str(ruta))
        print(f"{tema:5}  {ruta.name}  {pm.width()}x{pm.height()}")

    print(f"participantes en el latido: {motion.beat.participants}")
    w.hide()
    print(f"tras esconder:              {motion.beat.participants}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
