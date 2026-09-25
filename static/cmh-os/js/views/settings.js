// Configuración: providers (keys never shown), default limits, appearance,
// language, feature flags, data mode and server environment variables.
import { h, mount } from '../core/dom.js';
import { t, languages } from '../core/i18n.js';
import { validate } from '../core/validate.js';
import { request } from '../services/http.js';
import { loadConfig } from '../services/source.js';
import { panel, viewHeader, definitionList } from '../components/panel.js';
import { asyncView, alertBox, emptyState } from '../components/states.js';
import { statusBadge, maskedValue } from '../components/badge.js';
import { dataTable } from '../components/table.js';
import { field, checkbox, formValues, showErrors } from '../components/form.js';
import { confirmDialog } from '../components/modal.js';
import { toast } from '../components/toast.js';

/** @typedef {import('../types.js').AppContext} AppContext */
/** @typedef {import('../types.js').Prefs} Prefs */

/** @type {import('../core/validate.js').Schema} */
export const SETTINGS_SCHEMA = {
  maxIterations: { required: true, integer: true, min: 1, max: 200 },
  timeoutSeconds: { required: true, integer: true, min: 10, max: 86400 },
  budgetUsd: { required: true, min: 0.01, max: 1000 },
  actor: { required: true, maxLength: 60, pattern: /^[\p{L}\p{N} ._-]+$/u, patternMessage: 'settings.actorPattern' },
};

