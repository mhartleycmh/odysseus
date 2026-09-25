// Rules derived from data, shared by the live and demo sources.

/** @typedef {import('../types.js').PermissionLevel} PermissionLevel */
/** @typedef {import('../types.js').RiskLevel} RiskLevel */

/** Mirrors READ_TOOLS in src/cmh_workflows.py: the only tools a workflow step may use. */
export const READ_TOOLS = Object.freeze(['read_file', 'ls', 'grep', 'glob']);
const HIGH_RISK = new Set(['shell', 'send_email', 'python', 'execute_code', 'delete_file']);
const KNOWN_READ = new Set([...READ_TOOLS, 'web_search', 'consultar_estado', 'consultar_plan', 'leer_reportes_turno',
  'consultar_mantenimiento', 'registro_incidentes', 'estado_abastecimiento', 'costos_unitarios', 'indicadores_ambientales']);

/**
 * Least privilege, conservatively: an unknown tool is assumed able to write.
 * @param {string[]} tools
 * @returns {PermissionLevel}
 */
export function permissionFor(tools) {
  if (tools.some((tool) => HIGH_RISK.has(tool))) return 'admin';
  if (tools.some((tool) => !KNOWN_READ.has(tool))) return 'escritura';
  return 'lectura';
}

/**
 * @param {string} tool
 * @returns {RiskLevel}
 */
export function riskOfTool(tool) {
  if (HIGH_RISK.has(tool)) return 'alto';
  return KNOWN_READ.has(tool) ? 'bajo' : 'medio';
}

/** @param {string} tool */
export function isReadOnlyTool(tool) {
  return KNOWN_READ.has(tool);
}

/**
 * Drop credentials a URL may carry (user:token@, ?key=, #fragment) before it
 * reaches the page; mirrors the backend's redact_url.
 * @param {string} url
 */
export function redactUrl(url) {
  try {
    const parsed = new URL(url);
    return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
  } catch {
    return url.replace(/\/\/[^/@\s]*@/, '//').replace(/[?#].*$/, '');
  }
}

/**
 * Redact every URL inside free text (error messages).
 * @param {string} text
 */
export function redactText(text) {
  return text.replace(/\b[a-z][a-z0-9+.-]*:\/\/[^\s"'<>]+/gi, (url) => redactUrl(url));
}

/** @param {string[]} tools */
export function workflowCompatible(tools) {
  return tools.length > 0 && tools.every((tool) => READ_TOOLS.includes(tool));
}
