import {$, el, api, notice, jobRunning, queueBusy} from '../core/core.js';
import {store, nav} from '../core/store.js';
import {t, getLang, setLang, onLangChange} from '../core/i18n.js';
import {openFolder} from '../features/folders.js';
import {checkForUpdatesManual, renderCleanupGroups, scanLeftovers, runLeftoversClean} from '../chrome/updates.js';
import {STAGE_ICONS, INSTALLABLE_STAGES, sizeText} from '../features/components.js';
import {renderAbout} from '../chrome/credits.js';

const TABS = ['general', 'components', 'storage', 'updates', 'about'];
let activeTab = 'general';
let storageLoad = null;
let leftoverLoad = null;
let updatesLoaded = false;

function formatBytes(bytes) {
  const n = Math.max(0, Number(bytes) || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(n < 10 * 1024 ** 2 ? 1 : 0)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

function setupBusy() {
  const job = store.state.job;
  return !!job && job.kind === 'setup' && ['running', 'cancelling', 'queued'].includes(job.status);
}

function dialogOpen() {
  return !!$('settings-dialog')?.open;
}

async function loadStorage() {
  try {
    store.settingsStorage = await api('/api/storage');
  } catch (error) {
    store.settingsStorage = null;
    notice(error.message, 'error');
  }
}

async function loadUpdatesPrefs() {
  try {
    store.settingsUpdates = await api('/api/updates/status');
  } catch (_) {
    store.settingsUpdates = null;
  }
}

async function loadLeftovers() {
  try {
    store.settingsCleanup = await api('/api/cleanup');
  } catch (error) {
    store.settingsCleanup = null;
    notice(error.message, 'error');
  }
}

function renderLeftovers() {
  const info = store.settingsCleanup;
  const summary = $('settings-leftover-summary');
  const clean = $('settings-leftover-clean');
  const auto = $('settings-leftover-auto');
  if (!info) {
    summary.textContent = '—';
    clean.disabled = true;
    auto.disabled = true;
    return;
  }
  summary.textContent = info.count
    ? t('settings.leftoverSummary', {size: formatBytes(info.bytes), count: info.count})
    : t('settings.leftoverEmpty');
  clean.disabled = !info.count || queueBusy() || jobRunning();
  auto.disabled = false;
  auto.checked = !!info.prefs?.auto;
}

function renderComponents() {
  const list = $('settings-components');
  if (!list) return;
  list.replaceChildren();
  const stages = store.state.setup?.stages || [];
  const busy = setupBusy() || jobRunning();
  for (const stage of stages) {
    const card = el('div', `setup-tile settings-tile ${stage.done ? 'setup-tile--done' : 'setup-tile--pending'}`);
    const chip = stage.done
      ? ['done', `✓ ${t('setup.chip.installed')}`]
      : stage.required
        ? ['required', t('setup.chip.required')]
        : ['optional', t('setup.chip.optional')];
    const icon = el('span', 'setup-tile-icon');
    icon.innerHTML = STAGE_ICONS[stage.id] || STAGE_ICONS.runtime;
    const top = el('div', 'setup-tile-top');
    top.append(icon, el('span', `setup-chip setup-chip--${chip[0]}`, chip[1]));
    const foot = el('div', 'setup-tile-foot');
    foot.append(el('span', 'setup-tile-size', `~${sizeText(stage.size_mb)}`));
    if (INSTALLABLE_STAGES.has(stage.id)) {
      const action = el('button', 'btn btn-ghost btn-sm', stage.done ? t('settings.repair') : t('settings.install'));
      action.type = 'button';
      action.disabled = busy;
      action.onclick = () => startStage(stage.id, !!stage.done);
      foot.append(action);
    } else if (!stage.done) {
      foot.append(el('span', 'settings-tile-note', t('settings.runtimeFromInstaller')));
    }
    card.append(top, el('strong', 'setup-tile-name', t(`setup.name.${stage.id}`)),
      el('p', 'setup-tile-desc', t(`setup.desc.${stage.id}`)), foot);
    list.append(card);
  }
}

function renderStorage() {
  const storage = store.settingsStorage;
  $('settings-models-size').textContent = storage
    ? t('settings.modelsSize', {size: formatBytes(storage.models_bytes)})
    : '—';
  $('settings-projects-size').textContent = storage
    ? t('settings.projectsSize', {size: formatBytes(storage.projects_bytes)})
    : '—';
  $('settings-clear-models').disabled = !storage || storage.models_bytes <= 0 || queueBusy() || jobRunning();
  const list = $('settings-project-sizes');
  list.replaceChildren();
  if (!storage?.projects?.length) {
    list.append(el('p', 'hint', t('settings.noProjects')));
    return;
  }
  const titleCounts = {};
  for (const project of storage.projects) {
    const title = project.title || project.id;
    titleCounts[title] = (titleCounts[title] || 0) + 1;
  }
  for (const project of storage.projects) {
    const title = project.title || project.id;
    const row = el('div', 'settings-project-row');
    const text = el('div', 'settings-project-text');
    text.append(el('strong', '', title));
    if (titleCounts[title] > 1) {
      text.append(el('span', 'settings-project-folder', project.id));
    }
    text.append(el('span', 'settings-project-meta', t('settings.projectBytes', {
      total: formatBytes(project.bytes),
      exports: formatBytes(project.exports_bytes),
    })));
    const button = el('button', 'btn btn-ghost btn-sm', t('settings.clearExports'));
    button.type = 'button';
    button.disabled = !project.exports_bytes || queueBusy() || jobRunning();
    button.onclick = () => openClearExports(project);
    row.append(text, button);
    list.append(row);
  }
}

function renderFolder() {
  const root = store.state.root || t('common.noFolderSelected');
  $('settings-folder-path').textContent = root;
  const isDefault = !!store.state.root && store.state.root === store.state.default_root;
  $('settings-folder-default-tag').hidden = !isDefault;
  $('settings-folder-use-default').hidden = isDefault || !store.state.default_root;
}

function renderUpdates() {
  const status = store.settingsUpdates;
  const input = $('settings-updates-auto');
  input.checked = status?.check === 'auto';
  input.disabled = !status;
}

function renderLanguage() {
  const lang = getLang();
  $('settings-lang-en').setAttribute('aria-selected', String(lang === 'en'));
  $('settings-lang-vi').setAttribute('aria-selected', String(lang === 'vi'));
}

function selectTab(name, {focus = false} = {}) {
  if (!TABS.includes(name)) name = 'general';
  activeTab = name;
  store.settingsTab = name;
  for (const tab of TABS) {
    const button = $(`settings-tab-${tab}`);
    const panel = $(`settings-panel-${tab}`);
    const selected = tab === name;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    panel.hidden = !selected;
  }
  if (focus) $(`settings-tab-${name}`).focus();
  if (name === 'general') { renderLanguage(); renderFolder(); }
  if (name === 'components') renderComponents();
  if (name === 'updates') renderUpdates();
  if (name === 'about') renderAbout();
  if (name === 'storage') ensureStorage();
}

async function ensureStorage() {
  if (!store.settingsStorageLoaded) {
    storageLoad = storageLoad || loadStorage().then(() => { store.settingsStorageLoaded = true; });
    await storageLoad;
    storageLoad = null;
  }
  if (!store.settingsCleanupLoaded) {
    leftoverLoad = leftoverLoad || loadLeftovers().then(() => { store.settingsCleanupLoaded = true; });
    await leftoverLoad;
    leftoverLoad = null;
  }
  if (dialogOpen() && activeTab === 'storage') {
    renderStorage();
    renderLeftovers();
  }
}

async function openSettings(tab) {
  if (!updatesLoaded) {
    await loadUpdatesPrefs();
    updatesLoaded = true;
  }
  selectTab(tab || store.settingsTab || 'general');
  $('settings-dialog').showModal();
  $(`settings-tab-${activeTab}`).focus();
}

/** Called from the poll/render loop: only refresh install chips while the dialog is open. */
export function refreshSettingsOpen() {
  if (!dialogOpen()) return;
  renderComponents();
  if (activeTab === 'general') renderFolder();
}

async function startStage(stageId, repair) {
  if (store.busy || setupBusy() || jobRunning()) return;
  store.setupRunningStages = [stageId];
  try {
    await api('/api/setup/start', {stages: [stageId], repair: !!repair});
    await nav.refresh();
    notice(t(repair ? 'settings.repairStarted' : 'settings.installStarted'), 'info');
    renderComponents();
  } catch (error) {
    store.setupRunningStages = [];
    notice(error.message, 'error');
  }
}

function openClearExports(project) {
  store.clearingExports = {id: project.id, title: project.title || project.id, root: store.state.root};
  $('settings-clear-exports-name').textContent = store.clearingExports.title;
  $('settings-clear-exports-error').textContent = '';
  $('settings-clear-exports-dialog').showModal();
}

$('settings-open').onclick = () => openSettings();

document.querySelectorAll('#settings-tabs .settings-tab').forEach(button => {
  button.onclick = () => selectTab(button.dataset.tab, {focus: true});
});

$('settings-tabs').addEventListener('keydown', event => {
  const index = TABS.indexOf(activeTab);
  if (index < 0) return;
  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
    event.preventDefault();
    selectTab(TABS[(index + 1) % TABS.length], {focus: true});
  } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
    event.preventDefault();
    selectTab(TABS[(index - 1 + TABS.length) % TABS.length], {focus: true});
  } else if (event.key === 'Home') {
    event.preventDefault();
    selectTab(TABS[0], {focus: true});
  } else if (event.key === 'End') {
    event.preventDefault();
    selectTab(TABS[TABS.length - 1], {focus: true});
  }
});

