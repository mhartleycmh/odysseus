// Strict type check of static/cmh-os/js (JSDoc types) with the TypeScript
// compiler bundled in VS Code. No npm install: set CMH_OS_TYPESCRIPT to point
// at another typescript.js if VS Code is not present.
import { createRequire } from 'node:module';
import { existsSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const project = resolve(here, '../../static/cmh-os');

function findTypeScript() {
  if (process.env.CMH_OS_TYPESCRIPT) return process.env.CMH_OS_TYPESCRIPT;
  const roots = [dirname(process.execPath)];
  if (process.env.LOCALAPPDATA) roots.push(join(process.env.LOCALAPPDATA, 'Programs', 'Microsoft VS Code'));
  for (const root of roots) {
    const direct = join(root, 'resources/app/extensions/node_modules/typescript/lib/typescript.js');
    if (existsSync(direct)) return direct;
    if (!existsSync(root)) continue;
    for (const entry of readdirSync(root)) {
      const nested = join(root, entry, 'resources/app/extensions/node_modules/typescript/lib/typescript.js');
      if (existsSync(nested)) return nested;
    }
  }
  return null;
}

const tsPath = findTypeScript();
if (!tsPath) {
  console.error('typecheck: TypeScript not found; set CMH_OS_TYPESCRIPT');
  process.exit(2);
}
const ts = createRequire(import.meta.url)(tsPath);
const configPath = join(project, 'jsconfig.json');
const read = ts.readConfigFile(configPath, ts.sys.readFile);
if (read.error) {
  console.error(ts.flattenDiagnosticMessageText(read.error.messageText, '\n'));
  process.exit(2);
}
const parsed = ts.parseJsonConfigFileContent(read.config, ts.sys, project);
const program = ts.createProgram(parsed.fileNames, parsed.options);
const diagnostics = ts.getPreEmitDiagnostics(program);
for (const d of diagnostics) {
  const text = ts.flattenDiagnosticMessageText(d.messageText, '\n');
  if (d.file && d.start !== undefined) {
    const { line, character } = d.file.getLineAndCharacterOfPosition(d.start);
    const name = d.file.fileName.replaceAll('\\', '/').replace(project.replaceAll('\\', '/') + '/', '');
    console.error(`${name}:${line + 1}:${character + 1} TS${d.code} ${text}`);
  } else {
    console.error(`TS${d.code} ${text}`);
  }
}
console.log(`typecheck: TypeScript ${ts.version}, ${parsed.fileNames.length} files, ${diagnostics.length} errors`);
process.exit(diagnostics.length ? 1 : 0);
