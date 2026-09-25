// Form fields with visible labels, help text and inline errors wired through
// aria-describedby / aria-invalid.
import { h, uid } from '../core/dom.js';

/**
 * @typedef {Object} FieldOptions
 * @property {string} name
 * @property {string} label
 * @property {'text'|'number'|'textarea'|'select'|'search'} [type]
 * @property {string} [value]
 * @property {boolean} [required]
 * @property {string} [help]
 * @property {string} [placeholder]
 * @property {boolean} [disabled]
 * @property {{value: string, label: string}[]} [options]
 * @property {number} [rows]
 * @property {string} [min]
 * @property {string} [max]
 * @property {string} [step]
 * @property {string} [maxLength]
 * @property {string} [className]
 */

/**
 * @param {FieldOptions} options
 * @returns {HTMLDivElement}
 */
export function field(options) {
  const id = uid('f-' + options.name);
  const helpId = options.help ? id + '-help' : null;
  const errorId = id + '-err';
  const describedBy = [helpId, errorId].filter(Boolean).join(' ');
  /** @type {Record<string, string|boolean|null|undefined>} */
  const common = { id, name: options.name, required: options.required || null, disabled: options.disabled || null,
                   placeholder: options.placeholder, 'aria-describedby': describedBy, 'aria-required': options.required ? 'true' : null };
  /** @type {HTMLInputElement|HTMLSelectElement|HTMLTextAreaElement} */
  let control;
  if (options.type === 'textarea') {
    control = h('textarea', { class: 'textarea', attrs: { ...common, rows: String(options.rows || 4), maxlength: options.maxLength } });
    control.value = options.value || '';
  } else if (options.type === 'select') {
    control = h('select', { class: 'select', attrs: common }, (options.options || []).map((o) => h('option', { attrs: { value: o.value } }, o.label)));
    control.value = options.value || '';
  } else {
    control = h('input', { class: 'input', attrs: { ...common, type: options.type || 'text', min: options.min, max: options.max, step: options.step,
                                                   maxlength: options.maxLength, inputmode: options.type === 'number' ? 'decimal' : null } });
    control.value = options.value || '';
  }
  return h('div', { class: `field ${options.className || ''}`.trim(), dataset: { field: options.name } },
    h('label', { class: 'field-label', attrs: { for: id } }, options.label, options.required ? h('span', { class: 'req', attrs: { 'aria-hidden': 'true' } }, '*') : null),
    control,
    options.help ? h('span', { class: 'field-help', attrs: { id: helpId } }, options.help) : null,
    h('span', { class: 'field-error', attrs: { id: errorId, 'aria-live': 'polite' } }));
}

/**
 * @param {string} label
 * @param {string} name
 * @param {boolean} checked
 * @param {string} [help]
 */
export function checkbox(label, name, checked, help) {
  const id = uid('cb-' + name);
  const input = h('input', { attrs: { type: 'checkbox', id, name } });
  input.checked = checked;
  return h('div', { class: 'field' },
    h('label', { class: 'checkbox', attrs: { for: id } }, input, label),
    help ? h('span', { class: 'field-help' }, help) : null);
}

/**
 * Collect named control values as strings (checkboxes as "true"/"false").
 * @param {HTMLFormElement} form
 * @returns {Record<string, string>}
 */
export function formValues(form) {
  /** @type {Record<string, string>} */
  const values = {};
  for (const element of Array.from(form.elements)) {
    if (!(element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement) || !element.name) continue;
    values[element.name] = element instanceof HTMLInputElement && element.type === 'checkbox' ? String(element.checked) : element.value;
  }
  return values;
}

/**
 * Show validation errors; focuses the first invalid control. Returns true when valid.
 * @param {HTMLFormElement} form
 * @param {Record<string, string>} errors
 */
export function showErrors(form, errors) {
  let first = /** @type {HTMLElement|null} */ (null);
  for (const wrapper of Array.from(form.querySelectorAll('[data-field]'))) {
    const name = /** @type {HTMLElement} */ (wrapper).dataset.field || '';
    const control = wrapper.querySelector('input, select, textarea');
    const slot = wrapper.querySelector('.field-error');
    const message = errors[name];
    if (control) {
      if (message) control.setAttribute('aria-invalid', 'true');
      else control.removeAttribute('aria-invalid');
    }
    if (slot) slot.textContent = message || '';
    if (message && !first && control instanceof HTMLElement) first = control;
  }
  first?.focus();
  return !first;
}
