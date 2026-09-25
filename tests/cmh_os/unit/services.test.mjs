// Unit tests for the data layer: http, run-state reducer, simulator, demo and
// live sources, and the chat command router.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { request, HttpError, callMetrics } from '../../../static/cmh-os/js/services/http.js';
import { applyEvent, resetCounters, buildTrace, topoOrder, isFresh, TERMINAL_RUN_EVENTS, RUN_EVENT_KINDS } from '../../../static/cmh-os/js/services/run-state.js';
import { createSimulation } from '../../../static/cmh-os/js/services/simulator.js';
import { createDemoSource } from '../../../static/cmh-os/js/services/demo.js';
import { createLiveSource, mapMcpServer, mapProvider } from '../../../static/cmh-os/js/services/live.js';
import { parseCommand, respond } from '../../../static/cmh-os/js/services/chat.js';
import { AGENTS, WORKFLOWS } from '../../../static/cmh-os/js/mocks/data.js';

const SAMPLES = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../fixtures/api_samples.json'), 'utf8'));
const noSleep = async () => {};

/** @param {number} status @param {unknown} body */
const response = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

// --- http ------------------------------------------------------------------

test('GET retries a 5xx and returns the eventual success', async () => {
  let calls = 0;
  const fetchImpl = async () => (++calls < 3 ? response(502, { detail: 'bad gateway' }) : response(200, { ok: true }));
  assert.deepEqual(await request('/x', { fetchImpl, sleep: noSleep }), { ok: true });
  assert.equal(calls, 3);
});

test('POST is never retried and 4xx maps to a typed error with the server detail', async () => {
  let calls = 0;
  const fetchImpl = async () => { calls += 1; return response(500, { detail: 'boom' }); };
  await assert.rejects(request('/x', { method: 'POST', json: {}, fetchImpl, sleep: noSleep }), (e) => e instanceof HttpError && e.kind === 'server');
  assert.equal(calls, 1);
  const auth = async () => response(401, { detail: 'Not authenticated' });
  await assert.rejects(request('/x', { fetchImpl: auth, sleep: noSleep }), (e) => e instanceof HttpError && e.kind === 'auth' && e.message === 'No hay sesión iniciada en Odysseus.');
  const validation = async () => response(422, { detail: [{ msg: 'field required' }] });
  await assert.rejects(request('/x', { fetchImpl: validation, sleep: noSleep }), (e) => e.kind === 'validation' && /field required/.test(e.message));
});

test('a request that never answers ends as a timeout error', async () => {
  const fetchImpl = (_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))));
  await assert.rejects(request('/slow', { fetchImpl, timeoutMs: 20, retries: 0 }), (e) => e.kind === 'timeout');
  assert.ok(callMetrics().some((m) => m.path === '/slow' && m.status === 0));
});

// --- run-state -------------------------------------------------------------

/** @returns {import('../../../static/cmh-os/js/types.js').Execution} */
function sampleExecution() {
  return {
    id: 'run-1', workflowId: 'wf-1', workflowName: 'Flujo', projectId: 'p', objective: 'x', priority: 'media', responsibleAgentId: null,
    status: 'pending', createdAt: '2026-09-24T15:00:00Z', startedAt: null, finishedAt: null,
    limits: { maxIterations: null, timeoutSeconds: null, budgetUsd: null, enforced: false },
    usage: { tokensIn: 0, tokensOut: 0, costUsd: null, iterations: 0, elapsedSeconds: 0 },
    steps: [
      { key: 'revisor', agentId: 'a2', agentName: 'Revisor', status: 'pending', model: null, dependencies: ['investigador'], requiresApproval: true, error: null, startedAt: null, finishedAt: null, tools: [], tokensIn: 0, tokensOut: 0 },
      { key: 'investigador', agentId: 'a1', agentName: 'Investigador', status: 'pending', model: null, dependencies: [], requiresApproval: false, error: null, startedAt: null, finishedAt: null, tools: [], tokensIn: 0, tokensOut: 0 },
    ],
    artifacts: [], finalAnswer: null, error: null, attempt: 1, origin: 'real',
  };
}
const sampleEvents = () => SAMPLES.events['run-1'].map((e) => ({ seq: e.seq, kind: e.kind, stepKey: e.data.step_key, payload: e.data.payload, at: e.data.at }));

test('applyEvent rebuilds statuses, tools and tokens from the real event sample', () => {
  const state = sampleEvents().reduce(applyEvent, sampleExecution());
  const investigador = state.steps.find((s) => s.key === 'investigador');
  assert.equal(state.status, 'waiting_approval');
  assert.equal(investigador.status, 'completed');
  assert.deepEqual(investigador.tools, [{ tool: 'ls', status: 'ok', durationSeconds: 0.4 }]);
  assert.equal(state.usage.tokensIn, 4714);
  assert.equal(state.usage.iterations, 2, 'one tool call plus one model call');
  assert.equal(state.steps.find((s) => s.key === 'revisor').status, 'waiting_approval');
});

