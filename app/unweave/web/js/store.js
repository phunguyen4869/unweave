export const store = {
  state: {root: null, default_root: null, projects: [], jobs: [], active_job: null, job: null, finished_jobs: [], now: 0, setup: null},
  view: 'new', selected: null, audioSignature: '', loading: 0, controller: null,
  busy: false, editing: null, deleting: null, browseParent: '', sourceMode: 'file',
  chosenFile: null, pending: null, resepOpen: false, announced: new Set(),
  setupDeclined: false, setupYoutube: false, setupJobAnnounced: null, setupRunningStages: [],
  lookupSelections: {edit: null}, lookupEpoch: {edit: 0}, coverImages: new Map(),
  newTrimEditor: null, newTrimRange: null, newTrimDuration: 0, newBuffer: null,
  newTrimEpoch: 0,
  songTrimEditor: null, songTrimRange: null, songTrimKey: '',
  songPlanFor: null,
  splitEditor: null, splitRange: null, splitProject: null,
  exportPending: null, exportOffered: null,
};
export const nav = {show() {}, selectProject() {}, refresh() {}, render() {}};
