/* Pure stem-plan model. No DOM, no globals, no rendering — so every rule below
   can be unit-tested and the dialog, the summary line and the request payload
   all read the same answer.

   Vocabulary
     own      a stem (or leaf) that gets its own file
     grouped  a stem (or leaf) whose audio is folded into other.flac and NOT
              written as its own file — this is the "delete the merged stem"
              behaviour: grouping is destructive by construction
     dropped  not enabled at all; its audio is written nowhere
*/
import {STEMS, DEFAULT_STEMS} from './constants.js';

export const STEM_ORDER = STEMS.map(([id]) => id);
export const GROUP_STEM = 'other';
export const GUITAR = 'guitar';
export const LEAF_ORDER = ['lead', 'rhythm'];
// Model outputs that exist before any grouping. `lead`/`rhythm` are produced by
// the guitar split, not by Demucs.
const MODEL_STEMS = [...STEM_ORDER];

const EMPTY = Object.freeze([]);

/** Collapse the mutable sets into the single legal shape. The ONLY place rules live. */
function normalize(plan) {
  // Leaves are a product of the split, never an input: the Split control owns them.
  for (const id of LEAF_ORDER) plan.enabled.delete(id);
  // Dropping a stem also drops it out of the group — you cannot fold in silence.
  // Leaves are exempt: they live only in `grouped`, never in `enabled`.
  for (const id of [...plan.grouped]) {
    if (!LEAF_ORDER.includes(id) && !plan.enabled.has(id)) plan.grouped.delete(id);
  }
  // `other` is the destination, so it is folded in whenever it exists.
  if (plan.enabled.has(GROUP_STEM)) plan.grouped.add(GROUP_STEM);
  else plan.grouped.delete(GROUP_STEM);
  // Splitting needs the guitar as an input, so a folded or dropped guitar cannot split.
  if (!plan.enabled.has(GUITAR) || isGrouped(plan, GUITAR)) plan.split = false;
  // A merged leaf is meaningless once the split is off.
  for (const id of LEAF_ORDER) if (!plan.split) plan.grouped.delete(id);
  return plan;
}

export function createPlan(initial = {}) {
  return normalize({
    enabled: new Set(initial.enabled ?? DEFAULT_STEMS),
    grouped: new Set(initial.grouped ?? EMPTY),
    split: Boolean(initial.split),
  });
}

/** Quick-grid `{stems}` -> plan, without changing what lands on disk.
 *  Ticking `other` there means "fold every unlisted instrument in", so those
 *  become grouped-and-enabled rather than dropped. */
export function fromSelection(stems) {
  const chosen = new Set(stems || DEFAULT_STEMS);
  const plan = createPlan({enabled: chosen, grouped: EMPTY, split: false});
  if (chosen.has(GROUP_STEM)) {
    for (const id of MODEL_STEMS) {
      if (id === GROUP_STEM || chosen.has(id)) continue;
      plan.enabled.add(id);
      plan.grouped.add(id);
    }
  }
  return normalize(plan);
}

export function isGrouped(plan, id) {
  return id === GROUP_STEM ? plan.enabled.has(GROUP_STEM) : plan.grouped.has(id);
}

/** Rebuild a plan from a stored request, so the dialog reopens where you left it. */
export function fromRequest(request = {}) {
  const grouped = new Set(request.group || []);
  const enabled = new Set([...(request.stems || []), ...grouped]);
  return createPlan({enabled, grouped, split: Boolean(request.split ?? request.guitar_split)});
}

export function isSplitActive(plan) {
  return plan.split && plan.enabled.has(GUITAR) && !isGrouped(plan, GUITAR);
}

export function setEnabled(plan, id, on) {
  if (on) plan.enabled.add(id);
  else plan.enabled.delete(id);
  return normalize(plan);
}

export function setGrouped(plan, id, on) {
  if (on) {
    plan.enabled.add(id);
    plan.grouped.add(id);
  } else {
    plan.grouped.delete(id);
  }
  return normalize(plan);
}

export function setSplit(plan, on) {
  plan.split = Boolean(on);
  return normalize(plan);
}

export function clone(plan) {
  return createPlan({enabled: plan.enabled, grouped: plan.grouped, split: plan.split});
}

/** Every derived value the UI needs, computed once. */
export function describePlan(plan) {
  const enabled = STEM_ORDER.filter(id => plan.enabled.has(id));
  const split = isSplitActive(plan);
  const leaves = split ? LEAF_ORDER : [];
  const own = enabled.filter(id => !isGrouped(plan, id));
  const grouped = enabled.filter(id => isGrouped(plan, id) && id !== GROUP_STEM);
  const ownLeaves = leaves.filter(id => !plan.grouped.has(id));
  const groupedLeaves = leaves.filter(id => plan.grouped.has(id));
  const members = [
    ...(plan.enabled.has(GROUP_STEM) ? [GROUP_STEM] : []),
    ...grouped,
    ...groupedLeaves,
  ];
  const ownCount = own.length + ownLeaves.length;
  const files = ownCount + (members.length ? 1 : 0);
  // Everything the plan needs from the separator: own files, group members, and
  // the guitar whenever the split needs it as an input.
  const computed = new Set([...own, ...members.filter(id => MODEL_STEMS.includes(id))]);
  if (split) computed.add(GUITAR);
  const model = computed.size > 0 && [...computed].every(id => id === 'vocals')
    ? 'vocal' : 'six-stem';
  return {
    enabled, split, leaves, own, grouped, ownLeaves, groupedLeaves, members,
    computed: [...computed], ownCount, files,
    // The six-stem model always produces all six stems in one pass; the plan then
    // keeps some and discards the rest, so the pass count is what it costs, not
    // how many files survive.
    computedCount: model === 'vocal' ? computed.size : MODEL_STEMS.length,
    passes: split ? 2 : 1,
    model,
    silent: files === 0,
  };
}

/** Everything the plan has to do, in the order the pipeline runs it.
 *  Costs and labels are presentation and live in plan.js. */
export function steps(plan) {
  const d = describePlan(plan);
  // other.flac already exists when it is the only member, so nothing is mixed.
  const mixNeeded = d.members.length > 1
    || (d.members.length === 1 && d.members[0] !== GROUP_STEM);
  return [
    {id: 'separate', skipped: false, model: d.model},
    {id: 'split', skipped: !d.split},
    {id: 'mix', skipped: !mixNeeded},
  ];
}

export function warnings(plan) {
  const d = describePlan(plan);
  const notes = [];
  if (d.members.length >= 3) notes.push({id: 'peak', count: d.members.length});
  if (d.split && d.leaves.every(id => plan.grouped.has(id))) notes.push({id: 'leavesBothGrouped'});
  if (d.split) notes.push({id: 'splitSlow'});
  if (d.silent) notes.push({id: 'silent'});
  else if (!d.ownCount) notes.push({id: 'noOwnFiles'});
  else if (d.ownCount === 1 && d.files === 1 && !d.members.length) notes.push({id: 'singleFile'});
  return notes;
}

/** The plan payload shared by the picker and the separate request. It describes
 *  the work only; starting the job stays with the normal Start button. */
export function toRequest(plan) {
  const d = describePlan(plan);
  return {
    stems: [...d.own, ...d.ownLeaves],
    group: [...d.members],
    split: d.split,
  };
}
