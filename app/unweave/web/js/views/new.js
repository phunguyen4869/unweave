import {AUDIO_EXTENSIONS} from '../constants.js';
import {$, el, notice, stem, api, sep, projectUrl, jobPending, findJob, queueBusy, token} from '../core.js';
import {store, nav} from '../store.js';
import {pickerValue, pickerValid} from '../picker.js';
import {renderProgress} from '../progress.js';
import {player} from '../audio.js';
import {TrimEditor, trimRequest, sectionText, formatClock} from '../trim.js';
import {t} from '../i18n.js';
/* ---------- new separation ---------- */
const TRIM_FIRST_KEY = 'unweave.youtubeTrimFirst';
try { $('yt-trim-first').checked = localStorage.getItem(TRIM_FIRST_KEY) !== '0'; } catch (_) { /* default stays on */ }
$('yt-trim-first').onchange = () => {
  try { localStorage.setItem(TRIM_FIRST_KEY, $('yt-trim-first').checked ? '1' : '0'); } catch (_) { /* per-viewer nicety only */ }
  renderNew();
};
/** The audio the Section editor trims: the chosen file, or a downloaded YouTube song. */
function trimSource() {
  return store.sourceMode === 'file' ? store.chosenFile : store.ytReady?.blob || null;
}
export function setSource(mode) {
  const changed = store.sourceMode !== mode;
  store.newTrimEditor?.stopPreview();
  store.sourceMode = mode;
  if (changed) {
    // File and YouTube each keep their own song; the editor follows the visible one.
    resetNewTrim();
    const source = trimSource();
    if (source) prepareNewTrim(source);
  }
  $('src-file').setAttribute('aria-selected', String(mode === 'file'));
  $('src-yt').setAttribute('aria-selected', String(mode === 'youtube'));
  $('pane-file').hidden = mode !== 'file'; $('pane-yt').hidden = mode !== 'youtube';
  renderNew();
}
$('src-file').onclick = () => setSource('file');
$('src-yt').onclick = () => setSource('youtube');
function resetNewTrim() {
  store.newTrimEpoch = (store.newTrimEpoch || 0) + 1;
  store.newTrimEditor?.destroy();
  store.newTrimEditor = null;
  store.newTrimRange = null;
  store.newTrimDuration = 0;
  store.newBuffer = null;
  $('new-trim-editor').replaceChildren();
  $('new-trim-chip').replaceChildren();
  $('new-trim-chip').hidden = true;
}
/** Decode `file` (a File or a downloaded Blob) for the Section editor. */
async function prepareNewTrim(file) {
  resetNewTrim();
  const epoch = store.newTrimEpoch;
  const url = URL.createObjectURL(file);
  const audio = new Audio();
  audio.preload = 'metadata';
  const detected = await new Promise(resolve => {
    audio.onloadedmetadata = () => resolve(audio.duration || 0);
    audio.onerror = () => resolve(0);
    audio.src = url;
  }).finally(() => URL.revokeObjectURL(url));
  let buffer = null;
  try { buffer = await player.ensureContext().decodeAudioData(await file.arrayBuffer()); } catch (_) { /* waveform is optional */ }
  if (epoch !== store.newTrimEpoch) return;
  store.newBuffer = buffer;
  const duration = buffer?.duration || detected || 0;
  store.newTrimDuration = Number.isFinite(duration) ? duration : 0;
  store.newTrimRange = store.newTrimDuration ? {start: 0, end: store.newTrimDuration} : null;
  renderNew();
}
export function chooseFile(file) {
  if (!file) return;
  const ext = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase();
  if (!AUDIO_EXTENSIONS.includes(ext)) { notice(t('new.notSupportedFile', {filename: file.name}), 'error'); return; }
  store.chosenFile = file; $('start-error').textContent = '';
  $('new-title').placeholder = stem(file.name).replaceAll('_', ' ');
  prepareNewTrim(file);
  renderNew();
}
$('audio-file').onchange = () => chooseFile($('audio-file').files[0]);
$('file-clear').onclick = () => { resetNewTrim(); store.chosenFile = null; $('audio-file').value = ''; $('new-title').placeholder = t('new.usesFileName'); renderNew(); };
const zone = $('dropzone');
zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragging'); });
zone.addEventListener('dragleave', () => zone.classList.remove('dragging'));
zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('dragging'); chooseFile(e.dataTransfer.files[0]); });
$('youtube-url').oninput = () => renderNew();
$('yt-ready-clear').onclick = () => {
  // The download is already a project; dismissing only skips separating it now.
  resetNewTrim();
  store.ytReady = null;
  renderNew();
};