test('replaying a backlog over a snapshot never double counts', () => {
  const snapshot = sampleEvents().reduce(applyEvent, sampleExecution());
  const replayed = sampleEvents().reduce(applyEvent, resetCounters(snapshot));
  assert.equal(replayed.usage.tokensIn, 4714, 'the absolute value from the single model_metrics event');
  assert.equal(replayed.steps.find((s) => s.key === 'investigador').tools.length, 1);
  // The guard matters: replaying without resetting doubles every counter.
  assert.equal(sampleEvents().reduce(applyEvent, snapshot).usage.tokensIn, 9428);
  assert.equal(replayed.usage.measured, true);
  assert.equal(resetCounters(snapshot).usage.measured, false);
});

test('applyEvent does not mutate its input', () => {
  const before = sampleExecution();
  const frozen = JSON.stringify(before);
  applyEvent(before, sampleEvents()[2]);
  assert.equal(JSON.stringify(before), frozen);
});

test('buildTrace produces timed spans for steps, tools, model calls and approvals', () => {
  const events = sampleEvents();
  const trace = buildTrace(events.reduce(applyEvent, sampleExecution()), events);
  const kinds = trace.spans.map((s) => s.kind);
  assert.deepEqual([...new Set(kinds)].sort(), ['aprobacion', 'herramienta', 'modelo', 'paso']);
  const step = trace.spans.find((s) => s.kind === 'paso');
  assert.equal(step.durationMs, 24000);
  assert.equal(trace.spans.find((s) => s.kind === 'herramienta').durationMs, 400);
  assert.equal(trace.tokensIn + trace.tokensOut, 4714 + 681);
});

test('topoOrder puts dependencies first; isFresh ignores old events', () => {
  assert.deepEqual(topoOrder(sampleExecution().steps), ['investigador', 'revisor']);
  const now = Date.parse('2026-09-24T15:00:10Z');
  assert.equal(isFresh({ seq: 1, kind: 'x', stepKey: null, payload: {}, at: '2026-09-24T15:00:05Z' }, now), true);
  assert.equal(isFresh({ seq: 1, kind: 'x', stepKey: null, payload: {}, at: '2026-09-24T14:00:00Z' }, now), false);
});

// --- simulator -------------------------------------------------------------

function simExecution(workflowId, limits = {}) {
  const wf = WORKFLOWS.find((w) => w.id === workflowId);
  const agents = new Map(AGENTS.map((a) => [a.id, a]));
  return {
    agents,
    execution: {
      id: 'ex-sim', workflowId, workflowName: wf.name, projectId: wf.projectId, objective: 'Prueba', priority: 'media', responsibleAgentId: null,
      status: 'pending', createdAt: '2026-09-24T12:00:00Z', startedAt: null, finishedAt: null,
      limits: { maxIterations: 100, timeoutSeconds: 100000, budgetUsd: 100, enforced: true, ...limits },
      usage: { tokensIn: 0, tokensOut: 0, costUsd: 0, iterations: 0, elapsedSeconds: 0 },
      steps: wf.steps.map((s) => ({ key: s.key, agentId: s.agentId, agentName: agents.get(s.agentId).name, status: 'pending', model: agents.get(s.agentId).model,
                                    dependencies: [...s.dependsOn], requiresApproval: s.requiresApproval, error: null, startedAt: null, finishedAt: null, tools: [], tokensIn: 0, tokensOut: 0 })),
      artifacts: [], finalAnswer: null, error: null, attempt: 1, origin: 'demo',
    },
  };
}

function drain(sim, approveAll = true) {
  const events = [];
  for (let i = 0; i < 1000; i += 1) {
    const tick = sim.next();
    if (tick) { events.push(tick.event); continue; }
    const waiting = sim.waitingFor();
    if (waiting && approveAll) { sim.approve(waiting); continue; }
    break;
  }
  return events;
}

test('the simulator is deterministic for a given seed', () => {
  const a = simExecution('wf-operacion');
  const b = simExecution('wf-operacion');
  const first = drain(createSimulation({ ...a, seed: 42, startSeq: 0 })).map((e) => `${e.kind}:${e.stepKey}:${JSON.stringify(e.payload)}`);
  const second = drain(createSimulation({ ...b, seed: 42, startSeq: 0 })).map((e) => `${e.kind}:${e.stepKey}:${JSON.stringify(e.payload)}`);
  assert.deepEqual(first, second);
  assert.equal(first.at(-1).split(':')[0], 'run_completed');
});

