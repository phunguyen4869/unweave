/* Stem-plan diagram for the advanced separation dialog.
   Rendering only: every rule lives in plan-model.js and every colour in plan.css,
   so this file holds no policy and no colour literals. */
import {PLAN_META, STEMS, LEAVES} from './constants.js';
import {t} from './i18n.js';
import {clone, createPlan, describePlan, isGrouped, setEnabled,
  setGrouped, setSplit, steps, toRequest, warnings} from './plan-model.js';

const M = {
  root: {w: 118, h: 40},
  stem: {w: 150, h: 38},
  act: {w: 100, h: 26},
  leaf: {w: 156, h: 30},
  group: {w: 128},
  groupHead: 27,
  groupRow: 22,
  groupGap: 3,
  groupPad: 3,
  groupBorder: 2,
  groupEmpty: 27,
  // Room for the curve to land. A 16px gap left the S-bend no horizontal
  // travel, so the wire read as a cramped vertical squiggle.
  colGap: 38,
  rowGap: 14,
  actGap: 8,
  flowStagger: 0.19,
  flowCycles: 9,
};

const COLUMN_KEYS = {
  wide: ['root', 'stem', 'act', 'leaf', 'leafAct', 'group'],
  narrow: ['root', 'stem', 'act', 'group'],
};
const COLUMN_WIDTH = {root: M.root.w, stem: M.stem.w, act: M.act.w,
  leaf: M.leaf.w, leafAct: M.act.w, group: M.group.w};

const el = (tag, className, html) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (html != null) node.innerHTML = html;
  return node;
};
const label = id => t(PLAN_META[id].key);
const accent = id => PLAN_META[id].color;

/** Publish the one colour source (constants.js) as CSS variables, so the SVG
 *  strokes can reference var(--node-vocals) and no literal lives in this file. */
function applyNodeTokens() {
  const stage = document.getElementById('plan-stage');
  if (!stage || stage.dataset.tokens) return;
  for (const [id, , color] of [...STEMS, ...LEAVES]) {
    stage.style.setProperty(`--node-${id}`, color);
  }
  stage.dataset.tokens = '1';
}

/* ---------------- graph ---------------- */
function columnLayout(hasLeaves) {
  const columns = {};
  let x = 0;
  for (const key of hasLeaves ? COLUMN_KEYS.wide : COLUMN_KEYS.narrow) {
    columns[key] = {x, w: COLUMN_WIDTH[key]};
    x += COLUMN_WIDTH[key] + M.colGap;
  }
  columns.width = x - M.colGap;
  return columns;
}

function buildGraph(plan) {
  const described = describePlan(plan);
  const columns = columnLayout(described.split);
  const nodes = new Map();

  nodes.set('root', {id: 'root', kind: 'root', ...columns.root, h: M.root.h,
    label: t('plan.original'), parents: []});

  for (const id of STEMS.map(([value]) => value)) {
    nodes.set(id, {id, kind: 'stem', ...columns.stem, h: M.stem.h,
      label: label(id), color: accent(id), parents: ['root']});
  }

  const actions = [...described.enabled.filter(id => id !== 'other'), ...described.leaves];
  for (const id of actions) {
    const column = described.leaves.includes(id) ? columns.leafAct : columns.act;
    nodes.set(`act:${id}`, {id: `act:${id}`, kind: 'act', action: 'merge', target: id,
      ...column, h: M.act.h, parents: [id], order: 0});
  }
  if (described.enabled.includes('guitar')) {
    nodes.set('split', {id: 'split', kind: 'act', action: 'split',
      ...columns.act, h: M.act.h, parents: ['guitar'], order: 1});
  }

  for (const id of described.leaves) {
    nodes.set(id, {id, kind: 'leaf', ...columns.leaf, h: M.leaf.h,
      label: label(id), color: accent(id), sub: t(`plan.sub.${id}`), parents: ['split']});
  }

  nodes.set('group', {id: 'group', kind: 'group', ...columns.group, h: 0,
    members: described.members, parents: []});

  return {nodes, width: columns.width, height: 0, described};
}

