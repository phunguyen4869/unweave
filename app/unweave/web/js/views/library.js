import {$, el, jobPending, projectJob, notice} from '../core.js';
import {store, nav} from '../store.js';
import {coverImage} from '../covers.js';
import {t} from '../i18n.js';
/* ---------- library ---------- */
export function renderLibrary() {
  $('library-folder').textContent = store.state.root || t('library.noFolderLower');
  if (store.view !== 'library') return;
  const list = $('library'); list.replaceChildren();
  const query = $('search').value.toLowerCase();
  const projects = store.state.projects.filter(p => `${p.title} ${p.artist} ${p.album}`.toLowerCase().includes(query));
  for (const project of projects) {
    const card = el('button', 'song-card');
    const art = el('span', 'card-art');
    art.style.setProperty('--h', [...project.id].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7));
    art.append(el('span', 'card-initial', (project.title || '?').trim().charAt(0).toUpperCase()));
    coverImage(art, project);
    const job = projectJob(project.id);
    let badge;
    if (job?.status === 'queued') badge = el('span', 'badge badge-live', t('library.queued'));
    else if (jobPending(job)) badge = el('span', 'badge badge-live', t('library.processing', {pct: Math.floor(job.progress || 0)}));
    else if (project.stems.length) badge = el('span', 'badge badge-ok', t('library.stemsCount', {count: project.stems.length}));
    else badge = el('span', 'badge', t('library.notSeparated'));
    const text = el('span', 'card-text');
    text.append(el('strong', '', project.title), el('small', '', project.artist || t('common.unknownArtist')));
    card.append(art, text, badge);
    card.onclick = () => nav.selectProject(project.id);
    list.append(card);
  }
  if (!projects.length) {
    const empty = el('div', 'empty');
    empty.append(el('strong', '', query ? t('library.noMatching') : t('library.noSongsYet')),
      el('p', '', query ? t('library.tryDifferentSearch') : t('library.separateFirstSong')));
    if (!query) { const go = el('button', 'btn btn-primary btn-sm', t('library.separateASong')); go.onclick = () => nav.show('new'); empty.append(go); }
    list.append(empty);
  }
}
$('search').oninput = renderLibrary;
$('refresh').onclick = () => nav.refresh().catch(e => notice(e.message, 'error'));

