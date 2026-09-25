// Spanish wording for error details the Odysseus backend returns in English
// (routes/cmh_*_routes.py). Unknown messages pass through unchanged.

/** @type {Record<string, string>} */
export const SERVER_MESSAGES = {
  'Not authenticated': 'No hay sesión iniciada en Odysseus.',
  'CMH agent management is admin-only': 'La gestión CMH es solo para administradores.',
  'Agent not found': 'El agente no existe o no te pertenece.',
  'Project not found': 'El proyecto no existe.',
  'Unknown project': 'El proyecto no existe en el índice CMH.',
  'Name, role and instructions cannot be blank': 'Nombre, rol e instrucciones no pueden quedar vacíos.',
  'Task must be an owned LLM task': 'La tarea vinculada debe ser una tarea LLM propia.',
  'Project, workspace and model are required to activate an agent': 'Para activar un agente hacen falta proyecto, carpeta y modelo.',
  'Workflow not found': 'El flujo no existe.',
  'Workflow run not found': 'La ejecución no existe.',
  'Run is not active': 'La ejecución ya no está activa.',
  'Run cannot be resumed': 'Esta ejecución no se puede reanudar.',
  'Run is still stopping; try again': 'La ejecución todavía se está deteniendo; intenta de nuevo en unos segundos.',
  'No approval pending for this step': 'Este paso ya no espera aprobación.',
  'Workflow steps may use only read-only file tools': 'Los pasos de un flujo solo pueden usar herramientas de lectura.',
  'Workflow step requires a workspace': 'Cada paso del flujo necesita una carpeta autorizada.',
  'Proposal not found': 'La propuesta no existe.',
  'Proposal already decided': 'La propuesta ya fue decidida.',
  'Proposal has no changes': 'La propuesta no cambia nada.',
  'File changed since it was loaded; reload it before proposing': 'El archivo cambió desde que lo abriste; ábrelo de nuevo.',
  'Source changed after proposal; preview again': 'El archivo cambió después de la propuesta; revísala de nuevo.',
  'Memory file is outside approved sources': 'El archivo está fuera de las fuentes autorizadas.',
  'Selected model endpoint was removed. Pick another model in Settings.': 'El endpoint del modelo ya no existe. Elige otro en Configuración.',
};

/** @type {[RegExp, (match: RegExpMatchArray) => string][]} */
const PATTERNS = [
  [/^Step (\S+) requires an active linked agent$/, (m) => `El paso ${m[1]} necesita un agente activo y vinculado a una tarea.`],
  [/^Step (\S+) needs a matching configured model endpoint$/, (m) => `El paso ${m[1]} necesita un endpoint de modelo configurado y coincidente.`],
  [/^Step (\S+) must use a different agent than (\S+)$/, (m) => `El paso ${m[1]} debe usar un agente distinto de ${m[2]}.`],
  [/^Workspace lies in or contains the protected area (.+)$/, (m) => `La carpeta está dentro de un área protegida (${m[1]}) o la contiene.`],
];

/** @param {string} message */
export function translateServerMessage(message) {
  if (SERVER_MESSAGES[message]) return SERVER_MESSAGES[message];
  for (const [pattern, render] of PATTERNS) {
    const match = message.match(pattern);
    if (match) return render(match);
  }
  return message;
}
