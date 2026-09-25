// Accessible tabs (WAI-ARIA tabs pattern with arrow-key navigation).
import { h, uid } from '../core/dom.js';

/**
 * @param {{tabs: {id: string, label: string}[], selected: string, label: string, onChange: (id: string) => void}} options
 * @returns {HTMLDivElement}
 */
export function tabs(options) {
  const base = uid('tabs');
  const list = h('div', { class: 'tabs', attrs: { role: 'tablist', 'aria-label': options.label } });
  const buttons = options.tabs.map((tab) => h('button', {
    class: 'tab',
    attrs: { type: 'button', role: 'tab', id: `${base}-${tab.id}`, 'aria-selected': String(tab.id === options.selected), tabindex: tab.id === options.selected ? '0' : '-1', 'data-tab': tab.id },
    on: { click: () => select(tab.id) },
  }, tab.label));
  /** @param {string} id */
  function select(id) {
    for (const button of buttons) {
      const on = button.dataset.tab === id;
      button.setAttribute('aria-selected', String(on));
      button.tabIndex = on ? 0 : -1;
      if (on) button.focus();
    }
    options.onChange(id);
  }
  list.addEventListener('keydown', (event) => {
    const key = /** @type {KeyboardEvent} */ (event).key;
    const index = buttons.findIndex((b) => b.getAttribute('aria-selected') === 'true');
    if (key === 'ArrowRight' || key === 'ArrowLeft') {
      event.preventDefault();
      const next = buttons[(index + (key === 'ArrowRight' ? 1 : buttons.length - 1)) % buttons.length];
      select(next.dataset.tab || '');
    }
  });
  list.append(...buttons);
  return list;
}
