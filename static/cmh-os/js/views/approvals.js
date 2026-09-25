// Aprobaciones humanas: queue, action detail with risk and impact, decision
// with justification and an auditable history.
import { h, mount, uid } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { formatDateTime, formatRelative } from '../core/format.js';
import { panel, viewHeader, definitionList } from '../components/panel.js';
import { asyncView, alertBox, emptyState, errorMessage } from '../components/states.js';
import { riskBadge, statusBadge } from '../components/badge.js';
import { dataTable } from '../components/table.js';
import { confirmDialog } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { field, formValues } from '../components/form.js';

/** @typedef {import('../types.js').AppContext} AppContext */
/** @typedef {import('../types.js').ApprovalRequest} ApprovalRequest */
/** @typedef {import('../core/router.js').RouteMatch} RouteMatch */

/** @param {import('../types.js').ApprovalStatus} status */
function approvalStatusBadge(status) {
  return statusBadge(status === 'pendiente' ? 'warn' : status === 'aprobada' ? 'ok' : 'risk', t('approvals.status.' + status));
}

/** @param {string} diff */
function diffView(diff) {
  return h('pre', { class: 'code', attrs: { 'aria-label': t('approvals.diff') } }, diff.split('\n').map((line) =>
    h('span', { class: line.startsWith('+') && !line.startsWith('+++') ? 'diff-add' : line.startsWith('-') && !line.startsWith('---') ? 'diff-del' : '' }, line + '\n')));
}

/**
 * @param {AppContext} ctx
 * @param {RouteMatch} match
 */
