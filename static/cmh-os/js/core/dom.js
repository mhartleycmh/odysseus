// DOM construction that only ever assigns text. Components never parse HTML.

/** @typedef {string|number|Node|null|undefined|false} Child */
/** @typedef {Child|Child[]} Children */
/**
 * @typedef {Object} Props
 * @property {string} [class]
 * @property {Record<string, string|number|boolean|null|undefined>} [attrs]
 * @property {Record<string, (event: Event) => void>} [on]
 * @property {Record<string, string>} [dataset]
 * @property {(el: Element) => void} [ref]
 */

const URL_ATTRS = new Set(['href', 'src', 'action', 'formaction', 'xlink:href']);
const SAFE_URL = /^(#|\/(?!\/)|\.{0,2}\/|https?:|mailto:)/i;

/**
 * Reject javascript:, data: and protocol-relative URLs in link-like attributes.
 * @param {string} name
 * @param {string} value
 * @returns {string|null}
 */
export function safeAttr(name, value) {
  if (!URL_ATTRS.has(name.toLowerCase())) return value;
  const trimmed = value.trim();
  return SAFE_URL.test(trimmed) ? trimmed : null;
}

/**
 * @param {Element} el
 * @param {Props} props
 */
function applyProps(el, props) {
  if (props.class) el.setAttribute('class', props.class);
  for (const [name, value] of Object.entries(props.attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    const text = value === true ? '' : String(value);
    const safe = safeAttr(name, text);
    if (safe !== null) el.setAttribute(name, safe);
  }
  for (const [name, handler] of Object.entries(props.on || {})) el.addEventListener(name, handler);
  if (props.dataset && el instanceof HTMLElement) Object.assign(el.dataset, props.dataset);
  if (props.ref) props.ref(el);
}

/**
 * @param {Element} el
 * @param {Children[]} children
 */
function appendChildren(el, children) {
  for (const child of children.flat(3)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

/**
 * Create an HTML element.
 * @template {keyof HTMLElementTagNameMap} K
 * @param {K} tag
 * @param {Props|null} [props]
 * @param {...Children} children
 * @returns {HTMLElementTagNameMap[K]}
 */
export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  if (props) applyProps(el, props);
  appendChildren(el, children);
  return el;
}

const SVG_NS = 'http://www.w3.org/2000/svg';
/**
 * Create an SVG element.
 * @template {keyof SVGElementTagNameMap} K
 * @param {K} tag
 * @param {Props|null} [props]
 * @param {...Children} children
 * @returns {SVGElementTagNameMap[K]}
 */
export function s(tag, props, ...children) {
  const el = /** @type {SVGElementTagNameMap[K]} */ (document.createElementNS(SVG_NS, tag));
  if (props) applyProps(el, props);
  appendChildren(el, children);
  return el;
}

/**
 * Replace all children of a node.
 * @param {Element} el
 * @param {...Children} children
 */
export function mount(el, ...children) {
  el.replaceChildren();
  appendChildren(el, children);
}

/**
 * Stable unique id for aria relationships.
 * @param {string} prefix
 */
export function uid(prefix) {
  uid.counter += 1;
  return `${prefix}-${uid.counter}`;
}
uid.counter = 0;
