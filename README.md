# AirHand

Controla Windows con las manos. Tu iPhone hace de cámara y el vídeo **nunca
sale de tu red local**.

**→ [Instalación guiada](https://pablodev-star.github.io/AirHand/)**

Este repositorio contiene el sitio de instalación: una guía paso a paso pensada
para alguien que no ha programado nunca y que no tiene nada descargado.

---

## Las dos piezas

| | Qué es | Dónde |
|---|---|---|
| **AirTouch** | La aplicación de Windows: detecta las manos e interpreta los gestos | Se descarga desde este sitio |
| **AirLink** | La página que convierte el móvil en cámara | [Pablodev-star/AirLink](https://github.com/Pablodev-star/AirLink) |

## Cómo funciona el sitio

La parte importante: **el botón de descarga no lleva ninguna URL escrita a
mano**. Al cargar la página se consulta la API de GitHub por la última
publicación del repositorio y se usa el primer archivo instalable que traiga.

```js
const API = 'https://api.github.com/repos/Pablodev-star/AirHand/releases/latest';
```

Consecuencia práctica: **para sacar una versión nueva basta con publicarla**.
Ni esta página ni el comprobador de actualizaciones de la aplicación necesitan
ningún cambio. Si mañana el archivo se llama distinto o cambia de tamaño, todo
sigue funcionando.

Lo mismo dentro de la aplicación: `airtouch/net/updates.py` consulta la misma
API, compara el número de versión y ofrece la descarga.

## Publicar una versión nueva

1. Sube el número en `airtouch/version.py`:
   ```python
   __version__ = "1.1.0"
   ```
2. Compila:
   ```bat
   .venv\Scripts\python.exe build.py
   ```
   Genera `dist\AirHand-1.1.0-win64.zip`.
3. En GitHub: **Releases → Draft a new release**, etiqueta `v1.1.0`, sube el
   `.zip` y publica.

Ya está. La página de instalación ofrecerá la nueva descarga y quien tenga la
aplicación abierta verá el aviso de actualización. **No hay que tocar código.**

### Sobre el número de versión

La comparación entiende las formas habituales de etiquetar: `v1.2.3`,
`1.2.3-beta`, `release-2.1.0`. Y ordena bien `1.10.0` por encima de `1.9.0`,
que es el error clásico de comparar versiones como si fueran texto.

## Estructura

```
index.html   la guía completa: requisitos, 6 pasos, gestos, ayuda
app.js       descarga automática desde la API, progreso, detección del sistema
style.css
icons/
```

Sin dependencias, sin fuentes externas, sin analítica. Unos 30 KB.

## Licencia

MIT.
