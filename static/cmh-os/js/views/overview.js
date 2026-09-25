// Vista general: system summary, services, alerts, recent activity and a live
// mini-graph of the most relevant active run.
import { h, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { formatNumber, formatPercent, formatRelative, formatUsd, shortId } from '../core/format.js';
import { panel, kpi, viewHeader } from '../components/panel.js';
import { asyncView, alertBox, emptyState } from '../components/states.js';
import { executionBadge, statusBadge } from '../components/badge.js';
import { dataTable } from '../components/table.js';
import { createGraph } from '../components/graph.js';
import { isFresh } from '../services/run-state.js';
import { openRunFeed } from '../services/run-feed.js';

/** @typedef {import('../types.js').AppContext} AppContext */
/** @typedef {import('../types.js').Execution} Execution */

/**
 * @param {AppContext} ctx
 * @returns {{el: HTMLElement, title: string, destroy: () => void}}
 */
export function render(ctx) {
  const body = h('div', { class: 'stack' });
  /** @type {(() => void)[]} */
  const cleanups = [];
  let disposed = false;
  const el = h('section', { class: 'view', attrs: { 'data-view': 'overview' } },
    viewHeader(t('overview.title'), t('overview.lede'), [
      h('a', { class: 'btn btn-primary', attrs: { href: '#/ejecuciones?nuevo=1' } }, t('overview.newExecution')),
      h('a', { class: 'btn', attrs: { href: '#/orquestacion' } }, t('overview.openOrchestration')),
    ]),
    body);

  const source = ctx.source;
  const view = asyncView(body, async () => {
    const [agents, executions, approvals, services, servers] = await Promise.all([
      source.listAgents(), source.listExecutions(), source.listApprovals(), source.getServices(), source.listMcpServers().catch(() => []),
    ]);
    return { agents, executions, approvals, services, servers };
  }, ({ agents, executions, approvals, services, servers }) => {
    const active = agents.filter((a) => a.status === 'active' || a.status === 'running').length;
    const running = executions.filter((e) => e.status === 'running').length;
    const waiting = executions.filter((e) => e.status === 'waiting_approval').length;
    const pending = approvals.filter((a) => a.status === 'pendiente');
    const finished = executions.filter((e) => e.status === 'completed' || e.status === 'error');
    const successRate = finished.length ? finished.filter((e) => e.status === 'completed').length / finished.length : null;
    // Only measured runs count: a live list has no event data yet, and its zeros are unknown.
    const measuredRuns = executions.filter((e) => e.usage.measured);
    const tokens = measuredRuns.reduce((sum, e) => sum + e.usage.tokensIn + e.usage.tokensOut, 0);
    const cost = measuredRuns.some((e) => e.usage.costUsd !== null) ? measuredRuns.reduce((sum, e) => sum + (e.usage.costUsd || 0), 0) : null;
    const origin = source.mode;

    const kpis = h('div', { class: 'grid grid-kpi', attrs: { 'data-block': 'kpis' } },
      kpi({ label: t('overview.kpi.agents'), value: `${active} / ${agents.length}`, context: t('overview.kpi.agentsContext', { running: agents.filter((a) => a.status === 'running').length }) }),
      kpi({ label: t('overview.kpi.running'), value: formatNumber(running), context: t('overview.kpi.runningContext', { waiting }) }),
      kpi({ label: t('overview.kpi.approvals'), value: formatNumber(pending.length), context: t('overview.kpi.approvalsContext', { high: pending.filter((a) => a.risk === 'alto').length }),
            delta: pending.length ? { text: t('overview.kpi.approvalsDelta'), tone: 'warn' } : undefined }),
      kpi({ label: t('overview.kpi.success'), value: formatPercent(successRate), context: t('overview.kpi.successContext', { n: finished.length }) }),
      kpi({ label: t('overview.kpi.usage'), value: !measuredRuns.length ? '—' : cost !== null ? formatUsd(cost) : `${formatNumber(tokens)} tk`,
            context: !measuredRuns.length ? t('overview.kpi.usageNotMeasured') : cost !== null ? t('overview.kpi.usageTokens', { tokens: formatNumber(tokens) }) : t('overview.kpi.usageNoPrice') }));

    const alerts = [];
    const failed = executions.filter((e) => e.status === 'error').slice(0, 3);
    for (const e of failed) alerts.push(alertBox('risk', t('overview.alert.failed', { id: shortId(e.id), name: e.workflowName }), h('a', { attrs: { href: `#/ejecuciones/${encodeURIComponent(e.id)}` } }, t('overview.alert.openExecution'))));
    const high = pending.filter((a) => a.risk === 'alto');
    if (high.length) alerts.push(alertBox('warn', t('overview.alert.highRisk', { n: high.length }), h('a', { attrs: { href: '#/aprobaciones' } }, t('overview.alert.review'))));
    for (const s of servers.filter((sv) => sv.status !== 'connected')) alerts.push(alertBox('warn', t('overview.alert.mcp', { name: s.name }), h('span', null, s.error || t('status.mcp.' + s.status))));
    if (!alerts.length) alerts.push(alertBox('ok', t('overview.alert.none')));

    const servicesList = h('ul', { class: 'list', attrs: { 'data-block': 'services' } }, services.map((s) =>
      h('li', { class: 'row-between' }, h('span', { class: 'list-item-title' }, s.name), h('span', { class: 'row' }, statusBadge(s.tone, t('tone.' + s.tone)), h('span', { class: 'small muted' }, s.detail)))));

    const recent = dataTable({
      caption: t('overview.recent'), rowKey: (e) => e.id, rows: executions.slice(0, 6),
      onOpen: (e) => ctx.navigate(`#/ejecuciones/${encodeURIComponent(e.id)}`), rowLabel: (e) => t('executions.openRow', { id: shortId(e.id) }),
      columns: [
        { key: 'id', label: t('executions.col.id'), render: (e) => h('span', { class: 'mono' }, shortId(e.id)) },
        { key: 'flow', label: t('executions.col.workflow'), render: (e) => e.workflowName },
        { key: 'status', label: t('executions.col.status'), render: (e) => executionBadge(e.status) },
        { key: 'created', label: t('executions.col.created'), render: (e) => formatRelative(e.createdAt) },
      ],
    });

    const liveHost = h('div', { attrs: { 'data-block': 'live' } });
    const focus = executions.find((e) => e.status === 'running') || executions.find((e) => e.status === 'waiting_approval') || executions[0];
    if (focus) mountLive(focus.id, liveHost);
    else mount(liveHost, emptyState({ title: t('overview.noRuns'), action: h('a', { class: 'btn', attrs: { href: '#/ejecuciones?nuevo=1' } }, t('overview.newExecution')) }));

    return [
      kpis,
      h('div', { class: 'grid grid-main-side' },
        panel({ title: t('overview.liveTitle'), origin, help: t('overview.liveHelp'), body: liveHost,
                actions: focus ? h('a', { class: 'btn btn-sm', attrs: { href: `#/orquestacion/${encodeURIComponent(focus.id)}` } }, t('overview.openOrchestration')) : null }),
        h('div', { class: 'stack' },
          panel({ title: t('overview.services'), origin, body: servicesList, level: 'h2' }),
          panel({ title: t('overview.alerts'), origin, body: h('div', { class: 'stack' }, alerts) }))),
      panel({ title: t('overview.recent'), origin, body: recent, flush: true,
              actions: h('a', { class: 'btn btn-sm btn-ghost', attrs: { href: '#/ejecuciones' } }, t('common.viewAll')) }),
    ];
  }, { lines: 6 });

  /** @param {string} id @param {HTMLElement} host */
  async function mountLive(id, host) {
    try {
      const snapshot = await source.getExecution(id);
      // The user may have left while the snapshot loaded: open nothing then.
      if (disposed) return;
      const graph = createGraph({ execution: snapshot, orientation: window.innerWidth < 640 ? 'vertical' : 'horizontal', reducedMotion: ctx.reducedMotion,
                                  onSelect: () => ctx.navigate(`#/orquestacion/${encodeURIComponent(id)}`) });
      const caption = h('p', { class: 'small muted' }, `${snapshot.workflowName} · ${shortId(snapshot.id)}`);
      mount(host, caption, graph.el);
      const feed = openRunFeed(source, snapshot, { onChange(execution, event) {
        graph.update(execution);
        if (event && isFresh(event)) graph.onEvent(event);
      } });
      cleanups.push(() => { feed.dispose(); graph.destroy(); });
    } catch (error) {
      mount(host, alertBox('warn', t('overview.liveUnavailable'), h('span', null, error instanceof Error ? error.message : String(error))));
    }
  }

  return { el, title: t('overview.title'), destroy: () => { disposed = true; view.dispose(); cleanups.forEach((fn) => fn()); } };
}