test('the simulator honours dependencies, parallelism and approval gates', () => {
  const { execution, agents } = simExecution('wf-operacion');
  const events = drain(createSimulation({ execution, agents, seed: 3, startSeq: 0 }));
  const started = events.filter((e) => e.kind === 'step_started').map((e) => e.stepKey);
  assert.equal(started[0], 'planificacion');
  assert.ok(started.indexOf('finanzas') > Math.max(started.indexOf('produccion'), started.indexOf('mantenimiento'), started.indexOf('logistica')));
  const approvalAt = events.findIndex((e) => e.kind === 'step_approval_requested' && e.stepKey === 'seguridad');
  assert.ok(approvalAt > 0 && events.findIndex((e) => e.kind === 'step_started' && e.stepKey === 'seguridad') > approvalAt);
  let running = 0; let peak = 0;
  for (const e of events) { if (e.kind === 'step_started') running += 1; if (e.kind === 'step_completed') running -= 1; peak = Math.max(peak, running); }
  assert.equal(peak, 2, 'at most two steps run at once, like the backend');
  const state = events.reduce(applyEvent, execution);
  assert.equal(state.status, 'completed');
  assert.ok(state.finalAnswer?.startsWith('Artefacto de demostración — Sostenibilidad'));
});

test('the simulator stops at the iteration, budget and time limits', () => {
  for (const [limits, pattern] of [[{ maxIterations: 3 }, /iteraciones/], [{ budgetUsd: 0.001 }, /Presupuesto agotado/], [{ timeoutSeconds: 5 }, /Tiempo límite/]]) {
    const { execution, agents } = simExecution('wf-fpa', limits);
    const events = drain(createSimulation({ execution, agents, seed: 9, startSeq: 0 }));
    const last = events.at(-1);
    assert.equal(last.kind, 'run_error', JSON.stringify(limits));
    assert.match(String(last.payload.error), pattern);
    assert.equal(events.filter((e) => e.kind === 'run_error').length, 1);
    const state = events.reduce(applyEvent, execution);
    assert.equal(state.status, 'error');
    assert.ok(state.steps.some((s) => s.status === 'error'));
  }
});

test('the simulator stays waiting until approval and cancel emits interruption events', () => {
  const { execution, agents } = simExecution('wf-fpa');
  const sim = createSimulation({ execution, agents, seed: 1, startSeq: 0 });
  drain(sim, false);
  assert.equal(sim.waitingFor(), 'revisor');
  assert.equal(sim.next(), null);
  const cancel = sim.cancel();
  assert.deepEqual(cancel.map((e) => e.kind), ['run_stop_requested', 'run_interrupted']);
  assert.equal(sim.isFinished(), true);
});

// --- demo source -----------------------------------------------------------

test('demo source seeds history with completed, failed and waiting runs', async () => {
  const demo = createDemoSource({ speed: 0, now: () => Date.parse('2026-09-24T18:00:00Z') });
  const executions = await demo.listExecutions();
  const statuses = executions.map((e) => e.status).sort();
  assert.deepEqual(statuses, ['completed', 'completed', 'completed', 'error', 'error', 'waiting_approval']);
  assert.ok(executions.every((e) => e.origin === 'demo'));
  const approvals = await demo.listApprovals();
  assert.ok(approvals.some((a) => a.kind === 'paso' && a.status === 'pendiente'));
});

test('demo approval flow: validation, approve continues the run, history is kept', async () => {
  const demo = createDemoSource({ speed: 0 });
  const pending = (await demo.listApprovals()).find((a) => a.kind === 'paso' && a.status === 'pendiente');
  await assert.rejects(demo.decideApproval(pending.id, 'aprobar', '', 'tester'), (e) => e.kind === 'validation', 'seguridad is high risk and needs a reason');
  await assert.rejects(demo.decideApproval(pending.id, 'rechazar', 'corto', 'tester'), (e) => e.kind === 'validation');
  const decided = await demo.decideApproval(pending.id, 'aprobar', 'Evidencia revisada con el registro.', 'tester');
  assert.equal(decided.status, 'aprobada');
  const execution = await demo.getExecution(pending.executionId);
  assert.equal(execution.status, 'completed');
  await assert.rejects(demo.decideApproval(pending.id, 'aprobar', 'otra vez aprobando', 'tester'), (e) => e.kind === 'conflict');
});

test('demo execution lifecycle: create, fail on budget, retry with a larger budget', async () => {
  const demo = createDemoSource({ speed: 0, history: false });
  const created = await demo.createExecution({ workflowId: 'wf-operacion', objective: 'Revisión de prueba unitaria', priority: 'alta', responsibleAgentId: null,
                                               maxIterations: 100, timeoutSeconds: 100000, budgetUsd: 0.001 });
  let execution = await demo.getExecution(created.id);
  assert.equal(execution.status, 'error');
  assert.match(execution.error, /Presupuesto/);
  await demo.retryExecution(created.id, { budgetUsd: 50 });
  execution = await demo.getExecution(created.id);
  assert.equal(execution.attempt, 2);
  assert.equal(execution.status, 'waiting_approval');
  const request = (await demo.listApprovals()).find((a) => a.executionId === created.id);
  await demo.decideApproval(request.id, 'aprobar', 'Hallazgo verificado en el registro.', 'tester');
  assert.equal((await demo.getExecution(created.id)).status, 'completed');
});

