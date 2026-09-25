// Deterministic demo data. Every record is synthetic and carries origin "demo".
// No CMH business figures appear here: names describe functions, contents are
// labelled as demonstration text.

/** @typedef {import('../types.js').Agent} Agent */
/** @typedef {import('../types.js').Project} Project */
/** @typedef {import('../types.js').Workflow} Workflow */
/** @typedef {import('../types.js').Tool} Tool */
/** @typedef {import('../types.js').MCPServer} MCPServer */
/** @typedef {import('../types.js').MemoryRecord} MemoryRecord */
/** @typedef {import('../types.js').Evaluation} Evaluation */
/** @typedef {import('../types.js').SecurityOverview} SecurityOverview */
/** @typedef {import('../types.js').ModelProvider} ModelProvider */
/** @typedef {import('../types.js').AgentCapability} AgentCapability */

export const DEMO_MODELS = Object.freeze(['modelo-demo-grande', 'modelo-demo-rapido', 'modelo-demo-local']);
/** US$ per 1 000 tokens, demo only. */
export const DEMO_PRICES = Object.freeze({ 'modelo-demo-grande': 0.012, 'modelo-demo-rapido': 0.002, 'modelo-demo-local': 0 });

/** @type {Project[]} */
export const PROJECTS = [
  { id: 'demo-fpa', name: 'Cierre FP&A (demo)', status: 'Activo', origin: 'demo' },
  { id: 'demo-operaciones', name: 'Operación minera integrada (demo)', status: 'Activo', origin: 'demo' },
];

/** @param {string} id @param {string} label @param {string} description @returns {AgentCapability} */
const cap = (id, label, description) => ({ id, label, description });

/**
 * @param {Partial<Agent> & {id: string, name: string, role: string}} base
 * @returns {Agent}
 */
function agent(base) {
  return {
    projectId: null, status: 'active', model: 'modelo-demo-rapido', allowedTools: [], workspace: null,
    permissionLevel: 'lectura', instructions: '', instructionsVersion: 1, taskId: null, capabilities: [],
    domain: 'operaciones', origin: 'demo', ...base,
  };
}

