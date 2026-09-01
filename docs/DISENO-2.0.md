# AirTouch 2.0 — CRISTAL VIVO

**Especificación de diseño e implementación. Documento único de referencia.**
Sustituye por completo a `airtouch/ui/*` y `airtouch/overlay/*` (6022 líneas actuales).
Todo lo que no esté aquí, no se hace. Todo lo que esté aquí, se hace con los valores que están aquí.

---

## 0. Veredicto: qué dirección gana y por qué

Se han evaluado tres direcciones: **Cristal**, **Pliego** y **Pulso**.

**Gana CRISTAL**, injertando de Pulso toda su infraestructura de movimiento y su motor de
telemetría, y de Pliego su maquinaria tipográfica y su disciplina de regiones de daño de
tamaño constante. El sistema resultante se llama **CRISTAL VIVO**.

Razones, en el orden de peso que fijó el encargo:

1. **Sensación.** El encargo pide dos cosas concretas: la mano tendida de Apple en el
   asistente, y la energía y la jerarquía-por-tamaño del menú de Project Flight. Cristal es
   la única de las tres que resuelve las dos a la vez. Su mosaico de tarjetas grandes con
   fondo a sangre, títulos enormes en mayúsculas alineados a la derecha, iconos de línea
   fina y barra de navegación inferior en píldora **es** la lección de Project Flight
   traducida sin copiarla; y su asistente convierte la profundidad en narrativa (cada
   página es una lámina que se acerca, y la última *se expande* hasta convertirse en el
   panel). **Pliego se descarta como base por contradecir directamente la inspiración 2**:
   es austero, sin cajas, sin imagen a sangre, deliberadamente sin color y sin vida
   animada. Es una dirección preciosa y es la equivocada para este encargo. **Pulso se
   descarta como base por riesgo de "juguete"**: negro casi puro con seis a nueve
   superficies animadas simultáneas se lee como panel de gamer, y su propio texto admite
   que el modo claro es su punto débil estructural.
2. **Implementabilidad.** Cristal se apoya en un solo truco (recorte del lienzo
   pre-desenfocado + lavado) que en Qt funciona de verdad **mientras el fondo lo pinte la
   propia aplicación**, que es el 100 % de los casos del panel y del asistente. Nada de
   QtWebEngine, nada de shaders, nada de dependencias. Sus tres piezas caras —atlas de
   sombras 9-slice, caché del lienzo y pintor de filos— son QPainter puro.
3. **Modo claro.** Cristal es la única que llegó con una receta de modo claro pensada
   (filos invertidos, sombras acortadas y enfriadas, escalón de luminancia del 4 %) en vez
   de con una inversión de paleta.
4. **Estadísticas útiles.** Aquí gana Pulso por goleada, y por eso su motor de datos entra
   entero: `telemetry.py` con anillos de numpy preasignados, presupuesto de retardo,
   calidad del pinch por cierre y estabilidad del puntero. Cristal aportaba los gráficos;
   Pulso aporta la honestidad de los datos y el rendimiento del acopio.

### Injertos aceptados

| Origen | Qué se injerta | Por qué |
|---|---|---|
| Pulso | `motion.py` con un **único `Beat`** de 16 ms para toda la ventana | Hoy hay siete temporizadores compitiendo. Es la mayor ganancia de CPU de la UI. |
| Pulso | `telemetry.py` (anillos numpy) y las tarjetas de **presupuesto de retardo**, **calidad del pinch por cierre** y **estabilidad del puntero** | Es el único análisis que responde preguntas en vez de dibujar líneas. |
| Pulso | **Blit desplazado** (`QPixmap.scroll`) en toda traza temporal | Sin él, cada osciloscopio repinta 46 kpx por fotograma. |
| Pulso | **Modo ahorro automático** con histéresis | El encargo exige que vaya fino en PCs débiles. |
| Pulso | Overlay: **rayado diagonal** del modo seguro, **ausencia de cápsula** en control activo, `_static_since`, y rectángulo de daño propio para la lámpara que respira | Comunica sin leer y baja el reposo del overlay por debajo de 0,01 Mpx. |
| Pulso | Tarjeta **LA MANO** con esqueleto en vivo en vez de vídeo desaturado | Más barato (~1,5 ms), más bonito, y no obliga a convertir QImage por fotograma. |
| Pulso | Asistente: **espera con nombre**, **estimación viva de tiempo**, y la página "Tu pinch" donde el sistema **ya te había calibrado en silencio** | Es el pico absoluto de sensación Apple de las tres propuestas. |
| Pliego | `tipo.py`: fábrica de `QFont` con **tracking real** y cifras tabulares | Qt **ignora** `letter-spacing` y `line-height` en QSS. Hoy `theme.py` los escribe y no hacen nada. Sin esta pieza, media especificación tipográfica es decorativa. |
| Pliego | **Dos escalas tipográficas** con histéresis por ancho de ventana | Evita que los titulares se rompan en portátiles de 1366×768. |
| Pliego | **Regla dura**: ninguna región de daño del overlay puede depender del ancho de la pantalla ni del ancho de una ventana | Reduce 28× la región de las barras de ventana. Es gratis. |
| Pliego | **Cambio de tema con `grab()` + fundido de 220 ms** | Elimina el parpadeo del re-styling de Qt por dos líneas de código. |
| Pliego | **Recibo con puntos conductores** al final del asistente y **pie de consecuencia** en cada sección de ajustes | Lo que convierte "unos ajustes" en "unos ajustes buenos". |

---

## 1. Principios rectores

1. **La jerarquía se dibuja con altura y tamaño, nunca con líneas divisorias ni con cajas
   dentro de cajas.** Cinco niveles de elevación y una escala tipográfica con saltos
   grandes. Si hace falta una línea para separar dos cosas, están mal colocadas.
2. **El material se usa para algo.** Los gráficos *son* el fondo de la lámina, no van
   dentro de un recuadro. El filo claro de una lámina es el canal de retroalimentación
   barato. La profundidad es la navegación. Si el vidrio se queda en decoración por encima
   de un panel corriente, no habrá merecido la pena.
3. **El color significa.** El acento y los tintes de modo aparecen cuando hay un modo o un
   estado que comunicar. Cromo (texto, filos, rejillas, iconos) estrictamente monocromo.
   Cero degradados decorativos, cero neón fuera de las trazas.
4. **Ningún dato inventado.** Todo lo que se pinta sale de `output_ready`, `frame_ready`,
   `stats_ready`, `status_changed` o `log_line`. Toda métrica derivada lleva escrito en
   11 px cómo se calcula.
5. **El presupuesto de repintado manda sobre la estética.** Ninguna decisión visual puede
   subir el coste en reposo. Se verifica con un contador de píxeles dañados, no de oídas.

---

## 2. Arquitectura de archivos y orden de implementación

Nada visible se puede construir antes de las cinco primeras piezas. Ese es el precio de
esta dirección y hay que pagarlo por delante y bien.

```
airtouch/ui/
  tokens.py      ~260   paletas oscura y clara, rampa de modo, escala tipográfica, radios
  theme.py       ~200   API pública (apply/qss/signals/C/qcolor/rgba/mix), QSS mínimo
  tipo.py        ~250   fábrica de QFont: tracking, tnum, fallbacks, dos escalas, Parrafo
  glass.py       ~620   lienzo vivo cacheado, atlas de sombras 9-slice, filos, Sheet
  motion.py      ~300   Beat, curvas, Spring, Smooth, Stagger, SpecularSweep, ahorro
  widgets/
    __init__.py
    base.py      ~340   Sheet, Inset, Pill, Divider-free helpers
    controls.py  ~520   Toggle, Button, Slider, Segmented, Field, SettingRow, Chip
    display.py   ~380   Metric, Sparkline, Dot, Badge, Ring, LeaderLine
  telemetry.py   ~440   anillos numpy, agregados a 4 Hz, sugerencias
  charts.py      ~780   Trace, AreaChart, Histogram, Donut, Scatter, Heartbeat, Strip
  dashboard/
    shell.py     ~420   ventana, zonas A/B/C, navegación, contratos de app.py
    live.py      ~300   columna viva (identidad, núcleo, sesión, atajos)
    mosaic.py    ~360   rejilla de tarjetas, zoom tarjeta→página
    cards.py     ~520   RENDIMIENTO, LA MANO, GESTOS, SEGURIDAD, ENLACE, NOVEDADES
    page_stats.py ~560  página profunda de análisis
    page_camera.py ~240
    page_gestures.py ~280
    page_log.py  ~160
  settings/
    panel.py     ~380   dos paneles + búsqueda en vivo
    sections.py  ~620   definición declarativa de todas las filas
  wizard/
    wizard.py    ~380   armazón, hilo de progreso, transiciones, contrato
    pages.py     ~980   las siete páginas
  compact.py     ~180
  tray.py        ~110
  calibration.py ~260
  celebrate.py   ~200
  handart.py     ~300
  live_preview.py ~170
  airlink_panel.py ~200
airtouch/overlay/
  style.py       ~260   tokens del overlay, constantes de daño
  canvas.py      ~820   cursor, cápsula, barras, teclado, disciplina de daño
```

Total estimado ≈ 9 800 líneas. Es más que las 6 022 actuales; es un rehaul, no una mejora.

**Orden obligatorio:** `tokens` → `tipo` → `glass` → `motion` → `widgets` → `telemetry` →
`charts` → `dashboard/shell` → resto del panel → `settings` → `wizard` → `overlay` →
`compact`/`tray`.

**Hito de riesgo, antes de nada:** una pantalla de prueba desechable con tres láminas E2/E3/E4
sobre el lienzo vivo, en claro y en oscuro, a brillo 100 %. Si el escalón de luminancia del
4 % no basta en claro, se sube `edge.dark` a 0.14 — **nunca** se añade una línea divisoria.

---

## 3. Tokens

### 3.1 Paleta oscura

**Lienzo (E0, nunca plano).** Cuatro manchas radiales sobre una base:

| token | valor | uso |
|---|---|---|
| `canvas.base` | `#090B10` | base plana |
| `canvas.light` | `#22293A` α 0.40 | mancha arriba-izquierda, radio 62 % de la diagonal. **Es la fuente de luz del sistema.** |
| `canvas.cool` | `#0C1C2E` α 0.34 | mancha abajo-derecha |
| `canvas.tint` | `#103038` α 0.22 | mancha medio-derecha |
| `canvas.vignette` | `#000000` α 0.32 | viñeta concentrada en la esquina inferior derecha |

**Vidrio** (lavados sobre el lienzo; entre paréntesis el hex resuelto sobre `canvas.base`):

| token | valor | resuelto |
|---|---|---|
| `glass.wash` | `rgba(255,255,255,0.055)` | `#171A22` |
| `glass.raised` | `rgba(255,255,255,0.095)` | `#202430` |
| `glass.float` | `rgba(22,25,33,0.78)` + blanco 0.08 | `#1C2029` |
| `glass.sunken` | `rgba(0,0,0,0.28)` | `#070910` |

