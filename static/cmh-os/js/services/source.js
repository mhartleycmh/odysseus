// Data source selection (ADR-003): live when the CMH API answers for this
// session, demo otherwise, always with the reason visible to the user.
import { request as defaultRequest, HttpError } from './http.js';
import { createDemoSource } from './demo.js';
import { createLiveSource } from './live.js';
import { expectObject, optStr } from '../core/validate.js';

/** @typedef {import('../types.js').DataSource} DataSource */
/** @typedef {'forzado'|'sin_sesion'|'sin_permiso'|'sin_servidor'|null} DemoReason */

/**
 * @typedef {Object} PublicConfig
 * @property {boolean} uiEnabled
 * @property {'auto'|'demo'} defaultMode
 */

/**
 * @param {(path: string, options?: import('./http.js').RequestOptions) => Promise<unknown>} request
 * @returns {Promise<PublicConfig>}
 */
export async function loadConfig(request) {
  try {
    const body = expectObject(await request('/api/cmh/os/config', { retries: 0, timeoutMs: 4000 }), 'config');
    return { uiEnabled: body.ui_enabled !== false, defaultMode: optStr(body, 'default_mode') === 'demo' ? 'demo' : 'auto' };
  } catch {
    return { uiEnabled: true, defaultMode: 'auto' };
  }
}

/**
 * @param {Object} input
 * @param {'auto'|'demo'} input.preference user preference from Settings
 * @param {URLSearchParams} input.query page query string
 * @param {PublicConfig} input.config
 * @param {(path: string, options?: import('./http.js').RequestOptions) => Promise<unknown>} input.request
 * @returns {Promise<{mode: 'real'|'demo', reason: DemoReason}>}
 */
export async function detectMode({ preference, query, config, request }) {
  if (query.get('modo') === 'demo' || preference === 'demo' || config.defaultMode === 'demo') return { mode: 'demo', reason: 'forzado' };
  try {
    await request('/api/cmh/agents', { retries: 0, timeoutMs: 5000 });
    return { mode: 'real', reason: null };
  } catch (error) {
    if (error instanceof HttpError && error.kind === 'auth') return { mode: 'demo', reason: 'sin_sesion' };
    if (error instanceof HttpError && error.kind === 'forbidden') return { mode: 'demo', reason: 'sin_permiso' };
    return { mode: 'demo', reason: 'sin_servidor' };
  }
}

/**
 * @param {Object} options
 * @param {'real'|'demo'} options.mode
 * @param {() => boolean} options.failures
 * @param {number} [options.speed]
 * @param {(path: string, options?: import('./http.js').RequestOptions) => Promise<unknown>} [options.request]
 * @returns {DataSource}
 */
export function createSource({ mode, failures, speed, request = defaultRequest }) {
  const demo = createDemoSource({ failures, speed });
  return mode === 'real' ? createLiveSource({ demo, request }) : demo;
}
