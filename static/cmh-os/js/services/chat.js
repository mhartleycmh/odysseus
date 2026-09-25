// Coordinator chat (ADR-005): deterministic Spanish commands first; free text
// goes to a model only when the user enabled it and the backend supports it.
// Sensitive actions are never executed here: the reply offers an action that
// opens the corresponding confirmation dialog.
import { t } from '../core/i18n.js';
import { formatPercent, shortId } from '../core/format.js';

/** @typedef {import('../types.js').DataSource} DataSource */
/** @typedef {{label: string, href: string}} ChatLink */
/**
 * @typedef {{kind: 'navigate', label: string, href: string}
 *   | {kind: 'confirm-stop', label: string, executionId: string}
 *   | {kind: 'send', label: string, text: string}} ChatAction
 */
/**
 * @typedef {Object} ChatReply
 * @property {string} text
 * @property {string[]} [lines]
 * @property {ChatLink[]} [links]
 * @property {ChatAction[]} [actions]
 * @property {'regla'|'modelo'} answeredBy
 * @property {boolean} [error]
 */
/**
 * @typedef {'help'|'status'|'agents'|'approvals'|'executions'|'start'|'stop'|'search'|'goto'|'unknown'} Intent
 */

/** @param {string} text */
export function normalize(text) {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
}

export const MODULES = Object.freeze({
  inicio: '#/', general: '#/', agentes: '#/agentes', ejecuciones: '#/ejecuciones', orquestacion: '#/orquestacion',
  memoria: '#/memoria', herramientas: '#/herramientas', mcp: '#/herramientas', aprobaciones: '#/aprobaciones',
  observabilidad: '#/observabilidad', trazas: '#/observabilidad', evaluaciones: '#/evaluaciones', seguridad: '#/seguridad',
  configuracion: '#/configuracion', ayuda: '#/ayuda',
});

/**
 * @param {string} text
 * @returns {{intent: Intent, arg: string}}
 */
export function parseCommand(text) {
  // Spanish questions open with ¿ or ¡: strip opening and closing punctuation.
  const clean = normalize(text).replace(/^[/¿¡\s]+/, '').replace(/[?¿!¡.\s]+$/g, '');
  /** @type {[RegExp, Intent][]} */
  const rules = [
    [/^(ayuda|help|comandos|que puedes hacer)\b/, 'help'],
    [/^(estado|resumen|como va(mos)?|situacion)\b/, 'status'],
    [/^(agentes|lista de agentes|quien trabaja)\b/, 'agents'],
    [/^(aprobaciones|pendientes|que falta aprobar)\b/, 'approvals'],
    [/^(ejecuciones|corridas|historial)\b/, 'executions'],
    [/^(ejecuta|ejecutar|inicia|iniciar|lanza|lanzar|corre|correr)\b/, 'start'],
    // "para" alone is too ambiguous in Spanish ("para qué…"): only explicit verbs stop a run.
    [/^(deten|detener|cancela|cancelar|parar)\b/, 'stop'],
    [/^(busca|buscar|memoria|recuerda)\b/, 'search'],
    [/^(ir a|ve a|abre|abrir|mostrar|muestra)\b/, 'goto'],
  ];
  for (const [pattern, intent] of rules) {
    const match = clean.match(pattern);
    if (match) {
      let arg = clean.slice(match[0].length).trim();
      // Drop leading filler words ("el flujo", "la ejecución de") one at a time.
      for (let previous = ''; previous !== arg;) {
        previous = arg;
        arg = arg.replace(/^(el|la|los|las|a|de|del|flujo|ejecucion)(\s+|$)/, '').trim();
      }
      return { intent, arg };
    }
  }
  return { intent: 'unknown', arg: clean };
}

/** @returns {ChatAction[]} */
function suggestions() {
  return [
    { kind: 'send', label: t('chat.suggest.status'), text: 'estado' },
    { kind: 'send', label: t('chat.suggest.approvals'), text: 'aprobaciones' },
    { kind: 'send', label: t('chat.suggest.start'), text: 'ejecutar' },
    { kind: 'send', label: t('chat.suggest.help'), text: 'ayuda' },
  ];
}

/**
 * @typedef {Object} ChatContext
 * @property {DataSource} source
 * @property {boolean} allowModel User setting "Consultas al modelo desde el chat".
 * @property {{endpointId: string, model: string}|null} model
 */

/**
 * @param {string} text
 * @param {ChatContext} ctx
 * @returns {Promise<ChatReply>}
 */