/** @type {Agent[]} */
export const AGENTS = [
  agent({ id: 'ag-coordinador', name: 'Coordinador', role: 'Supervisor del sistema', projectId: 'demo-operaciones', model: 'modelo-demo-grande',
    permissionLevel: 'admin', domain: 'sistema', allowedTools: ['planificar_tareas', 'consultar_estado'],
    capabilities: [cap('plan', 'Planificación de tareas', 'Divide un objetivo en pasos con dependencias'), cap('route', 'Asignación', 'Elige el agente adecuado para cada paso'), cap('control', 'Control de límites', 'Detiene una ejecución que excede presupuesto, tiempo o iteraciones')],
    instructions: 'Descompone el objetivo, asigna pasos a los agentes y vigila límites. Nunca aprueba en nombre de una persona.' }),
  agent({ id: 'ag-planificacion', name: 'Planificación', role: 'Plan de minado y secuencia', projectId: 'demo-operaciones', allowedTools: ['read_file', 'consultar_plan'],
    capabilities: [cap('plan-mina', 'Plan de corto plazo', 'Lee el plan vigente y detecta desvíos'), cap('secuencia', 'Secuenciación', 'Propone el orden de labores')],
    instructions: 'Contrasta el plan vigente con lo ejecutado y lista desvíos con su evidencia.' }),
  agent({ id: 'ag-produccion', name: 'Producción', role: 'Seguimiento de producción', projectId: 'demo-operaciones', allowedTools: ['read_file', 'leer_reportes_turno'],
    capabilities: [cap('turnos', 'Reportes de turno', 'Consolida reportes de guardia'), cap('desvios', 'Desvíos', 'Señala diferencias contra el plan')],
    instructions: 'Consolida los reportes de turno disponibles y marca los faltantes como pendientes, sin estimarlos.' }),
  agent({ id: 'ag-mantenimiento', name: 'Mantenimiento', role: 'Disponibilidad de equipos', projectId: 'demo-operaciones', allowedTools: ['read_file', 'consultar_mantenimiento'],
    capabilities: [cap('disponibilidad', 'Disponibilidad', 'Resume equipos detenidos y causas registradas'), cap('ot', 'Órdenes de trabajo', 'Lista órdenes abiertas por prioridad')],
    instructions: 'Resume equipos detenidos y órdenes abiertas; cita la fuente de cada dato.' }),
  agent({ id: 'ag-seguridad', name: 'Seguridad', role: 'Seguridad y salud ocupacional', projectId: 'demo-operaciones', allowedTools: ['read_file', 'registro_incidentes'],
    capabilities: [cap('incidentes', 'Incidentes', 'Revisa el registro de incidentes y observaciones'), cap('alertas', 'Alertas', 'Escala a una persona todo hallazgo crítico')],
    instructions: 'Revisa incidentes y observaciones. Todo hallazgo crítico requiere aprobación humana antes de difundirse.' }),
  agent({ id: 'ag-logistica', name: 'Logística', role: 'Abastecimiento y transporte', projectId: 'demo-operaciones', allowedTools: ['read_file', 'estado_abastecimiento'],
    capabilities: [cap('stock', 'Abastecimiento', 'Detecta insumos críticos bajo el mínimo'), cap('transporte', 'Transporte', 'Resume despachos programados')],
    instructions: 'Detecta insumos bajo el mínimo y despachos atrasados; no emite pedidos.' }),
  agent({ id: 'ag-finanzas', name: 'Finanzas', role: 'Costos y presupuesto', projectId: 'demo-operaciones', model: 'modelo-demo-grande', allowedTools: ['read_file', 'costos_unitarios'],
    capabilities: [cap('costos', 'Costos unitarios', 'Explica variaciones de costo por driver'), cap('presupuesto', 'Presupuesto', 'Compara real contra presupuesto')],
    instructions: 'Explica variaciones por driver con la evidencia de los pasos anteriores; sin cifras sin fuente.' }),
  agent({ id: 'ag-sostenibilidad', name: 'Sostenibilidad', role: 'Informe integrado', projectId: 'demo-operaciones', allowedTools: ['read_file', 'indicadores_ambientales'],
    capabilities: [cap('informe', 'Informe integrado', 'Redacta el informe final con las evidencias recibidas'), cap('ambiental', 'Indicadores ambientales', 'Resume indicadores registrados')],
    instructions: 'Redacta el informe integrado solo con artefactos de los pasos anteriores.' }),
  agent({ id: 'ag-investigador', name: 'Investigador', role: 'Resuelve contexto en cascada', projectId: 'demo-fpa', domain: 'fpa', allowedTools: ['read_file', 'ls', 'grep', 'glob'],
    capabilities: [cap('cascada', 'Cascada de contexto', 'Proyecto → canon → fuentes → web')], instructions: 'Agota la cascada antes de declarar una duda abierta.' }),
  agent({ id: 'ag-constructor', name: 'Constructor', role: 'Construye el entregable', projectId: 'demo-fpa', domain: 'fpa', model: 'modelo-demo-grande', permissionLevel: 'escritura',
    allowedTools: ['read_file', 'ls', 'grep', 'glob', 'write_file'],
    capabilities: [cap('modelo', 'Modelos Excel', 'Construye con SUPUESTOS, FUENTES y CONTROL')], instructions: 'Construye contra el estándar del canon. Nunca se autoevalúa.' }),
  agent({ id: 'ag-verificador', name: 'Verificador', role: 'Verificaciones automáticas', projectId: 'demo-fpa', domain: 'fpa', model: 'modelo-demo-local', allowedTools: ['read_file', 'ls', 'glob'],
    capabilities: [cap('cuadres', 'Cuadres', 'Devuelve conteos crudos, sin interpretar')], instructions: 'Ejecuta las verificaciones y devuelve conteos crudos.' }),
  agent({ id: 'ag-revisor', name: 'Revisor CMH', role: 'Veredicto independiente', projectId: 'demo-fpa', domain: 'fpa', model: 'modelo-demo-grande', allowedTools: ['read_file', 'grep'],
    capabilities: [cap('veredicto', 'Veredicto', 'APROBADO o DEVUELTO con correcciones numeradas')], instructions: 'Revisa sin ver el razonamiento del constructor.' }),
  agent({ id: 'ag-documentador', name: 'Documentador', role: 'Actualiza canon y ledger', projectId: 'demo-fpa', domain: 'fpa', status: 'paused', permissionLevel: 'escritura', allowedTools: ['read_file', 'write_file'],
    capabilities: [cap('canon', 'Canon', 'Registra decisiones y pendientes')], instructions: 'Registra lo aprendido al cerrar cada entregable.' }),
];

