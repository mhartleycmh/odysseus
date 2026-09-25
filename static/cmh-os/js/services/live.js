// Live data source over the Odysseus API. Maps backend payloads to the shared
// contracts, never invents data, and drops secrets at the boundary (ADR-011).
// Domains without a backend are served by the demo source and keep origin
// "demo", so the UI can label them (ADR-003).
import { request as defaultRequest, HttpError } from './http.js';
import { applyEvent, buildTrace, finalAnswerOf, RUN_EVENT_KINDS, TERMINAL_RUN_EVENTS, topoOrder } from './run-state.js';
import { permissionFor, riskOfTool, isReadOnlyTool, READ_TOOLS, redactUrl, redactText } from './derive.js';
import { expectArray, expectObject, optNum, optStr, str, strList } from '../core/validate.js';
import { recordAudit, listAudit } from '../core/audit.js';

/** @typedef {import('../types.js').DataSource} DataSource */
/** @typedef {import('../types.js').Agent} Agent */
/** @typedef {import('../types.js').Execution} Execution */
/** @typedef {import('../types.js').ExecutionStatus} ExecutionStatus */
/** @typedef {import('../types.js').StepStatus} StepStatus */
/** @typedef {import('../types.js').Workflow} Workflow */
/** @typedef {import('../types.js').ApprovalRequest} ApprovalRequest */
/** @typedef {import('../types.js').MemoryRecord} MemoryRecord */
/** @typedef {import('../types.js').MCPServer} MCPServer */
/** @typedef {import('../types.js').ModelProvider} ModelProvider */
/** @typedef {import('../types.js').Tool} Tool */
/** @typedef {import('../types.js').RunEvent} RunEvent */
/** @typedef {import('./http.js').RequestOptions} RequestOptions */

const EXECUTION_STATUSES = ['pending', 'running', 'waiting_approval', 'completed', 'error', 'interrupted', 'paused'];
const STEP_STATUSES = ['pending', 'running', 'waiting_approval', 'completed', 'error', 'interrupted'];

/** @param {string} value @returns {ExecutionStatus} */
const execStatus = (value) => /** @type {ExecutionStatus} */ (EXECUTION_STATUSES.includes(value) ? value : 'error');
/** @param {string} value @returns {StepStatus} */
const stepStatus = (value) => /** @type {StepStatus} */ (STEP_STATUSES.includes(value) ? value : 'error');

/**
 * @param {unknown} raw
 * @returns {Agent}
 */
export function mapAgent(raw) {
  const obj = expectObject(raw, 'agente');
  const tools = strList(obj, 'allowed_tools');
  const status = str(obj, 'status', 'agente');
  return {
    id: str(obj, 'id', 'agente'), name: str(obj, 'name', 'agente'), role: str(obj, 'role', 'agente'),
    projectId: optStr(obj, 'project_id'), status: status === 'active' ? 'active' : 'paused', model: optStr(obj, 'model'),
    allowedTools: tools, workspace: optStr(obj, 'workspace'), permissionLevel: permissionFor(tools),
    instructions: optStr(obj, 'instructions') || '', instructionsVersion: optNum(obj, 'instructions_version') || 1,
    taskId: optStr(obj, 'task_id'),
    capabilities: tools.map((tool) => ({ id: tool, label: tool, description: isReadOnlyTool(tool) ? 'Herramienta de lectura' : 'Herramienta que puede modificar' })),
    domain: 'cmh', origin: 'real',
  };
}

/**
 * @param {unknown} raw
 * @returns {Workflow}
 */
export function mapWorkflow(raw) {
  const obj = expectObject(raw, 'flujo');
  const steps = expectArray(obj.steps, 'flujo.steps').map((item) => {
    const step = expectObject(item, 'flujo.steps[]');
    return { key: str(step, 'key', 'paso'), agentId: str(step, 'agent_id', 'paso'), dependsOn: strList(step, 'depends_on'),
             independentOf: strList(step, 'independent_of'), requiresApproval: step.requires_approval === true };
  });
  return { id: str(obj, 'id', 'flujo'), name: optStr(obj, 'name') || 'Flujo sin nombre', projectId: str(obj, 'project_id', 'flujo'),
           version: optNum(obj, 'version') || 1, description: '', steps, origin: 'real' };
}

