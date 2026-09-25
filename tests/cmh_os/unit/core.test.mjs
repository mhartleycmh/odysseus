// Unit tests for pure core modules: router, validation, formatting, prefs, derive.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseHash, matchRoute, href } from '../../../static/cmh-os/js/core/router.js';
import { validate, expectObject, ContractError, strList } from '../../../static/cmh-os/js/core/validate.js';
import { formatDuration, formatUsd, formatPercent, formatDateTime, shortId } from '../../../static/cmh-os/js/core/format.js';
import { sanitizePrefs, DEFAULT_PREFS } from '../../../static/cmh-os/js/core/prefs.js';
import { permissionFor, workflowCompatible, riskOfTool } from '../../../static/cmh-os/js/services/derive.js';

const ROUTES = [
  { name: 'overview', pattern: '/' },
  { name: 'agents', pattern: '/agentes' },
  { name: 'agent', pattern: '/agentes/:id' },
  { name: 'trace', pattern: '/observabilidad/:id' },
];

test('parseHash normalizes empty, trailing slash and query', () => {
  assert.deepEqual(parseHash('').path, '/');
  assert.equal(parseHash('#/agentes/').path, '/agentes');
  const { path, query } = parseHash('#/ejecuciones?nuevo=wf-1&x=2');
  assert.equal(path, '/ejecuciones');
  assert.equal(query.get('nuevo'), 'wf-1');
});

test('matchRoute extracts decoded params and rejects unknown paths', () => {
  assert.equal(matchRoute(ROUTES, '#/')?.name, 'overview');
  const match = matchRoute(ROUTES, '#/agentes/ag%20uno');
  assert.equal(match?.name, 'agent');
  assert.equal(match?.params.id, 'ag uno');
  assert.equal(matchRoute(ROUTES, '#/agentes/a/b'), null);
  assert.equal(matchRoute(ROUTES, '#/nada'), null);
  assert.equal(matchRoute(ROUTES, '#/agentes/%E0%A4%A'), null, 'malformed escape must not throw');
});

test('href encodes params', () => {
  assert.equal(href('/agentes/:id', { id: 'a/b' }), '#/agentes/a%2Fb');
});

test('validate applies required, length, number and pattern rules', () => {
  const schema = {
    name: { required: true, maxLength: 5 },
    notes: { minLength: 3 },
    n: { required: true, integer: true, min: 1, max: 10 },
    budget: { required: true, min: 0.01 },
    code: { pattern: /^[a-z]+$/ },
    pick: { oneOf: ['a', 'b'] },
  };
  assert.deepEqual(validate(schema, { name: 'ok', n: '3', budget: '0,5', code: 'abc', pick: 'a', notes: '' }), {});
  const errors = validate(schema, { name: '  ', n: '2.5', budget: '0', code: 'ABC', pick: 'z', notes: 'x' });
  assert.deepEqual(Object.keys(errors).sort(), ['budget', 'code', 'n', 'name', 'notes', 'pick']);
  assert.match(errors.name, /obligatorio/);
  assert.match(errors.n, /entero/);
  assert.match(validate(schema, { name: 'toolong', n: '11', budget: '1' }).n, /máximo es 10/);
});

test('validate runs custom checks after built-in rules', () => {
  const schema = { a: { required: true, check: (value) => (value === 'bad' ? 'validation.pattern' : null) } };
  assert.match(validate(schema, { a: 'bad' }).a, /formato/);
  assert.deepEqual(validate(schema, { a: 'good' }), {});
});

test('contract helpers reject wrong shapes', () => {
  assert.throws(() => expectObject([], 'x'), ContractError);
  assert.deepEqual(strList({ l: ['a', 1, 'b'] }, 'l'), ['a', 'b']);
});

test('format helpers produce es-PE output', () => {
  assert.equal(formatDuration(0.25), '250 ms');
  assert.equal(formatDuration(5.5), '5.5 s', 'same decimal separator as every other number (es-PE)');
  assert.equal(formatDuration(125), '2 min 5 s');
  assert.equal(formatDuration(null), '—');
  assert.match(formatUsd(1234.5), /^US\$ 1,?234\.50$/);
  assert.match(formatPercent(0.756), /75\.6\s?%/);
  // Naive backend timestamps are UTC; Lima is UTC-5.
  assert.match(formatDateTime('2026-09-24T15:00:00'), /24\/09\/2026.*10:00/);
  assert.equal(shortId('abcdefghijk'), 'abcdefgh');
});

test('sanitizePrefs keeps known values and drops junk', () => {
  assert.deepEqual(sanitizePrefs(undefined), { ...DEFAULT_PREFS, flags: { ...DEFAULT_PREFS.flags }, limits: { ...DEFAULT_PREFS.limits } });
  const prefs = sanitizePrefs({ theme: 'neon', motion: 'reduced', mode: 'demo', flags: { chatModel: 'yes', simulateFailures: true },
                                limits: { maxIterations: 5000, timeoutSeconds: 30, budgetUsd: -1 }, chatModel: { endpointId: 'e', model: '' }, actor: '  Ana  ' });
  assert.equal(prefs.theme, 'system');
  assert.equal(prefs.motion, 'reduced');
  assert.equal(prefs.mode, 'demo');
  assert.equal(prefs.flags.chatModel, false);
  assert.equal(prefs.flags.simulateFailures, true);
  assert.equal(prefs.limits.maxIterations, DEFAULT_PREFS.limits.maxIterations);
  assert.equal(prefs.limits.timeoutSeconds, 30);
  assert.equal(prefs.limits.budgetUsd, DEFAULT_PREFS.limits.budgetUsd);
  assert.equal(prefs.chatModel, null);
  assert.equal(prefs.actor, 'Ana');
});

test('permissionFor is conservative about unknown tools', () => {
  assert.equal(permissionFor(['read_file', 'ls', 'grep', 'glob']), 'lectura');
  assert.equal(permissionFor(['read_file', 'write_file']), 'escritura');
  assert.equal(permissionFor(['mcp__x__unknown']), 'escritura');
  assert.equal(permissionFor(['read_file', 'shell']), 'admin');
  assert.equal(workflowCompatible(['read_file', 'grep']), true);
  assert.equal(workflowCompatible(['read_file', 'write_file']), false);
  assert.equal(workflowCompatible([]), false);
  assert.equal(riskOfTool('send_email'), 'alto');
});
