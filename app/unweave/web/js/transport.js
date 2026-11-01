import {$, time, notice} from './core.js';
import {store} from './store.js';
import {player, renderTracks, syncTrackControls} from './audio.js';
import {t} from './i18n.js';
/* ---------- transport ---------- */
$('play').onclick = () => player.playing || player.starting ? player.pause() : player.play().catch(e => notice(e.message, 'error'));
$('restart').onclick = () => player.seek(0).catch(e => notice(e.message, 'error'));
$('seek').oninput = () => { $('elapsed').textContent = time(Number($('seek').value)); };
$('seek').onchange = () => player.seek(Number($('seek').value)).catch(e => notice(e.message, 'error'));
$('master-volume').oninput = () => player.setVolume(Number($('master-volume').value));
function showSpeed() {
  const percent = Number($('playback-speed').value);
  $('speed-value').textContent = `${percent}%`;
  $('playback-speed').setAttribute('aria-valuetext', t('transport.speedPercent', {percent}));
}
$('playback-speed').oninput = showSpeed;
$('playback-speed').onchange = () => {
  showSpeed();
  player.setPlaybackRate(Number($('playback-speed').value) / 100).catch(e => notice(e.message, 'error'));
};
$('reset-speed').onclick = () => {
  $('playback-speed').value = 100; showSpeed();
  player.setPlaybackRate(1).catch(e => notice(e.message, 'error'));
};
$('reset-mix').onclick = () => { for (const t of player.tracks) { t.muted = false; t.solo = false; t.volume = 1; } player.updateMix(); renderTracks(); };
document.addEventListener('keydown', e => {
  if (store.view === 'song' && e.code === 'Space' && !['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(e.target.tagName) && !document.querySelector('dialog[open]')) {
    e.preventDefault(); $('play').click();
  }
});
window.addEventListener('resize', () => { if (player.tracks.length) { renderTracks(); syncTrackControls(); } });

