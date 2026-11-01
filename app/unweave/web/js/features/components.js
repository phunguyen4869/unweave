/* Shared setup/settings component icons and size helpers. */
const svg = paths => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

export const STAGE_ICONS = {
  runtime: svg('<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 9h18M6.5 6.5h.01M9.5 6.5h.01"/>'),
  ffmpeg: svg('<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/>'),
  separation: svg('<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>'),
  youtube: svg('<rect x="2.5" y="5" width="19" height="14" rx="4"/><path d="m10 9.2 4.8 2.8-4.8 2.8V9.2Z"/>'),
};

export const INSTALLABLE_STAGES = new Set(['ffmpeg', 'separation', 'youtube']);

export function sizeText(mb) {
  return mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${mb} MB`;
}

/** Format a raw byte count for download progress (1024-based). */
export function byteText(bytes) {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return '';
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${Math.round(bytes)} B`;
}

/** Format bytes/sec for the first-start download subtitle. */
export function speedText(bps) {
  if (bps == null || !Number.isFinite(bps) || bps <= 0) return '';
  return `${byteText(bps)}/s`;
}

export {svg};
