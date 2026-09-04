"""Las dos piezas de las que cuelga todo el kit: la lamina y el rebaje.

Aqui viven ``Sheet`` (el widget-lamina), ``Inset`` (el rebaje E1) y los dos
mixins que todo widget del kit hereda. Los mixins son la mitad importante del
archivo, porque resuelven de una vez y para todos los dos fallos que la
interfaz vieja repite widget a widget:

* **El latido.** Un widget animado se apunta al ``Beat`` con ``animate()`` y se
  da de baja en ``hideEvent``. La baja no es una cortesia: la interfaz vieja
  tiene siete ``QTimer`` sueltos que siguen despertando la CPU con la ventana
  escondida, y ese es exactamente el fallo que motivo ``motion.py`` entero.
  Aqui no se puede olvidar porque no lo escribe el widget, lo escribe ``Beating``.
* **El tema.** Hoy la interfaz vieja **peta** al cambiar de tema con "Internal
  C++ object already deleted" en cuatro sitios (``wizard.py:50``,
  ``airlink_panel.py:109``, ``handart.py:295``, ``celebrate.py:138``): son
  lambdas conectadas a ``theme.signals.changed`` que nadie desconecta nunca, asi
  que cuando Qt destruye el objeto de C++ la lambda sigue viva y llama a
  ``update()`` sobre un cadaver. El kit no se conecta a la senal: se apunta al
  ``_ThemeBus``, que guarda **referencias debiles**, comprueba la validez del
  objeto de C++ antes de llamar y barre los muertos. Un widget del kit no puede
  dejar una lambda colgada porque no conecta nada.

La otra decision del archivo es geometrica y conviene entenderla antes de tocar
nada: **una lamina reserva dentro de su propia geometria el hueco de su sombra**
(``reserve()``). Qt recorta un hijo a su rectangulo, asi que un widget que
pintase la sombra fuera de el la veria cortada con un canto recto. Por eso el
vidrio no ocupa todo el widget, sino ``rect()`` menos la reserva, y por eso dos
laminas vecinas se colocan con ``gap_between()``, que devuelve el espaciado de
layout -a menudo negativo- que deja el hueco de vidrio a vidrio que pide el
apartado 3.4. Las reservas se solapan sin ensuciarse: son transparentes.
"""
from __future__ import annotations

import math
import weakref

from PySide6.QtCore import (QEvent, QMarginsF, QObject, QPoint, QRect, QRectF,
                            Qt)
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from .. import glass, motion, theme
from ..tokens import (GAP_FLOATING, GAP_SAME, R_FULL, R_LG, R_MD,
                      SHEET_PADDING, Elevation, Ink, Surface, concentric)

__all__ = [
    "bus", "ThemeAware", "Beating", "Sheet", "Inset", "Pill", "Gap",
    "gap_between", "FLASH_MS", "SHADOW_REACH",
]

#: Cuanto dura el destello del filo (apartado 5.5.10: vuelve en 300 ms).
FLASH_MS = 300.0

#: Alcance real del desenfoque del atlas en fraccion del desenfoque nominal.
#: Tres pasadas de caja de anchura ``blur/2`` dan un nucleo con soporte exacto
#: de +-1.5 * (blur/2). Bajarlo achica la reserva y corta la cola de la sombra
#: con un canto recto; subirlo solo desperdicia hueco.
SHADOW_REACH = 0.75

#: Holgura de la reserva: E3 crece un 1.008 al pintarse y hay que dejarle sitio.
_SLACK = 2.0

# En cuanto el alzado arranca se saltan las sombras del nivel alto. No se
# interpolan a proposito, ver ``_lift_elevation``.
_LIFT_SHADOW_AT = 0.02


try:
    from shiboken6 import isValid as _alive
except Exception:  # pragma: no cover - solo si shiboken cambia de nombre
    def _alive(obj: object) -> bool:
        return True


# --------------------------------------------------------------------------- #
# suscripcion al tema con desconexion segura
# --------------------------------------------------------------------------- #

