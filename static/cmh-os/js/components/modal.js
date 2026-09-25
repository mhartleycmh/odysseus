// Native <dialog> modals: focus is trapped by the browser, Esc closes, and
// focus returns to the element that opened the dialog.
import { h, uid } from '../core/dom.js';
import { t } from '../core/i18n.js';

/** @typedef {import('../core/dom.js').Children} Children */

/**
 * @typedef {Object} ModalOptions
 * @property {string} title
 * @property {Children} body
 * @property {Children} [footer]
 * @property {boolean} [wide]
 * @property {() => void} [onClose]
 */

/**
 * @param {ModalOptions} options
 * @returns {{dialog: HTMLDialogElement, close: () => void}}
 */
export function openModal(options) {
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const titleId = uid('modal');
  const dialog = h('dialog', { class: options.wide ? 'modal wide' : 'modal', attrs: { 'aria-labelledby': titleId } });
  const close = () => {
    if (dialog.open) dialog.close();
  };
  dialog.append(h('div', { class: 'modal-inner' },
    h('div', { class: 'modal-header' }, h('h2', { attrs: { id: titleId } }, options.title),
      h('button', { class: 'close-btn', attrs: { type: 'button', 'aria-label': t('common.close') }, on: { click: close } }, '×')),
    h('div', { class: 'modal-body' }, options.body),
    options.footer ? h('div', { class: 'modal-footer' }, options.footer) : null));
  dialog.addEventListener('close', () => {
    dialog.remove();
    options.onClose?.();
    if (opener && opener.isConnected) opener.focus();
  });
  document.body.append(dialog);
  dialog.showModal();
  const first = /** @type {HTMLElement|null} */ (dialog.querySelector('.modal-body input, .modal-body select, .modal-body textarea, .modal-footer .btn-primary, .modal-footer .btn-danger'));
  (first || /** @type {HTMLElement|null} */ (dialog.querySelector('.close-btn')))?.focus();
  return { dialog, close };
}

/**
 * @typedef {Object} ConfirmOptions
 * @property {string} title
 * @property {string} message
 * @property {string} [consequence]
 * @property {string} confirmLabel
 * @property {boolean} [danger]
 * @property {{label: string, minLength: number, help?: string}} [justification]
 */

/**
 * @param {ConfirmOptions} options
 * @returns {Promise<{confirmed: boolean, justification: string}>}
 */
export function confirmDialog(options) {
  return new Promise((resolve) => {
    let settled = false;
    const fieldId = uid('just');
    const errorId = uid('just-err');
    const area = options.justification
      ? h('textarea', { class: 'textarea', attrs: { id: fieldId, rows: '3', 'aria-describedby': errorId, required: true, minlength: String(options.justification.minLength) } })
      : null;
    const error = h('span', { class: 'field-error', attrs: { id: errorId, 'aria-live': 'polite' } });
    const body = [
      h('p', null, options.message),
      options.consequence ? h('div', { class: 'alert tone-warn' }, h('span', { class: 'alert-glyph', attrs: { 'aria-hidden': 'true' } }, '▲'),
        h('div', { class: 'alert-body' }, h('span', { class: 'alert-title' }, t('common.consequence')), h('span', null, options.consequence))) : null,
      area && options.justification ? h('div', { class: 'field' },
        h('label', { class: 'field-label', attrs: { for: fieldId } }, options.justification.label, h('span', { class: 'req', attrs: { 'aria-hidden': 'true' } }, '*')),
        area, options.justification.help ? h('span', { class: 'field-help' }, options.justification.help) : null, error) : null,
    ];
    const confirm = h('button', { class: options.danger ? 'btn btn-danger' : 'btn btn-primary', attrs: { type: 'button', 'data-action': 'confirm' } }, options.confirmLabel);
    const cancel = h('button', { class: 'btn', attrs: { type: 'button', 'data-action': 'cancel' } }, t('common.cancel'));
    const modal = openModal({ title: options.title, body, footer: [cancel, confirm], onClose: () => { if (!settled) resolve({ confirmed: false, justification: '' }); } });
    cancel.addEventListener('click', () => modal.close());
    confirm.addEventListener('click', () => {
      const text = area ? area.value.trim() : '';
      if (area && options.justification && text.length < options.justification.minLength) {
        area.setAttribute('aria-invalid', 'true');
        error.textContent = t('validation.minLength', { n: options.justification.minLength });
        area.focus();
        return;
      }
      settled = true;
      resolve({ confirmed: true, justification: text });
      modal.close();
    });
  });
}
