// Drive Edge against a THROWAWAY Odysseus with a real session, in real mode.
// Everything here is synthetic: disposable instance, disposable account,
// invented data. The user's own instance on port 7000 is never contacted.
import { launchBrowser, sleep } from '../../../tests/cmh_os/e2e/cdp.mjs';

const [BASE, USER, PASS] = process.argv.slice(2);
if (!BASE || !USER || !PASS) throw new Error('uso: checks.mjs <url> <usuario> <clave>');

let passed = 0;
let failed = 0;
const { page, close } = await launchBrowser();

async function check(name, fn) {
  try {
    await fn();
    passed += 1;
    console.log(`  OK   ${name}`);
  } catch (error) {
    failed += 1;
    console.log(`  FALLA ${name}\n        ${error.message}`);
  }
}

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

const text = async (selector) => page.eval(`document.querySelector(${JSON.stringify(selector)})?.textContent || ''`);

// The harness' goto waits for data-ready, a marker only the Agentic OS page
// sets; Odysseus' own pages (login, shell) never set it. Navigate ourselves.
// page.waitFor wraps the expression in Boolean(...), and Boolean(<Promise>)
// is ALWAYS true — an async condition there can never fail. Poll with eval,
// which awaits the promise and returns its value.
async function waitUntil(asyncExpr, label, timeout = 20000) {
  const start = Date.now();
  let last;
  while (Date.now() - start < timeout) {
    last = await page.eval(asyncExpr).catch((e) => String(e));
    if (last === true) return;
    await sleep(150);
  }
  throw new Error(`no se cumplio: ${label} (ultimo: ${JSON.stringify(last)})`);
}

const runState = async () => JSON.parse(String(await page.eval(
  `fetch('/api/cmh/runs/run-sintetico').then((r) => r.json()).then((d) => JSON.stringify(d))`)));

let visits = 0;
async function visit(url, ready) {
  visits += 1;
  page.errors = [];
  const bust = `${url.includes('?') ? '&' : '?'}_v=${visits}`;
  const [base, hash = ''] = url.split('#');
  await page.eval(`location.href = ${JSON.stringify(base + bust + (hash ? '#' + hash : ''))}`).catch(() => {});
  await page.waitFor("document.readyState === 'complete'", 25000, `carga de ${url}`);
  if (ready) await page.waitFor(ready, 25000, `listo: ${url}`);
}