class _ThemeBus(QObject):
    """El unico enganche del kit a ``theme.signals.changed``.

    Un solo ``connect`` en toda la interfaz nueva, y nunca hay que
    desconectarlo. Los suscriptores se guardan por referencia debil y se
    comprueban con ``shiboken6.isValid`` justo antes de llamarlos, que es la
    unica manera de distinguir "el envoltorio de Python sigue vivo" de "el
    objeto de C++ ya no existe". Sin esa comprobacion, cambiar de tema con una
    ventana a medio cerrar tira la aplicacion.
    """

    def __init__(self) -> None:
        super().__init__()
        self.serial = 0
        self._subs: list[weakref.ref] = []
        theme.signals.changed.connect(self._dispatch)

    @property
    def count(self) -> int:
        """Suscriptores vivos. Existe para poder vigilarlo en las pruebas."""
        return sum(1 for r in self._subs if r() is not None)

    def add(self, widget: QWidget) -> None:
        for ref in self._subs:
            if ref() is widget:
                return
        self._subs.append(weakref.ref(widget))

    def discard(self, widget: QWidget) -> None:
        self._subs = [r for r in self._subs if r() is not widget]

    def _dispatch(self, _name: str = "") -> None:
        self.serial += 1
        # Lo que manda el apartado 5.5.11: invalidar los pixmap cacheados. Se
        # hace aqui, una vez, y no en cada widget. El atlas cachea por tinta,
        # asi que los tiles viejos no ensucian nada; lo que sobra es la memoria.
        glass.ATLAS.clear()
        src = glass.active_canvas()
        if src is not None:
            src.set_tokens(theme.C.tokens)

        muertos: list[weakref.ref] = []
        for ref in tuple(self._subs):
            obj = ref()
            if obj is None or not _alive(obj):
                muertos.append(ref)
                continue
            try:
                obj._on_theme_signal(self.serial)
            except RuntimeError:
                # ha muerto entre el isValid y la llamada. Pasa al cerrar.
                muertos.append(ref)
        if muertos:
            # no vale remove(): un suscriptor puede haber creado o destruido
            # otros widgets al retematizarse, y la lista de ahora no es la de
            # cuando empezo el reparto
            self._subs = [r for r in self._subs if r not in muertos]


bus = _ThemeBus()


