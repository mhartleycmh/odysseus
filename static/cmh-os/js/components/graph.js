// Orchestration graph: coordinator hub plus the workflow DAG. It only moves
// when a run event arrives (ADR-004): pulse on step start, orbiting dots for
// tools in flight, particles carrying artifacts along edges, a halo while a
// step waits for approval, and the Plan → Execute → Observe → Reflect ring.
import { h, s, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { topoOrder } from '../services/run-state.js';

/** @typedef {import('../types.js').Execution} Execution */
/** @typedef {import('../types.js').RunEvent} RunEvent */
/** @typedef {import('../types.js').StepStatus} StepStatus */

/**
 * @typedef {Object} LayoutNode
 * @property {string} key
 * @property {number} x center
 * @property {number} y center
 * @property {number} layer
 */
/**
 * @typedef {Object} Layout
 * @property {number} width
 * @property {number} height
 * @property {{x: number, y: number}} hub
 * @property {LayoutNode[]} nodes
 * @property {{from: string, to: string}[]} edges
 * @property {number} nodeW
 * @property {number} nodeH
 */

/**
 * Longest-path layering: a step sits one layer after its deepest dependency.
 * @param {{key: string, dependencies: string[]}[]} steps
 * @returns {Map<string, number>}
 */
export function layers(steps) {
  const byKey = new Map(steps.map((step) => [step.key, step]));
  /** @type {Map<string, number>} */
  const depth = new Map();
  for (const key of topoOrder(steps)) {
    const deps = (byKey.get(key)?.dependencies || []).filter((d) => byKey.has(d));
    depth.set(key, deps.length ? Math.max(...deps.map((d) => depth.get(d) ?? 0)) + 1 : 0);
  }
  return depth;
}

/**
 * @param {{key: string, dependencies: string[]}[]} steps
 * @param {'horizontal'|'vertical'} orientation
 * @returns {Layout}
 */
export function layoutGraph(steps, orientation) {
  const depth = layers(steps);
  const layerCount = Math.max(1, ...[...depth.values()].map((d) => d + 1));
  /** @type {string[][]} */
  const columns = Array.from({ length: layerCount }, () => []);
  for (const step of steps) columns[depth.get(step.key) ?? 0].push(step.key);
  /** @type {LayoutNode[]} */
  const nodes = [];
  const edges = steps.flatMap((step) => step.dependencies.filter((d) => depth.has(d)).map((d) => ({ from: d, to: step.key })));
  if (orientation === 'horizontal') {
    const nodeW = 196;
    const nodeH = 64;
    const maxRows = Math.max(1, ...columns.map((c) => c.length));
    // Wide enough that consecutive layers never overlap (40 px minimum gap).
    const width = Math.max(1000, 60 + nodeW + (layerCount - 1) * (nodeW + 40));
    const top = 160;
    const rowGap = 82;
    const height = top + maxRows * rowGap + 10;
    const colGap = layerCount > 1 ? (width - 60 - nodeW) / (layerCount - 1) : 0;
    columns.forEach((keys, layer) => {
      const offset = top + ((maxRows - keys.length) * rowGap) / 2;
      keys.forEach((key, row) => nodes.push({ key, layer, x: layerCount > 1 ? 30 + nodeW / 2 + layer * colGap : width / 2, y: offset + row * rowGap + rowGap / 2 }));
    });
    return { width, height, hub: { x: width / 2, y: 64 }, nodes, edges, nodeW, nodeH };
  }
  const nodeW = 190;
  const nodeH = 60;
  const width = 440;
  let y = 170;
  columns.forEach((keys, layer) => {
    for (let i = 0; i < keys.length; i += 2) {
      const pair = keys.slice(i, i + 2);
      pair.forEach((key, index) => nodes.push({ key, layer, x: pair.length === 1 ? width / 2 : index === 0 ? width / 2 - nodeW / 2 - 10 : width / 2 + nodeW / 2 + 10, y }));
      y += 84;
    }
  });
  return { width, height: y - 20, hub: { x: width / 2, y: 64 }, nodes, edges, nodeW, nodeH };
}

/** @type {Record<StepStatus, string>} */
const STATUS_GLYPH = { pending: '○', running: '◆', waiting_approval: '▲', completed: '●', error: '■', interrupted: '▲', rejected: '✕' };
const PHASES = /** @type {const} */ (['plan', 'ejecutar', 'observar', 'reflexionar']);

/**
 * @typedef {Object} GraphOptions
 * @property {Execution} execution
 * @property {'horizontal'|'vertical'} [orientation]
 * @property {(stepKey: string) => void} [onSelect]
 * @property {() => boolean} [reducedMotion]
 * @property {string} [coordinatorLabel]
 */

/**
 * @param {GraphOptions} options
 */
export function createGraph(options) {
  let execution = options.execution;
  const orientation = options.orientation || 'horizontal';
  const layout = layoutGraph(execution.steps, orientation);
  const reduced = options.reducedMotion || (() => false);
  const nodeByKey = new Map(layout.nodes.map((n) => [n.key, n]));
  const svg = s('svg', { class: 'graph-svg', attrs: { viewBox: `0 0 ${layout.width} ${layout.height}`, role: 'group', 'aria-label': '' } });
  const edgesLayer = s('g', { class: 'graph-edges' });
  const spokesLayer = s('g', { class: 'graph-spokes' });
  const particleLayer = s('g', { class: 'graph-particles', attrs: { 'aria-hidden': 'true' } });
  const nodesLayer = s('g', { class: 'graph-nodes' });
  /** @type {Map<string, SVGPathElement>} */
  const edgePaths = new Map();
  /** @type {Map<string, SVGPathElement>} */
  const spokePaths = new Map();
  /** @type {Map<string, {group: SVGGElement, status: SVGTextElement, orbit: SVGGElement, rect: SVGRectElement}>} */
  const nodeEls = new Map();
  /** @type {Set<number>} */
  const frames = new Set();
  let phase = /** @type {typeof PHASES[number]|null} */ (null);
  const phaseEls = new Map();

  svg.append(s('defs', null,
    s('pattern', { attrs: { id: 'grid', width: '24', height: '24', patternUnits: 'userSpaceOnUse' } }, s('path', { class: 'graph-grid', attrs: { d: 'M 24 0 L 0 0 0 24' } })),
    s('marker', { attrs: { id: 'arrow', viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse' } },
      s('path', { class: 'graph-arrow', attrs: { d: 'M 0 0 L 10 5 L 0 10 z' } }))));
  svg.append(s('rect', { class: 'graph-bg', attrs: { x: '0', y: '0', width: String(layout.width), height: String(layout.height), fill: 'url(#grid)' } }));

  const half = { w: layout.nodeW / 2, h: layout.nodeH / 2 };
  for (const edge of layout.edges) {
    const a = nodeByKey.get(edge.from);
    const b = nodeByKey.get(edge.to);
    if (!a || !b) continue;
    let d;
    if (orientation === 'horizontal' && b.x > a.x) {
      const x1 = a.x + half.w; const x2 = b.x - half.w; const mid = (x1 + x2) / 2;
      d = `M ${x1} ${a.y} C ${mid} ${a.y}, ${mid} ${b.y}, ${x2} ${b.y}`;
    } else {
      const y1 = a.y + half.h; const y2 = b.y - half.h; const mid = (y1 + y2) / 2;
      d = `M ${a.x} ${y1} C ${a.x} ${mid}, ${b.x} ${mid}, ${b.x} ${y2}`;
    }
    const path = s('path', { class: 'graph-edge', attrs: { d, 'marker-end': 'url(#arrow)', 'data-edge': `${edge.from}>${edge.to}` } });
    edgePaths.set(`${edge.from}>${edge.to}`, path);
    edgesLayer.append(path);
  }
  for (const node of layout.nodes) {
    const d = `M ${layout.hub.x} ${layout.hub.y + 40} L ${node.x} ${node.y - half.h}`;
    const path = s('path', { class: 'graph-spoke', attrs: { d } });
    spokePaths.set(node.key, path);
    spokesLayer.append(path);
  }

  // Coordinator hub with the agent loop ring.
  const hub = s('g', { class: 'graph-hub', attrs: { transform: `translate(${layout.hub.x} ${layout.hub.y})` } });
  const ringR = 44;
  PHASES.forEach((name, index) => {
    const start = (index * Math.PI) / 2 - Math.PI / 2 + 0.08;
    const end = start + Math.PI / 2 - 0.16;
    const p1 = [Math.cos(start) * ringR, Math.sin(start) * ringR];
    const p2 = [Math.cos(end) * ringR, Math.sin(end) * ringR];
    const arc = s('path', { class: 'graph-phase', attrs: { d: `M ${p1[0]} ${p1[1]} A ${ringR} ${ringR} 0 0 1 ${p2[0]} ${p2[1]}`, 'data-phase': name } });
    const mid = start + (end - start) / 2;
    const right = Math.cos(mid) > 0;
    const label = s('text', { class: 'graph-phase-label', attrs: { x: String(Math.round(Math.cos(mid) * (ringR + 10))), y: String(Math.round(Math.sin(mid) * (ringR + 6) + 4)),
      'text-anchor': right ? 'start' : 'end' } }, t('graph.phase.' + name));
    phaseEls.set(name, { arc, label });
    hub.append(arc, label);
  });
  // The title sits beside the ring, not inside the core, so it never overflows.
  hub.append(s('circle', { class: 'graph-hub-core', attrs: { r: '32' } }),
    s('text', { class: 'graph-hub-glyph', attrs: { 'text-anchor': 'middle', y: '9', 'aria-hidden': 'true' } }, '✦'),
    s('text', { class: 'graph-hub-title', attrs: { 'text-anchor': 'start', x: String(ringR + 70), y: '-4' } }, options.coordinatorLabel || t('graph.coordinator')),
    s('text', { class: 'graph-hub-sub', attrs: { 'text-anchor': 'start', x: String(ringR + 70), y: '14' } }, t('graph.supervisor')));

  for (const node of layout.nodes) {
    const step = execution.steps.find((st) => st.key === node.key);
    const rect = s('rect', { class: 'graph-node-box', attrs: { x: String(-half.w), y: String(-half.h), width: String(layout.nodeW), height: String(layout.nodeH), rx: '6' } });
    const stripe = s('rect', { class: 'graph-node-stripe', attrs: { x: String(-half.w), y: String(-half.h), width: '4', height: String(layout.nodeH), rx: '2' } });
    const name = s('text', { class: 'graph-node-name', attrs: { x: String(-half.w + 14), y: '-5' } }, truncate(step?.agentName || node.key, 20));
    const status = s('text', { class: 'graph-node-status', attrs: { x: String(-half.w + 14), y: '17' } }, '');
    const orbit = s('g', { class: 'graph-orbit', attrs: { transform: `translate(${half.w - 16} ${-half.h + 14})` } });
    const halo = s('rect', { class: 'graph-node-halo', attrs: { x: String(-half.w - 6), y: String(-half.h - 6), width: String(layout.nodeW + 12), height: String(layout.nodeH + 12), rx: '10' } });
    const group = s('g', {
      class: 'graph-node', attrs: { transform: `translate(${node.x} ${node.y})`, tabindex: '0', role: 'button', 'data-node': node.key },
      on: {
        click: () => options.onSelect?.(node.key),
        keydown: (event) => {
          const key = /** @type {KeyboardEvent} */ (event).key;
          if (key === 'Enter' || key === ' ') { event.preventDefault(); options.onSelect?.(node.key); }
        },
      },
    }, halo, rect, stripe, name, status, orbit);
    nodeEls.set(node.key, { group, status, orbit, rect });
    nodesLayer.append(group);
  }
  svg.append(spokesLayer, edgesLayer, hub, nodesLayer, particleLayer);

  const liveText = h('p', { class: 'sr-only', attrs: { 'aria-live': 'polite' } });
  const legend = h('ul', { class: 'graph-legend', attrs: { 'aria-label': t('graph.legend') } },
    /** @type {StepStatus[]} */ (['pending', 'running', 'waiting_approval', 'completed', 'error', 'rejected']).map((st) =>
      h('li', { class: `legend-${st}` }, h('span', { attrs: { 'aria-hidden': 'true' } }, STATUS_GLYPH[st]), t('status.step.' + st))));
  const figure = h('figure', { class: `graph graph-${orientation}` }, svg, h('figcaption', { class: 'graph-caption' }, legend), liveText);

  /** @param {string} text @param {number} max */
  function truncate(text, max) {
    return text.length > max ? text.slice(0, max - 1) + '…' : text;
  }

  function summary() {
    const done = execution.steps.filter((st) => st.status === 'completed').length;
    const running = execution.steps.filter((st) => st.status === 'running').length;
    return t('graph.summary', { name: execution.workflowName, done, total: execution.steps.length, running, status: t('status.execution.' + execution.status) });
  }

  function paint() {
    for (const step of execution.steps) {
      const el = nodeEls.get(step.key);
      if (!el) continue;
      el.group.setAttribute('data-status', step.status);
      // A tool of a stopped or finished step never orbits: no event, no movement.
      const running = step.status === 'running' ? step.tools.filter((tool) => tool.status === 'running').length : 0;
      const tools = step.tools.length ? ` · ${t('graph.tools', { n: step.tools.length })}` : '';
      el.status.textContent = `${STATUS_GLYPH[step.status]} ${t('status.step.' + step.status)}${tools}`;
      el.group.setAttribute('aria-label', `${step.agentName}: ${t('status.step.' + step.status)}${tools}`);
      mount(el.orbit, Array.from({ length: Math.min(running, 3) }, (_, i) => s('circle', { class: 'graph-orbit-dot', attrs: { r: '3.5', cx: String(-i * 10), cy: '0' } })));
      for (const dep of step.dependencies) {
        const path = edgePaths.get(`${dep}>${step.key}`);
        if (path) path.setAttribute('data-state', step.status === 'running' ? 'active' : step.status === 'completed' ? 'done' : 'idle');
      }
      spokePaths.get(step.key)?.setAttribute('data-state', step.status === 'running' || step.status === 'waiting_approval' ? 'active' : 'idle');
    }
    svg.setAttribute('data-run-status', execution.status);
    svg.setAttribute('aria-label', summary());
    for (const [name, els] of phaseEls) {
      els.arc.setAttribute('data-active', String(name === phase));
      els.label.setAttribute('data-active', String(name === phase));
    }
  }

  /**
   * Move a particle along a path.
   * @param {SVGPathElement|undefined} path
   * @param {'forward'|'backward'} direction
   * @param {string} kind
   */
  function particle(path, direction, kind) {
    if (!path || reduced() || typeof path.getTotalLength !== 'function') return;
    const length = path.getTotalLength();
    if (!length) return;
    const dot = s('circle', { class: `graph-particle particle-${kind}`, attrs: { r: kind === 'artifact' ? '5' : '3.5' } });
    particleLayer.append(dot);
    const duration = 900;
    const started = performance.now();
    /** @param {number} now */
    const frame = (now) => {
      const progress = Math.min(1, (now - started) / duration);
      const eased = progress < 0.5 ? 2 * progress * progress : 1 - (-2 * progress + 2) ** 2 / 2;
      const point = path.getPointAtLength((direction === 'forward' ? eased : 1 - eased) * length);
      dot.setAttribute('cx', String(point.x));
      dot.setAttribute('cy', String(point.y));
      if (progress < 1) {
        const id = requestAnimationFrame(frame);
        frames.add(id);
      } else {
        dot.remove();
      }
    };
    frames.add(requestAnimationFrame(frame));
  }

  /** @param {string} key */
  function pulse(key) {
    const el = nodeEls.get(key);
    if (!el || reduced()) return;
    el.group.classList.remove('pulse');
    // Restart the CSS animation on the same element.
    void el.group.getBoundingClientRect();
    el.group.classList.add('pulse');
  }

  paint();
  return {
    el: figure,
    /** @param {Execution} next */
    update(next) {
      execution = next;
      paint();
    },
    /** @param {RunEvent} event */
    onEvent(event) {
      const key = event.stepKey;
      const step = key ? execution.steps.find((st) => st.key === key) : undefined;
      switch (event.kind) {
        case 'run_started': case 'step_approved': phase = 'plan'; break;
        case 'step_started':
          phase = 'plan';
          if (key) {
            particle(spokePaths.get(key), 'forward', 'assign');
            for (const dep of step?.dependencies || []) particle(edgePaths.get(`${dep}>${key}`), 'forward', 'artifact');
            pulse(key);
            liveText.textContent = t('graph.announce.started', { name: step?.agentName || key });
          }
          break;
        case 'tool_started': phase = 'ejecutar'; if (key) pulse(key); break;
        case 'tool_finished': case 'model_metrics': phase = 'observar'; break;
        case 'step_completed':
          phase = 'reflexionar';
          if (key) {
            particle(spokePaths.get(key), 'backward', 'report');
            liveText.textContent = t('graph.announce.completed', { name: step?.agentName || key });
          }
          break;
        case 'step_error': phase = 'reflexionar'; if (key) liveText.textContent = t('graph.announce.error', { name: step?.agentName || key }); break;
        case 'step_approval_requested': if (key) liveText.textContent = t('graph.announce.approval', { name: step?.agentName || key }); break;
        case 'run_completed': case 'run_error': case 'run_interrupted': phase = null; liveText.textContent = summary(); break;
        default: break;
      }
      paint();
    },
    destroy() {
      for (const id of frames) cancelAnimationFrame(id);
      frames.clear();
    },
  };
}
