// Sortable data table; rows can be opened with mouse, Enter or Space.
import { h, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';

/** @typedef {import('../core/dom.js').Children} Children */

/**
 * @template R
 * @typedef {Object} Column
 * @property {string} key
 * @property {string} label
 * @property {(row: R) => Children} render
 * @property {(row: R) => string|number} [sort]
 * @property {boolean} [num]
 */

/**
 * @template R
 * @typedef {Object} TableOptions
 * @property {Column<R>[]} columns
 * @property {R[]} rows
 * @property {(row: R) => string} rowKey
 * @property {(row: R) => void} [onOpen]
 * @property {(row: R) => string} [rowLabel] accessible name for an openable row
 * @property {string} caption
 * @property {string} [emptyText]
 * @property {{key: string, dir: 'asc'|'desc'}} [initialSort]
 */

/**
 * @template R
 * @param {TableOptions<R>} options
 * @returns {HTMLElement}
 */
export function dataTable(options) {
  let sort = options.initialSort || null;
  const wrap = h('div', { class: 'table-wrap' });

  function sortedRows() {
    if (!sort) return options.rows;
    const column = options.columns.find((c) => c.key === sort?.key);
    if (!column?.sort) return options.rows;
    const getter = column.sort;
    const factor = sort.dir === 'asc' ? 1 : -1;
    return [...options.rows].sort((a, b) => {
      const x = getter(a);
      const y = getter(b);
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'es')) * factor;
    });
  }

  function render() {
    const head = h('tr', null, options.columns.map((column) => {
      const active = sort?.key === column.key;
      const ariaSort = active ? (sort?.dir === 'asc' ? 'ascending' : 'descending') : column.sort ? 'none' : null;
      const content = column.sort
        ? h('button', { attrs: { type: 'button' }, on: { click: () => {
            sort = { key: column.key, dir: active && sort?.dir === 'asc' ? 'desc' : 'asc' };
            render();
            const button = /** @type {HTMLButtonElement|null} */ (wrap.querySelector(`th[data-key="${column.key}"] button`));
            button?.focus();
          } } }, column.label, h('span', { attrs: { 'aria-hidden': 'true' } }, active ? (sort?.dir === 'asc' ? '▲' : '▼') : '↕'))
        : column.label;
      return h('th', { class: column.num ? 'num' : '', attrs: { scope: 'col', 'aria-sort': ariaSort, 'data-key': column.key } }, content);
    }));
    const rows = sortedRows();
    const body = rows.length
      ? rows.map((row) => {
          const open = options.onOpen;
          const tr = h('tr', {
            class: open ? 'clickable' : '',
            attrs: { tabindex: open ? '0' : null, 'data-row': options.rowKey(row), 'aria-label': open && options.rowLabel ? options.rowLabel(row) : null },
            on: open ? {
              click: () => open(row),
              keydown: (event) => {
                const key = /** @type {KeyboardEvent} */ (event).key;
                if (key === 'Enter' || key === ' ') { event.preventDefault(); open(row); }
              },
            } : {},
          }, options.columns.map((column) => h('td', { class: column.num ? 'num' : '', attrs: { 'data-label': column.label } }, column.render(row))));
          return tr;
        })
      : [h('tr', null, h('td', { class: 'table-empty', attrs: { colspan: String(options.columns.length) } }, options.emptyText || t('state.empty')))];
    mount(wrap, h('table', { class: 'table stack-mobile' },
      h('caption', { class: 'sr-only' }, options.caption), h('thead', null, head), h('tbody', null, body)));
  }

  render();
  return wrap;
}