class ThemeAware:
    """Mixin: el widget se entera del cambio de tema y nunca deja basura.

    El gancho a redefinir es ``on_theme()``. Se llama **solo si el widget esta
    visible**; si estaba escondido se anota el numero de serie y se recupera en
    ``showEvent``, porque retematizar catorce paginas escondidas del asistente
    cada vez que alguien toca el interruptor de tema es trabajo tirado.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._theme_serial = bus.serial
        bus.add(self)

    def on_theme(self) -> None:
        self.update()

    def _on_theme_signal(self, serial: int) -> None:
        if not self.isVisible():
            return                      # pendiente: lo recoge showEvent
        self._theme_serial = serial
        self.on_theme()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._theme_serial != bus.serial:
            self._theme_serial = bus.serial
            self.on_theme()


class Beating:
    """Mixin: participacion en el ``Beat`` que no se puede quedar colgada.

    ``animate()`` apunta al latido, ``rest()`` da de baja, y ``hideEvent`` da de
    baja **siempre**. Un widget escondido que sigue en el latido despierta la
    CPU cada 16 ms sin pintar un solo pixel: es el fallo de la interfaz vieja
    que costo entero ``motion.py``, y aqui no depende de que nadie se acuerde.

    ``animate()`` sobre un widget que aun no se ve no apunta al latido: anota la
    intencion y la cumple en ``showEvent``. Asi una tarjeta construida dentro de
    una pagina que todavia no se ha mostrado no arranca a animarse en vacio.
    """

    BEAT_HZ = motion.HZ_FULL

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._beating = False
        self._wants_beat = False

    def tick(self, dt: float) -> bool:
        """Un paso de animacion. ``True`` si hay que seguir."""
        return False

    @property
    def beating(self) -> bool:
        return self._beating

    def animate(self) -> None:
        self._wants_beat = True
        if not self._beating and self.isVisible():
            motion.beat.join(self, self.BEAT_HZ)
            self._beating = True

    def rest(self) -> None:
        self._wants_beat = False
        if self._beating:
            motion.beat.leave(self)
            self._beating = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._wants_beat and not self._beating:
            motion.beat.join(self, self.BEAT_HZ)
            self._beating = True

    def hideEvent(self, event) -> None:
        if self._beating:
            motion.beat.leave(self)
            self._beating = False
        super().hideEvent(event)


# --------------------------------------------------------------------------- #
# geometria: la reserva de la sombra y el hueco entre laminas
# --------------------------------------------------------------------------- #

def _reserve_of(*elevations: Elevation) -> QMarginsF:
    """Hueco por lado que piden las sombras de estos niveles.

    Por lado y no uniforme porque las sombras van desplazadas: una E2 necesita
    34 px por debajo y 14 por arriba. Reservar el maximo por los cuatro lados
    engordaria las laminas un 40 % para nada.
    """
    left = right = top = bottom = 0.0
    for elev in elevations:
        for sh in elev.shadows:
            reach = SHADOW_REACH * sh.blur
            left = max(left, reach - sh.dx)
            right = max(right, reach + sh.dx)
            top = max(top, reach - sh.dy)
            bottom = max(bottom, reach + sh.dy)
    if left <= 0.0 and right <= 0.0 and top <= 0.0 and bottom <= 0.0:
        return QMarginsF()
    return QMarginsF(math.ceil(max(0.0, left)) + _SLACK,
                     math.ceil(max(0.0, top)) + _SLACK,
                     math.ceil(max(0.0, right)) + _SLACK,
                     math.ceil(max(0.0, bottom)) + _SLACK)


def gap_between(a: "Sheet", b: "Sheet", *, vertical: bool = False,
                gap: int | None = None) -> int:
    """Espaciado de layout para dejar ``gap`` px **de vidrio a vidrio**.

    Sale negativo casi siempre, y esta bien: las reservas de sombra de dos
    laminas vecinas tienen que solaparse, porque las sombras se solapan. El
    apartado 3.4 fija el hueco en 16 entre laminas de la misma elevacion y en 24
    cuando una flota sobre la otra; nunca 8.
    """
    if gap is None:
        gap = GAP_SAME if a.elevation == b.elevation else GAP_FLOATING
    ra, rb = a.reserve(), b.reserve()
    if vertical:
        return int(round(gap - ra.bottom() - rb.top()))
    return int(round(gap - ra.right() - rb.left()))


def _lift_elevation(base: Elevation, up: Elevation, k: float) -> Elevation:
    """El nivel intermedio del alzado por hover (apartado 5.5.3).

    Se interpola la escala y se cambia el relleno con un tinte aparte (ver
    ``_lift_tint``), pero **las sombras saltan de golpe**: el atlas cachea por
    desenfoque, asi que una rampa continua de 32 a 44 fabricaria trece tiles
    nuevos por radio y por tema en cada hover. El salto se da al arrancar el
    gesto, cuando el movimiento lo tapa.
    """
    if k <= 0.0:
        return base
    return Elevation(
        name=base.name, fill=base.fill,
        edge_tl=base.edge_tl, edge_br=base.edge_br,
        shadows=up.shadows if k > _LIFT_SHADOW_AT else base.shadows,
        scale=base.scale + (up.scale - base.scale) * k,
        clip_canvas=base.clip_canvas)


def _lift_tint(base: Surface, up: Surface, k: float) -> Ink | None:
    """El lavado que falta para llegar del nivel base al alzado.

    En oscuro da 0.042, que es el "+0.04 de alfa" que escribe el apartado 5.5.3;
    en claro da 0.62, porque alli la rampa de vidrio va de 0.74 a 0.90 de blanco.
    Escribir el 0.04 a pelo dejaba el hover del modo claro invisible: es la
    misma trampa que la de los filos, y por eso esto es una cuenta y no una
    constante.
    """
    if k <= 0.0:
        return None
    a, b = base.ink.alpha, up.ink.alpha
    if up.ink.hex != base.ink.hex or b <= a:
        d = b
    else:
        d = (b - a) / max(1e-6, 1.0 - a)
    return Ink(up.ink.hex, max(0.0, min(1.0, d * k)))


# --------------------------------------------------------------------------- #
# la lamina
# --------------------------------------------------------------------------- #

class Sheet(ThemeAware, Beating, QWidget):
    """El widget-lamina: un nivel de elevacion con contenido encima.

    Se le da un nivel (``"E1"``..``"E4"``), un radio y un padding, y el resto lo
    pinta ``glass.paint_sheet``. El contenido se compone dentro de
    ``content_rect()``, con el radio concentrico que devuelve ``child_radius()``:
    radio del hijo = radio del padre - padding, sin excepcion, que es la regla
    que hace que el vidrio parezca fabricado y no recortado.

    Redimensionar no cuesta nada: la sombra sale del atlas, que cachea por
    ``(radio, desenfoque, tinta)`` y no por tamanyo, asi que estirar una lamina
    no genera un tile nuevo. Lo unico que se recalcula es la reserva, y solo
    cuando cambia el nivel o el tema.

    **Al anidar**, el padre tiene que dejarle a la hija el hueco de su
    ``reserve()``: una lamina pegada al borde interior de otra sale con la
    sombra cortada a canto recto, porque Qt recorta cada hijo a su rectangulo.
    Con el padding normal de 20 y una hija E2 sobra; con una hija E4 (reserva 50
    por lado) hay que meterla mas adentro o bajarle el nivel.
    """

    #: A que nivel sube el hover. Se cambia por instancia con ``hover_to``.
    HOVER_TO = "E3"

    def __init__(self, parent: QWidget | None = None, *,
                 elevation: str = "E2", radius: float = R_LG,
                 padding: int = SHEET_PADDING, interactive: bool = False,
                 hover_to: str | None = None) -> None:
        super().__init__(parent)
        self._elevation = elevation
        self._hover_to = hover_to or self.HOVER_TO
        self._radius = float(radius)
        self._padding = int(padding)
        self._interactive = bool(interactive)
        self._hover = False
        self._active = False
        self._flash = 0.0
        self._tint: Ink | None = None
        self._bleed: QPixmap | None = None
        self._reserve: QMarginsF | None = None
        self._lift = motion.Spring(0.0)
        self._sweep = motion.SpecularSweep(self.update)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, self._interactive)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    # -- configuracion ------------------------------------------------------
    @property
    def elevation(self) -> str:
        return self._elevation

    def set_elevation(self, elevation: str) -> None:
        if elevation == self._elevation:
            return
        self._elevation = elevation
        self._invalidate()

    @property
    def radius(self) -> float:
        return self._radius

    def set_radius(self, radius: float) -> None:
        self._radius = float(radius)
        self.update()

    @property
    def padding(self) -> int:
        return self._padding

    def set_padding(self, padding: int) -> None:
        self._padding = int(padding)
        self._apply_margins()
        self.update()

    def set_interactive(self, value: bool) -> None:
        if bool(value) == self._interactive:
            return
        self._interactive = bool(value)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, self._interactive)
        if not self._interactive:
            self.set_hover(False)
        # la reserva cuenta con la sombra del nivel al que sube el hover, asi
        # que volverse interactiva cambia la geometria
        self._invalidate()

    def set_tint(self, tint: Ink | None) -> None:
        """Tinte de modo o de estado. El color significa (principio 3)."""
        self._tint = tint
        self.update()

    def set_bleed(self, bleed: QPixmap | None) -> None:
        """El grafico que **es** el fondo de la lamina, no un recuadro dentro."""
        self._bleed = bleed
        self.update()

    def set_active(self, value: bool) -> None:
        """Algo de dentro esta activo: el filo sube a 0.24 y lo cuenta."""
        if bool(value) == self._active:
            return
        self._active = bool(value)
        self.update()

    # -- geometria ----------------------------------------------------------
    def reserve(self) -> QMarginsF:
        """Hueco que la lamina se guarda dentro de si misma para su sombra."""
        if self._reserve is None:
            t = theme.C.tokens
            niveles = [glass.elevation_of(self._elevation, t)]
            if self._interactive:
                niveles.append(glass.elevation_of(self._hover_to, t))
            self._reserve = _reserve_of(*niveles)
        return self._reserve

    def glass_box(self) -> QRectF:
        """El rectangulo del vidrio: el widget menos la reserva de la sombra."""
        return QRectF(self.rect()).marginsRemoved(self.reserve())

    def content_rect(self) -> QRectF:
        """Donde va el contenido: el vidrio menos el padding.

        Lleva ya el desplazamiento de 2 px del hover. Se calcula sobre el vidrio
        **sin** la escala del alzado a proposito: la escala es un efecto de
        pintado de 1,2 px y el contenido que la siguiese temblaria.
        """
        r = self.glass_box().adjusted(self._padding, self._padding,
                                      -self._padding, -self._padding)
        return r.translated(0.0, self.content_offset())

    def place(self, rect: QRectF | QRect) -> None:
        """Coloca la lamina para que **su vidrio** ocupe ``rect``.

        Es la unica manera sensata de posicionar laminas a mano: la geometria
        del widget lleva la reserva de la sombra sumada, y hacer esa cuenta en
        cada sitio de llamada acaba en una lamina descuadrada respecto de sus
        vecinas.
        """
        m = self.reserve()
        r = QRectF(rect)
        self.setGeometry(
            int(round(r.left() - m.left())), int(round(r.top() - m.top())),
            int(round(r.width() + m.left() + m.right())),
            int(round(r.height() + m.top() + m.bottom())))

    def content_offset(self) -> float:
        """Los 2 px que el contenido sube en hover (apartado 5.5.3).

        Lo cobra ``content_rect()``, o sea el contenido pintado a mano. Los
        widget hijos **no** se mueven: hacerlo pedia un relayout por fotograma,
        que es mil veces mas caro que el alzado entero y arrastraria a los
        vecinos. Una tarjeta que quiera el matiz pinta su contenido.
        """
        return -2.0 * self._lift.value

    def child_radius(self) -> int:
        """Radio concentrico de un hijo directo. Nunca dos radios por esquina."""
        return concentric(int(self._radius), self._padding)

    def _apply_margins(self) -> None:
        lay = self.layout()
        if lay is None:
            return
        m = self.reserve()
        p = self._padding
        lay.setContentsMargins(int(m.left()) + p, int(m.top()) + p,
                               int(m.right()) + p, int(m.bottom()) + p)

    def setLayout(self, layout) -> None:      # noqa: N802 (API de Qt)
        """Instala el layout ya descontada la reserva y el padding.

        Sin esto todo el que ponga un layout dentro de una lamina tiene que
        acordarse de restar dos margenes distintos, y no se va a acordar.
        """
        super().setLayout(layout)
        self._apply_margins()

    def _invalidate(self) -> None:
        self._reserve = None
        self._apply_margins()
        self.updateGeometry()
        self.update()

    # -- estado -------------------------------------------------------------
    def flash(self) -> None:
        """Destello del filo a 0.30. Es el canal de retroalimentacion barato."""
        self._flash = 1.0
        self.animate()

    def sweep(self) -> None:
        """Barrido especular: la lamina ha cambiado de estado de verdad.

        Una sola vez y nunca en bucle; en bucle deja de significar nada.
        """
        self._sweep.start()

    def set_hover(self, value: bool) -> None:
        """Levanta o baja la lamina.

        Publico porque el raton no es el unico motivo para alzar una tarjeta:
        el foco de teclado tambien la alza, y la navegacion del panel se hace
        con las dos cosas.
        """
        if bool(value) == self._hover:
            return
        self._hover = bool(value)
        self._lift.set(1.0 if self._hover else 0.0)
        self.animate()

    def event(self, e) -> bool:
        if self._interactive:
            t = e.type()
            if t in (QEvent.Type.HoverEnter, QEvent.Type.HoverMove):
                # contra el vidrio y no contra el widget: la reserva de la
                # sombra se solapa con la lamina vecina, y si contase como zona
                # sensible el raton levantaria la tarjeta equivocada
                self.set_hover(self.glass_box().contains(e.position()))
            elif t == QEvent.Type.HoverLeave:
                self.set_hover(False)
        return super().event(e)

    def tick(self, dt: float) -> bool:
        self._lift.step(dt)
        busy = not self._lift.settled
        if self._flash > 0.0:
            self._flash = max(0.0, self._flash - dt * 1000.0 / FLASH_MS)
            busy = True
        self.update()
        if not busy:
            self.rest()
        return busy

    def hideEvent(self, event) -> None:
        # el barrido se apunta al latido por su cuenta, asi que tambien hay que
        # bajarlo: se le da un paso enorme para que termine y se de de baja solo
        if self._sweep.active:
            self._sweep.tick(10.0)
        super().hideEvent(event)

    def on_theme(self) -> None:
        # la reserva depende del tema: en claro las sombras van al 60 %
        self._invalidate()

    # -- pintado ------------------------------------------------------------
    def _edge_alpha(self) -> float:
        k = self._lift.value
        edge = glass.EDGE_REST + (glass.EDGE_HOVER - glass.EDGE_REST) * k
        if self._active:
            edge = max(edge, glass.EDGE_ACTIVE)
        if self._flash > 0.0:
            edge = edge + (glass.EDGE_FLASH - edge) * self._flash
        return edge

    def paint_glass(self, painter: QPainter):
        """Pinta la lamina y devuelve su camino, para recortarle el contenido."""
        t = theme.C.tokens
        base = glass.elevation_of(self._elevation, t)
        k = self._lift.value if self._interactive else 0.0
        elev = base
        tint = self._tint
        if k > 0.0:
            up = glass.elevation_of(self._hover_to, t)
            elev = _lift_elevation(base, up, k)
            lavado = _lift_tint(getattr(t.glass, base.fill),
                                getattr(t.glass, up.fill), k)
            tint = tint if lavado is None else lavado
        return glass.paint_sheet(
            painter, self.glass_box(), elev, self._radius,
            edge_light=self._edge_alpha(), tint=tint, bleed=self._bleed,
            tokens=t, canvas_origin=self.mapTo(self.window(), QPoint(0, 0)))

    def paint_content(self, painter: QPainter, rect: QRectF) -> None:
        """Gancho para las laminas que pintan su contenido a mano."""

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = self.paint_glass(p)
        p.save()
        p.setClipPath(path)
        self.paint_content(p, self.content_rect())
        # el barrido va sobre el contenido pintado a mano, pero por debajo de
        # los widget hijos: Qt los pinta despues del padre y no hay vuelta
        self._sweep.paint(p, path.boundingRect(), self._radius)
        p.restore()
        p.end()


class Inset(Sheet):
    """El rebaje E1: un pozo dentro de una lamina.

    Canal de deslizador, pozo de grafico, consola del registro. No proyecta
    sombra (por eso su reserva es cero) y lleva el filo invertido, oscuro
    arriba-izquierda, para leerse como un hueco y no como una placa encima.

    El radio por defecto es ``r-md`` 18, que es justamente
    ``concentric(R_LG, 6)``: un rebaje dentro de una lamina de radio 24. Si el
    padre tiene otro padding, se le pasa ``parent.child_radius()``.
    """

    def __init__(self, parent: QWidget | None = None, *,
                 radius: float = R_MD, padding: int = 12) -> None:
        super().__init__(parent, elevation="E1", radius=radius,
                         padding=padding, interactive=False)


class Pill(Sheet):
    """Lamina de radio completo: barra de navegacion, badges, avisos.

    Nace en E4 porque casi todas las pildoras del sistema flotan sobre algo.
    """

    def __init__(self, parent: QWidget | None = None, *,
                 elevation: str = "E4", padding: int = 12,
                 interactive: bool = False) -> None:
        super().__init__(parent, elevation=elevation, radius=R_FULL,
                         padding=padding, interactive=interactive)


class Gap(QWidget):
    """Separacion explicita entre dos cosas.

    Existe para que nadie escriba un ``QFrame`` de 1 px haciendo de separador:
    el principio 1 dice que la jerarquia se dibuja con altura y tamanyo, y que
    si hace falta una linea para separar dos cosas es que estan mal colocadas.
    """

    def __init__(self, size: int = GAP_SAME, *, vertical: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if vertical:
            self.setFixedHeight(int(size))
        else:
            self.setFixedWidth(int(size))