/* ---------------- layout ---------------- */
const stackFor = (nodes, id) => [nodes.get(`act:${id}`), id === 'guitar' ? nodes.get('split') : null]
  .filter(Boolean)
  .sort((a, b) => a.order - b.order);

// The group's height must cover its own 1px border: nodes are border-box, so an
// off-by-border would clip the last row.
const groupHeight = rows => (rows
  ? M.groupHead + M.groupPad * 2 + rows * M.groupRow + (rows - 1) * M.groupGap
  : M.groupEmpty) + M.groupBorder;

function layoutStemColumn(nodes) {
  let cursor = 0;
  for (const [id] of STEMS) {
    const stem = nodes.get(id);
    const stack = stackFor(nodes, id);
    const stackHeight = stack.length ? stack.length * M.act.h + (stack.length - 1) * M.actGap : 0;
    const slot = Math.max(M.stem.h, stackHeight);
    stem.top = cursor + (slot - M.stem.h) / 2;
    let top = cursor + (slot - stackHeight) / 2;
    for (const action of stack) {
      action.top = top;
      top += M.act.h + M.actGap;
    }
    cursor += slot + M.rowGap;
  }
}

function layoutLeaves(nodes) {
  const split = nodes.get('split');
  const leaves = LEAVES.map(([id]) => nodes.get(id)).filter(Boolean);
  if (!split || !leaves.length) return;
  const total = leaves.length * M.leaf.h + (leaves.length - 1) * M.actGap;
  let top = split.top + M.act.h / 2 - total / 2;
  for (const leaf of leaves) {
    leaf.top = top;
    const merge = nodes.get(`act:${leaf.id}`);
    if (merge) merge.top = top + (M.leaf.h - M.act.h) / 2;
    top += M.leaf.h + M.actGap;
  }
}

function layoutGroup(nodes) {
  const group = nodes.get('group');
  const body = [...nodes.values()].filter(node => node.kind !== 'group' && node.kind !== 'root');
  group.h = groupHeight(group.members.length);
  const top = Math.min(...body.map(node => node.top));
  const bottom = Math.max(...body.map(node => node.top + node.h));
  group.top = (top + bottom) / 2 - group.h / 2;
}

function snapToPixels(nodes) {
  const placed = [...nodes.values()].filter(node => node.kind !== 'root');
  const shift = -Math.min(...placed.map(node => node.top));
  for (const node of placed) node.top = Math.round(node.top + shift);
}

function placeRoot(nodes) {
  const root = nodes.get('root');
  const first = nodes.get(STEMS[0][0]);
  const last = nodes.get(STEMS[STEMS.length - 1][0]);
  const middle = (first.top + last.top + M.stem.h) / 2;
  root.top = Math.round(middle - M.root.h / 2);
}

function finishCentres(nodes) {
  for (const node of nodes.values()) node.cy = node.top + node.h / 2;
}

function layout(graph) {
  const {nodes} = graph;
  layoutStemColumn(nodes);
  layoutLeaves(nodes);
  layoutGroup(nodes);
  // The root is deliberately placed after the shift, from final stem positions.
  snapToPixels(nodes);
  placeRoot(nodes);
  finishCentres(nodes);
  graph.height = Math.max(...[...nodes.values()].map(node => node.top + node.h));
}

/* ---------------- nodes ---------------- */
const NODE_RENDERERS = {
  root: renderRoot,
  stem: renderStem,
  leaf: renderLeaf,
  group: renderGroup,
  act: renderAction,
};

const place = (node, geometry) => {
  Object.assign(node.style, {
    left: `${geometry.x}px`,
    top: `${geometry.top}px`,
    width: `${geometry.w}px`,
    height: `${geometry.h}px`,
  });
  if (geometry.color) node.style.setProperty('--c', geometry.color);
};

