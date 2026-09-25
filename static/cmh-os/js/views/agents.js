// Centro de agentes: list with search and filters, detail, create/edit form.
import { h, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { validate } from '../core/validate.js';
import { formatRelative, shortId } from '../core/format.js';
import { panel, viewHeader, definitionList, helpTip, mutableHeader } from '../components/panel.js';
import { asyncView, emptyState, alertBox, errorMessage } from '../components/states.js';
import { agentBadge, permissionBadge, riskBadge, chip, executionBadge } from '../components/badge.js';
import { dataTable } from '../components/table.js';
import { field, checkbox, formValues, showErrors } from '../components/form.js';
import { openModal, confirmDialog } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { workflowCompatible } from '../services/derive.js';

/** @typedef {import('../types.js').AppContext} AppContext */
/** @typedef {import('../types.js').Agent} Agent */
/** @typedef {import('../core/router.js').RouteMatch} RouteMatch */

/** @type {import('../core/validate.js').Schema} */
export const AGENT_SCHEMA = {
  name: { required: true, maxLength: 120 },
  role: { required: true, maxLength: 120 },
  instructions: { required: true, minLength: 10, maxLength: 20000 },
  workspace: { maxLength: 500, pattern: /^([a-zA-Z]:[\\/]|\/|data[\\/])/, patternMessage: 'agents.form.workspacePattern' },
  taskId: { maxLength: 80, pattern: /^[A-Za-z0-9-]+$/, patternMessage: 'agents.form.taskPattern' },
};

/**
 * @param {AppContext} ctx
 * @param {Agent|null} agent
 * @param {(saved: Agent) => void} onSaved
 */
export async function openAgentForm(ctx, agent, onSaved) {
  const [projects, tools, providers] = await Promise.all([ctx.source.listProjects(), ctx.source.listTools(), ctx.source.listProviders().catch(() => [])]);
  const models = [...new Set(providers.flatMap((p) => p.models))];
  if (agent?.model && !models.includes(agent.model)) models.unshift(agent.model);
  const formError = h('div', { attrs: { 'aria-live': 'polite' } });
  const toolBoxes = h('fieldset', { class: 'fieldset span-2', dataset: { field: 'allowedTools' } },
    h('legend', null, t('agents.form.tools')),
    h('div', { class: 'tool-grid' }, tools.map((tool) => {
      const box = checkbox(`${tool.name}`, `tool:${tool.id}`, agent ? agent.allowedTools.includes(tool.id) : tool.readOnly && tool.category === 'archivos');
      box.append(h('span', { class: 'row' }, riskBadge(tool.risk), tool.requiresApproval ? h('span', { class: 'xsmall muted' }, t('tools.needsApproval')) : null));
      return box;
    })),
    h('p', { class: 'field-help' }, t('agents.form.toolsHelp')),
    h('span', { class: 'field-error' }));
  const form = h('form', { class: 'form', attrs: { novalidate: true, 'data-form': 'agent' } },
    formError,
    h('div', { class: 'form-grid' },
      field({ name: 'name', label: t('agents.form.name'), required: true, value: agent?.name, maxLength: '120' }),
      field({ name: 'role', label: t('agents.form.role'), required: true, value: agent?.role, maxLength: '120' }),
      field({ name: 'projectId', label: t('agents.form.project'), type: 'select', value: agent?.projectId || '',
              options: [{ value: '', label: t('agents.form.noProject') }, ...projects.map((p) => ({ value: p.id, label: p.name }))] }),
      field({ name: 'model', label: t('agents.form.model'), type: 'select', value: agent?.model || '',
              options: [{ value: '', label: t('agents.form.noModel') }, ...models.map((m) => ({ value: m, label: m }))], help: t('agents.form.modelHelp') }),
      field({ name: 'workspace', label: t('agents.form.workspace'), value: agent?.workspace || '', help: t('agents.form.workspaceHelp'), className: 'span-2' }),
      field({ name: 'taskId', label: t('agents.form.task'), value: agent?.taskId || '', help: t('agents.form.taskHelp') }),
      toolBoxes,
      field({ name: 'instructions', label: t('agents.form.instructions'), type: 'textarea', rows: 6, required: true, value: agent?.instructions,
              help: agent ? t('agents.form.instructionsVersioned', { v: agent.instructionsVersion }) : t('agents.form.instructionsHelp'), className: 'span-2' })));
  const save = h('button', { class: 'btn btn-primary', attrs: { type: 'submit', form: 'agent-form' } }, agent ? t('common.save') : t('agents.create'));
  form.id = 'agent-form';
  const cancel = h('button', { class: 'btn', attrs: { type: 'button' } }, t('common.cancel'));
  const modal = openModal({ title: agent ? t('agents.editTitle', { name: agent.name }) : t('agents.createTitle'), body: form, footer: [cancel, save], wide: true });
  cancel.addEventListener('click', () => modal.close());
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = formValues(form);
    const errors = validate(AGENT_SCHEMA, values);
    if (!showErrors(form, errors)) return;
    const allowedTools = Object.keys(values).filter((key) => key.startsWith('tool:') && values[key] === 'true').map((key) => key.slice(5));
    save.setAttribute('aria-busy', 'true');
    save.disabled = true;
    try {
      const saved = await ctx.source.saveAgent({
        name: values.name.trim(), role: values.role.trim(), projectId: values.projectId || null, model: values.model || null,
        allowedTools, workspace: values.workspace.trim() || null, instructions: values.instructions, taskId: values.taskId.trim() || null,
      }, agent?.id);
      toast(agent ? t('agents.saved') : t('agents.created', { name: saved.name }), 'ok');
      modal.close();
      onSaved(saved);
    } catch (error) {
      mount(formError, alertBox('risk', t('agents.form.serverError'), h('span', null, errorMessage(error))));
      formError.querySelector('.alert')?.scrollIntoView({ block: 'nearest' });
    } finally {
      save.removeAttribute('aria-busy');
      save.disabled = false;
    }
  });
}