try {
  console.log('Sesion real contra el backend real (instancia desechable)');

  await check('Sin sesion, /cmh/os redirige al acceso', async () => {
    await visit(`${BASE}/cmh/os`);
    const url = await page.eval('location.pathname');
    expect(url === '/login', `esperaba /login, llego a ${url}`);
  });

  await check('Sin sesion, los activos de la pagina tampoco se sirven', async () => {
    const status = await page.eval(
      `fetch('/static/cmh-os/js/main.js', { redirect: 'manual' }).then((r) => r.status + ':' + r.type)`);
    expect(!String(status).startsWith('200:basic'), `main.js llego sin sesion: ${status}`);
  });

  await check('Inicio de sesion real: el navegador queda con cookie de sesion', async () => {
    await visit(`${BASE}/login`, `document.querySelector('#username')`);
    // Through the product's own login endpoint, from the page, so the browser
    // stores the Set-Cookie exactly as a form submit would. The form widget
    // itself is not what this run verifies.
    const body = await page.eval(
      `fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: ${JSON.stringify(USER)}, password: ${JSON.stringify(PASS)} }) })
        .then((r) => r.status + ':' + JSON.stringify(r.ok))`);
    expect(String(body).startsWith('200:'), `login devolvio ${body}`);
    const who = await page.eval(`fetch('/api/auth/status').then((r) => r.json()).then((d) => JSON.stringify(d))`);
    expect(/prueba/.test(String(who)), `sesion no establecida: ${who}`);
  });

  await check('Con sesion, /cmh/os carga la pagina entera', async () => {
    await visit(`${BASE}/cmh/os`, `document.documentElement.dataset.ready === 'true'`);
    await page.waitFor(`document.querySelector('h1')`, 20000, 'h1');
    const path = await page.eval('location.pathname');
    expect(path === '/cmh/os', `esperaba /cmh/os, quedo en ${path}`);
    const modules = await page.eval(
      `fetch('/static/cmh-os/js/main.js').then((r) => r.status)`);
    expect(modules === 200, `los modulos ES no cargan con sesion: ${modules}`);
  });

  await check('La interfaz se declara en MODO REAL, sin franja demo', async () => {
    await page.waitFor(`document.querySelector('[data-mode]')`, 20000, 'badge de modo');
    const mode = await page.eval(`document.querySelector('[data-mode]')?.dataset.mode`);
    expect(mode === 'real', `modo = ${mode}`);
    const demo = await page.eval(`document.querySelectorAll('[data-banner="demo"]').length`);
    expect(demo === 0, `hay ${demo} franjas demo en modo real`);
  });

  await check('Los agentes sembrados llegan desde el backend real', async () => {
    await page.eval(`location.hash = '#/agentes'`);
    await page.waitFor(`/CMH Investigaci/.test(document.body.textContent || '')`, 20000, 'agente sintetico');
    const body = await text('body');
    expect(/CMH Revisi/.test(body), 'falta el agente revisor');
  });

  await check('La ejecucion sembrada aparece esperando aprobacion', async () => {
    await page.eval(`location.hash = '#/ejecuciones'`);
    await page.waitFor(`/Esperando aprobaci/.test(document.body.textContent || '')`, 20000, 'estado');
  });

  await check('Rechazo real: exige justificacion, llama al endpoint nativo y termina la ejecucion', async () => {
    await page.eval(`location.hash = '#/aprobaciones'`);
    await page.waitFor(`document.querySelector('[data-action="reject"]')`, 20000, 'boton rechazar');
    await page.click('[data-action="reject"]');
    await sleep(500);
    const early = (await runState()).status;
    expect(early === 'waiting_approval', `rechazar sin justificacion cambio el estado a ${early}`);
    const dialogAfterEmpty = await page.eval(`document.querySelectorAll('dialog[open]').length`);
    expect(dialogAfterEmpty === 0, 'sin justificacion no deberia abrirse el dialogo de confirmacion');

    await page.fill('[data-form="decision"] textarea', 'El artefacto no cita la evidencia medida.');
    await page.click('[data-action="reject"]');
    await waitUntil(`Promise.resolve(document.querySelectorAll('dialog[open]').length === 1)`, 'dialogo de confirmacion');
    await page.click('dialog[open] [data-action="confirm"]');
    await waitUntil(
      `fetch('/api/cmh/runs/run-sintetico').then((r) => r.json()).then((d) => d.status === 'rejected')`,
      'la ejecucion queda rechazada');
  });

  await check('La decision quedo guardada en el servidor, no en el navegador', async () => {
    const raw = await page.eval(
      `fetch('/api/cmh/runs/run-sintetico').then((r) => r.json()).then((d) => JSON.stringify(d.steps.find((s) => s.key === 'revisor')))`);
    const step = JSON.parse(String(raw));
    expect(step.status === 'rejected', `estado del paso: ${step.status}`);
    expect(step.decision && step.decision.outcome === 'rejected', 'sin decision persistida');
    expect(step.decision.justification === 'El artefacto no cita la evidencia medida.',
           `justificacion: ${step.decision && step.decision.justification}`);
    expect(step.decision.by === 'prueba', `autor: ${step.decision && step.decision.by}`);
  });

  // Everything from here on provokes errors on purpose (409s), so judge the
  // console on what happened up to the rejection.
  const consoleUpToRejection = page.errors.slice();

  await check('Una ejecucion rechazada no se reanuda ni se decide otra vez', async () => {
    const resume = await page.eval(
      `fetch('/api/cmh/runs/run-sintetico/resume', { method: 'POST' }).then((r) => r.status)`);
    const again = await page.eval(
      `fetch('/api/cmh/runs/run-sintetico/steps/revisor/approve', { method: 'POST' }).then((r) => r.status)`);
    expect(resume === 409, `resume devolvio ${resume}`);
    expect(again === 409, `approve devolvio ${again}`);
  });

  await check('El artefacto ya producido sobrevive al rechazo', async () => {
    const count = await page.eval(
      `fetch('/api/cmh/runs/run-sintetico').then((r) => r.json()).then((d) => d.artifacts.length)`);
    expect(count === 1, `artefactos tras el rechazo: ${count}`);
  });

  await check('Sin errores de consola en la pagina autenticada', async () => {
    const errors = consoleUpToRejection.filter((e) => !/favicon|chromedevtools/i.test(e));
    expect(errors.length === 0, `errores: ${errors.slice(0, 3).join(' | ')}`);
  });
} finally {
  await close();
}

console.log(`\nmodo real: ${passed + failed} comprobaciones, ${passed} pasaron, ${failed} fallaron`);
process.exit(failed ? 1 : 0);
