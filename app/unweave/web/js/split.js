import {$, el, notice, api, projectUrl, jobPending, projectJob} from './core.js';
import {store, nav} from './store.js';
import {TrimEditor, trimRequest, sectionText} from './trim.js';
import {t} from './i18n.js';

function renderChip(offset) {
  const chip = $('split-chip');
  const range = store.splitRange;
  const duration = store.splitEditor?.duration || 0;
  chip.replaceChildren();
  if (!range || !duration || (range.start <= 0.001 && range.end >= duration - 0.001)) {
    chip.hidden = true;
    return;
  }
  chip.hidden = false;
  chip.append(el('span', '', sectionText(range, offset)));
}

export function openSplitDialog(projectId, track) {
  store.splitEditor?.destroy();
  store.splitEditor = null;
  $('split-trim').replaceChildren();
  $('split-error').textContent = '';
  $('split-submit').disabled = false;
  const offset = track.projectOffset ?? track.offset ?? 0;
  const duration = track.buffer.duration;
  store.splitProject = projectId;
  store.splitRange = {start: 0, end: duration};
  store.splitEditor = new TrimEditor($('split-trim'), {
    duration,
    buffer: track.buffer,
    displayOffset: offset,
    start: 0,
    end: duration,
    hint: t('split.hint'),
    onChange: range => { store.splitRange = range; renderChip(offset); },
  });
  renderChip(offset);
  if (!$('split-dialog').open) $('split-dialog').showModal();
}

$('split-dialog').addEventListener('close', () => store.splitEditor?.stopPreview());

$('split-form').onsubmit = async event => {
  event.preventDefault();
  if (!store.splitProject || jobPending(projectJob(store.splitProject))) return;
  const duration = store.splitEditor?.duration || 0;
  const offset = store.splitEditor?.displayOffset || 0;
  const trim = trimRequest(store.splitRange, duration)
    || (offset > 0 ? {start: 0, end: Number(duration.toFixed(3))} : null);
  $('split-submit').disabled = true;
  try {
    await api(`${projectUrl(store.splitProject)}/split-guitar`, {
      root: store.state.root, ...(trim ? {trim} : {}),
    });
    store.splitEditor?.stopPreview();
    $('split-dialog').close();
    notice();
    await nav.refresh();
  } catch (error) {
    $('split-error').textContent = error.message;
    $('split-submit').disabled = false;
  }
};