**Filos** (el borde de 1 px que recoge la luz):

`edge.light` `rgba(255,255,255,0.14)` (arriba + izquierda) ·
`edge.dark` `rgba(0,0,0,0.45)` (abajo + derecha) ·
`edge.hair` `rgba(255,255,255,0.07)` (anillo completo, sin dirección) ·
`edge.flash` `rgba(255,255,255,0.30)` (destello de 300 ms).

**Sombras:** `shadow.key` `rgba(0,0,0,0.50)` · `shadow.ambient` `rgba(0,0,0,0.26)`.

**Texto:** `text.primary` `#F2F4F9` · `text.secondary` `#A6AEC0` · `text.tertiary` `#6F7789` ·
`text.quiet` `#4A5162`.

**Acento y estado:** `accent` `#7C8CFF` · `accent.soft` `rgba(124,140,255,0.16)` ·
`accent.glow` `rgba(124,140,255,0.32)` · `ok` `#5FE3B0` · `warn` `#FFC46B` ·
`danger` `#FF7A85` · `info` `#74C0FF`.

**Rampa de modo** (idéntica en panel y overlay; es el corazón del sistema, se indexa
directamente por `airtouch.gestures.events.Mode`):

| Mode | oscuro | claro |
|---|---|---|
| `IDLE` | `#8A94A6` | `#6B7686` |
| `POINTING` | `#E8EDF5` | `#2A3140` |
| `PINCH_PENDING` | `#7ED6FF` | `#1E7FB8` |
| `SCROLLING` | `#B29EFF` | `#6B4FD8` |
| `DRAGGING` | `#5FE3B0` | `#0F9E74` |
| `WINDOW_MOVE` | `#FFC46B` | `#A66A05` |
| `WINDOW_RESIZE` | `#FFC46B` | `#A66A05` |
| `ZOOMING` | `#96C8FF` | `#1F6FD0` |
| `KEYBOARD` | `#E8EDF5` | `#2A3140` |
| `PAUSED` | `#FF7A85` | `#C93848` |
| *flick* (`flick_charge > 0`) | `#FFB05C` | `#B85C05` |

### 3.2 Paleta clara

El modo claro **no** es la oscura invertida. En vidrio claro las sombras largas y negras
ensucian, así que se acortan y se enfrían, y el filo dominante pasa a ser el oscuro de
abajo-derecha.

**Lienzo:** `canvas.base` `#EEF0F6` · `canvas.light` `#FFFFFF` α 0.70 (arriba-izquierda) ·
`canvas.cool` `#DCE0EC` α 0.55 (abajo-derecha) · `canvas.tint` `#E4ECF7` α 0.40 · **sin viñeta**.

**Vidrio:** `glass.wash` `rgba(255,255,255,0.72)` (`#F7F8FC`) · `glass.raised`
`rgba(255,255,255,0.88)` (`#FCFDFF`) · `glass.float` `rgba(255,255,255,0.94)` ·
`glass.sunken` `rgba(15,23,42,0.045)` (`#E7EAF1`).
**El escalón de luminancia entre lienzo y vidrio es del 4 %: es lo mínimo para que una
lámina se lea sin línea.**

**Filos:** `edge.light` `rgba(255,255,255,0.95)` · `edge.dark` `rgba(15,23,42,0.10)`
— este es el separador principal; **si un panel desaparece a brillo 100 %, se sube a 0.14** —
· `edge.hair` `rgba(15,23,42,0.06)`.

**Sombras** (más cortas y azuladas; desenfoques y desplazamientos al **60 %** de los de
oscuro): `shadow.key` `rgba(31,41,71,0.14)` · `shadow.ambient` `rgba(31,41,71,0.07)`.

**Texto:** `#10131B` / `#4E5768` / `#798194` / `#98A0B0`.

**Acento y estado:** `accent` `#4257E8` · `accent.soft` `rgba(66,87,232,0.12)` ·
`ok` `#0F9E74` · `warn` `#A66A05` · `danger` `#C93848` · `info` `#1F6FD0`.

### 3.3 Tipografía

Familias, por talla óptica real de Windows 11:

- ≥ 16 px → `"Segoe UI Variable Display"`
- 12–15 px → `"Segoe UI Variable Text"`
- ≤ 11 px → `"Segoe UI Variable Small"`
- Mono → `"Cascadia Mono"` → `Consolas`

**Cadena de respaldo obligatoria** (Windows 10 no trae Variable): `Segoe UI Variable X` →
`Segoe UI Semibold` → `Segoe UI`. Se comprueba **una vez al arrancar** con
`QFontDatabase.families()`; si falta Variable, `display` baja de 46 a 40 px y su tracking de
−1.6 a −1.1 px, y `mosaico` baja de 38 a 34 px.

**Escala** (tamaño px / peso / tracking absoluto px / interlineado):

| rol | tamaño | peso | tracking | interlineado | uso |
|---|---|---|---|---|---|
| `display` | 46 | 700 | −1.6 | 1.05 | héroe del asistente, y solo ahí |
| `title` | 30 | 650 | −0.8 | 1.10 | título de página del panel |
| `h1` | 21 | 620 | −0.3 | 1.15 | título de lámina grande |
| `h2` | 16 | 600 | −0.1 | 1.20 | título de lámina media |
| `body` | 13.5 | 400 | 0 | 1.35 | |
| `body-fuerte` | 13.5 | 600 | 0 | 1.35 | |
| `caption` | 11.5 | 500 | +0.2 | 1.30 | secundario dentro de láminas |
| `overline` | 10.5 | 700 | +1.2 | 1.20 | MAYÚSCULAS, etiquetas de métrica y sección |
| `metric` | 34 | 300 | −1.0 | 1.00 | cifra grande. **El peso Light es la firma; con 600 esto parece un dashboard corporativo.** |
| `metric-xl` | 46 | 300 | −1.4 | 1.00 | única cifra de la página de análisis |
| `mosaico` | 38 | 800 | +2.0 | 1.00 | MAYÚSCULAS, alineado a la derecha: título a sangre de tarjeta grande |
| `axis` | 10 | 500 | +0.3 | 1.10 | etiquetas de eje, `tnum` |
| `mono` | 12 | 300 | 0 | 1.55 | registro |

**Segunda escala**, activa por debajo de **1180 px de ancho de ventana**, con histéresis de
40 px aplicada en `resizeEvent`: `display` 36 / −1.2 · `title` 24 / −0.6 · `mosaico` 28 / +1.6 ·
`metric` 28 / −0.8 · `metric-xl` 36 / −1.1. El resto no cambia.

**Cifras tabulares obligatorias** en todo lo que cambie en vivo:
`f.setFeature(QFont.Tag("tnum"), 1)` (verificado disponible en el PySide6 6.8.3 del proyecto).
Si la llamada fallara, se cae a `Cascadia Mono` para esa etiqueta. Sin `tnum` los números
bailan horizontalmente y se rompe toda la sensación de solidez.

**Qt ignora `letter-spacing` y `line-height` en QSS.** Todo el tracking se aplica con
`QFont.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, px)` desde `tipo.py`, y todo el
interlineado con la clase `Parrafo` (`QTextLayout` + `QTextOption`), no con QLabel a secas.
No se escribe una sola propiedad tipográfica en el QSS más allá de la familia por defecto.

### 3.4 Espaciado

Base 4 px. Escala: **4, 8, 12, 16, 20, 24, 32, 40, 56, 72**.

Margen de ventana 28 · canalón de rejilla 16 · padding interior de lámina 20 (24 en las
grandes) · separación entre filas de ajuste 12 · separación entre grupos 32 · altura de fila
de ajuste 56 · altura de fila de lista compacta 40.

**Regla dura:** entre dos láminas de la **misma** elevación el hueco es **16**; entre
elevaciones distintas es **0** (una se apoya sobre la otra) o **24** (flota claramente por
encima). **Nunca 8**: a 8 px dos vidrios parecen un error de layout.

Anchos fijos: columna viva **320** · lista de secciones de ajustes **200** · barra flotante
inferior alto **56** · página profunda de análisis: margen 32 en vez de 28.

### 3.5 Radios

`r-xs` **8** (chips diminutos, puntos de paso) · `r-sm` **12** (botones, campos; teclas del
overlay 11) · `r-md` **18** (insets y placas hundidas) · `r-lg` **24** (láminas normales) ·
`r-xl` **32** (láminas héroe y el diálogo del asistente) · `r-full` (píldoras: barra de
navegación, badges, cápsula del overlay).

**Radios concéntricos, sin excepción:** radio del hijo = radio del padre − padding. Los
hijos directos de una lámina `r-lg` con padding 20 se dibujan a `r-md` 18 dejando 6 px desde
el borde interior. Esta regla es la que hace que el vidrio parezca fabricado y no recortado.
Nunca dos radios distintos en la misma esquina física.

### 3.6 Elevación

Cinco niveles. Cada uno es (fondo · filos · sombra · desplazamiento). **Todo lo pinta
`glass.py`; ningún widget dibuja su propia sombra.**

- **E0 LIENZO** — el fondo vivo. Sin filos, sin sombra. Es lo único que se mueve solo.
- **E1 PLACA (hundida)** — relleno `glass.sunken`; filo **invertido** (oscuro arriba-izquierda
  a 0.30, claro abajo-derecha a 0.06) para que se lea como un rebaje; sin sombra exterior.
  Uso: canal de deslizador, pozo de gráfico, consola del registro.
- **E2 LÁMINA** — recorte del lienzo desenfocado + `glass.wash`; filo claro arriba-izquierda
  1 px, filo oscuro abajo-derecha 1 px; sombra key desenfoque 32 desplazamiento (4, 10) +
  ambient desenfoque 12 desplazamiento (0, 2). Uso: tarjetas del mosaico, paneles de ajustes.
- **E3 LÁMINA ALZADA** — `glass.raised`; mismos filos con el claro a 0.18; sombra key
  desenfoque 44 desplazamiento (5, 14); escala 1.008 respecto de E2. Uso: hover, tarjeta
  seleccionada, el Núcleo de control.
- **E4 FLOTANTE** — `glass.float`; filo claro 0.22; **dos** sombras: key desenfoque 64
  desplazamiento (0, 22) α 0.55, y una apretada desenfoque 8 desplazamiento (0, 3) α 0.40 que
  la "pega" visualmente. Uso: barra de navegación inferior, menús, avisos, diálogo del
  asistente, cápsula del overlay.

En claro, todos los desenfoques y desplazamientos se multiplican por **0.60** y se usan
`shadow.key`/`shadow.ambient` claros.

---

## 4. `glass.py` — la capa de pintado

Son ~620 líneas que no producen nada visible. Si no se hacen primero y bien, la dirección
degenera en "tarjetas planas con un degradado", que es peor que una dirección plana hecha
con honestidad.

### 4.1 Lienzo vivo (`CanvasSource`)

- Un **QImage de 320×180 como máximo, pase lo que pase**, con la base y las cuatro manchas
  radiales dibujadas con `QRadialGradient`.