function renderRoot(spec) {
  return el('div', 'plan-node plan-root',
    `<span class="plan-dot"></span>
     <span class="plan-name">${spec.label}</span>`);
}

function renderStem(spec, plan, commit) {
  const state = !plan.enabled.has(spec.id) ? 'off'
    : isGrouped(plan, spec.id) ? 'grouped' : 'on';
  const auto = spec.id === 'other';
  const flag = state === 'grouped'
    ? `<span class="plan-flag other">${t(auto ? 'plan.badgeAuto' : 'plan.badgeGrouped')}</span>`
    : state === 'off' ? `<span class="plan-flag off">${t('plan.badgeDisabled')}</span>` : '';
  const node = el('button', 'plan-node plan-stem',
    `<span class="plan-dot"></span><span class="plan-name">${spec.label}</span>${flag}`);
  node.type = 'button';
  node.dataset.state = state;
  node.setAttribute('aria-pressed', String(plan.enabled.has(spec.id)));
  node.setAttribute('aria-label',
    `${spec.label}, ${t(`plan.state.${state}`)}`);
  node.title = t(state === 'off' ? 'plan.titleOff'
    : auto ? 'plan.titleAuto'
      : state === 'grouped' ? 'plan.titleGrouped' : 'plan.titleOn');
  node.onclick = () => commit(setEnabled(plan, spec.id, state === 'off'));
  return node;
}

function renderLeaf(spec, plan) {
  const grouped = plan.grouped.has(spec.id);
  // A leaf is the product of the split, not an input: it is never clickable.
  const node = el('div', 'plan-node plan-leaf',
    `<span class="plan-dot"></span><span class="plan-name">${spec.label}</span>
     ${grouped ? '' : `<span class="plan-sub">${spec.sub}</span>`}
     ${grouped ? `<span class="plan-flag other">${t('plan.badgeGrouped')}</span>` : ''}`);
  node.dataset.state = grouped ? 'grouped' : 'on';
  node.setAttribute('role', 'img');
  node.setAttribute('aria-label', `${spec.label}, ${t(grouped ? 'plan.state.grouped' : 'plan.state.on')}`);
  node.title = t(grouped ? 'plan.titleLeafGrouped' : 'plan.titleLeaf');
  return node;
}

function groupRow(id) {
  const row = el('div', 'plan-group-row',
    `<span class="plan-dot"></span><span class="plan-name">${label(id)}</span>`);
  row.style.setProperty('--c', accent(id));
  if (id === 'other') {
    row.append(el('span', 'plan-lock', t('plan.auto')));
  } else {
    const eject = el('button', 'plan-eject', '↩');
    eject.type = 'button';
    eject.dataset.unmerge = id;
    eject.title = t('plan.unmerge', {stem: label(id)});
    eject.setAttribute('aria-label', t('plan.unmerge', {stem: label(id)}));
    row.append(eject);
  }
  return row;
}

function renderGroup(spec, plan, commit) {
  const node = el('div', 'plan-node plan-group');
  const head = el('div', 'plan-group-head',
    `<span class="plan-dot"></span>${t('plan.otherFile')}
     <span class="plan-count">${spec.members.length}</span>`);
  const rows = el('div', 'plan-group-rows');
  rows.append(...spec.members.map(groupRow));
  node.append(head, rows);
  node.onclick = event => {
    const button = event.target.closest('[data-unmerge]');
    if (button) commit(setGrouped(plan, button.dataset.unmerge, false));
  };
  return node;
}

function renderAction(spec, plan, commit) {
  if (spec.action === 'split') return renderSplit(spec, plan, commit);
  const merged = plan.grouped.has(spec.target);
  const node = el('button', `plan-node plan-act${merged ? ' is-on' : ''}`,
    `<span class="plan-name">${t(merged ? 'plan.unmergeShort' : 'plan.mergeShort')}</span>`);
  node.type = 'button';
  node.setAttribute('aria-pressed', String(merged));
  node.setAttribute('aria-label', t(merged ? 'plan.unmerge' : 'plan.merge', {stem: label(spec.target)}));
  node.onclick = () => commit(setGrouped(plan, spec.target, !merged));
  return node;
}