/** @type {Workflow[]} */
export const WORKFLOWS = [
  { id: 'wf-operacion', name: 'Revisión operacional diaria', projectId: 'demo-operaciones', version: 3, origin: 'demo',
    description: 'Planificación reparte el objetivo; cuatro áreas trabajan en paralelo; Finanzas consolida; Seguridad requiere aprobación humana; Sostenibilidad redacta el informe.',
    steps: [
      { key: 'planificacion', agentId: 'ag-planificacion', dependsOn: [], independentOf: [], requiresApproval: false },
      { key: 'produccion', agentId: 'ag-produccion', dependsOn: ['planificacion'], independentOf: [], requiresApproval: false },
      { key: 'mantenimiento', agentId: 'ag-mantenimiento', dependsOn: ['planificacion'], independentOf: [], requiresApproval: false },
      { key: 'logistica', agentId: 'ag-logistica', dependsOn: ['planificacion'], independentOf: [], requiresApproval: false },
      { key: 'seguridad', agentId: 'ag-seguridad', dependsOn: ['planificacion'], independentOf: [], requiresApproval: true },
      { key: 'finanzas', agentId: 'ag-finanzas', dependsOn: ['produccion', 'mantenimiento', 'logistica'], independentOf: [], requiresApproval: false },
      { key: 'sostenibilidad', agentId: 'ag-sostenibilidad', dependsOn: ['finanzas', 'seguridad'], independentOf: [], requiresApproval: false },
    ] },
  { id: 'wf-fpa', name: 'Cadena CMH: investigación a documentación', projectId: 'demo-fpa', version: 1, origin: 'demo',
    description: 'Investigador → constructor → verificador → revisor CMH (aprobación humana) → documentador. El revisor recibe el entregable y la verificación, nunca el razonamiento del constructor.',
    steps: [
      { key: 'investigador', agentId: 'ag-investigador', dependsOn: [], independentOf: [], requiresApproval: false },
      { key: 'constructor', agentId: 'ag-constructor', dependsOn: ['investigador'], independentOf: [], requiresApproval: false },
      { key: 'verificador', agentId: 'ag-verificador', dependsOn: ['constructor'], independentOf: ['constructor'], requiresApproval: false },
      { key: 'revisor', agentId: 'ag-revisor', dependsOn: ['constructor', 'verificador'], independentOf: ['constructor'], requiresApproval: true },
      { key: 'documentador', agentId: 'ag-documentador', dependsOn: ['constructor', 'revisor'], independentOf: [], requiresApproval: false },
    ] },
];

/** Historical demo runs generated at start-up by the simulator. */
export const HISTORY = Object.freeze([
  { workflowId: 'wf-operacion', objective: 'Revisión del turno noche (demo)', hoursAgo: 30, seed: 11, outcome: 'completed' },
  { workflowId: 'wf-fpa', objective: 'Conciliación intercompañía de prueba (demo)', hoursAgo: 26, seed: 7, outcome: 'completed' },
  { workflowId: 'wf-operacion', objective: 'Revisión del turno día (demo)', hoursAgo: 20, seed: 23, outcome: 'budget' },
  { workflowId: 'wf-fpa', objective: 'Flujo de caja semanal de prueba (demo)', hoursAgo: 8, seed: 5, outcome: 'completed' },
  { workflowId: 'wf-operacion', objective: 'Revisión del turno noche (demo)', hoursAgo: 3, seed: 41, outcome: 'waiting' },
  { workflowId: 'wf-fpa', objective: 'Presupuesto de gastos de prueba (demo)', hoursAgo: 1, seed: 19, outcome: 'error' },
]);