- Se regenera **como máximo a 10 Hz**, y solo si alguna mancha se ha movido más de 1 px en
  el búfer pequeño.
- Las manchas derivan por trayectorias senoidales de periodo 23 s, 31 s y 41 s, amplitud
  ≤ 8 % del lado.
- **Tres compuertas de congelación obligatorias**: se congela por completo si (a) la ventana
  no está activa, (b) el motor está corriendo y el panel está en modo compacto, o
  (c) `cfg.ui.reduce_motion`. Sin las tres, el fondo vivo se come el presupuesto que el
  motor de visión necesita.
- Se expone `canvas_image()` (el búfer pequeño) y `blurred_crop(rect) -> QPixmap`, que
  devuelve el recorte reescalado con `Qt.SmoothTransformation`. Como el búfer es 8× menor
  que la ventana, **el reescalado es el desenfoque**: no hace falta un blur de verdad.
- **Paralaje:** el lienzo se desplaza `0.03 ×` el delta del cursor, máximo ±10 px; las
  láminas no se mueven. Se muestrea el cursor a 30 Hz y solo dentro de la ventana activa.
  Coste: el offset de un `drawImage`, cero píxeles extra.

### 4.2 Atlas de sombras 9-slice (`ShadowAtlas`)

- Para cada tupla `(radio, desenfoque, alfa)` se genera **una vez** un `QImage` de 128×128
  con el rectángulo redondeado en el canal alfa y **tres pasadas de box blur**; se cachea en
  un `dict`.
- Se pinta con 8 `drawImage` (4 esquinas + 4 lados estirados) y **se salta el centro**.
- **`QGraphicsDropShadowEffect` queda PROHIBIDO en todo el proyecto.** Hoy está en cada
  `Card` (`airtouch/ui/widgets.py:70`): fuerza un render fuera de pantalla de todo el
  subárbol en cada repintado y desactiva el ClearType. Sustituirlo no es opcional: es la
  mayor ganancia de rendimiento del rehaul. Si alguien lo reintroduce "porque es más rápido
  de escribir", la dirección se cae.
- `QGraphicsOpacityEffect` sí se permite, pero solo durante una animación y se **retira** al
  terminar (como ya hace `anim.fade()` hoy).

### 4.3 Pintor de láminas (`Sheet` / `paint_sheet`)

`paint_sheet(painter, rect, elevation, radius, *, edge_light=None, tint=None, bleed=None)`:

1. sombra desde el atlas,
2. recorte del lienzo desenfocado (solo E2/E3/E4) o relleno plano (E1),
3. lavado del nivel,
4. `bleed` opcional: el `QPixmap` del gráfico de fondo, recortado al rounded-rect, a
   opacidad **tope 0.45 y no ajustable**,
5. **velo obligatorio** cuando hay `bleed`: `QLinearGradient` vertical en el **55 % inferior**,
   de `rgba(0,0,0,0.62)` a transparente (en claro `rgba(255,255,255,0.72)`),
6. filos: claro arriba+izquierda, oscuro abajo+derecha, con `QPen` cosmético de ancho 0 sobre
   coordenadas enteras + 0.5 para que caigan en un píxel exacto a DPR 1.25 / 1.5,
7. contenido.

**Filos que responden al estado** (canal de retroalimentación barato): 0.14 en reposo · 0.18
en hover · 0.24 mientras algo dentro está activo · 0.30 en destello. Cambiarlo cuesta un
`QPen` y comunica más que un borde de color.

### 4.4 Mica: opcional, apagado por defecto

Se intenta `DwmSetWindowAttribute(hwnd, 38, DWMSBT_MAINWINDOW=2)` **solo con ctypes** cuando
`cfg.ui.mica = True` (nuevo campo, por defecto `False`). En Windows 10 la llamada falla en
silencio y se cae al fondo pintado. **La dirección no depende de Mica**: el lienzo pintado es
el camino principal, Mica es una mejora opcional para quien la quiera. Degradar, no reventar.

---

## 5. `motion.py` — el movimiento

### 5.1 Un solo latido

`Beat` es **un único `QTimer` de 16 ms para toda la ventana**. Los widgets animados se
registran con `beat.join(self)` y se desregistran en `hideEvent` con `beat.leave(self)`.
Cada participante expone `tick(dt) -> bool` (True = sigue animando). Cuando nadie devuelve
True, el intervalo sube a 33 ms y el temporizador se para a los 500 ms.

Hoy hay temporizadores sueltos en `Dot`, `SegmentedControl`, `PinchGauge`, `NavRail`,
`GestureIndicator`, `Ring` y `StepDots`: **desaparecen todos**.

**Compuertas de frecuencia dentro del Beat**, por participante:
60 Hz (cursor, arrastre, deriva de valores) · **20 Hz** (respiraciones y glows) ·
**10 Hz** (lienzo) · **4 Hz** (agregados de estadísticas).

### 5.2 Curvas

- `EASE_GLASS = QEasingCurve.OutQuint` — entradas de lámina, transiciones de página,
  cualquier cosa que llegue desde lejos. Arranca muy rápido y se asienta largo: es lo que
  hace que un objeto pesado parezca pesado.
- `EASE_SOFT = InOutCubic` — reflujos de layout, cambios de tamaño, barridos especulares.
  Nunca para entradas.
- `EASE_LIFT = OutBack` con **sobrepaso 1.12** (no el 1.70 por defecto de Qt, que es de
  dibujos animados) — todo lo que se acerca a ti: hover, pop de un badge, marca de
  verificación.
- `EASE_EXIT = InQuad` — **las salidas siempre con esta curva y siempre más cortas que la
  entrada: salida = 0.6 × entrada.** Un objeto que se va no merece atención.

### 5.3 Valores continuos

**Nunca se anima un dato en vivo con `QPropertyAnimation`**: el objetivo cambia antes de que
la animación termine.

- `Smooth` — la clase que ya existe en `airtouch/ui/anim.py:33`, se conserva **tal cual**
  (interpolación exponencial independiente del framerate). τ por defecto 0.14 s.
- `Spring` — nueva clase en `motion.py`: integrador crítico-subamortiguado con **ζ = 0.80,
  ω = 15 rad/s** (se asienta en ~340 ms con ~6 % de rebasamiento), conducido por el Beat.
  Se usa donde el objeto parte con velocidades distintas: perilla del interruptor, píldora
  de navegación, tarjeta que se levanta, botón que se habilita. **No se usa `OutBack` para
  esto**, porque rebota igual salga de donde salga. Con `reduce_motion`, ζ pasa a 1.0.

**Constantes de tiempo τ** (segundos): puntero en minimapa 0.055 · aguja/columna de pinch
0.045 · carga de catapulta 0.06 · medidores de fps y latencia 0.28 (más rápido tiembla y
parece roto) · cruce de color de modo 0.13 · progreso de anillo 0.20 · barras de histograma
0.35 · reparticiones de dona 0.25 · ancho de la cápsula del overlay 0.12 · cursor del overlay
0.055 · pinch del overlay 0.07 · barra de ventana 0.10 · teclado 0.38.

### 5.4 Duraciones

- **micro** 120 ms entrada / 90 ms salida — hover, pulsación, perilla, cambio de color de filo.
- **elemento** 200 ms — alzado de lámina, aparición de badge, tooltip, chip que se marca.
- **sección** 340 ms entrada / 200 ms salida, **solapadas 120 ms** — cambio de página del
  panel. Duración percibida ≈ 420 ms.
- **héroe** 520 ms — cambio de página del asistente, expansión de tarjeta a página.
- **celebración** 900 ms.
- **ambiente** 8–14 s (deriva de manchas), 3.2 s (respiración del Núcleo), 1.6 s (aviso de
  pausa), 3.6 s (lámpara del overlay).
- **barrido especular** 620 ms.

### 5.5 Patrones

1. **ENTRADA ESCALONADA.** Al entrar en una página, los hijos aparecen con opacidad 0→1 y
   desplazamiento +14 px en Y, **45 ms** de retardo entre ellos, 380 ms cada uno, `EASE_GLASS`.
   **Máximo 6 escalonados**: del séptimo en adelante entran todos junto al sexto. Solo al
   entrar en la página, **jamás** al actualizar datos.
2. **PARALAJE DE PROFUNDIDAD.** §4.1. El fondo se mueve, el vidrio no: es el indicio más
   fuerte de que hay dos planos.
3. **HOVER DE LÁMINA.** E2→E3 en 160 ms `EASE_LIFT`: sombra 32→44, desplazamiento
   (4,10)→(5,14), lavado +0.04 de alfa, filo claro 0.14→0.18, contenido +2 px arriba. Salida
   en 96 ms `EASE_EXIT`. El borde se tiñe además al color de modo a α 0.35.
4. **BARRIDO ESPECULAR.** Cuando una lámina cambia de estado de forma importante (arranca el
   motor, se completa un paso del asistente, se conecta el móvil): banda blanca de 120 px de
   ancho, α 0.22, `QLinearGradient` a 20° de la vertical, cruza la lámina de izquierda a
   derecha en 620 ms `EASE_SOFT`, recortada al rounded-rect. **Una sola vez, nunca en bucle.**
5. **CIFRAS QUE RUEDAN.** Las métricas interpolan con `Smooth` hacia el nuevo valor; la
   sparkline empuja el punto sin animar. **Nunca se anima un número que cambia más de 4 veces
   por segundo**, y solo se llama a `update()` cuando cambia el **texto ya formateado**.
6. **TRANSICIÓN DE PÁGINA DEL PANEL.** La saliente escala a 0.985 y se desvanece en 180 ms
   `EASE_EXIT`; la entrante arranca a los 120 ms desde escala 1.015, Y +10, opacidad 0, y se
   asienta en 340 ms `EASE_GLASS`. La escala se aplica con un `QTransform` en el `paintEvent`
   del contenedor, **no** con `setGraphicsEffect` por hijo. **La columna viva (zona A) y la
   barra inferior (zona C) no se mueven nunca**: eso es lo que hace que el panel parezca un
   aparato y no una web.
7. **TRANSICIÓN DE PÁGINA DEL ASISTENTE — en profundidad, no lateral.** La saliente retrocede
   (escala 0.94, opacidad 0, su lavado se oscurece +0.10 para simular que se aleja de la luz)
   en 260 ms; la entrante sube desde escala 1.06, opacidad 0, en 480 ms `EASE_GLASS`.
   **Excepción:** el título del asistente es un único `QLabel` persistente que se transforma
   (el texto viejo sube 14 px y se desvanece, el nuevo llega desde 14 px abajo, 260 ms). El
   marco no parpadea nunca: por eso parece un solo lugar que cambia y no siete pantallas.