/** @param {string|null} text */
const redactOptional = (text) => (text === null ? null : redactText(text));

/**
 * Drop MCP env values at the boundary; only variable names reach the UI.
 * @param {unknown} raw
 * @returns {MCPServer}
 */
export function mapMcpServer(raw) {
  const obj = expectObject(raw, 'servidor MCP');
  const env = obj.env && typeof obj.env === 'object' && !Array.isArray(obj.env) ? Object.keys(obj.env) : [];
  const status = optStr(obj, 'status') || 'disconnected';
  return {
    id: str(obj, 'id', 'servidor MCP'), name: optStr(obj, 'name') || 'Servidor MCP', transport: optStr(obj, 'transport') || '—',
    status: obj.needs_oauth === true ? 'needs_auth' : status === 'connected' ? 'connected' : status === 'error' ? 'error' : 'disconnected',
    toolCount: optNum(obj, 'tool_count') || 0, enabledToolCount: optNum(obj, 'enabled_tool_count') || 0,
    envKeys: env.sort(), error: redactOptional(optStr(obj, 'error')), origin: 'real',
  };
}

/**
 * @param {unknown} raw
 * @returns {ModelProvider}
 */
export function mapProvider(raw) {
  const obj = expectObject(raw, 'proveedor');
  const models = Array.isArray(obj.models)
    ? obj.models.map((m) => (typeof m === 'string' ? m : m && typeof m === 'object' && 'id' in m ? String(m.id) : '')).filter(Boolean)
    : [];
  const status = optStr(obj, 'status');
  return {
    id: str(obj, 'id', 'proveedor'), name: optStr(obj, 'name') || 'Proveedor', baseUrl: redactUrl(optStr(obj, 'base_url') || ''),
    status: status === 'online' ? 'online' : status === 'offline' ? 'offline' : 'unknown', hasKey: obj.has_key === true,
    keyFingerprint: optStr(obj, 'api_key_fingerprint') || null, supportsTools: typeof obj.supports_tools === 'boolean' ? obj.supports_tools : null,
    models, category: optStr(obj, 'category') || '—', origin: 'real',
  };
}

/**
 * @typedef {Object} LiveOptions
 * @property {import('../types.js').DataSource} demo Serves domains without a backend.
 * @property {(path: string, options?: RequestOptions) => Promise<unknown>} [request]
 * @property {typeof EventSource} [EventSourceImpl]
 * @property {number} [traceIdleMs]
 */

/**
 * @param {LiveOptions} options
 * @returns {DataSource}
 */
