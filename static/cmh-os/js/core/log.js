// Structured console logging: one JSON-shaped record per call.

/** @typedef {'debug'|'info'|'warn'|'error'} Level */

/** @type {{level: Level, module: string, message: string, at: string, data?: unknown}[]} */
const recent = [];
const MAX_RECENT = 200;

/**
 * @param {Level} level
 * @param {string} module
 * @param {string} message
 * @param {unknown} [data]
 */
export function log(level, module, message, data) {
  const record = { level, module, message, at: new Date().toISOString(), ...(data === undefined ? {} : { data }) };
  recent.push(record);
  if (recent.length > MAX_RECENT) recent.shift();
  const sink = level === 'error' ? console.error : level === 'warn' ? console.warn : level === 'debug' ? console.debug : console.info;
  sink('[cmh-os]', record);
}

/** Records of this page session, newest last. */
export function recentLogs() {
  return recent.slice();
}
