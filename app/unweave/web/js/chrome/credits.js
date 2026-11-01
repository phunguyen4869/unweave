import {$, el} from '../core/core.js';
import {store} from '../core/store.js';
import {t, onLangChange} from '../core/i18n.js';
/* ---------- About tab credits (the full list with licenses is in README.md) ---------- */
export const CREDITS = [
  ['about.basedOn', [
    ['Sound Razor', 'pedromtcosta', 'MIT', 'https://github.com/pedromtcosta/sound-razor'],
  ]],
  ['about.models', [
    ['Demucs (htdemucs_6s)', 'Meta AI', 'MIT', 'https://github.com/facebookresearch/demucs'],
    ['UVR MDX-Net Karaoke 2', 'Ultimate Vocal Remover', 'MIT', 'https://github.com/Anjok07/ultimatevocalremovergui'],
    ['Lead/rhythm guitar', 'listra92 / noblebarkrr', null, 'https://huggingface.co/noblebarkrr/mvsepless_resources'],
  ]],
  ['about.builtWith', [
    ['Music-Source-Separation-Training', 'ZFTurbo', 'MIT', 'https://github.com/ZFTurbo/Music-Source-Separation-Training'],
    ['BS-RoFormer', 'lucidrains', 'MIT', 'https://github.com/lucidrains/BS-RoFormer'],
    ['python-audio-separator', 'nomadkaraoke', 'MIT', 'https://github.com/nomadkaraoke/python-audio-separator'],
    ['yt-dlp', 'yt-dlp', 'Unlicense', 'https://github.com/yt-dlp/yt-dlp'],
    ['FFmpeg', 'FFmpeg', 'LGPL/GPL', 'https://ffmpeg.org'],
    ['pywebview', 'r0x0r', 'BSD-3', 'https://github.com/r0x0r/pywebview'],
  ]],
  ['about.data', [
    ['MusicBrainz & Cover Art Archive', 'MetaBrainz', 'CC0 / various', 'https://musicbrainz.org'],
  ]],
];
const README_CREDITS = 'https://github.com/um1chc5/unweave#credits';

function link(href, text, className = '') {
  const a = el('a', className, text); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
  return a;
}

export function renderAbout() {
  const version = $('about-version');
  const list = $('about-credits');
  const full = $('about-full');
  if (!version || !list || !full) return;
  version.textContent = store.state.version ? t('about.version', {version: store.state.version}) : '';
  list.replaceChildren();
  list.append(el('h3', 'about-thanks', t('about.thanks')));
  const items = el('ul', 'credits-list credits-list--compact');
  for (const [, entries] of CREDITS) {
    for (const [name, author, license, href] of entries) {
      const item = el('li');
      const meta = [author, license || t('about.licenseNotStated')].filter(Boolean).join(' · ');
      item.append(link(href, name, 'credits-name'), el('span', 'credits-meta', meta));
      items.append(item);
    }
  }
  list.append(items);
  full.href = README_CREDITS;
}

onLangChange(() => {
  if ($('settings-dialog')?.open && store.settingsTab === 'about') renderAbout();
});