export async function respond(text, ctx) {
  const { intent, arg } = parseCommand(text);
  const source = ctx.source;
  switch (intent) {
    case 'help':
      return { answeredBy: 'regla', text: t('chat.help.title'), lines: [t('chat.help.status'), t('chat.help.agents'), t('chat.help.approvals'),
        t('chat.help.executions'), t('chat.help.start'), t('chat.help.stop'), t('chat.help.search'), t('chat.help.goto')], actions: suggestions() };
    case 'status': {
      const [agents, executions, approvals] = await Promise.all([source.listAgents(), source.listExecutions(), source.listApprovals()]);
      const running = executions.filter((e) => e.status === 'running').length;
      const pending = approvals.filter((a) => a.status === 'pendiente').length;
      const finished = executions.filter((e) => e.status === 'completed' || e.status === 'error');
      const ok = finished.filter((e) => e.status === 'completed').length;
      return { answeredBy: 'regla', text: t('chat.status.title'),
        lines: [t('chat.status.agents', { active: agents.filter((a) => a.status === 'active' || a.status === 'running').length, total: agents.length }),
                t('chat.status.running', { n: running }), t('chat.status.approvals', { n: pending }),
                t('chat.status.success', { rate: finished.length ? formatPercent(ok / finished.length) : '—', n: finished.length })],
        actions: pending ? [{ kind: 'navigate', label: t('chat.action.reviewApprovals'), href: '#/aprobaciones' }] : [] };
    }
    case 'agents': {
      const agents = await source.listAgents();
      return { answeredBy: 'regla', text: t('chat.agents.title', { n: agents.length }),
        links: agents.slice(0, 12).map((a) => ({ label: `${a.name} · ${t('status.agent.' + a.status)}`, href: `#/agentes/${encodeURIComponent(a.id)}` })) };
    }
    case 'approvals': {
      const pending = (await source.listApprovals()).filter((a) => a.status === 'pendiente');
      if (!pending.length) return { answeredBy: 'regla', text: t('chat.approvals.none') };
      return { answeredBy: 'regla', text: t('chat.approvals.title', { n: pending.length }),
        links: pending.map((a) => ({ label: `${a.title} · ${t('risk.' + a.risk)}`, href: `#/aprobaciones?id=${encodeURIComponent(a.id)}` })),
        lines: [t('chat.approvals.note')] };
    }
    case 'executions': {
      const executions = (await source.listExecutions()).slice(0, 6);
      return { answeredBy: 'regla', text: t('chat.executions.title'),
        links: executions.map((e) => ({ label: `${shortId(e.id)} · ${e.workflowName} · ${t('status.execution.' + e.status)}`, href: `#/ejecuciones/${encodeURIComponent(e.id)}` })) };
    }
    case 'start': {
      const workflows = await source.listWorkflows();
      const match = arg ? workflows.find((w) => normalize(w.name).includes(arg) || normalize(w.id).includes(arg)) : undefined;
      if (match) {
        return { answeredBy: 'regla', text: t('chat.start.found', { name: match.name }), lines: [t('chat.start.confirmNote')],
          actions: [{ kind: 'navigate', label: t('chat.action.openNewExecution'), href: `#/ejecuciones?nuevo=${encodeURIComponent(match.id)}` }] };
      }
      return { answeredBy: 'regla', text: arg ? t('chat.start.notFound', { arg }) : t('chat.start.choose'),
        actions: workflows.map((w) => ({ kind: /** @type {const} */ ('navigate'), label: w.name, href: `#/ejecuciones?nuevo=${encodeURIComponent(w.id)}` })) };
    }
    case 'stop': {
      const executions = await source.listExecutions();
      const active = executions.filter((e) => ['running', 'pending', 'waiting_approval'].includes(e.status));
      const target = arg ? active.find((e) => normalize(e.id).startsWith(arg) || normalize(e.id) === arg) : active.length === 1 ? active[0] : undefined;
      if (target) {
        return { answeredBy: 'regla', text: t('chat.stop.confirm', { id: shortId(target.id), name: target.workflowName }),
          actions: [{ kind: 'confirm-stop', label: t('chat.action.stop'), executionId: target.id }] };
      }
      if (!active.length) return { answeredBy: 'regla', text: t('chat.stop.none') };
      return { answeredBy: 'regla', text: t('chat.stop.which'),
        actions: active.map((e) => ({ kind: /** @type {const} */ ('confirm-stop'), label: `${shortId(e.id)} · ${e.workflowName}`, executionId: e.id })) };
    }
    case 'search': {
      if (!arg) return { answeredBy: 'regla', text: t('chat.search.empty') };
      const records = await source.listMemory();
      const hits = records.filter((m) => normalize(`${m.title} ${m.content} ${m.tags.join(' ')} ${m.source}`).includes(arg)).slice(0, 5);
      return { answeredBy: 'regla', text: hits.length ? t('chat.search.found', { n: hits.length, q: arg }) : t('chat.search.none', { q: arg }),
        links: hits.map((m) => ({ label: `${m.title} · ${t('memory.kind.' + m.kind)}`, href: `#/memoria?q=${encodeURIComponent(arg)}` })) };
    }
    case 'goto': {
      const key = Object.keys(MODULES).find((name) => arg.startsWith(name));
      if (key) return { answeredBy: 'regla', text: t('chat.goto.ok', { name: key }), actions: [{ kind: 'navigate', label: t('chat.action.open', { name: key }), href: MODULES[/** @type {keyof typeof MODULES} */ (key)] }] };
      return { answeredBy: 'regla', text: t('chat.goto.unknown'), lines: [Object.keys(MODULES).join(', ')] };
    }
    default: {
      if (ctx.allowModel && source.capabilities.chatModel && ctx.model) {
        try {
          const answer = await source.askModel(text, ctx.model.endpointId, ctx.model.model);
          return { answeredBy: 'modelo', text: answer || t('chat.model.empty'), lines: [t('chat.model.caveat')] };
        } catch (error) {
          return { answeredBy: 'regla', error: true, text: t('chat.model.failed'), lines: [error instanceof Error ? error.message : String(error)], actions: suggestions() };
        }
      }
      const reason = !source.capabilities.chatModel ? t('chat.unknown.demo') : !ctx.allowModel ? t('chat.unknown.disabled') : t('chat.unknown.noModel');
      return { answeredBy: 'regla', text: t('chat.unknown.title'), lines: [reason], actions: suggestions() };
    }
  }
}