test('demo refuses to start a workflow with paused agents and to cancel a finished run', async () => {
  const demo = createDemoSource({ speed: 0, history: false });
  await assert.rejects(demo.createExecution({ workflowId: 'wf-fpa', objective: 'Documentador pausado', priority: 'media', responsibleAgentId: null, maxIterations: 50, timeoutSeconds: 5000, budgetUsd: 5 }),
    (e) => e.kind === 'validation' && /Documentador/.test(e.message));
  await demo.setAgentStatus('ag-documentador', 'active');
  const run = await demo.createExecution({ workflowId: 'wf-fpa', objective: 'Ahora sí con todos', priority: 'media', responsibleAgentId: null, maxIterations: 50, timeoutSeconds: 5000, budgetUsd: 5 });
  const cancelled = await demo.cancelExecution(run.id);
  assert.equal(cancelled.status, 'interrupted');
  await assert.rejects(demo.cancelExecution(run.id), (e) => e.kind === 'conflict');
});

test('demo agents: validation, duplicate names, versioned instructions, derived permissions', async () => {
  const demo = createDemoSource({ speed: 0, history: false });
  const input = { name: 'Auditor', role: 'Auditoría', projectId: 'demo-fpa', model: 'modelo-demo-rapido', allowedTools: ['read_file'], workspace: null, instructions: 'Revisa evidencia sintética.', taskId: null };
  await assert.rejects(demo.saveAgent({ ...input, allowedTools: ['no_existe'] }), (e) => e.kind === 'validation');
  await assert.rejects(demo.saveAgent({ ...input, name: 'Coordinador' }), (e) => e.kind === 'conflict');
  const created = await demo.saveAgent(input);
  assert.equal(created.status, 'paused');
  assert.equal(created.permissionLevel, 'lectura');
  const edited = await demo.saveAgent({ ...input, instructions: 'Instrucciones nuevas y más precisas.', allowedTools: ['read_file', 'write_file'] }, created.id);
  assert.equal(edited.instructionsVersion, 2);
  assert.equal(edited.permissionLevel, 'escritura');
});

test('demo failure injection fails every other read so a retry recovers', async () => {
  const demo = createDemoSource({ speed: 0, history: false, failures: () => true });
  await assert.rejects(demo.listAgents(), (e) => e.kind === 'simulated');
  assert.ok((await demo.listAgents()).length > 0);
});

test('demo memory: canon files cannot be archived; episodic records toggle', async () => {
  const demo = createDemoSource({ speed: 0, history: false });
  await assert.rejects(demo.archiveMemory('mem-canon-05'), (e) => e.kind === 'not_supported');
  assert.equal((await demo.archiveMemory('mem-ep-1')).archived, true);
  assert.equal((await demo.archiveMemory('mem-ep-1')).archived, false);
});

// --- live source -----------------------------------------------------------

/** Stateful fake API over a copy of the shared samples; records every call. */
function fakeApi() {
  const calls = [];
  const data = structuredClone(SAMPLES);
  const req = async (path, options = {}) => {
    const method = options.method || 'GET';
    calls.push(`${method} ${path}`);
    const route = path.split('?')[0];
    if (route === '/api/cmh/agents') return data.agents;
    if (route === '/api/cmh/projects') return data.projects;
    if (route === '/api/cmh/workflows') return data.workflows;
    if (route === '/api/cmh/runs') return data.runs;
    const detail = route.match(/^\/api\/cmh\/runs\/([^/]+)$/);
    if (detail) return data.run_detail[decodeURIComponent(detail[1])];
    const action = route.match(/^\/api\/cmh\/runs\/([^/]+)\/(stop|steps\/([^/]+)\/(?:approve|reject))$/);
    if (action && method === 'POST') {
      // Mirrors the backend: approve needs a waiting step; stop needs an active run.
      const run = data.run_detail[action[1]];
      const summary = data.runs.runs.find((r) => r.id === action[1]);
      if (action[2] === 'stop') {
        if (!['running', 'pending', 'waiting_approval'].includes(run.status)) throw new HttpError('conflict', 'Run is not active', 409);
        run.status = summary.status = 'interrupted';
        for (const s of run.steps) if (s.status === 'waiting_approval') s.status = 'pending';
      } else {
        const step = run.steps.find((s) => s.key === action[3]);
        if (run.status !== 'waiting_approval' || step?.status !== 'waiting_approval') throw new HttpError('conflict', 'No approval pending for this step', 409);
        const rejecting = action[2].endsWith('/reject');
        const justification = String((options.json && options.json.justification) || '').trim();
        if (rejecting && !justification) throw new HttpError('validation', 'A rejection needs a justification', 400);
        step.decision = { outcome: rejecting ? 'rejected' : 'approved', justification, by: 'tester', at: new Date().toISOString() };
        step.status = rejecting ? 'rejected' : 'pending';
        run.status = summary.status = rejecting ? 'rejected' : 'running';
      }
      return { id: action[1], status: 'ok' };
    }
    if (route === '/api/cmh/memory-proposals') return data.memory_proposals;
    const proposal = route.match(/^\/api\/cmh\/memory-proposals\/([^/]+)\/(approve|reject)$/);
    if (proposal && method === 'POST') {
      const row = data.memory_proposals.proposals.find((p) => p.id === proposal[1]);
      if (row.status !== 'pending') throw new HttpError('conflict', 'Proposal already decided', 409);
      row.status = proposal[2] === 'approve' ? 'approved' : 'rejected';
      return { id: row.id, status: row.status };
    }
    if (route.startsWith('/api/cmh/memory-proposals/') && method === 'GET') return SAMPLES.memory_proposal_detail;
    if (route === '/api/cmh/memories') return SAMPLES.memories;
    if (route === '/api/cmh/memories/content') return SAMPLES.memory_content;
    if (route === '/api/model-endpoints') return SAMPLES.model_endpoints;
    if (route === '/api/mcp/servers') return SAMPLES.mcp_servers;
    if (route === '/api/mcp/tools') return SAMPLES.mcp_tools;
    if (route === '/api/session') return { id: 'sess-1', name: 'x', model: 'm', rag: false, archived: false };
    if (route === '/api/chat') return { response: 'Respuesta del modelo' };
    if (method === 'POST') return { id: 'run-1', status: 'ok' };
    throw new HttpError('not_found', `unexpected ${path}`, 404);
  };
  return { calls, req };
}