function renderNewChip() {
  const chip = $('new-trim-chip');
  const range = store.newTrimRange;
  const duration = store.newTrimEditor?.duration || store.newTrimDuration;
  chip.replaceChildren();
  if (!range || !duration || (range.start <= 0.001 && range.end >= duration - 0.001)) {
    chip.hidden = true;
    return;
  }
  chip.hidden = false;
  chip.append(el('span', '', sectionText(range)));
  const clear = el('button', 'text-button', t('common.clear'));
  clear.type = 'button';
  clear.onclick = () => store.newTrimEditor?.setRange(0, duration);
  chip.append(clear);
}
function renderNewTrim() {
  const host = $('new-trim');
  const available = !!trimSource();
  host.hidden = !available;
  if (!available) return;
  const hint = $('new-trim-hint');
  if (!store.newTrimDuration) {
    hint.textContent = t('new.trim.readingDuration');
    $('new-trim-editor').replaceChildren();
    $('new-trim-chip').hidden = true;
    return;
  }
  hint.textContent = t('new.trim.optional');
  if (!store.newTrimEditor) {
    store.newTrimEditor = new TrimEditor($('new-trim-editor'), {
      duration: store.newTrimDuration,
      buffer: store.newBuffer,
      start: store.newTrimRange?.start ?? 0,
      end: store.newTrimRange?.end ?? store.newTrimDuration,
      onChange: range => { store.newTrimRange = range; renderNewChip(); },
    });
  }
  renderNewChip();
}
export function renderNew() {
  $('dropzone').hidden = !!store.chosenFile; $('file-card').hidden = !store.chosenFile;
  if (store.chosenFile) {
    $('file-name').textContent = store.chosenFile.name;
    $('file-meta').textContent = `${(store.chosenFile.size / 1048576).toFixed(1)} MB · ${(store.chosenFile.name.split('.').pop() || '').toUpperCase()}`;
  } else {
    $('new-title').placeholder = t('new.usesFileName');
  }
  $('root-label').textContent = store.state.root || t('common.noFolderSelected');
  $('root-label').title = store.state.root || '';
  const isDefault = store.state.root && store.state.root === store.state.default_root;
  $('root-default').hidden = !isDefault;
  $('folder-default').hidden = !store.state.default_root || isDefault;
  const name = store.sourceMode === 'file' ? (store.chosenFile ? stem(store.chosenFile.name) : t('new.placeholderSongName')) : t('new.placeholderVideoTitle');
  $('output-preview').textContent = store.state.root ? `→ ${store.state.root}${sep()}${name}${sep()}stems` : '';
  // The YouTube import this page started (or any one still in the queue).
  const pendingId = store.pending?.jobId || store.pending?.failed;
  const youtube = (pendingId && findJob(pendingId)) || (store.state.jobs || []).find(j => j.kind === 'youtube') || null;
  const showYt = !!youtube && (jobPending(youtube) || store.pending?.jobId === youtube.id || youtube.status === 'failed' && store.pending?.failed === youtube.id);
  $('yt-panel').hidden = !showYt;
  if (showYt) renderProgress($('yt-panel'), youtube);
  // YouTube support is optional in first-run setup, so offer it here when it was skipped.
  const ytMissing = !!store.state.setup?.stages?.find(s => s.id === 'youtube')?.missing;
  const ytSetup = (store.state.jobs || []).find(j => j.kind === 'setup' && (j.stages || []).includes('youtube'));
  $('yt-missing').hidden = !ytMissing;
  $('yt-install').disabled = !!ytSetup;
  $('yt-install').textContent = ytSetup ? t('youtube.installing', {pct: Math.floor(ytSetup.progress || 0)}) : t('youtube.install');
  const ytReady = store.ytReady;
  $('yt-link').hidden = !!ytReady;
  $('yt-ready').hidden = !ytReady;
  if (ytReady) {
    $('yt-ready-name').textContent = ytReady.title;
    $('yt-ready-meta').textContent = t('youtube.readyMeta', {duration: store.newTrimDuration ? formatClock(store.newTrimDuration, 0) : '…'});
  }
  const ready = store.sourceMode === 'file' ? !!store.chosenFile
    : !!ytReady || !ytMissing && /^https?:\/\/\S+/.test($('youtube-url').value.trim());
  // With "trim first" on, this click only downloads; separation waits for the trim.
  const downloadOnly = store.sourceMode === 'youtube' && !ytReady && $('yt-trim-first').checked;
  // A running job no longer blocks this page: the new one waits in the queue.
  $('start').disabled = !ready || !store.state.root || store.busy || !pickerValid($('new-stems'));
  $('start').textContent = store.busy ? t('start.starting') : downloadOnly ? t('start.download')
    : queueBusy() ? t('start.addToQueue') : t('start.button');
  // Queued jobs hold paths inside the current folder, so it stays put until they finish.
  $('folder-open').disabled = store.busy || queueBusy();
  $('folder-default').disabled = store.busy || queueBusy();
  renderNewTrim();
}
export function newFields() {
  return Object.fromEntries(['title', 'artist', 'album', 'year'].map(key => [key, $(`new-${key}`).value.trim()]));
}

