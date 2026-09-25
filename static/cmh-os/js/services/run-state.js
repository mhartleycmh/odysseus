// Pure reducer from run events to execution state, shared by the live stream,
// the demo simulator and the orchestration view. Also builds traces.

/** @typedef {import('../types.js').Execution} Execution */
/** @typedef {import('../types.js').ExecutionStep} ExecutionStep */
/** @typedef {import('../types.js').RunEvent} RunEvent */
/** @typedef {import('../types.js').Trace} Trace */
/** @typedef {import('../types.js').Span} Span */

export const RUN_EVENT_KINDS = Object.freeze([
  'run_created', 'run_started', 'step_started', 'step_completed', 'step_error', 'step_interrupted',
  'step_approval_requested', 'step_approved', 'step_rejected', 'run_completed', 'run_error', 'run_interrupted', 'run_rejected',
  'run_stop_requested', 'run_resume_requested', 'step_input_truncated',
  'tool_started', 'tool_finished', 'model_metrics',
]);
export const TERMINAL_RUN_EVENTS = Object.freeze(['run_completed', 'run_error', 'run_interrupted', 'run_rejected']);

/**
 * Only events that just happened animate; a replayed backlog updates state silently.
 * @param {RunEvent} event
 * @param {number} [now]
 */
export function isFresh(event, now = Date.now()) {
  const at = Date.parse(event.at);
  return Number.isFinite(at) && now - at < 8000;
}

/** @param {unknown} value */
const num =(value) => (typeof value === 'number' && Number.isFinite(value) ? value : 0);

/**
 * Deep-enough copy so reducers never mutate the caller's object.
 * @param {Execution} execution
 * @returns {Execution}
 */
export function cloneExecution(execution) {
  return {
    ...execution,
    limits: { ...execution.limits },
    usage: { ...execution.usage },
    steps: execution.steps.map((step) => ({ ...step, dependencies: [...step.dependencies], tools: step.tools.map((t) => ({ ...t })) })),
    artifacts: execution.artifacts.map((a) => ({ ...a })),
  };
}

/**
 * Zero the counters an event replay rebuilds (tools, tokens, cost, iterations)
 * while keeping statuses and artifacts, so replaying a full backlog on top of
 * a fetched snapshot never double counts.
 * @param {Execution} execution
 * @returns {Execution}
 */
export function resetCounters(execution) {
  const next = cloneExecution(execution);
  for (const step of next.steps) {
    step.tools = [];
    step.tokensIn = 0;
    step.tokensOut = 0;
  }
  next.usage = { tokensIn: 0, tokensOut: 0, costUsd: execution.usage.costUsd === null ? null : 0, iterations: 0, elapsedSeconds: 0, measured: false };
  return next;
}

/**
 * @param {Execution} execution
 * @param {RunEvent} event
 * @returns {Execution}
 */
