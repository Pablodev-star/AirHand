# Publicar una versión

Todo está automatizado: **subir una etiqueta compila y publica**. No hay que
tocar la página de instalación ni el comprobador de actualizaciones, porque los
dos preguntan a la API de GitHub en lugar de tener URLs escritas a mano.

## El proceso

Un solo comando:

```bat
.venv\Scripts\python.exe release.py 1.1.0
```

Eso comprueba que el árbol está limpio, que estás en `main` y sincronizado,
que la versión avanza, pasa las pruebas, sube el número en `version.py`,
confirma, etiqueta y empuja. Si algo no cuadra, se planta antes de tocar nada.

Luego GitHub Actions:

- clona AirLink (vive en su propio repositorio) dentro de `airlink-web/`
- **comprueba que la etiqueta coincide con `version.py`**
- pasa las pruebas del motor y del asistente
- compila con PyInstaller
- **ejecuta `--selftest` sobre el binario recién hecho**
- publica el `.zip` solo si todo lo anterior fue bien

En unos minutos, la página de instalación ofrece la descarga nueva y quien
tenga la aplicación abierta ve el aviso de actualización. Ninguna de las dos
cosas hay que tocarla: preguntan a la API de GitHub.

### Por qué se comprueba la etiqueta

El nombre del `.zip` sale de `version.py`, pero lo que dispara la publicación
es la etiqueta. Etiquetar `v1.1.0` sin subir el número publicaba una versión
`v1.1.0` que contenía un `AirHand-1.0.0-win64.zip`: quien la descargase se
llevaba el binario viejo creyendo que era el nuevo, sin un solo error por
ninguna parte. `release.py` lo hace imposible y el flujo lo verifica igual,
por si alguien etiqueta a mano.

## Publicar a mano

Si prefieres no usar el script: **Actions → Compilar y publicar → Run
workflow**, y escribe la etiqueta. La comprobación de versión sigue activa.

Y si quieres compilar en tu equipo:

```bat
.venv\Scripts\python.exe build.py
```

Deja `dist\AirHand-<versión>-win64.zip` listo para subir a mano.

## Qué hay que revisar antes

Casi nada, porque `build.py` no empaqueta si el ejecutable no funciona: al
terminar de compilar lo ejecuta con `--selftest` y comprueba de verdad que
MediaPipe carga, que los modelos y la web de AirLink viajan dentro y que la
pila de red responde. Si algo falla, no genera el `.zip`.

Esa comprobación existe por un fallo real: excluir `matplotlib` del paquete
para ahorrar espacio parecía inofensivo, pero `mediapipe/__init__.py` lo
importa de forma indirecta. El resultado era un ejecutable que arrancaba, que
mostraba el panel con normalidad y que **no detectaba ni una mano**. Compilaba
sin un solo error. Comprobar que "abre" no habría bastado.

Queda por revisar a mano:

- La versión de `version.py` coincide con la etiqueta.
- Un repaso con la cámara puesta, que ningún diagnóstico sustituye.

## Si algo va mal en una instalación

El mismo diagnóstico está disponible para quien tenga la aplicación:

```bat
AirTouch.exe --selftest
```

Escribe el resultado en `%APPDATA%\AirTouch\logs\airtouch.log`.