8. **ZOOM DE TARJETA A PÁGINA.** Al pulsar una tarjeta del mosaico, su `QRect` se anima hasta
   ocupar el área del mosaico en 380 ms `EASE_GLASS` mientras su contenido interior hace
   crossfade al de la página. Es la navegación principal del panel.
   **Plan B obligado y ya decidido:** si en el prototipo tartamudea o el layout de destino
   difiere demasiado del de la tarjeta, se sustituye por crossfade con escala 1.02, que no
   cuesta nada y deja intacta la dirección. Esta decisión se toma **antes** de construir las
   páginas profundas.
9. **PÍLDORA DE NAVEGACIÓN.** Viaja con `Spring` (no se desvanece y reaparece) e **interpola
   también su anchura** a la del rótulo de destino. El glifo entrante cambia de color en
   140 ms lineal: el color no debe rebotar aunque la píldora sí.
10. **CELEBRACIÓN.** Anillo de luz: radio 0→420 px, grosor 3→1 px, α 0.50→0, 900 ms OutQuint;
    simultáneamente **los filos claros de las láminas de la página actual** (no de toda la
    aplicación) saltan a `edge.flash` 0.30 y vuelven en 300 ms; y 46 partículas de confeti
    tintadas con el acento (`airtouch/ui/celebrate.py`, hoy 90 partículas: se bajan a 46 y se
    tintan), pintadas en un hijo transparente que **solo invalida el bbox unión de las
    partículas vivas**. Solo en la última página del asistente y al conectar el móvil por
    primera vez.
11. **CAMBIO DE TEMA EN CALIENTE.** Antes de aplicar la paleta nueva se toma un
    `QWidget.grab()` de la ventana, se pinta como `QLabel` encima a opacidad 1, se aplica el
    tema y se desvanece la captura en 220 ms `EASE_SOFT`. Cuesta una captura una sola vez y
    elimina el parpadeo del re-styling de Qt. En el slot de `theme.signals.changed` se
    **invalidan todos los `QPixmap` cacheados**: atlas de sombras, lienzo, trazas, rejillas.

### 5.6 `reduce_motion` y modo ahorro

`cfg.ui.reduce_motion = True`:
todas las duraciones × 0.35 · sin paralaje · sin deriva de manchas · sin respiraciones ·
sin confeti (se sustituye por una marca de verificación con escala 0.9→1 en 180 ms) ·
`Spring` con ζ = 1.0 · sin escalonados (entrada única) · sin cola ni barridos ambientales
en el overlay. **Se respeta en todas las animaciones sin excepción.**

**Modo ahorro automático:** si `pipeline_fps < 24` durante 3 s seguidos, la interfaz entra en
ahorro: Beat a 33 ms, respiraciones apagadas, rellenos de área planos sin degradado, recorte
del lienzo sustituido por relleno plano, escalonados a 0. Se sale con 5 s por encima de
30 fps (histéresis). Un chip discreto en la barra inferior dice **"ahorro"**, porque callarlo
sería deshonesto.

---

## 6. `telemetry.py` — el motor de datos

Una clase `Telemetry(QObject)` que se suscribe **una sola vez** a `output_ready`,
`stats_ready`, `status_changed` y `log_line`. Vive en el shell del panel, no en las páginas.

### 6.1 Cadencia real (importante)

`Controller._loop` emite `stats_ready` **cada 15 fotogramas**: son ~4 Hz a 60 fps y ~2 Hz a
30 fps. **Ningún gráfico puede asumir un intervalo fijo.** Se guarda un `t = perf_counter()`
junto a cada muestra y todo eje temporal se dibuja contra ese timestamp.

### 6.2 Búferes (numpy preasignado, ≈ 60 KB en total)

| búfer | forma | ventana |
|---|---|---|
| `frame_dt` | f32 × 3600 | 60 s a 60 Hz — periodo entre `output_ready` |
| `pinch` | f32 × 1800 | ~30 s de `pinch_ratio` |
| `pointer` | f32 × (1800, 2) | recorrido del puntero |
| `fps_cam`, `fps_pipe`, `lat`, `proc` | f32 × 1200 cada uno | ~5 min a 4 Hz |
| `t_stats` | f64 × 1200 | timestamps de lo anterior |
| segmentos de modo | (t0: f64, Mode: u8) × 4096 | duración por `Mode` |
| eventos | (id: u8, t: f64) × 4096 | uno por `GestureEvent` |
| cierres de pinch | (t, ratio_mínimo, desenlace: u8) × 2048 | |
| histograma de pinch | u32 × 64 bins en [0, 1.4] | |

Coste por fotograma: ocho escrituras escalares en arrays preasignados. Microsegundos.

**Además, niveles agregados para el eje largo** (los tres anillos de Cristal): fino
600 muestras a 4 Hz (2,5 min) · medio 600 a 0,5 Hz (20 min) · grueso 720 a 0,1 Hz (2 h). Cada
nivel guarda min / media / max del inferior.

### 6.3 Agregados

Se calculan con numpy **solo cuando la página de análisis está visible** y **a 4 Hz**, nunca
por fotograma:

- percentiles p50 / p95 / p99 de `lat` y de `frame_dt`,
- histograma de latencia, 48 bins en [0, 300] ms,
- reparto de tiempo por `Mode`,
- tasa de eventos por tipo y por minuto,
- **temblor del puntero** = media de `|p[t] − 2·p[t−1] + p[t−2]|` en píxeles sobre las
  últimas 300 muestras en modo `POINTING` (es el residuo de alta frecuencia: la definición
  honesta de temblor),
- **valle del histograma de pinch**: suavizado de 5 bins, mínimo global entre los dos máximos.

### 6.4 Honestidad de los datos (obligatorio en la interfaz)

- `latency_ms` es **latencia de captura** (`fs.capture_latency_ms`), no latencia total de
  extremo a extremo. Se etiqueta **"retardo de captura"**.
- El FPS autoritativo es siempre `pipeline_fps`. `camera_fps` con AirLink es el mismo valor
  (ver `Controller._emit_stats`), y eso se dice en la nota al pie de la tarjeta.
- `frame_dt` se mide **al llegar a la interfaz** e incluye la cola de Qt.
- Cada tarjeta derivada lleva una línea de 11 px en `text.tertiary` diciendo cómo se calcula.

### 6.5 Desconexión

Cuando el panel está oculto, minimizado o en modo compacto, `Telemetry` **desconecta**
`frame_ready` y baja la suscripción a `output_ready` a un contador ligero. `stats_ready` se
mantiene siempre (es barato y alimenta el modo compacto).

---

## 7. `charts.py` — los gráficos

Todo con `QPainter`. No hay QtCharts ni QtWebEngine y no se añaden dependencias.

**Reglas transversales, no negociables:**

- Todo widget de gráfico lleva `WA_OpaquePaintEvent` y **solo llama a `update()` cuando
  llegan datos nuevos**. Ningún gráfico tiene temporizador propio: se registran en el `Beat`
  con su compuerta de frecuencia.
- Toda traza temporal usa **blit desplazado**: se mantiene un `QPixmap` del tamaño del pozo;
  en cada muestra `pixmap.scroll(-step, 0, rect)` y solo se pinta la columna nueva de `step`
  px más el halo del último punto; `update()` con el rectángulo de esa columna + 12 px, no
  con el widget entero. A 60 Hz con `step = 2` son 2×110 px repintados en vez de 420×110.
- Los `QPainterPath` de área se cachean en un `QPixmap` y **solo se regeneran cuando entra
  una muestra**, nunca a 60 Hz.
- Al pasar el ratón: **línea de escrutinio** de 1 px en acento que persigue el cursor con
  τ = 0.05 y un chip flotante E4 con el valor; se repinta **solo esa columna** con
  `update(QRect)`.
- Al cambiar el tema o el tamaño se regenera el pixmap entero una vez.

Clases: `Trace` (traza scroll), `AreaChart` (áreas superpuestas + línea sobre eje derecho),
`Histogram` (barras con tope redondeado, marcas de percentil), `Donut` (arcos), `Scatter`
(puntos), `Heartbeat` (tira de ticks), `Strip` (barra apilada horizontal), `Sparkline`
(28×60 px, sin ejes).

---

## 8. Panel (dashboard)

Se abandona el raíl lateral de navegación actual (`airtouch/ui/dashboard.py:114`, NavRail de
232 px). Ventana **1240×820**, mínimo **1060×700**, margen 28, fondo E0.

### 8.1 Zona A — COLUMNA VIVA, 320 px fijos a la izquierda

Es la traducción honesta de la "columna de perfil" de Project Flight: **no es navegación, es
estado**. No se mueve al cambiar de página.

- **A1 Identidad (56 px):** la marca dibujada a mano — dos círculos solapados de vidrio con
  un arco especular, 32 px — + "AirTouch" en `h2` + chip de versión en `overline`.
- **A2 NÚCLEO (E3, 168 px):** el control principal. Botón redondo de encendido de **72 px**
  con anillo de progreso alrededor que se rellena mientras el motor arranca; a su derecha el
  estado en `h2` ("Detenido" / "Buscando manos" / "Control activo" / "En pausa") y debajo el
  interruptor de control real con su texto de una línea. Mientras el motor corre, el anillo
  **respira** (α 0.24↔0.40 en 3.2 s, refrescado a **20 Hz**).
  **El botón redondo ES `btn_engine`** y **el interruptor ES `control_toggle`**.
- **A3 SESIÓN (E2):** cuatro filas compactas de 40 px con lo que solo se sabe acumulando —
  tiempo activo · gestos realizados · clics emitidos · distancia recorrida por el puntero (en
  metros equivalentes de pantalla). Todo derivado de `output_ready`.
- **A4 ATAJOS (E2 sin fondo, filas fantasma):** Teclado virtual · Calibrar esquinas ·
  Configuración guiada. Estas dos últimas invocan `open_calibration` y `open_wizard`, que
  siguen siendo **atributos asignables desde `app.py`**.

### 8.2 Zona B — MOSAICO

El resto del ancho. Rejilla de **6 columnas**, canalón 16. **Jerarquía por tamaño.**

**Fila 1, alto 300 px:**

- **RENDIMIENTO** (columnas 1–4). Fondo **a sangre** = el gráfico grande de FPS y retardo, al
  45 % de opacidad, sin ejes. Icono de línea fina de 1.5 px arriba-izquierda. Título
  "RENDIMIENTO" en rol `mosaico` alineado a la derecha, abajo. Encima del título, tres cifras
  en `metric`: FPS del motor, retardo de captura p95, ms de detección.
- **LA MANO** (columnas 5–6). Lienzo a sangre: `canvas.sunken` con rejilla de 32 px en
  `edge.hair`, sobre la que se dibuja **el esqueleto en vivo** desde `frame_ready`
  (21 landmarks y los 21 huesos de `HAND_CONNECTIONS`, que ya existen en
  `airtouch/core/frame_state.py`): huesos 2 px en `text.secondary`, articulaciones 3 px,
  yemas 4.5 px, y el segmento pulgar–índice **teñido del color de modo** con grosor
  `2 + 3·(1 − pinch_ratio)`. **No se pinta la imagen de la cámara**: solo el esqueleto — es
  más barato (~1,5 ms), más bonito y más instrumento. Bajo el título, una línea:
  "apuntando · 2 manos · señal buena". Sin mano: el esqueleto se desvanece al 12 % y queda
  una pose fantasma inmóvil con el texto "SIN MANO".
  La tarjeta pone `ctl.preview_enabled = True` en `showEvent` y `False` en `hideEvent`, y
  sube `ctl._preview_every` a 3 mientras está en el mosaico (a 2 solo en la página de Cámara).