function renderSplit(spec, plan, commit) {
  const on = plan.split;
  // The label stays "Split" whether it is on or off: colour and aria-pressed
  // carry the state, and a changing label would not fit the column.
  const node = el('button', `plan-node plan-act plan-split${on ? ' is-on' : ''}`,
    `<span class="plan-name">${t('plan.split')}</span>
     <span class="plan-key">2×</span>`);
  node.type = 'button';
  node.setAttribute('aria-pressed', String(on));
  node.setAttribute('aria-label', t('plan.split'));
  node.title = t(on ? 'plan.splitTitleOn' : 'plan.splitTitleOff');
  node.onclick = () => commit(setSplit(plan, !on));
  return node;
}

function renderNodes(graph, plan, commit) {
  const host = document.getElementById('plan-nodes');
  const fragment = document.createDocumentFragment();
  for (const spec of graph.nodes.values()) {
    const node = NODE_RENDERERS[spec.kind](spec, plan, commit);
    place(node, spec);
    fragment.append(node);
  }
  host.replaceChildren(fragment);
  const height = Number.isFinite(graph.height) && graph.height > 0 ? graph.height : M.stem.h;
  // The canvas is sized explicitly so the SVG wires and the absolutely
  // positioned nodes share one coordinate space.
  const canvas = host.parentElement;
  Object.assign(host.style, {width: `${graph.width}px`, height: `${height}px`});
  Object.assign(canvas.style, {width: `${graph.width}px`, height: `${height}px`});
}

/* ---------------- wires ---------------- */
function curve(from, to) {
  const x1 = from.x + from.w;
  const x2 = to.x;
  // Half the gap each, so both control points meet in the middle and the wire
  // leaves and enters horizontally. Not a fraction > 0.5: that pushes the first
  // control point past the second, and the line bulges backwards in an S-kink.
  const bend = Math.max(0, x2 - x1) / 2;
  return `M${x1} ${from.cy} C${x1 + bend} ${from.cy}, ${x2 - bend} ${to.cy}, ${x2} ${to.cy}`;
}

function createWireSink(svg, width, height) {
  Object.assign(svg.style, {width: `${width}px`, height: `${height}px`});
  for (const [key, value] of Object.entries({width, height, viewBox: `0 0 ${width} ${height}`})) {
    svg.setAttribute(key, value);
  }
  const parts = [];
  let seq = 0;
  const wire = (from, to, options = {}) => {
    const path = curve(from, to);
    parts.push(`<path d="${path}" fill="none" stroke="${options.stroke || 'var(--line-strong)'}"
      stroke-width="${options.width || 1.5}" stroke-linecap="round"
      ${options.dash ? `stroke-dasharray="${options.dash}"` : ''}
      ${options.opacity != null ? `opacity="${options.opacity}"` : ''}/>`);
    if (!options.flow) return;
    const delay = (seq++ % M.flowCycles) * M.flowStagger;
    parts.push(`<path class="plan-flow" d="${path}" stroke="${options.flow.stroke}"
      stroke-width="${options.flow.width || 2}" stroke-opacity="${options.flow.opacity ?? 0.9}"
      style="animation-duration:${options.flow.duration || 1.7}s;animation-delay:-${delay}s"/>`);
  };
  wire.flush = () => { svg.innerHTML = parts.join(''); };
  return wire;
}

const STATE_OPACITY = {on: 1, grouped: 0.55, off: 0.3};

