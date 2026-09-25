// Ejecuciones: list, new execution form with limits, live detail with steps,
// tools, errors, final answer, cancel and controlled retry.
import { h, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { validate } from '../core/validate.js';
import { formatDateTime, formatDuration, formatNumber, formatRelative, formatUsd, shortId } from '../core/format.js';
import { panel, viewHeader, definitionList, helpTip, mutableHeader } from '../components/panel.js';
import { asyncView, alertBox, emptyState, errorMessage } from '../components/states.js';
import { executionBadge, stepBadge, statusBadge, chip } from '../components/badge.js';
import { dataTable } from '../components/table.js';
import { field, formValues, showErrors } from '../components/form.js';
import { openModal, confirmDialog } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { timeline } from '../components/timeline.js';
import { openRunFeed } from '../services/run-feed.js';

/** @typedef {import('../types.js').AppContext} AppContext */
/** @typedef {import('../types.js').Execution} Execution */
/** @typedef {import('../types.js').RunEvent} RunEvent */
/** @typedef {import('../core/router.js').RouteMatch} RouteMatch */

const ACTIVE = ['running', 'pending', 'waiting_approval'];

/** @type {import('../core/validate.js').Schema} */
export const EXECUTION_SCHEMA = {
  workflowId: { required: true },
  objective: { required: true, minLength: 10, maxLength: 12000 },
  priority: { required: true, oneOf: ['baja', 'media', 'alta'] },
  maxIterations: { required: true, integer: true, min: 1, max: 200 },
  timeoutSeconds: { required: true, integer: true, min: 10, max: 86400 },
  budgetUsd: { required: true, min: 0.01, max: 1000 },
};

/**
 * @param {AppContext} ctx
 * @param {string|null} preselected
 */
export async function openExecutionForm(ctx, preselected) {
  const [workflows, agents] = await Promise.all([ctx.source.listWorkflows(), ctx.source.listAgents()]);
  if (!workflows.length) {
    toast(t('executions.form.noWorkflows'), 'warn');
    return;
  }
  const limitsSupported = ctx.source.capabilities.executionLimits;
  const defaults = ctx.prefs().limits;
  const initial = workflows.find((w) => w.id === preselected)?.id || workflows[0].id;
  const description = h('p', { class: 'small muted', attrs: { 'aria-live': 'polite' } });
  const responsible = field({ name: 'responsibleAgentId', label: t('executions.form.responsible'), type: 'select', value: '', options: [], help: t('executions.form.responsibleHelp') });
  const form = h('form', { class: 'form', attrs: { novalidate: true, id: 'execution-form', 'data-form': 'execution' } },
    h('div', { attrs: { 'data-form-error': '' } }),
    h('div', { class: 'form-grid' },
      field({ name: 'workflowId', label: t('executions.form.workflow'), type: 'select', required: true, value: initial, options: workflows.map((w) => ({ value: w.id, label: w.name })), className: 'span-2' }),
      h('div', { class: 'span-2' }, description),
      field({ name: 'objective', label: t('executions.form.objective'), type: 'textarea', rows: 4, required: true, maxLength: '12000', help: t('executions.form.objectiveHelp'), className: 'span-2' }),
      field({ name: 'priority', label: t('executions.form.priority'), type: 'select', required: true, value: 'media',
              options: ['baja', 'media', 'alta'].map((p) => ({ value: p, label: t('priority.' + p) })), help: limitsSupported ? undefined : t('executions.form.priorityNotStored') }),
      responsible,
      h('fieldset', { class: 'fieldset span-2' }, h('legend', null, t('executions.form.limits'), ' ', helpTip(t('executions.form.limitsHelp'))),
        limitsSupported ? null : alertBox('warn', t('executions.form.limitsUnsupported')),
        h('div', { class: 'form-grid' },
          field({ name: 'maxIterations', label: t('executions.form.maxIterations'), type: 'number', required: true, min: '1', max: '200', step: '1', value: String(defaults.maxIterations), disabled: !limitsSupported }),
          field({ name: 'timeoutSeconds', label: t('executions.form.timeout'), type: 'number', required: true, min: '10', max: '86400', step: '1', value: String(defaults.timeoutSeconds), disabled: !limitsSupported }),
          field({ name: 'budgetUsd', label: t('executions.form.budget'), type: 'number', required: true, min: '0.01', max: '1000', step: '0.01', value: String(defaults.budgetUsd), disabled: !limitsSupported, help: t('executions.form.budgetHelp') })))));
  const workflowSelect = /** @type {HTMLSelectElement} */ (form.querySelector('select[name="workflowId"]'));
  const responsibleSelect = /** @type {HTMLSelectElement} */ (responsible.querySelector('select'));
  const syncWorkflow = () => {
    const wf = workflows.find((w) => w.id === workflowSelect.value);
    description.textContent = wf ? `${wf.description || ''} ${t('executions.form.steps', { n: wf.steps.length })}`.trim() : '';
    const ids = new Set(wf?.steps.map((s) => s.agentId) || []);
    mount(responsibleSelect, h('option', { attrs: { value: '' } }, t('executions.form.noResponsible')),
      agents.filter((a) => ids.has(a.id)).map((a) => h('option', { attrs: { value: a.id } }, `${a.name} · ${t('status.agent.' + a.status)}`)));
  };
  workflowSelect.addEventListener('change', syncWorkflow);
  syncWorkflow();
  const submit = h('button', { class: 'btn btn-primary', attrs: { type: 'submit', form: 'execution-form' } }, t('executions.form.start'));
  const cancel = h('button', { class: 'btn', attrs: { type: 'button' } }, t('common.cancel'));
  const modal = openModal({ title: t('executions.form.title'), body: form, footer: [cancel, submit], wide: true });
  cancel.addEventListener('click', () => modal.close());
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = formValues(form);
    const schema = limitsSupported ? EXECUTION_SCHEMA : { workflowId: EXECUTION_SCHEMA.workflowId, objective: EXECUTION_SCHEMA.objective, priority: EXECUTION_SCHEMA.priority };
    if (!showErrors(form, validate(schema, values))) return;
    submit.setAttribute('aria-busy', 'true');
    submit.disabled = true;
    try {
      const created = await ctx.source.createExecution({
        workflowId: values.workflowId, objective: values.objective.trim(), priority: /** @type {'baja'|'media'|'alta'} */ (values.priority),
        responsibleAgentId: values.responsibleAgentId || null,
        maxIterations: limitsSupported ? Number(values.maxIterations) : null, timeoutSeconds: limitsSupported ? Number(values.timeoutSeconds) : null,
        budgetUsd: limitsSupported ? Number(values.budgetUsd.replace(',', '.')) : null,
      });
      toast(t('executions.form.started', { id: shortId(created.id) }), 'ok');
      modal.close();
      ctx.navigate(`#/orquestacion/${encodeURIComponent(created.id)}`);
    } catch (error) {
      mount(/** @type {HTMLElement} */ (form.querySelector('[data-form-error]')), alertBox('risk', t('executions.form.failed'), h('span', null, errorMessage(error))));
    } finally {
      submit.removeAttribute('aria-busy');
      submit.disabled = false;
    }
  });
}

