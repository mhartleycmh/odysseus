// Every translation key used by the code exists in the Spanish dictionary,
// including the dynamic families built at runtime ("status.step." + status).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { lookup, t } from '../../../static/cmh-os/js/core/i18n.js';
import { RUN_EVENT_KINDS } from '../../../static/cmh-os/js/services/run-state.js';

const jsRoot = join(dirname(fileURLToPath(import.meta.url)), '../../../static/cmh-os/js');
/** @param {string} dir @returns {string[]} */
const walk = (dir) => readdirSync(dir).flatMap((n) => (statSync(join(dir, n)).isDirectory() ? walk(join(dir, n)) : [join(dir, n)]));
const sources = walk(jsRoot).filter((f) => f.endsWith('.js')).map((f) => readFileSync(f, 'utf8'));

test('every literal key passed to t() exists', () => {
  const keys = new Set();
  for (const source of sources) {
    for (const match of source.matchAll(/\bt\(\s*'([^']+)'\s*[,)]/g)) keys.add(match[1]);
    for (const match of source.matchAll(/patternMessage:\s*'([^']+)'/g)) keys.add(match[1]);
  }
  const missing = [...keys].filter((key) => lookup(key) === null);
  assert.ok(keys.size > 600, `expected many keys, found ${keys.size}`);
  assert.deepEqual(missing, []);
});

const FAMILIES = {
  'status.agent.': ['active', 'paused', 'running', 'error'],
  'status.execution.': ['pending', 'running', 'waiting_approval', 'completed', 'error', 'interrupted', 'paused'],
  'status.step.': ['pending', 'running', 'waiting_approval', 'completed', 'error', 'interrupted'],
  'status.mcp.': ['connected', 'disconnected', 'error', 'needs_auth'],
  'risk.': ['alto', 'medio', 'bajo'],
  'permission.': ['lectura', 'escritura', 'admin'],
  'priority.': ['baja', 'media', 'alta'],
  'tone.': ['ok', 'warn', 'risk', 'idle', 'live'],
  'memory.kind.': ['todas', 'trabajo', 'episodica', 'semantica'],
  'approvals.kind.': ['paso', 'memoria', 'herramienta'],
  'approvals.status.': ['pendiente', 'aprobada', 'rechazada'],
  'tools.category.': ['archivos', 'shell', 'web', 'mcp', 'memoria', 'comunicacion'],
  'security.effect.': ['permitir', 'denegar', 'aprobar'],
  'security.enforced.': ['backend', 'interfaz', 'demo'],
  'security.outcome.': ['ok', 'rechazado', 'error'],
  'security.recorded.': ['servidor', 'local', 'demo'],
  'evaluations.result.': ['ok', 'fallo', 'pendiente'],
  'trace.kind.': ['paso', 'herramienta', 'modelo', 'aprobacion'],
  'graph.phase.': ['plan', 'ejecutar', 'observar', 'reflexionar'],
  'settings.themeOption.': ['system', 'light', 'dark'],
  'settings.motionOption.': ['system', 'reduced', 'full'],
  'settings.languageOption.': ['es'],
  'settings.providerStatus.': ['online', 'offline', 'unknown'],
  'shell.demoReason.': ['forzado', 'sin_sesion', 'sin_permiso', 'sin_servidor'],
  'executions.stream.': ['open', 'reconnecting', 'closed'],
  'nav.section.': ['operacion', 'capacidades', 'control', 'sistema'],
  'nav.': ['overview', 'orchestration', 'executions', 'approvals', 'agents', 'tools', 'memory', 'observability', 'evaluations', 'security', 'settings', 'help'],
  'event.kind.': [...RUN_EVENT_KINDS],
};

test('every dynamic key family is complete', () => {
  const missing = [];
  for (const [prefix, values] of Object.entries(FAMILIES)) for (const v of values) if (lookup(prefix + v) === null) missing.push(prefix + v);
  for (const m of ['overview', 'orchestration', 'executions', 'approvals', 'agents', 'tools', 'memory', 'observability', 'evaluations', 'security', 'settings']) {
    for (const leaf of ['href', 'text']) if (lookup(`help.module.${m}.${leaf}`) === null) missing.push(`help.module.${m}.${leaf}`);
  }
  for (const g of ['agent', 'coordinator', 'workflow', 'execution', 'step', 'artifact', 'approval', 'memory', 'mcp', 'trace', 'span', 'token', 'loop', 'leastPrivilege', 'demo']) {
    for (const leaf of ['name', 'text']) if (lookup(`help.term.${g}.${leaf}`) === null) missing.push(`help.term.${g}.${leaf}`);
  }
  assert.deepEqual(missing, []);
});

test('t interpolates variables and leaves unknown placeholders', () => {
  assert.equal(t('agents.count', { shown: 2, total: 5 }), 'Mostrando 2 de 5 agentes');
  assert.equal(t('agents.count', { shown: 2 }), 'Mostrando 2 de {total} agentes');
  assert.equal(t('no.such.key'), 'no.such.key');
});

test('interface copy avoids exclamation marks and emoji (CMH executive style)', () => {
  const dictionary = readFileSync(join(jsRoot, 'i18n', 'es.js'), 'utf8');
  assert.doesNotMatch(dictionary, /[!¡]/);
  assert.doesNotMatch(dictionary, /[\u{1F300}-\u{1FAFF}]/u);
});