export function applyEvent(execution, event) {
  const next = cloneExecution(execution);
  const step = event.stepKey ? next.steps.find((s) => s.key === event.stepKey) : undefined;
  const payload = event.payload || {};
  // Events are the measurement: once one is seen, counters are real values.
  next.usage.measured = true;
  switch (event.kind) {
    case 'run_created':
      next.status = 'pending';
      break;
    case 'run_started':
      next.status = 'running';
      next.startedAt = next.startedAt || event.at;
      next.error = null;
      break;
    case 'step_started':
      if (step) {
        step.status = 'running';
        step.startedAt = event.at;
        step.finishedAt = null;
        step.error = null;
        if (typeof payload.model === 'string') step.model = payload.model;
      }
      break;
    case 'tool_started':
      if (step) step.tools.push({ tool: String(payload.tool || 'desconocida'), status: 'running', durationSeconds: null });
      next.usage.iterations += 1;
      break;
    case 'tool_finished':
      if (step) {
        const call = step.tools.find((t) => t.tool === String(payload.tool || 'desconocida') && t.status === 'running');
        if (call) {
          call.status = payload.error === true ? 'error' : 'ok';
          call.durationSeconds = typeof payload.duration_seconds === 'number' ? payload.duration_seconds : null;
        }
      }
      break;
    case 'model_metrics': {
      const metrics = /** @type {Record<string, unknown>} */ (payload.metrics && typeof payload.metrics === 'object' ? payload.metrics : {});
      const input = num(metrics.input_tokens);
      const output = num(metrics.output_tokens);
      if (step) {
        step.tokensIn += input;
        step.tokensOut += output;
      }
      next.usage.tokensIn += input;
      next.usage.tokensOut += output;
      next.usage.iterations += 1;
      if (typeof payload.cost_usd === 'number') next.usage.costUsd = (next.usage.costUsd || 0) + payload.cost_usd;
      break;
    }
    case 'step_completed':
      if (step) {
        step.status = 'completed';
        step.finishedAt = event.at;
      }
      if (typeof payload.content === 'string' && event.stepKey) {
        const id = typeof payload.artifact_id === 'string' ? payload.artifact_id : `${next.id}-${event.stepKey}`;
        if (!next.artifacts.some((a) => a.id === id)) {
          next.artifacts.push({ id, stepKey: event.stepKey, model: step?.model || '', content: payload.content });
        }
      }
      break;
    case 'step_error':
      if (step) {
        step.status = 'error';
        step.finishedAt = event.at;
        step.error = typeof payload.error === 'string' ? payload.error : 'Error';
      }
      break;
    case 'step_interrupted':
      if (step) step.status = 'interrupted';
      break;
    case 'step_approval_requested':
      if (step) step.status = 'waiting_approval';
      next.status = 'waiting_approval';
      break;
    case 'step_approved':
      if (step) step.status = 'pending';
      next.status = 'interrupted';
      break;
    // A refusal is terminal: the run never resumes, so the step keeps the
    // verdict rather than falling back to the generic error state.
    case 'step_rejected':
      if (step) {
        step.status = 'rejected';
        step.finishedAt = event.at;
      }
      break;
    case 'run_rejected':
      next.status = 'rejected';
      next.finishedAt = event.at;
      break;
    case 'run_completed':
      next.status = 'completed';
      next.finishedAt = event.at;
      next.finalAnswer = finalAnswerOf(next);
      break;
    case 'run_error':
      next.status = 'error';
      next.finishedAt = event.at;
      next.error = typeof payload.error === 'string' ? payload.error : next.error || 'La ejecución terminó con error';
      break;
    case 'run_interrupted':
    case 'run_stop_requested':
      next.status = 'interrupted';
      break;
    default:
      break;
  }
  if (typeof payload.elapsed_seconds === 'number') next.usage.elapsedSeconds = payload.elapsed_seconds;
  return next;
}

/**
 * Topological order of steps (dependencies first); stable for equal depth.
 * @param {{key: string, dependencies: string[]}[]} steps
 * @returns {string[]}
 */
export function topoOrder(steps) {
  const byKey = new Map(steps.map((s) => [s.key, s]));
  /** @type {string[]} */
  const order = [];
  const seen = new Set();
  /** @param {string} key */
  const visit = (key) => {
    if (seen.has(key)) return;
    seen.add(key);
    for (const dep of byKey.get(key)?.dependencies || []) if (byKey.has(dep)) visit(dep);
    order.push(key);
  };
  for (const step of steps) visit(step.key);
  return order;
}

/**
 * The deliverable of a completed run is the artifact of its last step.
 * @param {Execution} execution
 * @returns {string|null}
 */
export function finalAnswerOf(execution) {
  const order = topoOrder(execution.steps);
  for (let i = order.length - 1; i >= 0; i -= 1) {
    const artifact = execution.artifacts.find((a) => a.stepKey === order[i]);
    if (artifact) return artifact.content;
  }
  return null;
}

/**
 * Build a trace (spans with relative timing) from a run's event log.
 * @param {Execution} execution
 * @param {RunEvent[]} events
 * @returns {Trace}
 */
