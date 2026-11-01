import {$, el} from './core.js';
import {store} from './store.js';
import {t, onLangChange} from './i18n.js';
import {checkForUpdatesManual} from './updates.js';
/* ---------- About dialog: version and credits (the full list with licenses is in README.md) ---------- */
const CREDITS = [
  ['about.basedOn', [
    ['Sound Razor', 'pedromtcosta', 'MIT', 'https://github.com/pedromtcosta/sound-razor'],
  ]],
  ['about.models', [
    ['Demucs (htdemucs_6s)', 'Meta AI · Alexandre Défossez', 'MIT', 'https://github.com/facebookresearch/demucs'],
    ['UVR MDX-Net Karaoke 2', 'Ultimate Vocal Remover · Anjok07, aufr33', 'MIT', 'https://github.com/Anjok07/ultimatevocalremovergui'],
    ['Lead/rhythm guitar (Mel-Band RoFormer)', 'listra92 · hosted by noblebarkrr', null, 'https://huggingface.co/noblebarkrr/mvsepless_resources'],
  ]],
  ['about.builtWith', [
    ['Music-Source-Separation-Training', 'ZFTurbo (Roman Solovyev)', 'MIT', 'https://github.com/ZFTurbo/Music-Source-Separation-Training'],
    ['BS-RoFormer', 'lucidrains (Phil Wang)', 'MIT', 'https://github.com/lucidrains/BS-RoFormer'],
    ['python-audio-separator', 'nomadkaraoke (Andrew Beveridge)', 'MIT', 'https://github.com/nomadkaraoke/python-audio-separator'],
    ['yt-dlp', 'yt-dlp contributors', 'Unlicense', 'https://github.com/yt-dlp/yt-dlp'],
    ['FFmpeg', 'FFmpeg developers', 'LGPL/GPL', 'https://ffmpeg.org'],
    ['pywebview', 'Roman Sirokov', 'BSD-3-Clause', 'https://github.com/r0x0r/pywebview'],
  ]],
  ['about.data', [
    ['MusicBrainz & Cover Art Archive', 'MetaBrainz Foundation', 'CC0 / various', 'https://musicbrainz.org'],
  ]],
];
const README_CREDITS = 'https://github.com/um1chc5/unweave#credits';

function link(href, text, className = '') {
  const a = el('a', className, text); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
  return a;
}
function renderAbout() {
  $('about-version').textContent = store.state.version ? t('about.version', {version: store.state.version}) : '';
  const list = $('about-credits'); list.replaceChildren();
  for (const [heading, entries] of CREDITS) {
    const group = el('section', 'credits-group');
    group.append(el('h3', '', t(heading)));
    const items = el('ul', 'credits-list');
    for (const [name, author, license, href] of entries) {
      const item = el('li');
      item.append(link(href, name, 'credits-name'), el('span', 'credits-meta', `${author} · ${license || t('about.licenseNotStated')}`));
      items.append(item);
    }
    group.append(items);
    list.append(group);
  }
  $('about-full').href = README_CREDITS;
}
$('about-open').onclick = () => { renderAbout(); $('about-dialog').showModal(); };
$('about-check-updates').onclick = () => checkForUpdatesManual();
onLangChange(() => { if ($('about-dialog').open) renderAbout(); });
