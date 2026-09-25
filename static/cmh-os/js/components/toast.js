// Non-blocking notifications in a polite live region.
import { h } from '../core/dom.js';
import { t } from '../core/i18n.js';

/** @type {HTMLElement|null} */
let region = null;

function ensureRegion() {
  if (region && region.isConnected) return region;
  region = h('div', { class: 'toasts', attrs: { 'aria-live': 'polite', 'aria-atomic': 'false', role: 'region', 'aria-label': t('common.notifications') } });
  document.body.append(region);
  return region;
}

/**
 * @param {string} message
 * @param {import('../types.js').Tone} [tone]
 * @param {number} [ms]
 */
export function toast(message, tone = 'live', ms = 5000) {
  const node = h('div', { class: `toast tone-${tone}`, attrs: { role: tone === 'risk' ? 'alert' : 'status' } },
    h('p', null, message),
    h('button', { class: 'close-btn', attrs: { type: 'button', 'aria-label': t('common.close') }, on: { click: () => node.remove() } }, '×'));
  ensureRegion().append(node);
  setTimeout(() => node.remove(), ms);
  return node;
}