export function upload(file, data) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const query = new URLSearchParams({...data, filename: file.name, root: store.state.root});
    xhr.open('POST', `/api/import?${query}`);
    xhr.setRequestHeader('X-Unweave-Token', token);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = e => {
      if (!e.lengthComputable) return;
      const pct = Math.round(e.loaded / e.total * 100);
      $('upload-progress').value = pct; $('upload-pct').textContent = `${pct}%`;
    };
    xhr.onload = () => { try { const result = JSON.parse(xhr.responseText); xhr.status === 200 ? resolve(result) : reject(new Error(result.error)); } catch (_) { reject(new Error(t('new.importFailed'))); } };
    xhr.onerror = () => reject(new Error(t('new.couldNotReachServer')));
    xhr.send(file);
  });
}
$('yt-install').onclick = async () => {
  $('yt-install').disabled = true;
  try { await api('/api/setup/start', {stages: ['youtube']}); await nav.refresh(); }
  catch (error) { notice(error.message, 'error'); renderNew(); }
};
$('start').onclick = async () => {
  if (store.busy) return;
  if (store.state.setup?.required) { notice(t('setup.completeFirst'), 'error'); return; }
  store.newTrimEditor?.stopPreview();
  const choice = pickerValue($('new-stems'));
  const trim = trimSource() ? trimRequest(store.newTrimRange, store.newTrimDuration) : null;
  store.busy = true; $('start-error').textContent = ''; renderNew();
  try {
    if (store.sourceMode === 'youtube' && store.ytReady) {
      const projectId = store.ytReady.project;
      await api(`${projectUrl(projectId)}/separate`, {root: store.state.root, ...choice, ...(trim ? {trim} : {})});
      resetNewTrim();
      store.ytReady = null;
      await nav.refresh(); nav.selectProject(projectId);
    } else if (store.sourceMode === 'file') {
      $('upload-box').hidden = false; $('upload-progress').value = 0; $('upload-pct').textContent = '0%';
      const project = await upload(store.chosenFile, newFields());
      await api(`${projectUrl(project.id)}/separate`, {root: store.state.root, ...choice, ...(trim ? {trim} : {})});
      resetNewTrim();
      store.chosenFile = null; $('audio-file').value = ''; for (const k of ['title', 'artist', 'album', 'year']) $(`new-${k}`).value = '';
      await nav.refresh(); nav.selectProject(project.id);
    } else {
      const job = await api('/api/import-youtube', {...newFields(), url: $('youtube-url').value.trim(), root: store.state.root});
      store.pending = {jobId: job.id, ...choice, trimFirst: $('yt-trim-first').checked};
      await nav.refresh();
    }
  } catch (error) { $('start-error').textContent = error.message; }
  finally { store.busy = false; $('upload-box').hidden = true; renderNew(); }
};
export async function continuePending() {
  const job = store.pending?.jobId && findJob(store.pending.jobId);
  if (!job) return;
  if (job.status === 'succeeded' && job.project && store.pending.trimFirst) {
    store.pending = null;
    $('youtube-url').value = '';
    await openYoutubeTrim(job.project);
  } else if (job.status === 'succeeded' && job.project) {
    const request = pendingRequest(store.pending);
    store.pending = null;
    $('youtube-url').value = '';
    try { await api(`${projectUrl(job.project)}/separate`, {root: store.state.root, ...request}); await nav.refresh(); nav.selectProject(job.project); }
    catch (error) { notice(error.message, 'error'); await nav.refresh(); nav.selectProject(job.project); }
  } else if (['failed', 'cancelled'].includes(job.status)) {
    store.pending = {failed: job.id};
  }
}

/** Park a finished download on this page with the Section editor, instead of
 *  separating it straight away. The project already exists in the Library. */
async function openYoutubeTrim(projectId) {
  const project = (store.state.projects || []).find(item => item.id === projectId);
  const title = project?.title || t('nav.defaultSongTitle');
  try {
    const response = await fetch(`${projectUrl(projectId)}/original?${new URLSearchParams({root: store.state.root})}`,
      {headers: {'X-Unweave-Token': token}});
    if (!response.ok) throw new Error(t('new.importFailed'));
    store.ytReady = {project: projectId, title, blob: await response.blob()};
  } catch (error) {
    notice(error.message, 'error');
    return;
  }
  if (store.sourceMode === 'youtube') prepareNewTrim(store.ytReady.blob);
  else renderNew();
  if (store.view !== 'new') notice(t('youtube.readyNotice', {title}), 'success');
}

/** A pending choice's separation fields, without the job bookkeeping around them. */
function pendingRequest({preset, stems, group, split}) {
  return {preset, stems, ...(group ? {group} : {}), ...(split ? {split: true} : {})};
}
