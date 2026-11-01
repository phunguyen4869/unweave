import {STEMS, DEFAULT_STEMS} from './constants.js';
import {$, el} from './core.js';
import {nav} from './store.js';
import {t, onLangChange} from './i18n.js';
import {fromRequest, fromSelection, describePlan} from './plan-model.js';
import {openPlanDialog} from './plan.js';

/* ---------- stem picker ----------
   Two modes share one container: the quick grid, and an advanced plan whose
   detail lives in the plan dialog. `plans` holds the confirmed request per
   container so the summary line and the request payload stay in sync. */
const plans = new Map();

const PRESETS = [['custom', 'picker.customTitle', 'picker.customSub'],
  ['vocals', 'picker.vocalsPresetTitle', 'picker.vocalsPresetSub']];

export function buildPicker(container) {
  container.replaceChildren();
  const presets = el('div', 'preset-cards');
  for (const [value, title, sub] of PRESETS) {
    const label = el('label', 'preset-card');
    const input = el('input');
    input.type = 'radio';
    input.name = `${container.id}-preset`;
    input.value = value;
    input.checked = value === 'custom';
    label.append(input, el('strong', '', t(title)), el('small', '', t(sub)));
    presets.append(label);
  }
  const grid = el('fieldset', 'stem-grid');
  grid.append(el('legend', 'sr-only', t('picker.selectStemsLegend')));
  for (const [value, name, color] of STEMS) {
    const label = el('label', 'stem-option');
    label.style.setProperty('--c', color);
    const input = el('input');
    input.type = 'checkbox';
    input.value = value;
    input.checked = DEFAULT_STEMS.includes(value);
    label.append(input, el('span', 'stem-dot'), el('span', 'stem-label', t(name)));
    grid.append(label);
  }
  const help = el('p', 'hint', t('picker.hint', {other: t('stem.other')}));
  container.append(presets, grid, help, advancedRow(), openRow());
  container.onchange = () => { syncPicker(container); nav.render(); };
  container.querySelector('[data-plan-open]').onclick = () => editPlan(container);
  container.querySelector('[data-plan-clear]').onclick = () => { plans.delete(container.id); syncPicker(container); nav.render(); };
  syncPicker(container);
  onLangChange(() => translatePicker(container));
}

function openRow() {
  const row = el('div', 'plan-open-row');
  const button = el('button', 'btn btn-ghost btn-sm', t('plan.open'));
  button.type = 'button';
  button.dataset.planOpen = '';
  row.append(button);
  return row;
}

function advancedRow() {
  const row = el('div', 'plan-summary');
  row.hidden = true;
  const text = el('p', 'plan-summary-text');
  const edit = el('button', 'btn btn-ghost btn-sm', t('plan.edit'));
  edit.type = 'button';
  edit.dataset.planEdit = '';
  const clear = el('button', 'btn btn-ghost btn-sm', t('plan.toQuick'));
  clear.type = 'button';
  clear.dataset.planClear = '';
  row.append(text, edit, clear);
  return row;
}

async function editPlan(container) {
  const current = plans.get(container.id);
  const initial = current ? fromRequest(current) : fromSelection(quickSelection(container));
  const request = await openPlanDialog({initial, title: t('plan.title')});
  if (!request) return;
  plans.set(container.id, request);
  syncPicker(container);
  nav.render();
}

function quickSelection(container) {
  return [...container.querySelectorAll('.stem-grid input:checked')].map(input => input.value);
}

function summaryText(request) {
  const described = describePlan(fromRequest(request));
  return t('plan.summary', {own: described.ownCount, grouped: described.members.length});
}

function translatePicker(container) {
  container.querySelectorAll('.preset-card').forEach((label, i) => {
    label.querySelector('strong').textContent = t(PRESETS[i][1]);
    label.querySelector('small').textContent = t(PRESETS[i][2]);
  });
  container.querySelector('.stem-grid legend').textContent = t('picker.selectStemsLegend');
  container.querySelectorAll('.stem-option').forEach((label, i) => {
    label.querySelector('.stem-label').textContent = t(STEMS[i][1]);
  });
  container.querySelector('.hint').textContent = t('picker.hint', {other: t('stem.other')});
  container.querySelector('[data-plan-open]').textContent = t('plan.open');
  container.querySelector('[data-plan-edit]').textContent = t('plan.edit');
  container.querySelector('[data-plan-clear]').textContent = t('plan.toQuick');
  const request = plans.get(container.id);
  if (request) container.querySelector('.plan-summary-text').textContent = summaryText(request);
}

export function syncPicker(container) {
  const request = plans.get(container.id);
  const advanced = Boolean(request);
  const custom = container.querySelector('input[type=radio]:checked').value === 'custom';
  container.querySelector('.preset-cards').hidden = advanced;
  container.querySelector('.stem-grid').hidden = advanced || !custom;
  container.querySelector('.hint').hidden = advanced || !custom;
  container.querySelector('.plan-open-row').hidden = advanced;
  const summary = container.querySelector('.plan-summary');
  summary.hidden = !advanced;
  if (advanced) {
    summary.querySelector('.plan-summary-text').textContent = summaryText(request);
    summary.querySelector('[data-plan-edit]').onclick = () => editPlan(container);
  }
}

/** Seed a container from a project's saved plan; null returns it to the quick grid. */
export function loadPlan(container, request) {
  if (request) plans.set(container.id, request);
  else plans.delete(container.id);
  syncPicker(container);
}

export function pickerValue(container) {
  const request = plans.get(container.id);
  if (request) return {preset: 'custom', ...request};
  return {
    preset: container.querySelector('input[type=radio]:checked').value,
    stems: quickSelection(container),
  };
}

export function pickerValid(container) {
  const value = pickerValue(container);
  if (value.group) return value.stems.length + value.group.length > 0;
  return value.preset === 'vocals' || value.stems.length > 0;
}

buildPicker($('new-stems'));
buildPicker($('song-stems'));
