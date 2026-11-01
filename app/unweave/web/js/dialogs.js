import {$, api, notice, activeProject, sep, projectUrl, fields} from './core.js';
import {store, nav} from './store.js';
import {resetLookup} from './lookup.js';
import {t} from './i18n.js';
/* ---------- edit / delete ---------- */
$('edit-open').onclick = () => {
  const p = activeProject(); if (!p) return; store.editing = {id: p.id, root: store.state.root};
  resetLookup('edit');
  for (const key of ['title', 'artist', 'album', 'year']) $(`edit-${key}`).value = p[key] || '';
  $('edit-error').textContent = ''; $('edit-dialog').showModal();
};
$('edit-form').onsubmit = async e => {
  e.preventDefault();
  if (!store.editing) return;
  const target = store.editing;
  try { await api(`${projectUrl(target.id)}/metadata`, {...fields('edit'), root: target.root}); $('edit-dialog').close(); await nav.refresh(); }
  catch (error) { $('edit-error').textContent = error.message; }
};
$('delete-open').onclick = () => {
  const project = activeProject(); if (!project) return;
  store.deleting = {id: project.id, root: store.state.root};
  $('delete-name').textContent = project.title;
  $('delete-path').textContent = `${store.state.root}${sep()}${project.id}`;
  $('delete-error').textContent = ''; $('delete-dialog').showModal();
};
$('delete-form').onsubmit = async event => {
  event.preventDefault(); if (!store.deleting) return;
  const target = store.deleting; $('delete-submit').disabled = true;
  try {
    await api(`${projectUrl(target.id)}/delete`, {root: target.root});
    $('delete-dialog').close();
    if (store.selected === target.id && store.state.root === target.root) nav.show('library');
    await nav.refresh(); notice(t('dialog.delete.deletedNotice'));
  } catch (error) { $('delete-error').textContent = error.message; }
  finally { $('delete-submit').disabled = false; }
};
