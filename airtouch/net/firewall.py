"""Permiso del cortafuegos de Windows para AirLink.

Sin una regla de entrada, el movil no puede alcanzar el PC y lo unico que ve es
"no se encuentra el servidor", sin ninguna pista de por que.

Detalle que cuesta un rato descubrir: muchas redes domesticas quedan
clasificadas como **publicas** (sobre todo con sistemas mesh), y en ese perfil
Windows bloquea todo lo entrante. Por eso la regla se crea con ``profile=any``:
asi da igual como haya clasificado Windows tu WiFi.
"""
from __future__ import annotations

import ctypes
import logging
import subprocess

log = logging.getLogger(__name__)

RULE_NAME = "AirTouch AirLink"

_NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW: sin parpadeo de consola


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def rule_exists(port: int = 8443) -> bool | None:
    """True / False, o None si no se puede saber (hace falta admin para mirar)."""
    try:
        out = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             f"name={RULE_NAME}"],
            capture_output=True, text=True, timeout=6,
            creationflags=_NO_WINDOW,
        )
        if out.returncode != 0:
            return False
        return str(port) in out.stdout
    except Exception:
        return None


def _netsh_args(port: int) -> list[str]:
    return [
        "advfirewall", "firewall", "add", "rule",
        f"name={RULE_NAME}",
        "dir=in", "action=allow", "protocol=TCP",
        f"localport={port}",
        # any, no private: en redes mesh Windows suele marcar la red como
        # publica y una regla solo-privada no serviria de nada
        "profile=any",
        "description=Permite que el movil envie video a AirTouch por la red local",
    ]


def add_rule(port: int = 8443) -> bool:
    """Crea la regla. Si no hay permisos, pide elevacion (saldra un UAC)."""
    if is_admin():
        try:
            r = subprocess.run(["netsh", *_netsh_args(port)],
                               capture_output=True, text=True, timeout=15,
                               creationflags=_NO_WINDOW)
            return r.returncode == 0
        except Exception as exc:
            log.warning("No se pudo crear la regla: %s", exc)
            return False

    # sin permisos: se lanza netsh elevado, el usuario acepta el UAC
    try:
        params = " ".join(f'"{a}"' if " " in a else a for a in _netsh_args(port))
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "netsh", params, None, 0)
        return int(rc) > 32          # >32 = se lanzo; <=32 = error o cancelado
    except Exception as exc:
        log.warning("No se pudo pedir elevacion: %s", exc)
        return False


def remove_rule() -> bool:
    try:
        args = ["advfirewall", "firewall", "delete", "rule", f"name={RULE_NAME}"]
        if is_admin():
            r = subprocess.run(["netsh", *args], capture_output=True,
                               timeout=15, creationflags=_NO_WINDOW)
            return r.returncode == 0
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "netsh", " ".join(args), None, 0)
        return int(rc) > 32
    except Exception:
        return False


def network_is_public() -> bool | None:
    """True si alguna red activa esta clasificada como publica.

    Es la causa numero uno de que el movil no encuentre el PC.
    """
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetConnectionProfile).NetworkCategory"],
            capture_output=True, text=True, timeout=8,
            creationflags=_NO_WINDOW)
        if r.returncode != 0:
            return None
        return "Public" in r.stdout
    except Exception:
        return None
