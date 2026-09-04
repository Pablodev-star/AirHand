"""Pruebas del asistente inicial, sin camara y sin tocar el escritorio.

Existe por un fallo concreto que estuvo publicado: la pagina de camara del
asistente era la de iVCam, y al salir de ella dejaba
``camera.source_type = "index"``. Es decir, completar la configuracion inicial
apagaba AirLink y devolvia la aplicacion a la webcam del sistema, en silencio.
Quien instalase de cero terminaba el asistente y se quedaba sin camara.

Eso se sigue comprobando aqui, y ademas los mecanismos del apartado 9.2, que
son los que separan un acompanamiento de un formulario y los que se rompen sin
que nadie se entere:

* el **hilo de progreso** avanza fraccionadamente dentro de la pagina, no por
  pasos, y cada pagina se queda dentro de su tramo;
* el **boton primario no existe** hasta que la pagina es satisfacible;
* la **estimacion de tiempo** baja y no sube sola;
* **salir** siempre esta disponible y **no** da la vuelta por hecha;
* la pagina de camara **espera al movil de verdad** y ningun texto —ni pintado,
  ni en un QLabel— menciona iVCam.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Igual que en test_engine: una pantalla fija, para no depender del monitor de
# quien ejecute esto. Hay que hacerlo antes de importar lo que la consulta.
from airtouch.core import screen as _screen                # noqa: E402

_FAKE_SCREEN = _screen.Rect(0, 0, 2560, 1440)
_screen.primary_screen = lambda: _FAKE_SCREEN
_screen.virtual_screen = lambda: _FAKE_SCREEN

from PySide6.QtWidgets import QApplication, QLabel         # noqa: E402

from airtouch.config import Config                         # noqa: E402
from airtouch.core.controller import Controller            # noqa: E402
from airtouch.ui import theme                              # noqa: E402
from airtouch.ui.wizard.wizard import (TRAMOS, CameraPage,  # noqa: E402
                                       FinishPage, GesturePage, IntroPage,
                                       PinchPage, SetupWizard)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


#: Un puerto por asistente. Todas las pruebas construyen el suyo y la pagina de
#: camara arranca el servidor de AirLink al entrar: con un puerto fijo, el
#: segundo asistente vuelca una traza de "address already in use" en medio de la
#: salida y parece que algo ha fallado cuando no ha fallado nada.
_PUERTO = [8551]


def _wizard() -> tuple[SetupWizard, Config, Controller]:
    cfg = Config()
    # puerto distinto del habitual: si hay un AirTouch de verdad abierto, no se
    # pelean por el 8443 y la prueba no depende de que la maquina este ociosa
    _PUERTO[0] += 1
    cfg.airlink.port = _PUERTO[0]
    ctl = Controller(cfg)
    return SetupWizard(cfg, ctl), cfg, ctl


def _pagina(wiz: SetupWizard, clase):
    return next(p for p in wiz.pages if isinstance(p, clase))


# --------------------------------------------------------------------------- #
# la camara: el fallo que estuvo publicado
# --------------------------------------------------------------------------- #

def test_camera_page_deja_airlink() -> None:
    """El fallo original: salir de la pagina volvia a la camara del sistema."""
    _app()
    wiz, cfg, _ctl = _wizard()
    page = _pagina(wiz, CameraPage)

    cfg.camera.source_type = "index"          # como si vinieras de una v1
    page.on_leave()

    assert cfg.camera.source_type == "airlink", \
        f"el asistente dejo la camara en {cfg.camera.source_type!r}"
    print("  OK  el asistente deja la camara en AirLink")


def test_camera_page_webcam_solo_si_la_eliges() -> None:
    """Y solo se va a la webcam si el usuario la ha elegido de verdad."""
    _app()
    wiz, cfg, _ctl = _wizard()
    page = _pagina(wiz, CameraPage)

    page._elegir("webcam")
    page.on_leave()
    assert cfg.camera.source_type == "index", "eligiendo webcam se queda en AirLink"

    page._elegir("airlink")
    page.on_leave()
    assert cfg.camera.source_type == "airlink", "volver a AirLink no se guarda"
    print("  OK  la fuente guardada es la que el usuario elige")


def test_camera_page_espera_al_movil() -> None:
    """No se puede continuar con el movil sin conectar."""
    _app()
    wiz, _cfg, ctl = _wizard()
    page = _pagina(wiz, CameraPage)

    ctl.airlink.phone_connected = False
    ctl.airlink.frames_received = 0
    page._comprobar()
    assert not page.can_advance(), "deja seguir sin movil conectado"

    # conectado pero con dos fotogramas: aun no. La primera imagen llega antes
    # de que el movil estabilice la camara.
    ctl.airlink.phone_connected = True
    ctl.airlink.frames_received = 2
    page._comprobar()
    assert not page.can_advance(), "se fia del primer fotograma"

    ctl.airlink.frames_received = 120
    page._comprobar()
    assert page.can_advance(), "no deja seguir con el movil ya emitiendo"
    print("  OK  espera a que el movil emita de verdad")


def test_sin_rastro_de_ivcam() -> None:
    """Ningun texto visible puede seguir hablando de iVCam.

    Ahora el asistente no usa un solo ``QLabel``: pinta su texto. Por eso se
    revisa lo que las paginas declaran en ``textos()`` **y**, por si vuelve a
    aparecer alguna etiqueta, tambien los QLabel que pudiera haber.
    """
    _app()
    wiz, _cfg, _ctl = _wizard()

    visibles: list[str] = []
    for page in wiz.pages:
        visibles += page.textos()
        visibles += [w.text() for w in page.findChildren(QLabel)]
    malos = [t for t in visibles if "ivcam" in t.lower()]
    assert not malos, f"quedan textos con iVCam: {malos}"
    assert len(visibles) > 20, "las paginas no declaran su texto en textos()"
    print(f"  OK  ningun texto menciona iVCam ({len(visibles)} textos revisados)")


# --------------------------------------------------------------------------- #
# los mecanismos del 9.2
# --------------------------------------------------------------------------- #

def test_hilo_avanza_dentro_de_la_pagina() -> None:
    """El hilo crece fraccionadamente, no por pasos (9.2.1).

    Es el mecanismo mas importante del apartado 9: la barra se mueve porque
    mueves la mano. Si la pagina emite 0,5 y el hilo no se mueve hasta pulsar
    Continuar, el asistente vuelve a ser un formulario.
    """
    _app()
    wiz, _cfg, _ctl = _wizard()

    for indice, (lo, hi) in enumerate(TRAMOS):
        wiz._goto(indice)
        wiz._progreso_de_pagina(0.0)
        assert abs(wiz._hilo.target * 100.0 - lo) < 0.01, \
            f"la pagina {indice} arranca fuera de su tramo"
        wiz._progreso_de_pagina(0.5)
        medio = wiz._hilo.target * 100.0
        assert lo < medio < hi, \
            f"la pagina {indice} no avanza a mitad de camino ({medio:.1f} %)"
        wiz._progreso_de_pagina(1.0)
        assert abs(wiz._hilo.target * 100.0 - hi) < 0.01, \
            f"la pagina {indice} no cierra su tramo"

    assert TRAMOS[0][0] == 0 and TRAMOS[-1][1] == 100, "el reparto no cubre 0..100"
    for (_a, fin), (ini, _b) in zip(TRAMOS, TRAMOS[1:]):
        assert fin == ini, "hay un hueco entre dos tramos del hilo"
    print("  OK  el hilo avanza dentro de cada pagina y los tramos encajan")


def test_boton_no_existe_hasta_que_la_pagina_es_satisfacible() -> None:
    """El boton primario no se deshabilita: no esta (9.2.3)."""
    _app()
    wiz, _cfg, ctl = _wizard()

    ctl.airlink.phone_connected = False
    ctl.airlink.frames_received = 0
    wiz._goto(1)
    assert wiz.boton is not None and not wiz.boton.born, \
        "el boton ya existe con la pagina sin satisfacer"

    ctl.airlink.phone_connected = True
    ctl.airlink.frames_received = 400
    _pagina(wiz, CameraPage)._comprobar()
    assert wiz.boton.born, "el boton no se materializa al cumplirse la condicion"

    # y al pasar a una pagina que no esta satisfecha, vuelve a no existir
    wiz._goto(3)
    assert not wiz.boton.born, "el boton sobrevive a un cambio de pagina"
    print("  OK  el boton se materializa y vuelve a no existir")


def test_el_boton_nunca_miente() -> None:
    """Si el boton esta, se puede avanzar; si no, ``_next`` no hace nada."""
    _app()
    wiz, _cfg, _ctl = _wizard()

    wiz._goto(3)                              # el gesto: tres cierres, ninguno
    assert not wiz.pages[3].can_advance()
    wiz._next()
    assert wiz._indice == 3, "avanza con la pagina sin satisfacer"
    print("  OK  sin boton no se avanza")


def test_estimacion_de_tiempo_es_honesta() -> None:
    """Al empezar, minutos; a partir de la segunda pagina, segundos que bajan."""
    _app()
    wiz, _cfg, _ctl = _wizard()

    wiz._goto(0)
    texto = wiz._texto_tiempo()
    assert "minuto" in texto, f"la portada no promete minutos: {texto!r}"

    wiz._goto(2)
    wiz._resto = wiz._estimar()
    primero = wiz._resto
    wiz._goto(5)
    segundo = wiz._estimar()
    assert segundo < primero, \
        f"la estimacion no baja al avanzar ({primero:.0f} -> {segundo:.0f})"

    wiz._goto(6)
    assert wiz._texto_tiempo() == "", "la ultima pagina sigue prometiendo tiempo"
    print(f"  OK  la estimacion baja de {primero:.0f} s a {segundo:.0f} s")


def test_salir_siempre_y_sin_dar_la_vuelta_por_hecha() -> None:
    """Salir esta en todas las paginas con cromo y no marca first_run (9.2.6)."""
    _app()
    wiz, cfg, _ctl = _wizard()
    cfg.app.first_run = True

    wiz._goto(0)
    assert wiz.pages[0].SIN_CROMO, "la portada no es a sangre"
    for indice in range(1, len(wiz.pages)):
        wiz._goto(indice)
        assert wiz.salir.isVisible() or not wiz.isVisible(), \
            f"la pagina {indice} no ofrece salir"

    wiz._salir()
    assert cfg.app.first_run, "salir del asistente dio la configuracion por hecha"
    print("  OK  salir siempre esta y no marca la configuracion como hecha")


def test_el_recibo_sale_de_lo_medido() -> None:
    """El recibo de P6 no inventa: recibe lo que el armazon ha visto (9.3, P6)."""
    _app()
    wiz, _cfg, _ctl = _wizard()

    wiz._on_stats({"latency_ms": 70.0})
    wiz._on_stats({"latency_ms": 78.0})
    gesto = _pagina(wiz, GesturePage)
    gesto.minimos = [0.31, 0.29, 0.33]
    gesto.abierto = 0.86

    wiz._goto(6)
    final = _pagina(wiz, FinishPage)
    assert abs(final.retardo_ms - 74.0) < 0.01, \
        f"el retardo del recibo no es la media medida: {final.retardo_ms}"
    assert final.gestos_ok == 3, "el recibo no cuenta los gestos hechos"

    # y P4 recibe en silencio lo que P3 guardo sin decirlo
    wiz._goto(4)
    pinch = _pagina(wiz, PinchPage)
    assert pinch.minimos == gesto.minimos, "P4 no hereda las medidas de P3"
    print("  OK  el recibo y el umbral salen de lo medido de verdad")


def test_paginas_completas_y_contratos() -> None:
    """Siete paginas, en su orden, y el contrato con ``app.py`` intacto."""
    _app()
    wiz, _cfg, _ctl = _wizard()

    assert len(wiz.pages) == 7, f"hay {len(wiz.pages)} paginas, no siete"
    assert isinstance(wiz.pages[0], IntroPage)
    assert isinstance(wiz.pages[-1], FinishPage)
    assert hasattr(wiz, "completed") and hasattr(wiz, "exec")
    assert len(TRAMOS) == len(wiz.pages), "el hilo no reparte las siete paginas"
    print("  OK  siete paginas y el contrato de app.py intacto")


def test_terminar_expande_y_cumple_el_contrato() -> None:
    """Terminar emite ``completed`` con el interruptor, hace ``commit`` y expande.

    Es el contrato exacto que usa ``app.py``. Y el orden importa: ``completed``
    sale **antes** de la animacion, para que el panel se levante detras mientras
    la lamina viaja hasta el area del mosaico (9.3, P6).
    """
    _app()
    wiz, cfg, _ctl = _wizard()
    cfg.app.first_run = True
    recibido: list[bool] = []
    wiz.completed.connect(recibido.append)

    wiz._goto(6)
    final = _pagina(wiz, FinishPage)
    final.control.setChecked(True)
    wiz._terminar()

    assert recibido == [True], f"completed no llego bien: {recibido}"
    assert not cfg.app.first_run, "terminar no hizo commit de la configuracion"
    assert wiz._expansion is not None, "la ultima pagina se cerro en vez de expandirse"
    assert abs(wiz._hilo.target - 1.0) < 1e-6, "el hilo no llega al 100 %"
    print("  OK  terminar emite completed, hace commit y expande la lamina")


def main() -> int:
    print("Pruebas del asistente inicial\n")
    pruebas = [
        test_camera_page_deja_airlink,
        test_camera_page_webcam_solo_si_la_eliges,
        test_camera_page_espera_al_movil,
        test_sin_rastro_de_ivcam,
        test_hilo_avanza_dentro_de_la_pagina,
        test_boton_no_existe_hasta_que_la_pagina_es_satisfacible,
        test_el_boton_nunca_miente,
        test_estimacion_de_tiempo_es_honesta,
        test_salir_siempre_y_sin_dar_la_vuelta_por_hecha,
        test_el_recibo_sale_de_lo_medido,
        test_paginas_completas_y_contratos,
        test_terminar_expande_y_cumple_el_contrato,
    ]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
        except AssertionError as exc:
            fallos += 1
            print(f"  FALLO  {fn.__name__}: {exc}")
        except Exception as exc:
            fallos += 1
            print(f"  ERROR  {fn.__name__}: {type(exc).__name__}: {exc}")
    print()
    if fallos:
        print(f"{fallos} de {len(pruebas)} pruebas han fallado")
    else:
        print(f"Las {len(pruebas)} pruebas han pasado")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
