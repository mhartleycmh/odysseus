// Documentación integrada: module guide, legends, glossary and local docs.
import { h } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { panel, viewHeader } from '../components/panel.js';
import { statusBadge, originBadge, riskBadge, permissionBadge } from '../components/badge.js';

/** @typedef {import('../types.js').AppContext} AppContext */

const MODULES = ['overview', 'orchestration', 'executions', 'approvals', 'agents', 'tools', 'memory', 'observability', 'evaluations', 'security', 'settings'];
const GLOSSARY = ['agent', 'coordinator', 'workflow', 'execution', 'step', 'artifact', 'approval', 'memory', 'mcp', 'trace', 'span', 'token', 'loop', 'leastPrivilege', 'demo'];
const DOCS = ['ARCHITECTURE', 'DECISIONS', 'UI_UX_SPECIFICATION', 'IMPLEMENTATION_PLAN', 'TEST_PLAN', 'IMPLEMENTATION_STATUS', 'RESEARCH', 'OPEN_SOURCE_REFERENCES', 'LICENSES_AND_ATTRIBUTIONS'];

/** @param {AppContext} ctx */
export function render(ctx) {
  const el = h('section', { class: 'view', attrs: { 'data-view': 'help' } },
    viewHeader(t('help.title'), t('help.lede')),
    panel({ title: t('help.modules'), origin: null, body: h('dl', { class: 'dl' }, MODULES.flatMap((m) => [
      h('dt', null, h('a', { attrs: { href: t(`help.module.${m}.href`) } }, t('nav.' + m))), h('dd', null, t(`help.module.${m}.text`)),
    ])) }),
    h('div', { class: 'grid grid-2' },
      panel({ title: t('help.legends'), origin: null, body: [
        h('h3', null, t('help.legendStatus')),
        h('div', { class: 'chip-list' }, statusBadge('ok', t('tone.ok')), statusBadge('live', t('tone.live')), statusBadge('warn', t('tone.warn')), statusBadge('risk', t('tone.risk')), statusBadge('idle', t('tone.idle'))),
        h('p', { class: 'small muted' }, t('help.legendStatusText')),
        h('h3', null, t('help.legendOrigin')),
        h('div', { class: 'chip-list' }, originBadge('real'), originBadge('demo'), originBadge('demo', { partial: true })),
        h('p', { class: 'small muted' }, t('help.legendOriginText')),
        h('h3', null, t('help.legendRisk')),
        h('div', { class: 'chip-list' }, riskBadge('bajo'), riskBadge('medio'), riskBadge('alto'), permissionBadge('lectura'), permissionBadge('escritura'), permissionBadge('admin')),
        h('h3', null, t('help.legendGraph')),
        h('p', { class: 'small muted' }, t('help.legendGraphText')),
      ] }),
      panel({ title: t('help.shortcuts'), origin: null, body: h('ul', { class: 'list' },
        h('li', null, h('span', null, h('kbd', { class: 'kbd' }, '/'), ' ', t('help.shortcut.chat'))),
        h('li', null, h('span', null, h('kbd', { class: 'kbd' }, 'Esc'), ' ', t('help.shortcut.close'))),
        h('li', null, h('span', null, h('kbd', { class: 'kbd' }, 'Tab'), ' ', t('help.shortcut.tab'))),
        h('li', null, h('span', null, h('kbd', { class: 'kbd' }, '←'), h('kbd', { class: 'kbd' }, '→'), ' ', t('help.shortcut.tabs'))),
        h('li', null, h('span', null, h('kbd', { class: 'kbd' }, 'Enter'), ' ', t('help.shortcut.open')))) })),
    panel({ title: t('help.glossary'), origin: null, body: h('dl', { class: 'dl' }, GLOSSARY.flatMap((g) => [h('dt', null, t(`help.term.${g}.name`)), h('dd', null, t(`help.term.${g}.text`))])) }),
    panel({ title: t('help.docs'), origin: null, body: [
      h('p', null, t('help.docsText')),
      h('ul', { class: 'list' }, DOCS.map((d) => h('li', null, h('code', null, `integrations/cmh/docs/${d}.md`)))),
      h('p', { class: 'small muted' }, t('help.mode', { mode: ctx.mode === 'real' ? t('origin.realMode') : t('origin.demoMode') })),
    ] }));
  return { el, title: t('help.title') };
}
