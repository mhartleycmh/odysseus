// Translation lookup. Every visible string goes through t(); a missing key is
// shown as the key itself and logged once, so gaps are visible, not silent.
import es from '../i18n/es.js';
import { log } from './log.js';

/** @typedef {{[key: string]: string | Dictionary}} Dictionary */

/** @type {Record<string, Dictionary>} */
const DICTIONARIES = { es };
let current = 'es';
const reported = new Set();

/** @param {string} lang */
export function setLanguage(lang) {
  if (DICTIONARIES[lang]) current = lang;
}

export function language() {
  return current;
}

export function languages() {
  return Object.keys(DICTIONARIES);
}

/**
 * @param {string} key dotted path, e.g. "nav.overview"
 * @returns {string|null}
 */
export function lookup(key) {
  /** @type {string|Dictionary|undefined} */
  let node = DICTIONARIES[current];
  for (const part of key.split('.')) {
    if (!node || typeof node === 'string') return null;
    node = node[part];
  }
  return typeof node === 'string' ? node : null;
}

/**
 * @param {string} key
 * @param {Record<string, string|number>} [vars]
 * @returns {string}
 */
export function t(key, vars) {
  const template = lookup(key);
  if (template === null) {
    if (!reported.has(key)) {
      reported.add(key);
      log('warn', 'i18n', 'missing key', { key });
    }
    return key;
  }
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match));
}
