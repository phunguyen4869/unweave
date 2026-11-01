import {$} from './core.js';
import {t, getLang, setLang} from './i18n.js';

function syncButton() {
  const lang = getLang();
  const button = $('lang-toggle');
  button.textContent = lang === 'vi' ? 'EN' : 'VI';
  const title = t(lang === 'vi' ? 'lang.toEn' : 'lang.toVi');
  button.title = button.ariaLabel = title;
}

export function initLangToggle() {
  $('lang-toggle').onclick = () => { setLang(getLang() === 'vi' ? 'en' : 'vi'); syncButton(); };
  syncButton();
}
