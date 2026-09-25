// Production check for static/cmh-os. The browser runs the modules as they are
// (ADR-008), so "build" means: every import resolves, no module is orphaned,
// every asset the HTML references exists, and the payload stays in budget.
import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { gzipSync } from 'node:zlib';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const staticRoot = resolve(here, '../../static');
const root = join(staticRoot, 'cmh-os');
const BUDGET_GZIP_BYTES = 150_000;
const errors = [];

/** @param {string} dir @returns {string[]} */
function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

const IMPORT = /(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]|import\s*\(\s*['"]([^'"]+)['"]\s*\)|import\s*['"]([^'"]+)['"]/g;
const reached = new Set();
/** @param {string} file */
function visit(file) {
  if (reached.has(file)) return;
  if (!existsSync(file)) { errors.push(`missing module ${relative(root, file)}`); return; }
  reached.add(file);
  const source = readFileSync(file, 'utf8');
  for (const match of source.matchAll(IMPORT)) {
    const spec = match[1] || match[2] || match[3];
    if (!spec.startsWith('.')) { errors.push(`${relative(root, file)} imports bare specifier '${spec}'`); continue; }
    if (!spec.endsWith('.js')) { errors.push(`${relative(root, file)} imports '${spec}' without .js extension`); continue; }
    visit(resolve(dirname(file), spec));
  }
}

const html = readFileSync(join(root, 'index.html'), 'utf8');
const refs = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((m) => m[1]).filter((r) => r.startsWith('/static/'));
for (const ref of refs) {
  const file = join(staticRoot, ref.slice('/static/'.length));
  if (!existsSync(file)) errors.push(`index.html references missing ${ref}`);
}
const entry = refs.find((r) => r.endsWith('/js/main.js'));
if (!entry) errors.push('index.html does not load /static/cmh-os/js/main.js');
else visit(join(staticRoot, entry.slice('/static/'.length)));

const jsFiles = walk(join(root, 'js')).filter((f) => f.endsWith('.js'));
for (const file of jsFiles) {
  if (!reached.has(file) && !file.endsWith('types.js')) errors.push(`orphan module ${relative(root, file)}`);
}

// Budget what the browser actually downloads: the HTML, the files it
// references and every module reached from main.js, measured gzip-compressed.
const loaded = [join(root, 'index.html'), ...refs.map((ref) => join(staticRoot, ref.slice('/static/'.length))).filter((f) => existsSync(f) && !f.endsWith('main.js')),
                ...reached, join(root, 'assets', 'logo-cmh.png')];
let raw = 0;
let gzip = 0;
const manifest = [...new Set(loaded)].map((file) => {
  const data = readFileSync(file);
  const zipped = gzipSync(data).length;
  raw += data.length;
  gzip += zipped;
  return { path: relative(root, file).replaceAll('\\', '/'), bytes: data.length, gzip: zipped,
           sha256: createHash('sha256').update(data).digest('hex').slice(0, 12) };
});
if (gzip > BUDGET_GZIP_BYTES) errors.push(`payload ${gzip} gzip bytes exceeds budget ${BUDGET_GZIP_BYTES}`);

for (const error of errors) console.error('build: ' + error);
if (process.argv.includes('--manifest')) console.log(JSON.stringify(manifest, null, 2));
console.log(`build: ${reached.size} modules reached from main.js, ${manifest.length} files loaded, ${raw} bytes raw, ${gzip} bytes gzip (budget ${BUDGET_GZIP_BYTES}), ${errors.length} errors`);
process.exit(errors.length ? 1 : 0);