export function render(ctx, match) {
  const host = h('div', { class: 'stack' });
  const el = h('section', { class: 'view', attrs: { 'data-view': 'approvals' } }, viewHeader(t('approvals.title'), t('approvals.lede')), host);
  let selectedId = match.query.get('id');

  const view = asyncView(host, () => ctx.source.listApprovals(), (items) => {
    const pending = items.filter((a) => a.status === 'pendiente');
    const decided = items.filter((a) => a.status !== 'pendiente');
    if (!selectedId || !items.some((a) => a.id === selectedId)) selectedId = pending[0]?.id || null;
    const queue = h('ul', { class: 'queue', attrs: { 'aria-label': t('approvals.queue') } });
    const detail = h('div', { class: 'stack', attrs: { 'data-block': 'approval-detail' } });
    const drawQueue = () => mount(queue, pending.length ? pending.map((a) => h('li', null, h('button', {
      class: `queue-item${a.id === selectedId ? ' active' : ''}`, attrs: { type: 'button', 'aria-pressed': String(a.id === selectedId), 'data-approval': a.id },
      on: { click: () => { selectedId = a.id; drawQueue(); drawDetail(); } },
    }, h('span', { class: 'row-between' }, h('strong', null, a.title), riskBadge(a.risk)),
       h('span', { class: 'small muted' }, `${t('approvals.kind.' + a.kind)} · ${a.requestedBy} · ${formatRelative(a.createdAt)}`)))) : [h('li', null, emptyState({ title: t('approvals.emptyQueue'), glyph: '●' }))]);

    const drawDetail = () => {
      const request = items.find((a) => a.id === selectedId);
      if (!request) { mount(detail, emptyState({ title: t('approvals.selectOne') })); return; }
      const form = h('form', { class: 'form', attrs: { novalidate: true, 'data-form': 'decision' }, on: { submit: (e) => e.preventDefault() } },
        field({ name: 'justification', label: t('approvals.justification'), type: 'textarea', rows: 3, maxLength: '2000', required: request.risk === 'alto',
                help: request.risk === 'alto' ? t('approvals.justificationHighRisk') : t('approvals.justificationHelp') }));
      const errorSlot = /** @type {HTMLElement} */ (form.querySelector('.field-error'));
      const area = /** @type {HTMLTextAreaElement} */ (form.querySelector('textarea'));
      /** @param {'aprobar'|'rechazar'} decision */
      const decide = async (decision) => {
        const text = formValues(form).justification.trim();
        const needs = decision === 'rechazar' || request.risk === 'alto';
        if (needs && text.length < 10) {
          area.setAttribute('aria-invalid', 'true');
          errorSlot.textContent = decision === 'rechazar' ? t('approvals.rejectNeedsReason') : t('approvals.highRiskNeedsReason');
          area.focus();
          return;
        }
        area.removeAttribute('aria-invalid');
        errorSlot.textContent = '';
        const answer = await confirmDialog({
          title: decision === 'aprobar' ? t('approvals.confirmApprove') : t('approvals.confirmReject'),
          message: request.title, consequence: decision === 'aprobar' ? request.impact : request.rejectEffect,
          confirmLabel: decision === 'aprobar' ? t('approvals.approve') : t('approvals.reject'), danger: decision === 'rechazar',
        });
        if (!answer.confirmed) return;
        const buttons = /** @type {HTMLButtonElement[]} */ ([...detail.querySelectorAll('[data-action="approve"], [data-action="reject"]')]);
        for (const button of buttons) button.disabled = true;
        detail.querySelector(`[data-action="${decision === 'aprobar' ? 'approve' : 'reject'}"]`)?.setAttribute('aria-busy', 'true');
        try {
          await ctx.source.decideApproval(request.id, decision, text, ctx.prefs().actor);
          toast(decision === 'aprobar' ? t('approvals.approved') : t('approvals.rejected'), decision === 'aprobar' ? 'ok' : 'warn');
          selectedId = null;
          ctx.refreshCounts();
          view.reload();
        } catch (error) {
          toast(errorMessage(error), 'risk');
          for (const button of buttons) { button.disabled = false; button.removeAttribute('aria-busy'); }
        }
      };
      const argsId = uid('args');
      mount(detail,
        h('div', { class: 'row-between' }, h('h2', null, request.title), h('span', { class: 'row' }, approvalStatusBadge(request.status), riskBadge(request.risk))),
        definitionList([
          [t('approvals.kindLabel'), t('approvals.kind.' + request.kind)],
          [t('approvals.requestedBy'), request.requestedBy],
          [t('approvals.action'), h('code', null, request.action)],
          [t('approvals.created'), formatDateTime(request.createdAt)],
          request.executionId ? [t('approvals.execution'), h('a', { attrs: { href: `#/orquestacion/${encodeURIComponent(request.executionId)}` } }, request.executionId)] : [t('approvals.execution'), '—'],
        ]),
        h('h3', { attrs: { id: argsId } }, t('approvals.args')),
        h('table', { class: 'table', attrs: { 'aria-labelledby': argsId } }, h('tbody', null, Object.entries(request.args).map(([k, v]) => h('tr', null, h('th', { attrs: { scope: 'row' } }, k), h('td', { class: 'wrap-anywhere' }, v))))),
        alertBox('live', t('approvals.impact'), h('span', null, request.impact)),
        alertBox('warn', t('approvals.rejectEffect'), h('span', null, request.rejectEffect)),
        request.diff ? h('div', { class: 'stack' }, h('h3', null, t('approvals.diff')), diffView(request.diff)) : null,
        request.status === 'pendiente'
          ? h('div', { class: 'stack' }, form, h('div', { class: 'form-actions' },
              h('button', { class: 'btn btn-danger', attrs: { type: 'button', 'data-action': 'reject' }, on: { click: () => decide('rechazar') } }, t('approvals.reject')),
              h('button', { class: 'btn btn-primary', attrs: { type: 'button', 'data-action': 'approve' }, on: { click: () => decide('aprobar') } }, t('approvals.approve'))))
          : alertBox(request.status === 'aprobada' ? 'ok' : 'risk', t('approvals.decidedBy', { who: request.decidedBy || '—', when: formatDateTime(request.decidedAt) }), h('span', null, request.justification || t('approvals.noJustification'))));
    };
    drawQueue();
    drawDetail();
    const history = dataTable({
      caption: t('approvals.history'), rows: decided, rowKey: (a) => a.id, emptyText: t('approvals.noHistory'),
      onOpen: (a) => { selectedId = a.id; drawDetail(); detail.scrollIntoView({ block: 'start' }); }, rowLabel: (a) => a.title,
      columns: [
        { key: 'title', label: t('approvals.col.request'), render: (a) => a.title },
        { key: 'kind', label: t('approvals.kindLabel'), render: (a) => t('approvals.kind.' + a.kind) },
        { key: 'status', label: t('approvals.col.decision'), render: (a) => approvalStatusBadge(a.status) },
        { key: 'who', label: t('approvals.col.who'), render: (a) => a.decidedBy || '—' },
        { key: 'when', label: t('approvals.col.when'), sort: (a) => a.decidedAt || '', render: (a) => formatDateTime(a.decidedAt) },
        { key: 'why', label: t('approvals.col.why'), render: (a) => a.justification || '—' },
      ] });
    const origin = items[0]?.origin || ctx.source.mode;
    return [
      ctx.source.mode === 'real' ? alertBox('idle', t('approvals.localTrail')) : null,
      h('div', { class: 'approvals-layout' },
        panel({ title: t('approvals.queueTitle', { n: pending.length }), origin, body: queue }),
        panel({ title: t('approvals.detail'), origin, body: detail })),
      panel({ title: t('approvals.history'), origin, flush: true, body: history, help: t('approvals.historyHelp') }),
    ];
  }, { lines: 6 });
  return { el, title: t('approvals.title') };
}
