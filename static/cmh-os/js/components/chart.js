// Small SVG charts following the CMH chart rules: axis from zero, horizontal
// bars for comparisons, values labelled on the mark, the title states the finding.
import { h, s } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { formatDuration, formatNumber } from '../core/format.js';

/** @typedef {import('../types.js').Span} Span */

/**
 * @param {{label: string, value: number, display?: string}[]} data
 * @param {{title: string, unit?: string}} options
 */
export function barChart(data, options) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const rowH = 30;
  const labelW = 150;
  const width = 560;
  const height = data.length * rowH + 8;
  const svg = s('svg', { class: 'chart', attrs: { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': options.title } });
  data.forEach((d, i) => {
    const y = i * rowH + 4;
    const w = Math.max(2, ((width - labelW - 70) * d.value) / max);
    svg.append(
      s('text', { class: 'chart-label', attrs: { x: String(labelW - 8), y: String(y + 17), 'text-anchor': 'end' } }, d.label.length > 22 ? d.label.slice(0, 21) + '…' : d.label),
      s('rect', { class: `chart-bar series-${(i % 3) + 1}`, attrs: { x: String(labelW), y: String(y + 4), width: String(w), height: String(rowH - 12), rx: '2' } }),
      s('text', { class: 'chart-value', attrs: { x: String(labelW + w + 6), y: String(y + 17) } }, d.display || formatNumber(d.value)));
  });
  const table = h('table', { class: 'sr-only' }, h('caption', null, options.title),
    h('tbody', null, data.map((d) => h('tr', null, h('th', { attrs: { scope: 'row' } }, d.label), h('td', null, d.display || formatNumber(d.value))))));
  return h('figure', { class: 'chart-figure' }, h('figcaption', { class: 'chart-title' }, options.title), svg, table);
}

/**
 * @param {number[]} values
 * @param {string} label
 */
export function sparkline(values, label) {
  const width = 120;
  const height = 32;
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((v, i) => `${Math.round(i * step)},${Math.round(height - 3 - (v / max) * (height - 6))}`).join(' ');
  return s('svg', { class: 'sparkline', attrs: { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': label, preserveAspectRatio: 'none' } },
    s('line', { class: 'sparkline-base', attrs: { x1: '0', y1: String(height - 1), x2: String(width), y2: String(height - 1) } }),
    s('polyline', { class: 'sparkline-line', attrs: { points } }));
}

/**
 * Trace waterfall: one row per span, bar offset by start time.
 * @param {Span[]} spans
 * @param {number} totalMs
 * @param {string} title
 */
export function waterfall(spans, totalMs, title) {
  const total = Math.max(1, totalMs, ...spans.map((sp) => sp.startMs + sp.durationMs));
  const rows = spans.map((span) => {
    const left = (span.startMs / total) * 100;
    const width = Math.max(0.6, (span.durationMs / total) * 100);
    return h('li', { class: `wf-row wf-${span.kind} wf-${span.status}` },
      h('span', { class: 'wf-name' }, h('span', { class: 'wf-kind' }, t('trace.kind.' + span.kind)), span.name),
      h('span', { class: 'wf-track' },
        h('span', { class: 'wf-bar', attrs: { style: `left:${left.toFixed(2)}%;width:${width.toFixed(2)}%` } })),
      h('span', { class: 'wf-meta' }, formatDuration(span.durationMs / 1000), span.tokens ? ` · ${formatNumber(span.tokens)} tk` : ''));
  });
  return h('figure', { class: 'waterfall' }, h('figcaption', { class: 'chart-title' }, title),
    rows.length ? h('ol', { class: 'wf-list' }, rows) : h('p', { class: 'muted' }, t('trace.noSpans')));
}