**Fila 2, alto 190 px, tres tarjetas de 2 columnas:**

- **GESTOS** — fondo = el histograma de pinch en vivo; contadores de clic / scroll / zoom.
- **SEGURIDAD** — cuatro indicadores de guarda (cara, ratón físico, palma abierta, Esc) como
  puntos con su etiqueta; el fondo se tiñe de `danger` cuando hay pausa, y el detalle muestra
  el motivo real de `SafetyGuard.status_text()` / `state.reason` ("no se detecta al usuario",
  "palma abierta", "Esc", "ratón físico").
- **ENLACE** — AirLink: móvil conectado, resolución, atajo al QR.

**Franja NOVEDADES (96 px, solo si hay algo que decir):** mini-tarjetas fechadas en fila
horizontal — actualización disponible, últimos avisos del registro, sugerencias derivadas de
los datos ("tu cámara está a 720p: los dedos se detectan con ruido", disparada por
`stats["low_res"]`).

**Toda tarjeta con fondo a sangre lleva el velo obligatorio de §4.3.** Sin él, el look se
vuelve ilegible en cuanto el gráfico sube. Opacidad del fondo topada al 45 % y **no ajustable**.

### 8.3 Zona C — BARRA FLOTANTE INFERIOR (E4)

Píldora centrada, alto **56**, radio 28, a **22 px** del borde inferior, ancho ajustado al
contenido. Cinco destinos: **Mosaico ◎ · Cámara ▣ · Gestos ⌁ · Ajustes ◫ · Registro ≡**.
El activo lleva una píldora rellena de acento (**del color de modo cuando el control real
está activo**: la barra te dice de un vistazo si estás en directo) que viaja con `Spring`.
A la derecha, separado por un filo de 1 px, un chip de estado siempre visible: punto + texto
("control activo" / "modo seguro" / "en pausa" / "ahorro"). **Ese chip es `status_badge` y
sobrevive a cualquier página.**

### 8.4 Navegación

Pulsar una tarjeta grande la expande hasta ocupar el área del mosaico (patrón 8) y esa
tarjeta se convierte en la cabecera de la página profunda. **Esc** o la barra inferior
vuelven. La jerarquía por tamaño se convierte así en jerarquía por zoom, que es puro lenguaje
de elevación.

### 8.5 Página profunda: ANÁLISIS (desde RENDIMIENTO)

Margen 32. Cabecera con `SegmentedControl` de rango — **2 min · 20 min · 2 h** (elige el
nivel del anillo de §6.2) — y el reloj de sesión.

**Fichas de cabecera (cuatro, E2):** FPS del motor · Retardo de captura p95 · Detección (ms) ·
Manos vistas (%). Cada una con `metric` 34/300, unidad en `caption`, flecha de tendencia de
3 px y microsparkline de 28 px.

1. **LÍNEA DE TIEMPO** (4 columnas × 260 px). Áreas superpuestas de `pipeline_fps` (accent) y
   `camera_fps` (info) sobre eje izquierdo 0–max(72, pico); retardo como línea fina de 1.5 px
   sobre eje derecho (warn). `QPainterPath` cúbico, relleno en `QLinearGradient` del color de
   la serie de α 90 a 0 (α 36 en claro). Cuatro rejillas horizontales en `edge.hair`,
   **ninguna vertical**. La diferencia entre las dos áreas se sombrea: "fotogramas que el
   motor no llegó a procesar".
2. **HISTOGRAMA DE LATENCIA CON PERCENTILES** (2 col × 190). 48 bins en [0, 300] ms, barras
   con tope redondeado, altura suavizada con `Smooth(τ=0.35)`. Marcas verticales en p50, p95
   y p99 con etiqueta. Debajo, **una frase con veredicto**: "p95 = 118 ms · por debajo de
   130 ms el puntero se siente pegado al dedo". El p95 es la cifra que importa y hoy no se
   muestra en ningún sitio.
3. **PRESUPUESTO DE RETARDO** (2 col × 190). Área apilada en el tiempo: captura
   (`latency_ms`, info) · visión (`process_ms`, accent) · resto (periodo − process, `edge.hair`),
   con la media y el porcentaje de cada tramo a la derecha y una regla de objetivo a 100 ms.
4. **RELOJ DE MODOS** (2 col × 190). Dona del tiempo de permanencia por `Mode`: arcos de
   14 px de grosor, radio 62, huecos de 3 px, **coloreados con la rampa de modo compartida con
   el overlay**. En el centro, el modo dominante y su porcentaje. Los segmentos crecen con
   `Smooth(τ=0.25)`. A la derecha, la lista ordenada con tiempo y porcentaje.
5. **CURVA DE PINCH** (2 col × 190) — **el gráfico que justifica toda la página**. Histograma
   de `pinch_ratio` (64 bins) con los dos umbrales dibujados y la banda de histéresis
   sombreada al 8 %. Se calcula el valle más profundo entre los dos picos y se imprime
   *"sugerido: 0,31 / 0,38"* con un botón **«Aplicar»** que escribe `cfg.gestures.pinch_on` y
   `pinch_off` y llama a `ctl.retune()`. Convierte el ajuste de umbrales de adivinar a leer.
6. **CIERRES** (2 col × 190). Eje horizontal = `pinch_ratio` mínimo alcanzado en cada cierre;
   cada cierre de la sesión es un punto de 4 px coloreado por su desenlace (clic = `ok`,
   arrastre = tinte DRAGGING, scroll = tinte SCROLLING, abortado = `text.quiet`); las dos
   reglas verticales de umbral. Frase calculada: si la mediana de los abortados cae entre
   `pinch_on` y `pinch_on + 0.04`, escribe *"Tu pinch se queda en 0,36 de media y el umbral
   está en 0,34: sube el cierre a 0,37"* con su botón «Aplicar».
7. **ESTABILIDAD DEL PUNTERO** (2 col × 190). Temblor según §6.3, cifra en `metric` con "px",
   traza temporal, veredicto en una palabra, y una **huella** de 120×120 px con las últimas
   600 posiciones superpuestas.
8. **ESTABILIDAD DEL BUCLE** (ancho completo × 120). Traza de latido: un tick vertical de 2 px
   por fotograma, coloreado por tramo (≤20 ms `ok`, ≤33 ms `warn`, >33 ms `danger`), 900 ticks,
   pintado en un pixmap que se desplaza a sí mismo 1 px a la izquierda por muestra. Debajo:
   *"97,4 % de los fotogramas por debajo de 20 ms · 14 saltos en 2 min"*.
9. **SALUD DE LA SESIÓN** (ancho completo × 132). Tira de fichas: tiempo con manos · con cara ·
   en pausa (nº y total) · desconexiones de cámara · resolución más baja vista · reparto entre
   modo seguro y control real.

**Botón «Informe»:** copia al portapapeles un resumen en texto plano (versión, cámara,
resolución, p50/p95/p99, FPS medios, saltos, umbrales, temblor) para pegar en un informe de
fallo. Sin dependencias.

**Orden de sacrificio si hay que recortar alcance:** primero la tarjeta 7, luego la 6, luego
la 9. **Nunca** el `Beat` ni el blit desplazado, porque sin ellos la dirección no rinde.

### 8.6 Otras páginas

- **CÁMARA.** Vista previa grande (`live_preview.py` rehecho), cuatro medidores radiales de
  56 px en vivo (LUZ = luminancia media del fotograma reducido, objetivo 60–180 · DISTANCIA =
  ancho de la palma / ancho del fotograma, objetivo 0.14–0.32 · CENTRADO = distancia de la
  palma al centro de la región de mapeo · NITIDEZ = `HandState.score` combinado con
  `low_res`), selector de fuente, espejo, región activa, y el bloque AirLink con QR.
  **Sin señal:** el rectángulo se rellena de `glass.sunken` y dentro, alineado al margen
  izquierdo, "SIN SEÑAL" en `overline` y un párrafo con qué hacer. Un estado vacío maquetado
  como una página, no como un error.
- **GESTOS.** Arriba, la **regla de pinch** horizontal a todo el ancho: línea de 1 px con
  marcas cada 10 %, la posición actual como triángulo relleno de 8 px (τ = 0.045) y las dos
  marcas de umbral etiquetadas. Debajo, catálogo de doce tarjetas (apuntar, clic, doble,
  catapulta/derecho, scroll, scroll horizontal, arrastrar, zoom, mover ventana, redimensionar,
  teclado, pausa con palma). Cada tarjeta tiene una ilustración de mano de línea fina
  (`handart.py` reestilizado) que **solo se anima bajo el cursor**; las demás quedan en su
  pose de reposo, coste cero. Al ejecutar el gesto de verdad: borde al color de modo, destello
  de 240 ms `EASE_GLASS`, contador que sube con `Spring`. Bajo cada tarjeta, el parámetro que
  la gobierna con un mini-deslizador que escribe en `cfg` y llama a `ctl.retune()`.
  Debajo, **rejilla de eventos**: 9 filas × 60 columnas de celdas de 6×6 px con 2 px de canal,
  un cubo de 10 s por celda, opacidad por conteo. 540 rectángulos a 4 Hz: gratis.
- **REGISTRO.** `Cascadia Mono` 12 px, interlínea 1.55, pozo E1, radio 18. Marca de hora en
  `text.quiet`, texto en `text.secondary`, líneas con "Error" en `danger` y con "Control
  activo" en `accent`. Tres pestañas de texto en `overline`: TODO · MOTOR · ERRORES. Al pie,
  «Copiar» y «Guardar en un archivo». **`_append_log(str)` escribe aquí.**

### 8.7 Ajustes

Se abandona la columna única de tarjetas de `airtouch/ui/settings/panel.py`. **Dos paneles:**
lista de secciones de 200 px a la izquierda y contenido a la derecha.

Secciones: **Aspecto · Cámara · Puntero · Gestos · Teclado · Seguridad · AirLink · Avanzado**.

- **Campo de búsqueda arriba** que filtra las filas en vivo: cada `SettingRow` declara
  `keywords: str`; las que no casan se ocultan con un fundido de 120 ms y los grupos vacíos se
  colapsan.
- Cada fila que difiere del valor por defecto muestra un **punto de acento de 4 px** en su
  borde izquierdo; la sección enseña "3 modificados" junto a un botón fantasma
  **«Restablecer sección»** (usa `Config.reset_section`).