export function createLiveSource(options) {
  const request = options.request || defaultRequest;
  const demo = options.demo;
  const EventSourceImpl = options.EventSourceImpl || globalThis.EventSource;
  const traceIdleMs = options.traceIdleMs ?? 1200;
  /** @type {Map<string, string>} */
  const chatSessions = new Map();

  const api = (/** @type {string} */ path, /** @type {RequestOptions} */ opts = {}) => request(path, opts);

  async function agents() {
    const body = expectObject(await api('/api/cmh/agents'), 'agentes');
    return expectArray(body.agents, 'agentes').map(mapAgent);
  }
  async function workflows() {
    const body = expectObject(await api('/api/cmh/workflows'), 'flujos');
    return expectArray(body.workflows, 'flujos').map(mapWorkflow);
  }
  async function runSummaries() {
    const body = expectObject(await api('/api/cmh/runs'), 'ejecuciones');
    return expectArray(body.runs, 'ejecuciones').map((item) => expectObject(item, 'ejecución'));
  }

  /**
   * @param {Record<string, unknown>} summary
   * @param {Map<string, Workflow>} flows
   * @returns {Execution}
   */
  function executionFromSummary(summary, flows) {
    const definitionId = optStr(summary, 'definition_id') || '';
    const flow = flows.get(definitionId);
    return {
      id: str(summary, 'id', 'ejecución'), workflowId: definitionId, workflowName: flow?.name || 'Flujo', projectId: optStr(summary, 'project_id') || '',
      objective: '', priority: 'media', responsibleAgentId: null, status: execStatus(optStr(summary, 'status') || 'error'),
      createdAt: optStr(summary, 'created_at') || new Date(0).toISOString(), startedAt: null, finishedAt: null,
      limits: { maxIterations: 12, timeoutSeconds: null, budgetUsd: null, enforced: false },
      usage: { tokensIn: 0, tokensOut: 0, costUsd: null, iterations: 0, elapsedSeconds: 0, measured: false },
      steps: [], artifacts: [], finalAnswer: null, error: null, attempt: 1, origin: 'real',
    };
  }

  /** Lists every detail needs; fetched once per refresh, not once per run. */
  async function sharedLists() {
    const [summaries, flows, agentList] = await Promise.all([runSummaries(), workflows(), agents().catch(() => /** @type {Agent[]} */ ([]))]);
    return { summaries, flows, agentList };
  }

  /**
   * @param {string} id
   * @param {Awaited<ReturnType<typeof sharedLists>>} [shared]
   * @returns {Promise<Execution>}
   */
  async function executionDetail(id, shared) {
    const [detailRaw, lists] = await Promise.all([api(`/api/cmh/runs/${encodeURIComponent(id)}`), shared || sharedLists()]);
    const { summaries, flows, agentList } = lists;
    const detail = expectObject(detailRaw, 'ejecución');
    const flowMap = new Map(flows.map((f) => [f.id, f]));
    const summary = summaries.find((s) => s.id === id) || { id, status: detail.status, project_id: detail.project_id };
    const base = executionFromSummary(summary, flowMap);
    const flow = flowMap.get(base.workflowId);
    const names = new Map(agentList.map((a) => [a.id, a.name]));
    base.status = execStatus(str(detail, 'status', 'ejecución'));
    base.steps = expectArray(detail.steps, 'ejecución.steps').map((item) => {
      const step = expectObject(item, 'paso');
      const key = str(step, 'key', 'paso');
      const agentId = optStr(step, 'agent_id') || '';
      return { key, agentId, agentName: names.get(agentId) || key, status: stepStatus(optStr(step, 'status') || 'error'),
               model: optStr(step, 'model'), dependencies: strList(step, 'dependencies'),
               requiresApproval: Boolean(flow?.steps.find((s) => s.key === key)?.requiresApproval),
               error: optStr(step, 'error'), startedAt: null, finishedAt: null, tools: [], tokensIn: 0, tokensOut: 0 };
    });
    base.steps = topoOrder(base.steps).map((key) => /** @type {import('../types.js').ExecutionStep} */ (base.steps.find((s) => s.key === key)));
    base.artifacts = expectArray(detail.artifacts, 'ejecución.artifacts').map((item) => {
      const artifact = expectObject(item, 'artefacto');
      return { id: str(artifact, 'id', 'artefacto'), stepKey: str(artifact, 'step_key', 'artefacto'),
               model: optStr(artifact, 'model') || '', content: optStr(artifact, 'content') || '' };
    });
    base.error = base.steps.find((s) => s.error)?.error || null;
    if (base.status === 'completed') base.finalAnswer = finalAnswerOf(base);
    return base;
  }

  /**
   * Replay a run's stored events (the SSE endpoint sends its backlog first).
   * @param {string} id
   * @returns {Promise<RunEvent[]>}
   */
  function replayEvents(id) {
    return new Promise((resolve) => {
      /** @type {RunEvent[]} */
      const events = [];
      /** @type {ReturnType<typeof setTimeout>|null} */
      let timer = null;
      const finish = () => {
        if (timer) clearTimeout(timer);
        stream.close();
        resolve(events);
      };
      /** @param {number} ms */
      const arm = (ms) => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(finish, ms);
      };
      // A terminal event is not the end of the backlog: a failed or interrupted
      // run may have been resumed. Finish only after the stream goes quiet,
      // sooner once a terminal event has been seen.
      const stream = openStream(id, { onEvent(event) { events.push(event); arm(TERMINAL_RUN_EVENTS.includes(event.kind) ? Math.min(400, traceIdleMs) : traceIdleMs); } });
      arm(traceIdleMs);
    });
  }

  /**
   * @param {string} id
   * @param {import('../types.js').RunStreamHandlers} handlers
   */
  function openStream(id, handlers) {
    if (!EventSourceImpl) {
      handlers.onState?.('closed');
      return { close() {} };
    }
    const source = new EventSourceImpl(`/api/cmh/runs/${encodeURIComponent(id)}/events`, { withCredentials: true });
    for (const kind of RUN_EVENT_KINDS) {
      source.addEventListener(kind, (raw) => {
        const message = /** @type {MessageEvent} */ (raw);
        try {
          const data = expectObject(JSON.parse(String(message.data)), 'evento');
          handlers.onEvent({ seq: Number(message.lastEventId) || 0, kind, stepKey: optStr(data, 'step_key'),
                             payload: data.payload && typeof data.payload === 'object' ? /** @type {Record<string, unknown>} */ (data.payload) : {},
                             at: optStr(data, 'at') || new Date().toISOString() });
        } catch {
          // A malformed event is skipped; the next state refresh corrects the view.
        }
      });
    }
    source.onopen = () => handlers.onState?.('open');
    source.onerror = () => handlers.onState?.(source.readyState === 2 ? 'closed' : 'reconnecting');
    return { close() { source.close(); handlers.onState?.('closed'); } };
  }

  /** @returns {Promise<ApprovalRequest[]>} */
  async function approvals() {
    /** @type {ApprovalRequest[]} */
    const items = [];
    const shared = await sharedLists();
    const waiting = shared.summaries.filter((s) => s.status === 'waiting_approval').slice(0, 10);
    const details = await Promise.all(waiting.map((s) => executionDetail(String(s.id), shared)));
    for (const execution of details) {
      for (const step of execution.steps.filter((s) => s.status === 'waiting_approval')) {
        items.push({
          id: `apr-${execution.id}-${step.key}`, kind: 'paso', title: `Aprobar el paso «${step.agentName}»`, requestedBy: step.agentName,
          agentId: step.agentId, executionId: execution.id, stepKey: step.key, proposalId: null,
          action: `Ejecutar ${step.agentName} dentro de «${execution.workflowName}»`,
          args: { ejecución: execution.id, paso: step.key, modelo: step.model || '—', dependencias: step.dependencies.join(', ') || '—' },
          impact: 'Hasta aprobar, este paso y los que dependen de él no se ejecutan.',
          rejectEffect: 'El backend no tiene rechazo de paso: rechazar detiene la ejecución, que puede reanudarse y volverá a pedir aprobación.',
          risk: 'medio', status: 'pendiente', createdAt: execution.createdAt, decidedAt: null, decidedBy: null, justification: null, diff: null, origin: 'real',
        });
      }
    }
    // Step decisions taken in this browser: the backend keeps no history of them.
    for (const entry of listAudit().filter((a) => a.target.startsWith('step:'))) {
      const [, executionId = '', stepKey = ''] = entry.target.split(':');
      if (items.some((item) => item.executionId === executionId && item.stepKey === stepKey)) continue;
      items.push({
        id: `apr-${executionId}-${stepKey}-${entry.id}`, kind: 'paso', title: `Paso «${stepKey}» de ${executionId}`, requestedBy: stepKey, agentId: null,
        executionId, stepKey, proposalId: null, action: `Paso ${stepKey}`, args: { ejecución: executionId, paso: stepKey },
        impact: 'Decisión registrada en este navegador.', rejectEffect: 'Rechazar detuvo la ejecución.', risk: 'medio',
        status: entry.outcome === 'ok' ? 'aprobada' : 'rechazada', createdAt: entry.at, decidedAt: entry.at, decidedBy: entry.actor,
        justification: entry.detail, diff: null, origin: 'real',
      });
    }
    /** @type {Record<string, unknown>[]} */
    let proposals = [];
    try {
      const body = expectObject(await api('/api/cmh/memory-proposals'), 'propuestas');
      proposals = expectArray(body.proposals, 'propuestas').map((p) => expectObject(p, 'propuesta'));
    } catch {
      // Memory proposals failing must not hide the step approvals already found.
    }
    const pending = proposals.filter((p) => p.status === 'pending').slice(0, 20);
    const diffs = await Promise.all(pending.map((p) => api(`/api/cmh/memory-proposals/${encodeURIComponent(String(p.id))}`).then((d) => expectObject(d, 'propuesta')).catch(() => null)));
    const localDecisions = new Map(listAudit().filter((a) => a.target.startsWith('prop:')).map((a) => [a.target.slice(5), a]));
    for (const proposal of proposals) {
      const id = str(proposal, 'id', 'propuesta');
      const path = optStr(proposal, 'path') || '';
      const name = path.split(/[\\/]/).pop() || path;
      const statusRaw = optStr(proposal, 'status');
      const detail = diffs[pending.indexOf(proposal)] || null;
      const local = localDecisions.get(id);
      items.push({
        id: `apr-mem-${id}`, kind: 'memoria', title: `Escribir «${name}»`, requestedBy: 'Propuesta de memoria', agentId: null,
        executionId: null, stepKey: null, proposalId: id, action: `Escribir en ${path}`,
        args: { archivo: path, espejo: optStr(proposal, 'mirror') || '—', ...(statusRaw === 'restored' ? { 'estado en el backend': 'aprobada y luego restaurada (se recuperó la copia)' } : {}) },
        impact: 'Escribe en un archivo fuente de verdad (canon o ficha). El backend guarda una copia recuperable antes de escribir.',
        rejectEffect: 'La propuesta se descarta sin escribir el archivo.', risk: path.includes('CMH_Canon') ? 'alto' : 'medio',
        ...(statusRaw === 'restored' ? { title: `Escribir «${name}» (restaurada después)` } : {}),
        status: statusRaw === 'pending' ? 'pendiente' : statusRaw === 'rejected' ? 'rechazada' : 'aprobada',
        createdAt: optStr(proposal, 'created_at') || new Date(0).toISOString(), decidedAt: local?.at || null, decidedBy: local?.actor || null,
        justification: local?.detail || null, diff: detail ? optStr(detail, 'diff') : null, origin: 'real',
      });
    }
    return items;
  }

  /** @type {DataSource} */
  const source = {
    mode: 'real',
    capabilities: { agents: true, executions: true, executionLimits: false, approvals: true, memory: true, memoryArchive: false,
                    tools: true, traces: true, evaluations: false, security: false, providers: true, chatModel: true },

    async listProjects() {
      const body = expectObject(await api('/api/cmh/projects'), 'proyectos');
      return expectArray(body.projects, 'proyectos').map((raw) => {
        const obj = expectObject(raw, 'proyecto');
        return { id: str(obj, 'id', 'proyecto'), name: str(obj, 'name', 'proyecto'), status: optStr(obj, 'status') || '—', origin: /** @type {const} */ ('real') };
      });
    },
    listAgents: agents,
    async getAgent(id) {
      const found = (await agents()).find((a) => a.id === id);
      if (!found) throw new HttpError('not_found', 'Agente no encontrado', 404);
      return found;
    },
    async saveAgent(input, id) {
      const json = { name: input.name, project_id: input.projectId, role: input.role, instructions: input.instructions, model: input.model,
                     allowed_tools: input.allowedTools, workspace: input.workspace, task_id: input.taskId };
      const raw = await api(id ? `/api/cmh/agents/${encodeURIComponent(id)}` : '/api/cmh/agents', { method: id ? 'PUT' : 'POST', json });
      return mapAgent(raw);
    },
    async setAgentStatus(id, status) {
      const raw = await api(`/api/cmh/agents/${encodeURIComponent(id)}/${status === 'active' ? 'resume' : 'pause'}`, { method: 'POST' });
      return mapAgent(raw);
    },
    listWorkflows: workflows,
    async listExecutions() {
      const [summaries, flows] = await Promise.all([runSummaries(), workflows()]);
      const map = new Map(flows.map((f) => [f.id, f]));
      return summaries.map((s) => executionFromSummary(s, map));
    },
    getExecution: executionDetail,
    async createExecution(input) {
      const raw = expectObject(await api(`/api/cmh/workflows/${encodeURIComponent(input.workflowId)}/runs`, { method: 'POST', json: { initial_input: input.objective } }), 'ejecución');
      const execution = await executionDetail(str(raw, 'id', 'ejecución'));
      execution.objective = input.objective;
      return execution;
    },
    async cancelExecution(id) {
      await api(`/api/cmh/runs/${encodeURIComponent(id)}/stop`, { method: 'POST' });
      return executionDetail(id);
    },
    async retryExecution(id) {
      await api(`/api/cmh/runs/${encodeURIComponent(id)}/resume`, { method: 'POST' });
      return executionDetail(id);
    },
    openRunStream: openStream,

    listApprovals: approvals,
    async decideApproval(id, decision, justification, actor) {
      const request = (await approvals()).find((a) => a.id === id);
      if (!request) throw new HttpError('not_found', 'Solicitud no encontrada o ya decidida', 404);
      const text = justification.trim();
      if (decision === 'rechazar' && text.length < 10) throw new HttpError('validation', 'Rechazar exige una justificación de al menos 10 caracteres', 400);
      if (decision === 'aprobar' && request.risk === 'alto' && text.length < 10) throw new HttpError('validation', 'El riesgo alto exige justificar también la aprobación (mínimo 10 caracteres)', 400);
      if (request.kind === 'paso' && request.executionId && request.stepKey) {
        const run = encodeURIComponent(request.executionId);
        if (decision === 'aprobar') await api(`/api/cmh/runs/${run}/steps/${encodeURIComponent(request.stepKey)}/approve`, { method: 'POST' });
        else await api(`/api/cmh/runs/${run}/stop`, { method: 'POST' });
      } else if (request.kind === 'memoria' && request.proposalId) {
        await api(`/api/cmh/memory-proposals/${encodeURIComponent(request.proposalId)}/${decision === 'aprobar' ? 'approve' : 'reject'}`, { method: 'POST' });
      }
      // The backend stores no justification: keep it in the local, labelled trail.
      recordAudit({ actor, action: decision === 'aprobar' ? 'Aprobó solicitud' : 'Rechazó solicitud',
                    target: request.proposalId ? `prop:${request.proposalId}` : request.executionId && request.stepKey ? `step:${request.executionId}:${request.stepKey}` : request.title,
                    outcome: decision === 'aprobar' ? 'ok' : 'rechazado', detail: text || 'Sin justificación' });
      return { ...request, status: decision === 'aprobar' ? 'aprobada' : 'rechazada', justification: text, decidedAt: new Date().toISOString(), decidedBy: actor };
    },

    async listMemory() {
      const body = expectObject(await api('/api/cmh/memories'), 'memorias');
      /** @type {MemoryRecord[]} */
      const records = expectArray(body.memories, 'memorias').map((raw) => {
        const obj = expectObject(raw, 'memoria');
        const path = str(obj, 'path', 'memoria');
        const modified = optNum(obj, 'modified');
        const sourceName = optStr(obj, 'source') || 'Archivo CMH';
        return { id: `file:${path}`, kind: /** @type {const} */ ('semantica'), title: optStr(obj, 'name') || path, content: '', source: sourceName,
                 createdAt: modified ? new Date(modified * 1000).toISOString() : new Date(0).toISOString(), relevance: sourceName.startsWith('Canon') ? 0.9 : 0.7,
                 tags: [sourceName], archived: false, archivable: false, path, origin: /** @type {const} */ ('real') };
      });
      const shared = await sharedLists();
      const details = await Promise.all(shared.summaries.slice(0, 5).map((s) => executionDetail(String(s.id), shared).catch(() => null)));
      for (const execution of details) {
        if (!execution) continue;
        for (const artifact of execution.artifacts) {
          records.push({ id: `artifact:${artifact.id}`, kind: execution.status === 'running' || execution.status === 'waiting_approval' ? 'trabajo' : 'episodica',
                         title: `${artifact.stepKey} · ${execution.workflowName}`, content: artifact.content, source: `Artefacto de ${artifact.stepKey}`,
                         createdAt: execution.createdAt, relevance: 0.6, tags: [artifact.stepKey, artifact.model].filter(Boolean),
                         archived: false, archivable: false, path: null, origin: 'real' });
        }
      }
      return records;
    },
    async readMemory(id) {
      if (!id.startsWith('file:')) {
        const found = (await source.listMemory()).find((m) => m.id === id);
        if (!found) throw new HttpError('not_found', 'Registro no encontrado', 404);
        return found;
      }
      const path = id.slice(5);
      const body = expectObject(await api(`/api/cmh/memories/content?path=${encodeURIComponent(path)}`), 'contenido');
      return { id, kind: 'semantica', title: path.split(/[\\/]/).pop() || path, content: optStr(body, 'content') || '', source: 'Archivo CMH',
               createdAt: new Date().toISOString(), relevance: 0.9, tags: [], archived: false, archivable: false, path, origin: 'real' };
    },
    async archiveMemory() {
      throw new HttpError('not_supported', 'Los archivos CMH son la fuente de verdad: no se archivan ni borran desde aquí. Proponer un cambio pasa por aprobación.', 400);
    },

    async listTools() {
      const [agentList, mcpTools] = await Promise.all([agents(), api('/api/mcp/tools').then((b) => expectArray(b, 'herramientas MCP')).catch(() => [])]);
      /** @type {Map<string, Tool>} */
      const tools = new Map();
      const names = new Set([...READ_TOOLS, ...agentList.flatMap((a) => a.allowedTools)]);
      for (const name of names) {
        tools.set(name, { id: name, name, category: 'archivos', description: READ_TOOLS.includes(name) ? 'Herramienta de lectura confinada a la carpeta del agente.' : 'Herramienta nativa de Odysseus.',
                          risk: riskOfTool(name), enabled: true, readOnly: isReadOnlyTool(name), requiresApproval: !isReadOnlyTool(name), serverId: null,
                          usageCount: 0, usedBy: agentList.filter((a) => a.allowedTools.includes(name)).map((a) => a.name), origin: 'real' });
      }
      for (const raw of mcpTools) {
        const obj = expectObject(raw, 'herramienta MCP');
        const name = str(obj, 'name', 'herramienta MCP');
        const id = optStr(obj, 'qualified_name') || name;
        tools.set(id, { id, name, category: 'mcp', description: optStr(obj, 'description') || 'Herramienta MCP', risk: 'medio', enabled: obj.is_disabled !== true,
                        readOnly: false, requiresApproval: true, serverId: optStr(obj, 'server_id'), usageCount: 0, usedBy: [], origin: 'real' });
      }
      return [...tools.values()];
    },
    async listMcpServers() {
      return expectArray(await api('/api/mcp/servers'), 'servidores MCP').map(mapMcpServer);
    },
    async listTraces() {
      const executions = await source.listExecutions();
      return executions.map((execution) => buildTrace(execution, []));
    },
    async getTrace(executionId) {
      const [execution, events] = await Promise.all([executionDetail(executionId), replayEvents(executionId)]);
      const state = events.reduce((acc, event) => applyEvent(acc, event), execution);
      return buildTrace(state, events);
    },
    listEvaluations: () => demo.listEvaluations(),
    runEvaluation: (id) => demo.runEvaluation(id),
    async getSecurity() {
      const [overview, providers, servers] = await Promise.all([demo.getSecurity(), source.listProviders().catch(() => []), source.listMcpServers().catch(() => [])]);
      overview.secrets = [
        ...providers.map((p) => ({ id: `prov:${p.id}`, name: `Clave de ${p.name}`, owner: 'Endpoints de modelos', configured: p.hasKey, fingerprint: p.keyFingerprint, origin: /** @type {const} */ ('real') })),
        ...servers.flatMap((s) => s.envKeys.map((key) => ({ id: `mcp:${s.id}:${key}`, name: key, owner: s.name, configured: true, fingerprint: null, origin: /** @type {const} */ ('real') }))),
      ];
      overview.policies = overview.policies.filter((p) => p.origin === 'real');
      overview.audit = [...listAudit(), ...overview.audit];
      return overview;
    },
    async listProviders() {
      return expectArray(await api('/api/model-endpoints'), 'proveedores').map(mapProvider);
    },
    async getServices() {
      const checks = await Promise.allSettled([agents(), source.listProviders(), source.listMcpServers()]);
      const [agentCheck, providerCheck, mcpCheck] = checks;
      const providers = providerCheck.status === 'fulfilled' ? providerCheck.value : [];
      const servers = mcpCheck.status === 'fulfilled' ? mcpCheck.value : [];
      const online = providers.filter((p) => p.status === 'online').length;
      const connected = servers.filter((s) => s.status === 'connected').length;
      return [
        { id: 'api', name: 'API CMH', tone: agentCheck.status === 'fulfilled' ? 'ok' : 'risk', detail: agentCheck.status === 'fulfilled' ? 'Responde' : 'Sin respuesta', origin: 'real' },
        { id: 'eventos', name: 'Eventos en vivo', tone: EventSourceImpl ? 'ok' : 'warn', detail: EventSourceImpl ? 'SSE con reanudación por Last-Event-ID' : 'Navegador sin EventSource', origin: 'real' },
        { id: 'modelos', name: 'Proveedores de modelos', tone: providerCheck.status !== 'fulfilled' ? 'risk' : online === providers.length && online > 0 ? 'ok' : 'warn',
          detail: providerCheck.status === 'fulfilled' ? `${online} de ${providers.length} en línea` : 'No disponible', origin: 'real' },
        { id: 'mcp', name: 'Servidores MCP', tone: mcpCheck.status !== 'fulfilled' ? 'idle' : connected === servers.length ? 'ok' : 'warn',
          detail: mcpCheck.status === 'fulfilled' ? `${connected} de ${servers.length} conectados` : 'No disponible', origin: 'real' },
      ];
    },
    async askModel(message, endpointId, model) {
      const key = `${endpointId}|${model}`;
      let session = chatSessions.get(key);
      if (!session) {
        const created = expectObject(await api('/api/session', { method: 'POST', form: { name: 'Agentic OS · coordinador', endpoint_id: endpointId, model } }), 'sesión');
        session = str(created, 'id', 'sesión');
        chatSessions.set(key, session);
      }
      const reply = expectObject(await api('/api/chat', { method: 'POST', json: { message, session }, timeoutMs: 120000 }), 'respuesta');
      return optStr(reply, 'response') || '';
    },
  };
  return source;
}
