// Deterministic run simulator for demo mode. It emits the same event kinds as
// the backend SSE stream (ADR-004) and enforces the limits the backend does not
// yet apply: iterations, simulated time and budget. Pure: no timers here; the
// caller decides how fast to replay (demo.js drives it with setTimeout, tests
// call next() in a loop).
import { createRng } from '../mocks/rng.js';
import { DEMO_PRICES, STEP_TOOLS } from '../mocks/data.js';

/** @typedef {import('../types.js').Execution} Execution */
/** @typedef {import('../types.js').RunEvent} RunEvent */
/** @typedef {import('../types.js').Agent} Agent */

/**
 * @typedef {Object} SimOptions
 * @property {Execution} execution Current state; completed steps are kept.
 * @property {Map<string, Agent>} agents
 * @property {number} seed
 * @property {number} startSeq Last event sequence number already emitted.
 * @property {string|null} [failStep] Step that fails (error injection).
 * @property {string[]} [preApproved] Steps whose approval was already granted.
 */

/**
 * @typedef {Object} SimTick
 * @property {number} delayMs Real delay before emitting, for animation.
 * @property {RunEvent} event
 */

/**
 * @typedef {Object} Simulation
 * @property {() => SimTick|null} next null when waiting for approval or finished.
 * @property {(stepKey: string) => boolean} approve
 * @property {() => RunEvent[]} cancel
 * @property {() => boolean} isFinished
 * @property {() => string|null} waitingFor
 * @property {() => number} lastSeq
 */

/** @typedef {{kind: string, stepKey: string|null, payload: Record<string, unknown>, delayMs: number, advance: number}} Item */

const RESULTS = Object.freeze([
  'Sin desvíos que requieran acción; evidencia citada.',
  'Dos observaciones con evidencia; una requiere seguimiento.',
  'Un faltante de información marcado como PENDIENTE, sin estimar.',
  'Coherente con los artefactos recibidos; límites respetados.',
]);
const MAX_PARALLEL = 2;

/**
 * @param {SimOptions} options
 * @returns {Simulation}
 */