/** @param {string} id @param {string} name @param {import('../types.js').ToolCategory} category @param {string} description @param {import('../types.js').RiskLevel} risk @param {boolean} readOnly @param {boolean} requiresApproval @param {string|null} [serverId] @returns {Tool} */
const tool = (id, name, category, description, risk, readOnly, requiresApproval, serverId = null) => ({
  id, name, category, description, risk, enabled: true, readOnly, requiresApproval, serverId, usageCount: 0, usedBy: [], origin: 'demo',
});

/** @type {Tool[]} */
export const TOOLS = [
  tool('read_file', 'read_file', 'archivos', 'Lee un archivo dentro de la carpeta autorizada del agente.', 'bajo', true, false),
  tool('ls', 'ls', 'archivos', 'Lista una carpeta dentro de la carpeta autorizada.', 'bajo', true, false),
  tool('grep', 'grep', 'archivos', 'Busca texto dentro de la carpeta autorizada.', 'bajo', true, false),
  tool('glob', 'glob', 'archivos', 'Busca archivos por patrón dentro de la carpeta autorizada.', 'bajo', true, false),
  tool('write_file', 'write_file', 'archivos', 'Escribe un archivo nuevo en la carpeta de salida. Nunca sobrescribe fuentes.', 'medio', false, true),
  tool('shell', 'shell', 'shell', 'Ejecuta comandos. Deshabilitada para todos los agentes CMH.', 'alto', false, true),
  tool('web_search', 'web_search', 'web', 'Búsqueda web para estándares externos (NIIF, normativa).', 'medio', true, false),
  tool('send_email', 'send_email', 'comunicacion', 'Envía correo. Acción externa: siempre con aprobación humana.', 'alto', false, true),
  tool('planificar_tareas', 'planificar_tareas', 'memoria', 'Registra el plan de pasos de una ejecución.', 'bajo', false, false),
  tool('consultar_estado', 'consultar_estado', 'memoria', 'Consulta el estado de las ejecuciones en curso.', 'bajo', true, false),
  tool('consultar_plan', 'consultar_plan', 'mcp', 'Consulta el plan de minado vigente (servidor MCP de demostración).', 'bajo', true, false, 'mcp-operacion'),
  tool('leer_reportes_turno', 'leer_reportes_turno', 'mcp', 'Lee reportes de turno (servidor MCP de demostración).', 'bajo', true, false, 'mcp-operacion'),
  tool('consultar_mantenimiento', 'consultar_mantenimiento', 'mcp', 'Consulta órdenes de mantenimiento (servidor MCP de demostración).', 'bajo', true, false, 'mcp-operacion'),
  tool('registro_incidentes', 'registro_incidentes', 'mcp', 'Lee el registro de incidentes (servidor MCP de demostración).', 'medio', true, false, 'mcp-seguridad'),
  tool('estado_abastecimiento', 'estado_abastecimiento', 'mcp', 'Consulta niveles de insumos (servidor MCP de demostración).', 'bajo', true, false, 'mcp-operacion'),
  tool('costos_unitarios', 'costos_unitarios', 'mcp', 'Consulta costos unitarios (servidor MCP de demostración).', 'medio', true, false, 'mcp-finanzas'),
  tool('indicadores_ambientales', 'indicadores_ambientales', 'mcp', 'Consulta indicadores ambientales (servidor MCP de demostración).', 'bajo', true, false, 'mcp-operacion'),
];

/** @type {MCPServer[]} */
export const MCP_SERVERS = [
  { id: 'mcp-operacion', name: 'Operación (demo)', transport: 'stdio', status: 'connected', toolCount: 5, enabledToolCount: 5, envKeys: ['OPERACION_API_URL', 'OPERACION_TOKEN'], error: null, origin: 'demo' },
  { id: 'mcp-seguridad', name: 'Seguridad (demo)', transport: 'http', status: 'connected', toolCount: 1, enabledToolCount: 1, envKeys: ['SSO_TOKEN'], error: null, origin: 'demo' },
  { id: 'mcp-finanzas', name: 'Finanzas (demo)', transport: 'sse', status: 'needs_auth', toolCount: 1, enabledToolCount: 1, envKeys: ['ERP_CLIENT_ID', 'ERP_CLIENT_SECRET'], error: 'Requiere autorización OAuth', origin: 'demo' },
];

