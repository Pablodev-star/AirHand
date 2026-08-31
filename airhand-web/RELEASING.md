# Publicar una versión

Todo está automatizado: **subir una etiqueta compila y publica**. No hay que
tocar la página de instalación ni el comprobador de actualizaciones, porque los
dos preguntan a la API de GitHub en lugar de tener URLs escritas a mano.

## El proceso

1. Sube el número de versión en `airtouch/version.py`:

   ```python
   __version__ = "1.1.0"
   ```

2. Confirma y sube la etiqueta:

   ```bash
   git add -A
   git commit -m "Versión 1.1.0"
   git tag v1.1.0
   git push origin main --tags
   ```

3. Ya está. GitHub Actions:
   - clona AirLink (que vive en su propio repositorio) dentro de `airlink-web/`
   - instala las dependencias
   - **pasa las pruebas** — si fallan, no se publica nada
   - compila con PyInstaller
   - comprueba que el ejecutable y el `.zip` existen
   - crea la publicación con el `.zip` adjunto

En unos minutos, la página de instalación ofrecerá la descarga nueva y quien
tenga la aplicación abierta verá el aviso de actualización.

## Publicar a mano

Si prefieres no usar etiquetas: **Actions → Compilar y publicar → Run
workflow**, y escribe la etiqueta.

Y si quieres compilar en tu equipo:

```bat
.venv\Scripts\python.exe build.py
```

Deja `dist\AirHand-<versión>-win64.zip` listo para subir a mano.

## Qué hay que revisar antes

- Las pruebas pasan: `python tests\test_engine.py`
- El ejecutable **arranca**. Compilar sin errores no garantiza que funcione:
  hay fallos que solo salen al ejecutar el binario (rutas, imports que
  PyInstaller no detecta). Ábrelo y comprueba que llega al panel.
- La versión de `version.py` coincide con la etiqueta.
