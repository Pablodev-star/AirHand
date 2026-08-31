"""Version de AirHand.

Es el unico sitio donde se toca el numero. El instalador, la pagina web y el
comprobador de actualizaciones lo leen de aqui o de la API de GitHub, nunca
escrito a mano en dos sitios distintos.
"""
from __future__ import annotations

__version__ = "1.0.0"

#: Repositorio publico del que se descargan las actualizaciones.
GITHUB_OWNER = "Pablodev-star"
GITHUB_REPO = "AirHand"

RELEASES_API = (f"https://api.github.com/repos/{GITHUB_OWNER}/"
                f"{GITHUB_REPO}/releases/latest")
RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
SETUP_URL = f"https://{GITHUB_OWNER.lower()}.github.io/{GITHUB_REPO}/"


def parse(version: str) -> tuple[int, ...]:
    """Saca (mayor, menor, parche) de una etiqueta de version.

    Se busca el primer grupo de numeros separados por puntos, en vez de cortar
    por guiones: asi valen tanto 'v1.2.3' como 'release-2.1.0' o
    'airhand-1.2.0-beta'. Cortando por el guion, 'release-2.1.0' se leia como
    0.0.0 y la actualizacion no se ofrecia nunca.
    """
    import re

    match = re.search(r"(\d+(?:\.\d+)*)", version or "")
    if not match:
        return (0, 0, 0)
    parts = [int(chunk) for chunk in match.group(1).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(candidate: str, current: str = __version__) -> bool:
    """True si `candidate` es posterior a `current`."""
    try:
        return parse(candidate) > parse(current)
    except Exception:
        return False