test('live source maps real payloads to the shared contracts', async () => {
  const { req } = fakeApi();
  const live = createLiveSource({ demo: createDemoSource({ speed: 0, history: false }), request: req, EventSourceImpl: undefined });
  const agents = await live.listAgents();
  assert.equal(agents[0].permissionLevel, 'lectura');
  assert.equal(agents[0].origin, 'real');
  const execution = await live.getExecution('run-0');
  assert.deepEqual(execution.steps.map((s) => s.key), ['investigador', 'revisor']);
  assert.equal(execution.steps[1].requiresApproval, true, 'taken from the workflow definition');
  assert.equal(execution.steps[0].agentName, 'Investigador');
  assert.equal(execution.finalAnswer, 'APROBADO (sintético).');
  assert.equal(execution.limits.enforced, false);
  const list = await live.listExecutions();
  assert.equal(list[0].workflowName, 'CMH: investigación a documentación');
});

test('live source never lets secret values reach the UI layer', async () => {
  const server = mapMcpServer(SAMPLES.mcp_servers[0]);
  assert.deepEqual(server.envKeys, ['API_TOKEN', 'BASE_URL']);
  assert.doesNotMatch(JSON.stringify(server), /valor-secreto/);
  const provider = mapProvider({ ...SAMPLES.model_endpoints[0], api_key: 'sk-live-should-not-pass-0123456789' });
  assert.doesNotMatch(JSON.stringify(provider), /sk-live/);
  const { req } = fakeApi();
  const live = createLiveSource({ demo: createDemoSource({ speed: 0, history: false }), request: req });
  const security = await live.getSecurity();
  assert.doesNotMatch(JSON.stringify(security), /valor-secreto/);
  assert.ok(security.secrets.some((s) => s.name === 'API_TOKEN' && s.configured));
});

test('live approvals route decisions to the right endpoints and keep the justification locally', async () => {
  const { req, calls } = fakeApi();
  const live = createLiveSource({ demo: createDemoSource({ speed: 0, history: false }), request: req });
  const approvals = await live.listApprovals();
  const step = approvals.find((a) => a.kind === 'paso');
  const memoryRequest = approvals.find((a) => a.kind === 'memoria' && a.status === 'pendiente');
  assert.equal(step.id, 'apr-run-1-revisor');
  assert.match(memoryRequest.diff, /Nuevo pendiente/);
  assert.equal(memoryRequest.risk, 'alto');
  await assert.rejects(live.decideApproval(step.id, 'rechazar', '', 'tester'), (e) => e.kind === 'validation');
  await live.decideApproval(step.id, 'aprobar', '', 'tester');
  assert.ok(calls.includes('POST /api/cmh/runs/run-1/steps/revisor/approve'));
  // Decided once: the same request is gone and cannot be decided again.
  await assert.rejects(live.decideApproval(step.id, 'rechazar', 'Intento de segunda decisión.', 'tester'), (e) => e.kind === 'not_found');
  await live.decideApproval(memoryRequest.id, 'rechazar', 'La fila no tiene fuente.', 'tester');
  assert.ok(calls.includes('POST /api/cmh/memory-proposals/prop-1/reject'));
  await assert.rejects(live.decideApproval(memoryRequest.id, 'aprobar', 'Segunda decisión.', 'tester'), (e) => e.kind === 'not_found' || e.kind === 'conflict');
});

