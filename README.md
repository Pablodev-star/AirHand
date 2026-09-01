# AirHand

Control gestual del escritorio de Windows con las manos, usando el móvil como
cámara. El dedo índice es el puntero y el *pinch* (juntar pulgar e índice) es el
clic. Inspirado en la interacción del Apple Vision Pro.

**→ [Instalación guiada paso a paso](https://pablodev-star.github.io/AirHand/)**

---

## Las tres piezas

| Pieza | Qué hace |
|---|---|
| **AirTouch** (`airtouch/`) | La aplicación de Windows: visión, gestos e inyección de eventos |
| **AirLink** ([repo aparte](https://github.com/Pablodev-star/AirLink)) | La página que convierte el móvil en cámara de alta resolución |
| **El sitio** (`airhand-web/`) | La guía de instalación publicada en GitHub Pages |

## Gestos

| Gesto | Acción |
|---|---|
| Índice extendido | Mueve el puntero |
| Pinch corto | Clic izquierdo |
| Dos pinch seguidos | Doble clic |
| Pinch + mover arriba/abajo | Scroll |
| Pinch con las dos manos, separarlas | Zoom |
| Catapulta con el índice | Clic derecho |
| Pinch en la barra bajo una ventana | Mover la ventana |
| Pinch en la esquina inferior derecha | Redimensionar |
| Pinch sobre el teclado virtual | Escribir |
| Catapulta sobre una tecla | Variantes (á, à, ä…) |

**La catapulta** es el gesto de tirar chapas: curva el índice apoyándolo contra
el pulgar y suéltalo de golpe. Se distingue de un pinch normal por la
*curvatura* del dedo, no solo por el contacto.

### Salidas de emergencia

1. **Modo seguro** — activo por defecto: se dibuja todo pero no se inyecta nada
2. **Esc mantenido** ~1 s — pausa o reanuda
3. **Mover el ratón físico** — AirTouch cede el control al instante
4. **Palma abierta** un momento — pausa
5. **Sin cara delante** 3 s — pausa automática

## La cámara

El PC levanta un servidor HTTPS con certificado propio, muestra un QR, y el
móvil envía su cámara por **WebRTC directo por la red local**. Nada pasa por
internet.

Hay una restricción que condiciona todo el diseño: `getUserMedia` exige un
contexto seguro, y a la vez una página HTTPS **no puede** abrir `ws://` contra
una IP local (contenido mixto). Por eso el PC sirve la página él mismo por
HTTPS y la señalización va por `wss://` al mismo origen.

Calidad recomendada: **1080p a 60 fps**. Más resolución aporta poco, porque el
detector recibe un recorte de 384 px alrededor de la mano.

## Por qué se siente estable

El jitter es lo que separa un demo de algo usable:

1. **Punto de referencia mezclado** — la yema es el landmark más ruidoso de los
   21; se mezcla con la falange anterior (78/22)
2. **One Euro** con `beta` bajo — `beta` multiplica la velocidad, y el ruido
   *parece* velocidad, así que un valor alto se realimenta. Medido: 0,06 → 17 px
   de deriva; 0,02 → 10 px, con el mismo retardo
3. **El cursor se ancla al pinzar** — el clic cae donde apuntabas
4. **El arrastre se mide con la palma** — al juntar los dedos la yema se
   desplaza sola, y medir ahí convertía cada clic en scroll
5. **El scroll no se arma hasta pasados 360 ms** — más de lo que dura un clic

## Arquitectura

```
airtouch/
├─ app.py            ensambla todo y arranca Qt
├─ version.py        el número de versión, en un único sitio
├─ config.py         dataclasses + %APPDATA%\AirTouch\config.json
├─ core/             captura, visión, filtros, mapeo, controlador
├─ gestures/         máquina de estados, catapulta, eventos
├─ actuators/        SendInput, ventanas, seguridad, campos de texto
├─ net/              AirLink (WebRTC), certificados, cortafuegos, updates
├─ overlay/          ventana transparente click-through
└─ ui/               panel, asistente, ajustes, widgets, temas
```

Cuatro hilos: captura → visión → gestos → actuación, comunicados por señales de
Qt. **El motor de gestos no toca el sistema operativo**: solo produce eventos.
El controlador decide si se aplican, y solo si el control real está activado.
Por eso el modo seguro es real y no un parche.

## Desarrollo

```bat
install.bat          crea el entorno e instala dependencias
run.bat              ejecuta desde el código
```

Pruebas — fabrican manos sintéticas y validan la máquina de estados **sin
cámara y sin tocar el escritorio**:

```bat
.venv\Scripts\python.exe tests\test_engine.py
```

Compilar:

```bat
.venv\Scripts\python.exe build.py
```

Comprobar una instalación (visión, modelos, web y red, sin abrir la interfaz):

```bat
AirTouch.exe --selftest
```

Publicar una versión — un solo comando; ver
[airhand-web/RELEASING.md](airhand-web/RELEASING.md):

```bat
.venv\Scripts\python.exe release.py 1.1.0
```

## Limitaciones conocidas

- **La mirada no sirve como puntero.** El Vision Pro usa cámaras infrarrojas a
  3 cm del ojo; una cámara a 60 cm da 5-10° de error, varios centímetros en
  pantalla. La cara se usa solo para presencia.
- **El brazo cansa.** Pensado para gestos pequeños con el codo apoyado, no para
  sustituir al ratón durante horas.
- Las apps que corren como administrador ignoran la entrada inyectada salvo que
  AirTouch también se ejecute como administrador.

## Licencia

MIT.