function wireRootToStems(wire, graph, plan) {
  const root = graph.nodes.get('root');
  for (const [id] of STEMS) {
    const state = !plan.enabled.has(id) ? 'off' : isGrouped(plan, id) ? 'grouped' : 'on';
    wire(root, graph.nodes.get(id), {
      stroke: state === 'grouped' ? 'var(--c-other-dim)' : 'var(--line-strong)',
      dash: state === 'off' ? '3 4' : '',
      opacity: STATE_OPACITY[state],
      flow: state === 'off' ? null
        : {stroke: state === 'grouped' ? 'var(--c-other)' : `var(--node-${id})`,
          opacity: state === 'grouped' ? 0.35 : 0.45, duration: 2.4},
    });
  }
}

function wireStemToActions(wire, graph, plan) {
  for (const node of graph.nodes.values()) {
    if (node.kind !== 'act') continue;
    const split = node.action === 'split';
    for (const parent of node.parents) {
      const leaf = graph.nodes.get(parent).kind === 'leaf';
      const state = leaf
        ? (plan.grouped.has(parent) ? 'grouped' : 'on')
        : !plan.enabled.has(parent) ? 'off' : isGrouped(plan, parent) ? 'grouped' : 'on';
      wire(graph.nodes.get(parent), node, {
        stroke: split ? 'var(--c-split-dim)' : 'var(--line-strong)',
        opacity: state === 'off' ? STATE_OPACITY.off : 1,
        dash: state === 'off' ? '3 4' : '',
        flow: state === 'off' ? null : {
          stroke: split ? 'var(--c-split)' : `var(--node-${parent})`,
          opacity: split ? 0.85 : 0.5, width: 1.9, duration: 2,
        },
      });
    }
  }
}

function wireSplitToLeaves(wire, graph, plan) {
  const split = graph.nodes.get('split');
  if (!split) return;
  for (const [id] of LEAVES) {
    const leaf = graph.nodes.get(id);
    if (!leaf) continue;
    const grouped = plan.grouped.has(id);
    wire(split, leaf, {
      stroke: 'var(--c-split-dim)',
      opacity: grouped ? 0.5 : 1,
      flow: {stroke: 'var(--c-split)', opacity: 0.8, width: 1.9, duration: 1.9},
    });
  }
}

function wireMergesToGroup(wire, graph, plan) {
  const group = graph.nodes.get('group');
  for (const node of graph.nodes.values()) {
    if (node.kind !== 'act' || node.action !== 'merge') continue;
    const source = graph.nodes.get(node.target);
    const merged = plan.grouped.has(node.target);
    const dropped = source.kind === 'leaf' ? false : !plan.enabled.has(node.target);
    wire(node, group, merged
      ? {stroke: 'var(--c-other)', width: 2,
         flow: {stroke: 'var(--c-other)', width: 2.4, opacity: 0.95, duration: 1.5}}
      : {stroke: 'var(--c-other-faint)', width: 1.3, dash: '3 4',
         opacity: dropped ? STATE_OPACITY.off : 1});
  }
}

function wireAutoToGroup(wire, graph, plan) {
  const other = graph.nodes.get('other');
  const group = graph.nodes.get('group');
  if (!other || !plan.enabled.has('other')) return;
  wire(other, group, {
    stroke: 'var(--c-other)', width: 2,
    flow: {stroke: 'var(--c-other)', width: 2.4, opacity: 0.95, duration: 1.5},
  });
}

function renderWires(graph, plan) {
  const wire = createWireSink(document.getElementById('plan-wires'), graph.width, graph.height);
  wireRootToStems(wire, graph, plan);
  wireStemToActions(wire, graph, plan);
  wireSplitToLeaves(wire, graph, plan);
  wireMergesToGroup(wire, graph, plan);
  wireAutoToGroup(wire, graph, plan);
  wire.flush();
}

/* ---------------- run plan ---------------- */
const STEP_HTML = {
  separate: (step, described) => t(step.model === 'vocal'
    ? 'plan.stepSeparateVocal' : 'plan.stepSeparate', {
    stems: described.computedCount,
  }),
  split: step => t(step.skipped ? 'plan.stepSplitSkipped' : 'plan.stepSplit'),
  mix: (step, described) => {
    if (step.skipped) return t('plan.stepMixNone');
    const members = described.members;
    if (members.length === 1) return t('plan.stepMixSingle');
    return t('plan.stepMix', {count: members.length});
  },
};

