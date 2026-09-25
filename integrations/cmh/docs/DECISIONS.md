# Decisiones de arquitectura (ADR) — Interfaz Agentic OS CMH

Formato: contexto → decisión → alternativas descartadas → consecuencias.
Fecha de todas las decisiones iniciales: 2026-09-24. Estado: aceptadas salvo indicación.

---

## ADR-000 · «Guía Agentic OS.md» no existe; se usa la especificación disponible

- **Contexto.** El encargo remite a «Guía Agentic OS.md». Se buscó en todo
  `Documentos\` (recursivo, patrón `*Agentic*`) y no aparece.
- **Decisión.** Se toman como especificación, en este orden: (1) el encargo de
  interfaz del usuario (2026-09-24) y la imagen de referencia conceptual;
  (2) `integrations/cmh/ESTADO_AGENTIC_OS.md` (objetivo acordado y estado del
  backend); (3) `CMH_Claude/entregables/PLAN_ECOSISTEMA_AGENTICO_v1.0_202609.md`
  (principio «los agentes no conversan, dejan rastro»); (4) `integrations/cmh/README.md`
  (fronteras de seguridad).
- **Consecuencia.** Si la guía aparece, se contrasta contra `ARCHITECTURE.md` y
  se registra cada diferencia como ADR nueva.

## ADR-001 · La interfaz vive dentro de Odysseus, en `/cmh/os`

- **Contexto.** Odysseus ya sirve `/cmh` con autenticación, CSP con nonce y las
  APIs `/api/cmh/*` (agentes, proyectos, flujos, eventos SSE, aprobaciones,
  memoria). El encargo pide reutilizar el backend existente.
- **Decisión.** Nueva página `/cmh/os` servida por FastAPI con el mismo
  `serve_html_with_nonce`. Recursos en `static/cmh-os/`. La vista `/cmh`
  existente **no se elimina**; ambas se enlazan.
- **Descartado.** Aplicación separada en otro puerto (duplicaría autenticación y
  obligaría a CORS); reemplazar `/cmh` (rompería un flujo ya verificado en Edge).

## ADR-002 · JavaScript nativo con módulos ES y tipos JSDoc verificados por TypeScript

- **Contexto.** La máquina no tiene Node ni npm en PATH; Odysseus usa JS nativo
  sin empaquetador; la CSP solo admite scripts propios con nonce (y jsDelivr en
  la página principal). El encargo exige tipado estricto, lint, build y pruebas.
- **Decisión.** Módulos ES nativos sin framework ni empaquetador. Tipos en
  JSDoc (`@typedef`, `@param`, `@returns`) verificados con el compilador de
  TypeScript 6.0.3 que trae VS Code, en modo `strict` + `checkJs` +
  `noImplicitAny` + `noUnusedLocals`. Se ejecuta con el Node 24 embebido en
  VS Code (`ELECTRON_RUN_AS_NODE=1`), sin instalar nada.
- **Descartado.** React + Vite + TypeScript (requiere npm, cadena de build y
  dependencias; no instalable aquí sin cambiar la máquina); Svelte/Vue (ídem);
  htmx (no cubre el grafo animado ni el estado de cliente).
- **Consecuencias.** Cero dependencias de ejecución y cero riesgo de cadena de
  suministro. Sin JSX: los componentes construyen DOM con un helper `h()` que
  solo asigna texto (nunca `innerHTML`). El «build» es una verificación del
  grafo de módulos y de los recursos, no una transpilación (ADR-008).

## ADR-003 · Capa de datos desacoplada: `DataSource` con adaptadores real y demo

- **Contexto.** Parte del alcance tiene backend (agentes, flujos, eventos,
  aprobaciones de pasos, propuestas de memoria, endpoints de modelos, MCP) y
  parte no (evaluaciones, políticas de seguridad, catálogo agregado de
  herramientas, presupuesto por ejecución).
- **Decisión.** Interfaz única `DataSource` (`js/services/source.js`). Dos
  implementaciones: `LiveSource` (HTTP contra `/api/*`) y `DemoSource` (datos
  deterministas en `js/mocks/`). El modo se detecta al arrancar: si
  `/api/cmh/agents` responde 200 → **real**; 401/403 o sin red → **demo** con
  franja visible. Cada registro lleva `origin: "real" | "demo"` y la interfaz lo
  muestra con una insignia. En modo real, los dominios sin backend se sirven
  desde la demo **y se etiquetan «Demo — sin backend»**; nunca se mezclan sin
  etiqueta.
- **Descartado.** Mocks dentro de los componentes; un backend nuevo para todos
  los dominios en esta fase (fuera del alcance de interfaz y sin decisión de
  negocio detrás).

## ADR-004 · Movimiento real de los agentes a partir de eventos, no de animación decorativa

- **Contexto.** El usuario pidió «movimiento real de los agentes». El backend
  emite por SSE `step_started`, `tool_started`, `tool_finished`,
  `model_metrics`, `step_completed`, `step_approval_requested`, etc.
- **Decisión.** El grafo de orquestación (SVG) solo se mueve cuando llega un
  evento: pulso en el nodo al iniciar un paso, órbita por cada herramienta en
  curso, partícula que viaja por la arista cuando un artefacto pasa al paso
  siguiente, halo de espera en aprobaciones. En modo demo, un simulador
  determinista (`js/services/simulator.js`, PRNG con semilla) emite **los mismos
  tipos de evento** por la misma interfaz `RunEventStream`, de modo que el
  renderizador no distingue origen. Se respeta `prefers-reduced-motion`.
- **Descartado.** Canvas/WebGL (no accesible, sin texto seleccionable); React
  Flow (MIT, pero exige React).
- **Ajuste tras la revisión independiente (2026-09-25).** Se quitaron las
  animaciones continuas ligadas al estado (guiones que corrían en aristas
  activas, halo pulsante en la espera de aprobación): ahora son trazos
  estáticos. Las órbitas de herramienta solo se muestran si el paso está en
  curso. En demo, los eventos entregados en vivo llevan la hora real para que
  la animación distinga lo nuevo del historial.

## ADR-005 · Chat del coordinador: comandos deterministas primero, LLM opcional y apagado por defecto

- **Contexto.** Principio del encargo: «uso de LLM solo donde aporte valor» y
  aprobación humana para acciones externas.
- **Decisión.** El chat interpreta primero comandos en español con reglas
  (estado, agentes, aprobaciones, ejecutar flujo, detener, buscar memoria,
  ayuda). Las acciones sensibles no se ejecutan desde el chat: el chat abre el
  diálogo de confirmación correspondiente. El texto libre se envía al modelo
  **solo** si el usuario activa «Consultas al modelo desde el chat» en
  Configuración (modo real): se crea una sesión Odysseus (`POST /api/session`)
  y se usa `POST /api/chat`. En demo, el texto libre recibe sugerencias de
  comandos.
- **Descartado.** Chat 100 % LLM (no determinista, costoso, sin control de
  acciones).

## ADR-006 · Enrutamiento por hash

- `#/agentes/:id`. Funciona igual detrás de FastAPI y del servidor estático de
  pruebas, sin reglas de reescritura. Descartado: History API (exigiría rutas
  comodín en FastAPI para cada subruta).

## ADR-007 · Identidad visual oficial CMH

- **Fuente.** Tokens y logotipo del recurso de identidad corporativa CMH del
  usuario (paleta `#002D46`, `#001B2B`, `#17607F`, `#B19A3B`, `#8A7623`, grises;
  semáforo con etiqueta obligatoria; tipografía Aptos → Segoe UI).
  Logotipo PNG 460 × 189 (proporción 2.43:1) copiado byte a byte a
  `static/cmh-os/assets/logo-cmh.png` (SHA-256 `4358872912c35db8…`).
- **Reglas aplicadas.** El logotipo no se redibuja ni se recolorea; sobre fondo
  azul va en caja blanca con margen. El oro `#B19A3B` nunca como texto sobre
  claro (se usa `#8A7623`). Todo estado lleva etiqueta de texto además de color.
  No se generan fotografías de operación minera (regla de la identidad CMH): el
  fondo del centro de control es abstracto.
- **Tema oscuro.** Derivado de `azul_profundo`; los tokens semánticos se
  recalculan para mantener contraste AA (verificado por prueba unitaria).

## ADR-008 · Build = verificación de producción sin transpilar

- El navegador ejecuta los módulos tal como están. `scripts/cmh_os/build.mjs`
  resuelve el grafo de importaciones desde `main.js`, falla si falta un módulo o
  recurso, si aparece un módulo huérfano o si algún archivo referenciado desde
  el HTML no existe. Produce un manifiesto en la salida estándar, no archivos
  generados.
- **Presupuesto (revisado el 2026-09-25).** El primer presupuesto (300 KB sin
  comprimir sobre todos los archivos de la carpeta) medía mal: contaba
  `types.js`, que el navegador nunca descarga, y el código fuente sin comprimir
  no es lo que viaja por la red. Se reemplazó por **150 KB gzip sobre lo que la
  página realmente carga** (HTML, CSS, módulos alcanzados desde `main.js`,
  logotipo). Medido el 2026-09-25: 135 361 bytes gzip (428 161 sin comprimir).

## ADR-009 · Pruebas sin instalar dependencias

- Unitarias: `node --test` (Node 24 de VS Code) sobre módulos sin DOM.
- Componentes, integración y end-to-end: Edge sin ventana controlado por
  DevTools Protocol desde un ejecutor propio (`tests/cmh_os/e2e/`), con el
  WebSocket y `fetch` nativos de Node 24. Capturas en 390, 820 y 1440 px.
- Contrato real ↔ interfaz: prueba pytest que llama a los manejadores reales de
  `/api/cmh/*` y compara sus claves con las fijaciones JSON que usa el servidor
  falso del end-to-end.
- **Descartado.** Playwright/Cypress/Jest/Vitest (requieren npm o pip nuevos).
  ESLint (requiere npm): se sustituye por `lint.mjs` con reglas explícitas y por
  las verificaciones estrictas del compilador. Se declara la diferencia, no se
  oculta.

## ADR-010 · Documentación en `integrations/cmh/docs/`

- El encargo nombra `docs/`. Odysseus es un fork de un proyecto público; la capa
  CMH vive en `integrations/cmh/` para que las fusiones con el original no
  choquen. Los documentos van en `integrations/cmh/docs/`.

## ADR-011 · Secretos nunca llegan al DOM

- `LiveSource` descarta en el acto `env` de `/api/mcp/servers` (conserva solo
  los nombres de variable) y de los endpoints de modelos muestra únicamente
  `has_key` y la huella. La interfaz no tiene ningún campo que muestre o edite
  una clave. Prueba unitaria dedicada.

## ADR-013 · El límite de iteraciones es por ejecución y su valor por defecto es 40

- **Contexto.** El primer valor por defecto (12) se tomó del `max_steps=12` del
  backend, que es **por paso**. La prueba end-to-end F6 mostró que el flujo
  operacional de 7 pasos necesita unas 19 iteraciones (llamadas a herramientas
  más respuestas del modelo): la ejecución se cortaba justo después de la
  aprobación humana.
- **Decisión.** El límite de la interfaz es por ejecución completa y su valor
  por defecto es 40. Sigue siendo editable en el formulario y en Configuración.

## ADR-014 · Los eventos SSE incluyen su hora (`at`)

- **Contexto.** `/api/cmh/runs/{id}/events` enviaba `step_key` y `payload`,
  sin la hora guardada del evento. Al reproducir el historial, todas las horas
  eran «ahora» y las trazas no tenían tiempos reales.
- **Decisión.** Cambio mínimo en `routes/cmh_workflow_routes.py`: el dato de
  cada evento agrega `at` (UTC ISO con `Z`, desde `created_at`). Compatible hacia
  atrás: la vista `/cmh` ignora claves nuevas. Prueba en
  `tests/test_cmh_workflow_routes.py`.

## ADR-015 · Variantes AA de dos colores de estado CMH

- Medición (prueba `design.test.mjs`): el verde oficial «En meta» `#2E7D4F`
  sobre su fondo `#E8F2EC` da 4,41:1 y el gris «No iniciado» `#6B7681` sobre
  `#F4F6F8` da 4,28:1, bajo el 4,5:1 que exige WCAG AA para texto pequeño.
  Solo para **texto** se usan `#256841` (5,85:1) y `#5A6672` (5,42:1, el
  `gris_600` oficial). Rellenos, bordes y gráficos conservan los colores oficiales.
- Hallazgo para el dueño de la marca: el recurso de identidad declara el «oro
  texto» `#8A7623` válido como texto sobre blanco, pero mide 4,47:1, apenas bajo
  AA. La interfaz no lo usa como texto en el tema claro.

## ADR-016 · `CMH_OS_UI_ENABLED` cubre también los activos (cerrado 2026-09-25)

- Enunciado original: la bandera apagaba la ruta `/cmh/os` (404) y la interfaz
  respetaba `ui_enabled=false`, pero Odysseus servía `/static/*` sin
  autenticación (`AUTH_EXEMPT_PREFIXES`), así que `/static/cmh-os/index.html`
  seguía descargándose y, sin sesión, caía en modo demo.
- Resuelto: `routes/cmh_os_routes.is_os_asset_path` marca la carpeta de la
  página, `app.py` la excluye de la exención de `/static` —y solo a ella— y
  `_RevalidatingStatic` devuelve 404 para esa carpeta cuando la bandera está en
  `false`. El resto de `/static` conserva la exención.
- La comprobación es insensible a mayúsculas y al separador a propósito: NTFS
  sirve `/static/CMH-OS/index.html` de la misma carpeta y `StaticFiles`
  normaliza su ruta relativa con `os.path.normpath`, que en Windows usa `\`.
  Un guardia escrito contra la forma literal dejaría pasar ambas grafías.
- **Defecto encontrado y cerrado dentro de la misma sesión.** La primera
  versión comparaba la ruta literal, así que `/static/./cmh-os/index.html` y
  `/static/foo/../cmh-os/index.html` servían la página con **200 y 848 bytes
  sin sesión**. No apareció antes porque la sonda usaba `httpx`, que colapsa
  `.` y `..` **antes de enviar** —igual que un navegador—, de modo que el
  cliente no podía expresar la ruta. Se midió construyendo el `scope` ASGI a
  mano. La verificación independiente lo reprodujo además con uvicorn real y
  socket crudo, y encontró una grafía más: `%2e%2e`, que los navegadores **no**
  decodifican, y `/static//cmh-os/…`, que cualquier navegador manda tal cual.
- Por eso el guardia normaliza cuatro cosas: mayúsculas, separador, barras
  repetidas y segmentos punto. El colapso de barras no es alcanzable por
  ninguna ruta enrutable hoy; se conserva para que el predicado sea correcto
  por sí mismo.
- Medición final (18 grafías probadas por la revisión independiente, incluidas
  `%2e%2e`, `\`, `//`, `/./`, `/foo/../` y mayúsculas): todas 302 con sesión
  ausente y 404 con la bandera apagada. `/static/cmh-control.html` (4 649 B) e
  `icon.ico` (174 B) siguen en 200, así que la compuerta no es un 302
  indiscriminado. Con sesión probada, la página carga entera: `index.html`
  848 B, `js/main.js` 12 278 B, `css/tokens.css` 3 607 B.
  `/static/cmh-os/../cmh-control.html` cae correctamente en el estático
  compartido. Reintroducidos los defectos, fallan las pruebas que los guardan.

## ADR-017 · Rechazo nativo de paso con justificación persistida

- Antes, rechazar un paso en modo real llamaba a `/stop`: la ejecución quedaba
  `interrupted`, podía reanudarse y volvía a pedir la misma aprobación, y la
  justificación vivía solo en la auditoría del navegador. Una compuerta humana
  cuya negativa no sobrevive al navegador no es evidencia.
- Ahora `POST /api/cmh/runs/{id}/steps/{key}/reject` exige `justification` no
  vacía (400 si falta), deja el paso y la ejecución en `rejected`, emite
  `step_rejected` y `run_rejected`, y guarda `{outcome, justification, by, at}`
  en la columna nueva `cmh_workflow_steps.decision`.
- Terminal por diseño: `execute()` solo arranca desde `pending`/`interrupted`/
  `paused` y `resume` solo admite `interrupted`/`error`/`paused`, así que una
  ejecución rechazada no se reanuda ni admite una segunda decisión (409). Los
  artefactos ya producidos se conservan.
- La decisión no se guarda en `config` porque `config` es la foto congelada de
  la ejecución (agente, modelo, endpoint, versión de instrucciones, carpeta y
  herramientas); una decisión es evidencia sobre la ejecución, no una entrada.
- `approve` acepta la misma justificación, opcional, y la guarda igual. Sigue
  funcionando sin cuerpo, para no romper al llamador anterior.
- Límites medidos: una justificación de más de 2 000 caracteres la rechaza
  Pydantic con **422** (`string_too_long`), no con el 400 de la validación
  propia; 2 000 exactos se almacenan íntegros. Dos rechazos simultáneos dan
  `[200, 409]` y una sola decisión; rechazo y aprobación a la vez, también.
- Límite conocido: los pasos hermanos que nunca arrancaron quedan `pending`
  bajo una ejecución `rejected`. Es inocuo —nada los revive, y una prueba lo
  fija— pero la interfaz los pinta como «No iniciado» dentro de una ejecución
  «Rechazada».

## ADR-018 · `disable_mcp` se aplica al ejecutar, no solo al armar el prompt

- `ToolPolicy.blocks()` decidía solo por nombre. Una tarea restringida traduce
  su allowlist a `known_tool_names() - allowed_tools`, y ese conjunto no puede
  contener un nombre MCP cualificado (`mcp__servidor__herramienta`): medido, 82
  nombres, 0 con prefijo `mcp`. `disable_mcp` solo ponía `mcp_mgr = None`
  dentro de `agent_loop`, mientras `tool_execution` pide el gestor al proceso
  por su cuenta. Un nombre `mcp__*` adivinado quedaba sin bloquear.
- Corrección en la raíz: `blocks()` rechaza cualquier nombre con prefijo
  `mcp__` cuando la política declara `disable_mcp`. El otro único uso de la
  bandera —el turno guide-only— ya bloqueaba todo, así que el radio del cambio
  es la política de tareas restringidas.
- El mapa heredado `_MCP_TOOL_MAP` (`read_file`, `ls`…) no se toca: sus nombres
  no llevan el prefijo, así que el piloto conserva sus cuatro herramientas.
- **Excepción explícita, añadida tras la revisión.** 15 herramientas de correo
  están en `known_tool_names()`, o sea son allowlistables, y cada una aliasa a
  su forma `mcp__email__*` vía `email_tool_policy_names`. Las compuertas
  evalúan `any(blocks(n) for n in policy_names)`, así que una cláusula ciega
  bloqueaba `send_email` **aunque la allowlist lo permitiera**, mientras el
  prompt seguía ofreciéndolo: vetado en silencio. `ToolPolicy` lleva ahora
  `allowed_mcp_names`, que `task_scheduler` calcula desde la propia allowlist.
  La cláusula no puede contradecir a la lista blanca que la acompaña.
- Inventario real, medido en `src/builtin_mcp.py`: **cinco** servidores
  builtin, no tres — `image_gen`, `memory`, `rag`, `email` (Python) y
  `builtin_browser` (Playwright por npx, 12 herramientas con nombres
  documentados en `routes/chat_routes.py`). `email` ya estaba cubierto por su
  alias; los otros cuatro no lo estaban.
- Severidad medida por verificación adversaria independiente: **media**, no
  alta. Matices que la sostienen y su límite:
  - los tres nombres con que se demostró el hueco —`mcp__bash__bash`,
    `mcp__filesystem__read_text_file`, `mcp__anything__do_it`— **no existen**
    como servidores: bash, python y filesystem se replegaron a ejecución
    nativa en proceso;
  - de 4 formatos de llamada probados, solo `<invoke name="mcp__…">` produce
    un `tool_type` con prefijo `mcp__`; el canal fenced que usa el piloto
    local no lo parsea, porque `TOOL_TAGS` (77 etiquetas) no tiene ninguna
    `mcp*`;
  - **no verificado**: que `builtin_browser` esté conectado en la máquina
    objetivo —aquí no hay Node en PATH, así que npx no arranca— ni la
    afirmación de «una sola llamada por ejecución» atribuida a la compuerta de
    contexto externo. Si `builtin_browser` conecta, la superficie es control de
    navegador y el argumento de severidad media **no se sostiene**. La
    corrección no depende de ese dato: la cláusula bloquea los cinco por igual.
- Medición que sí es firme: `known_tool_names()` = **82** nombres, **0** con
  prefijo `mcp`, y `validate_task_tools` exige `names <= known_tool_names()`,
  así que ninguna allowlist puede contener un nombre MCP cualificado.

## ADR-012 · Configuración por variables de entorno

- `CMH_OS_UI_ENABLED` (por defecto `true`) y `CMH_OS_DEFAULT_MODE`
  (`auto` | `demo`). Se leen en el servidor y se exponen sin secretos en
  `GET /api/cmh/os/config`. Se documentan en `.env.example`.
