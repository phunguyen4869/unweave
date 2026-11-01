// Importing feature modules installs their DOM handlers; theme.js applies the saved theme first.
import {initThemeToggle} from './theme.js';
import {initNavigation} from './navigation.js';
import {initTitlebar} from './window.js';
import './transport.js';
import './dialogs.js';
import './folders.js';
import './lookup.js';
import './credits.js';
import {nav} from './store.js';
import {queueBusy, notice} from './core.js';
import {animate} from './audio.js';
import {t} from './i18n.js';
import {initLangToggle} from './lang-toggle.js';
import {considerUpdates} from './updates.js';

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
