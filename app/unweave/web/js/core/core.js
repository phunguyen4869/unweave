import {store} from './store.js';
import {t} from './i18n.js';
import {STEM_LABEL_KEYS} from './constants.js';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="unweave-token"]').content;
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
let noticeTimer = null;
function notice(message = '', kind = 'info') {
  clearTimeout(noticeTimer);
  $('notice').textContent = message; $('notice').hidden = !message; $('notice').dataset.kind = kind;
  if (message) noticeTimer = setTimeout(() => { $('notice').hidden = true; }, kind === 'error' ? 9000 : 5000);
}
function time(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
function duration(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60), s = seconds % 60;
  return m < 60 ? `${m}m ${String(s).padStart(2, '0')}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}
let clockSkew = 0;
function setClockSkew(value) { clockSkew = value; }
function serverNow() { return Date.now() / 1000 + clockSkew; }
function sep() { return (store.state.root || '').includes('\\') ? '\\' : '/'; }
function stem(name) { return name.replace(/\.[^.]+$/, ''); }
async function api(path, data) {
  const response = await fetch(path, {
    method: data === undefined ? 'GET' : 'POST',
    headers: {'X-Unweave-Token': token, ...(data === undefined ? {} : {'Content-Type': 'application/json'})},
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || t('core.requestFailed', {status: response.status}));
  return result;
}
function stemLabel(file, fallback) {
  const key = STEM_LABEL_KEYS[stem(file || '').toLowerCase()];
  return key ? t(key) : fallback;
}
function activeProject() { return store.state.projects.find(p => p.id === store.selected); }
function activeJob() { return store.state.active_job ? store.state.jobs.find(j => j.id === store.state.active_job) : store.state.job; }
function jobRunning() { const job = activeJob(); return !!job && ['running', 'cancelling'].includes(job.status); }
// Queue-aware lookups: several jobs can be running or waiting at once.
function jobPending(job) { return !!job && ['queued', 'running', 'cancelling'].includes(job.status); }
function findJob(id) {
  const {jobs = [], finished_jobs: finished = [], job} = store.state;
  return jobs.find(j => j.id === id) || [...finished].reverse().find(j => j.id === id) || (job?.id === id ? job : null);
}
// The job to show on a song page: its running or queued job, else the latest finished one.
function projectJob(id) {
  const {jobs = [], finished_jobs: finished = [], job} = store.state;
  const live = jobs.filter(j => j.project === id && j.kind !== 'youtube').sort((a, b) => a.position - b.position);
  if (live.length) return live[0];
  const done = [...finished].reverse().find(j => j.project === id && j.kind !== 'youtube');
  return done || (job?.project === id && job.kind !== 'youtube' ? job : null);
}
function queueBusy() { return (store.state.jobs || []).length > 0; }
function projectUrl(id) { return `/api/projects/${encodeURIComponent(id)}`; }
function fields(prefix) {
  const data = Object.fromEntries(['title', 'artist', 'album', 'year'].map(key => [key, $(`${prefix}-${key}`).value]));
  if (store.lookupSelections[prefix]) data.lookup_token = store.lookupSelections[prefix];
  return data;
}
export {$, token, el, notice, time, duration, serverNow, setClockSkew, sep, stem, api, activeJob, activeProject, jobRunning,
  jobPending, findJob, projectJob, queueBusy, projectUrl, fields, stemLabel};
