"""Hito de riesgo del apartado 2: tres láminas E2/E3/E4 sobre el lienzo vivo.

    .venv\\Scripts\\python.exe tools\\prueba_cristal.py <carpeta-destino>

Pantalla desechable. Existe para contestar una sola pregunta antes de construir
seis pantallas encima: ¿el recorte del lienzo pre-desenfocado más el lavado se
lee como cristal, o se lee como un rectángulo gris plano? Se contesta mirando
los PNG, no leyendo el código.

Las láminas se colocan a propósito una sobre la mancha de luz, otra sobre la
zona fría y otra a caballo entre las dos: si el recorte funciona, las tres
tienen que salir con un fondo distinto. Si salen iguales, el paralaje o el
mapeo de coordenadas están mal y no hay cristal.

También mide el coste real de `paint_sheet` (200 repeticiones) e imprime el
escalon de luminancia entre lienzo y vidrio, que es el número que decide si el
modo claro sobrevive.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from PySide6.QtCore import QPoint, QRectF, Qt                    # noqa: E402
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget              # noqa: E402

from airtouch.ui import glass, theme, tipo                       # noqa: E402
from airtouch.ui.tokens import R_LG, R_XL                        # noqa: E402

ANCHO, ALTO = 1180, 720


def grafico_de_prueba(w: int, h: int, color: str) -> QPixmap:
    """Un sangrado falso: la silueta de un área, como la de una tarjeta real."""
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    grad = QLinearGradient(0, h * 0.35, 0, h)
    c = QColor(color)
    c.setAlphaF(0.90)
    grad.setColorAt(0.0, c)
    tail = QColor(color)
    tail.setAlpha(0)
    grad.setColorAt(1.0, tail)
    path_pts = []
    import math
    for i in range(w + 1):
        t = i / w
        y = h * (0.62 - 0.22 * math.sin(t * 6.0) - 0.10 * math.sin(t * 17.0))
        path_pts.append((i, y))
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.moveTo(0, h)
    for x, y in path_pts:
        path.lineTo(x, y)
    path.lineTo(w, h)
    path.closeSubpath()
    p.fillPath(path, grad)
    p.end()
    return pm


class Prueba(QWidget):
    """Lienzo + tres láminas. Nada más: cualquier adorno enmascara el problema."""

    def __init__(self) -> None:
        super().__init__()
        self.resize(ANCHO, ALTO)
        self.canvas = glass.CanvasSource(theme.C.tokens)
        self.canvas.resize(ANCHO, ALTO)
        glass.set_active_canvas(self.canvas)
        self.bleed = grafico_de_prueba(360, 200, theme.C.accent)

    def retema(self) -> None:
        self.canvas.set_tokens(theme.C.tokens)
        self.bleed = grafico_de_prueba(360, 200, theme.C.accent)

    # las tres láminas, cada una sobre una parte distinta del lienzo
    def laminas(self) -> list[tuple[str, QRectF, float, bool]]:
        return [
            # sobre la mancha de luz de arriba-izquierda
            ("E2", QRectF(64, 96, 360, 240), R_LG, True),
            # a caballo entre la luz y el tinte de la derecha
            ("E3", QRectF(460, 156, 360, 240), R_LG, False),
            # sobre la zona fría de abajo-derecha
            ("E4", QRectF(690, 420, 400, 220), R_XL, False),
        ]

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.canvas.paint(p)

        etiqueta = tipo.font("overline")
        titulo = tipo.font("h1")
        cuerpo = tipo.font("body")

        for nombre, rect, radio, con_sangrado in self.laminas():
            bleed = self.bleed if con_sangrado else None
            path = glass.paint_sheet(p, rect, nombre, radio,
                                     canvas=self.canvas,
                                     canvas_origin=QPoint(0, 0),
                                     bleed=bleed)
            p.save()
            p.setClipPath(path)
            r = glass.sheet_rect(rect, nombre)
            pad = 24 if nombre == "E4" else 20
            p.setPen(QColor(theme.C.ink.tertiary))
            p.setFont(etiqueta)
            p.drawText(QRectF(r.left() + pad, r.top() + pad, r.width() - 2 * pad, 16),
                       Qt.AlignmentFlag.AlignLeft, tipo.text("overline", f"lámina {nombre}"))
            p.setPen(QColor(theme.C.ink.primary))
            p.setFont(titulo)
            p.drawText(QRectF(r.left() + pad, r.top() + pad + 22,
                              r.width() - 2 * pad, 30),
                       Qt.AlignmentFlag.AlignLeft, "Cristal vivo")
            p.setPen(QColor(theme.C.ink.secondary))
            p.setFont(cuerpo)
            p.drawText(QRectF(r.left() + pad, r.bottom() - pad - 20,
                              r.width() - 2 * pad, 20),
                       Qt.AlignmentFlag.AlignLeft,
                       "recorte + lavado + filos" if not con_sangrado
                       else "con sangrado y velo")
            p.restore()

            # una placa E1 dentro de la E3: comprueba el filo invertido y el
            # radio concéntrico, que es donde se ve si el vidrio parece fabricado
            if nombre == "E3":
                r = glass.sheet_rect(rect, nombre)
                hueco = QRectF(r.left() + 20, r.bottom() - 116, r.width() - 40, 64)
                glass.paint_sheet(p, hueco, "E1", radio - 20, canvas=self.canvas,
                                  canvas_origin=QPoint(0, 0))
        p.end()


def medir(w: Prueba) -> float:
    """Coste de paint_sheet en ms, sobre un pixmap fuera de pantalla."""
    pm = QPixmap(ANCHO, ALTO)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(64, 96, 360, 240)
    # una pasada en frío para que el atlas ya tenga sus tiles: medir la
    # generación mezclada con el pintado daría un número que no existe en la vida
    glass.paint_sheet(p, rect, "E2", R_LG, canvas=w.canvas)
    t0 = time.perf_counter()
    for _ in range(200):
        glass.paint_sheet(p, rect, "E2", R_LG, canvas=w.canvas)
    t1 = time.perf_counter()
    p.end()
    return (t1 - t0) * 1000.0 / 200.0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    destino = Path(argv[1])
    destino.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv[:1])
    w = Prueba()
    w.show()

    for tema in ("dark", "light"):
        theme.apply(tema)
        app.setStyleSheet(theme.qss())
        w.retema()
        w.update()
        fin = time.time() + 0.8
        while time.time() < fin:
            app.processEvents()
            time.sleep(0.01)
        pm = w.grab()
        ruta = destino / f"cristal-{tema}.png"
        pm.save(str(ruta))
        paso = glass.wash_luminance_step() * 100.0
        print(f"{tema:5}  {ruta.name}  {pm.width()}x{pm.height()}  "
              f"escalon de luminancia lienzo-vidrio {paso:.1f} %")

    theme.apply("dark")
    w.retema()
    print(f"\npaint_sheet E2 360x240: {medir(w):.3f} ms  "
          f"(atlas: {glass.ATLAS.built} tiles)")
    w.hide()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
