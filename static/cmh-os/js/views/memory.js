// Memoria: working, episodic and semantic records with search, filters,
// metadata, relevance, and archive with confirmation.
import { h, mount } from '../core/dom.js';
import { t } from '../core/i18n.js';
import { formatDateTime, formatPercent } from '../core/format.js';
import { panel, viewHeader, definitionList } from '../components/panel.js';
import { asyncView, alertBox, emptyState, errorMessage, skeleton } from '../components/states.js';
import { chip, statusBadge } from '../components/badge.js';
import { field, checkbox, formValues } from '../components/form.js';
import { tabs } from '../components/tabs.js';
import { openModal, confirmDialog } from '../components/modal.js';
import { toast } from '../components/toast.js';

/** @typedef {import('../types.js').AppContext} AppContext */
/** @typedef {import('../types.js').MemoryRecord} MemoryRecord */
/** @typedef {import('../core/router.js').RouteMatch} RouteMatch */

/**
 * Case- and accent-insensitive match over title, content, tags and source.
 * @param {MemoryRecord} record
 * @param {string} query
 */
export function memoryMatches(record, query) {
  if (!query) return true;
  const fold = (/** @type {string} */ s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  return fold(`${record.title} ${record.content} ${record.tags.join(' ')} ${record.source}`).includes(fold(query.trim()));
}

/**
 * @param {AppContext} ctx
 * @param {RouteMatch} match
 */
export function render(ctx, match) {
  const host = h('div', { class: 'stack' });
  const el = h('section', { class: 'view', attrs: { 'data-view': 'memory' } }, viewHeader(t('memory.title'), t('memory.lede')), host);
  let kind = 'todas';

  asyncView(host, () => ctx.source.listMemory(), (records) => {
    const sources = [...new Set(records.map((r) => r.source))].sort();
    const toolbar = h('form', { class: 'toolbar', attrs: { role: 'search', 'aria-label': t('memory.filter.label') }, on: { submit: (e) => e.preventDefault() } },
      field({ name: 'q', label: t('memory.filter.search'), type: 'search', value: match.query.get('q') || '', placeholder: t('memory.filter.searchPlaceholder'), className: 'grow' }),
      field({ name: 'source', label: t('memory.filter.source'), type: 'select', value: '', options: [{ value: '', label: t('common.all') }, ...sources.map((s) => ({ value: s, label: s }))] }),
      field({ name: 'sort', label: t('memory.filter.sort'), type: 'select', value: 'relevance', options: [{ value: 'relevance', label: t('memory.sort.relevance') }, { value: 'date', label: t('memory.sort.date') }] }),
      checkbox(t('memory.filter.archived'), 'archived', false));
    const count = h('p', { class: 'small muted', attrs: { 'aria-live': 'polite', 'data-count': '' } });
    const list = h('ul', { class: 'memory-list', attrs: { 'aria-label': t('memory.results') } });
    const counts = (/** @type {string} */ k) => records.filter((r) => k === 'todas' || r.kind === k).length;
    const tabBar = tabs({ label: t('memory.kinds'), selected: kind, onChange: (id) => { kind = id; draw(); },
      tabs: ['todas', 'trabajo', 'episodica', 'semantica'].map((k) => ({ id: k, label: `${t('memory.kind.' + k)} (${counts(k)})` })) });

    /** @param {MemoryRecord} record */
    const card = (record) => {
      const archiveButton = h('button', { class: 'btn btn-sm', attrs: { type: 'button', disabled: !record.archivable || !ctx.source.capabilities.memoryArchive, 'data-action': 'archive',
        title: record.archivable && ctx.source.capabilities.memoryArchive ? '' : t('memory.notArchivable') },
        on: { click: async () => {
          const answer = await confirmDialog({ title: record.archived ? t('memory.restoreTitle') : t('memory.archiveTitle'), message: record.title,
            consequence: record.archived ? t('memory.restoreConsequence') : t('memory.archiveConsequence'), confirmLabel: record.archived ? t('memory.restore') : t('memory.archive'), danger: !record.archived });
          if (!answer.confirmed) return;
          try {
            const updated = await ctx.source.archiveMemory(record.id);
            Object.assign(record, updated);
            toast(updated.archived ? t('memory.archived') : t('memory.restored'), 'ok');
            draw();
          } catch (error) {
            toast(errorMessage(error), 'risk');
          }
        } } }, record.archived ? t('memory.restore') : t('memory.archive'));
      const open = h('button', { class: 'btn btn-sm', attrs: { type: 'button', 'data-action': 'open-memory' }, on: { click: () => openRecord(record) } }, t('memory.open'));
      return h('li', { class: `memory-card${record.archived ? ' archived' : ''}`, attrs: { 'data-memory': record.id } },
        h('div', { class: 'row-between' }, h('h3', null, record.title), h('span', { class: 'row' },
          statusBadge(record.kind === 'trabajo' ? 'live' : record.kind === 'episodica' ? 'warn' : 'ok', t('memory.kind.' + record.kind)),
          record.archived ? statusBadge('idle', t('memory.archivedBadge')) : null)),
        h('p', { class: 'small muted' }, `${record.source} · ${formatDateTime(record.createdAt)}${record.path ? ' · ' + record.path : ''}`),
        record.content ? h('p', { class: 'memory-preview' }, record.content.length > 220 ? record.content.slice(0, 219) + '…' : record.content) : h('p', { class: 'small muted' }, t('memory.contentOnDemand')),
        h('div', { class: 'row-between' },
          h('div', { class: 'row' }, h('span', { class: 'xsmall muted' }, t('memory.relevance')),
            h('span', { class: 'meter relevance', attrs: { role: 'meter', 'aria-valuemin': '0', 'aria-valuemax': '1', 'aria-valuenow': String(record.relevance), 'aria-label': t('memory.relevance') } },
              h('span', { attrs: { style: `width:${Math.round(record.relevance * 100)}%` } })),
            h('span', { class: 'xsmall' }, formatPercent(record.relevance))),
          h('div', { class: 'row' }, open, archiveButton)),
        record.tags.length ? h('div', { class: 'chip-list' }, record.tags.map(chip)) : null);
    };

    const draw = () => {
      const v = formValues(toolbar);
      const rows = records.filter((r) => (kind === 'todas' || r.kind === kind) && (v.archived === 'true' || !r.archived) && (!v.source || r.source === v.source) && memoryMatches(r, v.q))
        .sort((a, b) => v.sort === 'date' ? b.createdAt.localeCompare(a.createdAt) : b.relevance - a.relevance);
      count.textContent = t('memory.count', { shown: rows.length, total: records.length });
      mount(list, rows.length ? rows.map(card) : [h('li', null, emptyState({ title: t('memory.noMatch'), text: t('memory.noMatchText') }))]);
    };
    toolbar.addEventListener('input', draw);
    toolbar.addEventListener('change', draw);
    draw();
    return [
      ctx.source.mode === 'real' ? alertBox('idle', t('memory.realNote'), h('a', { attrs: { href: '/cmh' } }, t('memory.openLegacy'))) : null,
      panel({ title: t('memory.store'), origin: records[0]?.origin || ctx.source.mode, help: t('memory.storeHelp'), body: [tabBar, toolbar, count, list] }),
    ];
  }, { isEmpty: (r) => r.length === 0, empty: () => emptyState({ title: t('memory.empty') }) });

  /** @param {MemoryRecord} record */
  async function openRecord(record) {
    const body = h('div', { class: 'stack' }, skeleton(5));
    openModal({ title: record.title, body, wide: true });
    try {
      const full = record.content ? record : await ctx.source.readMemory(record.id);
      mount(body, definitionList([[t('memory.kindLabel'), t('memory.kind.' + full.kind)], [t('memory.filter.source'), full.source], [t('memory.date'), formatDateTime(full.createdAt)],
        [t('memory.relevance'), formatPercent(full.relevance)], [t('memory.path'), full.path ? h('code', null, full.path) : '—']]),
        h('pre', { class: 'code' }, full.content || t('memory.noContent')));
    } catch (error) {
      mount(body, alertBox('risk', t('state.errorTitle'), h('span', null, errorMessage(error))));
    }
  }
  return { el, title: t('memory.title') };
}
