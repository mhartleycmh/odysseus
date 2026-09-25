// Bootstrap: preferences, data source selection, shell, router and chat.
import { h, mount } from './core/dom.js';
import { viewHeader } from './components/panel.js';
import { t, setLanguage } from './core/i18n.js';
import { log } from './core/log.js';
import { loadPrefs, savePrefs } from './core/prefs.js';
import { createRouter, matchRoute } from './core/router.js';
import { request } from './services/http.js';
import { createSource, detectMode, loadConfig } from './services/source.js';
import { createShell } from './components/shell.js';
import { createChatPanel } from './components/chat-panel.js';
import { confirmDialog } from './components/modal.js';
import { toast } from './components/toast.js';
import { emptyState, errorMessage } from './components/states.js';
import * as overview from './views/overview.js';
import * as agents from './views/agents.js';
import * as executions from './views/executions.js';
import * as orchestration from './views/orchestration.js';
import * as memory from './views/memory.js';
import * as tools from './views/tools.js';
import * as approvals from './views/approvals.js';
import * as observability from './views/observability.js';
import * as evaluations from './views/evaluations.js';
import * as security from './views/security.js';
import * as settings from './views/settings.js';
import * as help from './views/help.js';

/** @typedef {import('./types.js').AppContext} AppContext */
/** @typedef {import('./types.js').Prefs} Prefs */
/** @typedef {import('./core/router.js').RouteMatch} RouteMatch */
/** @typedef {{el: HTMLElement, title: string, destroy?: () => void}} ViewInstance */
/** @typedef {(ctx: AppContext, match: RouteMatch) => ViewInstance} ViewFactory */

/** @type {{name: string, pattern: string, nav: boolean, section: string, glyph: string, label: string, view: ViewFactory, parent?: string}[]} */
const ROUTES = [
  { name: 'overview', pattern: '/', nav: true, section: 'operacion', glyph: '◈', label: 'nav.overview', view: overview.render },
  { name: 'orchestration', pattern: '/orquestacion', nav: true, section: 'operacion', glyph: '✦', label: 'nav.orchestration', view: orchestration.render },
  { name: 'orchestrationRun', pattern: '/orquestacion/:id', nav: false, section: 'operacion', glyph: '', label: 'nav.orchestration', view: orchestration.render, parent: 'orchestration' },
  { name: 'executions', pattern: '/ejecuciones', nav: true, section: 'operacion', glyph: '▶', label: 'nav.executions', view: executions.renderList },
  { name: 'execution', pattern: '/ejecuciones/:id', nav: false, section: 'operacion', glyph: '', label: 'nav.executions', view: executions.renderDetail, parent: 'executions' },
  { name: 'approvals', pattern: '/aprobaciones', nav: true, section: 'operacion', glyph: '✓', label: 'nav.approvals', view: approvals.render },
  { name: 'agents', pattern: '/agentes', nav: true, section: 'capacidades', glyph: '◉', label: 'nav.agents', view: agents.renderList },
  { name: 'agent', pattern: '/agentes/:id', nav: false, section: 'capacidades', glyph: '', label: 'nav.agents', view: agents.renderDetail, parent: 'agents' },
  { name: 'tools', pattern: '/herramientas', nav: true, section: 'capacidades', glyph: '⚙', label: 'nav.tools', view: tools.render },
  { name: 'memory', pattern: '/memoria', nav: true, section: 'capacidades', glyph: '▤', label: 'nav.memory', view: memory.render },
  { name: 'observability', pattern: '/observabilidad', nav: true, section: 'control', glyph: '≋', label: 'nav.observability', view: observability.renderList },
  { name: 'trace', pattern: '/observabilidad/:id', nav: false, section: 'control', glyph: '', label: 'nav.observability', view: observability.renderTrace, parent: 'observability' },
  { name: 'evaluations', pattern: '/evaluaciones', nav: true, section: 'control', glyph: '◇', label: 'nav.evaluations', view: evaluations.render },
  { name: 'security', pattern: '/seguridad', nav: true, section: 'control', glyph: '⛨', label: 'nav.security', view: security.render },
  { name: 'settings', pattern: '/configuracion', nav: true, section: 'sistema', glyph: '⚒', label: 'nav.settings', view: settings.render },
  { name: 'help', pattern: '/ayuda', nav: true, section: 'sistema', glyph: '?', label: 'nav.help', view: help.render },
];