test('live step rejection calls the native endpoint, is terminal and keeps the reason', async () => {
  const { req, calls } = fakeApi();
  const live = createLiveSource({ demo: createDemoSource({ speed: 0, history: false }), request: req });
  await live.decideApproval('apr-run-1-revisor', 'rechazar', 'No hay evidencia suficiente.', 'tester');
  assert.ok(calls.includes('POST /api/cmh/runs/run-1/steps/revisor/reject'), 'native reject endpoint');
  assert.ok(!calls.includes('POST /api/cmh/runs/run-1/stop'), 'no longer falls back to stop');
  const history = (await live.listApprovals()).filter((a) => a.kind === 'paso' && a.status !== 'pendiente');
  assert.ok(history.some((a) => a.executionId === 'run-1' && a.status === 'rechazada' && a.justification === 'No hay evidencia suficiente.'));
  // Terminal: the run cannot be decided again.
  await assert.rejects(live.decideApproval('apr-run-1-revisor', 'aprobar', 'Segunda decisión.', 'tester'),
                       (e) => e.kind === 'not_found' || e.kind === 'conflict');
});

test('a reloaded rejected run keeps its status instead of degrading to error', async () => {
  // The SSE path sets status directly, so only a RELOAD goes through the
  // enum in live.js. Without 'rejected' in it, a user who refreshes the page
  // over a rejected run is told the run failed.
  const { req } = fakeApi();
  const live = createLiveSource({ demo: createDemoSource({ speed: 0, history: false }), request: req });
  await live.decideApproval('apr-run-1-revisor', 'rechazar', 'No hay evidencia suficiente.', 'tester');
  const reloaded = await live.getExecution('run-1');
  assert.equal(reloaded.status, 'rejected');
  assert.equal(reloaded.steps.find((s) => s.key === 'revisor').status, 'rejected');
});

test('run_rejected is a known, terminal run event', () => {
  // Left out of TERMINAL_RUN_EVENTS, a rejected run's stream stays open until
  // the idle timeout instead of closing as soon as the verdict arrives.
  assert.ok(RUN_EVENT_KINDS.includes('run_rejected'));
  assert.ok(RUN_EVENT_KINDS.includes('step_rejected'));
  assert.ok(TERMINAL_RUN_EVENTS.includes('run_rejected'));
});

test('applyEvent records a rejection on the step and the run', () => {
  // Start from the real snapshot the other reducer tests use, replayed up to
  // the approval request, so the rejection lands on a realistic state.
  const base = sampleEvents().reduce(applyEvent, sampleExecution());
  assert.equal(base.status, 'waiting_approval');
  const at = '2026-09-25T12:00:00.000Z';
  const afterStep = applyEvent(base, { kind: 'step_rejected', stepKey: 'revisor', at, payload: {} });
  const afterRun = applyEvent(afterStep, { kind: 'run_rejected', stepKey: null, at, payload: {} });
  assert.equal(afterStep.steps[0].status, 'rejected');
  assert.equal(afterRun.status, 'rejected');
  assert.equal(afterRun.finishedAt, at);
});

test('a rejection without a justification never reaches the backend', async () => {
  const { req, calls } = fakeApi();
  const live = createLiveSource({ demo: createDemoSource({ speed: 0, history: false }), request: req });
  await assert.rejects(live.decideApproval('apr-run-1-revisor', 'rechazar', '  ', 'tester'), (e) => e.kind === 'validation');
  assert.ok(!calls.some((c) => c.includes('/reject')), 'no call was made');
});

test('live approvals survive a failing memory-proposals endpoint', async () => {
  const { req } = fakeApi();
  const failing = async (path, options) => { if (path.startsWith('/api/cmh/memory-proposals')) throw new HttpError('server', 'boom', 500); return req(path, options); };
  const live = createLiveSource({ demo: createDemoSource({ speed: 0, history: false }), request: failing });
  assert.ok((await live.listApprovals()).some((a) => a.id === 'apr-run-1-revisor'));
});

/** EventSource stand-in that delivers a scripted backlog, honouring close(). */
function scriptedEventSource(backlogByRun) {
  return class FakeEventSource {
    constructor(url) {
      this.listeners = new Map();
      this.readyState = 1;
      const runId = decodeURIComponent(url.split('/')[4]);
      const backlog = backlogByRun[runId] || [];
      backlog.forEach((event, index) => setTimeout(() => {
        if (this.readyState === 2) return;
        for (const cb of this.listeners.get(event.kind) || []) cb({ data: JSON.stringify(event.data), lastEventId: String(event.seq) });
      }, 5 * (index + 1)));
    }
    addEventListener(kind, cb) { if (!this.listeners.has(kind)) this.listeners.set(kind, []); this.listeners.get(kind).push(cb); }
    close() { this.readyState = 2; }
  };
}

