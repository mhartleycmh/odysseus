// Orquestación: coordinator and workers moving with real (or simulated) run
// events, global state, selected step detail and live event feed.
import { h, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { formatDuration, formatNumber, formatUsd, shortId } from '../core/format.js';
import { panel, viewHeader, definitionList } from '../components/panel.js';
import { asyncView, alertBox, emptyState, errorMessage } from '../components/states.js';
import { executionBadge, stepBadge, chip } from '../components/badge.js';
import { createGraph } from '../components/graph.js';
import { timeline } from '../components/timeline.js';
import { toast } from '../components/toast.js';
import { openExecutionForm } from './executions.js';
import { isFresh, resetCounters } from '../services/run-state.js';
import { openRunFeed } from '../services/run-feed.js';

/** @typedef {import('../types.js').AppContext} AppContext */
/** @typedef {import('../types.js').Execution} Execution */
/** @typedef {import('../types.js').RunEvent} RunEvent */
/** @typedef {import('../core/router.js').RouteMatch} RouteMatch */

/**
 * @param {AppContext} ctx
 * @param {RouteMatch} match
 */
export function render(ctx, match) {
  const host = h('div', { class: 'stack' });
  const newButton = h('button', { class: 'btn btn-primary', attrs: { type: 'button', 'data-action': 'new-execution' },
    on: { click: () => openExecutionForm(ctx, null).catch((e) => toast(errorMessage(e), 'risk')) } }, t('executions.new'));
  const el = h('section', { class: 'view', attrs: { 'data-view': 'orchestration' } }, viewHeader(t('orchestration.title'), t('orchestration.lede'), newButton), host);
  /** @type {(() => void)[]} */
  const cleanups = [];

  const outer = asyncView(host, () => ctx.source.listExecutions(), (executions) => {
    const chosen = match.params.id || executions.find((e) => e.status === 'running')?.id || executions.find((e) => e.status === 'waiting_approval')?.id || executions[0]?.id;
    const select = h('select', { class: 'select', attrs: { id: 'orch-run', 'aria-label': t('orchestration.select') } },
      executions.map((e) => h('option', { attrs: { value: e.id } }, `${shortId(e.id)} · ${e.workflowName} · ${t('status.execution.' + e.status)}`)));
    select.value = chosen || '';
    select.addEventListener('change', () => ctx.navigate(`#/orquestacion/${encodeURIComponent(select.value)}`));
    const stage = h('div', { class: 'stack' });
    mountRun(chosen || '', stage);
    return [
      h('div', { class: 'toolbar' }, h('div', { class: 'field grow' }, h('label', { class: 'field-label', attrs: { for: 'orch-run' } }, t('orchestration.select')), select)),
      stage,
    ];
  }, { isEmpty: (list) => list.length === 0, empty: () => emptyState({ title: t('orchestration.empty'), text: t('orchestration.emptyText'), action: h('button', { class: 'btn btn-primary', attrs: { type: 'button' }, on: { click: () => newButton.click() } }, t('executions.new')) }) });

  /** @param {string} id @param {HTMLElement} stage */
  function mountRun(id, stage) {
    const inner = asyncView(stage, () => ctx.source.getExecution(id), (snapshot) => {
      let execution = resetCounters(snapshot);
      let selected = execution.steps.find((s) => s.status === 'running')?.key || execution.steps[0]?.key || '';
      const vertical = window.innerWidth < 640;
      const graph = createGraph({ execution, orientation: vertical ? 'vertical' : 'horizontal', reducedMotion: ctx.reducedMotion,
                                  onSelect: (key) => { selected = key; paintSide(); } });
      const globalBox = h('div', { class: 'stack', attrs: { 'data-block': 'global' } });
      const stepBox = h('div', { class: 'stack', attrs: { 'data-block': 'step' } });
      const feed = h('div', { class: 'timeline-host' });
      const approvalBox = h('div');
      const streamState = h('span', { class: 'badge tone-idle', attrs: { 'aria-live': 'polite', 'data-stream': '' } }, t('executions.stream.closed'));

      const paintSide = () => {
        const done = execution.steps.filter((s) => s.status === 'completed').length;
        mount(globalBox, h('div', { class: 'row' }, executionBadge(execution.status), streamState),
          h('div', { class: 'meter', attrs: { role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(execution.steps.length), 'aria-valuenow': String(done), 'aria-label': t('orchestration.progress') } },
            h('span', { attrs: { style: `width:${execution.steps.length ? ((done / execution.steps.length) * 100).toFixed(1) : 0}%` } })),
          definitionList([
            [t('orchestration.progress'), t('orchestration.progressValue', { done, total: execution.steps.length })],
            [t('executions.usage.tokens'), formatNumber(execution.usage.tokensIn + execution.usage.tokensOut)],
            [t('executions.usage.cost'), formatUsd(execution.usage.costUsd)],
            [t('executions.usage.iterations'), formatNumber(execution.usage.iterations)],
            [t('executions.usage.elapsed'), formatDuration(execution.usage.elapsedSeconds)],
          ]),
          h('div', { class: 'row' },
            h('a', { class: 'btn btn-sm', attrs: { href: `#/ejecuciones/${encodeURIComponent(execution.id)}` } }, t('orchestration.openDetail')),
            ['running', 'pending', 'waiting_approval'].includes(execution.status)
              ? h('button', { class: 'btn btn-sm btn-danger', attrs: { type: 'button', 'data-action': 'cancel-execution' }, on: { click: () => { ctx.confirmStop(execution.id); } } }, t('executions.cancel')) : null));
        const step = execution.steps.find((s) => s.key === selected);
        const artifact = execution.artifacts.find((a) => a.stepKey === selected);
        mount(stepBox, step ? [
          h('div', { class: 'row-between' }, h('strong', null, step.agentName), stepBadge(step.status)),
          definitionList([
            [t('executions.step.key'), h('code', null, step.key)],
            [t('executions.step.model'), step.model || '—'],
            [t('orchestration.dependsOn'), step.dependencies.length ? step.dependencies.join(', ') : t('orchestration.noDeps')],
            [t('executions.col.tokens'), formatNumber(step.tokensIn + step.tokensOut)],
          ]),
          step.tools.length ? h('div', { class: 'chip-list', attrs: { 'aria-label': t('executions.step.tools') } },
            step.tools.map((c) => chip(`${c.status === 'error' ? '■' : c.status === 'running' ? '◆' : '●'} ${c.tool}${c.durationSeconds !== null ? ' · ' + formatDuration(c.durationSeconds) : ''}`))) : h('p', { class: 'small muted' }, t('orchestration.noTools')),
          step.error ? alertBox('risk', t('executions.step.error'), h('span', null, step.error)) : null,
          artifact ? h('details', { class: 'artifact' }, h('summary', null, t('orchestration.artifact')), h('pre', { class: 'code' }, artifact.content)) : null,
        ] : emptyState({ title: t('orchestration.selectStep') }));
        const events = runFeed ? runFeed.events() : [];
        mount(feed, events.length ? timeline(events, { limit: 14 }) : emptyState({ title: t('executions.noEvents') }));
        const waiting = execution.steps.find((s) => s.status === 'waiting_approval');
        mount(approvalBox, waiting ? alertBox('warn', t('orchestration.waiting', { name: waiting.agentName }),
          h('a', { class: 'btn btn-sm btn-primary', attrs: { href: `#/aprobaciones?id=${encodeURIComponent(`apr-${execution.id}-${waiting.key}`)}` } }, t('executions.answer.review'))) : null);
      };

      /** @type {import('../services/run-feed.js').RunFeed|null} */
      let runFeed = null;
      paintSide();
      let scheduled = false;
      runFeed = openRunFeed(ctx.source, snapshot, {
        onChange(next, event) {
          execution = next;
          graph.update(execution);
          if (event && isFresh(event)) {
            graph.onEvent(event);
            if (event.kind === 'step_started' && event.stepKey) selected = event.stepKey;
          }
          if (!scheduled) {
            scheduled = true;
            requestAnimationFrame(() => { scheduled = false; if (!runFeed?.disposed()) paintSide(); });
          }
          if (event && (event.kind === 'step_approval_requested' || event.kind === 'step_approved')) ctx.refreshCounts();
        },
        onState(state) {
          streamState.textContent = t('executions.stream.' + state);
          streamState.className = `badge ${state === 'open' ? 'tone-live' : state === 'reconnecting' ? 'tone-warn' : 'tone-idle'}`;
        },
      });
      const opened = runFeed;
      cleanups.push(() => { opened.dispose(); graph.destroy(); });
      return [
        approvalBox,
        h('div', { class: 'orch-layout' },
          h('div', { class: 'orch-canvas panel', attrs: { 'aria-label': t('orchestration.canvas') } },
            h('div', { class: 'orch-canvas-head' }, h('h2', null, execution.workflowName), h('span', { class: 'mono small' }, shortId(execution.id))),
            graph.el),
          h('div', { class: 'stack orch-side' },
            panel({ title: t('orchestration.global'), origin: execution.origin, body: globalBox, level: 'h2' }),
            panel({ title: t('orchestration.stepTitle'), origin: execution.origin, body: stepBox, level: 'h2' }))),
        panel({ title: t('orchestration.feed'), origin: execution.origin, help: t('orchestration.feedHelp'), body: feed }),
      ];
    }, { lines: 8 });
    cleanups.push(() => inner.dispose());
  }
  cleanups.push(() => outer.dispose());

  return { el, title: t('orchestration.title'), destroy: () => cleanups.forEach((fn) => fn()) };
}
