/*
 * AirHand — sitio de instalación.
 *
 * Lo importante de este archivo: **el botón de descarga no lleva ninguna URL
 * escrita a mano**. Se pregunta a la API de GitHub cuál es la última versión
 * publicada y se usa ese archivo. Así, publicar una versión nueva de AirHand
 * es lo único que hay que hacer: esta página se entera sola y no hay que
 * tocarla nunca más.
 */
'use strict';

const REPO = { owner: 'Pablodev-star', name: 'AirHand' };
const REPO_URL = `https://github.com/${REPO.owner}/${REPO.name}`;
const API = `https://api.github.com/repos/${REPO.owner}/${REPO.name}/releases/latest`;
const LS_STEPS = 'airhand.setup.steps.v1';

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

// ---------------------------------------------------------------- descarga
async function loadRelease() {
  const btn = $('#btn-download');
  const meta = $('#download-meta');
  try {
    const res = await fetch(API, { headers: { Accept: 'application/vnd.github+json' } });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const rel = await res.json();

    // Se coge el primer archivo instalable que traiga la publicación. No se
    // filtra por nombre exacto a propósito: si mañana el archivo se llama de
    // otra forma, esto sigue funcionando.
    const asset = (rel.assets || []).find((a) =>
      /\.(exe|zip|msi)$/i.test(a.name));

    if (!asset) throw new Error('sin archivo');

    btn.href = asset.browser_download_url;
    btn.classList.remove('disabled');
    btn.textContent = 'Descargar AirHand ' + (rel.tag_name || '');
    meta.textContent = `${formatSize(asset.size)} · publicado ${formatDate(rel.published_at)}`;
    const hv = $('#hero-version');
    if (hv) hv.textContent = `Versión ${rel.tag_name || '?'} · gratis y de código abierto`;
  } catch (err) {
    // Todavía no hay ninguna versión publicada, o GitHub no responde.
    btn.href = REPO_URL + '/releases';
    btn.textContent = 'Ver descargas en GitHub';
    meta.innerHTML =
      'Aún no se ha publicado ninguna versión automática. ' +
      `En <a href="${REPO_URL}" target="_blank" rel="noopener">el repositorio</a> ` +
      'están las instrucciones para compilarlo tú mismo.';
  }
}

function formatSize(bytes) {
  if (!bytes) return '';
  const mb = bytes / 1024 / 1024;
  return mb >= 1 ? mb.toFixed(0) + ' MB' : (bytes / 1024).toFixed(0) + ' KB';
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString('es-ES',
      { day: 'numeric', month: 'long', year: 'numeric' });
  } catch (_) { return ''; }
}

// ---------------------------------------------------------------- sistema
function checkOS() {
  const el = $('#check-os');
  if (!el) return;
  const ua = navigator.userAgent;
  const isWindows = /Windows NT/.test(ua);
  const isPhone = /iPhone|iPad|Android/.test(ua);

  if (isWindows) {
    el.textContent = '✓ Estás en Windows: perfecto';
    el.className = 'check ok';
  } else if (isPhone) {
    el.textContent = '↻ Estás en el móvil. Abre esta página en tu PC para descargarlo';
    el.className = 'check bad';
  } else {
    el.textContent = '! No parece que estés en Windows. AirHand solo funciona en Windows';
    el.className = 'check bad';
  }
}

// ---------------------------------------------------------------- pasos
function setupSteps() {
  const boxes = $$('.done input');
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(LS_STEPS) || '{}'); } catch (_) {}

  boxes.forEach((box, i) => {
    box.checked = !!saved[i];
    box.addEventListener('change', () => {
      saved[i] = box.checked;
      try { localStorage.setItem(LS_STEPS, JSON.stringify(saved)); } catch (_) {}
      refreshProgress();
    });
  });

  // marcar también pulsando la cabecera del paso, que es un objetivo mayor
  $$('.step-head').forEach((head) => {
    head.addEventListener('click', (e) => {
      if (e.target.closest('.done')) return;
      const box = head.querySelector('.done input');
      if (box) { box.checked = !box.checked; box.dispatchEvent(new Event('change')); }
    });
  });

  refreshProgress();
}

function refreshProgress() {
  const boxes = $$('.done input');
  const done = boxes.filter((b) => b.checked).length;
  const pct = boxes.length ? (done / boxes.length) * 100 : 0;

  $('#progress').style.width = pct + '%';
  $('#progress-text').textContent = `${done} de ${boxes.length} pasos`;

  boxes.forEach((b) => b.closest('.step').classList.toggle('is-done', b.checked));
  $('#finished').hidden = done < boxes.length;
}