/**
 * @param {AppContext} ctx
 * @param {RouteMatch} match
 */
export function renderList(ctx, match) {
  const body = h('div', { class: 'stack' });
  const createButton = h('button', { class: 'btn btn-primary', attrs: { type: 'button', 'data-action': 'create-agent' } }, t('agents.create'));
  const el = h('section', { class: 'view', attrs: { 'data-view': 'agents' } }, viewHeader(t('agents.title'), t('agents.lede'), createButton), body);
  asyncView(body, () => Promise.all([ctx.source.listAgents(), ctx.source.listProjects()]), ([agents, projects]) => {
    const projectName = new Map(projects.map((p) => [p.id, p.name]));
    const search = field({ name: 'q', label: t('agents.filter.search'), type: 'search', value: match.query.get('q') || '', placeholder: t('agents.filter.searchPlaceholder'), className: 'grow' });
    const status = field({ name: 'status', label: t('agents.filter.status'), type: 'select', value: '',
      options: [{ value: '', label: t('common.all') }, ...['active', 'running', 'paused', 'error'].map((s) => ({ value: s, label: t('status.agent.' + s) }))] });
    const permission = field({ name: 'permission', label: t('agents.filter.permission'), type: 'select', value: '',
      options: [{ value: '', label: t('common.all') }, ...['lectura', 'escritura', 'admin'].map((p) => ({ value: p, label: t('permission.' + p) }))] });
    const project = field({ name: 'project', label: t('agents.filter.project'), type: 'select', value: '',
      options: [{ value: '', label: t('common.all') }, ...projects.map((p) => ({ value: p.id, label: p.name }))] });
    const toolbar = h('form', { class: 'toolbar', attrs: { role: 'search', 'aria-label': t('agents.filter.label') }, on: { submit: (e) => e.preventDefault() } }, search, status, permission, project);
    const countText = h('p', { class: 'small muted', attrs: { 'aria-live': 'polite', 'data-count': '' } });
    const tableHost = h('div');
    const draw = () => {
      const values = formValues(toolbar);
      const q = values.q.trim().toLocaleLowerCase();
      const rows = agents.filter((a) => (!q || `${a.name} ${a.role} ${a.model || ''} ${a.allowedTools.join(' ')}`.toLocaleLowerCase().includes(q))
        && (!values.status || a.status === values.status) && (!values.permission || a.permissionLevel === values.permission)
        && (!values.project || a.projectId === values.project));
      countText.textContent = t('agents.count', { shown: rows.length, total: agents.length });
      mount(tableHost, dataTable({
        caption: t('agents.title'), rows, rowKey: (a) => a.id, onOpen: (a) => ctx.navigate(`#/agentes/${encodeURIComponent(a.id)}`),
        rowLabel: (a) => t('agents.openRow', { name: a.name }), emptyText: t('agents.noMatch'), initialSort: { key: 'name', dir: 'asc' },
        columns: [
          { key: 'name', label: t('agents.col.name'), sort: (a) => a.name, render: (a) => h('span', { class: 'list-item-title' }, a.name) },
          { key: 'role', label: t('agents.col.role'), sort: (a) => a.role, render: (a) => a.role },
          { key: 'status', label: t('agents.col.status'), sort: (a) => a.status, render: (a) => agentBadge(a.status) },
          { key: 'permission', label: t('agents.col.permission'), sort: (a) => a.permissionLevel, render: (a) => permissionBadge(a.permissionLevel) },
          { key: 'model', label: t('agents.col.model'), sort: (a) => a.model || '', render: (a) => a.model ? h('span', { class: 'mono small' }, a.model) : h('span', { class: 'muted' }, '—') },
          { key: 'tools', label: t('agents.col.tools'), num: true, sort: (a) => a.allowedTools.length, render: (a) => String(a.allowedTools.length) },
          { key: 'project', label: t('agents.col.project'), sort: (a) => projectName.get(a.projectId || '') || '', render: (a) => projectName.get(a.projectId || '') || t('agents.form.noProject') },
        ],
      }));
    };
    toolbar.addEventListener('input', draw);
    toolbar.addEventListener('change', draw);
    draw();
    return panel({ title: t('agents.registry'), origin: agents[0]?.origin || ctx.source.mode, help: t('agents.registryHelp'), body: [toolbar, countText, tableHost] });
  }, { isEmpty: ([agents]) => agents.length === 0, empty: () => emptyState({ title: t('agents.empty'), text: t('agents.emptyText'), action: h('button', { class: 'btn btn-primary', attrs: { type: 'button' }, on: { click: () => createButton.click() } }, t('agents.create')) }) });
  createButton.addEventListener('click', () => {
    openAgentForm(ctx, null, (saved) => ctx.navigate(`#/agentes/${encodeURIComponent(saved.id)}`)).catch((error) => toast(errorMessage(error), 'risk'));
  });
  if (match.query.get('nuevo')) setTimeout(() => createButton.click(), 0);
  return { el, title: t('agents.title') };
}