- **Cada grupo ancla arriba su instrumento** (injerto de Pulso, y es la clave de "mejores
  ajustes"): el grupo *Gestos* fija un osciloscopio de pinch de 180 px que permanece visible
  mientras arrastras `pinch_on` y `pinch_off`, con las reglas de umbral moviéndose bajo tu
  dedo en tiempo real; el grupo *Puntero* ancla el medidor de temblor y un readout del retardo
  añadido por el suavizado, para que veas el intercambio suavidad↔latencia mientras mueves el
  deslizador.
- **Cada sección termina con un pie de consecuencia** en `caption` que explica el efecto
  físico, no la opción: *"Bajar el corte suaviza el puntero pero añade unos 20 ms de retardo"*.
- Deslizadores: canal E1 de 1 px de alto visible dentro de un área de 24 px, marca de posición
  como rectángulo de 2×16 px, valor a la derecha en `mono` tabular; al arrastrar aparecen 10
  subdivisiones de 1×6 px con fundido de 120 ms, y el valor flota en `metric` sobre el pulgar
  y se desvanece 400 ms después de soltar.
- **`refresh_from_config()` se mantiene con la misma firma**, y el panel sigue siendo
  accesible como `dashboard.settings`.

### 8.8 Modo compacto

`enter_compact()` (contrato intacto): tira de **300×96** en la esquina inferior derecha, sin
marco, arrastrable, E4. Contiene: lámpara de modo, la palabra del modo en `h2`, un arco de
pinch de 40 px, `pipeline_fps` en `readout`, y dos botones (pausar, volver al panel). **Es el
mismo lenguaje que la cápsula del overlay**, para que compacto y overlay se lean como el mismo
aparato. Frente a los 372×380 de hoy ocupa la mitad y no tapa nada. Al entrar en compacto se
congela el lienzo vivo y se desconecta `frame_ready`.

### 8.9 Contratos con `app.py` (no se pueden romper)

| contrato | dónde vive ahora |
|---|---|
| `.show() .raise_() .activateWindow() .setWindowState()` | `DashboardWindow` |
| `.settings.refresh_from_config()` | `settings/panel.py` |
| `.control_toggle` (checkable, `.setChecked(bool)`) | el `Toggle` del Núcleo (A2) |
| `.btn_engine` (`.setText(str)`) | el botón redondo del Núcleo (A2) |
| `._refresh_control_hint()` | actualiza la línea de escape bajo el Núcleo |
| `._append_log(str)` | página Registro |
| `._toggle_engine()` | colgado de `btn_engine` |
| `.enter_compact()` | §8.8 |
| `.open_calibration`, `.open_wizard` | atributos asignables, invocados desde A4 |
| Tray: señales `show_dashboard`, `toggle_engine`, `toggle_control`, `toggle_keyboard`, `quit_app`; `.refresh(running, control)`, `.show()`, `.hide()`, `.showMessage(...)`; `build_icon(activo)` | `tray.py` |
| `SetupWizard(cfg, ctl, parent)`, señal `completed(bool)`, `.exec()` | `wizard/wizard.py` |
| `CalibrationWindow(cfg)` | `calibration.py` |
| `theme.apply(str) -> Palette`, `.qss() -> str`, `.signals.changed`, `.C`, `.windows_prefers_light()`, `.qcolor(token)`, `.rgba(hex, a)`, `.mix()` | `theme.py` |
| `overlay_style.apply_theme(dark: bool)` | `overlay/style.py` |
| `OverlayCanvas`: `.engine_ref`, `.set_output(EngineOutput)`, `.refresh_geometry()`, `.show_overlay()`, `.hide_overlay()`, `.hwnd()`, `.update()` | `overlay/canvas.py` |

**La línea de escape** (`_refresh_control_hint()`) siempre visible bajo el Núcleo, en
`caption`: *"Para recuperar el control: mantén Esc, mueve el ratón físico, o abre la palma."*

---

## 9. Asistente de configuración (setup)

Diálogo **sin marco, 1040×760, E4, radio 32**, sobre un velo que es el mismo lienzo vivo a
1.6× de brillo con un lavado negro al 0.55 — se lee como desenfoque y cuesta un `drawImage`.

**Siete páginas.** Hoy son ocho: fusionar es en sí mismo el mecanismo de "cuando te das
cuenta, ya terminaste". Duración objetivo **2:00 – 2:40**.

### 9.1 Regla rectora

**Ninguna página termina solo con texto.** Cada página acaba con el usuario habiendo **hecho**
algo con su cuerpo y la interfaz reaccionando visiblemente a ello.

### 9.2 Cromo permanente — los mecanismos que producen la sensación Apple

1. **Hilo de progreso continuo.** 3 px pegado al borde superior del diálogo, en acento con
   glow de 6 px. **Crece de forma continua, no por pasos**: avanza fraccionadamente dentro de
   cada página según se cumplen sus sub-objetivos, en saltos de 300 ms `EASE_GLASS`. Reparto:
   P0 0→5 · P1 5→22 · P2 22→42 · P3 42→58 · P4 58→74 · P5 74→92 · P6 92→100.
   *Ver la barra moverse porque mueves la mano, no porque pulsas «Continuar», es la diferencia
   entre un formulario y un acompañamiento.*
2. **Contador "2 / 7"** en `overline`, arriba a la derecha, discretísimo.
3. **El botón primario no existe hasta que la página es satisfacible.** Se **materializa**
   (opacidad 0→1 + subida de 12 px, 320 ms `EASE_GLASS`, más un `Spring` de escala 0.96→1.00)
   en el instante en que se cumple la condición. La ausencia previa es la señal más fuerte de
   "te estoy guiando"; la aparición es la recompensa. **El botón nunca miente.**
4. **Honestidad con el tiempo.** Abajo a la izquierda, "unos 2 minutos" al empezar; desde la
   página 2, estimación viva "quedan ~40 s" calculada con el tiempo medio real de las páginas
   restantes.
5. **Nunca esperas a solas.** Toda espera (arrancar motor, conectar móvil) se muestra como
   **pasos con nombre** que se van marcando: "Abriendo la cámara" → "Cargando el modelo de
   manos" → "Listo", cada marca dibujándose sola en 260 ms (animación de `setDashOffset` del
   trazo). Una espera con nombre se percibe más corta que una barra indeterminada.
6. **Salir siempre es posible**, como texto casi invisible abajo a la izquierda en `overline`
   `text.quiet`: "Salir del asistente".

### 9.3 Las siete páginas

**P0 · BIENVENIDA** (a sangre, sin cromo de navegación).
Lienzo a plena intensidad con las manchas a la deriva. En el centro flota la **lente de vidrio
de la marca**, oscilando 3° en 9 s, con un barrido especular cada 6 s. `overline` "BIENVENIDO"
· `display` 46 **"Tus manos son el ratón"** · `body` "Apunta con el índice. Junta los dedos
para hacer clic." · botón «Empezar» con halo respirando.
Entrada: la lente escala 0.86→1 en 700 ms `EASE_GLASS`, luego el texto escalona a 90 ms.
**Dopamina:** la lente responde al ratón — paralaje 0.06× y el reflejo especular sigue al
cursor. *Antes de pulsar nada, la aplicación ya te ha contestado.*

**P1 · TU CÁMARA.**
Dos tarjetas grandes en el lenguaje del mosaico (AirLink / webcam del sistema), ilustración a
sangre, título en `mosaico` a la derecha. **Al elegir una, esa tarjeta se expande a todo el
ancho en 240 ms `EASE_SOFT` mientras la otra sale por su lado, y el flujo continúa dentro de
la tarjeta**: AirLink despliega el QR sobre una placa E3 con la URL en `mono` debajo; webcam
despliega la lista de dispositivos. **No hay cambio de página.**
A la derecha, una silueta de dispositivo vacía y gris. En el instante en que `stats.connected`
pasa a `True`: la silueta se rellena con el **vídeo real**, el filo de la lámina destella a
0.30, se dibuja sola una marca de verificación en 260 ms, sale un estallido de 46 partículas
y se materializa el botón «Perfecto, seguir». La cabecera pasa a "Móvil conectado · 1920×1080
· 60 fps".
Si pasan 20 s, aparece en voz baja una segunda vía: «¿No aparece? Usa la webcam del sistema».
El hilo avanza al 40 % de su tramo al pintar el QR y al 100 % al conectar.

**P2 · EL ENCUADRE.**
Vista previa a sangre dentro del vidrio, con la región activa dibujada. Alrededor, **cuatro
medidores radiales de 56 px**, cada uno una medida real (las mismas de §8.6): LUZ · DISTANCIA ·
CENTRADO · NITIDEZ. Cada medidor se llena y vira a `ok` al entrar en rango, con un muelle de
260 ms y la marca dibujándose por trazo.
**Cuando los cuatro llevan 1,2 s seguidos en verde, la página AVANZA SOLA** tras un compás de
900 ms con la palabra «Listo» y un anillo que se cierra sobre el botón para que no sea un
susto. **Es el único auto-avance de todo el asistente, y por eso resulta mágico en vez de
alarmante**: el usuario no pulsa nada aquí.

**P3 · EL GESTO.**
Izquierda: la ilustración animada de la mano (`handart.py`, `GestureArt` reestilizado) en
bucle de 1,6 s. Derecha: una **columna de pinch vertical de 280 px** con tu `pinch_ratio` en
vivo (τ = 0.045) y las dos reglas de umbral; es el mismo vocabulario que verás luego en el
panel, y aprenderlo aquí lo hace tuyo.
Tarea: **«Junta los dedos tres veces»**. Tres fichas de vidrio se rellenan una a una, cada una
con un pop de `Spring` y un anillo que se expande en 380 ms. La tercera dispara el barrido
especular en toda la página y materializa el botón.
**En silencio, la página guarda el `pinch_ratio` mínimo de cada uno de los tres cierres.**

**P4 · TU PINCH.**
Se enseña lo que la página anterior guardó sin decirlo: eje horizontal con **tus tres puntos**
y un umbral propuesto que **se desliza a su sitio** en 700 ms `EASE_SOFT`. Simultáneamente, un
**histograma que se construye delante de ti**: al abrir y cerrar la mano las barras aparecen
en tiempo real en acento; a los ~6 s las dos jorobas están visiblemente separadas y la
aplicación dibuja la línea de umbral en el valle con un barrido de 500 ms.
Texto: *"Tu pinch cierra a 0,31. He ajustado el umbral a tu mano."* Un botón: «Perfecto». Un
enlace discreto: «prefiero ajustarlo yo» que revela los dos deslizadores.
Después, tres segundos de prueba en vivo: la aguja se pone verde al pinchar; **dos pinches
correctos** y la página queda satisfecha.
*Este es el pico de la sensación Apple de todo el asistente: el sistema trabajó por ti
mientras no mirabas, y además ves a la máquina aprender **tu** mano.*
Si la medición sale mal (recorrido < 0,22), no hay error rojo: el titular cambia a "Vamos otra
vez", una frase explica por qué, y el botón dice «Repetir».

