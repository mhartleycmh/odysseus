// Seguridad: roles, permissions, policies (with who enforces each), masked
// secrets, sessions, audit and risk indicators under least privilege.
import { h } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { formatDateTime, formatRelative } from '../core/format.js';
import { panel, viewHeader, kpi } from '../components/panel.js';
import { asyncView, alertBox } from '../components/states.js';
import { statusBadge, permissionBadge, chip, originBadge, maskedValue } from '../components/badge.js';
import { dataTable } from '../components/table.js';

/** @typedef {import('../types.js').AppContext} AppContext */

/** @param {AppContext} ctx */
export function render(ctx) {
  const host = h('div', { class: 'stack' });
  const el = h('section', { class: 'view', attrs: { 'data-view': 'security' } }, viewHeader(t('security.title'), t('security.lede')), host);
  asyncView(host, () => Promise.all([ctx.source.getSecurity(), ctx.source.listAgents()]), ([security, agents]) => {
    const admin = agents.filter((a) => a.permissionLevel === 'admin');
    const writers = agents.filter((a) => a.permissionLevel === 'escritura');
    const missing = security.secrets.filter((s) => !s.configured).length;
    const partial = ctx.source.mode === 'real';
    return [
      h('div', { class: 'grid grid-kpi' },
        kpi({ label: t('security.kpi.readOnly'), value: `${agents.length - admin.length - writers.length} / ${agents.length}`, context: t('security.kpi.readOnlyContext') }),
        kpi({ label: t('security.kpi.writers'), value: String(writers.length), context: writers.map((a) => a.name).join(', ') || '—' }),
        kpi({ label: t('security.kpi.admins'), value: String(admin.length), context: admin.map((a) => a.name).join(', ') || '—', delta: admin.length ? { text: t('security.kpi.adminsDelta'), tone: 'warn' } : undefined }),
        kpi({ label: t('security.kpi.secrets'), value: `${security.secrets.length - missing} / ${security.secrets.length}`, context: missing ? t('security.kpi.secretsMissing', { n: missing }) : t('security.kpi.secretsOk') })),
      panel({ title: t('security.policies'), origin: security.policies[0]?.origin || ctx.source.mode, help: t('security.policiesHelp'), flush: true, body: dataTable({
        caption: t('security.policies'), rows: security.policies, rowKey: (p) => p.id,
        columns: [
          { key: 'name', label: t('security.col.policy'), render: (p) => h('span', null, h('strong', null, p.name), h('br'), h('span', { class: 'xsmall muted' }, p.description)) },
          { key: 'scope', label: t('security.col.scope'), render: (p) => p.scope },
          { key: 'effect', label: t('security.col.effect'), render: (p) => statusBadge(p.effect === 'denegar' ? 'risk' : p.effect === 'aprobar' ? 'warn' : 'ok', t('security.effect.' + p.effect)) },
          { key: 'enforced', label: t('security.col.enforcedBy'), render: (p) => h('span', { class: 'row' }, t('security.enforced.' + p.enforcedBy), originBadge(p.origin)) },
        ] }) }),
      h('div', { class: 'grid grid-2' },
        panel({ title: t('security.roles'), origin: security.roles[0]?.origin || 'demo', partial, body: h('ul', { class: 'list' }, security.roles.map((r) => h('li', null,
          h('div', { class: 'row-between' }, h('span', { class: 'list-item-title' }, r.name), h('span', { class: 'small muted' }, t('security.members', { n: r.members }))),
          h('span', { class: 'small muted' }, r.description), h('div', { class: 'chip-list' }, r.permissions.map(chip))))) }),
        panel({ title: t('security.agentPermissions'), origin: agents[0]?.origin || ctx.source.mode, help: t('security.agentPermissionsHelp'), body: h('ul', { class: 'list' }, agents.map((a) => h('li', { class: 'row-between' },
          h('a', { attrs: { href: `#/agentes/${encodeURIComponent(a.id)}` } }, a.name), h('span', { class: 'row' }, permissionBadge(a.permissionLevel), h('span', { class: 'xsmall muted' }, t('security.toolsCount', { n: a.allowedTools.length })))))) })),
      panel({ title: t('security.secrets'), origin: security.secrets[0]?.origin || ctx.source.mode, help: t('security.secretsHelp'), body: [
        alertBox('ok', t('security.secretsNote')),
        dataTable({ caption: t('security.secrets'), rows: security.secrets, rowKey: (s) => s.id, emptyText: t('security.noSecrets'),
          columns: [
            { key: 'name', label: t('security.col.secret'), render: (s) => h('code', null, s.name) },
            { key: 'owner', label: t('security.col.owner'), render: (s) => s.owner },
            { key: 'state', label: t('security.col.state'), render: (s) => s.configured ? statusBadge('ok', t('security.configured')) : statusBadge('warn', t('security.notConfigured')) },
            { key: 'value', label: t('security.col.value'), render: (s) => (s.configured ? maskedValue(s.fingerprint) : '—') },
          ] }),
      ] }),
      h('div', { class: 'grid grid-2' },
        panel({ title: t('security.sessions'), origin: security.sessions[0]?.origin || 'demo', partial, body: h('ul', { class: 'list' }, security.sessions.map((s) => h('li', { class: 'row-between' },
          h('span', null, h('strong', null, s.user), s.current ? h('span', { class: 'badge tone-live', attrs: { style: 'margin-left:8px' } }, t('security.current')) : null),
          h('span', { class: 'small muted' }, t('security.sessionSeen', { when: formatRelative(s.lastSeen) }))))) }),
        panel({ title: t('security.audit'), origin: ctx.source.mode, partial: true, help: t('security.auditHelp'), flush: true, body: dataTable({
          caption: t('security.audit'), rows: security.audit.slice(0, 20), rowKey: (a) => a.id, emptyText: t('security.noAudit'),
          columns: [
            { key: 'at', label: t('security.col.when'), render: (a) => formatDateTime(a.at) },
            { key: 'actor', label: t('security.col.actor'), render: (a) => a.actor },
            { key: 'action', label: t('security.col.action'), render: (a) => h('span', null, a.action, h('br'), h('span', { class: 'xsmall muted' }, a.target)) },
            { key: 'outcome', label: t('security.col.outcome'), render: (a) => statusBadge(a.outcome === 'ok' ? 'ok' : a.outcome === 'rechazado' ? 'warn' : 'risk', t('security.outcome.' + a.outcome)) },
            { key: 'where', label: t('security.col.recordedIn'), render: (a) => t('security.recorded.' + a.recordedIn) },
          ] }) })),
    ];
  }, { lines: 8 });
  return { el, title: t('security.title') };
}
