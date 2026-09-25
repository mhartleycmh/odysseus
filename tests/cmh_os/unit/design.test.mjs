// Design-system checks: WCAG contrast of the token pairs used for text in both
// themes, and the orchestration graph layout.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { layoutGraph, layers } from '../../../static/cmh-os/js/components/graph.js';
import { WORKFLOWS } from '../../../static/cmh-os/js/mocks/data.js';

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../../../static/cmh-os/css/tokens.css'), 'utf8');

/** @param {string} selector */
function block(selector) {
  const start = css.indexOf(selector + ' {');
  assert.ok(start >= 0, `missing ${selector}`);
  const body = css.slice(start, css.indexOf('}', start));
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]));
}
const light = block(':root');
const dark = { ...light, ...block(":root[data-theme='dark']") };

/** @param {string} hex */
function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
/** @param {string} a @param {string} b */
export function contrast(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m);
  return (x + 0.05) / (y + 0.05);
}

// [foreground, background, minimum]: 4.5 for normal text, 3 for large text or graphics.
const PAIRS = [
  ['text', 'bg', 4.5], ['text', 'surface', 4.5], ['text', 'surface-2', 4.5], ['text-muted', 'surface', 4.5], ['text-muted', 'surface-2', 4.5],
  ['text-strong', 'surface', 4.5], ['link', 'surface', 4.5], ['link', 'surface-2', 4.5],
  ['ok-text', 'ok-bg', 4.5], ['warn-text', 'warn-bg', 4.5], ['risk-text', 'risk-bg', 4.5], ['idle-text', 'idle-bg', 4.5], ['live', 'live-bg', 4.5],
  ['risk-text', 'surface', 4.5], ['ok-text', 'surface', 4.5],
  ['header-text', 'header-bg', 4.5], ['header-muted', 'header-bg', 4.5], ['nav-text', 'nav-bg', 4.5], ['nav-active-text', 'nav-active-bg', 4.5],
  ['canvas-text', 'canvas-node', 4.5], ['canvas-muted', 'canvas-node', 4.5], ['canvas-muted', 'canvas-bg', 4.5],
  ['canvas-live', 'canvas-node', 4.5], ['canvas-ok', 'canvas-node', 4.5], ['canvas-warn', 'canvas-node', 4.5], ['canvas-risk', 'canvas-node', 4.5],
  ['canvas-accent', 'canvas-node', 4.5], ['focus', 'surface', 3], ['border-strong', 'surface', 1.4],
];

for (const [name, theme] of [['claro', light], ['oscuro', dark]]) {
  test(`token pairs meet WCAG AA in the ${name} theme`, () => {
    const failures = PAIRS.map(([fg, bg, min]) => ({ fg, bg, min, ratio: contrast(theme[fg], theme[bg]) }))
      .filter((p) => p.ratio < p.min).map((p) => `${p.fg} on ${p.bg}: ${p.ratio.toFixed(2)} < ${p.min}`);
    assert.deepEqual(failures, []);
  });
}

test('primary button text is readable in both themes', () => {
  assert.ok(contrast(light['text-on-brand'], light['cmh-azul']) >= 4.5);
  assert.ok(contrast(light['text-on-brand'], light['cmh-azul-medio']) >= 4.5, 'dark theme primary uses azul medio');
});

test('brand gold is never a light-theme text token (CMH identity rule)', () => {
  assert.notEqual(light['accent-text'], light['cmh-oro']);
  assert.ok(contrast(light['cmh-oro'], light.surface) < 3, 'sanity: #B19A3B on white fails, which is why the rule exists');
  const stylesheets = ['base.css', 'components.css', 'views.css'].map((f) => readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../../../static/cmh-os/css', f), 'utf8')).join('\n');
  assert.doesNotMatch(stylesheets, /(^|[^-])color:\s*var\(--(accent|cmh-oro)\)/m, 'gold only as fill, border or on dark canvas');
});

test('graph layout places each step one layer after its deepest dependency', () => {
  const steps = WORKFLOWS[0].steps.map((s) => ({ key: s.key, dependencies: s.dependsOn }));
  const depth = layers(steps);
  assert.equal(depth.get('planificacion'), 0);
  assert.equal(depth.get('produccion'), 1);
  assert.equal(depth.get('finanzas'), 2);
  assert.equal(depth.get('sostenibilidad'), 3);
});

for (const orientation of ['horizontal', 'vertical']) {
  test(`${orientation} graph layout has no overlapping nodes and stays inside the canvas`, () => {
    for (const workflow of WORKFLOWS) {
      const layout = layoutGraph(workflow.steps.map((s) => ({ key: s.key, dependencies: s.dependsOn })), orientation);
      assert.equal(layout.nodes.length, workflow.steps.length);
      for (const node of layout.nodes) {
        assert.ok(node.x - layout.nodeW / 2 >= 0 && node.x + layout.nodeW / 2 <= layout.width, `${node.key} x inside`);
        assert.ok(node.y - layout.nodeH / 2 >= 100 && node.y + layout.nodeH / 2 <= layout.height, `${node.key} y inside and below the hub`);
      }
      for (let i = 0; i < layout.nodes.length; i += 1) {
        for (let j = i + 1; j < layout.nodes.length; j += 1) {
          const a = layout.nodes[i]; const b = layout.nodes[j];
          const apart = Math.abs(a.x - b.x) >= layout.nodeW || Math.abs(a.y - b.y) >= layout.nodeH;
          assert.ok(apart, `${a.key} overlaps ${b.key}`);
        }
      }
      assert.equal(layout.edges.length, workflow.steps.reduce((n, s) => n + s.dependsOn.length, 0));
    }
  });
}