$('settings-clear-models').onclick = () => {
  $('settings-clear-models-error').textContent = '';
  $('settings-clear-models-dialog').showModal();
};

$('settings-clear-models-form').onsubmit = async event => {
  event.preventDefault();
  const submit = $('settings-clear-models-submit');
  submit.disabled = true;
  try {
    await api('/api/storage/clear-models', {});
    $('settings-clear-models-dialog').close();
    notice(t('settings.modelsCleared'), 'success');
    store.settingsStorageLoaded = false;
    await ensureStorage();
  } catch (error) {
    $('settings-clear-models-error').textContent = error.message;
  } finally {
    submit.disabled = false;
  }
};

$('settings-clear-exports-form').onsubmit = async event => {
  event.preventDefault();
  if (!store.clearingExports) return;
  const target = store.clearingExports;
  const submit = $('settings-clear-exports-submit');
  submit.disabled = true;
  try {
    await api(`/api/projects/${encodeURIComponent(target.id)}/clear-exports`, {root: target.root});
    $('settings-clear-exports-dialog').close();
    notice(t('settings.exportsCleared', {title: target.title}), 'success');
    store.settingsStorageLoaded = false;
    await ensureStorage();
  } catch (error) {
    $('settings-clear-exports-error').textContent = error.message;
  } finally {
    submit.disabled = false;
  }
};

