// User preferences: defaults, sanitizing load and persistence (per viewer).
import { readPref, writePref } from './storage.js';

/** @typedef {import('../types.js').Prefs} Prefs */

/** @type {Prefs} */
export const DEFAULT_PREFS = Object.freeze({
  theme: 'system',
  motion: 'system',
  mode: 'auto',
  language: 'es',
  flags: { chatModel: false, simulateFailures: false, evaluations: true },
  // Per execution (all steps together). The backend's max_steps=12 is per step,
  // so a seven-step flow needs about 20 iterations; 40 leaves headroom.
  limits: { maxIterations: 40, timeoutSeconds: 600, budgetUsd: 2 },
  chatModel: null,
  actor: 'usuario',
});

/**
 * @param {unknown} value
 * @param {number} min
 * @param {number} max
 * @param {number} fallback
 */
function clampNumber(value, min, max, fallback) {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max ? value : fallback;
}

/**
 * Accept only known values: stored preferences may come from an older version.
 * @param {unknown} raw
 * @returns {Prefs}
 */
export function sanitizePrefs(raw) {
  const value = raw && typeof raw === 'object' ? /** @type {Record<string, unknown>} */ (raw) : {};
  const flags = value.flags && typeof value.flags === 'object' ? /** @type {Record<string, unknown>} */ (value.flags) : {};
  const limits = value.limits && typeof value.limits === 'object' ? /** @type {Record<string, unknown>} */ (value.limits) : {};
  const chat = value.chatModel && typeof value.chatModel === 'object' ? /** @type {Record<string, unknown>} */ (value.chatModel) : null;
  return {
    theme: value.theme === 'light' || value.theme === 'dark' ? value.theme : 'system',
    motion: value.motion === 'reduced' || value.motion === 'full' ? value.motion : 'system',
    mode: value.mode === 'demo' ? 'demo' : 'auto',
    language: value.language === 'es' ? 'es' : 'es',
    flags: {
      chatModel: flags.chatModel === true,
      simulateFailures: flags.simulateFailures === true,
      evaluations: flags.evaluations !== false,
    },
    limits: {
      maxIterations: clampNumber(limits.maxIterations, 1, 200, DEFAULT_PREFS.limits.maxIterations),
      timeoutSeconds: clampNumber(limits.timeoutSeconds, 10, 86400, DEFAULT_PREFS.limits.timeoutSeconds),
      budgetUsd: clampNumber(limits.budgetUsd, 0.01, 1000, DEFAULT_PREFS.limits.budgetUsd),
    },
    chatModel: chat && typeof chat.endpointId === 'string' && typeof chat.model === 'string' && chat.endpointId && chat.model
      ? { endpointId: chat.endpointId, model: chat.model } : null,
    actor: typeof value.actor === 'string' && value.actor.trim() ? value.actor.trim().slice(0, 60) : 'usuario',
  };
}

/** @returns {Prefs} */
export function loadPrefs() {
  return sanitizePrefs(readPref('prefs', DEFAULT_PREFS));
}

/** @param {Prefs} prefs */
export function savePrefs(prefs) {
  writePref('prefs', sanitizePrefs(prefs));
}
