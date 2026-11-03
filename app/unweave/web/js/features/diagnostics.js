import {$, el, api, notice} from '../core/core.js';
import {t} from '../core/i18n.js';

const ISSUES_URL = 'https://github.com/um1chc5/unweave/issues/new';
const FACEBOOK_URL = 'https://www.facebook.com/um1chc5/';

async function openExternal(url) {
  try {
    await api('/api/window/open-external', {url});
  } catch {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}

function showFallback(text) {
  let dialog = $('diagnostics-dialog');
  if (!dialog) {
    dialog = el('dialog', 'diagnostics-dialog');
    dialog.id = 'diagnostics-dialog';
    dialog.innerHTML = `
      <form method="dialog" class="diagnostics-fallback">
        <header class="dialog-header">
          <h2 data-diag-title></h2>
          <button type="submit" class="close-dialog icon-close" value="cancel"></button>
        </header>
        <p class="dialog-sub" data-diag-hint></p>
        <textarea class="diagnostics-text" readonly rows="16" spellcheck="false"></textarea>
        <div class="dialog-actions">
          <button type="button" class="btn btn-primary" data-diag-select></button>
          <button type="submit" class="btn btn-ghost" value="cancel" data-diag-close></button>
        </div>
      </form>`;
    document.body.append(dialog);
    dialog.querySelector('[data-diag-select]').onclick = () => {
      const area = dialog.querySelector('.diagnostics-text');
      area.focus();
      area.select();
    };
  }
  dialog.querySelector('[data-diag-title]').textContent = t('diagnostics.fallbackTitle');
  dialog.querySelector('[data-diag-hint]').textContent = t('diagnostics.fallbackHint');
  dialog.querySelector('[data-diag-select]').textContent = t('diagnostics.selectAll');
  dialog.querySelector('[data-diag-close]').textContent = t('common.close');
  const area = dialog.querySelector('.diagnostics-text');
  area.value = text;
  dialog.showModal();
  area.focus();
  area.select();
}

export async function copyDiagnostics(jobId) {
  const path = jobId
    ? `/api/diagnostics?job_id=${encodeURIComponent(jobId)}`
    : '/api/diagnostics';
  const {text} = await api(path);
  if (!text) throw new Error(t('diagnostics.empty'));
  try {
    await navigator.clipboard.writeText(text);
    notice(t('diagnostics.copied'), 'success');
  } catch {
    showFallback(text);
  }
}

export async function openGitHubIssues() {
  await openExternal(ISSUES_URL);
}

export async function openFacebook() {
  await openExternal(FACEBOOK_URL);
}
