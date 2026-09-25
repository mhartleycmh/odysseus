// Live view of one run: snapshot + event stream in one place, so every view
// gets the same behaviour. It never double counts a replayed backlog, closes
// its stream when disposed (even if disposal happens before it opened), and in
// live mode fetches the artifact of a completed step, because the real
// step_completed event carries only its id.
import { applyEvent, finalAnswerOf, resetCounters } from './run-state.js';

/** @typedef {import('../types.js').DataSource} DataSource */
/** @typedef {import('../types.js').Execution} Execution */
/** @typedef {import('../types.js').RunEvent} RunEvent */

/**
 * @typedef {Object} RunFeed
 * @property {() => Execution} state
 * @property {() => RunEvent[]} events
 * @property {() => void} dispose
 * @property {() => boolean} disposed
 */

/**
 * @param {DataSource} source
 * @param {Execution} snapshot
 * @param {{onChange: (execution: Execution, event: RunEvent|null) => void, onState?: (state: 'open'|'reconnecting'|'closed') => void}} handlers
 * @returns {RunFeed}
 */
export function openRunFeed(source, snapshot, handlers) {
  let execution = resetCounters(snapshot);
  /** @type {RunEvent[]} */
  const events = [];
  let closed = false;

  /** Merge artifacts fetched after a step completed without content. */
  async function refreshArtifacts() {
    try {
      const fresh = await source.getExecution(snapshot.id);
      if (closed) return;
      const known = new Set(execution.artifacts.map((a) => a.id));
      const added = fresh.artifacts.filter((a) => !known.has(a.id));
      if (!added.length) return;
      execution = { ...execution, artifacts: [...execution.artifacts, ...added] };
      if (execution.status === 'completed') execution = { ...execution, finalAnswer: finalAnswerOf(execution) };
      handlers.onChange(execution, null);
    } catch {
      // The next event or a manual reload shows the artifact.
    }
  }

  const stream = source.openRunStream(snapshot.id, {
    onEvent(event) {
      if (closed) return;
      events.push(event);
      execution = applyEvent(execution, event);
      handlers.onChange(execution, event);
      const artifactId = event.payload?.artifact_id;
      if (event.kind === 'step_completed' && typeof event.payload?.content !== 'string'
          && typeof artifactId === 'string' && !execution.artifacts.some((a) => a.id === artifactId)) {
        refreshArtifacts();
      }
    },
    onState(state) {
      if (!closed) handlers.onState?.(state);
    },
  });
  return {
    state: () => execution,
    events: () => events,
    dispose() {
      if (closed) return;
      closed = true;
      stream.close();
    },
    disposed: () => closed,
  };
}
