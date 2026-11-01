import {$, el, activeProject, jobPending, projectJob, findJob, queueBusy, api, notice, projectUrl, stemLabel} from '../core.js';
import {store, nav} from '../store.js';
import {renderProgress} from '../progress.js';
import {pickerValue, pickerValid, loadPlan} from '../picker.js';
import {loadAudio, player} from '../audio.js';
import {coverImage} from '../covers.js';
import {ORIGINAL_FILE, EXPORT_FORMATS} from '../constants.js';
import {TrimEditor, trimRequest, sectionText, formatClock} from '../trim.js';
import {t} from '../i18n.js';
function storedTrim(project, duration) {
  const trim = project.separation?.trim;
  if (!trim || typeof trim !== 'object') return null;
  const start = Number(trim.start);
  const end = Number(trim.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) return null;
  const clamped = {start: Math.min(start, duration), end: Math.min(end, duration)};
  return clamped.end > clamped.start ? clamped : null;
}

/** The plan that produced this song's stems, or null when it was a quick run.
 *  Only a plan that actually folded stems is worth remembering: everything else
 *  is exactly what the quick grid already expresses. */
function storedPlan(project) {
  const separation = project.separation || {};
  const group = Array.isArray(separation.group) ? separation.group : [];
  if (!group.length) return null;
  const stems = Array.isArray(separation.stems) ? separation.stems : [];
  return {
    stems: stems.filter(name => !group.includes(name)),
    group,
    split: Boolean(separation.lead_rhythm_split),
  };
}
function renderSongChip() {
  const chip = $('song-trim-chip');
  const range = store.songTrimRange;
  const duration = store.songTrimEditor?.duration || 0;
  chip.replaceChildren();
  if (!range || !duration || (range.start <= 0.001 && range.end >= duration - 0.001)) {
    chip.hidden = true;
    return;
  }
  chip.hidden = false;
  chip.append(el('span', '', sectionText(range)));
  const clear = el('button', 'text-button', t('common.clear'));
  clear.type = 'button';
  clear.onclick = () => store.songTrimEditor?.setRange(0, duration);
  chip.append(clear);
}
function renderSongTrim(project) {
  const host = $('song-trim');
  host.hidden = !project.original;
  if (!project.original) return;
  if (store.songTrimKey && !store.songTrimKey.startsWith(`${project.id}:`)) {
    store.songTrimEditor?.destroy();
    store.songTrimEditor = null;
    store.songTrimRange = null;
    store.songTrimKey = '';
    $('song-trim-editor').replaceChildren();
    $('song-trim-chip').replaceChildren();
    $('song-trim-chip').hidden = true;
  }
  const original = player.tracks.find(track => track.file === ORIGINAL_FILE);
  if (!original?.buffer) {
    $('song-trim-chip').hidden = true;
    if (!store.songTrimEditor) $('song-trim-editor').textContent = t('loading.originalWaveform');
    return;
  }
  const duration = original.buffer.duration;
  const trim = storedTrim(project, duration);
  const key = `${project.id}:${duration}:${trim ? `${trim.start}-${trim.end}` : 'full'}`;
  if (store.songTrimEditor && store.songTrimKey === key) {
    renderSongChip();
    return;
  }
  store.songTrimEditor?.destroy();
  $('song-trim-editor').replaceChildren();
  const range = trim || {start: 0, end: duration};
  store.songTrimRange = range;
  store.songTrimEditor = new TrimEditor($('song-trim-editor'), {
    duration,
    buffer: original.buffer,
    start: range.start,
    end: range.end,
    onChange: value => { store.songTrimRange = value; renderSongChip(); },
    onPreview: () => { if (player.playing || player.starting) player.pause(); },
  });
  store.songTrimKey = key;
  renderSongChip();
}
function exportOptions(host, items, checked, kind, translate) {
  host.replaceChildren(...items.map(([value, title, sub]) => {
    const label = el('label', `export-option export-${kind}`);
    const input = el('input');
    input.type = 'checkbox';
    input.value = value;
    input.checked = checked(value);
    const text = el('span', 'export-option-text');
    text.append(el('strong', '', translate ? t(title) : title), el('small', '', (translate ? t(sub || '') : sub) || ''));
    label.append(input, text);
    return label;
  }));
}
function openExportDialog(success = false) {
  const project = activeProject();
  if (!project) return;
  exportOptions($('export-formats'), EXPORT_FORMATS, value => value === 'flac', 'format', true);
  exportOptions($('export-stems'), project.stems.map(item => [item.file, stemLabel(item.file, item.name), '']), () => true, 'stem', false);
  const syncExportSubmit = () => {
    const formats = $('export-formats').querySelectorAll('input:checked').length;
    const stems = $('export-stems').querySelectorAll('input:checked').length;
    $('export-submit').disabled = !formats || !stems || jobPending(projectJob(project.id));
  };
  $('export-formats').onchange = syncExportSubmit;
  $('export-stems').onchange = syncExportSubmit;
  const stems = player.tracks.filter(track => track.file !== ORIGINAL_FILE);
  const start = stems.length ? Math.min(...stems.map(track => track.projectOffset ?? track.offset ?? 0)) : 0;
  const end = stems.length ? Math.max(...stems.map(track =>
    (track.projectOffset ?? track.offset ?? 0) + track.buffer.duration)) : 0;
  const trim = project.separation?.trim;
  const trimmed = trim && Number(trim.end) > Number(trim.start);
  const sectioned = stems.length > 0 && (start > 0 || trimmed);
  const sectionStart = start > 0 ? start : Math.max(0, Number(trim?.start) || 0);
  const sectionLength = end > start ? end - start : Math.max(0, Number(trim?.end) - Number(trim?.start) || 0);
  $('export-section-note').hidden = !sectioned;
  $('export-section-note').textContent = sectioned
    ? t('export.sectionNote', {length: sectionLength.toFixed(1), start: formatClock(sectionStart, 1)}) : '';
  $('export-success').hidden = !success;
  $('export-reveal').hidden = !success;
  $('export-clipping').checked = true;
  $('export-warning').hidden = true;
  $('export-error').textContent = '';
  syncExportSubmit();
  if (!$('export-dialog').open) $('export-dialog').showModal();
}
/* ---------- song view ---------- */
export function renderSong() {
  const project = activeProject();
  if (store.view !== 'song' || !project) return;
  $('title').textContent = project.title;
  coverImage(document.querySelector('.record-art'), project);
  $('artist').textContent = project.artist || t('common.unknownArtist');
  $('album').textContent = [project.album, project.year].filter(Boolean).join(' · ');
  $('source-name').textContent = project.original || t('song.noOriginalFile');
  $('project-warning').textContent = project.warnings.join(' ');
  $('project-warning').hidden = !project.warnings.length;
  // This song's own job; jobs for other songs only queue up behind it.
  const job = projectJob(store.selected);
  const busyHere = jobPending(job);
  const showJob = !!job && (busyHere || ['failed', 'cancelled'].includes(job.status));
  $('job-panel').hidden = !showJob;
  if (showJob) renderProgress($('job-panel'), job);
  const hasStems = project.stems.length > 0;
  const showPlayer = (hasStems || !!project.original) && !busyHere;
  $('mixer').hidden = !showPlayer;
  $('transport').hidden = !showPlayer;
  document.querySelector('.mixer .panel-sub').textContent = hasStems
    ? t('mixer.subWithOriginal')
    : t('mixer.subPreviewOriginal');
  $('resep-panel').hidden = busyHere || (hasStems && !store.resepOpen);
  $('resep-close').hidden = !hasStems;
  $('resep-title').textContent = hasStems ? t('song.separateAgain') : t('song.separateThisSong');
  $('separation-description').textContent = hasStems
    ? t('song.rerunReplaces')
    : t('song.notSeparatedYet');
  // Seed the picker from this song's saved plan once per song, so the polling
  // refresh never discards a plan the user is still editing.
  if (store.songPlanFor !== store.selected) {
    store.songPlanFor = store.selected;
    loadPlan($('song-stems'), storedPlan(project));
  }
  $('separate').disabled = !project.original || busyHere || !pickerValid($('song-stems'));
  $('separate').textContent = queueBusy() && !busyHere ? t('start.addToQueue') : hasStems ? t('song.separateAgain') : t('song.separateStemsButton');
  $('delete-open').disabled = busyHere;
  $('resep-open').disabled = busyHere;
  $('export-open').disabled = !hasStems || busyHere;
  document.querySelectorAll('[data-split-guitar]').forEach(button => { button.disabled = busyHere; });
  const exported = store.exportPending && findJob(store.exportPending.jobId);
  if (exported && exported.project === store.selected) {
    if (exported.status === 'succeeded' && store.exportOffered !== exported.id) {
      store.exportOffered = exported.id;
      store.exportPending = null;
      openExportDialog(true);
    } else if (['failed', 'cancelled'].includes(exported.status)) {
      store.exportPending = null;
    }
  }
  if (!busyHere && !$('resep-panel').hidden) renderSongTrim(project);
  const signature = JSON.stringify([store.state.root, project.id, project.stems, project.original]);
  if (signature !== store.audioSignature && !busyHere) {
    store.audioSignature = signature;
    loadAudio(project)
      .then(() => { if (store.view === 'song' && store.selected === project.id) renderSong(); })
      .catch(error => { if (error.name !== 'AbortError') notice(error.message, 'error'); });
  }
}
$('resep-open').onclick = () => { store.resepOpen = true; renderSong(); $('resep-panel').scrollIntoView({behavior: 'smooth', block: 'nearest'}); };
$('resep-close').onclick = () => { store.songTrimEditor?.stopPreview(); store.resepOpen = false; renderSong(); };
$('separate').onclick = async () => {
  if (!store.selected) return; $('separate').disabled = true; store.songTrimEditor?.stopPreview();
  const trim = trimRequest(store.songTrimRange, store.songTrimEditor?.duration || 0);
  try {
    await api(`${projectUrl(store.selected)}/separate`, {
      root: store.state.root, ...pickerValue($('song-stems')), ...(trim ? {trim} : {}),
    });
    store.resepOpen = false;
    await nav.refresh();
  } catch (error) { notice(error.message, 'error'); renderSong(); }
};
$('reveal').onclick = () => api(`${projectUrl(store.selected)}/reveal`, {root: store.state.root, target: 'project'}).catch(e => notice(e.message, 'error'));
$('export-open').onclick = () => openExportDialog(false);
$('export-clipping').onchange = () => { $('export-warning').hidden = $('export-clipping').checked; };
$('export-reveal').onclick = () => api(`${projectUrl(store.selected)}/reveal`, {root: store.state.root, target: 'exports'}).catch(e => notice(e.message, 'error'));
$('export-form').onsubmit = async event => {
  event.preventDefault();
  if (!store.selected || jobPending(projectJob(store.selected))) return;
  const formats = [...$('export-formats').querySelectorAll('input:checked')].map(input => input.value);
  const stems = [...$('export-stems').querySelectorAll('input:checked')].map(input => input.value);
  if (!formats.length) { $('export-error').textContent = t('export.chooseFormat'); return; }
  if (!stems.length) { $('export-error').textContent = t('export.chooseStem'); return; }
  $('export-submit').disabled = true;
  try {
    const job = await api(`${projectUrl(store.selected)}/export`, {
      root: store.state.root, formats, stems, prevent_clipping: $('export-clipping').checked,
    });
    store.exportPending = {jobId: job.id, project: store.selected};
    $('export-dialog').close();
    await nav.refresh();
  } catch (error) {
    $('export-error').textContent = error.message;
    $('export-submit').disabled = false;
  }
};

