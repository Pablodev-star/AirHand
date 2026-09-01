"""Publica una version nueva con un solo comando.

    .venv\\Scripts\\python.exe release.py 1.1.0

Existe para cerrar un agujero concreto: el numero de version vive en
``airtouch/version.py`` y de ahi sale el nombre del .zip, pero lo que dispara
la publicacion es una etiqueta de git. Si se etiqueta sin tocar el fichero, se
publica una version ``v1.1.0`` que contiene un ``AirHand-1.0.0-win64.zip``, y
quien la descargue se lleva el binario viejo creyendo que es el nuevo. Es un
fallo silencioso: no falla nada, simplemente entregas lo de antes.

Aqui el numero se escribe una sola vez y todo lo demas se deriva de el.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
VERSION_PY = RAIZ / "airtouch" / "version.py"


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=str(RAIZ), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} fallo:\n{r.stderr.strip()}")
    return (r.stdout or "").strip()


def version_actual() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', VERSION_PY.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("No encuentro __version__ en airtouch/version.py")
    return m.group(1)


def escribir_version(nueva: str) -> None:
    texto = VERSION_PY.read_text(encoding="utf-8")
    texto = re.sub(r'(__version__\s*=\s*")[^"]+(")', rf'\g<1>{nueva}\g<2>', texto, count=1)
    VERSION_PY.write_text(texto, encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", argv[1]):
        print(__doc__)
        print(f"Version actual: {version_actual()}")
        return 2
    nueva = argv[1]
    actual = version_actual()

    # ---- comprobaciones antes de tocar nada ----
    if nueva == actual:
        raise SystemExit(f"La version ya es {actual}. Elige otra.")

    def piezas(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("."))

    if piezas(nueva) < piezas(actual):
        raise SystemExit(f"{nueva} es anterior a {actual}. El comprobador de "
                         "actualizaciones no ofreceria nada a quien ya tenga "
                         f"la {actual}.")

    if git("status", "--porcelain"):
        raise SystemExit("Hay cambios sin confirmar. Guardalos o descartalos "
                         "antes de publicar: lo que no este en el commit no "
                         "viaja en la version.")

    rama = git("rev-parse", "--abbrev-ref", "HEAD")
    if rama != "main":
        raise SystemExit(f"Estas en la rama {rama}. Las versiones salen de main.")

    if git("tag", "-l", f"v{nueva}"):
        raise SystemExit(f"La etiqueta v{nueva} ya existe.")

    git("fetch", "origin", "--tags")
    if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
        raise SystemExit("main y origin/main no coinciden. Haz push o pull "
                         "antes de publicar.")

    # ---- las pruebas, antes de escribir el numero ----
    print("Pasando las pruebas...")
    for prueba in ("tests/test_engine.py", "tests/test_wizard.py"):
        r = subprocess.run([sys.executable, prueba], cwd=str(RAIZ))
        if r.returncode != 0:
            raise SystemExit(f"{prueba} ha fallado. No se publica nada.")

    # ---- ya si ----
    print(f"\n{actual} -> {nueva}")
    escribir_version(nueva)
    git("add", "airtouch/version.py")
    git("commit", "-m", f"Version {nueva}")
    git("tag", "-a", f"v{nueva}", "-m", f"AirHand {nueva}")
    git("push", "origin", "main")
    git("push", "origin", f"v{nueva}")

    print(f"\nEtiqueta v{nueva} subida. GitHub compila, ejecuta el "
          f"autodiagnostico sobre el binario y publica solo si pasa.")
    print("  Progreso : https://github.com/Pablodev-star/AirHand/actions")
    print(f"  Resultado: https://github.com/Pablodev-star/AirHand/releases/tag/v{nueva}")
    print("\nLa pagina de instalacion y el aviso de actualizacion de la app se "
          "enteran solos: preguntan a la API de GitHub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
