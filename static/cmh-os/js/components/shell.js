// Application frame: header with the official logo in a white box (CMH rule
// for blue backgrounds), module navigation, demo banner, footer with provenance.
import { h, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { formatDateTime } from '../core/format.js';

/**
 * @typedef {Object} NavItem
 * @property {string} name
 * @property {string} href
 * @property {string} label
 * @property {string} glyph
 * @property {string} section
 */

/**
 * @typedef {Object} ShellOptions
 * @property {NavItem[]} nav
 * @property {'real'|'demo'} mode
 * @property {string|null} reason
 * @property {() => void} onToggleChat
 * @property {() => void} onToggleTheme
 */

/** @param {ShellOptions} options */
export function createShell(options) {
  const navList = h('ul', null);
  const nav = h('nav', { class: 'app-nav', attrs: { id: 'app-nav', 'aria-label': t('shell.navLabel') } }, navList);
  const navToggle = h('button', { class: 'icon-btn nav-toggle', attrs: { type: 'button', 'aria-controls': 'app-nav', 'aria-expanded': 'false', 'aria-label': t('shell.menu') },
    on: { click: () => setNavOpen(!nav.classList.contains('open')) } }, '☰');
  const modeBadge = h('span', { class: `badge badge-origin origin-${options.mode}`, attrs: { 'data-mode': options.mode } }, options.mode === 'real' ? t('origin.realMode') : t('origin.demoMode'));
  const servicesText = h('span', { class: 'header-services' }, '');
  const chatButton = h('button', { class: 'icon-btn', attrs: { type: 'button', 'aria-pressed': 'false', 'aria-controls': 'app-chat', 'data-action': 'toggle-chat' },
    on: { click: options.onToggleChat } }, h('span', { attrs: { 'aria-hidden': 'true' } }, '✦'), h('span', { class: 'btn-text' }, t('shell.chat')));
  const themeButton = h('button', { class: 'icon-btn', attrs: { type: 'button', 'aria-label': t('shell.theme'), 'data-action': 'toggle-theme' }, on: { click: options.onToggleTheme } },
    h('span', { attrs: { 'aria-hidden': 'true' } }, '◐'));
  const header = h('header', { class: 'app-header' },
    navToggle,
    h('a', { class: 'brand', attrs: { href: '#/', 'aria-label': t('shell.home') } },
      h('span', { class: 'brand-logo' }, h('img', { attrs: { src: '/static/cmh-os/assets/logo-cmh.png', alt: 'Consorcio Minero Horizonte', width: '68', height: '28' } })),
      h('span', { class: 'brand-name' }, h('strong', null, 'Agentic OS'), h('span', null, t('shell.scope')))),
    h('span', { class: 'header-spacer' }),
    h('span', { class: 'header-status' }, modeBadge, servicesText),
    h('div', { class: 'header-actions' }, chatButton, themeButton));

  const banner = options.mode === 'demo'
    ? h('div', { class: 'demo-banner', attrs: { role: 'status', 'data-banner': 'demo' } },
        h('strong', null, t('shell.demoBanner')), h('span', null, t('shell.demoReason.' + (options.reason || 'forzado'))))
    : null;
  const viewHost = h('div', { class: 'view-host' });
  const loadedAt = new Date().toISOString();
  const footer = h('footer', { class: 'app-footer' },
    t('shell.footer', { source: options.mode === 'real' ? t('shell.sourceReal') : t('shell.sourceDemo'), cut: formatDateTime(loadedAt), mode: options.mode === 'real' ? t('origin.real') : t('origin.demo') }));
  const main = h('main', { class: 'app-main', attrs: { id: 'main', tabindex: '-1' } }, banner, viewHost, footer);
  const chatHost = h('aside', { class: 'app-chat', attrs: { id: 'app-chat', hidden: true, 'aria-label': t('chat.title') } });
  const app = h('div', { class: 'app' }, header, nav, main, chatHost);
  const root = h('div', null, h('a', { class: 'skip-link', attrs: { href: '#main' }, on: { click: (event) => { event.preventDefault(); main.focus(); } } }, t('shell.skip')), app);

  /** @param {boolean} open */
  function setNavOpen(open) {
    nav.classList.toggle('open', open);
    navToggle.setAttribute('aria-expanded', String(open));
  }

  /** @type {Map<string, HTMLElement>} */
  const counters = new Map();
  /** @param {string} active */
  function renderNav(active) {
    let section = '';
    /** @type {HTMLElement[]} */
    const items = [];
    for (const item of options.nav) {
      if (item.section !== section) {
        section = item.section;
        items.push(h('li', { class: 'nav-section', attrs: { 'aria-hidden': 'true' } }, t('nav.section.' + section)));
      }
      const count = h('span', { class: 'nav-count', attrs: { hidden: true } }, '');
      counters.set(item.name, count);
      items.push(h('li', null, h('a', { class: 'nav-link', attrs: { href: item.href, 'aria-current': item.name === active ? 'page' : null, 'data-nav': item.name, title: item.label },
        on: { click: () => setNavOpen(false) } },
        h('span', { class: 'nav-glyph', attrs: { 'aria-hidden': 'true' } }, item.glyph), h('span', { class: 'nav-label' }, item.label), count)));
    }
    mount(navList, items);
  }

  return {
    root,
    viewHost,
    chatHost,
    app,
    renderNav,
    /** @param {string} name @param {number} value @param {string} label */
    setCount(name, value, label) {
      const node = counters.get(name);
      if (!node) return;
      node.hidden = value === 0;
      node.textContent = String(value);
      node.setAttribute('aria-label', label);
    },
    /** @param {string} text */
    setServices(text) {
      servicesText.textContent = text;
    },
    /** @param {boolean} open */
    setChatOpen(open) {
      chatHost.hidden = !open;
      app.classList.toggle('chat-open', open);
      chatButton.setAttribute('aria-pressed', String(open));
    },
  };
}
