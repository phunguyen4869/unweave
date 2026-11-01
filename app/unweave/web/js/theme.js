import {$} from './core.js';
import {t, onLangChange} from './i18n.js';

const THEME_KEY = 'unweave-theme';
const LEGACY_THEME_KEY = 'sound-razor-theme';

function readTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY) || localStorage.getItem(LEGACY_THEME_KEY);
    if (saved && !localStorage.getItem(THEME_KEY)) {
      localStorage.setItem(THEME_KEY, saved);
      localStorage.removeItem(LEGACY_THEME_KEY);
    }
    return saved || 'dark';
  } catch (_) {
    return 'dark';
  }
}

function initTheme() {
  document.documentElement.dataset.theme = readTheme();
}
initTheme();

export function initThemeToggle() {
$('theme-toggle').onclick = () => {
  const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem(THEME_KEY, next);
    localStorage.removeItem(LEGACY_THEME_KEY);
  } catch (_) { /* private mode etc. */ }
  $('theme-toggle').title = $('theme-toggle').ariaLabel = next === 'light' ? t('theme.toDark') : t('theme.toLight');
};
$('theme-toggle').title = $('theme-toggle').ariaLabel = document.documentElement.dataset.theme === 'light' ? t('theme.toDark') : t('theme.toLight');
onLangChange(() => { $('theme-toggle').title = $('theme-toggle').ariaLabel = document.documentElement.dataset.theme === 'light' ? t('theme.toDark') : t('theme.toLight'); });

}