/**
 * @param {AppContext} ctx
 * @param {RouteMatch} match
 */
export function renderDetail(ctx, match) {
  const id = match.params.id;
  const header = mutableHeader(t('agents.detailTitle'), '');
  header.setCrumb(h('nav', { class: 'breadcrumb small', attrs: { 'aria-label': t('common.breadcrumb') } }, h('a', { attrs: { href: '#/agentes' } }, t('agents.title'))));
  const host = h('div', { class: 'stack' });
  const el = h('section', { class: 'view', attrs: { 'data-view': 'agent' } }, header.el, host);
  const load = async () => {
    const [agent, projects, executions] = await Promise.all([ctx.source.getAgent(id), ctx.source.listProjects(), ctx.source.listExecutions()]);
    let withSteps = executions;
    if (executions.length && executions.every((e) => e.steps.length === 0)) {
      withSteps = await Promise.all(executions.slice(0, 8).map((e) => ctx.source.getExecution(e.id).catch(() => e)));
    }
    return { agent, projects, history: withSteps.filter((e) => e.steps.some((s) => s.agentId === agent.id)).slice(0, 10) };
  };
  const view = asyncView(host, load, ({ agent, projects, history }) => {
    document.title = `${agent.name} · Agentic OS CMH`;
    header.setTitle(agent.name);
    header.setLede(agent.role);
    header.setCrumb(h('nav', { class: 'breadcrumb small', attrs: { 'aria-label': t('common.breadcrumb') } }, h('a', { attrs: { href: '#/agentes' } }, t('agents.title')), ' / ', agent.name));
    const edit = h('button', { class: 'btn', attrs: { type: 'button', 'data-action': 'edit-agent' }, on: { click: () => openAgentForm(ctx, agent, () => view.reload()).catch((e) => toast(errorMessage(e), 'risk')) } }, t('common.edit'));
    const toggle = h('button', { class: agent.status === 'paused' ? 'btn btn-primary' : 'btn', attrs: { type: 'button', 'data-action': 'toggle-agent' }, on: { click: async () => {
      const activating = agent.status === 'paused';
      const answer = await confirmDialog({ title: activating ? t('agents.activateTitle') : t('agents.pauseTitle'), message: t(activating ? 'agents.activateMessage' : 'agents.pauseMessage', { name: agent.name }),
                                           consequence: activating ? t('agents.activateConsequence') : t('agents.pauseConsequence'), confirmLabel: activating ? t('agents.activate') : t('agents.pause'), danger: !activating });
      if (!answer.confirmed) return;
      try {
        await ctx.source.setAgentStatus(agent.id, activating ? 'active' : 'paused');
        toast(activating ? t('agents.activated') : t('agents.paused'), 'ok');
        view.reload();
      } catch (error) {
        toast(errorMessage(error), 'risk');
      }
    } } }, agent.status === 'paused' ? t('agents.activate') : t('agents.pause'));
    const projectName = projects.find((p) => p.id === agent.projectId)?.name || t('agents.form.noProject');
    header.setActions([edit, toggle]);
    return [
      h('div', { class: 'row' }, agentBadge(agent.status), permissionBadge(agent.permissionLevel),
        workflowCompatible(agent.allowedTools) ? h('span', { class: 'badge tone-live' }, t('agents.workflowReady')) : h('span', { class: 'badge tone-idle' }, t('agents.workflowNotReady')), helpTip(t('agents.workflowHelp'))),
      h('div', { class: 'grid grid-2' },
        panel({ title: t('agents.summary'), origin: agent.origin, body: definitionList([
          [t('agents.form.role'), agent.role], [t('agents.form.project'), projectName], [t('agents.form.model'), agent.model || '—'],
          [t('agents.form.workspace'), agent.workspace ? h('code', null, agent.workspace) : '—'], [t('agents.col.permission'), permissionBadge(agent.permissionLevel)],
          [t('agents.form.task'), agent.taskId ? h('code', null, agent.taskId) : '—'], [t('agents.instructionsVersion'), `v${agent.instructionsVersion}`], [t('agents.id'), h('code', null, agent.id)],
        ]) }),
        panel({ title: t('agents.capabilities'), origin: agent.origin, body: agent.capabilities.length
          ? h('ul', { class: 'list' }, agent.capabilities.map((c) => h('li', null, h('span', { class: 'list-item-title' }, c.label), h('span', { class: 'small muted' }, c.description))))
          : emptyState({ title: t('agents.noCapabilities') }) })),
      panel({ title: t('agents.tools'), origin: agent.origin, help: t('agents.toolsHelp'), body: agent.allowedTools.length
        ? h('div', { class: 'chip-list' }, agent.allowedTools.map((tool) => chip(tool)))
        : alertBox('warn', t('agents.noTools')) }),
      panel({ title: t('agents.form.instructions'), origin: agent.origin, body: h('pre', { class: 'code' }, agent.instructions || '—') }),
      panel({ title: t('agents.history'), origin: agent.origin, flush: true, body: dataTable({
        caption: t('agents.history'), rows: history, rowKey: (e) => e.id, emptyText: t('agents.noHistory'),
        onOpen: (e) => ctx.navigate(`#/ejecuciones/${encodeURIComponent(e.id)}`), rowLabel: (e) => t('executions.openRow', { id: shortId(e.id) }),
        columns: [
          { key: 'id', label: t('executions.col.id'), render: (e) => h('span', { class: 'mono' }, shortId(e.id)) },
          { key: 'flow', label: t('executions.col.workflow'), render: (e) => e.workflowName },
          { key: 'step', label: t('agents.stepStatus'), render: (e) => { const step = e.steps.find((s) => s.agentId === agent.id); return step ? t('status.step.' + step.status) : '—'; } },
          { key: 'status', label: t('executions.col.status'), render: (e) => executionBadge(e.status) },
          { key: 'created', label: t('executions.col.created'), render: (e) => formatRelative(e.createdAt) },
        ] }) }),
    ];
  });
  return { el, title: t('agents.detailTitle'), destroy: () => view.dispose() };
}
