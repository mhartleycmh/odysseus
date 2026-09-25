// The only module that calls fetch: timeouts, bounded retries for idempotent
// reads, typed errors and per-call latency for the observability view.
import { log } from '../core/log.js';
import { translateServerMessage } from '../i18n/server-es.js';

/** @typedef {'auth'|'forbidden'|'not_found'|'conflict'|'validation'|'server'|'network'|'timeout'|'not_supported'|'simulated'} ErrorKind */

export class HttpError extends Error {
  /**
   * @param {ErrorKind} kind
   * @param {string} message
   * @param {number} [status]
   */
  constructor(kind, message, status = 0) {
    super(message);
    this.name = 'HttpError';
    this.kind = kind;
    this.status = status;
  }
}

/** @param {number} status @returns {ErrorKind} */
export function kindForStatus(status) {
  if (status === 401) return 'auth';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 400 || status === 413 || status === 422) return 'validation';
  return 'server';
}

/**
 * @typedef {Object} CallMetric
 * @property {string} method
 * @property {string} path
 * @property {number} status
 * @property {number} ms
 * @property {string} at
 * @property {number} attempt
 */
/** @type {CallMetric[]} */
const metrics = [];
export function callMetrics() {
  return metrics.slice();
}

/**
 * @typedef {Object} RequestOptions
 * @property {string} [method]
 * @property {unknown} [json]
 * @property {Record<string, string>} [form]
 * @property {number} [timeoutMs]
 * @property {number} [retries]
 * @property {typeof globalThis.fetch} [fetchImpl]
 * @property {(ms: number) => Promise<void>} [sleep]
 */

/** @param {number} ms */
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * @param {Response} response
 * @returns {Promise<string>}
 */
async function detailOf(response) {
  try {
    const body = await response.json();
    if (body && typeof body === 'object') {
      const detail = /** @type {Record<string, unknown>} */ (body).detail ?? /** @type {Record<string, unknown>} */ (body).error;
      if (typeof detail === 'string') return translateServerMessage(detail);
      if (Array.isArray(detail)) return detail.map((d) => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : String(d))).join('; ');
    }
  } catch {
    // Non-JSON error body: fall back to the status text.
  }
  return response.statusText || `HTTP ${response.status}`;
}

/**
 * Perform a same-origin request and return the parsed JSON body.
 * @param {string} path
 * @param {RequestOptions} [options]
 * @returns {Promise<unknown>}
 */
export async function request(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const retries = options.retries ?? (method === 'GET' ? 2 : 0);
  const timeoutMs = options.timeoutMs ?? 15000;
  const fetchImpl = options.fetchImpl || globalThis.fetch.bind(globalThis);
  const sleep = options.sleep || wait;
  /** @type {RequestInit} */
  const init = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
  if (options.json !== undefined) {
    init.headers = { ...init.headers, 'Content-Type': 'application/json' };
    init.body = JSON.stringify(options.json);
  } else if (options.form) {
    const body = new FormData();
    for (const [key, value] of Object.entries(options.form)) body.append(key, value);
    init.body = body;
  }
  /** @type {HttpError|null} */
  let lastError = null;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    if (attempt > 0) await sleep(300 * 2 ** (attempt - 1));
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const started = Date.now();
    try {
      const response = await fetchImpl(path, { ...init, signal: controller.signal });
      metrics.push({ method, path, status: response.status, ms: Date.now() - started, at: new Date().toISOString(), attempt });
      if (response.ok) {
        if (response.status === 204) return null;
        return await response.json();
      }
      const error = new HttpError(kindForStatus(response.status), await detailOf(response), response.status);
      if (response.status < 500) throw error;
      lastError = error;
    } catch (caught) {
      if (caught instanceof HttpError && caught.status > 0 && caught.status < 500) throw caught;
      if (caught instanceof HttpError) {
        lastError = caught;
      } else {
        const aborted = caught instanceof Error && caught.name === 'AbortError';
        metrics.push({ method, path, status: 0, ms: Date.now() - started, at: new Date().toISOString(), attempt });
        lastError = aborted
          ? new HttpError('timeout', `Sin respuesta en ${Math.round(timeoutMs / 1000)} s`)
          : new HttpError('network', 'No se pudo conectar con el servidor');
      }
    } finally {
      clearTimeout(timer);
    }
    if (metrics.length > 500) metrics.splice(0, metrics.length - 500);
  }
  log('warn', 'http', 'request failed', { method, path, kind: lastError?.kind });
  throw lastError || new HttpError('network', 'Solicitud fallida');
}
