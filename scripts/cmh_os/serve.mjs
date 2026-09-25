// Local server for previews and end-to-end tests. Serves /cmh/os and /static
// like FastAPI does, with a CSP as strict as Odysseus', and optionally a fake
// API built from tests/cmh_os/fixtures/api_samples.json (same keys as the
// real handlers; see tests/test_cmh_os_routes.py).
//   node scripts/cmh_os/serve.mjs --port 8765          demo mode (no API)
//   node scripts/cmh_os/serve.mjs --port 8765 --api    live mode against the fake API
import { createServer } from 'node:http';
import { readFileSync, existsSync, statSync } from 'node:fs';
import { dirname, extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../..');
const staticRoot = join(repo, 'static');
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
                '.png': 'image/png', '.ico': 'image/x-icon', '.json': 'application/json', '.svg': 'image/svg+xml' };
const CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'";

/** @param {import('node:http').ServerResponse} res @param {number} status @param {unknown} body */
function json(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(body));
}

/** @param {import('node:http').IncomingMessage} req */
async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString('utf8');
  try { return text ? JSON.parse(text) : null; } catch { return text; }
}

function fakeState() {
  const samples = JSON.parse(readFileSync(join(repo, 'tests/cmh_os/fixtures/api_samples.json'), 'utf8'));
  return { samples, calls: /** @type {string[]} */ ([]), nextSeq: 100, latencyMs: 0,
           /** @type {Map<string, Set<import('node:http').ServerResponse>>} */ streams: new Map() };
}

/** Append an event to a run and push it to every open stream, like the real SSE loop. */
function emit(state, runId, kind, stepKey, payload = {}) {
  const event = { seq: ++state.nextSeq, kind, data: { step_key: stepKey, payload, at: new Date().toISOString() } };
  (state.samples.events[runId] ||= []).push(event);
  for (const res of state.streams.get(runId) || []) res.write(`id: ${event.seq}\nevent: ${kind}\ndata: ${JSON.stringify(event.data)}\n\n`);
}

/**
 * @param {ReturnType<typeof fakeState>} state
 * @param {import('node:http').IncomingMessage} req
 * @param {import('node:http').ServerResponse} res
 * @param {URL} url
 */
