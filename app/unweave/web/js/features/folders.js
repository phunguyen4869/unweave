import {$, el, api, notice} from '../core/core.js';
import {store, nav} from '../core/store.js';
import {t} from '../core/i18n.js';
/* ---------- output folder ---------- */
export async function browse(path) {
  const data = await api(`/api/folders?path=${encodeURIComponent(path || '')}`);
  $('folder-path').value = data.path; store.browseParent = data.parent;
  $('folder-children').replaceChildren();
  for (const folder of data.folders) {
    const button = el('button', '', `▸  ${folder.name}`); button.type = 'button';
    button.onclick = () => browse(folder.path).catch(e => $('folder-error').textContent = e.message);
    $('folder-children').append(button);
  }
  if (!data.folders.length) $('folder-children').append(el('p', '', t('folders.noSubfolders')));
}
export async function openFolder() {
  // The desktop app uses the system folder picker; the in-app browser below is only
  // the fallback for running the UI in a plain web browser.
  try {
    const result = await api('/api/window/pick-folder', {});
    if (result.native) {
      if (!result.cancelled) await nav.refresh();
      return;
    }
  } catch (error) {
    notice(error.message, 'error');
    return;
  }
  $('folder-error').textContent = ''; $('create-folder').checked = false;
  $('folder-dialog').showModal();
  browse(store.state.root).catch(error => $('folder-error').textContent = error.message);
}
$('folder-open').onclick = openFolder;
$('library-folder').onclick = openFolder;
$('folder-default').onclick = async () => {
  try { await api('/api/library', {path: store.state.default_root, create: true}); await nav.refresh(); notice(t('folders.savingDefault')); }
  catch (error) { notice(error.message, 'error'); }
};
$('browse-path').onclick = () => browse($('folder-path').value).catch(e => $('folder-error').textContent = e.message);
$('folder-up').onclick = () => browse(store.browseParent).catch(e => $('folder-error').textContent = e.message);
$('folder-form').onsubmit = async e => {
  e.preventDefault();
  try {
    await api('/api/library', {path: $('folder-path').value, create: $('create-folder').checked});
    $('folder-dialog').close(); await nav.refresh();
  } catch (error) { $('folder-error').textContent = error.message; }
};
document.querySelectorAll('.close-dialog').forEach(button => button.onclick = () => { if (!store.busy) button.closest('dialog').close(); });