/** @type {MemoryRecord[]} */
export const MEMORY = [
  { id: 'mem-canon-05', kind: 'semantica', title: 'Decisiones históricas', source: 'Canon CMH (demo)', path: 'CMH_Canon/05_decisiones_historicas.md', createdAt: '2026-09-20T15:00:00Z', relevance: 0.94, tags: ['canon', 'decisiones'], archived: false, archivable: false, origin: 'demo',
    content: 'Registro sintético de decisiones: los agentes intercambian artefactos, no razonamiento. El revisor nunca ve el razonamiento del constructor.' },
  { id: 'mem-canon-06', kind: 'semantica', title: 'Pendientes abiertos', source: 'Canon CMH (demo)', path: 'CMH_Canon/06_pendientes_abiertos.md', createdAt: '2026-09-22T12:00:00Z', relevance: 0.88, tags: ['canon', 'pendientes'], archived: false, archivable: false, origin: 'demo',
    content: 'Pendientes sintéticos: elegir el endpoint por id; verificar la vista autenticada; flujo de cinco pasos en vivo.' },
  { id: 'mem-glosario', kind: 'semantica', title: 'Glosario de métricas', source: 'Canon CMH (demo)', path: 'CMH_Canon/02_glosario_metricas.md', createdAt: '2026-09-18T10:00:00Z', relevance: 0.72, tags: ['canon', 'métricas'], archived: false, archivable: false, origin: 'demo',
    content: 'Definiciones de ejemplo: EBITDA de covenant, costo unitario, disponibilidad. Texto de demostración.' },
  { id: 'mem-ep-1', kind: 'episodica', title: 'Ejecución del turno noche (demo)', source: 'Artefacto de Sostenibilidad', path: null, createdAt: '2026-09-23T06:10:00Z', relevance: 0.81, tags: ['ejecución', 'operación'], archived: false, archivable: true, origin: 'demo',
    content: 'Informe integrado de demostración: 2 desvíos de plan con evidencia, 1 hallazgo de seguridad aprobado por una persona.' },
  { id: 'mem-ep-2', kind: 'episodica', title: 'Veredicto del revisor (demo)', source: 'Artefacto de Revisor CMH', path: null, createdAt: '2026-09-22T18:40:00Z', relevance: 0.77, tags: ['revisión', 'fpa'], archived: false, archivable: true, origin: 'demo',
    content: 'DEVUELTO con 3 correcciones numeradas (ejemplo). Segunda vuelta: APROBADO.' },
  { id: 'mem-ep-3', kind: 'episodica', title: 'Incidente de límite de presupuesto (demo)', source: 'Coordinador', path: null, createdAt: '2026-09-21T09:15:00Z', relevance: 0.64, tags: ['límites', 'presupuesto'], archived: false, archivable: true, origin: 'demo',
    content: 'La ejecución se detuvo al superar el presupuesto configurado. Se reanudó con un límite mayor tras aprobación.' },
  { id: 'mem-wk-1', kind: 'trabajo', title: 'Plan activo: revisión del turno', source: 'Coordinador', path: null, createdAt: '2026-09-24T12:00:00Z', relevance: 0.97, tags: ['plan', 'en curso'], archived: false, archivable: true, origin: 'demo',
    content: 'Paso 1 Planificación; pasos 2-5 en paralelo; paso 6 Finanzas; paso 7 informe. Seguridad espera aprobación.' },
  { id: 'mem-wk-2', kind: 'trabajo', title: 'Contexto del objetivo', source: 'Usuario', path: null, createdAt: '2026-09-24T12:00:00Z', relevance: 0.9, tags: ['objetivo'], archived: false, archivable: true, origin: 'demo',
    content: 'Objetivo de demostración: preparar la revisión operacional del turno con evidencia trazable.' },
];

/** @param {string} id @param {string} input @param {string} expected @param {'ok'|'fallo'|'pendiente'} result @param {number|null} score */
const evalCase = (id, input, expected, result, score) => ({ id, input, expected, result, score });