**P5 · TUS ESQUINAS Y TU PUNTERÍA.**
El diálogo baja su propio cuerpo al **12 %** de opacidad y el overlay toma la pantalla entera.
El usuario apunta a las cuatro esquinas; cada objetivo **respira** (escala 1.00↔1.06, 2,2 s) y
un anillo se llena en 900 ms de permanencia. Al capturar: el anillo se cierra de golpe, el
objetivo colapsa a un punto y **el siguiente objetivo viaja** hasta su esquina por una
trayectoria curva en 420 ms — viaja, no se teletransporta, para que la vista lo siga. El
rectángulo de la región se va dibujando lado a lado y pulsa una vez al cerrarse.
**Inmediatamente después, en la misma pantalla completa, aparecen tres dianas** que hay que
apuntar y pinchar. Cada acierto: implosión de 240 ms + 12 partículas de 3 px del color de modo
+ contador. Al tercero, el diálogo vuelve a subir con la región mapeada dibujada sobre la
vista previa.
*La aplicación se aparta y toda la pantalla se convierte en la interfaz. Este es el compás de
"magia".* Se puede saltar en un clic («Usar el área por defecto»), pero casi nadie lo hará.

**P6 · LISTO.**
La marca de éxito se dibuja (`SuccessMark`), un anillo de luz se expande, 46 partículas de
confeti tintadas de acento.
Y el pago de verdad: **un recibo de configuración con puntos conductores y tus números**:

```
CÁMARA ................ iPhone · 1920×1080 · 60 fps
TU PINCH .............. 0,31 / 0,38
REGIÓN ACTIVA ......... 68 % del encuadre · 4 esquinas calibradas
RETARDO MEDIO ......... 74 ms
GESTOS PROBADOS ....... 3 de 3
```

Cada línea con 90 ms de retardo y cada número **contando desde 0** hasta su valor en 500 ms.
*No te dicen "enhorabuena": te devuelven una hoja de especificaciones que es tuya y que no
existía hace dos minutos.*
Debajo, **un solo interruptor**: «Activar control real ahora» (**apagado por defecto**,
coherente con `SafetyConfig.control_enabled = False`), y el botón «Entrar en AirTouch».
Al pulsarlo **el diálogo no se cierra: se expande hasta el panel** — su lámina anima su
geometría hasta coincidir con el área del mosaico mientras el resto del panel escalona detrás,
620 ms. **Continuidad de material: la última cosa que ven es que el asistente y el panel son
el mismo objeto.**
Se conserva la señal `completed(bool)` y que el `commit()` de la configuración solo se ejecute
al terminar de verdad.

---

## 10. Overlay

**Principio:** el overlay flota sobre contenido arbitrario, así que **no puede apoyarse en un
fondo que controle**. Su vidrio es **autoiluminado**: placa oscura con un realce interior
fuerte arriba-izquierda y un glow exterior amplio y blando de su propio color de estado, de
modo que se lee como un objeto encendido esté lo que esté detrás. **Aquí no se usa el truco
del lienzo pre-desenfocado: no funciona fuera de la ventana de la aplicación.**

### 10.1 Reglas transversales de repintado (la restricción dura del proyecto)

1. **Queda prohibido cualquier elemento del overlay cuya región de daño dependa del ancho de
   la pantalla o del ancho de una ventana.** Cada indicador declara su tamaño como constante
   en `overlay/style.py` (`CAPSULE_DAMAGE = (200, 92)`, `CHROME_DAMAGE_BAR = (300, 44)`, …) y
   `_current_region()` se construye con esas constantes devolviendo **rectángulos sueltos,
   nunca su envolvente**.
2. **`_static_since` por elemento del HUD:** si un elemento no ha cambiado nada en 2
   fotogramas, **se saca de la región sucia**. Hoy `_current_region()` (`canvas.py:265`) mete
   las pastillas siempre que `_hud_a > 0.01`, y por eso se repintan eternamente aunque no
   cambien. Esto por sí solo ya baja el reposo actual.
3. **La cápsula publica su rect exacto** en `_hud_rects` con un margen igual al radio del glow
   (+48 px), en lugar del heurístico actual de ±70/±12 (`canvas.py:266`).
4. **Lo que solo respira se actualiza a 20 Hz** mediante una compuerta temporal en `_tick`; a
   60 Hz no se distingue y cuesta el triple.
5. **La animación ambiente tiene su propio rectángulo**: la lámpara que respira invalida solo
   su círculo de 24×24 px, no la cápsula entera. Es la diferencia entre 0,6 kpx y 16 kpx por
   fotograma.
6. Filos y trazos finos con `QPen` cosmético de ancho 0 sobre coordenadas enteras + 0.5, para
   que caigan en un píxel exacto y no obliguen a ampliar el rectángulo de daño por el medio
   píxel antialiaseado.
7. **Modo de depuración con contador de píxeles dañados** (tecla F9 con el overlay visible):
   imprime px/fotograma medios y pico de los últimos 5 s. **La verificación es obligatoria
   antes de dar el overlay por terminado.**

### 10.2 Cursor

- Núcleo blanco de **9 px de diámetro** al 0.94.
- Anillo de 1 px a **radio 20** con el tinte del modo al 0.55.
- Glow radial hasta **radio 30** al 0.14 (hoy `CURSOR_GLOW_RADIUS = 34` y α 46: se baja).
- **Medidor de pinch sobre el anillo** (injerto de Pulso, y es información, no decoración):
  arco de 2.5 px que arranca en −90° en sentido horario con
  `clip((pinch_off − ratio) / (pinch_off − pinch_on), 0, 1)`, en el color de modo, con las dos
  marcas de umbral como muescas radiales. Al cruzar el umbral, el arco se completa y el núcleo
  destella a 13 px durante 120 ms.
- Al pinchar el anillo se contrae a 13 px en 90 ms; al soltar vuelve con sobrepaso hasta 23 y
  se asienta en 20 (140 ms, `EASE_LIFT`).
- Con `flick_charge > 0` el arco cambia al tinte flick y se llena en sentido antihorario.
- **Región de daño fija de 68×68 px ≈ 4,6 kpx** (radio máximo 30 + 4 de margen).
- **La cola de cometa de Pulso se descarta**: sube el rectángulo del elemento que más se mueve
  a 170×170 = 29 kpx. Queda como opción apagada por defecto en Ajustes → Avanzado.

### 10.3 La cápsula de estado

Sustituye a las **dos píldoras de texto plano** de hoy ("MODO SEGURO · no se inyecta nada" y
"EN PAUSA", `airtouch/overlay/canvas.py:614`) por **un solo componente**.

**Geometría:** rounded-rect de alto **44**, radio **22**, ancho mínimo **132** (44 cuando está
colapsada: es un círculo), arriba y centrada, **y = 28**. Nunca de lado a lado.
**Anatomía:** `[glifo pintado 22 px] [filo de 1 px] [estado 12,5 px semibold tracking +0.4]
[detalle opcional 11 px sobre HUD_TEXT_DIM]`.

- **MODO SEGURO.** Glifo: escudo de línea fina con barra diagonal, en `warn` `#FFC46B`. Texto
  «MODO SEGURO», detalle «no se inyecta nada». Relleno `rgba(18,14,6,0.72)`, filo
  arriba-izquierda `rgba(255,196,107,0.34)`, glow radial exterior `#FFC46B` al 0.16 radio 46.
  **Relleno con rayado diagonal** a 45°, paso 6 px, línea de 1 px, en `warn` a α 0.14 (0.10 en
  claro), recortado a la forma de la cápsula: *el rayado es la textura universal de "esto es un
  ensayo" y comunica el estado sin leer.*
  **Comportamiento clave:** a los **4 s se colapsa** en un círculo de 44×44 que solo muestra el
  glifo, en 420 ms (`Smooth(τ=0.12)` para el ancho, texto a α 0 en los primeros 140 ms). Se
  reexpande 2,5 s ante cualquier cambio de modo. *El recordatorio constante se vuelve
  ambiental* — y de paso el colapsado repinta ~4 kpx en vez de ~14 kpx.
- **EN PAUSA.** Glifo: dos barras de 3×12 px, en `danger` `#FF7A85`. Texto «EN PAUSA», detalle
  = **el motivo real** que ya produce `SafetyGuard.state.reason` ("no se detecta al usuario" /
  "palma abierta" / "Esc" / "ratón físico"). **No se colapsa nunca**: una pausa es un estado
  que tienes que poder ver. En su lugar **respira**: el glow exterior oscila entre 0.12 y 0.26
  en 1,6 s, senoidal, a **20 Hz**. Si la pausa tiene temporizador (`no_face_timeout_ms`),
  aparece una **hairline de cuenta atrás** de 2 px pegada al borde inferior interior que se
  vacía de derecha a izquierda; si la pausa es manual, queda llena.
  **Y además, un anillo de 2 px en el borde de toda la pantalla** en `danger` al 0.22, dibujado
  como **cuatro rectángulos finos**: 2 × (2560 + 1440) × 2 ≈ 16 kpx, o sea nada, y es imposible
  no verlo. *Es la mejor mejora del overlay: periférico, no invasivo, y dice "el sistema no está
  escuchando tus manos" sin una palabra.*
- **CONTROL ACTIVO: sin cápsula.** Cuando todo va bien no hay nada que decir; **la ausencia de
  insignia es el mensaje**. Queda solo la lámpara (círculo de 34 px con el punto de modo
  dentro) al 55 % de opacidad, y se puede apagar del todo desde Ajustes → Aspecto.
- **Transición entre estados:** crossfade del glifo y tween de color de relleno, filo y glow en
  240 ms; el ancho con `Smooth(τ=0.12)`.

### 10.4 Píldora inferior de modo

Misma anatomía de cápsula, centro en `y = alto − 54`. **Visible solo cuando el modo no es
`POINTING` ni `IDLE`.** Entra deslizando 12 px hacia arriba con τ = 0.12 y opacidad; sale en
180 ms `EASE_EXIT`. Muestra la palabra del modo (`Mode.value`, ya en español) y, si hay
`out.note`, "modo · nota" durante 1,1 s. Si el teclado está abierto, sube por encima de él como
ya hace hoy.

### 10.5 Barras de ventana

Se mantiene la geometría funcional (barra bajo el borde inferior, esquina de redimensionado) y
se reestiliza al vidrio autoiluminado, **pero con la regla de daño constante de Pliego**:

- **Barra de mover:** lámina autoiluminada de **7 px** de alto, **ancho topado a 260 px**
  (`CHROME_BAR_MAX_W`, que ya existe) **centrada** bajo el borde inferior de la ventana, con
  filo claro arriba y glow del tinte `WINDOW` `#FFC46B`. Crece desde el centro con τ = 0.13. Al
  agarrarla, el glow sube de 0.16 a 0.34 en 120 ms y aparecen **dos guiones de arrastre de 1 px**
  en los extremos, a 34 px de la barra.
  **Daño:** tres rectángulos sueltos de tamaño constante — la barra (300×44) y los dos guiones
  (36×36 cada uno) ≈ **15,8 kpx**. Hoy la región es `(ancho + 92) × 110`, que en una ventana de
  1200 px son **132 000 px²**: **reducción de 8×**, y en ventanas anchas mucho más. Esta es la
  optimización más rentable de todo el rediseño y sale gratis del lenguaje visual.