async function fakeApi(state, req, res, url) {
  const s = state.samples;
  const method = req.method || 'GET';
  const path = url.pathname;
  if (path === '/api/__test/latency' && method === 'POST') {
    state.latencyMs = Number(url.searchParams.get('ms') || 0);
    return json(res, 200, { latencyMs: state.latencyMs });
  }
  if (path === '/api/__test/streams') return json(res, 200, { open: [...state.streams.values()].reduce((n, set) => n + set.size, 0) });
  state.calls.push(`${method} ${path}`);
  const body = method !== 'GET' ? await readBody(req) : null;
  if (state.latencyMs) await new Promise((resolveDelay) => setTimeout(resolveDelay, state.latencyMs));
  const run = path.match(/^\/api\/cmh\/runs\/([^/]+)(\/.*)?$/);
  if (method === 'GET' && path === '/api/cmh/os/config') return json(res, 200, s.os_config);
  if (method === 'GET' && path === '/api/cmh/agents') return json(res, 200, s.agents);
  if (method === 'GET' && path === '/api/cmh/projects') return json(res, 200, s.projects);
  if (method === 'GET' && path === '/api/cmh/workflows') return json(res, 200, s.workflows);
  if (method === 'GET' && path === '/api/cmh/runs') return json(res, 200, s.runs);
  if (run && method === 'GET' && !run[2]) {
    const detail = s.run_detail[decodeURIComponent(run[1])];
    return detail ? json(res, 200, detail) : json(res, 404, { detail: 'Workflow run not found' });
  }
  if (run && method === 'GET' && run[2] === '/events') {
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
    const after = Number(req.headers['last-event-id'] || url.searchParams.get('after') || 0);
    const events = s.events[decodeURIComponent(run[1])] || [];
    for (const e of events.filter((ev) => ev.seq > after)) res.write(`id: ${e.seq}\nevent: ${e.kind}\ndata: ${JSON.stringify(e.data)}\n\n`);
    const runId = decodeURIComponent(run[1]);
    if (!state.streams.has(runId)) state.streams.set(runId, new Set());
    state.streams.get(runId).add(res);
    const timer = setInterval(() => res.write(': keep-alive\n\n'), 5000);
    req.on('close', () => { clearInterval(timer); state.streams.get(runId)?.delete(res); });
    return undefined;
  }
  if (run && method === 'POST') {
    const id = decodeURIComponent(run[1]);
    const detail = s.run_detail[id];
    const summary = s.runs.runs.find((r) => r.id === id);
    if (!detail || !summary) return json(res, 404, { detail: 'Workflow run not found' });
    const approve = run[2] && run[2].match(/^\/steps\/([^/]+)\/approve$/);
    if (approve) {
      // Same checks and event sequence as routes/cmh_workflow_routes.py + src/cmh_workflows.py:
      // the step runs after approval and its step_completed carries only the artifact id.
      const key = decodeURIComponent(approve[1]);
      const step = detail.steps.find((st) => st.key === key);
      if (!step || detail.status !== 'waiting_approval' || step.status !== 'waiting_approval') return json(res, 409, { detail: 'No approval pending for this step' });
      step.status = 'running';
      detail.status = summary.status = 'running';
      emit(state, id, 'step_approved', key);
      emit(state, id, 'run_started', null);
      emit(state, id, 'step_started', key, { agent_id: step.agent_id, model: step.model });
      setTimeout(() => {
        const artifactId = `art-${key}-${state.nextSeq}`;
        detail.artifacts.push({ id: artifactId, step_key: key, model: step.model, content: 'APROBADO con evidencia (sintético).' });
        step.status = 'completed';
        detail.status = summary.status = 'completed';
        emit(state, id, 'step_completed', key, { artifact_id: artifactId, duration_seconds: 1.5 });
        emit(state, id, 'run_completed', null);
      }, 1500);
      return json(res, 200, { id, step_key: key, status: 'approved' });
    }
    const reject = run[2] && run[2].match(/^\/steps\/([^/]+)\/reject$/);
    if (reject) {
      // Mirrors routes/cmh_workflow_routes.py: a refusal needs a reason, ends
      // the run and is terminal, so the artifacts already produced stay.
      const key = decodeURIComponent(reject[1]);
      const step = detail.steps.find((st) => st.key === key);
      const justification = String((body && body.justification) || '').trim();
      if (!justification) return json(res, 400, { detail: 'A rejection needs a justification' });
      if (!step || detail.status !== 'waiting_approval' || step.status !== 'waiting_approval') return json(res, 409, { detail: 'No approval pending for this step' });
      const decision = { outcome: 'rejected', justification, by: 'admin', at: new Date().toISOString() };
      step.status = 'rejected';
      step.decision = decision;
      detail.status = summary.status = 'rejected';
      emit(state, id, 'step_rejected', key);
      emit(state, id, 'run_rejected', null);
      return json(res, 200, { id, step_key: key, status: 'rejected', decision });
    }
    if (run[2] === '/stop') {
      if (!['running', 'pending', 'waiting_approval'].includes(detail.status)) return json(res, 409, { detail: 'Run is not active' });
      detail.status = summary.status = 'interrupted';
      for (const step of detail.steps) if (step.status === 'waiting_approval') step.status = 'pending';
      emit(state, id, 'run_stop_requested', null);
      emit(state, id, 'run_interrupted', null);
      return json(res, 200, { id, status: 'interrupted' });
    }
    if (run[2] === '/resume') {
      detail.status = summary.status = 'waiting_approval';
      return json(res, 200, { id, status: 'interrupted' });
    }
  }
  if (method === 'GET' && path === '/api/cmh/memories') return json(res, 200, s.memories);
  if (method === 'GET' && path === '/api/cmh/memories/content') return json(res, 200, s.memory_content);
  if (method === 'GET' && path === '/api/cmh/memory-proposals') return json(res, 200, s.memory_proposals);
  const proposal = path.match(/^\/api\/cmh\/memory-proposals\/([^/]+)(\/(approve|reject))?$/);
  if (proposal && method === 'GET') return json(res, 200, { ...s.memory_proposal_detail, id: proposal[1] });
  if (proposal && method === 'POST' && proposal[3]) {
    const row = s.memory_proposals.proposals.find((p) => p.id === proposal[1]);
    if (!row || row.status !== 'pending') return json(res, 409, { detail: 'Proposal already decided' });
    row.status = proposal[3] === 'approve' ? 'approved' : 'rejected';
    return json(res, 200, { id: row.id, status: row.status });
  }
  if (method === 'GET' && path === '/api/model-endpoints') return json(res, 200, s.model_endpoints);
  if (method === 'GET' && path === '/api/mcp/servers') return json(res, 200, s.mcp_servers);
  if (method === 'GET' && path === '/api/mcp/tools') return json(res, 200, s.mcp_tools);
  const agent = path.match(/^\/api\/cmh\/agents\/([^/]+)\/(pause|resume)$/);
  if (agent && method === 'POST') {
    const row = s.agents.agents.find((a) => a.id === agent[1]);
    if (!row) return json(res, 404, { detail: 'Agent not found' });
    row.status = agent[2] === 'pause' ? 'paused' : 'active';
    return json(res, 200, row);
  }
  return json(res, 404, { detail: `No fake route for ${method} ${path}` });
}

