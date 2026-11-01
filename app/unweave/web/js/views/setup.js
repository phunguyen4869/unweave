import {SETUP_STAGE_FULL_LABEL} from '../constants.js';
import {$, el, api, notice, jobRunning} from '../core.js';
import {store, nav} from '../store.js';
import {t} from '../i18n.js';
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
    if (stage.missing) total += stage.size_mb;
    const row = el('label', 'setup-row');
    const input = el('input'); input.type = 'checkbox';
    input.disabled = stage.required || stage.done || running;
    input.checked = stage.required || stage.done;
    if (!stage.required && !stage.done) {
      input.checked = store.setupYoutube;
      input.onchange = () => { store.setupYoutube = input.checked; };
    }
    const pct = running ? stageProgress(stage.id, job) : null;
    const isDone = stage.done || pct === 100;
    const isActive = running && pct !== null && pct > 0 && pct < 100;
    const isQueued = running && pct === 0;
    let icon = '↓', cls = 'setup-status--missing';
    if (isDone) { icon = '✓'; cls = 'setup-status--done'; }
    else if (isActive || job?.stage === stage.id) { icon = `${pct ?? 0}%`; cls = 'setup-status--active'; }
    else if (isQueued) { icon = '⋯'; cls = 'setup-status--queued'; }
    row.classList.toggle('setup-row--active', isActive || (running && job?.stage === stage.id));
    row.classList.toggle('setup-row--done', isDone);
    const status = el('span', `setup-status ${cls}`, icon);
    const labelKey = SETUP_STAGE_FULL_LABEL[stage.id];
    const label = labelKey ? t(labelKey) : stage.label;
    row.append(input, status, el('span', 'setup-row-label', label), el('span', 'setup-row-size', `~${stage.size_mb} MB`));
    if (isActive || (running && job?.stage === stage.id)) {
      const bar = el('div', 'setup-row-bar'); const fill = el('i'); fill.style.width = `${pct ?? 0}%`; bar.append(fill);
      row.append(bar);
    }
    list.append(row);
  }
  $('setup-total').textContent = running
    ? t('setup.installing', {pct: Math.floor(job.progress)})
    : t('setup.totalSummary', {total});
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
  try {
    await api('/api/setup/start', {stages});
    await nav.refresh();
  } catch (error) { store.setupRunningStages = []; $('setup-error').textContent = error.message; }
};
$('setup-cancel').onclick = () => api('/api/cancel', {}).then(nav.refresh).catch(e => notice(e.message, 'error'));
