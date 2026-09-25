// Run event timeline (newest last), readable without the graph.
import { h } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { formatDuration, formatNumber, formatTime } from '../core/format.js';

/** @typedef {import('../types.js').RunEvent} RunEvent */

/**
 * @param {RunEvent} event
 * @returns {string}
 */
export function describeEvent(event) {
  const p = event.payload || {};
  /** @type {string[]} */
  const parts = [];
  if (typeof p.tool === 'string') parts.push(p.tool);
  if (typeof p.model === 'string' && event.kind !== 'tool_started' && event.kind !== 'tool_finished') parts.push(p.model);
  if (typeof p.duration_seconds === 'number') parts.push(formatDuration(p.duration_seconds));
  if (p.error === true) parts.push(t('event.withError'));
  if (typeof p.error === 'string') parts.push(p.error);
  if (p.metrics && typeof p.metrics === 'object') {
    const m = /** @type {Record<string, unknown>} */ (p.metrics);
    if (typeof m.input_tokens === 'number') parts.push(t('event.tokens', { input: formatNumber(m.input_tokens), output: formatNumber(typeof m.output_tokens === 'number' ? m.output_tokens : 0) }));
  }
  if (typeof p.total === 'number' && typeof p.included === 'number') parts.push(t('event.truncated', { included: formatNumber(p.included), total: formatNumber(p.total) }));
  return parts.join(' · ');
}

/** @param {string} kind @returns {import('../types.js').Tone} */
function toneOf(kind) {
  if (kind.endsWith('_error')) return 'risk';
  if (kind.endsWith('completed')) return 'ok';
  if (kind.includes('approval') || kind.includes('interrupted') || kind.includes('stop')) return 'warn';
  if (kind.startsWith('tool') || kind === 'model_metrics') return 'idle';
  return 'live';
}

/**
 * @param {RunEvent[]} events
 * @param {{limit?: number}} [options]
 */
export function timeline(events, options = {}) {
  const shown = options.limit ? events.slice(-options.limit) : events;
  return h('ol', { class: 'timeline', attrs: { 'aria-label': t('event.timeline') } },
    shown.map((event) => h('li', { class: `timeline-item tone-border-${toneOf(event.kind)}` },
      h('span', { class: 'timeline-time mono' }, formatTime(event.at)),
      h('span', { class: 'timeline-kind' }, t('event.kind.' + event.kind)),
      h('span', { class: 'timeline-step' }, event.stepKey || t('event.run')),
      h('span', { class: 'timeline-detail' }, describeEvent(event)))));
}