- **Esquina de redimensionado:** arco de 6 px con el mismo tratamiento, dentro de un rectángulo
  de daño constante de **96×96** (hoy 120×120).

### 10.6 Teclado virtual

Panel E4 autoiluminado, radio 26. Cada tecla lleva su filo claro arriba-izquierda de 1 px: *es
lo que hace que un teclado plano parezca un teclado.*
Hover: relleno 0.10→0.25 en 90 ms y la tecla se eleva 2 px. Activa: invierte a relleno blanco
0.89 con glifo oscuro, crossfade de 90 ms, más un anillo de 1 px que se expande 8 px y se
desvanece en 220 ms.
**Solo se repinta la tecla afectada (rect de la tecla + 10 px), nunca el panel entero** — esa
es la optimización que falta hoy. El rectángulo del panel solo se invalida al abrir, cerrar o
cambiar de layout.
Popup de acentos: tira horizontal, misma anatomía de cápsula.

### 10.7 Presupuesto

| situación | hoy | objetivo |
|---|---|---|
| reposo apuntando (cursor + cápsula colapsada) | ~0,10 Mpx | **≤ 0,010 Mpx** |
| pausa (cursor + cápsula + anillo de pantalla) | — | ≤ 0,026 Mpx |
| arrastrando ventana | ~0,14 Mpx | ≤ 0,022 Mpx |
| teclado abierto | ~0,55 Mpx | ≤ 0,30 Mpx (solo teclas tocadas) |

*La dirección más "cara" visualmente acaba siendo la más barata en el overlay, y eso hay que
verificarlo con el contador de F9, no suponerlo.*

### 10.8 Bandeja

`build_icon(activo)` se redibuja en el mismo lenguaje: círculo de 16 px con el punto de modo
dentro; gris cuando el motor está parado, del color de modo cuando corre, **con el rayado
diagonal cuando está en modo seguro**. Se regenera solo al cambiar de estado, nunca
periódicamente.

---

## 11. Modo claro: reglas de supervivencia

Es donde mueren estos sistemas. Blanco sobre blanco sin líneas apenas tiene contraste.

1. Escalón de luminancia del **4 %** entre lienzo y vidrio. Ni más (se ve la caja) ni menos
   (desaparece).
2. El filo dominante es `edge.dark` abajo-derecha. **Si un panel desaparece a brillo 100 %, se
   sube `edge.dark` a 0.14. Nunca se añade una línea divisoria: eso rompería el principio.**
3. Sombras al 60 % de desenfoque y desplazamiento, y azuladas (`rgba(31,41,71,·)`), nunca
   negras.
4. **Nada de pozos oscuros dentro de tarjetas claras.** Los gráficos en claro usan `sunken`
   claro `#E7EAF1`, no negro.
5. Rellenos de área de gráfico: α **0.36** en claro frente a **0.90** en oscuro; rejilla más
   presente (`edge.hair` claro `rgba(15,23,42,0.06)`).
6. Rampa de modo oscurecida (tabla §3.1) para pasar AA sobre blanco.
7. Sin viñeta en el lienzo claro.
8. **Pasada de contraste obligatoria a brillo 100 % en un portátil barato**, en la página de
   análisis (que es donde más se nota) y en el mosaico con fondos a sangre.

---

## 12. Lo que NO se hace (descartes explícitos)

Se listan aquí para que nadie los reintroduzca "solo para ver".

1. **Desenfoque de fondo real (backdrop blur).** Qt no lo tiene. Se simula con el recorte del
   lienzo pre-desenfocado, que funciona **solo** dentro de la ventana de la aplicación.
   Cualquier superficie que salga de la ventana (menús desbordados y todo el overlay) usa
   **vidrio autoiluminado**, no translucidez. No se intenta capturar la pantalla por debajo:
   es caro, parpadea y en un overlay click-through se realimenta.
2. **Mica como requisito.** Se intenta con ctypes, degrada en silencio en Windows 10, y está
   **apagada por defecto**. La dirección no depende de ella.
3. **`QGraphicsDropShadowEffect`.** Prohibido en todo el proyecto, incluidas las "dos
   excepciones" que proponía Pliego. Atlas 9-slice y punto.
4. **Saturación +12 % del recorte de fondo para E4** (propuesta de Cristal). Es una pasada por
   píxel sobre un `QImage` en cada repintado. Se sustituye por un lavado más claro fijo.
5. **Cola de cometa del cursor** (Pulso). Multiplica por 6 el rectángulo del elemento que más se
   mueve. Opción apagada por defecto.
6. **`letter-spacing` / `line-height` en QSS.** Qt los ignora. Hoy `theme.py` los escribe y no
   hacen nada. Todo por `QFont` y `QTextLayout`.
7. **Animación de tracking en directo sobre `QLabel`** (la firma de Pliego). Cada paso llama a
   `setFont()` y fuerza un relayout por fotograma; con dos simultáneas se nota en un PC débil.
   Se conserva **solo** para el titular `display` de P0 del asistente, protegida por una bandera
   de módulo que garantiza **una sola animación de tracking activa en toda la aplicación**.
8. **Sitka** para los titulares. A 46 px con el antialiasing de Windows la serif se ve frágil y
   anticuada. Registrado como decisión de no hacer.
9. **Dona de reparto de modos en la página de Gestos.** Solo hay una, en la página de análisis.
   Duplicar gráficos es duplicar coste.
10. **Radio 0 y ausencia total de cajas** (Pliego). Contradice la inspiración 2.
11. **Confeti de 90 partículas.** Bajado a 46, tintado, y pintado sobre un hijo transparente que
    solo invalida el bbox de las partículas vivas.
12. **`QEasingCurve.setCustomType` con lambda de Python** para el muelle. Se sustituye por la
    clase `Spring` conducida por el `Beat`: mismo resultado, sin callback de Python por paso, y
    sirve para valores que persiguen un objetivo cambiante.

---

## 13. Riesgos vivos y cómo se vigilan

| riesgo | mitigación | cómo se comprueba |
|---|---|---|
| La capa `glass.py` no se hace primero y la dirección degenera en "tarjetas planas" | Orden de implementación obligatorio del §2 | Hito de la pantalla de prueba antes de tocar el panel |
| Modo claro sin contraste | §11 | Pasada a brillo 100 % en portátil barato |
| El zoom tarjeta→página tartamudea | Plan B ya decidido: crossfade con escala 1.02 | Prototipo antes de construir las páginas profundas |
| Fondo vivo se come la CPU del motor | Búfer topado a 320×180, 10 Hz, tres compuertas de congelación | Contador de fps del panel con el motor corriendo |
| Overlay se dispara de coste | §10.1, constantes de daño, `_static_since` | Contador F9, obligatorio antes de cerrar |
| Falta `Segoe UI Variable` (Windows 10) | Comprobación única al arrancar, `display` a 40 px y tracking a −1.1 | Probar en una máquina sin la fuente, no asumirlo |
| Gráficos vacíos al arrancar | Estado inicial explícito: "acumulando: 42 s de 90" en `caption`, nunca un hueco | Primer minuto de sesión limpia |
| Cadencia variable de `stats_ready` | Timestamp por muestra, ningún eje asume intervalo fijo | Probar a 30 fps forzados |
| "Vidrio" como cliché | El material se usa para algo (§1.2): los gráficos son el fondo, el filo es el canal de estado, la profundidad es la navegación | Revisión de dirección al terminar el mosaico |

---

## 14. Plan de archivos

| # | archivo | escribe | depende de |
|---|---|---|---|
| 1 | `ui/tokens.py` | paletas oscura/clara, rampa de modo, escala tipográfica, radios, espaciado | — |
| 2 | `ui/theme.py` | API pública intacta (`apply`, `qss`, `signals`, `C`, `qcolor`, `rgba`, `mix`, `windows_prefers_light`), QSS mínimo (solo familia y colores base) | 1 |
| 3 | `ui/tipo.py` | fábrica de `QFont` con tracking y `tnum`, cadena de respaldo, dos escalas, `Parrafo` | 1 |
| 4 | `ui/glass.py` | `CanvasSource`, `ShadowAtlas`, `paint_sheet`, filos, velo, Mica opcional | 1, 2 |
| 5 | `ui/motion.py` | `Beat`, curvas, `Spring`, reexport de `Smooth`, `Stagger`, `SpecularSweep`, ahorro | — |
| 6 | `ui/widgets/*` | `Sheet`, `Inset`, `Toggle`, `Button`, `Slider`, `Segmented`, `SettingRow`, `Chip`, `Metric`, `Sparkline`, `Dot`, `Ring` | 2, 3, 4, 5 |
| 7 | `ui/telemetry.py` | anillos numpy, agregados a 4 Hz, sugerencias de umbral | — (solo `core` y `gestures`) |
| 8 | `ui/charts.py` | `Trace`, `AreaChart`, `Histogram`, `Donut`, `Scatter`, `Heartbeat`, `Strip` | 2, 3, 5, 7 |
| 9 | `ui/dashboard/shell.py` | ventana, zonas A/B/C, navegación, **todos los contratos de `app.py`** | 4, 5, 6, 7 |
| 10 | `ui/dashboard/live.py` | columna viva: identidad, Núcleo (`btn_engine`, `control_toggle`), sesión, atajos | 6, 9 |
| 11 | `ui/dashboard/mosaic.py` + `cards.py` | rejilla, zoom tarjeta→página, las seis tarjetas | 6, 8, 9 |
| 12 | `ui/dashboard/page_stats.py` | las nueve tarjetas de análisis | 7, 8, 11 |
| 13 | `ui/dashboard/page_camera.py`, `page_gestures.py`, `page_log.py` | | 6, 8, 9 |
| 14 | `ui/settings/sections.py` + `panel.py` | definición declarativa, búsqueda, instrumentos anclados, `refresh_from_config()` | 6, 8 |
| 15 | `ui/wizard/wizard.py` + `pages.py` | armazón (hilo, contador, botón que se materializa, estimación viva) y las siete páginas | 6, 8, 14 |
| 16 | `overlay/style.py` | tokens del overlay, **constantes de daño**, `apply_theme(dark)` | 1 |
| 17 | `overlay/canvas.py` | cursor, cápsula, píldora de modo, barras, teclado, `_current_region`, `_static_since`, contador F9 | 16 |
| 18 | `ui/compact.py`, `tray.py`, `calibration.py`, `celebrate.py`, `handart.py`, `live_preview.py`, `airlink_panel.py` | | 6, 16 |

`airtouch/ui/anim.py` se absorbe en `motion.py`; la clase `Smooth` se conserva **tal cual** y se
reexporta para no romper importaciones existentes durante la migración.

---

*Documento cerrado. Si algo aquí resulta impracticable durante la implementación, la respuesta
correcta es anotarlo en este archivo con el plan B, no improvisar una solución que rompa uno de
los cinco principios del §1.*