/**
 * @param {{port?: number, api?: boolean}} [options]
 */
export function startServer(options = {}) {
  const state = options.api ? fakeState() : null;
  const server = createServer(async (req, res) => {
    const url = new URL(req.url || '/', 'http://localhost');
    try {
      if (url.pathname === '/cmh/os' || url.pathname === '/cmh/os/') {
        res.writeHead(200, { 'Content-Type': TYPES['.html'], 'Content-Security-Policy': CSP, 'Cache-Control': 'no-store' });
        res.end(readFileSync(join(staticRoot, 'cmh-os', 'index.html')));
        return;
      }
      if (url.pathname.startsWith('/static/')) {
        const file = normalize(join(staticRoot, decodeURIComponent(url.pathname.slice('/static/'.length))));
        if (!file.startsWith(staticRoot) || !existsSync(file) || !statSync(file).isFile()) { res.writeHead(404); res.end('not found'); return; }
        res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
        res.end(readFileSync(file));
        return;
      }
      if (url.pathname.startsWith('/api/')) {
        if (state) { await fakeApi(state, req, res, url); return; }
        if (url.pathname === '/api/cmh/os/config') { json(res, 200, { ui_enabled: true, default_mode: 'demo' }); return; }
        json(res, 404, { detail: 'No API in demo server' });
        return;
      }
      res.writeHead(302, { Location: '/cmh/os' });
      res.end();
    } catch (error) {
      json(res, 500, { detail: String(error) });
    }
  });
  return new Promise((resolvePromise) => {
    server.listen(options.port || 0, '127.0.0.1', () => {
      const address = /** @type {import('node:net').AddressInfo} */ (server.address());
      resolvePromise({ url: `http://127.0.0.1:${address.port}`, calls: state ? state.calls : [], close: () => new Promise((r) => { server.closeAllConnections?.(); server.close(() => r(undefined)); }) });
    });
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const portIndex = process.argv.indexOf('--port');
  const port = portIndex > 0 ? Number(process.argv[portIndex + 1]) : 8765;
  startServer({ port, api: process.argv.includes('--api') }).then((server) => {
    process.stdout.write(`Agentic OS CMH preview: ${server.url}/cmh/os${process.argv.includes('--api') ? ' (fake API)' : ' (demo)'}\n`);
  });
}
