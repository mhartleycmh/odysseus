// Demo data source: deterministic, in-memory, with live-looking runs driven by
// the simulator. Every record it returns carries origin "demo" (ADR-003).
import { AGENTS, EVALUATIONS, HISTORY, MCP_SERVERS, MEMORY, PROJECTS, PROVIDERS, SECURITY, TOOLS, WORKFLOWS } from '../mocks/data.js';
import { seedFrom } from '../mocks/rng.js';
import { recordAudit, listAudit } from '../core/audit.js';
import { HttpError } from './http.js';
import { createSimulation } from './simulator.js';
import { applyEvent, buildTrace } from './run-state.js';
import { permissionFor } from './derive.js';

/** @typedef {import('../types.js').DataSource} DataSource */
/** @typedef {import('../types.js').Agent} Agent */
/** @typedef {import('../types.js').AgentInput} AgentInput */
/** @typedef {import('../types.js').Execution} Execution */
/** @typedef {import('../types.js').ExecutionInput} ExecutionInput */
/** @typedef {import('../types.js').RunEvent} RunEvent */
/** @typedef {import('../types.js').ApprovalRequest} ApprovalRequest */
/** @typedef {import('../types.js').RunStreamHandlers} RunStreamHandlers */
/** @typedef {import('../types.js').Workflow} Workflow */
/** @typedef {import('./simulator.js').Simulation} Simulation */

/**
 * @typedef {Object} DemoOptions
 * @property {number} [speed] Multiplier for simulated delays (0 = instant, for tests).
 * @property {() => boolean} [failures] When true, reads fail transiently (every other call).
 * @property {() => number} [now]
 * @property {boolean} [history] Seed historical runs (default true).
 */

/**
 * @typedef {Object} RunRecord
 * @property {Execution} execution
 * @property {RunEvent[]} events
 * @property {Simulation|null} sim
 * @property {ReturnType<typeof setTimeout>|null} timer
 * @property {Set<RunStreamHandlers>} listeners
 */

/** @template T @param {T} value @returns {T} */
const clone = (value) => structuredClone(value);

/**
 * @param {DemoOptions} [options]
 * @returns {DataSource & {runRecord: (id: string) => RunRecord|undefined}}
 */