export function buildTrace(execution, events) {
  const ordered = [...events].sort((a, b) => a.seq - b.seq);
  const t0 = ordered.length ? Date.parse(ordered[0].at) : Date.parse(execution.createdAt);
  const ms = (/** @type {string} */ at) => Math.max(0, Date.parse(at) - t0);
  /** @type {Span[]} */
  const spans = [];
  /** @type {Map<string, Span>} */
  const openSteps = new Map();
  /** @type {Map<string, Span[]>} */
  const openTools = new Map();
  /** @type {Map<string, Span>} */
  const openApprovals = new Map();
  let tokensIn = 0;
  let tokensOut = 0;
  let errors = 0;
  let lastMs = 0;
  for (const event of ordered) {
    const at = ms(event.at);
    lastMs = Math.max(lastMs, at);
    const key = event.stepKey || 'run';
    const payload = event.payload || {};
    if (event.kind === 'step_started') {
      const span = { id: `s-${event.seq}`, name: key, kind: /** @type {const} */ ('paso'), stepKey: key, startMs: at, durationMs: 0, status: /** @type {'running'} */ ('running'), tokens: 0 };
      spans.push(span);
      openSteps.set(key, span);
    } else if (event.kind === 'step_completed' || event.kind === 'step_error' || event.kind === 'step_interrupted') {
      const span = openSteps.get(key);
      if (span) {
        span.durationMs = at - span.startMs;
        span.status = event.kind === 'step_completed' ? 'ok' : 'error';
        openSteps.delete(key);
      }
      if (event.kind === 'step_error') errors += 1;
    } else if (event.kind === 'tool_started') {
      const span = { id: `t-${event.seq}`, name: String(payload.tool || 'herramienta'), kind: /** @type {const} */ ('herramienta'), stepKey: key, startMs: at, durationMs: 0, status: /** @type {'running'} */ ('running'), tokens: 0 };
      spans.push(span);
      const list = openTools.get(key + '|' + span.name) || [];
      list.push(span);
      openTools.set(key + '|' + span.name, list);
    } else if (event.kind === 'tool_finished') {
      const list = openTools.get(key + '|' + String(payload.tool || 'herramienta')) || [];
      const span = list.shift();
      if (span) {
        span.durationMs = typeof payload.duration_seconds === 'number' ? Math.round(payload.duration_seconds * 1000) : at - span.startMs;
        span.status = payload.error === true ? 'error' : 'ok';
        if (payload.error === true) errors += 1;
      }
    } else if (event.kind === 'model_metrics') {
      const metrics = /** @type {Record<string, unknown>} */ (payload.metrics && typeof payload.metrics === 'object' ? payload.metrics : {});
      const input = num(metrics.input_tokens);
      const output = num(metrics.output_tokens);
      tokensIn += input;
      tokensOut += output;
      const seconds = num(metrics.response_time);
      spans.push({ id: `m-${event.seq}`, name: String(metrics.model || payload.model || 'modelo'), kind: 'modelo', stepKey: key,
                   startMs: Math.max(0, at - Math.round(seconds * 1000)), durationMs: Math.round(seconds * 1000), status: 'ok', tokens: input + output });
    } else if (event.kind === 'step_approval_requested') {
      const span = { id: `a-${event.seq}`, name: `aprobación ${key}`, kind: /** @type {const} */ ('aprobacion'), stepKey: key, startMs: at, durationMs: 0, status: /** @type {'running'} */ ('running'), tokens: 0 };
      spans.push(span);
      openApprovals.set(key, span);
    } else if (event.kind === 'step_approved') {
      const span = openApprovals.get(key);
      if (span) {
        span.durationMs = at - span.startMs;
        span.status = 'ok';
      }
    }
  }
  for (const span of spans) if (span.status === 'running') span.durationMs = Math.max(0, lastMs - span.startMs);
  return {
    id: `trace-${execution.id}`,
    executionId: execution.id,
    name: execution.workflowName,
    status: execution.status,
    startedAt: execution.startedAt || execution.createdAt,
    durationMs: lastMs,
    tokensIn,
    tokensOut,
    costUsd: execution.usage.costUsd,
    errors,
    agents: [...new Set(execution.steps.map((s) => s.agentName))],
    measured: ordered.length > 0,
    spans,
    origin: execution.origin,
  };
}