/** @param {Prefs} prefs */
function applyAppearance(prefs) {
  const media = window.matchMedia;
  const dark = prefs.theme === 'dark' || (prefs.theme === 'system' && media?.('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  const reduced = prefs.motion === 'reduced' || (prefs.motion === 'system' && media?.('(prefers-reduced-motion: reduce)').matches);
  document.documentElement.dataset.motion = reduced ? 'reduced' : 'full';
}

async function start() {
  let prefs = loadPrefs();
  setLanguage(prefs.language);
  applyAppearance(prefs);
  const query = new URLSearchParams(window.location.search);
  const config = await loadConfig(request);
  if (!config.uiEnabled) {
    const host = /** @type {HTMLElement} */ (document.getElementById('app'));
    mount(host, h('main', { class: 'view', attrs: { id: 'main' } }, viewHeader(t('errors.disabledTitle'), t('errors.disabledText'))));
    return;
  }
  const { mode, reason } = await detectMode({ preference: prefs.mode, query, config, request });
  const speed = query.get('velocidad') === 'rapida' ? 0.15 : 1;
  const source = createSource({ mode, failures: () => prefs.flags.simulateFailures && mode === 'demo', speed });
  log('info', 'main', 'source selected', { mode, reason });

  /** @type {ViewInstance|null} */
  let current = null;
  let firstView = true;
  let chatOpen = false;

  const shell = createShell({
    nav: ROUTES.filter((r) => r.nav && (r.name !== 'evaluations' || prefs.flags.evaluations)).map((r) => ({ name: r.name, href: '#' + r.pattern, label: t(r.label), glyph: r.glyph, section: r.section })),
    mode, reason,
    onToggleChat: () => setChat(!chatOpen),
    onToggleTheme: () => {
      const dark = document.documentElement.dataset.theme === 'dark';
      ctx.setPrefs({ theme: dark ? 'light' : 'dark' });
    },
  });
  mount(/** @type {HTMLElement} */ (document.getElementById('app')), shell.root);

  /** @type {AppContext} */
  const ctx = {
    source, mode, reason,
    prefs: () => prefs,
    setPrefs(patch) {
      prefs = { ...prefs, ...patch };
      savePrefs(prefs);
      applyAppearance(prefs);
    },
    navigate: (hash) => router.go(hash),
    refreshCounts,
    async confirmStop(executionId) {
      const answer = await confirmDialog({ title: t('confirm.stop.title'), message: t('confirm.stop.message', { id: executionId }),
                                           consequence: t('confirm.stop.consequence'), confirmLabel: t('confirm.stop.action'), danger: true });
      if (!answer.confirmed) return false;
      try {
        await source.cancelExecution(executionId);
        toast(t('confirm.stop.done'), 'warn');
        return true;
      } catch (error) {
        toast(errorMessage(error), 'risk');
        return false;
      }
    },
    reducedMotion: () => document.documentElement.dataset.motion === 'reduced',
  };

  const chat = createChatPanel({
    context: () => ({ source, allowModel: prefs.flags.chatModel, model: prefs.chatModel }),
    onNavigate: (href) => {
      if (window.matchMedia?.('(max-width: 1279px)').matches) setChat(false);
      router.go(href);
    },
    onConfirmStop: (id) => { ctx.confirmStop(id); },
    onClose: () => setChat(false),
  });
  shell.chatHost.append(chat.el);

  /** @param {boolean} open */
  function setChat(open) {
    chatOpen = open;
    shell.setChatOpen(open);
    if (open) chat.focus();
  }

  async function refreshCounts() {
    // A hidden tab does not poll; it refreshes when it becomes visible again.
    if (document.hidden) return;
    try {
      const pending = (await source.listApprovals()).filter((a) => a.status === 'pendiente').length;
      shell.setCount('approvals', pending, t('nav.pendingCount', { n: pending }));
    } catch {
      // Counter is advisory; the approvals view reports its own errors.
    }
  }

  async function refreshServices() {
    try {
      const services = await source.getServices();
      const bad = services.filter((s) => s.tone === 'risk').length;
      const warn = services.filter((s) => s.tone === 'warn').length;
      shell.setServices(bad ? t(bad === 1 ? 'shell.services.riskOne' : 'shell.services.risk', { n: bad })
        : warn ? t(warn === 1 ? 'shell.services.warnOne' : 'shell.services.warn', { n: warn }) : t('shell.services.ok'));
    } catch {
      shell.setServices(t('shell.services.unknown'));
    }
  }

  /** @param {RouteMatch|null} match */
  function show(match) {
    current?.destroy?.();
    current = null;
    // A dialog belongs to the view that opened it: never let it act on the next one.
    for (const dialog of document.querySelectorAll('dialog[open]')) /** @type {HTMLDialogElement} */ (dialog).close();
    const route = match ? ROUTES.find((r) => r.name === match.name) : undefined;
    shell.renderNav(route?.parent || route?.name || '');
    if (!route || !match) {
      const el = document.createElement('section');
      el.className = 'view';
      el.dataset.view = 'not-found';
      mount(el, viewHeader(t('notFound.title'), t('notFound.text')), h('a', { class: 'btn btn-primary', attrs: { href: '#/' } }, t('nav.overview')));
      mount(shell.viewHost, el);
      document.title = `${t('notFound.title')} · Agentic OS CMH`;
      return;
    }
    try {
      current = route.view(ctx, match);
      mount(shell.viewHost, current.el);
      document.title = `${current.title} · Agentic OS CMH`;
      const heading = /** @type {HTMLElement|null} */ (current.el.querySelector('h1'));
      // After a navigation, focus moves to the new page title (screen readers
      // announce it); on the very first load the page keeps its natural order.
      if (heading && !firstView) heading.focus({ preventScroll: true });
      firstView = false;
      window.scrollTo(0, 0);
    } catch (error) {
      log('error', 'main', 'view failed', { route: route.name, message: errorMessage(error) });
      toast(errorMessage(error), 'risk');
    }
  }

  const router = createRouter(ROUTES.map((r) => ({ name: r.name, pattern: r.pattern })), show);
  window.addEventListener('error', (event) => {
    log('error', 'window', 'uncaught', { message: event.message });
    toast(t('errors.unexpected'), 'risk');
  });
  window.addEventListener('unhandledrejection', (event) => {
    log('error', 'window', 'unhandled rejection', { message: errorMessage(event.reason) });
    toast(t('errors.unexpected'), 'risk');
  });
  document.addEventListener('keydown', (event) => {
    const target = /** @type {HTMLElement} */ (event.target);
    if (event.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) && !document.querySelector('dialog[open]')) {
      event.preventDefault();
      setChat(true);
    }
  });
  for (const query of ['(prefers-color-scheme: dark)', '(prefers-reduced-motion: reduce)']) {
    window.matchMedia?.(query).addEventListener?.('change', () => applyAppearance(prefs));
  }
  router.start();
  document.documentElement.dataset.ready = 'true';
  refreshCounts();
  refreshServices();
  setInterval(refreshCounts, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshCounts(); });
  // Exposed for the end-to-end runner and for debugging; read-only information.
  Object.defineProperty(window, '__cmhOs', { value: Object.freeze({ mode, reason, routes: ROUTES.map((r) => r.pattern), match: (/** @type {string} */ hash) => matchRoute(ROUTES, hash)?.name || null }) });
}

start().catch((error) => {
  log('error', 'main', 'start failed', { message: errorMessage(error) });
  const host = document.getElementById('app');
  if (host) mount(host, emptyState({ title: t('errors.startTitle'), text: errorMessage(error), glyph: '■' }));
});
