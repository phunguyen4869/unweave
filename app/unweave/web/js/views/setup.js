import {$, el, api, notice, jobRunning} from '../core/core.js';
import {store, nav} from '../core/store.js';
import {t} from '../core/i18n.js';
import {STAGE_ICONS, sizeText, speedText} from '../features/components.js';
import {copyDiagnostics, openFacebook, openGitHubIssues} from '../features/diagnostics.js';
/* ---------- first-run setup ---------- */
// How much of the overall 0-100 progress each running stage gets, in the same order
// backend setup.py allocated bands (STAGE_ORDER, filtered to what was actually
// requested) — matches run_setup()'s `band = (100 - FINALIZE_BAND) // len(missing)`
// exactly, so a stage's own 0-100% can be derived client-side from the one shared
// job.progress number without the backend needing to report per-stage percentages.
const SETUP_FINALIZE_BAND = 10;

export function stageProgress(stageId, job) {
  const index = store.setupRunningStages.indexOf(stageId);
  if (index === -1) return null;
  const band = Math.floor((100 - SETUP_FINALIZE_BAND) / Math.max(1, store.setupRunningStages.length));
  const start = index * band;
  if (job.progress >= start + band) return 100;
  if (job.progress <= start) return 0;
  return Math.round((job.progress - start) / band * 100);
}
export function renderSetup() {
  const setup = store.state.setup; if (!setup) return;
  const list = $('setup-list'); list.replaceChildren();
  let total = 0;
  const job = store.state.job;
  const running = job && job.kind === 'setup' && ['running', 'cancelling'].includes(job.status);
  // setupRunningStages is normally set when the "Download & install" click fires, but a
  // page reload (or anything else landing here) while a setup job is already running
  // would otherwise leave every row unable to compute its share of progress — rebuild it
  // from the stages currently reported missing, same order, same filter the backend uses.
  if (running && !store.setupRunningStages.length) {
    // Best-effort reconstruction — the user's original optional-YouTube choice isn't
    // recoverable after a reload, so default to "most people leave it unchecked" (just
    // the required stages), but always include whichever stage the job reports as
    // currently active even if optional, since it's clearly part of this run.
    store.setupRunningStages = setup.stages.filter(s => s.missing && (s.required || s.id === job?.stage)).map(s => s.id);
  }
  for (const stage of setup.stages) {
    const optional = !stage.required && !stage.done;
    const included = !optional || store.setupYoutube;
    if (stage.missing && included) total += stage.size_mb;
    const pct = running ? stageProgress(stage.id, job) : null;
    const isDone = stage.done || pct === 100;
    const isActive = running && !isDone && (job?.stage === stage.id || (pct !== null && pct > 0));
    const isQueued = running && !isDone && !isActive && pct === 0;
    const state = isDone ? 'done' : isActive ? 'active' : isQueued ? 'queued' : included ? 'pending' : 'off';
    // An optional item is a <label>, so a click anywhere on its card flips the switch.
    const card = el(optional && !running ? 'label' : 'div', `setup-tile setup-tile--${state}`);
    card.dataset.stage = stage.id;
    const chip = isDone ? ['done', `✓ ${t('setup.chip.installed')}`]
      : isActive ? ['active', t('setup.chip.installing')]
      : isQueued ? ['queued', t('setup.chip.queued')]
      : stage.required ? ['required', t('setup.chip.required')] : ['optional', t('setup.chip.optional')];
    const icon = el('span', 'setup-tile-icon');
    icon.innerHTML = STAGE_ICONS[stage.id] || STAGE_ICONS.runtime;
    const top = el('div', 'setup-tile-top');
    top.append(icon, el('span', `setup-chip setup-chip--${chip[0]}`, chip[1]));
    const name = el('strong', 'setup-tile-name', t(`setup.name.${stage.id}`));
    const desc = el('p', 'setup-tile-desc', t(`setup.desc.${stage.id}`));
    const foot = el('div', 'setup-tile-foot');
    foot.append(el('span', 'setup-tile-size', isDone ? t('setup.readyToUse') : `~${sizeText(stage.size_mb)}`));
    if (optional) {
      const toggle = el('span', 'setup-switch');
      const input = el('input');
      input.type = 'checkbox';
      input.checked = store.setupYoutube;
      input.disabled = running;
      input.setAttribute('aria-label', t('setup.include'));
      input.onchange = () => { store.setupYoutube = input.checked; renderSetup(); };
      toggle.append(input, el('span', 'setup-switch-track'), el('span', 'setup-switch-text', t('setup.include')));
      foot.append(toggle);
    }
    card.append(top, name, desc, foot);
    list.append(card);
  }
  const speed = running ? speedText(job.download_speed) : '';
  const totalEl = $('setup-total');
  totalEl.textContent = running
    ? (speed
      ? t('setup.installingSpeed', {pct: Math.floor(job.progress), speed})
      : t('setup.installing', {pct: Math.floor(job.progress)}))
    : t('setup.totalSummary', {total: sizeText(total)});
  totalEl.classList.toggle('is-busy', running);
  const activity = $('setup-activity');
  if (running) {
    const phase = ['download', 'install', 'prepare', 'finalize'].includes(job.phase) ? job.phase : 'install';
    activity.hidden = false;
    activity.textContent = speed
      ? t('setup.activity.downloadSpeed', {speed})
      : t(`setup.activity.${phase}`);
  } else {
    activity.hidden = true;
    activity.textContent = '';
  }
  const overall = $('setup-overall-bar').parentElement;
  overall.hidden = !running;
  overall.classList.toggle('is-busy', running);
  $('setup-overall-bar').style.width = `${running ? Math.floor(job.progress) : 0}%`;
  const failed = job && job.kind === 'setup' && job.status === 'failed';
  const logPanel = $('setup-log');
  const logBody = $('setup-log-body');
  const logs = (running || failed) ? (job.logs || []) : [];
  if ((running || failed) && logs.length) {
    logPanel.hidden = false;
    const text = logs.join('\n');
    const nearBottom = logBody.scrollHeight - logBody.scrollTop - logBody.clientHeight < 40;
    if (logBody.textContent !== text) {
      logBody.textContent = text;
      if (nearBottom) logBody.scrollTop = logBody.scrollHeight;
    }
  } else if (!running && !failed) {
    logPanel.hidden = true;
    logBody.textContent = '';
  }
  const report = $('setup-report');
  report.hidden = !failed;
  $('setup-error').textContent = failed ? (job.error || t('setup.failed')) : '';
  const requiredMissing = setup.stages.some(s => s.required && s.missing);
  $('setup-start').disabled = !requiredMissing || running;
  $('setup-start').hidden = running;
  $('setup-decline').hidden = running;
  $('setup-cancel').hidden = !running;
  $('setup-cancel').disabled = job?.status === 'cancelling';
}
export function renderSetupBanner() {
  const banner = $('setup-banner');
  if (store.state.setup?.required && !store.setupDeclined && store.view !== 'setup') banner.hidden = false;
  else banner.hidden = true;
}
export function renderSetupView() {
  const job = store.state.job;
  if (job && !['running', 'cancelling'].includes(job.status) && store.setupJobAnnounced !== job.id) {
    if (job.status === 'failed') { notice(job.error || t('setup.failed'), 'error'); store.setupJobAnnounced = job.id; }
    if (job.status === 'succeeded') { store.setupRunningStages = []; }
    store.setupJobAnnounced = job.id;
  }
}
$('setup-banner-open').onclick = () => nav.show('setup');
$('setup-decline').onclick = () => { store.setupDeclined = true; nav.render(); nav.show('new'); };
$('setup-start').onclick = async () => {
  if (store.busy || jobRunning()) return;
  const stages = store.state.setup.stages.filter(s => s.missing && (s.required || s.id === 'youtube' && store.setupYoutube)).map(s => s.id);
  store.setupRunningStages = stages;  // same order/filter the backend uses for its progress bands
  $('setup-error').textContent = '';
  $('setup-report').hidden = true;
  try {
    await api('/api/setup/start', {stages});
    await nav.refresh();
  } catch (error) { store.setupRunningStages = []; $('setup-error').textContent = error.message; }
};
$('setup-cancel').onclick = () => api('/api/cancel', {}).then(nav.refresh).catch(e => notice(e.message, 'error'));
$('setup-copy-report').onclick = async () => {
  try { await copyDiagnostics(store.state.job?.kind === 'setup' ? store.state.job.id : undefined); }
  catch (error) { notice(error.message, 'error'); }
};
$('setup-github-issues').onclick = () => {
  openGitHubIssues().catch(error => notice(error.message, 'error'));
};
$('setup-facebook').onclick = () => {
  openFacebook().catch(error => notice(error.message, 'error'));
};