/** @param {AppContext} ctx */
export function render(ctx) {
  const host = h('div', { class: 'stack' });
  const el = h('section', { class: 'view', attrs: { 'data-view': 'settings' } }, viewHeader(t('settings.title'), t('settings.lede')), host);
  asyncView(host, () => Promise.all([ctx.source.listProviders().catch(() => []), loadConfig(request)]), ([providers, config]) => {
    const prefs = ctx.prefs();
    const modelOptions = providers.flatMap((p) => p.models.map((m) => ({ value: `${p.id}|${m}`, label: `${p.name} · ${m}` })));
    const form = h('form', { class: 'form', attrs: { novalidate: true, 'data-form': 'settings' } },
      h('fieldset', { class: 'fieldset' }, h('legend', null, t('settings.appearance')), h('div', { class: 'form-grid' },
        field({ name: 'theme', label: t('settings.theme'), type: 'select', value: prefs.theme, options: ['system', 'light', 'dark'].map((v) => ({ value: v, label: t('settings.themeOption.' + v) })) }),
        field({ name: 'motion', label: t('settings.motion'), type: 'select', value: prefs.motion, options: ['system', 'reduced', 'full'].map((v) => ({ value: v, label: t('settings.motionOption.' + v) })), help: t('settings.motionHelp') }),
        field({ name: 'language', label: t('settings.language'), type: 'select', value: prefs.language, options: languages().map((l) => ({ value: l, label: t('settings.languageOption.' + l) })), help: t('settings.languageHelp') }),
        field({ name: 'actor', label: t('settings.actor'), value: prefs.actor, required: true, maxLength: '60', help: t('settings.actorHelp') }))),
      h('fieldset', { class: 'fieldset' }, h('legend', null, t('settings.limits')), h('p', { class: 'field-help' }, t('settings.limitsHelp')), h('div', { class: 'form-grid' },
        field({ name: 'maxIterations', label: t('executions.form.maxIterations'), type: 'number', required: true, min: '1', max: '200', value: String(prefs.limits.maxIterations) }),
        field({ name: 'timeoutSeconds', label: t('executions.form.timeout'), type: 'number', required: true, min: '10', max: '86400', value: String(prefs.limits.timeoutSeconds) }),
        field({ name: 'budgetUsd', label: t('executions.form.budget'), type: 'number', required: true, min: '0.01', max: '1000', step: '0.01', value: String(prefs.limits.budgetUsd) }))),
      h('fieldset', { class: 'fieldset' }, h('legend', null, t('settings.flags')),
        checkbox(t('settings.flag.chatModel'), 'chatModel', prefs.flags.chatModel, ctx.source.capabilities.chatModel ? t('settings.flag.chatModelHelp') : t('settings.flag.chatModelDemo')),
        field({ name: 'chatModelChoice', label: t('settings.chatModel'), type: 'select', value: prefs.chatModel ? `${prefs.chatModel.endpointId}|${prefs.chatModel.model}` : '',
                options: [{ value: '', label: t('settings.noChatModel') }, ...modelOptions], disabled: !ctx.source.capabilities.chatModel }),
        checkbox(t('settings.flag.simulateFailures'), 'simulateFailures', prefs.flags.simulateFailures, t('settings.flag.simulateFailuresHelp')),
        checkbox(t('settings.flag.evaluations'), 'evaluations', prefs.flags.evaluations, t('settings.flag.evaluationsHelp'))),
      h('fieldset', { class: 'fieldset' }, h('legend', null, t('settings.dataMode')),
        definitionList([[t('settings.currentMode'), ctx.mode === 'real' ? t('origin.realMode') : t('origin.demoMode')], [t('settings.reason'), ctx.reason ? t('shell.demoReason.' + ctx.reason) : t('settings.reasonReal')]]),
        field({ name: 'mode', label: t('settings.modePreference'), type: 'select', value: prefs.mode, options: [{ value: 'auto', label: t('settings.modeOption.auto') }, { value: 'demo', label: t('settings.modeOption.demo') }], help: t('settings.modeHelp') })),
      h('div', { class: 'form-actions' }, h('button', { class: 'btn btn-primary', attrs: { type: 'submit', 'data-action': 'save-settings' } }, t('settings.save'))));

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const v = formValues(form);
      if (!showErrors(form, validate(SETTINGS_SCHEMA, v))) return;
      const wantsModel = v.chatModel === 'true';
      if (wantsModel && !prefs.flags.chatModel) {
        const answer = await confirmDialog({ title: t('settings.chatConfirmTitle'), message: t('settings.chatConfirmMessage'), consequence: t('settings.chatConfirmConsequence'), confirmLabel: t('settings.chatConfirmAction') });
        if (!answer.confirmed) return;
      }
      const [endpointId, ...modelParts] = (v.chatModelChoice || '').split('|');
      const modeChanged = v.mode !== prefs.mode;
      ctx.setPrefs({
        theme: /** @type {Prefs['theme']} */ (v.theme), motion: /** @type {Prefs['motion']} */ (v.motion), language: v.language, actor: v.actor.trim(),
        mode: v.mode === 'demo' ? 'demo' : 'auto',
        limits: { maxIterations: Number(v.maxIterations), timeoutSeconds: Number(v.timeoutSeconds), budgetUsd: Number(v.budgetUsd.replace(',', '.')) },
        flags: { chatModel: wantsModel, simulateFailures: v.simulateFailures === 'true', evaluations: v.evaluations === 'true' },
        chatModel: endpointId && modelParts.length ? { endpointId, model: modelParts.join('|') } : null,
      });
      mount(status, alertBox('ok', t('settings.saved'), modeChanged
        ? h('button', { class: 'btn btn-sm', attrs: { type: 'button', 'data-action': 'reload' }, on: { click: () => window.location.reload() } }, t('settings.reloadToApply')) : null));
      toast(t('settings.saved'), 'ok');
    });
    const status = h('div', { attrs: { 'aria-live': 'polite' } });

    const providersTable = dataTable({
      caption: t('settings.providers'), rows: providers, rowKey: (p) => p.id, emptyText: t('settings.noProviders'),
      columns: [
        { key: 'name', label: t('settings.col.provider'), render: (p) => h('span', null, h('strong', null, p.name), h('br'), h('code', { class: 'xsmall' }, p.baseUrl)) },
        { key: 'status', label: t('settings.col.status'), render: (p) => statusBadge(p.status === 'online' ? 'ok' : p.status === 'offline' ? 'risk' : 'idle', t('settings.providerStatus.' + p.status)) },
        { key: 'key', label: t('settings.col.key'), render: (p) => (p.hasKey ? maskedValue(p.keyFingerprint) : h('span', { class: 'muted' }, t('settings.noKey'))) },
        { key: 'tools', label: t('settings.col.tools'), render: (p) => p.supportsTools === null ? h('span', { class: 'muted' }, t('settings.unknown')) : p.supportsTools ? statusBadge('ok', t('common.yes')) : statusBadge('warn', t('common.no')) },
        { key: 'models', label: t('settings.col.models'), num: true, render: (p) => String(p.models.length) },
      ] });

    const envTable = dataTable({
      caption: t('settings.env'), rowKey: (r) => r.name,
      rows: [
        { name: 'CMH_OS_UI_ENABLED', value: String(config.uiEnabled), description: t('settings.envUi') },
        { name: 'CMH_OS_DEFAULT_MODE', value: config.defaultMode, description: t('settings.envMode') },
      ],
      columns: [
        { key: 'name', label: t('settings.col.variable'), render: (r) => h('code', null, r.name) },
        { key: 'value', label: t('settings.col.value'), render: (r) => h('code', null, r.value) },
        { key: 'description', label: t('settings.col.description'), render: (r) => r.description },
      ] });

    return [
      panel({ title: t('settings.preferences'), origin: null, body: [form, status] }),
      panel({ title: t('settings.providers'), origin: providers[0]?.origin || ctx.source.mode, help: t('settings.providersHelp'), flush: true,
              body: providers.length ? providersTable : emptyState({ title: t('settings.noProviders') }) }),
      panel({ title: t('settings.env'), origin: ctx.mode, help: t('settings.envHelp'), flush: true, body: envTable,
              footer: t('settings.envFooter') }),
    ];
  }, { lines: 8 });
  return { el, title: t('settings.title') };
}
