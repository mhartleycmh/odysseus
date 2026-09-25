// Minimal Chrome DevTools Protocol client for headless Edge/Chrome, using the
// WebSocket and fetch built into Node 24 (no Playwright/Puppeteer install).
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CANDIDATES = [
  process.env.CMH_OS_BROWSER,
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/microsoft-edge',
].filter(Boolean);

/** @param {number} ms */
export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function launchBrowser() {
  const executable = CANDIDATES.find((path) => existsSync(path));
  if (!executable) throw new Error('No Chromium-based browser found; set CMH_OS_BROWSER');
  const port = 9400 + Math.floor(Math.random() * 400);
  const profile = mkdtempSync(join(tmpdir(), 'cmh-os-e2e-'));
  const child = spawn(executable, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--no-first-run',
    '--no-default-browser-check', '--disable-extensions', '--disable-gpu', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  let targets = null;
  for (let i = 0; i < 80 && !targets; i += 1) {
    await sleep(150);
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); } catch { targets = null; }
  }
  if (!targets) { child.kill(); throw new Error('Browser did not expose DevTools'); }
  const target = targets.find((t) => t.type === 'page');
  const page = await Page.connect(target.webSocketDebuggerUrl);
  return {
    page,
    async close() {
      page.close();
      child.kill();
      await sleep(300);
      try { rmSync(profile, { recursive: true, force: true }); } catch { /* profile files may still be locked on Windows */ }
    },
  };
}

export class Page {
  /** @param {WebSocket} ws */
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    /** @type {Map<number, {resolve: (v: unknown) => void, reject: (e: Error) => void}>} */
    this.pending = new Map();
    /** @type {string[]} */
    this.errors = [];
    /** @type {string[]} */
    this.warnings = [];
    ws.onmessage = (event) => {
      const message = JSON.parse(String(event.data));
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message));
        else resolve(message.result);
      } else if (message.method === 'Runtime.exceptionThrown') {
        this.errors.push(message.params.exceptionDetails?.exception?.description || message.params.exceptionDetails?.text || 'exception');
      } else if (message.method === 'Runtime.consoleAPICalled') {
        const text = message.params.args.map((a) => a.value ?? a.description ?? '').join(' ');
        if (message.params.type === 'error') this.errors.push(text);
        if (message.params.type === 'warning') this.warnings.push(text);
      } else if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') {
        this.errors.push(`${message.params.entry.source}: ${message.params.entry.text} ${message.params.entry.url || ''}`);
      }
    };
  }

  /** @param {string} url */
  static async connect(url) {
    const ws = new WebSocket(url);
    await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
    const page = new Page(ws);
    await page.send('Runtime.enable');
    await page.send('Log.enable');
    await page.send('Page.enable');
    return page;
  }

  /** @param {string} method @param {Record<string, unknown>} [params] */
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); } }, 30000);
    });
  }

  close() {
    this.ws.close();
  }

  /** Evaluate an expression (may return a promise) and return its JSON value. @param {string} expression */
  async eval(expression) {
    const result = /** @type {any} */ (await this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }));
    if (result.exceptionDetails) throw new Error(`eval failed: ${result.exceptionDetails.exception?.description || result.exceptionDetails.text}\n${expression.slice(0, 300)}`);
    return result.result.value;
  }

  /** Always a full page load: a hash-only change would keep the old document. @param {string} url */
  async goto(url) {
    this.errors = [];
    this.loads = (this.loads || 0) + 1;
    const [base, hash = ''] = url.split('#');
    const busted = `${base}${base.includes('?') ? '&' : '?'}_load=${this.loads}${hash ? '#' + hash : ''}`;
    await this.send('Page.navigate', { url: busted });
    await this.waitFor("document.readyState === 'complete' && document.documentElement.dataset.ready === 'true'", 20000, `load ${url}`);
  }

  /** @param {string} expression @param {number} [timeout] @param {string} [label] */
  async waitFor(expression, timeout = 10000, label = expression) {
    const start = Date.now();
    let last;
    while (Date.now() - start < timeout) {
      try { last = await this.eval(`Boolean(${expression})`); } catch (error) { last = String(error); }
      if (last === true) return;
      await sleep(80);
    }
    throw new Error(`Timed out waiting for: ${label} (last: ${last})`);
  }

  /** @param {string} selector */
  async click(selector) {
    await this.waitFor(`document.querySelector(${JSON.stringify(selector)})`, 10000, `click target ${selector}`);
    await this.eval(`document.querySelector(${JSON.stringify(selector)}).click()`);
  }

  /** Set a form control value and fire input/change like a user would. @param {string} selector @param {string} value */
  async fill(selector, value) {
    await this.waitFor(`document.querySelector(${JSON.stringify(selector)})`, 10000, `fill target ${selector}`);
    await this.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); el.focus(); el.value = ${JSON.stringify(value)};
      el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  }

  /** @param {string} key e.g. 'Escape', 'Tab', 'Enter' */
  async press(key) {
    const codes = { Escape: 27, Tab: 9, Enter: 13, ArrowRight: 39, ArrowLeft: 37 };
    const code = codes[key] || 0;
    await this.send('Input.dispatchKeyEvent', { type: 'keyDown', key, code: key, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code });
    await this.send('Input.dispatchKeyEvent', { type: 'keyUp', key, code: key, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code });
  }

  /** @param {number} width @param {number} height */
  async viewport(width, height) {
    await this.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 640 });
  }

  /** @param {string} path */
  async screenshot(path) {
    const result = /** @type {any} */ (await this.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }));
    writeFileSync(path, Buffer.from(result.data, 'base64'));
  }
}
