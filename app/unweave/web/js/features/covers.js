import {store} from '../core/store.js';
import {$, token, el, projectUrl} from '../core/core.js';
import {t} from '../core/i18n.js';
export async function coverImage(container, project) {
  const key = JSON.stringify([store.state.root, project.id, project.cover]);
  if (container.dataset.coverKey === key) return;
  container.dataset.coverKey = key;
  container.querySelector('img')?.remove(); container.classList.remove('has-cover');
  if (!project.cover) return;
  const root = store.state.root;
  if (!store.coverImages.has(key)) {
    store.coverImages.set(key, fetch(`${projectUrl(project.id)}/cover?${new URLSearchParams({root})}`, {headers: {'X-Unweave-Token': token}})
      .then(r => { if (!r.ok) throw new Error(t('covers.unavailable')); return r.blob(); })
      .then(blob => URL.createObjectURL(blob)).catch(() => { store.coverImages.delete(key); return null; }));
    if (store.coverImages.size > 64) {
      const oldest = store.coverImages.keys().next().value;
      store.coverImages.get(oldest).then(url => { if (url) URL.revokeObjectURL(url); }); store.coverImages.delete(oldest);
    }
  }
  const url = await store.coverImages.get(key);
  if (!url || root !== store.state.root || container.dataset.coverKey !== key) return;
  const img = el('img'); img.alt = `${project.album || project.title} cover`; img.src = url;
  img.onerror = () => { img.remove(); container.classList.remove('has-cover'); };
  container.append(img); container.classList.add('has-cover');
}

