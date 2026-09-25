// Chat panel for the coordinator. Rendering only; replies come from services/chat.js.
import { h } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { respond } from '../services/chat.js';
import { errorMessage } from './states.js';

/** @typedef {import('../services/chat.js').ChatReply} ChatReply */
/** @typedef {import('../services/chat.js').ChatAction} ChatAction */
/** @typedef {import('../services/chat.js').ChatContext} ChatContext */

/**
 * @typedef {Object} ChatPanelOptions
 * @property {() => ChatContext} context
 * @property {(href: string) => void} onNavigate
 * @property {(executionId: string) => void} onConfirmStop
 * @property {() => void} onClose
 */

/** @param {ChatPanelOptions} options */
export function createChatPanel(options) {
  const log = h('div', { class: 'chat-log', attrs: { role: 'log', 'aria-live': 'polite', 'aria-label': t('chat.log') } });
  const input = h('textarea', { class: 'textarea chat-input', attrs: { rows: '2', maxlength: '4000', 'aria-label': t('chat.inputLabel'), placeholder: t('chat.placeholder') } });
  const send = h('button', { class: 'btn btn-primary', attrs: { type: 'submit' } }, t('chat.send'));
  const form = h('form', { class: 'chat-form' }, input, send);
  let busy = false;

  /** @param {ChatAction} action */
  function actionButton(action) {
    return h('button', { class: 'btn btn-sm', attrs: { type: 'button', 'data-chat-action': action.kind }, on: { click: () => {
      if (action.kind === 'navigate') options.onNavigate(action.href);
      else if (action.kind === 'confirm-stop') options.onConfirmStop(action.executionId);
      else submit(action.text);
    } } }, action.label);
  }

  /** @param {ChatReply} reply */
  function coordinatorMessage(reply) {
    return h('div', { class: `chat-msg chat-msg-bot${reply.error ? ' chat-msg-error' : ''}`, attrs: { 'data-answered-by': reply.answeredBy } },
      h('div', { class: 'chat-msg-head' }, h('strong', null, t('chat.coordinator')),
        h('span', { class: `badge ${reply.answeredBy === 'modelo' ? 'tone-warn' : 'tone-idle'}` }, reply.answeredBy === 'modelo' ? t('chat.byModel') : t('chat.byRule'))),
      h('p', null, reply.text),
      reply.lines?.length ? h('ul', { class: 'chat-lines' }, reply.lines.map((line) => h('li', null, line))) : null,
      reply.links?.length ? h('ul', { class: 'chat-links' }, reply.links.map((link) => h('li', null, h('a', { attrs: { href: link.href } }, link.label)))) : null,
      reply.actions?.length ? h('div', { class: 'chat-actions' }, reply.actions.map(actionButton)) : null);
  }

  /** @param {string} text */
  async function submit(text) {
    const message = text.trim();
    if (!message || busy) return;
    busy = true;
    send.setAttribute('aria-busy', 'true');
    log.append(h('div', { class: 'chat-msg chat-msg-user' }, h('div', { class: 'chat-msg-head' }, h('strong', null, t('chat.you'))), h('p', null, message)));
    const thinking = h('div', { class: 'chat-msg chat-msg-bot chat-thinking' }, h('span', { class: 'live-dot', attrs: { 'aria-hidden': 'true' } }), ' ', t('chat.thinking'));
    log.append(thinking);
    log.scrollTop = log.scrollHeight;
    try {
      const reply = await respond(message, options.context());
      thinking.replaceWith(coordinatorMessage(reply));
    } catch (error) {
      thinking.replaceWith(coordinatorMessage({ answeredBy: 'regla', error: true, text: t('chat.failed'), lines: [errorMessage(error)] }));
    } finally {
      busy = false;
      send.removeAttribute('aria-busy');
      log.scrollTop = log.scrollHeight;
    }
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const text = input.value;
    input.value = '';
    submit(text);
  });
  input.addEventListener('keydown', (event) => {
    const key = /** @type {KeyboardEvent} */ (event);
    if (key.key === 'Enter' && !key.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
    if (key.key === 'Escape') options.onClose();
  });

  log.append(coordinatorMessage({ answeredBy: 'regla', text: t('chat.welcome'), actions: [
    { kind: 'send', label: t('chat.suggest.status'), text: 'estado' },
    { kind: 'send', label: t('chat.suggest.approvals'), text: 'aprobaciones' },
    { kind: 'send', label: t('chat.suggest.start'), text: 'ejecutar' },
    { kind: 'send', label: t('chat.suggest.help'), text: 'ayuda' },
  ] }));

  const el = h('section', { class: 'chat-panel', attrs: { 'aria-label': t('chat.title') } },
    h('div', { class: 'chat-header' },
      h('div', null, h('h2', null, t('chat.title')), h('p', { class: 'xsmall muted' }, t('chat.subtitle'))),
      h('button', { class: 'close-btn', attrs: { type: 'button', 'aria-label': t('chat.close') }, on: { click: () => options.onClose() } }, '×')),
    log, form, h('p', { class: 'chat-hint xsmall muted' }, t('chat.hint')));
  return { el, focus: () => input.focus(), submit };
}
