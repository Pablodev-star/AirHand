"""Punto de entrada del ejecutable.

Existe por un detalle de PyInstaller: al congelar ``airtouch/__main__.py``, ese
modulo pasa a ser ``__main__`` y se queda sin paquete padre, asi que sus
imports relativos (``from .app import main``) fallan antes de que llegue a
ejecutarse una sola linea util — ni siquiera da tiempo a escribir el log.

Con un lanzador que usa imports absolutos, el problema desaparece.
``python -m airtouch`` sigue funcionando igual a traves de ``__main__.py``.
"""
from __future__ import annotations

import sys

from airtouch.app import main

if __name__ == "__main__":
    sys.exit(main())
