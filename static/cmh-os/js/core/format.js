// Number, date and duration formatting for es-PE (Lima time).

const LOCALE = 'es-PE';
const TIME_ZONE = 'America/Lima';

/** @param {string|null|undefined} iso */
function toDate(iso) {
  if (!iso) return null;
  // The backend stores naive UTC timestamps without a zone suffix.
  const normalized = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z';
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** @param {string|null|undefined} iso @returns {string} */
export function formatDateTime(iso) {
  const date = toDate(iso);
  if (!date) return '—';
  return new Intl.DateTimeFormat(LOCALE, {
    timeZone: TIME_ZONE, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date);
}

/** @param {string|null|undefined} iso @returns {string} */
export function formatTime(iso) {
  const date = toDate(iso);
  if (!date) return '—';
  return new Intl.DateTimeFormat(LOCALE, { timeZone: TIME_ZONE, hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date);
}

/**
 * "hace 5 min" style relative time.
 * @param {string|null|undefined} iso
 * @param {number} [now]
 */
export function formatRelative(iso, now = Date.now()) {
  const date = toDate(iso);
  if (!date) return '—';
  const seconds = Math.round((date.getTime() - now) / 1000);
  const rtf = new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto' });
  const abs = Math.abs(seconds);
  if (abs < 60) return rtf.format(seconds, 'second');
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), 'minute');
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), 'hour');
  return rtf.format(Math.round(seconds / 86400), 'day');
}

/** @param {number|null|undefined} seconds @returns {string} */
export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds < 10 ? formatNumber(seconds, 1) : Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}

/** @param {number|null|undefined} value @param {number} [digits] */
export function formatNumber(value, digits = 0) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

/** @param {number|null|undefined} ratio 0..1 */
export function formatPercent(ratio) {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return '—';
  return new Intl.NumberFormat(LOCALE, { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(ratio);
}

/** @param {number|null|undefined} value */
export function formatUsd(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return 'US$ ' + new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: value < 1 ? 4 : 2 }).format(value);
}

/** @param {string} id @param {number} [size] */
export function shortId(id, size = 8) {
  return id.length > size ? id.slice(0, size) : id;
}
