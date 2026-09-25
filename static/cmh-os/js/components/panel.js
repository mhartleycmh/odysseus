// Panel, KPI card and contextual help.
import { h, mount, uid } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { originBadge } from './badge.js';

/** @typedef {import('../core/dom.js').Children} Children */

/**
 * @typedef {Object} PanelOptions
 * @property {string} title
 * @property {import('../types.js').Origin|null} [origin]
 * @property {boolean} [partial] demo data inside live mode
 * @property {Children} [actions]
 * @property {string} [help]
 * @property {Children} [body]
 * @property {Children} [footer]
 * @property {'h2'|'h3'} [level]
 * @property {boolean} [flush]
 * @property {string} [id]
 */

/** @param {PanelOptions} options */
export function panel(options) {
  const headingId = uid('panel');
  const heading = h(options.level || 'h2', { attrs: { id: headingId } }, options.title);
  return h('section', { class: 'panel', attrs: { 'aria-labelledby': headingId, id: options.id } },
    h('div', { class: 'panel-header' },
      h('div', { class: 'panel-title' }, heading, options.help ? helpTip(options.help) : null,
        options.origin ? originBadge(options.origin, { partial: options.partial }) : null),
      options.actions ? h('div', { class: 'row' }, options.actions) : null),
    h('div', { class: options.flush ? 'panel-body flush' : 'panel-body' }, options.body),
    options.footer ? h('div', { class: 'panel-footer' }, options.footer) : null);
}

/**
 * @typedef {Object} KpiOptions
 * @property {string} label
 * @property {string} value
 * @property {string} [context]
 * @property {{text: string, tone: import('../types.js').Tone}} [delta]
 */

/** @param {KpiOptions} options */
export function kpi(options) {
  return h('div', { class: 'kpi', attrs: { role: 'group', 'aria-label': options.label } },
    h('span', { class: 'kpi-label' }, options.label),
    h('span', { class: 'kpi-value' }, options.value),
    options.context ? h('span', { class: 'kpi-context' }, options.context) : null,
    options.delta ? h('span', { class: `kpi-delta tone-text-${options.delta.tone}` }, options.delta.text) : null);
}

/** @param {string} text */
export function helpTip(text) {
  const id = uid('tip');
  return h('span', { class: 'tip' },
    h('button', { class: 'tip-trigger', attrs: { type: 'button', 'aria-label': t('common.help'), 'aria-describedby': id } }, '?'),
    h('span', { class: 'tip-bubble', attrs: { role: 'tooltip', id } }, text));
}

/**
 * @param {string} title
 * @param {string} lede
 * @param {Children} [actions]
 */
export function viewHeader(title, lede, actions) {
  return h('div', { class: 'view-header' },
    h('div', null, h('h1', { attrs: { tabindex: '-1' } }, title), h('p', { class: 'lede' }, lede)),
    actions ? h('div', { class: 'actions' }, actions) : null);
}

/**
 * A header whose h1 exists from the first frame and is updated in place, so a
 * detail view never has zero h1 while loading and focus can land on it.
 * @param {string} title
 * @param {string} lede
 */
export function mutableHeader(title, lede) {
  const heading = h('h1', { attrs: { tabindex: '-1' } }, title);
  const ledeEl = h('p', { class: 'lede' }, lede);
  const actions = h('div', { class: 'actions' });
  const crumb = h('div');
  const el = h('div', { class: 'stack' }, crumb, h('div', { class: 'view-header' }, h('div', null, heading, ledeEl), actions));
  return {
    el,
    /** @param {string} value */
    setTitle(value) { heading.textContent = value; },
    /** @param {string} value */
    setLede(value) { ledeEl.textContent = value; },
    /** @param {Children} nodes */
    setActions(nodes) { mount(actions, nodes); },
    /** @param {Children} nodes */
    setCrumb(nodes) { mount(crumb, nodes); },
  };
}

/**
 * @param {[string, Children][]} rows
 */
export function definitionList(rows) {
  return h('dl', { class: 'dl' }, rows.flatMap(([term, value]) => [h('dt', null, term), h('dd', null, value)]));
}