/**
 * @param {AppContext} ctx
 * @param {RouteMatch} match
 */
export function renderList(ctx, match) {
  const body = h('div', { class: 'stack' });
  const create = h('button', { class: 'btn btn-primary', attrs: { type: 'button', 'data-action': 'new-execution' },
    on: { click: () => openExecutionForm(ctx, null).catch((e) => toast(errorMessage(e), 'risk')) } }, t('executions.new'));
  const el = h('section', { class: 'view', attrs: { 'data-view': 'executions' } }, viewHeader(t('executions.title'), t('executions.lede'), create), body);
  asyncView(body, () => Promise.all([ctx.source.listExecutions(), ctx.source.listWorkflows()]), ([executions, workflows]) => {
    const toolbar = h('form', { class: 'toolbar', attrs: { role: 'search', 'aria-label': t('executions.filter.label') }, on: { submit: (e) => e.preventDefault() } },
      field({ name: 'q', label: t('executions.filter.search'), type: 'search', placeholder: t('executions.filter.searchPlaceholder'), className: 'grow' }),
      field({ name: 'status', label: t('executions.filter.status'), type: 'select', value: match.query.get('estado') || '',
              options: [{ value: '', label: t('common.all') }, ...['running', 'waiting_approval', 'completed', 'error', 'interrupted', 'pending'].map((s) => ({ value: s, label: t('status.execution.' + s) }))] }),
      field({ name: 'workflow', label: t('executions.filter.workflow'), type: 'select', value: '', options: [{ value: '', label: t('common.all') }, ...workflows.map((w) => ({ value: w.id, label: w.name }))] }));
    const host = h('div');
    const count = h('p', { class: 'small muted', attrs: { 'aria-live': 'polite', 'data-count': '' } });
    const draw = () => {
      const v = formValues(toolbar);
      const q = v.q.trim().toLocaleLowerCase();
      const rows = executions.filter((e) => (!q || `${e.id} ${e.workflowName} ${e.objective}`.toLocaleLowerCase().includes(q)) && (!v.status || e.status === v.status) && (!v.workflow || e.workflowId === v.workflow));
      count.textContent = t('executions.count', { shown: rows.length, total: executions.length });
      mount(host, dataTable({
        caption: t('executions.title'), rows, rowKey: (e) => e.id, emptyText: t('executions.noMatch'),
        onOpen: (e) => ctx.navigate(`#/ejecuciones/${encodeURIComponent(e.id)}`), rowLabel: (e) => t('executions.openRow', { id: shortId(e.id) }),
        initialSort: { key: 'created', dir: 'desc' },
        columns: [
          { key: 'id', label: t('executions.col.id'), sort: (e) => e.id, render: (e) => h('span', { class: 'mono' }, shortId(e.id)) },
          { key: 'flow', label: t('executions.col.workflow'), sort: (e) => e.workflowName, render: (e) => e.workflowName },
          { key: 'objective', label: t('executions.col.objective'), render: (e) => e.objective ? h('span', { class: 'truncate', attrs: { title: e.objective } }, e.objective.length > 60 ? e.objective.slice(0, 59) + '…' : e.objective) : h('span', { class: 'muted' }, t('executions.objectiveUnavailable')) },
          { key: 'status', label: t('executions.col.status'), sort: (e) => e.status, render: (e) => executionBadge(e.status) },
          { key: 'steps', label: t('executions.col.steps'), num: true, render: (e) => e.steps.length ? `${e.steps.filter((s) => s.status === 'completed').length}/${e.steps.length}` : '—' },
          { key: 'tokens', label: t('executions.col.tokens'), num: true, sort: (e) => e.usage.tokensIn + e.usage.tokensOut, render: (e) => (e.usage.measured ? formatNumber(e.usage.tokensIn + e.usage.tokensOut) : '—') },
          { key: 'cost', label: t('executions.col.cost'), num: true, sort: (e) => e.usage.costUsd || 0, render: (e) => formatUsd(e.usage.costUsd) },
          { key: 'created', label: t('executions.col.created'), sort: (e) => e.createdAt, render: (e) => formatRelative(e.createdAt) },
        ] }));
    };
    toolbar.addEventListener('input', draw);
    toolbar.addEventListener('change', draw);
    draw();
    return panel({ title: t('executions.listTitle'), origin: ctx.source.mode, body: [toolbar, count, host] });
  }, { isEmpty: ([executions]) => executions.length === 0, empty: () => emptyState({ title: t('executions.empty'), action: h('button', { class: 'btn btn-primary', attrs: { type: 'button' }, on: { click: () => create.click() } }, t('executions.new')) }) });
  const preselect = match.query.get('nuevo');
  if (preselect) setTimeout(() => openExecutionForm(ctx, preselect === '1' ? null : preselect).catch((e) => toast(errorMessage(e), 'risk')), 0);
  return { el, title: t('executions.title') };
}