export function createSimulation(options) {
  const { execution, agents } = options;
  const rng = createRng(options.seed);
  let seq = options.startSeq;
  const baseMs = Date.parse(execution.startedAt || execution.createdAt);
  let clock = execution.usage.elapsedSeconds;
  let iterations = execution.usage.iterations;
  let cost = execution.usage.costUsd || 0;
  /** @type {Map<string, 'pending'|'running'|'completed'|'error'|'interrupted'>} */
  const status = new Map(execution.steps.map((s) => [s.key, s.status === 'completed' ? 'completed' : 'pending']));
  const approved = new Set(options.preApproved || []);
  /** @type {Item[]} */
  let queue = [];
  let started = false;
  let finished = false;
  let failed = false;
  /** @type {string|null} */
  let waiting = null;

  /** @param {string} key */
  const stepDef = (key) => execution.steps.find((s) => s.key === key);

  /** @param {Item} item @returns {SimTick} */
  function tick(item) {
    seq += 1;
    return {
      delayMs: item.delayMs,
      event: { seq, kind: item.kind, stepKey: item.stepKey, payload: { ...item.payload, elapsed_seconds: Math.round(clock) },
               at: new Date(baseMs + clock * 1000).toISOString() },
    };
  }

  /** @param {string} key @returns {Item[]} */
  function scriptFor(key) {
    const step = stepDef(key);
    const agent = step ? agents.get(step.agentId) : undefined;
    const model = step?.model || agent?.model || 'modelo-demo-rapido';
    const tools = /** @type {Record<string, readonly string[]>} */ (STEP_TOOLS)[key] || ['read_file'];
    const common = { agent_id: step?.agentId || null, model };
    /** @type {Item[]} */
    const script = [{ kind: 'step_started', stepKey: key, payload: common, delayMs: rng.int(250, 450), advance: 1 }];
    for (const tool of tools) {
      const duration = rng.int(2, 18) / 10;
      script.push({ kind: 'tool_started', stepKey: key, payload: { ...common, tool }, delayMs: rng.int(300, 650), advance: 1 });
      script.push({ kind: 'tool_finished', stepKey: key, payload: { ...common, tool, error: false, duration_seconds: duration },
                    delayMs: Math.round(duration * 260) + 120, advance: duration });
    }
    const input = rng.int(800, 4000);
    const output = rng.int(150, 900);
    const responseTime = rng.int(12, 90) / 10;
    const price = /** @type {Record<string, number>} */ (DEMO_PRICES)[model] ?? 0.004;
    script.push({ kind: 'model_metrics', stepKey: key, delayMs: rng.int(500, 900), advance: responseTime,
      payload: { ...common, cost_usd: Math.round(((input + output) / 1000) * price * 10000) / 10000,
                 metrics: { model, input_tokens: input, output_tokens: output, total_tokens: input + output, response_time: responseTime, usage_source: 'demo' } } });
    if (options.failStep === key) {
      script.push({ kind: 'step_error', stepKey: key, payload: { error: 'Fallo simulado: el origen de datos no respondió (demo)' }, delayMs: 400, advance: 1 });
    } else {
      const content = [`Artefacto de demostración — ${agent?.name || key}`, `Objetivo: ${execution.objective}`,
                       `Evidencia: ${tools.join(', ')}`, `Resultado: ${rng.pick(RESULTS)}`].join('\n');
      script.push({ kind: 'step_completed', stepKey: key, delayMs: rng.int(300, 600), advance: 1,
                    payload: { artifact_id: `${execution.id}-${key}-a${execution.attempt}`, content } });
    }
    return script;
  }

  function schedule() {
    const keys = [...status.keys()];
    const pending = keys.filter((k) => status.get(k) === 'pending');
    const running = keys.filter((k) => status.get(k) === 'running');
    if (!pending.length && !running.length) {
      const allDone = keys.every((k) => status.get(k) === 'completed');
      queue.push({ kind: allDone ? 'run_completed' : 'run_error', stepKey: null, payload: allDone ? {} : { error: 'Hay pasos con error' }, delayMs: 500, advance: 1 });
      return;
    }
    const done = new Set(keys.filter((k) => status.get(k) === 'completed'));
    const ready = pending.filter((key) => (stepDef(key)?.dependencies || []).every((dep) => done.has(dep))).slice(0, MAX_PARALLEL);
    if (!ready.length) {
      if (!running.length) queue.push({ kind: 'run_error', stepKey: null, payload: { error: 'Ningún paso ejecutable' }, delayMs: 300, advance: 0 });
      return;
    }
    const gated = ready.find((key) => stepDef(key)?.requiresApproval && !approved.has(key));
    if (gated) {
      queue.push({ kind: 'step_approval_requested', stepKey: gated, payload: {}, delayMs: 450, advance: 1 });
      return;
    }
    const scripts = ready.map((key) => {
      status.set(key, 'running');
      return scriptFor(key);
    });
    // Interleave parallel steps so both visibly progress at the same time.
    while (scripts.some((script) => script.length)) {
      for (const script of scripts) {
        const item = script.shift();
        if (item) queue.push(item);
      }
    }
  }

  /** @param {Item} item @returns {string|null} */
  function limitCrossed(item) {
    const limits = execution.limits;
    if (item.kind === 'tool_started' || item.kind === 'model_metrics') {
      iterations += 1;
      if (limits.maxIterations !== null && iterations > limits.maxIterations) return `Límite de iteraciones alcanzado (${limits.maxIterations})`;
    }
    if (limits.timeoutSeconds !== null && clock > limits.timeoutSeconds) return `Tiempo límite superado (${limits.timeoutSeconds} s simulados)`;
    if (item.kind === 'model_metrics') {
      cost += typeof item.payload.cost_usd === 'number' ? item.payload.cost_usd : 0;
      if (limits.budgetUsd !== null && cost > limits.budgetUsd) return `Presupuesto agotado (US$ ${limits.budgetUsd.toFixed(2)})`;
    }
    return null;
  }

  /** Apply the state change of an item, then emit it. @param {Item} item @returns {SimTick} */
  function handle(item) {
    if (item.kind === 'step_completed' && item.stepKey) status.set(item.stepKey, 'completed');
    if (item.kind === 'step_error' && item.stepKey) {
      status.set(item.stepKey, 'error');
      failed = true;
      queue = [];
      for (const [key, s] of status) {
        if (s === 'running') {
          status.set(key, 'interrupted');
          queue.push({ kind: 'step_interrupted', stepKey: key, payload: {}, delayMs: 200, advance: 0 });
        }
      }
      queue.push({ kind: 'run_error', stepKey: null, payload: { error: String(item.payload.error || 'Error') }, delayMs: 300, advance: 0 });
    }
    if (item.kind === 'step_approval_requested' && item.stepKey) waiting = item.stepKey;
    if (item.kind === 'run_completed' || item.kind === 'run_error') finished = true;
    return tick(item);
  }

  return {
    next() {
      if (finished || waiting) return null;
      if (!started) {
        started = true;
        return tick({ kind: 'run_started', stepKey: null, payload: {}, delayMs: 300, advance: 0 });
      }
      if (!queue.length) schedule();
      const item = queue.shift();
      if (!item) return null;
      clock += item.advance;
      const reason = failed ? null : limitCrossed(item);
      if (!reason) return handle(item);
      failed = true;
      const key = item.stepKey || [...status.entries()].find(([, s]) => s === 'running')?.[0] || null;
      /** @type {Item} */
      const error = key
        ? { kind: 'step_error', stepKey: key, payload: { error: reason }, delayMs: 300, advance: 0 }
        : { kind: 'run_error', stepKey: null, payload: { error: reason }, delayMs: 300, advance: 0 };
      if (item.kind === 'model_metrics') {
        // Emit the call that crossed the budget, then stop.
        queue = [error];
        return tick(item);
      }
      return handle(error);
    },
    approve(stepKey) {
      if (waiting !== stepKey) return false;
      approved.add(stepKey);
      waiting = null;
      queue.push({ kind: 'step_approved', stepKey, payload: {}, delayMs: 200, advance: 1 });
      queue.push({ kind: 'run_started', stepKey: null, payload: {}, delayMs: 250, advance: 0 });
      return true;
    },
    cancel() {
      if (finished) return [];
      finished = true;
      queue = [];
      const events = [tick({ kind: 'run_stop_requested', stepKey: null, payload: {}, delayMs: 0, advance: 0 }).event];
      for (const [key, s] of status) {
        if (s === 'running') events.push(tick({ kind: 'step_interrupted', stepKey: key, payload: {}, delayMs: 0, advance: 0 }).event);
      }
      events.push(tick({ kind: 'run_interrupted', stepKey: null, payload: {}, delayMs: 0, advance: 0 }).event);
      return events;
    },
    isFinished: () => finished,
    waitingFor: () => waiting,
    lastSeq: () => seq,
  };
}