test('live traces keep events after a resumed error (replay does not stop at the first terminal event)', async () => {
  const { req } = fakeApi();
  const at = (s) => `2026-09-24T15:00:${String(s).padStart(2, '0')}Z`;
  const ev = (seq, kind, step_key, s, payload = {}) => ({ seq, kind, data: { step_key, payload, at: at(s) } });
  const backlog = { 'run-0': [ev(1, 'run_started', null, 0), ev(2, 'step_started', 'investigador', 1), ev(3, 'step_error', 'investigador', 4, { error: 'x' }),
    ev(4, 'run_error', null, 4), ev(5, 'run_resume_requested', null, 6), ev(6, 'run_started', null, 6), ev(7, 'step_started', 'investigador', 7),
    ev(8, 'step_completed', 'investigador', 9, { artifact_id: 'art-0a' }), ev(9, 'step_started', 'revisor', 9), ev(10, 'step_completed', 'revisor', 10, { artifact_id: 'art-0b' }), ev(11, 'run_completed', null, 10)] };
  const live = createLiveSource({ demo: createDemoSource({ speed: 0, history: false }), request: req, EventSourceImpl: scriptedEventSource(backlog), traceIdleMs: 150 });
  const trace = await live.getTrace('run-0');
  const steps = trace.spans.filter((s) => s.kind === 'paso');
  assert.equal(steps.length, 3, 'failed attempt + retried step + reviewer');
  assert.equal(trace.durationMs, 10000);
});

test('a run feed fetches the artifact a live step_completed only references (final answer is right)', async () => {
  const { openRunFeed } = await import('../../../static/cmh-os/js/services/run-feed.js');
  const snapshot = { ...sampleExecution(), status: 'waiting_approval',
    artifacts: [{ id: 'art-1', stepKey: 'investigador', model: 'm', content: 'Nota del investigador' }] };
  let listener = null;
  const source = {
    openRunStream: (_id, handlers) => { listener = handlers; return { close() {} }; },
    getExecution: async () => ({ ...snapshot, artifacts: [...snapshot.artifacts, { id: 'art-2', stepKey: 'revisor', model: 'm', content: 'Veredicto del revisor' }] }),
  };
  let latest = null;
  const feed = openRunFeed(source, snapshot, { onChange: (execution) => { latest = execution; } });
  listener.onEvent({ seq: 1, kind: 'step_completed', stepKey: 'revisor', payload: { artifact_id: 'art-2' }, at: new Date().toISOString() });
  listener.onEvent({ seq: 2, kind: 'run_completed', stepKey: null, payload: {}, at: new Date().toISOString() });
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(latest.status, 'completed');
  assert.equal(latest.finalAnswer, 'Veredicto del revisor');
  feed.dispose();
  listener.onEvent({ seq: 3, kind: 'run_error', stepKey: null, payload: {}, at: new Date().toISOString() });
  assert.equal(feed.state().status, 'completed', 'a disposed feed ignores late events');
});

test('demo: a rejected step asks for approval again after a retry', async () => {
  const demo = createDemoSource({ speed: 0, history: false });
  const run = await demo.createExecution({ workflowId: 'wf-operacion', objective: 'Rechazo y reintento', priority: 'media', responsibleAgentId: null, maxIterations: 100, timeoutSeconds: 100000, budgetUsd: 50 });
  const id = `apr-${run.id}-seguridad`;
  await demo.decideApproval(id, 'rechazar', 'Falta el registro de incidentes.', 'tester');
  assert.equal((await demo.getExecution(run.id)).status, 'interrupted');
  await demo.retryExecution(run.id);
  assert.equal((await demo.getExecution(run.id)).status, 'waiting_approval');
  const again = (await demo.listApprovals()).find((a) => a.id === id);
  assert.equal(again.status, 'pendiente');
  await demo.decideApproval(id, 'aprobar', 'Registro de incidentes ya revisado.', 'tester');
  assert.equal((await demo.getExecution(run.id)).status, 'completed');
});

test('demo: events delivered live are fresh, so the graph animates (also after approving a seeded run)', async () => {
  const demo = createDemoSource({ speed: 0.01, now: () => Date.now() });
  const waiting = (await demo.listApprovals()).find((a) => a.kind === 'paso' && a.status === 'pendiente');
  const fresh = [];
  const stream = demo.openRunStream(waiting.executionId, { onEvent: (e) => fresh.push(isFresh(e)) });
  const replayed = fresh.length;
  await demo.decideApproval(waiting.id, 'aprobar', 'Evidencia revisada con el registro.', 'tester');
  await new Promise((r) => setTimeout(r, 400));
  stream.close();
  const live = fresh.slice(replayed);
  assert.ok(live.length > 5, `live events after approval: ${live.length}`);
  assert.ok(live.every(Boolean), 'every live event is fresh');
  assert.ok(fresh.slice(0, replayed).every((f) => !f), 'the seeded backlog is not');
});

