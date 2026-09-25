// Evaluaciones: cases, datasets, runs, results, comparison against baseline
// and history. Served from demo data until a backend exists (labelled).
import { h, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { formatDateTime, formatPercent } from '../core/format.js';
import { panel, viewHeader, definitionList } from '../components/panel.js';
import { asyncView, alertBox, emptyState, errorMessage } from '../components/states.js';
import { statusBadge } from '../components/badge.js';
import { dataTable } from '../components/table.js';
import { sparkline } from '../components/chart.js';
import { toast } from '../components/toast.js';

/** @typedef {import('../types.js').AppContext} AppContext */
/** @typedef {import('../types.js').Evaluation} Evaluation */

/**
 * @param {number|null} score
 * @param {number|null} baseline
 * @returns {{text: string, tone: import('../types.js').Tone}}
 */
export function compareToBaseline(score, baseline) {
  if (score === null) return { text: t('evaluations.notRun'), tone: 'idle' };
  if (baseline === null) return { text: t('evaluations.noBaseline'), tone: 'idle' };
  const delta = Math.round((score - baseline) * 1000) / 10;
  if (delta > 0) return { text: t('evaluations.better', { pp: delta.toFixed(1) }), tone: 'ok' };
  if (delta < 0) return { text: t('evaluations.worse', { pp: Math.abs(delta).toFixed(1) }), tone: 'risk' };
  return { text: t('evaluations.same'), tone: 'idle' };
}

/** @param {AppContext} ctx */
export function render(ctx) {
  const host = h('div', { class: 'stack' });
  const el = h('section', { class: 'view', attrs: { 'data-view': 'evaluations' } }, viewHeader(t('evaluations.title'), t('evaluations.lede')), host);
  if (!ctx.prefs().flags.evaluations) {
    mount(host, emptyState({ title: t('evaluations.disabled'), action: h('a', { class: 'btn', attrs: { href: '#/configuracion' } }, t('nav.settings')) }));
    return { el, title: t('evaluations.title') };
  }
  let selected = '';
  const partial = !ctx.source.capabilities.evaluations;
  asyncView(host, () => ctx.source.listEvaluations(), (evaluations) => {
    selected = selected || evaluations[0].id;
    const detail = h('div');
    const tableHost = h('div');
    const drawTable = () => mount(tableHost, dataTable({
      caption: t('evaluations.comparison'), rows: evaluations, rowKey: (e) => e.id,
      onOpen: (e) => { selected = e.id; drawDetail(); }, rowLabel: (e) => t('evaluations.openRow', { name: e.name }),
      columns: [
        { key: 'name', label: t('evaluations.col.name'), render: (e) => h('span', null, h('strong', null, e.name), h('br'), h('span', { class: 'xsmall muted' }, e.dataset)) },
        { key: 'metric', label: t('evaluations.col.metric'), render: (e) => e.metric },
        { key: 'score', label: t('evaluations.col.score'), num: true, sort: (e) => e.score ?? -1, render: (e) => formatPercent(e.score) },
        { key: 'baseline', label: t('evaluations.col.baseline'), num: true, render: (e) => formatPercent(e.baselineScore) },
        { key: 'delta', label: t('evaluations.col.delta'), render: (e) => { const c = compareToBaseline(e.score, e.baselineScore); return statusBadge(c.tone, c.text); } },
        { key: 'trend', label: t('evaluations.col.trend'), render: (e) => e.history.length > 1 ? sparkline(e.history.map((p) => p.score), t('evaluations.trendLabel', { name: e.name })) : h('span', { class: 'muted' }, '—') },
        { key: 'run', label: t('evaluations.col.lastRun'), sort: (e) => e.runAt || '', render: (e) => formatDateTime(e.runAt) },
      ] }));
    const drawDetail = () => {
      const evaluation = evaluations.find((e) => e.id === selected);
      if (!evaluation) return;
      const run = h('button', { class: 'btn btn-primary', attrs: { type: 'button', 'data-action': 'run-evaluation' }, on: { click: async () => {
        run.setAttribute('aria-busy', 'true');
        try {
          const updated = await ctx.source.runEvaluation(evaluation.id);
          Object.assign(evaluation, updated);
          toast(t('evaluations.ran', { name: evaluation.name, score: formatPercent(evaluation.score) }), 'ok');
          drawTable();
          drawDetail();
        } catch (error) {
          toast(errorMessage(error), 'risk');
        } finally {
          run.removeAttribute('aria-busy');
        }
      } } }, t('evaluations.run'));
      const pendingCases = evaluation.cases.filter((c) => c.result === 'pendiente').length;
      mount(detail,
        h('div', { class: 'row-between' }, h('h3', null, evaluation.name), run),
        definitionList([[t('evaluations.dataset'), evaluation.dataset], [t('evaluations.target'), evaluation.target], [t('evaluations.col.metric'), evaluation.metric],
          [t('evaluations.cases'), t('evaluations.casesValue', { n: evaluation.cases.length, pending: pendingCases })], [t('evaluations.col.lastRun'), formatDateTime(evaluation.runAt)]]),
        evaluation.runAt === null ? alertBox('idle', t('evaluations.neverRun')) : null,
        dataTable({
          caption: t('evaluations.cases'), rows: evaluation.cases, rowKey: (c) => c.id, emptyText: t('evaluations.noCases'),
          columns: [
            { key: 'input', label: t('evaluations.col.input'), render: (c) => h('code', { class: 'wrap-anywhere' }, c.input) },
            { key: 'expected', label: t('evaluations.col.expected'), render: (c) => c.expected },
            { key: 'result', label: t('evaluations.col.result'), render: (c) => statusBadge(c.result === 'ok' ? 'ok' : c.result === 'fallo' ? 'risk' : 'idle', t('evaluations.result.' + c.result)) },
            { key: 'score', label: t('evaluations.col.score'), num: true, render: (c) => c.score === null ? '—' : String(c.score) },
          ] }),
        h('h4', null, t('evaluations.history')),
        evaluation.history.length ? h('ol', { class: 'list' }, [...evaluation.history].reverse().map((p) => h('li', { class: 'row-between' }, formatDateTime(p.runAt), h('strong', null, formatPercent(p.score)))))
          : emptyState({ title: t('evaluations.noHistory') }));
    };
    drawTable();
    drawDetail();
    const origin = evaluations[0]?.origin || 'demo';
    return [
      partial ? alertBox('warn', t('evaluations.noBackend')) : null,
      panel({ title: t('evaluations.comparison'), origin, partial, help: t('evaluations.comparisonHelp'), body: tableHost, flush: true }),
      panel({ title: t('evaluations.detail'), origin, partial, body: detail }),
    ];
  }, { isEmpty: (list) => list.length === 0, empty: () => emptyState({ title: t('evaluations.empty'), text: t('evaluations.emptyText') }) });
  return { el, title: t('evaluations.title') };
}
