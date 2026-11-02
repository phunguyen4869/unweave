import {$, api, notice} from '../core/core.js';
import {store} from '../core/store.js';
import {t} from '../core/i18n.js';

const DISMISS_KEY = 'unweave.linuxAudioBannerDismissed';

function isNative() {
  return new URLSearchParams(location.search).get('native') === '1';
}

function dismissed() {
  try { return localStorage.getItem(DISMISS_KEY) === '1'; } catch (_) { return false; }
}

function dismiss() {
  try { localStorage.setItem(DISMISS_KEY, '1'); } catch (_) { /* nicety only */ }
  const banner = $('linux-audio-banner');
  if (banner) banner.hidden = true;
}

/** WebKitGTK Web Audio is often silent; offer the loopback URL in a real browser. */
export function renderLinuxAudioBanner() {
  const banner = $('linux-audio-banner');
  if (!banner) return;
  banner.hidden = !(isNative() && store.state.platform === 'linux' && !dismissed());
}

async function openInSystemBrowser() {
  const url = `${location.origin}/`;
  // window.open is blocked in pywebview/WebKitGTK — ask the desktop shell instead.
  try {
    await api('/api/window/open-external', {url});
  } catch (error) {
    notice(error.message || t('banner.openInBrowser'), 'error');
  }
}

export function initLinuxAudioBanner() {
  const open = $('linux-audio-banner-open');
  const later = $('linux-audio-banner-later');
  if (open) {
    open.href = `${location.origin}/`;
    open.onclick = event => {
      event.preventDefault();
      openInSystemBrowser();
    };
  }
  if (later) later.onclick = () => dismiss();
  renderLinuxAudioBanner();
}