test('URL redaction strips credentials, query and fragment', async () => {
  const { redactUrl, redactText } = await import('../../../static/cmh-os/js/services/derive.js');
  assert.equal(redactUrl('https://user:secret@api.example.com/v1?key=abc#x'), 'https://api.example.com/v1');
  assert.equal(redactText('fallo al llamar http://u:p@h:1/x?token=1 hoy'), 'fallo al llamar http://h:1/x hoy');
  const provider = mapProvider({ ...SAMPLES.model_endpoints[0], base_url: 'https://me:tok@api.x/v1?key=zzz' });
  assert.equal(provider.baseUrl, 'https://api.x/v1');
  assert.equal(mapMcpServer({ ...SAMPLES.mcp_servers[0], error: 'no conecta a https://a:b@c.d/e?k=1' }).error, 'no conecta a https://c.d/e');
});

test('backend English error details reach the UI in Spanish', async () => {
  const fetchImpl = async () => response(409, { detail: 'No approval pending for this step' });
  await assert.rejects(request('/x', { method: 'POST', fetchImpl, sleep: noSleep }), (e) => e.message === 'Este paso ya no espera aprobación.');
  const pattern = async () => response(400, { detail: 'Step revisor must use a different agent than constructor' });
  await assert.rejects(request('/x', { method: 'POST', fetchImpl: pattern, sleep: noSleep }), (e) => /revisor debe usar un agente distinto de constructor/.test(e.message));
});

test('live chat model creates one session per endpoint and model', async () => {
  const { req, calls } = fakeApi();
  const live = createLiveSource({ demo: createDemoSource({ speed: 0, history: false }), request: req });
  assert.equal(await live.askModel('hola', 'ep-1', 'claude'), 'Respuesta del modelo');
  await live.askModel('otra', 'ep-1', 'claude');
  assert.equal(calls.filter((c) => c === 'POST /api/session').length, 1);
  await assert.rejects(live.archiveMemory('file:x'), (e) => e.kind === 'not_supported');
});

test('live tools merge read tools, agent tools and MCP tools', async () => {
  const { req } = fakeApi();
  const live = createLiveSource({ demo: createDemoSource({ speed: 0, history: false }), request: req });
  const tools = await live.listTools();
  assert.ok(tools.some((t) => t.id === 'read_file' && t.readOnly && t.usedBy.includes('Revisor')));
  assert.ok(tools.some((t) => t.id === 'mcp__srv-1__consultar' && t.category === 'mcp' && t.requiresApproval));
});

// --- chat ------------------------------------------------------------------

test('parseCommand recognizes Spanish commands with or without accents', () => {
  assert.deepEqual(parseCommand('Estado'), { intent: 'status', arg: '' });
  assert.equal(parseCommand('¿qué puedes hacer?').intent, 'help');
  assert.deepEqual(parseCommand('ejecutar el flujo revisión'), { intent: 'start', arg: 'revision' });
  assert.deepEqual(parseCommand('detén ex-003'), { intent: 'stop', arg: 'ex-003' });
  assert.deepEqual(parseCommand('buscar Presupuesto'), { intent: 'search', arg: 'presupuesto' });
  assert.equal(parseCommand('ir a memoria').intent, 'goto');
  assert.equal(parseCommand('cuánto costó ayer').intent, 'unknown');
});

test('chat answers from data and never executes sensitive actions itself', async () => {
  const source = createDemoSource({ speed: 0, now: () => Date.parse('2026-09-24T18:00:00Z') });
  const ctx = { source, allowModel: false, model: null };
  const status = await respond('estado', ctx);
  assert.equal(status.answeredBy, 'regla');
  assert.ok(status.lines.some((l) => /aprobaciones pendientes/.test(l)));
  const start = await respond('ejecutar revisión operacional', ctx);
  assert.equal(start.actions[0].kind, 'navigate');
  assert.equal(start.actions[0].href, '#/ejecuciones?nuevo=wf-operacion');
  const stop = await respond('detener', ctx);
  assert.ok(stop.actions.every((a) => a.kind === 'confirm-stop'), 'stopping always goes through a confirmation');
  const before = (await source.listExecutions()).filter((e) => e.status === 'waiting_approval').length;
  assert.equal(before, 1, 'asking to stop did not stop anything');
  const search = await respond('buscar presupuesto', ctx);
  assert.ok(search.links.length >= 1);
  const unknown = await respond('cuánto costó ayer', ctx);
  assert.match(unknown.lines[0], /modo demo/);
});

test('free text reaches the model only when enabled and supported', async () => {
  let asked = 0;
  const source = { ...createDemoSource({ speed: 0, history: false }), capabilities: { chatModel: true }, askModel: async () => { asked += 1; return 'ok modelo'; } };
  const off = await respond('una pregunta libre', { source, allowModel: false, model: { endpointId: 'e', model: 'm' } });
  assert.equal(off.answeredBy, 'regla');
  const on = await respond('una pregunta libre', { source, allowModel: true, model: { endpointId: 'e', model: 'm' } });
  assert.equal(on.answeredBy, 'modelo');
  assert.equal(on.text, 'ok modelo');
  assert.equal(asked, 1);
});
