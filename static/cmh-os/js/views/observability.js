// Observabilidad: traces with filters, latency, tokens, cost, errors, success
// rate, this session's API calls and structured logs; trace waterfall detail.
import { h, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { formatDateTime, formatDuration, formatNumber, formatPercent, formatUsd, formatTime, shortId } from '../core/format.js';
import { recentLogs } from '../core/log.js';
import { callMetrics } from '../services/http.js';
import { panel, viewHeader, kpi, definitionList, mutableHeader } from '../components/panel.js';
import { asyncView, emptyState } from '../components/states.js';
import { executionBadge, statusBadge } from '../components/badge.js';
import { dataTable } from '../components/table.js';
import { field, formValues } from '../components/form.js';
import { waterfall, barChart } from '../components/chart.js';

/** @typedef {import('../types.js').AppContext} AppContext */
/** @typedef {import('../types.js').Trace} Trace */
/** @typedef {import('../core/router.js').RouteMatch} RouteMatch */

/**
 * Filter traces by status, agent, workflow name and free text.
 * @param {Trace[]} traces
 * @param {{status?: string, agent?: string, q?: string}} filter
 */
export function filterTraces(traces, filter) {
  const q = (filter.q || '').trim().toLocaleLowerCase();
  return traces.filter((trace) => (!filter.status || trace.status === filter.status)
    && (!filter.agent || trace.agents.includes(filter.agent))
    && (!q || `${trace.executionId} ${trace.name}`.toLocaleLowerCase().includes(q)));
}

/**
 * @param {AppContext} ctx
 * @param {RouteMatch} match
 */
export function renderList(ctx, match) {
  const host = h('div', { class: 'stack' });
  const el = h('section', { class: 'view', attrs: { 'data-view': 'observability' } }, viewHeader(t('observability.title'), t('observability.lede')), host);
  asyncView(host, () => ctx.source.listTraces(), (traces) => {
    const agents = [...new Set(traces.flatMap((tr) => tr.agents))].sort();
    const toolbar = h('form', { class: 'toolbar', attrs: { role: 'search', 'aria-label': t('observability.filter.label') }, on: { submit: (e) => e.preventDefault() } },
      field({ name: 'q', label: t('observability.filter.search'), type: 'search', className: 'grow', placeholder: t('observability.filter.searchPlaceholder') }),
      field({ name: 'status', label: t('observability.filter.status'), type: 'select', value: match.query.get('estado') || '',
              options: [{ value: '', label: t('common.all') }, ...['completed', 'error', 'running', 'waiting_approval', 'interrupted'].map((s) => ({ value: s, label: t('status.execution.' + s) }))] }),
      field({ name: 'agent', label: t('observability.filter.agent'), type: 'select', value: '', options: [{ value: '', label: t('common.all') }, ...agents.map((a) => ({ value: a, label: a }))] }));
    const kpis = h('div', { class: 'grid grid-kpi' });
    const tableHost = h('div');
    const chartHost = h('div');
    const count = h('p', { class: 'small muted', attrs: { 'aria-live': 'polite', 'data-count': '' } });
    const draw = () => {
      const rows = filterTraces(traces, formValues(toolbar));
      const finished = rows.filter((r) => r.status === 'completed' || r.status === 'error');
      const toolSpans = rows.flatMap((r) => r.spans.filter((s) => s.kind === 'herramienta' && s.status !== 'running'));
      const modelSpans = rows.flatMap((r) => r.spans.filter((s) => s.kind === 'modelo'));
      const cost = rows.some((r) => r.costUsd !== null) ? rows.reduce((sum, r) => sum + (r.costUsd || 0), 0) : null;
      count.textContent = t('observability.count', { shown: rows.length, total: traces.length });
      mount(kpis,
        kpi({ label: t('observability.kpi.success'), value: formatPercent(finished.length ? finished.filter((r) => r.status === 'completed').length / finished.length : null), context: t('observability.kpi.successContext', { n: finished.length }) }),
        kpi({ label: t('observability.kpi.toolLatency'), value: toolSpans.length ? formatDuration(toolSpans.reduce((s, sp) => s + sp.durationMs, 0) / toolSpans.length / 1000) : '—', context: t('observability.kpi.toolLatencyContext', { n: toolSpans.length }) }),
        kpi({ label: t('observability.kpi.modelLatency'), value: modelSpans.length ? formatDuration(modelSpans.reduce((s, sp) => s + sp.durationMs, 0) / modelSpans.length / 1000) : '—', context: t('observability.kpi.modelLatencyContext', { n: modelSpans.length }) }),
        kpi({ label: t('observability.kpi.tokens'), value: rows.some((r) => r.measured) ? formatNumber(rows.reduce((s, r) => s + r.tokensIn + r.tokensOut, 0)) : '—', context: cost !== null ? formatUsd(cost) : t('observability.kpi.noCost') }),
        kpi({ label: t('observability.kpi.errors'), value: formatNumber(rows.reduce((s, r) => s + r.errors, 0)), context: t('observability.kpi.errorsContext') }));
      mount(tableHost, dataTable({
        caption: t('observability.traces'), rows, rowKey: (r) => r.id, emptyText: t('observability.noMatch'),
        onOpen: (r) => ctx.navigate(`#/observabilidad/${encodeURIComponent(r.executionId)}`), rowLabel: (r) => t('observability.openTrace', { id: shortId(r.executionId) }),
        initialSort: { key: 'started', dir: 'desc' },
        columns: [
          { key: 'id', label: t('executions.col.id'), render: (r) => h('span', { class: 'mono' }, shortId(r.executionId)) },
          { key: 'name', label: t('executions.col.workflow'), sort: (r) => r.name, render: (r) => r.name },
          { key: 'status', label: t('executions.col.status'), sort: (r) => r.status, render: (r) => executionBadge(r.status) },
          { key: 'duration', label: t('observability.col.duration'), num: true, sort: (r) => r.durationMs, render: (r) => r.spans.length ? formatDuration(r.durationMs / 1000) : '—' },
          { key: 'tokens', label: t('executions.col.tokens'), num: true, sort: (r) => r.tokensIn + r.tokensOut, render: (r) => (r.measured ? formatNumber(r.tokensIn + r.tokensOut) : '—') },
          { key: 'cost', label: t('executions.col.cost'), num: true, sort: (r) => r.costUsd || 0, render: (r) => formatUsd(r.costUsd) },
          { key: 'errors', label: t('observability.col.errors'), num: true, sort: (r) => r.errors, render: (r) => !r.measured ? '—' : r.errors ? statusBadge('risk', String(r.errors)) : '0' },
          { key: 'started', label: t('executions.col.created'), sort: (r) => r.startedAt, render: (r) => formatDateTime(r.startedAt) },
        ] }));
      const byAgent = new Map();
      for (const r of rows) for (const sp of r.spans.filter((s) => s.kind === 'modelo' && s.stepKey)) byAgent.set(sp.stepKey, (byAgent.get(sp.stepKey) || 0) + sp.tokens);
      const top = [...byAgent.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
      mount(chartHost, top.length ? barChart(top.map(([label, value]) => ({ label, value, display: `${formatNumber(value)} tk` })), { title: t('observability.tokensByStep', { step: top[0][0] }) })
        : emptyState({ title: t('observability.noSpans'), text: ctx.source.mode === 'real' ? t('observability.noSpansReal') : undefined }));
    };
    toolbar.addEventListener('input', draw);
    toolbar.addEventListener('change', draw);
    draw();
    const calls = callMetrics().slice(-12).reverse();
    const logs = recentLogs().slice(-12).reverse();
    const origin = traces[0]?.origin || ctx.source.mode;
    return [
      panel({ title: t('observability.filters'), origin, body: [toolbar, count] }),
      kpis,
      panel({ title: t('observability.traces'), origin, body: tableHost, flush: true }),
      h('div', { class: 'grid grid-2' },
        panel({ title: t('observability.tokensTitle'), origin, body: chartHost }),
        panel({ title: t('observability.calls'), origin: 'real', help: t('observability.callsHelp'), flush: true, body: dataTable({
          caption: t('observability.calls'), rows: calls, rowKey: (c) => c.at + c.path + c.attempt, emptyText: ctx.source.mode === 'demo' ? t('observability.noCallsDemo') : t('observability.noCalls'),
          columns: [
            { key: 'at', label: t('observability.col.time'), render: (c) => formatTime(c.at) },
            { key: 'call', label: t('observability.col.call'), render: (c) => h('code', { class: 'xsmall' }, `${c.method} ${c.path.split('?')[0]}`) },
            { key: 'status', label: t('observability.col.status'), render: (c) => statusBadge(c.status >= 200 && c.status < 400 ? 'ok' : 'risk', c.status ? String(c.status) : t('observability.noResponse')) },
            { key: 'ms', label: t('observability.col.latency'), num: true, render: (c) => `${formatNumber(c.ms)} ms` },
          ] }) })),
      panel({ title: t('observability.logs'), origin: 'real', help: t('observability.logsHelp'), body: logs.length
        ? h('ol', { class: 'log-list' }, logs.map((l) => h('li', { class: `log-${l.level}` }, h('span', { class: 'mono xsmall' }, formatTime(l.at)), ' ', h('strong', null, l.level.toUpperCase()), ` ${l.module}: ${l.message}`)))
        : emptyState({ title: t('observability.noLogs') }) }),
    ];
  }, { lines: 8 });
  return { el, title: t('observability.title') };
}

/**
 * @param {AppContext} ctx
 * @param {RouteMatch} match
 */
export function renderTrace(ctx, match) {
  const id = match.params.id;
  const header = mutableHeader(t('observability.traceTitle', { id: shortId(id) }), '');
  header.setCrumb(h('nav', { class: 'breadcrumb small', attrs: { 'aria-label': t('common.breadcrumb') } }, h('a', { attrs: { href: '#/observabilidad' } }, t('observability.title')), ' / ', shortId(id)));
  header.setActions(h('a', { class: 'btn', attrs: { href: `#/ejecuciones/${encodeURIComponent(id)}` } }, t('observability.openExecution')));
  const host = h('div', { class: 'stack' });
  const el = h('section', { class: 'view', attrs: { 'data-view': 'trace' } }, header.el, host);
  const view = asyncView(host, () => ctx.source.getTrace(id), (trace) => {
    header.setLede(trace.name);
    return [
      h('div', { class: 'grid grid-main-side' },
        panel({ title: t('observability.waterfall'), origin: trace.origin, help: t('observability.waterfallHelp'), body: waterfall(trace.spans, trace.durationMs, t('observability.waterfallCaption', { n: trace.spans.length })) }),
        panel({ title: t('executions.summary'), origin: trace.origin, body: definitionList([
          [t('executions.col.status'), executionBadge(trace.status)], [t('observability.col.duration'), formatDuration(trace.durationMs / 1000)],
          [t('executions.usage.tokens'), t('executions.usage.tokensValue', { input: formatNumber(trace.tokensIn), output: formatNumber(trace.tokensOut) })],
          [t('executions.usage.cost'), formatUsd(trace.costUsd)], [t('observability.col.errors'), formatNumber(trace.errors)], [t('observability.agents'), trace.agents.join(', ')],
        ]) })),
    ];
  }, { lines: 8 });
  return { el, title: t('observability.traceTitle', { id: shortId(id) }), destroy: () => view.dispose() };
}