/**
 * @param {AppContext} ctx
 * @param {Execution} execution
 * @param {() => void} onDone
 */
async function openRetry(ctx, execution, onDone) {
  if (!ctx.source.capabilities.executionLimits) {
    const answer = await confirmDialog({ title: t('executions.retry.title'), message: t('executions.retry.messageReal'), consequence: t('executions.retry.consequence'), confirmLabel: t('executions.retry.action') });
    if (!answer.confirmed) return;
    try { await ctx.source.retryExecution(execution.id); toast(t('executions.retry.done'), 'ok'); onDone(); } catch (error) { toast(errorMessage(error), 'risk'); }
    return;
  }
  const form = h('form', { class: 'form', attrs: { novalidate: true, id: 'retry-form' } },
    h('p', null, t('executions.retry.message')),
    execution.error ? alertBox('risk', t('executions.retry.lastError'), h('span', null, execution.error)) : null,
    h('div', { class: 'form-grid' },
      field({ name: 'maxIterations', label: t('executions.form.maxIterations'), type: 'number', required: true, min: '1', max: '200', value: String(execution.limits.maxIterations ?? 12) }),
      field({ name: 'timeoutSeconds', label: t('executions.form.timeout'), type: 'number', required: true, min: '10', max: '86400', value: String(execution.limits.timeoutSeconds ?? 600) }),
      field({ name: 'budgetUsd', label: t('executions.form.budget'), type: 'number', required: true, min: '0.01', max: '1000', step: '0.01', value: String(execution.limits.budgetUsd ?? 2), help: t('executions.retry.budgetHelp', { spent: formatUsd(execution.usage.costUsd) }) })));
  const submit = h('button', { class: 'btn btn-primary', attrs: { type: 'submit', form: 'retry-form' } }, t('executions.retry.action'));
  const cancel = h('button', { class: 'btn', attrs: { type: 'button' } }, t('common.cancel'));
  const modal = openModal({ title: t('executions.retry.title'), body: form, footer: [cancel, submit] });
  cancel.addEventListener('click', () => modal.close());
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = formValues(form);
    const schema = { maxIterations: EXECUTION_SCHEMA.maxIterations, timeoutSeconds: EXECUTION_SCHEMA.timeoutSeconds, budgetUsd: EXECUTION_SCHEMA.budgetUsd };
    if (!showErrors(form, validate(schema, values))) return;
    try {
      await ctx.source.retryExecution(execution.id, { maxIterations: Number(values.maxIterations), timeoutSeconds: Number(values.timeoutSeconds), budgetUsd: Number(values.budgetUsd.replace(',', '.')) });
      toast(t('executions.retry.done'), 'ok');
      modal.close();
      onDone();
    } catch (error) {
      toast(errorMessage(error), 'risk');
    }
  });
}

