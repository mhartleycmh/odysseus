// Guarded browser storage for per-viewer preferences only. Storage can be
// unavailable (private window, blocked site data): every access is wrapped and
// falls back to an in-memory map so the page still works.

const PREFIX = 'cmh-os:';
/** @type {Map<string, string>} */
const memory = new Map();

/** @returns {Storage|null} */
function backend() {
  try {
    const store = globalThis.localStorage;
    if (!store) return null;
    const probe = PREFIX + '__probe';
    store.setItem(probe, '1');
    store.removeItem(probe);
    return store;
  } catch {
    return null;
  }
}

/**
 * @template T
 * @param {string} key
 * @param {T} fallback
 * @returns {T}
 */
export function readPref(key, fallback) {
  let raw = null;
  try {
    raw = backend()?.getItem(PREFIX + key) ?? memory.get(key) ?? null;
  } catch {
    raw = memory.get(key) ?? null;
  }
  if (raw === null) return fallback;
  try {
    return /** @type {T} */ (JSON.parse(raw));
  } catch {
    return fallback;
  }
}

/**
 * @param {string} key
 * @param {unknown} value
 */
export function writePref(key, value) {
  const raw = JSON.stringify(value);
  memory.set(key, raw);
  try {
    backend()?.setItem(PREFIX + key, raw);
  } catch {
    // Memory copy already holds the value for this page session.
  }
}

/** @param {string} key */
export function removePref(key) {
  memory.delete(key);
  try {
    backend()?.removeItem(PREFIX + key);
  } catch {
    // Nothing persisted to remove.
  }
}