// ---------------------------------------------------------------- contenido
const GESTOS = [
  ['Mover el puntero', 'Apunta con el índice extendido'],
  ['Clic', 'Junta el pulgar y el índice y suelta'],
  ['Doble clic', 'Dos pinch seguidos'],
  ['Scroll', 'Mantén el pinch y mueve la mano arriba o abajo'],
  ['Clic derecho', 'Catapulta: curva el índice contra el pulgar y suéltalo'],
  ['Zoom', 'Pinch con las dos manos y sepáralas o júntalas'],
  ['Mover una ventana', 'Pinch en la barra que aparece bajo la ventana'],
  ['Redimensionar', 'Pinch en la esquina inferior derecha de la ventana'],
  ['Escribir', 'Al tocar un campo de texto aparece un teclado virtual'],
  ['Letras con tilde', 'Catapulta sobre una tecla para ver sus variantes'],
  ['Pausar', 'Abre la palma un momento, o mantén Esc un segundo'],
  ['Recuperar el ratón', 'Muévelo físicamente: AirHand se aparta solo'],
];

const FAQ = [
  ['El móvil dice que no encuentra el servidor',
   'Casi siempre es el cortafuegos (paso 3). Comprueba también que el móvil y el ' +
   'PC están en la <b>misma red</b>: las redes de invitados aíslan los ' +
   'dispositivos entre sí. Si usas un sistema mesh, revisa que no tenga activado ' +
   'el «aislamiento de clientes».'],
  ['Safari dice que la conexión no es privada',
   'Es esperado. El certificado lo genera tu propio PC y no hay ninguna empresa ' +
   'que lo firme, porque no hace falta: la conexión no sale de tu casa. Pulsa ' +
   '<b>Mostrar detalles → Visitar este sitio web</b>.'],
  ['El puntero tiembla mucho',
   'Lo más probable es que la cámara esté enviando poca resolución. En el móvil, ' +
   'elige <b>1080p y 60 fps</b>. También ayuda tener buena luz: en penumbra el ' +
   'detector pierde precisión. Si aun así tiembla, sube el <b>suavizado</b> en ' +
   'Ajustes → Puntero.'],
  ['El clic se convierte en scroll',
   'No debería: el scroll solo se activa si mantienes el pinch más de un tercio ' +
   'de segundo. Si te pasa, es que el pinch se queda «pegado»: repite la ' +
   'calibración de la mano en Ajustes.'],
  ['El clic derecho no me sale',
   'Es el gesto más difícil. Tiene que ser seco: el índice curvado apoyado ' +
   'contra el pulgar, y salir disparado hacia delante hasta quedar recto. Si no ' +
   'hay manera, baja la <b>velocidad mínima de la catapulta</b> en Ajustes.'],
  ['El vídeo se corta al salir de la app del móvil',
   'iOS apaga la cámara cuando la app pasa a segundo plano. Es una limitación ' +
   'del sistema: deja AirLink abierto en primer plano.'],
  ['No detecta mis manos, o algo falla y no sé qué',
   'AirHand se sabe revisar a sí mismo. Abre la carpeta donde lo descomprimiste, ' +
   'escribe <code>cmd</code> en la barra de direcciones del explorador y ejecuta:<br>' +
   '<code>AirTouch.exe --selftest</code><br>' +
   'Comprueba la cámara, los modelos y la red, y dice qué pieza falla. El ' +
   'informe queda en <code>%APPDATA%\\AirTouch\\logs</code>.'],
  ['¿Se ve mi cámara en internet?',
   'No. El vídeo va directo del móvil al PC por tu red local, cifrado. No hay ' +
   'ningún servidor por el medio, y AirHand funciona igual con el router sin ' +
   'internet.'],
  ['¿Puedo desinstalarlo?',
   'Borra la carpeta. No escribe en el registro de Windows salvo si activas ' +
   '«arrancar con Windows», y esa entrada se quita desactivando la opción. La ' +
   'configuración vive en <code>%APPDATA%\\AirTouch</code>.'],
  ['¿Funciona con Android?',
   'Sí. AirLink es una página web normal: se abre en Chrome y funciona igual. ' +
   'La guía habla de iPhone porque es lo más común.'],
  ['¿Necesito instalar Python?',
   'No. La descarga trae todo dentro. Solo hace falta Python si quieres ' +
   'compilarlo tú desde el código.'],
];

function renderContent() {
  $('#gestures').innerHTML = GESTOS.map(
    ([name, desc]) => `<div class="gesture"><b>${name}</b><span>${desc}</span></div>`
  ).join('');

  $('#faq').innerHTML = FAQ.map(
    ([q, a]) => `<details class="faq-item"><summary>${q}</summary><p>${a}</p></details>`
  ).join('');

  for (const el of [$('#nav-repo'), $('#foot-repo')]) {
    if (el) el.href = REPO_URL;
  }
}

// ---------------------------------------------------------------- arranque
renderContent();
setupSteps();
checkOS();
loadRelease();