/**
 * @param {AppContext} ctx
 * @param {RouteMatch} match
 */
export function renderDetail(ctx, match) {
  const id = match.params.id;
  const header = mutableHeader(t('executions.detailTitle', { id: shortId(id) }), '');
  header.setCrumb(h('nav', { class: 'breadcrumb small', attrs: { 'aria-label': t('common.breadcrumb') } }, h('a', { attrs: { href: '#/ejecuciones' } }, t('executions.title')), ' / ', shortId(id)));
  const host = h('div', { class: 'stack' });
  const el = h('section', { class: 'view', attrs: { 'data-view': 'execution' } }, header.el, host);
  /** @type {import('../services/run-feed.js').RunFeed|null} */
  let feed = null;

  const view = asyncView(host, () => ctx.source.getExecution(id), (snapshot) => {
    feed?.dispose();
    let execution = snapshot;
    const badges = h('div', { class: 'row', attrs: { 'data-block': 'badges' } });
    const summary = h('div');
    const steps = h('div');
    const answer = h('div', { attrs: { 'data-block': 'answer' } });
    const artifacts = h('div');
    const eventsHost = h('div', { class: 'timeline-host' });
    const streamState = h('span', { class: 'small muted', attrs: { 'aria-live': 'polite' } });
    header.setTitle(t('executions.detailTitle', { id: shortId(snapshot.id) }));
    header.setLede(snapshot.workflowName);

    let paintedStatus = '';
    const paint = () => {
      mount(badges, executionBadge(execution.status), statusBadge(execution.limits.enforced ? 'live' : 'idle', execution.limits.enforced ? t('executions.limitsEnforced') : t('executions.limitsNotEnforced')),
        h('span', { class: 'small muted' }, t('executions.attempt', { n: execution.attempt })));
      const active = ACTIVE.includes(execution.status);
      // Rebuild the buttons only when the status changes, so keyboard focus survives live events.
      if (paintedStatus !== execution.status) header.setActions([
        h('a', { class: 'btn', attrs: { href: `#/orquestacion/${encodeURIComponent(execution.id)}` } }, t('executions.viewOrchestration')),
        h('a', { class: 'btn', attrs: { href: `#/observabilidad/${encodeURIComponent(execution.id)}` } }, t('executions.viewTrace')),
        active ? h('button', { class: 'btn btn-danger', attrs: { type: 'button', 'data-action': 'cancel-execution' }, on: { click: async () => { if (await ctx.confirmStop(execution.id)) view.reload(); } } }, t('executions.cancel')) : null,
        ['error', 'interrupted'].includes(execution.status) ? h('button', { class: 'btn btn-primary', attrs: { type: 'button', 'data-action': 'retry-execution' }, on: { click: () => openRetry(ctx, execution, () => view.reload()) } }, t('executions.retryButton')) : null]);
      paintedStatus = execution.status;
      const u = execution.usage;
      const l = execution.limits;
      const measured = (/** @type {string} */ value) => (u.measured ? value : t('executions.usage.notMeasured'));
      mount(summary, definitionList([
        [t('executions.form.objective'), execution.objective || t('executions.objectiveUnavailable')],
        [t('executions.form.priority'), t('priority.' + execution.priority)],
        [t('executions.form.workflow'), execution.workflowName],
        [t('executions.col.created'), formatDateTime(execution.createdAt)],
        [t('executions.usage.tokens'), measured(t('executions.usage.tokensValue', { input: formatNumber(u.tokensIn), output: formatNumber(u.tokensOut) }))],
        [t('executions.usage.cost'), `${formatUsd(u.costUsd)}${l.budgetUsd !== null ? ' / ' + formatUsd(l.budgetUsd) : ''}`],
        [t('executions.usage.iterations'), measured(`${formatNumber(u.iterations)}${l.maxIterations !== null ? ' / ' + formatNumber(l.maxIterations) : ''}`)],
        [t('executions.usage.elapsed'), `${formatDuration(u.elapsedSeconds)}${l.timeoutSeconds !== null ? ' / ' + formatDuration(l.timeoutSeconds) : ''}`],
      ]), l.budgetUsd !== null && u.costUsd !== null ? h('div', { class: 'stack', attrs: { style: 'margin-top:12px' } },
        h('span', { class: 'small muted' }, t('executions.usage.budgetUsed')),
        h('div', { class: `meter ${u.costUsd / l.budgetUsd > 0.9 ? 'tone-risk' : u.costUsd / l.budgetUsd > 0.7 ? 'tone-warn' : ''}`, attrs: { role: 'meter', 'aria-valuemin': '0', 'aria-valuemax': String(l.budgetUsd), 'aria-valuenow': String(u.costUsd), 'aria-label': t('executions.usage.budgetUsed') } },
          h('span', { attrs: { style: `width:${Math.min(100, (u.costUsd / l.budgetUsd) * 100).toFixed(1)}%` } }))) : null);
      mount(steps, dataTable({
        caption: t('executions.steps'), rows: execution.steps, rowKey: (s) => s.key,
        columns: [
          { key: 'key', label: t('executions.step.key'), render: (s) => h('span', null, h('strong', null, s.agentName), h('br'), h('span', { class: 'mono xsmall muted' }, s.key)) },
          { key: 'status', label: t('executions.step.status'), render: (s) => h('span', { class: 'row' }, stepBadge(s.status), s.requiresApproval ? h('span', { class: 'xsmall muted' }, t('executions.step.requiresApproval')) : null) },
          { key: 'model', label: t('executions.step.model'), render: (s) => s.model ? h('span', { class: 'mono xsmall' }, s.model) : '—' },
          { key: 'tools', label: t('executions.step.tools'), render: (s) => s.tools.length ? h('div', { class: 'chip-list' }, s.tools.map((c) => chip(`${c.status === 'error' ? '■' : c.status === 'running' ? '◆' : '●'} ${c.tool}`))) : h('span', { class: 'muted' }, '—') },
          { key: 'tokens', label: t('executions.col.tokens'), num: true, render: (s) => (u.measured ? formatNumber(s.tokensIn + s.tokensOut) : '—') },
          { key: 'error', label: t('executions.step.error'), render: (s) => s.error ? h('span', { class: 'tone-text-risk small' }, s.error) : '—' },
        ] }));
      if (execution.status === 'completed' && execution.finalAnswer) mount(answer, h('pre', { class: 'code', attrs: { 'data-final-answer': '' } }, execution.finalAnswer));
      else if (execution.status === 'error') mount(answer, alertBox('risk', t('executions.answer.error'), h('span', null, execution.error || '—')));
      else if (execution.status === 'waiting_approval') mount(answer, alertBox('warn', t('executions.answer.waiting'), h('a', { attrs: { href: '#/aprobaciones' } }, t('executions.answer.review'))));
      else if (execution.status === 'interrupted') mount(answer, alertBox('warn', t('executions.answer.interrupted')));
      else mount(answer, alertBox('live', t('executions.answer.pending')));
      mount(artifacts, execution.artifacts.length
        ? execution.artifacts.map((a) => h('details', { class: 'artifact' }, h('summary', null, `${a.stepKey} · ${a.model || '—'} · ${shortId(a.id, 12)}`), h('pre', { class: 'code' }, a.content)))
        : emptyState({ title: t('executions.noArtifacts') }));
      const events = feed ? feed.events() : [];
      mount(eventsHost, events.length ? timeline(events, { limit: 80 }) : emptyState({ title: t('executions.noEvents') }));
    };

    let scheduled = false;
    feed = openRunFeed(ctx.source, snapshot, {
      onChange(next) {
        execution = next;
        // A replayed backlog arrives in a burst: paint once per microtask.
        if (scheduled) return;
        scheduled = true;
        queueMicrotask(() => { scheduled = false; if (!feed?.disposed()) paint(); });
      },
      onState(state) { streamState.textContent = t('executions.stream.' + state); },
    });
    execution = feed.state();
    paint();
    return [
      badges,
      h('div', { class: 'grid grid-main-side' },
        panel({ title: t('executions.answer.title'), origin: execution.origin, body: answer }),
        panel({ title: t('executions.summary'), origin: execution.origin, body: summary, help: t('executions.summaryHelp') })),
      panel({ title: t('executions.steps'), origin: execution.origin, body: steps, flush: true }),
      h('div', { class: 'grid grid-2' },
        panel({ title: t('executions.events'), origin: execution.origin, body: [streamState, eventsHost] }),
        panel({ title: t('executions.artifacts'), origin: execution.origin, help: t('executions.artifactsHelp'), body: artifacts })),
    ];
  });
  return { el, title: t('executions.detailTitle', { id: shortId(id) }), destroy: () => { view.dispose(); feed?.dispose(); } };
}