export function createDemoSource(options = {}) {
  const speed = options.speed ?? 1;
  const now = options.now || (() => Date.now());
  const failures = options.failures || (() => false);
  /** @type {Agent[]} */
  const agents = clone(AGENTS);
  /** @type {Workflow[]} */
  const workflows = clone(WORKFLOWS);
  const memory = clone(MEMORY);
  const evaluations = clone(EVALUATIONS);
  /** @type {Map<string, RunRecord>} */
  const runs = new Map();
  /** @type {Map<string, {status: 'aprobada'|'rechazada', justification: string, decidedAt: string, decidedBy: string}>} */
  const decisions = new Map();
  /** @type {Map<string, number>} */
  const callCounts = new Map();
  let executionCounter = 0;

  /** @param {string} method */
  async function read(method) {
    if (speed > 0) await new Promise((resolve) => setTimeout(resolve, Math.round(140 * speed)));
    if (!failures()) return;
    const count = (callCounts.get(method) || 0) + 1;
    callCounts.set(method, count);
    if (count % 2 === 1) throw new HttpError('simulated', 'Fallo transitorio simulado (demo). Reintentar debería recuperarlo.');
  }

  const agentMap = () => new Map(agents.map((a) => [a.id, a]));

  /** @param {Workflow} workflow @param {ExecutionInput} input @param {number} createdMs @returns {Execution} */
  function newExecution(workflow, input, createdMs) {
    executionCounter += 1;
    const byId = agentMap();
    return {
      id: `ex-${String(executionCounter).padStart(3, '0')}`,
      workflowId: workflow.id, workflowName: workflow.name, projectId: workflow.projectId,
      objective: input.objective, priority: input.priority, responsibleAgentId: input.responsibleAgentId,
      status: 'pending', createdAt: new Date(createdMs).toISOString(), startedAt: null, finishedAt: null,
      limits: { maxIterations: input.maxIterations, timeoutSeconds: input.timeoutSeconds, budgetUsd: input.budgetUsd, enforced: true },
      usage: { tokensIn: 0, tokensOut: 0, costUsd: 0, iterations: 0, elapsedSeconds: 0, measured: true },
      steps: workflow.steps.map((step) => ({
        key: step.key, agentId: step.agentId, agentName: byId.get(step.agentId)?.name || step.agentId, status: 'pending',
        model: byId.get(step.agentId)?.model || null, dependencies: [...step.dependsOn], requiresApproval: step.requiresApproval,
        error: null, startedAt: null, finishedAt: null, tools: [], tokensIn: 0, tokensOut: 0,
      })),
      artifacts: [], finalAnswer: null, error: null, attempt: 1, origin: 'demo',
    };
  }

  /** @param {RunRecord} record @param {RunEvent} event */
  function apply(record, event) {
    record.events.push(event);
    record.execution = applyEvent(record.execution, event);
    for (const listener of [...record.listeners]) listener.onEvent(event);
  }

  /** @param {RunRecord} record */
  function drive(record) {
    if (record.timer || !record.sim) return;
    const step = () => {
      record.timer = null;
      const tick = record.sim?.next();
      if (!tick) return;
      if (speed === 0) {
        apply(record, tick.event);
        step();
        return;
      }
      record.timer = setTimeout(() => {
        record.timer = null;
        apply(record, { ...tick.event, at: new Date(now()).toISOString() });
        step();
      }, Math.round(tick.delayMs * speed));
    };
    if (speed === 0) step();
    else record.timer = setTimeout(step, 0);
  }

  /** @param {RunRecord} record @param {string} kind @param {string} [at] */
  function startEvent(record, kind, at = new Date(now()).toISOString()) {
    const last = record.events.length ? record.events[record.events.length - 1].seq : 0;
    apply(record, { seq: last + 1, kind, stepKey: null, payload: {}, at });
  }

  // Historical runs, simulated to completion synchronously at start-up.
  if (options.history !== false) {
    for (const entry of HISTORY) {
      const workflow = workflows.find((w) => w.id === entry.workflowId);
      if (!workflow) continue;
      const input = { workflowId: workflow.id, objective: entry.objective, priority: /** @type {const} */ ('media'), responsibleAgentId: null,
                      maxIterations: 40, timeoutSeconds: 1800, budgetUsd: entry.outcome === 'budget' ? 0.02 : 2 };
      const execution = newExecution(workflow, input, now() - entry.hoursAgo * 3600_000);
      /** @type {RunRecord} */
      const record = { execution, events: [], sim: null, timer: null, listeners: new Set() };
      runs.set(execution.id, record);
      startEvent(record, 'run_created', execution.createdAt);
      record.sim = createSimulation({ execution: record.execution, agents: agentMap(), seed: entry.seed, startSeq: 1,
                                      failStep: entry.outcome === 'error' ? workflow.steps[1].key : null });
      for (let guard = 0; guard < 500; guard += 1) {
        const tick = record.sim.next();
        if (tick) { apply(record, tick.event); continue; }
        const waiting = record.sim.waitingFor();
        if (waiting && entry.outcome !== 'waiting') {
          record.sim.approve(waiting);
          decisions.set(`apr-${execution.id}-${waiting}`, { status: 'aprobada', justification: 'Evidencia revisada (demo).', decidedAt: record.events[record.events.length - 1].at, decidedBy: 'revisor.demo' });
          continue;
        }
        break;
      }
    }
  }

  /** @param {string} id */
  function runOrThrow(id) {
    const record = runs.get(id);
    if (!record) throw new HttpError('not_found', 'Ejecución no encontrada');
    return record;
  }

  /** @returns {Agent[]} */
  function liveAgents() {
    const busy = new Set();
    for (const record of runs.values()) for (const step of record.execution.steps) if (step.status === 'running') busy.add(step.agentId);
    return agents.map((a) => ({ ...clone(a), status: a.status === 'active' && busy.has(a.id) ? 'running' : a.status }));
  }

  /** @returns {ApprovalRequest[]} */
  function stepApprovals() {
    /** @type {ApprovalRequest[]} */
    const items = [];
    for (const record of runs.values()) {
      for (const step of record.execution.steps.filter((s) => s.requiresApproval)) {
        const id = `apr-${record.execution.id}-${step.key}`;
        const decided = decisions.get(id);
        const waiting = record.sim?.waitingFor() === step.key && record.execution.status === 'waiting_approval';
        if (!decided && !waiting) continue;
        const requestEvent = record.events.find((e) => e.kind === 'step_approval_requested' && e.stepKey === step.key);
        items.push({
          id, kind: 'paso', title: `Aprobar el paso «${step.agentName}»`, requestedBy: step.agentName, agentId: step.agentId,
          executionId: record.execution.id, stepKey: step.key, proposalId: null,
          action: `Ejecutar ${step.agentName} dentro de «${record.execution.workflowName}»`,
          args: { ejecución: record.execution.id, paso: step.key, objetivo: record.execution.objective, modelo: step.model || '—' },
          impact: 'Hasta aprobar, este paso y los que dependen de él no se ejecutan. Aprobar permite que el agente trabaje con sus herramientas autorizadas.',
          rejectEffect: 'Rechazar detiene la ejecución; los artefactos ya producidos se conservan y puede reanudarse después.',
          risk: step.key === 'seguridad' ? 'alto' : 'medio', status: decided ? decided.status : 'pendiente',
          createdAt: requestEvent?.at || record.execution.createdAt, decidedAt: decided?.decidedAt || null,
          decidedBy: decided?.decidedBy || null, justification: decided?.justification || null, diff: null, origin: 'demo',
        });
      }
    }
    return items;
  }

  /** @type {ApprovalRequest[]} */
  const staticApprovals = [
    { id: 'apr-mem-glosario', kind: 'memoria', title: 'Actualizar «Glosario de métricas»', requestedBy: 'Documentador', agentId: 'ag-documentador',
      executionId: null, stepKey: null, proposalId: 'prop-001', action: 'Escribir en CMH_Canon/02_glosario_metricas.md', args: { archivo: 'CMH_Canon/02_glosario_metricas.md', líneas: '+2 −1' },
      impact: 'Cambia una definición del canon que leen todos los agentes. Se guarda una copia recuperable antes de escribir.', rejectEffect: 'La propuesta se descarta sin escribir el archivo.',
      risk: 'alto', status: 'pendiente', createdAt: new Date(now() - 50 * 60_000).toISOString(), decidedAt: null, decidedBy: null, justification: null, origin: 'demo',
      diff: '--- CMH_Canon/02_glosario_metricas.md\n+++ propuesta\n@@ -12,3 +12,4 @@\n-| Disponibilidad | PENDIENTE |\n+| Disponibilidad | Horas operativas / horas calendario (definición de demostración) |\n+| Fuente | Reporte de mantenimiento (demo) |' },
    { id: 'apr-tool-correo', kind: 'herramienta', title: 'Enviar el informe integrado por correo', requestedBy: 'Sostenibilidad', agentId: 'ag-sostenibilidad',
      executionId: null, stepKey: null, proposalId: null, action: 'send_email', args: { destinatarios: 'comite.demo@ejemplo.invalid', asunto: 'Informe integrado (demo)', adjuntos: '1' },
      impact: 'Acción externa: el informe sale de la plataforma y no puede retirarse después del envío.', rejectEffect: 'El correo no se envía; el informe queda disponible como artefacto.',
      risk: 'alto', status: 'pendiente', createdAt: new Date(now() - 20 * 60_000).toISOString(), decidedAt: null, decidedBy: null, justification: null, diff: null, origin: 'demo' },
    { id: 'apr-mem-decisiones', kind: 'memoria', title: 'Agregar fila a «Decisiones históricas»', requestedBy: 'Documentador', agentId: 'ag-documentador',
      executionId: null, stepKey: null, proposalId: 'prop-000', action: 'Escribir en CMH_Canon/05_decisiones_historicas.md', args: { archivo: 'CMH_Canon/05_decisiones_historicas.md', líneas: '+1' },
      impact: 'Agrega una decisión al canon.', rejectEffect: 'La propuesta se descarta sin escribir.', risk: 'medio', status: 'aprobada',
      createdAt: new Date(now() - 26 * 3600_000).toISOString(), decidedAt: new Date(now() - 25 * 3600_000).toISOString(), decidedBy: 'usuario.demo',
      justification: 'Decisión confirmada en comité (demo).', diff: '+| 2026-09-23 | Una sola pila FCST (demo) |', origin: 'demo' },
  ];

  /** @returns {ApprovalRequest[]} */
  function currentApprovals() {
    const items = [...stepApprovals(), ...staticApprovals.map((a) => {
      const decided = decisions.get(a.id);
      return decided ? { ...clone(a), status: decided.status, justification: decided.justification, decidedAt: decided.decidedAt, decidedBy: decided.decidedBy } : clone(a);
    })];
    return items.sort((a, b) => (a.status === 'pendiente' ? 0 : 1) - (b.status === 'pendiente' ? 0 : 1) || b.createdAt.localeCompare(a.createdAt));
  }

  /** @param {string} message */
  const invalid = (message) => new HttpError('validation', message, 400);

  /** @type {DataSource & {runRecord: (id: string) => RunRecord|undefined}} */
  const source = {
    mode: 'demo',
    capabilities: { agents: true, executions: true, executionLimits: true, approvals: true, memory: true, memoryArchive: true,
                    tools: true, traces: true, evaluations: true, security: true, providers: true, chatModel: false },
    runRecord: (id) => runs.get(id),

    async listProjects() { await read('projects'); return clone(PROJECTS); },
    async listAgents() { await read('agents'); return liveAgents(); },
    async getAgent(id) {
      await read('agent');
      const found = liveAgents().find((a) => a.id === id);
      if (!found) throw new HttpError('not_found', 'Agente no encontrado', 404);
      return found;
    },
    async saveAgent(input, id) {
      if (!input.name.trim() || !input.role.trim() || !input.instructions.trim()) throw invalid('Nombre, rol e instrucciones no pueden quedar vacíos');
      const unknown = input.allowedTools.filter((tool) => !TOOLS.some((t) => t.id === tool));
      if (unknown.length) throw invalid(`Herramienta desconocida: ${unknown.join(', ')}`);
      if (input.projectId && !PROJECTS.some((p) => p.id === input.projectId)) throw invalid('Proyecto desconocido');
      if (agents.some((a) => a.name.toLocaleLowerCase() === input.name.trim().toLocaleLowerCase() && a.id !== id)) throw new HttpError('conflict', 'Ya existe un agente con ese nombre', 409);
      if (id) {
        const agent = agents.find((a) => a.id === id);
        if (!agent) throw new HttpError('not_found', 'Agente no encontrado', 404);
        if (agent.instructions !== input.instructions) agent.instructionsVersion += 1;
        Object.assign(agent, { name: input.name.trim(), role: input.role.trim(), projectId: input.projectId, model: input.model,
                               allowedTools: [...input.allowedTools].sort(), workspace: input.workspace, instructions: input.instructions,
                               taskId: input.taskId, permissionLevel: permissionFor(input.allowedTools) });
        return clone(agent);
      }
      /** @type {Agent} */
      const created = { id: `ag-${seedFrom(input.name + agents.length).toString(36)}`, name: input.name.trim(), role: input.role.trim(),
        projectId: input.projectId, status: 'paused', model: input.model, allowedTools: [...input.allowedTools].sort(), workspace: input.workspace,
        permissionLevel: permissionFor(input.allowedTools), instructions: input.instructions, instructionsVersion: 1, taskId: input.taskId,
        capabilities: [], domain: 'operaciones', origin: 'demo' };
      agents.push(created);
      return clone(created);
    },
    async setAgentStatus(id, status) {
      const agent = agents.find((a) => a.id === id);
      if (!agent) throw new HttpError('not_found', 'Agente no encontrado', 404);
      if (status === 'active' && (!agent.model || !agent.projectId)) throw invalid('Proyecto y modelo son obligatorios para activar un agente');
      agent.status = status;
      return clone(agent);
    },

    async listWorkflows() { await read('workflows'); return clone(workflows); },
    async listExecutions() {
      await read('executions');
      return [...runs.values()].map((r) => clone(r.execution)).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    },
    async getExecution(id) { await read('execution'); return clone(runOrThrow(id).execution); },
    async createExecution(input) {
      const workflow = workflows.find((w) => w.id === input.workflowId);
      if (!workflow) throw invalid('Flujo desconocido');
      if (!input.objective.trim()) throw invalid('El objetivo es obligatorio');
      const byId = agentMap();
      const paused = workflow.steps.filter((s) => byId.get(s.agentId)?.status !== 'active').map((s) => byId.get(s.agentId)?.name || s.agentId);
      if (paused.length) throw invalid(`Hay agentes pausados en el flujo: ${paused.join(', ')}. Actívalos en el Centro de agentes.`);
      const execution = newExecution(workflow, input, now());
      /** @type {RunRecord} */
      const record = { execution, events: [], sim: null, timer: null, listeners: new Set() };
      runs.set(execution.id, record);
      startEvent(record, 'run_created');
      record.sim = createSimulation({ execution: record.execution, agents: byId, seed: seedFrom(execution.id + input.objective), startSeq: 1 });
      drive(record);
      return clone(record.execution);
    },
    async cancelExecution(id) {
      const record = runOrThrow(id);
      if (!['running', 'pending', 'waiting_approval'].includes(record.execution.status)) throw new HttpError('conflict', 'La ejecución no está activa', 409);
      if (record.timer) clearTimeout(record.timer);
      record.timer = null;
      for (const event of record.sim?.cancel() || []) apply(record, event);
      return clone(record.execution);
    },
    async retryExecution(id, limits = {}) {
      const record = runOrThrow(id);
      if (!['error', 'interrupted'].includes(record.execution.status)) throw new HttpError('conflict', 'Solo se reintenta una ejecución con error o detenida', 409);
      const execution = record.execution;
      execution.attempt += 1;
      execution.limits = { ...execution.limits, ...limits };
      for (const step of execution.steps) if (step.status !== 'completed') { step.status = 'pending'; step.error = null; }
      execution.error = null;
      for (const [key, decision] of [...decisions.entries()]) {
        if (key.startsWith(`apr-${id}-`) && decision.status === 'rechazada') decisions.delete(key);
      }
      const preApproved = [...decisions.entries()].filter(([key, d]) => key.startsWith(`apr-${id}-`) && d.status === 'aprobada').map(([key]) => key.slice(`apr-${id}-`.length));
      startEvent(record, 'run_resume_requested');
      record.sim = createSimulation({ execution, agents: agentMap(), seed: seedFrom(id) + execution.attempt, startSeq: record.events[record.events.length - 1].seq, preApproved });
      drive(record);
      return clone(record.execution);
    },
    openRunStream(id, handlers) {
      const record = runs.get(id);
      if (!record) {
        handlers.onState?.('closed');
        return { close() {} };
      }
      for (const event of record.events) handlers.onEvent(event);
      record.listeners.add(handlers);
      handlers.onState?.('open');
      return { close() { record.listeners.delete(handlers); handlers.onState?.('closed'); } };
    },

    async listApprovals() {
      await read('approvals');
      return currentApprovals();
    },
    async decideApproval(id, decision, justification, actor) {
      const request = currentApprovals().find((a) => a.id === id);
      if (!request) throw new HttpError('not_found', 'Solicitud no encontrada', 404);
      if (request.status !== 'pendiente') throw new HttpError('conflict', 'La solicitud ya fue decidida', 409);
      const text = justification.trim();
      if (decision === 'rechazar' && text.length < 10) throw invalid('Rechazar exige una justificación de al menos 10 caracteres');
      if (decision === 'aprobar' && request.risk === 'alto' && text.length < 10) throw invalid('El riesgo alto exige justificar también la aprobación (mínimo 10 caracteres)');
      if (request.kind === 'paso' && request.executionId && request.stepKey) {
        const record = runOrThrow(request.executionId);
        if (decision === 'aprobar') {
          if (!record.sim?.approve(request.stepKey)) throw new HttpError('conflict', 'El paso ya no espera aprobación', 409);
          drive(record);
        } else {
          for (const event of record.sim?.cancel() || []) apply(record, event);
        }
      }
      const decided = { status: /** @type {'aprobada'|'rechazada'} */ (decision === 'aprobar' ? 'aprobada' : 'rechazada'), justification: text, decidedAt: new Date(now()).toISOString(), decidedBy: actor };
      decisions.set(id, decided);
      recordAudit({ actor, action: decision === 'aprobar' ? 'Aprobó solicitud' : 'Rechazó solicitud', target: request.title,
                    outcome: decision === 'aprobar' ? 'ok' : 'rechazado', detail: text || 'Sin justificación' });
      return { ...request, ...decided };
    },

    async listMemory() { await read('memory'); return clone(memory); },
    async readMemory(id) {
      const record = memory.find((m) => m.id === id);
      if (!record) throw new HttpError('not_found', 'Registro no encontrado', 404);
      return clone(record);
    },
    async archiveMemory(id) {
      const record = memory.find((m) => m.id === id);
      if (!record) throw new HttpError('not_found', 'Registro no encontrado', 404);
      if (!record.archivable) throw new HttpError('not_supported', 'Los archivos del canon son la fuente de verdad: no se archivan desde aquí', 400);
      record.archived = !record.archived;
      recordAudit({ actor: 'usuario', action: record.archived ? 'Archivó memoria' : 'Restauró memoria', target: record.title, outcome: 'ok', detail: record.kind });
      return clone(record);
    },

    async listTools() {
      await read('tools');
      const usage = new Map();
      for (const record of runs.values()) for (const e of record.events) if (e.kind === 'tool_started') usage.set(String(e.payload.tool), (usage.get(String(e.payload.tool)) || 0) + 1);
      return TOOLS.map((t) => ({ ...clone(t), usageCount: usage.get(t.id) || 0, usedBy: agents.filter((a) => a.allowedTools.includes(t.id)).map((a) => a.name) }));
    },
    async listMcpServers() { await read('mcp'); return clone(MCP_SERVERS); },

    async listTraces() {
      await read('traces');
      return [...runs.values()].map((r) => buildTrace(r.execution, r.events)).sort((a, b) => b.startedAt.localeCompare(a.startedAt));
    },
    async getTrace(executionId) { await read('trace'); const r = runOrThrow(executionId); return buildTrace(r.execution, r.events); },

    async listEvaluations() { await read('evaluations'); return clone(evaluations); },
    async runEvaluation(id) {
      const evaluation = evaluations.find((e) => e.id === id);
      if (!evaluation) throw new HttpError('not_found', 'Evaluación no encontrada', 404);
      for (const item of evaluation.cases) if (item.result === 'pendiente') { item.result = 'ok'; item.score = 1; }
      const scored = evaluation.cases.filter((c) => c.score !== null);
      evaluation.score = scored.length ? scored.reduce((sum, c) => sum + (c.score || 0), 0) / scored.length : null;
      evaluation.runAt = new Date(now()).toISOString();
      if (evaluation.score !== null) evaluation.history.push({ runAt: evaluation.runAt, score: evaluation.score });
      if (evaluation.baselineScore === null) evaluation.baselineScore = evaluation.score;
      return clone(evaluation);
    },

    async getSecurity() {
      await read('security');
      const overview = clone(SECURITY);
      overview.audit = [...listAudit(), ...overview.audit];
      return overview;
    },
    async listProviders() { await read('providers'); return clone(PROVIDERS); },
    async getServices() {
      await read('services');
      const connected = MCP_SERVERS.filter((s) => s.status === 'connected').length;
      return [
        { id: 'api', name: 'API del sistema', tone: 'ok', detail: 'Simulada en el navegador', origin: 'demo' },
        { id: 'eventos', name: 'Eventos en vivo', tone: 'ok', detail: 'Simulador determinista', origin: 'demo' },
        { id: 'modelos', name: 'Proveedores de modelos', tone: 'ok', detail: `${PROVIDERS.length} de ${PROVIDERS.length} en línea`, origin: 'demo' },
        { id: 'mcp', name: 'Servidores MCP', tone: connected === MCP_SERVERS.length ? 'ok' : 'warn', detail: `${connected} de ${MCP_SERVERS.length} conectados`, origin: 'demo' },
      ];
    },
    async askModel() {
      throw new HttpError('not_supported', 'En modo demo no hay un modelo conectado; usa los comandos sugeridos.');
    },
  };
  return source;
}
