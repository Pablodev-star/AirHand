"""Empaqueta AirTouch en un unico AirTouch.exe con PyInstaller.

    .venv\\Scripts\\python.exe build.py

El ejecutable queda en dist\\AirTouch\\AirTouch.exe. Se usa modo carpeta (no
--onefile) porque MediaPipe descomprime sus modelos en tiempo de ejecucion y
onefile lo hace mucho mas lento al arrancar.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Instalando PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def smoke_test(exe: Path, timeout: int = 180) -> bool:
    """Ejecuta el binario en modo autodiagnostico y exige que pase.

    Compilar sin errores no demuestra que el programa funcione. Los fallos de
    empaquetado solo aparecen al ejecutar el .exe, y los peores ni siquiera
    impiden que se abra la ventana: paso una vez que el panel salia
    perfectamente y MediaPipe no habia cargado, asi que no detectaba nada.

    Por eso no se comprueba "arranca", sino que la vision, los modelos, la web
    y la pila de red respondan de verdad. Ver ``airtouch.app.selftest``.
    """
    print()
    print("=== Prueba de humo: --selftest sobre el binario ===")

    sys.path.insert(0, str(ROOT))
    from airtouch.config import app_data_dir

    log = app_data_dir() / "logs" / "airtouch.log"
    if log.exists():
        log.unlink()                          # solo interesa esta ejecucion

    try:
        code = subprocess.call([str(exe), "--selftest"], cwd=str(exe.parent),
                               timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"FALLO: se quedo colgado mas de {timeout} s")
        return False

    # Sin consola no hay salida estandar: el detalle esta en el registro.
    detail = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    for line in detail.splitlines():
        if "autodiagnostico" in line or "[OK ]" in line or "[MAL]" in line:
            print("   " + line.split(": ", 2)[-1])

    if code != 0:
        print(f"FALLO: el autodiagnostico devolvio {code}")
        if not detail:
            print("   Y no escribio registro: no llego ni a arrancar.")
        return False
    print("OK: el ejecutable funciona.")
    return True


def main() -> int:
    ensure_pyinstaller()

    models = ROOT / "models"
    if not any(models.glob("*.task")):
        print("Descargando los modelos antes de empaquetar...")
        sys.path.insert(0, str(ROOT))
        from airtouch.core import models as model_store

        model_store.ensure_models()

    for folder in ("build", "dist"):
        target = ROOT / folder
        if target.exists():
            shutil.rmtree(target)

    web = ROOT / "airlink-web"
    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", "AirTouch",
        "--noconsole",
        "--noconfirm",
        "--clean",
        "--add-data", f"{models};models",
        # la web de AirLink viaja dentro: el PC la sirve por HTTPS
        "--add-data", f"{web};airlink-web",
        "--collect-all", "mediapipe",
        "--hidden-import", "comtypes.stream",
        "--hidden-import", "aiortc",
        "--hidden-import", "av",
        # OJO: NO excluir matplotlib ni tkinter. Parece peso muerto, pero
        # mediapipe/__init__.py acaba importando matplotlib a traves de
        # drawing_styles. Sin el, el ejecutable arranca igual pero MediaPipe no
        # inicializa y no se detecta ni una mano. Solo se ve al ejecutarlo.
        # lanzador con imports absolutos: ver launcher.py
        str(ROOT / "launcher.py"),
    ]
    print(" ".join(args))
    result = subprocess.call(args, cwd=str(ROOT))
    if result != 0:
        return result

    exe = ROOT / "dist" / "AirTouch" / "AirTouch.exe"
    print(f"\nEjecutable: {exe}")

    if not smoke_test(exe):
        print("\nEl ejecutable compila pero NO funciona. No se empaqueta.")
        return 1

    # Zip con el numero de version en el nombre. Es el archivo que se sube a
    # la publicacion de GitHub; la pagina de instalacion y el comprobador de
    # actualizaciones lo encuentran solos, sin que haya que tocar nada.
    sys.path.insert(0, str(ROOT))
    from airtouch.version import __version__

    name = f"AirHand-{__version__}-win64"
    archive = shutil.make_archive(str(ROOT / "dist" / name), "zip",
                                  str(ROOT / "dist"), "AirTouch")
    size = Path(archive).stat().st_size / 1024 / 1024
    print(f"Paquete   : {archive}  ({size:.0f} MB)")
    print(f"\nPara publicar: crea una release con la etiqueta v{__version__} "
          f"y sube ese .zip.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
