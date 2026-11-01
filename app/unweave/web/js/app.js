// Importing feature modules installs their DOM handlers; theme.js applies the saved theme first.
import {initThemeToggle} from './chrome/theme.js';
import {initNavigation} from './chrome/navigation.js';
import {initTitlebar} from './chrome/window.js';
import './audio/transport.js';
import './features/dialogs.js';
import './features/folders.js';
import './views/settings.js';
import './features/lookup.js';
import './chrome/credits.js';
import {nav} from './core/store.js';
import {queueBusy, notice} from './core/core.js';
import {animate} from './audio/audio.js';
import {t} from './core/i18n.js';
import {initLangToggle} from './chrome/lang-toggle.js';
import {considerUpdates} from './chrome/updates.js';

// Late-bind the hooks only after every module has evaluated, then initialize the
// remaining page chrome before the initial state poll starts.
initNavigation();
initTitlebar();
initThemeToggle();
initLangToggle();

async function poll() {
  try { await nav.refresh(); }
  catch (error) { notice(t('nav.connectionProblem', {error: error.message}), 'error'); }
  try { await considerUpdates(); } catch (_) { /* update consent/check is best-effort */ }
  setTimeout(poll, queueBusy() ? 1000 : 2500);
}
poll(); animate();
