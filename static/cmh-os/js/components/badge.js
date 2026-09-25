// Status and provenance badges: color plus glyph plus text, never color alone.
import { h } from '../core/dom.js';
import { t } from '../core/i18n.js';

/** @typedef {import('../types.js').Tone} Tone */
/** @typedef {import('../types.js').Origin} Origin */

/** @type {Record<Tone, string>} */
const GLYPH = { ok: '●', warn: '▲', risk: '■', idle: '○', live: '◆' };

/**
 * @param {Tone} tone
 * @param {string} label
 * @returns {HTMLSpanElement}
 */
export function statusBadge(tone, label) {
  return h('span', { class: `badge tone-${tone}` }, h('span', { class: 'badge-glyph', attrs: { 'aria-hidden': 'true' } }, GLYPH[tone]), label);
}

/**
 * Provenance badge (ADR-003). "partial" marks demo data inside live mode.
 * @param {Origin} origin
 * @param {{partial?: boolean}} [options]
 */
export function originBadge(origin, options = {}) {
  const label = origin === 'real' ? t('origin.real') : options.partial ? t('origin.demoNoBackend') : t('origin.demo');
  return h('span', { class: `badge badge-origin origin-${origin}`, attrs: { title: origin === 'real' ? t('origin.realHelp') : t('origin.demoHelp') } }, label);
}

/** @param {import('../types.js').ExecutionStatus|import('../types.js').StepStatus} status @returns {Tone} */
export function toneForRun(status) {
  switch (status) {
    case 'completed': return 'ok';
    case 'running': return 'live';
    case 'waiting_approval': case 'interrupted': case 'paused': return 'warn';
    case 'error': return 'risk';
    default: return 'idle';
  }
}

/** @param {import('../types.js').ExecutionStatus} status */
export function executionBadge(status) {
  return statusBadge(toneForRun(status), t('status.execution.' + status));
}

/** @param {import('../types.js').StepStatus} status */
export function stepBadge(status) {
  return statusBadge(toneForRun(status), t('status.step.' + status));
}

/** @param {import('../types.js').AgentStatus} status */
export function agentBadge(status) {
  /** @type {Record<import('../types.js').AgentStatus, Tone>} */
  const tones = { active: 'ok', running: 'live', paused: 'idle', error: 'risk' };
  return statusBadge(tones[status], t('status.agent.' + status));
}

/** @param {import('../types.js').RiskLevel} risk */
export function riskBadge(risk) {
  /** @type {Record<import('../types.js').RiskLevel, Tone>} */
  const tones = { alto: 'risk', medio: 'warn', bajo: 'ok' };
  return statusBadge(tones[risk], t('risk.' + risk));
}

/** @param {import('../types.js').PermissionLevel} level */
export function permissionBadge(level) {
  /** @type {Record<import('../types.js').PermissionLevel, Tone>} */
  const tones = { lectura: 'ok', escritura: 'warn', admin: 'risk' };
  return statusBadge(tones[level], t('permission.' + level));
}

/**
 * A masked secret: bullets for the eye, real text for screen readers.
 * @param {string|null} fingerprint
 */
export function maskedValue(fingerprint) {
  return h('span', { class: 'mono' },
    h('span', { attrs: { 'aria-hidden': 'true' } }, fingerprint ? `•••• ${fingerprint}` : '••••••••'),
    h('span', { class: 'sr-only' }, fingerprint ? t('security.maskedWithFingerprint', { fp: fingerprint }) : t('security.masked')));
}

/** @param {string} text */
export function chip(text) {
  return h('span', { class: 'chip' }, text);
}
