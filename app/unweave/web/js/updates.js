import {$, api, notice} from './core.js';
import {store} from './store.js';
import {t, onLangChange} from './i18n.js';

let booted = false;
let consentOpen = false;
let lastStatus = null;

function appUsable() {
  // Spec 10: prompt after required setup is complete or dismissed — not before.
  return !store.state.setup?.required || store.setupDeclined;
}

function showBanner(status) {
  lastStatus = status || null;
  const banner = $('update-banner');
  if (!status?.available || !status.latest) {
    banner.hidden = true;
    return;
  }
  $('update-banner-text').textContent = t('updates.available', {
    latest: status.latest,
    current: status.current || store.state.version || '—',
  });
  const link = $('update-banner-open');
  link.href = status.url || '#';
  banner.hidden = false;
}

function hideBanner() {
  $('update-banner').hidden = true;
}

async function persistPrefs(body) {
  return api('/api/updates/prefs', body);
}

async function runCheck({manual}) {
  const status = await api('/api/updates/check', {manual: !!manual});
  showBanner(status);
  return status;
}

function openConsent() {
  if (consentOpen || $('updates-consent-dialog').open) return;
  consentOpen = true;
  $('updates-dont-ask').checked = false;
  $('updates-consent-dialog').showModal();
}

async function onAllow() {
  $('updates-consent-dialog').close();
  consentOpen = false;
  await persistPrefs({check: 'auto'});
  try {
    await runCheck({manual: false});
  } catch (_) {
    /* auto failures stay quiet */
  }
}

async function onNotNow() {
  $('updates-consent-dialog').close();
  consentOpen = false;
  const dontAsk = $('updates-dont-ask').checked;
  if (dontAsk) await persistPrefs({check: 'manual'});
  else await persistPrefs({check: 'ask'});
}

export async function considerUpdates() {
  if (!appUsable()) return;
  let status;
  try {
    status = await api('/api/updates/status');
  } catch (_) {
    return;
  }
  showBanner(status);
  if (!booted) {
    booted = true;
    if (status.should_prompt) {
      openConsent();
      return;
    }
    if (status.should_auto_check) {
      try { await runCheck({manual: false}); }
      catch (_) { /* silent for auto */ }
    }
  }
}

export async function checkForUpdatesManual() {
  try {
    const status = await runCheck({manual: true});
    if (status.available) notice(t('updates.availableNotice', {latest: status.latest}), 'info');
    else notice(t('updates.upToDate'), 'success');
  } catch (error) {
    notice(error.message, 'error');
  }
}

$('update-banner-later').onclick = async () => {
  const tag = lastStatus?.latest || '';
  hideBanner();
  if (!tag) return;
  try { await persistPrefs({dismissed_tag: tag}); }
  catch (error) { notice(error.message, 'error'); }
};

$('updates-allow').onclick = () => { onAllow().catch(error => notice(error.message, 'error')); };
$('updates-not-now').onclick = () => { onNotNow().catch(error => notice(error.message, 'error')); };
$('updates-consent-dialog').addEventListener('close', () => { consentOpen = false; });

onLangChange(() => {
  if (!$('update-banner').hidden) {
    api('/api/updates/status').then(showBanner).catch(() => {});
  }
});