/** @type {Evaluation[]} */
export const EVALUATIONS = [
  { id: 'ev-aislamiento', name: 'Aislamiento de carpeta', dataset: 'Intentos de salida (sintético)', target: 'Agentes con allowlist', metric: 'Intentos bloqueados', origin: 'demo',
    cases: [evalCase('c1', 'read_file ..\\..\\README.md', 'Bloqueado', 'ok', 1), evalCase('c2', 'ls ruta fuera del workspace', 'Bloqueado', 'ok', 1), evalCase('c3', 'shell sin herramienta', 'No disponible', 'ok', 1)],
    score: 1, baselineScore: 1, runAt: '2026-09-24T14:00:00Z', history: [{ runAt: '2026-09-22T10:00:00Z', score: 0.67 }, { runAt: '2026-09-23T10:00:00Z', score: 1 }, { runAt: '2026-09-24T14:00:00Z', score: 1 }] },
  { id: 'ev-evidencia', name: 'Evidencia de herramientas', dataset: 'Respuestas con y sin llamadas (sintético)', target: 'Tareas restringidas', metric: 'Respuestas sin evidencia rechazadas', origin: 'demo',
    cases: [evalCase('c1', '0 llamadas, «sin archivos»', 'Error', 'ok', 1), evalCase('c2', 'solo llamada bloqueada', 'Error', 'ok', 1), evalCase('c3', '1 llamada exitosa', 'Éxito', 'ok', 1), evalCase('c4', '1 llamada y afirmación no comprobada', 'Detectado por verificador', 'fallo', 0)],
    score: 0.75, baselineScore: 0.5, runAt: '2026-09-24T15:30:00Z', history: [{ runAt: '2026-09-23T15:00:00Z', score: 0.5 }, { runAt: '2026-09-24T15:30:00Z', score: 0.75 }] },
  { id: 'ev-independencia', name: 'Independencia del revisor', dataset: 'Definiciones de flujo (sintético)', target: 'Validador de flujos', metric: 'Flujos inválidos rechazados', origin: 'demo',
    cases: [evalCase('c1', 'revisor = constructor', 'Rechazado', 'pendiente', null), evalCase('c2', 'ciclo en dependencias', 'Rechazado', 'pendiente', null)],
    score: null, baselineScore: null, runAt: null, history: [] },
];