$('settings-folder-change').onclick = () => openFolder().then(() => {
  renderFolder();
}).catch(error => notice(error.message, 'error'));

$('settings-folder-use-default').onclick = async () => {
  try {
    await api('/api/library', {path: store.state.default_root, create: true});
    await nav.refresh();
    notice(t('folders.savingDefault'));
    renderFolder();
  } catch (error) {
    notice(error.message, 'error');
  }
};

$('settings-updates-auto').onchange = async event => {
  const enabled = event.target.checked;
  try {
    store.settingsUpdates = await api('/api/updates/prefs', {check: enabled ? 'auto' : 'manual'});
    notice(enabled ? t('settings.updatesAutoOn') : t('settings.updatesAutoOff'), 'success');
  } catch (error) {
    event.target.checked = !enabled;
    notice(error.message, 'error');
  }
};

$('settings-updates-check').onclick = () => checkForUpdatesManual();
$('settings-lang-en').onclick = () => setLang('en');
$('settings-lang-vi').onclick = () => setLang('vi');

$('settings-leftover-scan').onclick = async () => {
  $('settings-leftover-scan').disabled = true;
  try {
    store.settingsCleanup = await scanLeftovers();
    store.settingsCleanupLoaded = true;
    renderLeftovers();
    notice(t('settings.leftoverScanned'), 'success');
  } catch (error) {
    notice(error.message, 'error');
  } finally {
    $('settings-leftover-scan').disabled = false;
  }
};

$('settings-leftover-clean').onclick = async () => {
  const info = store.settingsCleanup;
  if (!info?.count) return;
  $('cleanup-confirm-body').textContent = t('cleanup.body', {size: formatBytes(info.bytes)});
  renderCleanupGroups($('cleanup-confirm-groups'), info.items);
  $('cleanup-confirm-error').textContent = '';
  $('cleanup-confirm-dialog').showModal();
};

$('cleanup-confirm-form').onsubmit = async event => {
  event.preventDefault();
  const submit = $('cleanup-confirm-submit');
  submit.disabled = true;
  try {
    const result = await runLeftoversClean();
    $('cleanup-confirm-dialog').close();
    notice(t('cleanup.freed', {size: formatBytes(result.freed_bytes || 0)}), 'success');
    store.settingsCleanup = await api('/api/cleanup');
    store.settingsCleanupLoaded = true;
    renderLeftovers();
  } catch (error) {
    $('cleanup-confirm-error').textContent = error.message;
  } finally {
    submit.disabled = false;
  }
};

$('settings-leftover-auto').onchange = async event => {
  const enabled = event.target.checked;
  try {
    const prefs = await api('/api/cleanup/prefs', {auto: enabled});
    if (store.settingsCleanup) store.settingsCleanup.prefs = prefs;
    notice(enabled ? t('settings.leftoverAutoOn') : t('settings.leftoverAutoOff'), 'success');
  } catch (error) {
    event.target.checked = !enabled;
    notice(error.message, 'error');
  }
};

onLangChange(() => {
  if (!dialogOpen()) return;
  renderLanguage();
  renderComponents();
  if (activeTab === 'about') renderAbout();
  if (activeTab === 'storage' && store.settingsStorageLoaded) {
    renderStorage();
    if (store.settingsCleanupLoaded) renderLeftovers();
  }
  if (activeTab === 'updates') renderUpdates();
});
