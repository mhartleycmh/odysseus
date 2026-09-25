// Herramientas e integraciones: catalog, permissions, usage, MCP servers and
// the approval mechanism for sensitive operations. Secret values never reach
// this view: MCP env shows variable names only (ADR-011).
import { h, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { formatNumber } from '../core/format.js';
import { panel, viewHeader } from '../components/panel.js';
import { asyncView, alertBox, emptyState } from '../components/states.js';
import { riskBadge, statusBadge, chip } from '../components/badge.js';
import { dataTable } from '../components/table.js';
import { field, formValues } from '../components/form.js';
import { barChart } from '../components/chart.js';

/** @typedef {import('../types.js').AppContext} AppContext */
/** @typedef {import('../types.js').MCPServer} MCPServer */

/** @param {MCPServer['status']} status */
function mcpBadge(status) {
  /** @type {Record<MCPServer['status'], import('../types.js').Tone>} */
  const tones = { connected: 'ok', disconnected: 'idle', error: 'risk', needs_auth: 'warn' };
  return statusBadge(tones[status], t('status.mcp.' + status));
}

/** @param {AppContext} ctx */
export function render(ctx) {
  const host = h('div', { class: 'stack' });
  const el = h('section', { class: 'view', attrs: { 'data-view': 'tools' } }, viewHeader(t('tools.title'), t('tools.lede')), host);
  asyncView(host, () => Promise.all([ctx.source.listTools(), ctx.source.listMcpServers().catch(() => /** @type {MCPServer[]} */ ([]))]), ([tools, servers]) => {
    const categories = [...new Set(tools.map((tool) => tool.category))];
    const toolbar = h('form', { class: 'toolbar', attrs: { role: 'search', 'aria-label': t('tools.filter.label') }, on: { submit: (e) => e.preventDefault() } },
      field({ name: 'q', label: t('tools.filter.search'), type: 'search', className: 'grow', placeholder: t('tools.filter.searchPlaceholder') }),
      field({ name: 'category', label: t('tools.filter.category'), type: 'select', value: '', options: [{ value: '', label: t('common.all') }, ...categories.map((c) => ({ value: c, label: t('tools.category.' + c) }))] }),
      field({ name: 'risk', label: t('tools.filter.risk'), type: 'select', value: '', options: [{ value: '', label: t('common.all') }, ...['bajo', 'medio', 'alto'].map((r) => ({ value: r, label: t('risk.' + r) }))] }));
    const tableHost = h('div');
    const draw = () => {
      const v = formValues(toolbar);
      const q = v.q.trim().toLocaleLowerCase();
      const rows = tools.filter((tool) => (!q || `${tool.name} ${tool.description}`.toLocaleLowerCase().includes(q)) && (!v.category || tool.category === v.category) && (!v.risk || tool.risk === v.risk));
      mount(tableHost, dataTable({
        caption: t('tools.catalog'), rows, rowKey: (tool) => tool.id, emptyText: t('tools.noMatch'), initialSort: { key: 'name', dir: 'asc' },
        columns: [
          { key: 'name', label: t('tools.col.name'), sort: (tool) => tool.name, render: (tool) => h('span', null, h('code', null, tool.name), h('br'), h('span', { class: 'xsmall muted' }, tool.description)) },
          { key: 'category', label: t('tools.col.category'), sort: (tool) => tool.category, render: (tool) => t('tools.category.' + tool.category) },
          { key: 'risk', label: t('tools.col.risk'), sort: (tool) => ['bajo', 'medio', 'alto'].indexOf(tool.risk), render: (tool) => riskBadge(tool.risk) },
          { key: 'access', label: t('tools.col.access'), render: (tool) => tool.readOnly ? statusBadge('ok', t('tools.readOnly')) : statusBadge('warn', t('tools.canWrite')) },
          { key: 'approval', label: t('tools.col.approval'), render: (tool) => tool.requiresApproval ? statusBadge('warn', t('tools.needsApproval')) : h('span', { class: 'muted' }, t('tools.noApproval')) },
          { key: 'enabled', label: t('tools.col.enabled'), render: (tool) => tool.enabled ? statusBadge('ok', t('tools.enabled')) : statusBadge('idle', t('tools.disabled')) },
          { key: 'usedBy', label: t('tools.col.usedBy'), render: (tool) => tool.usedBy.length ? tool.usedBy.join(', ') : h('span', { class: 'muted' }, '—') },
          { key: 'usage', label: t('tools.col.usage'), num: true, sort: (tool) => tool.usageCount, render: (tool) => formatNumber(tool.usageCount) },
        ] }));
    };
    toolbar.addEventListener('input', draw);
    toolbar.addEventListener('change', draw);
    draw();
    const used = tools.filter((tool) => tool.usageCount > 0).sort((a, b) => b.usageCount - a.usageCount).slice(0, 8);
    const sensitive = tools.filter((tool) => tool.requiresApproval || tool.risk === 'alto');
    const origin = tools[0]?.origin || ctx.source.mode;
    const serverOrigin = servers[0]?.origin || ctx.source.mode;
    return [
      panel({ title: t('tools.catalog'), origin, help: t('tools.catalogHelp'), body: [toolbar, tableHost] }),
      h('div', { class: 'grid grid-2' },
        panel({ title: used.length ? t('tools.usageTitle', { name: used[0].name }) : t('tools.usageEmptyTitle'), origin,
                body: used.length ? barChart(used.map((tool) => ({ label: tool.name, value: tool.usageCount })), { title: t('tools.usageChart') }) : emptyState({ title: t('tools.noUsage') }) }),
        panel({ title: t('tools.sensitive'), origin, help: t('tools.sensitiveHelp'), body: [
          alertBox('warn', t('tools.sensitiveMechanism'), h('a', { attrs: { href: '#/aprobaciones' } }, t('tools.openApprovals'))),
          h('ul', { class: 'list' }, sensitive.map((tool) => h('li', { class: 'row-between' }, h('code', null, tool.name), h('span', { class: 'row' }, riskBadge(tool.risk), tool.requiresApproval ? h('span', { class: 'xsmall muted' }, t('tools.needsApproval')) : null)))),
        ] })),
      panel({ title: t('tools.mcpTitle'), origin: serverOrigin, help: t('tools.mcpHelp'), body: servers.length
        ? h('ul', { class: 'mcp-grid' }, servers.map((server) => h('li', { class: 'mcp-card', attrs: { 'data-mcp': server.id } },
            h('div', { class: 'row-between' }, h('h3', null, server.name), mcpBadge(server.status)),
            h('p', { class: 'small muted' }, `${t('tools.transport')}: ${server.transport} · ${t('tools.mcpTools', { enabled: server.enabledToolCount, total: server.toolCount })}`),
            server.envKeys.length ? h('div', { class: 'stack' }, h('span', { class: 'xsmall muted' }, t('tools.envKeys')),
              h('div', { class: 'chip-list' }, server.envKeys.map((key) => chip(`${key} = ••••`)))) : null,
            server.error ? alertBox('warn', t('tools.mcpError'), h('span', null, server.error)) : null)))
        : emptyState({ title: t('tools.noMcp'), text: t('tools.noMcpText') }) }),
    ];
  }, { lines: 6 });
  return { el, title: t('tools.title') };
}