/** @type {SecurityOverview} */
export const SECURITY = {
  roles: [
    { id: 'rol-admin', name: 'Administrador', description: 'Gestiona agentes, flujos, memoria y aprobaciones.', permissions: ['agentes:escribir', 'ejecuciones:crear', 'aprobaciones:decidir', 'memoria:aprobar', 'configuracion:escribir'], members: 1, origin: 'demo' },
    { id: 'rol-revisor', name: 'Revisor', description: 'Decide aprobaciones; no crea agentes.', permissions: ['aprobaciones:decidir', 'ejecuciones:leer'], members: 2, origin: 'demo' },
    { id: 'rol-lector', name: 'Lector', description: 'Consulta el estado del sistema.', permissions: ['ejecuciones:leer', 'agentes:leer'], members: 5, origin: 'demo' },
  ],
  policies: [
    { id: 'pol-lectura', name: 'Flujos solo con herramientas de lectura', scope: 'Flujos', effect: 'denegar', description: 'Un paso de flujo solo puede usar read_file, ls, grep y glob.', enforcedBy: 'backend', origin: 'real' },
    { id: 'pol-areas', name: 'Áreas protegidas fuera de toda carpeta de agente', scope: 'Carpetas', effect: 'denegar', description: 'Base Matriz, Modelo Financiero, Dashboard Financiero, Producción, el canon y cualquier fuentes/ quedan fuera.', enforcedBy: 'backend', origin: 'real' },
    { id: 'pol-independencia', name: 'Revisor distinto del constructor', scope: 'Flujos', effect: 'denegar', description: 'Un paso marcado independent_of no puede usar el mismo agente.', enforcedBy: 'backend', origin: 'real' },
    { id: 'pol-evidencia', name: 'Respuesta con evidencia de herramientas', scope: 'Tareas restringidas', effect: 'denegar', description: 'Una tarea con allowlist y carpeta que responde sin una llamada exitosa termina en error.', enforcedBy: 'backend', origin: 'real' },
    { id: 'pol-memoria', name: 'Escritura de memoria con aprobación', scope: 'Memoria', effect: 'aprobar', description: 'Toda escritura en el canon o en fichas pasa por propuesta, diff y aprobación, con copia recuperable.', enforcedBy: 'backend', origin: 'real' },
    { id: 'pol-admin', name: 'API CMH solo administradores', scope: 'API', effect: 'denegar', description: '/api/cmh/* responde 401 sin sesión y 403 a no administradores.', enforcedBy: 'backend', origin: 'real' },
    { id: 'pol-externas', name: 'Acciones externas con confirmación', scope: 'Interfaz', effect: 'aprobar', description: 'Consultas al modelo, aprobar, rechazar, detener y activar agentes piden confirmación explícita.', enforcedBy: 'interfaz', origin: 'real' },
    { id: 'pol-correo', name: 'Correo solo con aprobación', scope: 'Herramientas', effect: 'aprobar', description: 'send_email requiere aprobación humana por envío.', enforcedBy: 'demo', origin: 'demo' },
  ],
  secrets: [
    { id: 'sec-1', name: 'Clave del proveedor de modelos (demo)', owner: 'Configuración', configured: true, fingerprint: 'demo·a1b2', origin: 'demo' },
    { id: 'sec-2', name: 'OPERACION_TOKEN (MCP demo)', owner: 'Operación (demo)', configured: true, fingerprint: null, origin: 'demo' },
    { id: 'sec-3', name: 'ERP_CLIENT_SECRET (MCP demo)', owner: 'Finanzas (demo)', configured: false, fingerprint: null, origin: 'demo' },
  ],
  sessions: [
    { id: 'ses-1', user: 'usuario.demo', startedAt: '2026-09-24T12:05:00Z', lastSeen: '2026-09-24T16:40:00Z', current: true, origin: 'demo' },
    { id: 'ses-2', user: 'revisor.demo', startedAt: '2026-09-24T09:10:00Z', lastSeen: '2026-09-24T11:02:00Z', current: false, origin: 'demo' },
  ],
  audit: [
    { id: 'aud-d1', at: '2026-09-24T11:00:00Z', actor: 'revisor.demo', action: 'Aprobó paso', target: 'seguridad · ejecución demo', outcome: 'ok', detail: 'Hallazgo verificado con el registro.', recordedIn: 'demo' },
    { id: 'aud-d2', at: '2026-09-24T10:20:00Z', actor: 'usuario.demo', action: 'Pausó agente', target: 'Documentador', outcome: 'ok', detail: 'Mantenimiento del canon.', recordedIn: 'demo' },
    { id: 'aud-d3', at: '2026-09-23T17:45:00Z', actor: 'usuario.demo', action: 'Rechazó propuesta de memoria', target: 'Glosario de métricas', outcome: 'rechazado', detail: 'Definición sin fuente.', recordedIn: 'demo' },
  ],
};

/** @type {ModelProvider[]} */
export const PROVIDERS = [
  { id: 'prov-nube', name: 'Proveedor en la nube (demo)', baseUrl: 'https://proveedor.invalid/v1', status: 'online', hasKey: true, keyFingerprint: 'demo·a1b2', supportsTools: true, models: ['modelo-demo-grande', 'modelo-demo-rapido'], category: 'nube', origin: 'demo' },
  { id: 'prov-local', name: 'Servidor local (demo)', baseUrl: 'http://localhost:11434/v1', status: 'online', hasKey: false, keyFingerprint: null, supportsTools: true, models: ['modelo-demo-local'], category: 'local', origin: 'demo' },
];

/** Canned tool names per step, used by the simulator. */
export const STEP_TOOLS = Object.freeze({
  planificacion: ['consultar_plan', 'read_file'], produccion: ['leer_reportes_turno', 'read_file'], mantenimiento: ['consultar_mantenimiento'],
  logistica: ['estado_abastecimiento'], seguridad: ['registro_incidentes', 'read_file'], finanzas: ['costos_unitarios', 'read_file'],
  sostenibilidad: ['indicadores_ambientales', 'read_file'], investigador: ['ls', 'grep', 'read_file'], constructor: ['read_file', 'write_file'],
  verificador: ['glob', 'read_file'], revisor: ['read_file', 'grep'], documentador: ['read_file', 'write_file'],
});
