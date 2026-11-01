import {$, api, notice} from './core.js';
import {store, nav} from './store.js';
import {t} from './i18n.js';
/* ---------- Desktop window chrome (frameless pywebview only) ---------- */
// Routed through our own HTTP API (POST/GET /api/window/<action>), same as everything
// else in this app, rather than pywebview's JS bridge: window.pywebview never actually
// shows up on this page in practice, so that bridge can't be relied on for something
// this basic.
function windowAction(action, data) { return api(`/api/window/${action}`, data || {}).catch(error => notice(error.message, 'error')); }

// Drag-to-move and drag-to-resize both work the same way: on mousedown, grab the
// window's current bounds once; on every (rAF-throttled) mousemove after that, compute
// the new bounds from the cursor's screen-space delta and send them. This replaces the
// classic WM_SYSCOMMAND/HTCAPTION "hand the drag to the OS" trick, which doesn't work
// reliably through a Chromium-based webview (its own mouse capture gets in the way) —
// confirmed here: it simply never moved the window.
function trackDrag(downEvent, onFrame) {
  if (downEvent.button !== 0) return;
  downEvent.preventDefault();
  const startX = downEvent.screenX, startY = downEvent.screenY;
  let raf = null, pending = null;
  const flush = () => { raf = null; if (pending) { onFrame(pending); pending = null; } };
  const onMove = event => {
    pending = {dx: event.screenX - startX, dy: event.screenY - startY};
    if (raf === null) raf = requestAnimationFrame(flush);
  };
  const onUp = () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    if (raf !== null) cancelAnimationFrame(raf);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

async function startWindowMove(downEvent) {
  const start = await windowAction('bounds');
  if (!start) return;
  trackDrag(downEvent, ({dx, dy}) => windowAction('move', {x: start.x + dx, y: start.y + dy}));
}

async function startWindowResize(downEvent, dir) {
  const start = await windowAction('bounds');
  if (!start) return;
  trackDrag(downEvent, ({dx, dy}) => {
    let width = start.width, height = start.height;
    if (dir.includes('e')) width += dx;
    if (dir.includes('w')) width -= dx;
    if (dir.includes('s')) height += dy;
    if (dir.includes('n')) height -= dy;
    windowAction('resize', {width, height, direction: dir});
  });
}

export function initTitlebar() {
  // The desktop app loads this page with ?native=1 (see ui_entrypoint.py); that alone,
  // checked synchronously, decides whether this bar (and the resize edges) show at all.
  if (new URLSearchParams(location.search).get('native') !== '1') return;
  $('titlebar').hidden = false;
  $('resize-edges').hidden = false;
  document.body.classList.add('has-titlebar');

  const drag = document.querySelector('.titlebar-drag');
  drag.addEventListener('mousedown', event => startWindowMove(event));
  drag.addEventListener('dblclick', () => $('win-max').click());  // OS-standard convention

  document.querySelectorAll('.redge').forEach(edge => {
    edge.addEventListener('mousedown', event => startWindowResize(event, edge.dataset.dir));
  });

  $('win-min').onclick = () => windowAction('minimize');
  $('win-max').onclick = async () => {
    if ($('win-max').disabled) return;  // ignore a second click while one is in flight
    $('win-max').disabled = true;
    const result = await windowAction('toggle-maximize');
    const maximized = !!result?.maximized;
    $('win-max').classList.toggle('is-restore', maximized);
    $('win-max').title = $('win-max').ariaLabel = maximized ? t('titlebar.restore') : t('titlebar.maximize');
    $('win-max').disabled = false;
  };
  let closePending = false;  // set when the backend asks for close confirmation

  $('win-close').onclick = async () => {
    if (closePending) { await windowAction('close', {confirm: true}); return; }
    const result = await windowAction('close');
    if (result?.confirm) {
      closePending = true;
      $('close-confirm-message').textContent = result.message || t('dialog.closeConfirm.message');
      $('close-confirm-dialog').showModal();
    }
  };
  $('close-confirm-submit').onclick = async event => {
    event.preventDefault();
    closePending = false;
    $('close-confirm-dialog').close();
    await windowAction('close', {confirm: true});
  };
  // Cancel must re-arm the prompt, or the next close click would skip it.
  $('close-confirm-dialog').addEventListener('close', () => { closePending = false; });
}
