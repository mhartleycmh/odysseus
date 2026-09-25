// Loading, empty, error and ready states, implemented once (ARCHITECTURE §4).
import { h, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { log } from '../core/log.js';

/** @typedef {import('../core/dom.js').Children} Children */

/** @param {number} [lines] */
export function skeleton(lines = 4) {
  const widths = ['w-80', 'w-60', 'w-40', 'w-80', 'w-60'];
  return h('div', { class: 'skeleton', attrs: { 'aria-busy': 'true', 'aria-live': 'polite' } },
    h('span', { class: 'sr-only' }, t('state.loading')),
    Array.from({ length: lines }, (_, i) => h('div', { class: `skeleton-line ${widths[i % widths.length]}` })));
}

/**
 * @param {{title: string, text?: string, action?: Children, glyph?: string}} options
 */
export function emptyState(options) {
  return h('div', { class: 'state', attrs: { role: 'status' } },
    h('span', { class: 'state-glyph', attrs: { 'aria-hidden': 'true' } }, options.glyph || '○'),
    h('p', { class: 'state-title' }, options.title),
    options.text ? h('p', null, options.text) : null,
    options.action || null);
}

/** @param {unknown} error */
export function errorMessage(error) {
  if (error instanceof Error) return error.message;
  return String(error);
}

/**
 * @param {{error: unknown, onRetry?: () => void, title?: string}} options
 */
export function errorState(options) {
  const kind = options.error && typeof options.error === 'object' && 'kind' in options.error ? String(options.error.kind) : 'desconocido';
  return h('div', { class: 'alert tone-risk', attrs: { role: 'alert' } },
    h('span', { class: 'alert-glyph', attrs: { 'aria-hidden': 'true' } }, '■'),
    h('div', { class: 'alert-body' },
      h('span', { class: 'alert-title' }, options.title || t('state.errorTitle')),
      h('span', null, errorMessage(options.error)),
      h('details', null, h('summary', null, t('state.technical')), h('code', null, `tipo: ${kind}`)),
      options.onRetry ? h('div', null, h('button', { class: 'btn btn-sm', attrs: { type: 'button', 'data-action': 'retry' }, on: { click: options.onRetry } }, t('common.retry'))) : null));
}

/**
 * @param {import('../types.js').Tone} tone
 * @param {string} title
 * @param {Children} [body]
 */
export function alertBox(tone, title, body) {
  /** @type {Record<import('../types.js').Tone, string>} */
  const glyph = { ok: '●', warn: '▲', risk: '■', idle: '○', live: '◆' };
  return h('div', { class: `alert tone-${tone}`, attrs: { role: tone === 'risk' ? 'alert' : 'status' } },
    h('span', { class: 'alert-glyph', attrs: { 'aria-hidden': 'true' } }, glyph[tone]),
    h('div', { class: 'alert-body' }, h('span', { class: 'alert-title' }, title), body || null));
}

/**
 * Load data into a container with the four standard states.
 * @template T
 * @param {Element} container
 * @param {() => Promise<T>} loader
 * @param {(data: T) => Children} render
 * @param {{isEmpty?: (data: T) => boolean, empty?: () => Children, lines?: number}} [options]
 * @returns {{reload: () => Promise<void>, dispose: () => void}}
 */
export function asyncView(container, loader, render, options = {}) {
  let token = 0;
  let disposed = false;
  const reload = async () => {
    if (disposed) return;
    const mine = ++token;
    mount(container, skeleton(options.lines));
    try {
      const data = await loader();
      // A view left before its data arrived must not render (or open streams).
      if (mine !== token || disposed) return;
      if (options.isEmpty && options.isEmpty(data)) mount(container, options.empty ? options.empty() : emptyState({ title: t('state.empty') }));
      else mount(container, render(data));
    } catch (error) {
      if (mine !== token || disposed) return;
      log('warn', 'view', 'load failed', { message: errorMessage(error) });
      mount(container, errorState({ error, onRetry: () => { reload(); } }));
    }
  };
  reload();
  return { reload, dispose: () => { disposed = true; token += 1; } };
}
