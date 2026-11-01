import {$, el, api, notice} from '../core/core.js';
import {store} from '../core/store.js';
import {t, onLangChange} from '../core/i18n.js';

let booted = false;
let dialogOpen = false;
let lastStatus = null;
let pending = {updates: false, cleanup: false};
let startupCleanup = null;

function appUsable() {
  // Spec 10 / 13: prompt after required setup is complete or dismissed — not before.
  return !store.state.setup?.required || store.setupDeclined;
}

function formatBytes(bytes) {
  const n = Math.max(0, Number(bytes) || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(n < 10 * 1024 ** 2 ? 1 : 0)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
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

async function persistUpdatePrefs(body) {
  return api('/api/updates/prefs', body);
}

async function runCheck({manual}) {
  const status = await api('/api/updates/check', {manual: !!manual});
  showBanner(status);
  return status;
}

function groupLabel(group) {
  return t(`cleanup.group.${group}`);
}

export function renderCleanupGroups(target, items) {
  target.replaceChildren();
  const groups = {};
  for (const item of items || []) {
    const key = item.group || 'temp';
    if (!groups[key]) groups[key] = {bytes: 0, items: []};
    groups[key].bytes += item.bytes || 0;
    groups[key].items.push(item);
  }
  for (const [group, data] of Object.entries(groups)) {
    const details = el('details', 'startup-cleanup-group');
    const summary = el('summary', '');
    summary.append(
      el('strong', '', groupLabel(group)),
      el('span', 'startup-cleanup-meta', t('cleanup.groupMeta', {
        size: formatBytes(data.bytes),
        count: data.items.length,
      })),
    );
    const list = el('ul', 'startup-cleanup-paths');
    for (const item of data.items) {
      list.append(el('li', '', item.path));
    }
    details.append(summary, list);
    target.append(details);
  }
}

function maybeCloseStartup() {
  if (pending.updates || pending.cleanup) return;
  $('startup-dialog').close();
  dialogOpen = false;
}

function openStartup({showUpdates, showCleanup, cleanup}) {
  if (dialogOpen || $('startup-dialog')?.open) return;
  if (!showUpdates && !showCleanup) return;
  dialogOpen = true;
  pending = {updates: !!showUpdates, cleanup: !!showCleanup};
  startupCleanup = cleanup || null;
  $('startup-updates').hidden = !showUpdates;
  $('startup-cleanup').hidden = !showCleanup;
  $('updates-dont-ask').checked = false;
  $('cleanup-auto').checked = false;
  $('cleanup-dont-ask').checked = false;
  $('startup-cleanup-status').hidden = true;
  $('startup-cleanup-status').textContent = '';
  $('cleanup-run').disabled = false;
  if (showCleanup && cleanup) {
    $('startup-cleanup-body').textContent = t('cleanup.body', {size: formatBytes(cleanup.bytes)});
    renderCleanupGroups($('startup-cleanup-groups'), cleanup.items);
  }
  $('startup-dialog').showModal();
}

async function onAllow() {
  pending.updates = false;
  $('startup-updates').hidden = true;
  await persistUpdatePrefs({check: 'auto'});
  maybeCloseStartup();
  try { await runCheck({manual: false}); } catch (_) { /* auto failures stay quiet */ }
}

async function onNotNow() {
  pending.updates = false;
  $('startup-updates').hidden = true;
  const dontAsk = $('updates-dont-ask').checked;
  if (dontAsk) await persistUpdatePrefs({check: 'manual'});
  else await persistUpdatePrefs({check: 'ask'});
  maybeCloseStartup();
}

async function onCleanupNotNow() {
  pending.cleanup = false;
  $('startup-cleanup').hidden = true;
  const prefs = {
    auto: $('cleanup-auto').checked,
    dont_ask: $('cleanup-dont-ask').checked,
  };
  await api('/api/cleanup/prefs', prefs);
  maybeCloseStartup();
}

async function onCleanupRun() {
  const status = $('startup-cleanup-status');
  const button = $('cleanup-run');
  button.disabled = true;
  status.hidden = false;
  status.textContent = t('cleanup.working');
  try {
    const prefs = {
      auto: $('cleanup-auto').checked,
      dont_ask: $('cleanup-dont-ask').checked,
    };
    await api('/api/cleanup/prefs', prefs);
    const result = await api('/api/cleanup/run', {});
    status.textContent = t('cleanup.freed', {size: formatBytes(result.freed_bytes || 0)});
    pending.cleanup = false;
    setTimeout(() => {
      $('startup-cleanup').hidden = true;
      maybeCloseStartup();
    }, 900);
  } catch (error) {
    status.textContent = error.message;
    button.disabled = false;
  }
}

function maybeShowCleanupNotice(state) {
  const noticeInfo = state?.cleanup?.notice;
  if (!noticeInfo?.freed_bytes) return;
  notice(t('cleanup.freed', {size: formatBytes(noticeInfo.freed_bytes)}), 'success');
}

export async function considerUpdates() {
  if (!appUsable()) return;
  maybeShowCleanupNotice(store.state);
  let startup;
  try {
    // /api/startup scans once if needed, applies the silent rule, then reports
    // which dialog sections (if any) should open.
    startup = await api('/api/startup');
  } catch (_) {
    return;
  }
  showBanner(startup.updates);
  if (!booted) {
    booted = true;
    if (startup.open) {
      openStartup({
        showUpdates: startup.show_updates,
        showCleanup: startup.show_cleanup,
        cleanup: startup.cleanup,
      });
      return;
    }
    if (startup.should_auto_check) {
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

export async function scanLeftovers() {
  return api('/api/cleanup/scan', {});
}

export async function runLeftoversClean(ids) {
  return api('/api/cleanup/run', ids ? {ids} : {});
}

$('update-banner-later').onclick = async () => {
  const tag = lastStatus?.latest || '';
  hideBanner();
  if (!tag) return;
  try { await persistUpdatePrefs({dismissed_tag: tag}); }
  catch (error) { notice(error.message, 'error'); }
};

$('updates-allow').onclick = () => { onAllow().catch(error => notice(error.message, 'error')); };
$('updates-not-now').onclick = () => { onNotNow().catch(error => notice(error.message, 'error')); };
$('cleanup-not-now').onclick = () => { onCleanupNotNow().catch(error => notice(error.message, 'error')); };
$('cleanup-run').onclick = () => { onCleanupRun().catch(error => notice(error.message, 'error')); };
$('startup-dialog').addEventListener('close', () => { dialogOpen = false; pending = {updates: false, cleanup: false}; });

onLangChange(() => {
  if (!$('update-banner').hidden) {
    api('/api/updates/status').then(showBanner).catch(() => {});
  }
});