const STEP_COST = {
  separate: (step, described) => t(step.model === 'vocal' ? 'plan.costFast' : 'plan.costFull'),
  split: step => t(step.skipped ? 'plan.costSkipped' : 'plan.costSplit'),
  mix: (step, described) => t(step.skipped ? 'plan.costSkipped'
    : described.members.length > 1 ? 'plan.costMix' : 'plan.costInstant'),
};

function renderRuns(plan) {
  const described = describePlan(plan);
  const list = document.getElementById('plan-run-list');
  list.replaceChildren(...steps(plan).map((step, index) => {
    const row = el('li', step.skipped ? 'is-skipped' : '',
      `<span class="plan-step-n">${index + 1}</span>
       <span>${STEP_HTML[step.id](step, described)}</span>
       <span class="plan-step-cost">${STEP_COST[step.id](step, described)}</span>`);
    return row;
  }));

  const passPill = document.getElementById('plan-pass-pill');
  passPill.textContent = t('plan.passes', {count: described.passes});
  passPill.className = `pill${described.passes > 1 ? ' warn' : ''}`;
  document.getElementById('plan-file-pill').textContent =
    t('plan.files', {count: described.files});
  // Stem pass ~1x, guitar split ~10x, mixing <1 s: the split dominates the run, so a
  // plan that enables it costs roughly eleven times a plain separation.
  document.getElementById('plan-run-total').textContent = t('plan.estimate', {
    factor: described.split ? '11' : '1',
  });
  document.getElementById('plan-foot-hint').textContent = t('plan.footHint', {
    own: described.ownCount, grouped: described.members.length,
  });
  document.getElementById('plan-confirm').disabled = described.silent;

  const notes = warnings(plan);
  const box = document.getElementById('plan-warning');
  box.hidden = !notes.length;
  document.getElementById('plan-warning-text').innerHTML = notes
    .map(note => `<p>${t(`plan.warn.${note.id}`, note.count != null ? {count: note.count} : {})}</p>`)
    .join('');
}

/* ---------------- dialog ---------------- */
function render(plan, commit) {
  const graph = buildGraph(plan);
  layout(graph);
  renderNodes(graph, plan, commit);
  renderWires(graph, plan);
  renderRuns(plan);
  return graph;
}

let pending = null;

/** Open the plan dialog. Resolves with the plan request, or null when cancelled.
 *  It only describes the work: starting the job stays with the normal button. */
export function openPlanDialog({initial, title} = {}) {
  // A second open request cancels the first instead of leaving it pending.
  pending?.finish(null);
  return new Promise(resolve => {
    const dialog = document.getElementById('plan-dialog');
    const original = clone(initial || createPlan());
    const draft = clone(original);

    const state = {done: false, confirmed: false};
    const finish = value => {
      if (state.done) return;
      state.done = true;
      if (pending && pending.finish === finish) pending = null;
      resolve(value);
    };
    pending = {finish};

    // Model mutators already applied their change; commit just repaints.
    const commit = () => render(draft, commit);

    if (title) document.getElementById('plan-title').textContent = title;
    applyNodeTokens();

    document.getElementById('plan-confirm').onclick = () => {
      state.confirmed = true;
      const request = toRequest(draft);
      dialog.close();
      finish(request);
    };
    document.getElementById('plan-reset').onclick = () => {
      const fresh = clone(original);
      draft.enabled = fresh.enabled;
      draft.grouped = fresh.grouped;
      draft.split = fresh.split;
      commit();
    };
    dialog.onclose = () => { if (!state.confirmed) finish(null); };

    render(draft, commit);
    if (!dialog.open) dialog.showModal();
  });
}
