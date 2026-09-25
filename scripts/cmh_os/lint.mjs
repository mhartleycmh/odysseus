// Lint rules for static/cmh-os that the type checker cannot express.
// Each rule names the reason it exists; a finding prints file:line and fails.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '../../static/cmh-os');
const args = process.argv.slice(2);
const target = args[0] ? resolve(args[0]) : root;

/** @type {{id: string, why: string, test: RegExp, only?: RegExp, except?: RegExp}[]} */
const RULES = [
  { id: 'no-unsafe-html', why: 'untrusted text must enter the DOM as textContent',
    test: /\.(innerHTML|outerHTML)\b|insertAdjacentHTML|document\.write/, only: /\.(js|html)$/ },
  { id: 'no-eval', why: 'CSP and code-injection safety', test: /\beval\s*\(|new\s+Function\s*\(/, only: /\.js$/ },
  { id: 'no-console-log', why: 'use the structured logger in core/log.js', test: /console\.log\s*\(/, only: /\.js$/,
    except: /core[\\/]log\.js$/ },
  { id: 'no-todo', why: 'no deferred work left in shipped code', test: /\b(TODO|FIXME|XXX)\b/ },
  { id: 'no-any', why: 'strict typing: name the type', test: /@(type|param|returns?|property)\s*\{[^}]*(\bany\b|\{\*\})/, only: /\.js$/ },
  { id: 'fetch-in-http-only', why: 'timeouts, retries and error typing live in services/http.js',
    test: /(^|[^.\w])fetch\s*\(/, only: /\.js$/, except: /services[\\/]http\.js$/ },
  { id: 'storage-in-storage-only', why: 'browser storage can throw; only core/storage.js guards it',
    test: /\b(localStorage|sessionStorage)\b/, only: /\.js$/, except: /core[\\/]storage\.js$/ },
  { id: 'colors-in-tokens-only', why: 'brand colors come from css/tokens.css',
    test: /#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?([0-9a-fA-F]{2})?\b(?![-\w])/, only: /\.(css|js)$/, except: /tokens\.css$/ },
  { id: 'no-secrets', why: 'no credentials in client code',
    test: /(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{8,}|ody_[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|(api[_-]?key|secret|password)\s*[:=]\s*['"][^'"\s]{8,}['"])/i },
  { id: 'no-inline-handlers', why: 'CSP forbids inline event handlers', test: /\son[a-z]+\s*=\s*["']/, only: /\.html$/ },
  { id: 'no-inline-script', why: 'CSP: scripts are external modules', test: /<script(?![^>]*\bsrc=)[^>]*>/, only: /\.html$/ },
];

/** @param {string} dir @returns {string[]} */
function walk(dir) {
  if (statSync(dir).isFile()) return [dir];
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (name === 'assets' || name === 'jsconfig.json') return [];
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

const files = walk(target).filter((f) => /\.(js|css|html)$/.test(f));
const findings = [];
for (const file of files) {
  const lines = readFileSync(file, 'utf8').split(/\r?\n/);
  for (const rule of RULES) {
    if (rule.only && !rule.only.test(file)) continue;
    if (rule.except && rule.except.test(file)) continue;
    lines.forEach((line, index) => {
      if (rule.id === 'colors-in-tokens-only' && /^\s*(\/\/|\*|\/\*)/.test(line)) return;
      if (rule.test.test(line)) findings.push(`${relative(root, file) || file}:${index + 1} ${rule.id} — ${rule.why}\n    ${line.trim()}`);
    });
  }
}
for (const finding of findings) console.error(finding);
console.log(`lint: ${files.length} files, ${RULES.length} rules, ${findings.length} findings`);
process.exit(findings.length ? 1 : 0);
