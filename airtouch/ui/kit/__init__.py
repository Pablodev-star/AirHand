"""El kit de widgets de CRISTAL VIVO (apartado 6 de la especificacion).

Todo lo que se ve en la interfaz nueva se compone con piezas de aqui, y todas
cuelgan de ``base.py``: la lamina, el rebaje y los dos mixins que resuelven de
una vez el latido compartido y el cambio de tema en caliente.

**Por que "kit" y no "widgets".** La especificacion llama al paquete
``ui/widgets/``, pero ``airtouch/ui/widgets.py`` ya existe y lo usa la interfaz
vieja, que tiene que seguir arrancando durante toda la migracion; un modulo y un
paquete no pueden compartir nombre. ``widgets.py`` se borrara al final, cuando
nadie lo importe, y para entonces renombrar esto seria un ``git mv`` que no
merece la pena. El nombre del paquete es lo unico que se desvia del documento.

Uso minimo::

    tarjeta = Sheet(padding=24, interactive=True)
    tarjeta.setLayout(QVBoxLayout())          # los margenes los pone la lamina
    pozo = Inset(tarjeta, radius=tarjeta.child_radius())

Dos cosas que hay que saber antes de colocar laminas en un layout:

* una lamina reserva **dentro de si misma** el hueco de su sombra, asi que el
  espaciado entre dos vecinas se pide con ``gap_between(a, b)``, que suele
  devolver un numero negativo y esta bien;
* un widget del kit **nunca** conecta nada a ``theme.signals.changed`` ni crea
  un ``QTimer``: redefine ``on_theme()`` y ``tick(dt)``.
"""
from __future__ import annotations

from .base import (FLASH_MS, SHADOW_REACH, Beating, Gap, Inset, Pill, Sheet,
                   ThemeAware, bus, gap_between)
from .controls import (BIRTH_MS, BIRTH_RISE, DISABLED_ALPHA, RING, Button,
                       Chip, Field, Phase, Segmented, SettingRow, Slider,
                       Toggle)

__all__ = [
    "Sheet", "Inset", "Pill", "Gap",
    "ThemeAware", "Beating", "bus", "gap_between",
    "FLASH_MS", "SHADOW_REACH",
    "Phase", "Toggle", "Button", "Slider", "Segmented", "Field", "SettingRow",
    "Chip", "DISABLED_ALPHA", "RING", "BIRTH_MS", "BIRTH_RISE",
]
