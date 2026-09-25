// End-to-end, component, accessibility and responsive tests in headless Edge.
//   bash scripts/cmh_os/node.sh tests/cmh_os/e2e/run.mjs [--screens]
// Exit code 0 only when every check passes. Screenshots go to data/cmh-os-screens/.
import { mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { startServer } from '../../../scripts/cmh_os/serve.mjs';
import { launchBrowser, sleep } from './cdp.mjs';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const screensDir = join(repo, 'data', 'cmh-os-screens');
const takeScreens = process.argv.includes('--screens');
mkdirSync(screensDir, { recursive: true });

const ROUTES = ['/', '/orquestacion', '/ejecuciones', '/aprobaciones', '/agentes', '/herramientas', '/memoria', '/observabilidad',
                '/evaluaciones', '/seguridad', '/configuracion', '/ayuda', '/agentes/ag-coordinador', '/ejecuciones/ex-001', '/observabilidad/ex-001'];
const NAV = { overview: 'Vista general', orchestration: 'Orquestación', executions: 'Ejecuciones', approvals: 'Aprobaciones', agents: 'Centro de agentes',
              tools: 'Herramientas e integraciones', memory: 'Memoria', observability: 'Observabilidad', evaluations: 'Evaluaciones', security: 'Seguridad',
              settings: 'Configuración', help: 'Ayuda' };

/** @type {{name: string, ok: boolean, ms: number, error?: string}[]} */
const results = [];
/** @param {string} name @param {() => Promise<void>} fn */
async function check(name, fn) {
  const started = Date.now();
  try {
    // A failed check must not leave a dialog open for the next one.
    await page.eval(`document.querySelectorAll('dialog[open]').forEach((d) => d.close())`).catch(() => {});
    await fn();
    results.push({ name, ok: true, ms: Date.now() - started });
    process.stdout.write(`  ✔ ${name}\n`);
  } catch (error) {
    results.push({ name, ok: false, ms: Date.now() - started, error: error instanceof Error ? error.message : String(error) });
    process.stdout.write(`  ✖ ${name}\n      ${String(error instanceof Error ? error.message : error).split('\n')[0]}\n`);
  }
}
/** @param {boolean} condition @param {string} message */
function expect(condition, message) {
  if (!condition) throw new Error(message);
}

const demoServer = await startServer({});
const apiServer = await startServer({ api: true });
// A second fake backend with its own state: rejecting run-1 is terminal, so it
// cannot share the instance the approval check consumes.
const rejectServer = await startServer({ api: true });
const browser = await launchBrowser();
const page = browser.page;
const DEMO = `${demoServer.url}/cmh/os?modo=demo&velocidad=rapida`;

/** Navigate by hash and wait until the view finished loading. @param {string} hash */
async function route(hash) {
  await page.eval(`location.hash = ${JSON.stringify(hash)}`);
  await page.waitFor(`document.querySelector('main h1') && !document.querySelector('.view-host .skeleton')`, 10000, `view ${hash}`);
}
const text = (/** @type {string} */ selector) => page.eval(`document.querySelector(${JSON.stringify(selector)})?.textContent?.trim() ?? null`);
const count = (/** @type {string} */ selector) => page.eval(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
const noErrors = (/** @type {string} */ where) => {
  const errors = page.errors.filter((e) => !/favicon/.test(e));
  page.errors = [];
  expect(errors.length === 0, `${where}: console errors ${JSON.stringify(errors.slice(0, 3))}`);
};

try {
  await page.viewport(1440, 1000);
  await page.goto(`${DEMO}#/`);

  console.log('Componentes (en el navegador)');
  await check('h() asigna solo texto y bloquea URL javascript:', async () => {
    const r = await page.eval(`import('/static/cmh-os/js/core/dom.js').then(({ h }) => {
      const el = h('a', { attrs: { href: 'javascript:alert(1)', title: 'x' } }, '<img src=x onerror=alert(1)>');
      const ok = h('a', { attrs: { href: '#/agentes' } }, 'ok');
      return { href: el.getAttribute('href'), children: el.children.length, text: el.textContent, safe: ok.getAttribute('href') };
    })`);
    expect(r.href === null && r.children === 0 && r.text.startsWith('<img') && r.safe === '#/agentes', JSON.stringify(r));
  });
  await check('dataTable ordena por columna y abre filas con Enter', async () => {
    const r = await page.eval(`import('/static/cmh-os/js/components/table.js').then(({ dataTable }) => {
      let opened = null;
      const el = dataTable({ caption: 'c', rowKey: (r) => r.n, rows: [{ n: 'b', v: 2 }, { n: 'a', v: 3 }, { n: 'c', v: 1 }], onOpen: (r) => { opened = r.n; },
        columns: [{ key: 'n', label: 'N', sort: (r) => r.n, render: (r) => r.n }, { key: 'v', label: 'V', num: true, sort: (r) => r.v, render: (r) => String(r.v) }] });
      document.body.append(el);
      const order = () => [...el.querySelectorAll('tbody tr')].map((tr) => tr.dataset.row).join('');
      const initial = order();
      el.querySelector('th[data-key="v"] button').click();
      const asc = order();
      el.querySelector('th[data-key="v"] button').click();
      const desc = order();
      const sortAttr = el.querySelector('th[data-key="v"]').getAttribute('aria-sort');
      el.querySelector('tbody tr').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      el.remove();
      return { initial, asc, desc, sortAttr, opened };
    })`);
    expect(r.initial === 'bac' && r.asc === 'cba' && r.desc === 'abc' && r.sortAttr === 'descending' && r.opened === 'a', JSON.stringify(r));
  });
  await check('confirmDialog: Esc cancela y el foco vuelve al disparador', async () => {
    await page.eval(`(() => { const b = document.createElement('button'); b.id = 'opener'; b.textContent = 'abrir'; document.body.append(b); b.focus();
      window.__confirm = import('/static/cmh-os/js/components/modal.js').then(({ confirmDialog }) => confirmDialog({ title: 't', message: 'm', confirmLabel: 'ok' })); })()`);
    await page.waitFor(`document.querySelector('dialog[open]')`);
    await page.press('Escape');
    const r = await page.eval(`window.__confirm.then((a) => ({ confirmed: a.confirmed, open: !!document.querySelector('dialog[open]'), focus: document.activeElement?.id }))`);
    await page.eval(`document.getElementById('opener').remove()`);
    expect(r.confirmed === false && r.open === false && r.focus === 'opener', JSON.stringify(r));
  });
  await check('confirmDialog con justificación exige el mínimo antes de confirmar', async () => {
    await page.eval(`void (window.__just = import('/static/cmh-os/js/components/modal.js').then(({ confirmDialog }) => confirmDialog({ title: 't', message: 'm', confirmLabel: 'ok', justification: { label: 'Por qué', minLength: 10 } })))`);
    await page.click('dialog[open] [data-action="confirm"]');
    const invalid = await page.eval(`document.querySelector('dialog[open] textarea').getAttribute('aria-invalid')`);
    await page.fill('dialog[open] textarea', 'Justificación suficiente');
    await page.click('dialog[open] [data-action="confirm"]');
    const r = await page.eval(`window.__just`);
    expect(invalid === 'true' && r.confirmed && r.justification === 'Justificación suficiente', JSON.stringify({ invalid, r }));
  });
  await check('asyncView muestra error con reintento y se recupera', async () => {
    const r = await page.eval(`import('/static/cmh-os/js/components/states.js').then(async ({ asyncView }) => {
      const host = document.createElement('div'); document.body.append(host);
      let calls = 0;
      asyncView(host, async () => { calls += 1; if (calls === 1) throw new Error('fallo'); return 'listo'; }, (d) => d);
      await new Promise((r) => setTimeout(r, 50));
      const errorShown = !!host.querySelector('[role="alert"]');
      host.querySelector('[data-action="retry"]').click();
      await new Promise((r) => setTimeout(r, 50));
      const text = host.textContent; host.remove();
      return { errorShown, text, calls };
    })`);
    expect(r.errorShown && r.text === 'listo' && r.calls === 2, JSON.stringify(r));
  });
  noErrors('componentes');

  console.log('Flujos obligatorios (modo demo)');
  await check('F1 navegar por los 12 módulos desde el menú', async () => {
    for (const [name, title] of Object.entries(NAV)) {
      await page.click(`a[data-nav="${name}"]`);
      await page.waitFor(`document.querySelector('main h1')?.textContent === ${JSON.stringify(title)} && !document.querySelector('.view-host .skeleton')`, 10000, `module ${name}`);
      const current = await page.eval(`document.querySelector('a[aria-current="page"]')?.dataset.nav`);
      expect(current === name, `aria-current on ${current}, expected ${name}`);
    }
    await route('#/no-existe');
    expect((await text('main h1')) === 'Página no encontrada', 'unknown route shows not found');
    noErrors('F1');
  });

  let agentId = '';
  await check('F2 crear y editar un agente con validación', async () => {
    await route('#/agentes');
    await page.click('[data-action="create-agent"]');
    await page.waitFor(`document.querySelector('dialog[open] [data-form="agent"]')`);
    await page.click('dialog[open] .modal-footer .btn-primary');
    const invalid = await page.eval(`['name','role','instructions'].map((n) => document.querySelector('dialog[open] [name="' + n + '"]').getAttribute('aria-invalid'))`);
    expect(invalid.every((v) => v === 'true'), `empty form must be invalid: ${invalid}`);
    await page.fill('dialog[open] [name="name"]', 'Agente de pruebas E2E');
    await page.fill('dialog[open] [name="role"]', 'Verificación automatizada');
    await page.fill('dialog[open] [name="instructions"]', 'Leer solo archivos sintéticos y reportar evidencia.');
    await page.fill('dialog[open] [name="workspace"]', 'relativa/no-valida');
    await page.click('dialog[open] .modal-footer .btn-primary');
    expect((await page.eval(`document.querySelector('dialog[open] [name="workspace"]').getAttribute('aria-invalid')`)) === 'true', 'workspace pattern enforced');
    await page.fill('dialog[open] [name="workspace"]', '');
    await page.click('dialog[open] .modal-footer .btn-primary');
    await page.waitFor(`location.hash.startsWith('#/agentes/ag-') && document.querySelector('main h1')?.textContent === 'Agente de pruebas E2E'`, 10000, 'agent detail');
    agentId = await page.eval(`decodeURIComponent(location.hash.split('/')[2])`);
    await page.waitFor(`!document.querySelector('.view-host .skeleton')`);
    await page.click('[data-action="edit-agent"]');
    await page.waitFor(`document.querySelector('dialog[open] [name="instructions"]')`);
    await page.fill('dialog[open] [name="instructions"]', 'Instrucciones revisadas: leer, contrastar y citar la fuente.');
    await page.click('dialog[open] .modal-footer .btn-primary');
    await page.waitFor(`!document.querySelector('dialog[open]') && document.querySelector('main')?.textContent.includes('v2')`, 10000, 'instructions version 2');
    noErrors('F2');
  });

  let runId = '';
  await check('F3 iniciar una ejecución y ver a los agentes moverse', async () => {
    await route('#/ejecuciones');
    await page.click('[data-action="new-execution"]');
    await page.waitFor(`document.querySelector('dialog[open] [data-form="execution"]')`);
    await page.click('dialog[open] .modal-footer .btn-primary');
    expect((await page.eval(`document.querySelector('dialog[open] [name="objective"]').getAttribute('aria-invalid')`)) === 'true', 'objective required');
    await page.fill('dialog[open] [name="workflowId"]', 'wf-operacion');
    await page.fill('dialog[open] [name="objective"]', 'Revisión E2E del turno con evidencia trazable');
    await page.fill('dialog[open] [name="budgetUsd"]', '5');
    await page.click('dialog[open] .modal-footer .btn-primary');
    await page.waitFor(`location.hash.startsWith('#/orquestacion/ex-')`, 10000, 'orchestration of new run');
    runId = await page.eval(`decodeURIComponent(location.hash.split('/')[2])`);
    await page.waitFor(`document.querySelector('.graph-node[data-status="running"]')`, 10000, 'a node running');
    await page.waitFor(`document.querySelector('.graph-particle') || document.querySelector('.graph-orbit-dot')`, 10000, 'movement: particle or tool orbit');
    await page.waitFor(`document.querySelector('.graph-phase[data-active="true"]')`, 10000, 'agent loop phase highlighted');
    await page.waitFor(`document.querySelector('.graph-node[data-node="seguridad"][data-status="waiting_approval"]')`, 20000, 'seguridad waits for approval');
    noErrors('F3');
  });

  await check('F4 consultar pasos, herramientas y eventos de la ejecución', async () => {
    await route(`#/ejecuciones/${runId}`);
    await page.waitFor(`document.querySelectorAll('.timeline-item').length > 10`, 10000, 'timeline filled');
    const steps = await count('[data-view="execution"] tbody tr');
    const tools = await count('[data-view="execution"] .chip');
    const answer = await text('[data-block="answer"]');
    expect(steps >= 7, `7 steps expected, got ${steps}`);
    expect(tools > 0, 'tool chips visible');
    expect(/aprobación/.test(answer || ''), `answer panel explains the wait: ${answer}`);
    noErrors('F4');
  });

  await check('F5 revisar la solicitud de aprobación con riesgo e impacto', async () => {
    await route(`#/aprobaciones?id=apr-${runId}-seguridad`);
    await page.waitFor(`document.querySelector('[data-block="approval-detail"] h2')?.textContent.includes('Seguridad')`, 10000, 'detail of the step approval');
    const detail = await text('[data-block="approval-detail"]');
    expect(/Riesgo alto/.test(detail) && /Impacto si apruebas/.test(detail) && /detiene la ejecución/.test(detail), 'risk, impact and reject effect shown');
    noErrors('F5');
  });

  await check('F6 aprobar con justificación y ver la ejecución completarse', async () => {
    await page.click('[data-action="approve"]');
    const error = await text('[data-form="decision"] .field-error');
    expect(/justificar/.test(error || ''), `high risk needs a reason: ${error}`);
    await page.fill('[data-form="decision"] textarea', 'Hallazgo verificado contra el registro de incidentes.');
    await page.click('[data-action="approve"]');
    await page.waitFor(`document.querySelector('dialog[open] [data-action="confirm"]')`);
    await page.click('dialog[open] [data-action="confirm"]');
    await page.waitFor(`[...document.querySelectorAll('.toast')].some((t) => /aprobada/.test(t.textContent))`, 10000, 'approval toast');
    await page.waitFor(`document.querySelector('[data-view="approvals"]')?.textContent.includes('Hallazgo verificado')`, 10000, 'history shows the justification');
    await route(`#/ejecuciones/${runId}`);
    await page.waitFor(`document.querySelector('[data-final-answer]')`, 20000, 'final answer after approval');
    expect((await text('[data-final-answer]')).includes('Sostenibilidad'), 'final answer comes from the last step');
    await route('#/seguridad');
    expect((await text('[data-view="security"]')).includes('Local (este navegador)'), 'decision recorded in the local audit trail');
    noErrors('F6');
  });

  await check('F6b rechazar exige justificación', async () => {
    await route('#/aprobaciones?id=apr-tool-correo');
    await page.waitFor(`document.querySelector('[data-block="approval-detail"] h2')?.textContent.includes('correo')`);
    await page.click('[data-action="reject"]');
    expect(/justificación/.test((await text('[data-form="decision"] .field-error')) || ''), 'reject without reason blocked');
    await page.fill('[data-form="decision"] textarea', 'El comité aún no revisó el informe.');
    await page.click('[data-action="reject"]');
    await page.click('dialog[open] [data-action="confirm"]');
    await page.waitFor(`[...document.querySelectorAll('.toast')].some((t) => /rechazada/.test(t.textContent))`, 10000, 'reject toast');
    noErrors('F6b');
  });

  await check('F7 buscar en memoria y archivar con confirmación', async () => {
    await route('#/memoria');
    await page.fill('[data-view="memory"] input[name="q"]', 'presupuesto');
    const summary = await text('[data-view="memory"] [data-count]');
    expect(/Mostrando [1-9]/.test(summary) && (await count('.memory-card')) >= 1, `search result: ${summary}`);
    await page.fill('[data-view="memory"] input[name="q"]', '');
    const canonDisabled = await page.eval(`document.querySelector('[data-memory="mem-canon-05"] [data-action="archive"]').disabled`);
    expect(canonDisabled, 'canon files cannot be archived');
    await page.click('[data-memory="mem-ep-1"] [data-action="archive"]');
    await page.click('dialog[open] [data-action="confirm"]');
    await page.waitFor(`!document.querySelector('[data-memory="mem-ep-1"]')`, 10000, 'archived record hidden by default');
    await page.click('[data-view="memory"] input[name="archived"]');
    await page.waitFor(`document.querySelector('[data-memory="mem-ep-1"].archived')`, 10000, 'archived record visible with filter');
    await page.click('[data-view="memory"] [data-tab="semantica"]');
    expect(!(await page.eval(`!!document.querySelector('[data-memory="mem-ep-1"]')`)), 'semantic tab hides episodic records');
    noErrors('F7');
  });

  await check('F8 filtros de observabilidad y cascada de una traza', async () => {
    await route('#/observabilidad');
    const all = await text('[data-view="observability"] [data-count]');
    await page.fill('[data-view="observability"] select[name="status"]', 'error');
    const filtered = await text('[data-view="observability"] [data-count]');
    expect(all !== filtered && /Mostrando [0-9]+ de/.test(filtered), `${all} → ${filtered}`);
    const rows = await page.eval(`[...document.querySelectorAll('[data-view="observability"] tbody tr[data-row]')].length`);
    expect(rows >= 1, 'at least one failed trace');
    await page.click('[data-view="observability"] tbody tr[data-row]');
    await page.waitFor(`location.hash.startsWith('#/observabilidad/ex-') && document.querySelectorAll('.wf-row').length > 3`, 10000, 'waterfall rows');
    noErrors('F8');
  });

  await check('F9 cambiar configuración sin exponer secretos', async () => {
    await route('#/configuracion');
    await page.fill('[data-form="settings"] select[name="theme"]', 'dark');
    await page.click('[data-view="settings"] input[name="simulateFailures"]');
    await page.fill('[data-form="settings"] input[name="maxIterations"]', '999');
    await page.click('[data-action="save-settings"]');
    expect((await page.eval(`document.querySelector('[name="maxIterations"]').getAttribute('aria-invalid')`)) === 'true', 'limits validated');
    await page.fill('[data-form="settings"] input[name="maxIterations"]', '20');
    await page.click('[data-action="save-settings"]');
    await page.waitFor(`document.documentElement.dataset.theme === 'dark'`, 5000, 'dark theme applied');
    const dom = await page.eval(`document.documentElement.outerHTML`);
    expect(!/valor-secreto|sk-[A-Za-z0-9]{12,}/.test(dom), 'no secret values in the DOM');
    expect(dom.includes('••••'), 'keys shown masked');
    noErrors('F9');
  });

  await check('F10 recuperarse de un error simulado con Reintentar', async () => {
    await page.eval(`location.hash = '#/agentes'`);
    await page.waitFor(`document.querySelector('[data-view="agents"] [role="alert"] [data-action="retry"]')`, 10000, 'error state with retry');
    await page.click('[data-view="agents"] [data-action="retry"]');
    await page.waitFor(`document.querySelectorAll('[data-view="agents"] tbody tr[data-row]').length > 5`, 10000, 'recovered table');
    await route('#/configuracion');
    await page.click('[data-view="settings"] input[name="simulateFailures"]');
    await page.fill('[data-form="settings"] select[name="theme"]', 'light');
    await page.click('[data-action="save-settings"]');
    await page.waitFor(`document.documentElement.dataset.theme === 'light'`);
    page.errors = page.errors.filter((e) => !/Fallo transitorio simulado/.test(e));
    noErrors('F10');
  });

  await check('Chat: comandos, enlaces y detención solo con confirmación', async () => {
    await route('#/');
    await page.press('Escape');
    await page.eval(`document.activeElement?.blur(); document.body.focus()`);
    await page.send('Input.dispatchKeyEvent', { type: 'keyDown', key: '/', code: 'Slash', text: '/' });
    await page.send('Input.dispatchKeyEvent', { type: 'keyUp', key: '/', code: 'Slash' });
    await page.waitFor(`!document.getElementById('app-chat').hidden && document.activeElement?.classList.contains('chat-input')`, 5000, 'slash opens chat');
    await page.fill('.chat-input', 'estado');
    await page.eval(`document.querySelector('.chat-form').requestSubmit()`);
    await page.waitFor(`[...document.querySelectorAll('.chat-msg-bot')].some((m) => /aprobaciones pendientes/.test(m.textContent))`, 5000, 'status reply');
    await page.fill('.chat-input', '¿qué puedes hacer?');
    await page.eval(`document.querySelector('.chat-form').requestSubmit()`);
    await page.waitFor(`[...document.querySelectorAll('.chat-msg-bot')].some((m) => /Comandos disponibles/.test(m.textContent))`, 5000, 'help reply');
    await page.fill('.chat-input', 'ejecutar revisión operacional');
    await page.eval(`document.querySelector('.chat-form').requestSubmit()`);
    await page.waitFor(`document.querySelector('.chat-msg-bot:last-child [data-chat-action="navigate"]')`, 5000, 'start offers navigation');
    await page.click('.chat-msg-bot:last-child [data-chat-action="navigate"]');
    await page.waitFor(`document.querySelector('dialog[open] [data-form="execution"] select[name="workflowId"]')?.value === 'wf-operacion'`, 10000, 'form prefilled');
    await page.press('Escape');
    noErrors('chat');
  });

  console.log('Accesibilidad básica (15 rutas)');
  await check('A11y: un h1, landmarks, nombres accesibles, alt, ids únicos', async () => {
    const problems = [];
    for (const r of ROUTES) {
      await route('#' + r);
      const report = await page.eval(`(() => {
        // Form controls get their name from labels, never from their own text content.
        const isField = (el) => ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName);
        const name = (el) => (el.getAttribute('aria-label') || (el.getAttribute('aria-labelledby') || '').split(' ').map((id) => document.getElementById(id)?.textContent || '').join(' ')
          || (el.id && document.querySelector('label[for="' + el.id + '"]')?.textContent) || el.closest('label')?.textContent || el.getAttribute('title')
          || (isField(el) ? '' : el.textContent) || el.getAttribute('alt') || '').trim();
        const interactive = [...document.querySelectorAll('button, a[href], input, select, textarea, [role="button"], [tabindex="0"]')].filter((el) => !el.closest('[hidden]'));
        const unnamed = interactive.filter((el) => !name(el) && !(el.tagName === 'svg')).map((el) => el.outerHTML.slice(0, 80));
        const ids = [...document.querySelectorAll('[id]')].map((el) => el.id);
        const dupes = ids.filter((id, i) => ids.indexOf(id) !== i);
        return { h1: document.querySelectorAll('main h1').length, main: !!document.querySelector('main'), nav: !!document.querySelector('nav[aria-label]'),
                 header: !!document.querySelector('header'), skip: !!document.querySelector('.skip-link'), unnamed, dupes,
                 noAlt: [...document.querySelectorAll('img')].filter((i) => !i.hasAttribute('alt')).length, lang: document.documentElement.lang };
      })()`);
      if (report.h1 !== 1) problems.push(`${r}: ${report.h1} h1`);
      if (!report.main || !report.nav || !report.header || !report.skip) problems.push(`${r}: missing landmark`);
      if (report.unnamed.length) problems.push(`${r}: unnamed ${report.unnamed.slice(0, 2).join(' | ')}`);
      if (report.dupes.length) problems.push(`${r}: duplicate ids ${report.dupes.slice(0, 3).join(',')}`);
      if (report.noAlt) problems.push(`${r}: ${report.noAlt} img without alt`);
      if (report.lang !== 'es') problems.push(`${r}: lang ${report.lang}`);
    }
    expect(problems.length === 0, problems.join('\n'));
  });
  await check('A11y: el enlace de salto lleva el foco al contenido y hay estilo de foco', async () => {
    await page.goto(`${DEMO}#/`);
    await page.press('Tab');
    const first = await page.eval(`document.activeElement?.className`);
    await page.press('Enter');
    const focused = await page.eval(`document.activeElement?.id`);
    const focusRule = await page.eval(`[...document.styleSheets].some((s) => { try { return [...s.cssRules].some((r) => r.selectorText && r.selectorText.includes(':focus-visible')); } catch { return false; } })`);
    expect(first === 'skip-link' && focused === 'main' && focusRule, JSON.stringify({ first, focused, focusRule }));
  });
  await check('A11y: abrir un detalle con Enter lleva el foco a su h1', async () => {
    await route('#/agentes');
    await page.eval(`document.querySelector('[data-view="agents"] tbody tr[data-row]').focus()`);
    await page.press('Enter');
    await page.waitFor(`location.hash.startsWith('#/agentes/')`, 5000, 'detail route');
    const immediate = await page.eval(`document.querySelectorAll('main h1').length`);
    await page.waitFor(`!document.querySelector('.view-host .skeleton')`);
    const focus = await page.eval(`({ tag: document.activeElement?.tagName, text: document.activeElement?.textContent })`);
    expect(immediate === 1, `h1 exists while loading (${immediate})`);
    expect(focus.tag === 'H1', `focus on ${focus.tag}`);
    noErrors('focus');
  });
  await check('A11y: movimiento reducido detiene las partículas', async () => {
    await page.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
    await page.goto(`${DEMO}#/ejecuciones`);
    await page.waitFor(`document.documentElement.dataset.motion === 'reduced'`);
    await route('#/ejecuciones');
    await page.click('[data-action="new-execution"]');
    await page.waitFor(`document.querySelector('dialog[open] [data-form="execution"]')`);
    await page.fill('dialog[open] [name="workflowId"]', 'wf-operacion');
    await page.fill('dialog[open] [name="objective"]', 'Ejecución con movimiento reducido');
    await page.click('dialog[open] .modal-footer .btn-primary');
    await page.waitFor(`document.querySelector('.graph-node[data-status="running"]')`, 10000, 'running with reduced motion');
    let particles = 0;
    for (let i = 0; i < 12; i += 1) { particles += await count('.graph-particle'); await sleep(100); }
    expect(particles === 0, `${particles} particles seen with reduced motion`);
    await page.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
  });

  console.log('Responsive (390, 820, 1440)');
  for (const [width, height] of [[390, 844], [820, 1180], [1440, 1000]]) {
    await check(`Sin desbordamiento horizontal a ${width} px en 15 rutas`, async () => {
      await page.viewport(width, height);
      await page.goto(`${DEMO}#/`);
      const overflow = [];
      for (const r of ROUTES) {
        await route('#' + r);
        await sleep(150);
        const m = await page.eval(`({ sw: document.documentElement.scrollWidth, iw: window.innerWidth })`);
        if (m.sw > m.iw + 1) overflow.push(`${r} (${m.sw} > ${m.iw})`);
        if (takeScreens) await page.screenshot(join(screensDir, `${width}${r.replaceAll('/', '_') || '_inicio'}.png`));
      }
      expect(overflow.length === 0, overflow.join(', '));
      noErrors(`responsive ${width}`);
    });
  }
  await page.viewport(1440, 1000);

  console.log('Integración en modo real (API falsa con el contrato del backend)');
  await check('Detecta modo real, sin franja demo, con datos del backend', async () => {
    await page.goto(`${apiServer.url}/cmh/os#/agentes`);
    await route('#/agentes');
    expect((await page.eval(`document.querySelector('[data-mode]')?.dataset.mode`)) === 'real', 'real mode badge');
    expect((await count('[data-banner="demo"]')) === 0, 'no demo banner in real mode');
    expect((await text('[data-view="agents"] tbody')).includes('Investigador'), 'agents from the API');
    noErrors('live agents');
  });
  await check('Orquestación real reproduce eventos SSE y espera la aprobación', async () => {
    await route('#/orquestacion/run-1');
    await page.waitFor(`document.querySelector('.graph-node[data-node="revisor"][data-status="waiting_approval"]')`, 10000, 'revisor waiting');
    await page.waitFor(`document.querySelector('.graph-node[data-node="investigador"][data-status="completed"]')`);
    // Statuses come from the snapshot at once; tokens only exist in the SSE backlog.
    await page.waitFor(`/5,395/.test(document.querySelector('[data-block="global"]')?.textContent || '')`, 10000, 'tokens rebuilt from SSE model_metrics');
    await page.waitFor(`document.querySelector('.graph-node[data-node="investigador"]')?.getAttribute('aria-label')?.includes('1 herr.')`, 5000, 'tool call from SSE');
    noErrors('live orchestration');
  });
  await check('Aprobación real: la respuesta final llega en vivo con el artefacto nuevo', async () => {
    await route('#/aprobaciones?id=apr-run-1-revisor');
    await page.waitFor(`document.querySelector('[data-block="approval-detail"] h2')`);
    await page.click('[data-action="approve"]');
    await page.click('dialog[open] [data-action="confirm"]');
    await page.waitFor(`[...document.querySelectorAll('.toast')].some((t) => /aprobada/.test(t.textContent))`, 10000, 'toast');
    expect(apiServer.calls.includes('POST /api/cmh/runs/run-1/steps/revisor/approve'), 'approve endpoint called');
    // Open the detail while the step is still running (the fake completes it 1.5 s after approval),
    // so the final answer can only come from live events plus the artifact fetch.
    await route('#/ejecuciones/run-1');
    const badge = await text('[data-block="badges"]');
    expect(/En curso/.test(badge || ''), `detail must open before completion to test the live path (badge: ${badge})`);
    await page.waitFor(`document.querySelector('[data-final-answer]')?.textContent.includes('APROBADO con evidencia')`, 10000, 'final answer from the artifact fetched after step_completed');
    expect(!(await text('[data-final-answer]')).includes('Nota de investigación'), 'final answer is the reviewer artifact, not the researcher one');
    noErrors('live approval');
  });
  await check('Sin fugas: salir de una vista a medio cargar no deja streams abiertos', async () => {
    const openStreams = async () => (await (await fetch(`${apiServer.url}/api/__test/streams`)).json()).open;
    await route('#/ayuda');
    await sleep(300);
    const baseline = await openStreams();
    await fetch(`${apiServer.url}/api/__test/latency?ms=600`, { method: 'POST' });
    for (const hash of ['#/orquestacion/run-0', '#/ejecuciones/run-0', '#/']) {
      await page.eval(`location.hash = ${JSON.stringify(hash)}`);
      await sleep(120);
      await page.eval(`location.hash = '#/ayuda'`);
    }
    await sleep(2500);
    await fetch(`${apiServer.url}/api/__test/latency?ms=0`, { method: 'POST' });
    const after = await openStreams();
    expect(after === baseline, `open SSE streams: ${baseline} before, ${after} after leaving three half-loaded views`);
    noErrors('stream leak');
  });
  await check('Propuesta de memoria real: rechazo con justificación llama a reject', async () => {
    await route('#/aprobaciones?id=apr-mem-prop-1');
    await page.waitFor(`document.querySelector('[data-block="approval-detail"]')?.textContent.includes('Nuevo pendiente')`, 10000, 'diff shown');
    await page.fill('[data-form="decision"] textarea', 'La fila no cita su fuente.');
    await page.click('[data-action="reject"]');
    await page.click('dialog[open] [data-action="confirm"]');
    await page.waitFor(`[...document.querySelectorAll('.toast')].some((t) => /rechazada/.test(t.textContent))`, 10000, 'toast');
    expect(apiServer.calls.includes('POST /api/cmh/memory-proposals/prop-1/reject'), 'reject endpoint called');
    noErrors('live memory');
  });
  await check('Rechazo real de un paso: justificación obligatoria, endpoint nativo y ejecución terminada', async () => {
    await page.goto(`${rejectServer.url}/cmh/os#/aprobaciones?id=apr-run-1-revisor`);
    await route('#/aprobaciones?id=apr-run-1-revisor');
    await page.waitFor(`document.querySelector('[data-block="approval-detail"] h2')`, 10000, 'step approval detail');
    // Rejecting without a reason must not reach the backend at all.
    await page.click('[data-action="reject"]');
    expect(!rejectServer.calls.some((c) => c.includes('/reject')), 'no reject call without a justification');
    await page.fill('[data-form="decision"] textarea', 'El artefacto no cita la evidencia medida.');
    await page.click('[data-action="reject"]');
    await page.click('dialog[open] [data-action="confirm"]');
    await page.waitFor(`[...document.querySelectorAll('.toast')].some((t) => /rechazada/.test(t.textContent))`, 10000, 'toast');
    expect(rejectServer.calls.includes('POST /api/cmh/runs/run-1/steps/revisor/reject'), 'native step reject endpoint called');
    expect(!rejectServer.calls.includes('POST /api/cmh/runs/run-1/stop'), 'no longer falls back to stop');
    await route('#/ejecuciones/run-1');
    await page.waitFor(`/Rechazada/.test(document.querySelector('[data-block="badges"]')?.textContent || '')`, 10000, 'run shown as rejected');
    noErrors('live step rejection');
  });
  await check('Herramientas reales: variables MCP solo por nombre', async () => {
    await route('#/herramientas');
    const body = await text('[data-view="tools"]');
    expect(body.includes('API_TOKEN = ••••') && !/valor-secreto/.test(await page.eval(`document.documentElement.outerHTML`)), 'env masked');
    expect((await count('[data-view="tools"] .origin-real')) > 0, 'real data labelled as real');
    noErrors('live tools');
  });
  await check('Dominios sin backend se etiquetan «Demo · sin backend» en modo real', async () => {
    await route('#/evaluaciones');
    expect((await text('[data-view="evaluations"]')).includes('Demo · sin backend'), 'evaluations labelled as demo without backend');
    noErrors('live evaluations');
  });

  if (takeScreens) {
    await page.viewport(1440, 1000);
    await page.goto(`${DEMO}#/`);
    for (const [name, hash, wait] of [['overview', '#/', 1500], ['orchestration', '#/orquestacion/ex-005', 1500], ['approvals', '#/aprobaciones', 800],
                                      ['agents', '#/agentes', 800], ['observability', '#/observabilidad/ex-001', 800], ['memory', '#/memoria', 800]]) {
      await route(hash);
      await sleep(wait);
      await page.screenshot(join(screensDir, `final-${name}.png`));
    }
    await page.eval(`document.documentElement.dataset.theme = 'dark'`);
    await route('#/orquestacion/ex-005');
    await sleep(1200);
    await page.screenshot(join(screensDir, 'final-orchestration-dark.png'));
  }
} finally {
  await browser.close();
  await demoServer.close();
  await apiServer.close();
  await rejectServer.close();
}

const failed = results.filter((r) => !r.ok);
console.log(`\ne2e: ${results.length} checks, ${results.length - failed.length} passed, ${failed.length} failed`);
for (const f of failed) console.log(`FAILED ${f.name}\n  ${f.error}`);
process.exit(failed.length ? 1 : 0);
