import {$, el, api, token, fields} from './core.js';
import {store} from './store.js';
import {t} from './i18n.js';
/* ---------- MusicBrainz lookup (edit dialog) ---------- */
export function resetLookup(prefix) {
  store.lookupEpoch[prefix]++;
  store.lookupSelections[prefix] = null;
  const panel = $(`${prefix}-lookup-results`);
  if (panel) { panel.replaceChildren(); panel.hidden = true; }
  const status = $(`${prefix}-lookup-status`);
  if (status) status.textContent = '';
  const button = $(`${prefix}-lookup`);
  if (button) button.disabled = false;
  $(`${prefix}-form`).querySelector('[type=submit]').disabled = false;
}

for (const prefix of ['edit']) {
  const form = $(`${prefix}-form`);
  const box = el('div', 'metadata-lookup');
  const find = el('button', 'secondary', t('lookup.findButton')); find.type = 'button'; find.id = `${prefix}-lookup`;
  const help = el('p', 'lookup-help', t('lookup.help'));
  const status = el('p', 'lookup-status'); status.id = `${prefix}-lookup-status`; status.setAttribute('role', 'status');
  const results = el('div', 'lookup-results'); results.id = `${prefix}-lookup-results`; results.hidden = true;
  box.append(find, help, status, results);
  form.insertBefore(box, form.querySelector('[type=submit]'));
  for (const key of ['title', 'artist', 'album']) $(`${prefix}-${key}`).addEventListener('input', () => resetLookup(prefix));
  form.closest('dialog').addEventListener('close', () => resetLookup(prefix));
  find.onclick = async () => {
    resetLookup(prefix);
    const epoch = ++store.lookupEpoch[prefix];
    find.disabled = true; status.textContent = t('lookup.searching');
    try {
      const data = await api('/api/metadata/search', fields(prefix));
      if (epoch !== store.lookupEpoch[prefix]) return;
      status.textContent = data.matches.length ? t('lookup.chooseMatch') : t('lookup.noMatches');
      results.hidden = !data.matches.length;
      for (const match of data.matches) {
        const card = el('div', 'lookup-match');
        card.append(el('strong', '', `${match.title} — ${match.artist}`));
        card.append(el('p', '', [match.album, match.year, match.type, match.edition, match.recording_note].filter(Boolean).join(' · ')));
        const source = el('a', 'lookup-source', 'MusicBrainz');
        source.href = `https://musicbrainz.org/release/${encodeURIComponent(match.release_id)}`; source.target = '_blank'; source.rel = 'noopener noreferrer';
        const choose = el('button', 'text-button', t('lookup.useThisMatch')); choose.type = 'button';
        choose.onclick = async () => {
          const selectionEpoch = ++store.lookupEpoch[prefix];
          results.querySelectorAll('button').forEach(b => b.disabled = true);
          find.disabled = true; form.querySelector('[type=submit]').disabled = true;
          status.textContent = t('lookup.fetchingCover');
          try {
            const prepared = await api('/api/metadata/prepare', {token: match.token});
            if (selectionEpoch !== store.lookupEpoch[prefix]) return;
            for (const key of ['title', 'artist', 'album', 'year']) if (prepared.fields[key]) $(`${prefix}-${key}`).value = prepared.fields[key];
            store.lookupSelections[prefix] = prepared.token;
            results.replaceChildren(); results.hidden = false;
            results.append(el('p', '', t('lookup.selectedSave', {album: match.album, coverSuffix: prepared.has_cover ? t('lookup.andCover') : ''})));
            if (prepared.has_cover) {
              const response = await fetch(`/api/metadata/cover/${prepared.token}`, {headers: {'X-Unweave-Token': token}});
              if (!response.ok) throw new Error(t('lookup.coverUnavailable'));
              const url = URL.createObjectURL(await response.blob());
              if (selectionEpoch !== store.lookupEpoch[prefix]) { URL.revokeObjectURL(url); return; }
              const img = el('img', 'lookup-cover'); img.alt = t('lookup.coverAlt', {album: match.album});
              img.onload = img.onerror = () => URL.revokeObjectURL(url); img.src = url; results.prepend(img);
            }
            status.textContent = prepared.warning || t('lookup.detailsReady');
          } catch (error) {
            if (selectionEpoch === store.lookupEpoch[prefix]) status.textContent = error.message;
          } finally {
            if (selectionEpoch === store.lookupEpoch[prefix]) {
              find.disabled = false; form.querySelector('[type=submit]').disabled = false;
              results.querySelectorAll('button').forEach(b => b.disabled = false);
            }
          }
        };
        card.append(source, choose); results.append(card);
      }
    } catch (error) { if (epoch === store.lookupEpoch[prefix]) status.textContent = error.message; }
    finally { if (epoch === store.lookupEpoch[prefix]) find.disabled = false; }
  };
}
