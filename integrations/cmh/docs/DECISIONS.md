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
  - **medido en el arranque real del 2026-09-25 (19:03)**: de los cinco
    servidores builtin, cuatro conectan —`email` con 16 herramientas,
    `image_gen`, `memory` y `rag` con 1 cada uno— y `builtin_browser`
    **falla** con `[WinError 2]` porque no hay npx en PATH. La superficie de
    control de navegador que habría tumbado el argumento de severidad media no
    existe en este equipo; en otro con npx sí existiría. La corrección no
    depende de ese dato: la cláusula bloquea los cinco por igual.
  - **sigue sin verificar**: la afirmación de «una sola llamada por ejecución»
    atribuida a la compuerta de contexto externo.
- Medición que sí es firme: `known_tool_names()` = **82** nombres, **0** con
  prefijo `mcp`, y `validate_task_tools` exige `names <= known_tool_names()`,
  así que ninguna allowlist puede contener un nombre MCP cualificado.

## ADR-012 · Configuración por variables de entorno

- `CMH_OS_UI_ENABLED` (por defecto `true`) y `CMH_OS_DEFAULT_MODE`
  (`auto` | `demo`). Se leen en el servidor y se exponen sin secretos en
  `GET /api/cmh/os/config`. Se documentan en `.env.example`.

---

## ADR-019 · Compuerta de costo cero por host, con su límite declarado

- **Contexto.** Decisión D1 del usuario (2026-09-28): ningún agente, paso de
  flujo ni automatización llama a un endpoint de pago. El endpoint Anthropic
  `9a76d7a3` no se borra: sirve al chat personal y queda excluido de la cadena.
- **Decisión.** `src/cmh_cost_policy.py` clasifica una ruta como gratuita si el
  endpoint es un runtime local o si su host está en `FREE_HOSTS`
  (`api.groq.com`, `openrouter.ai`); en OpenRouter exige
  además que el modelo termine en `:free`, y un modelo desconocido **falla
  cerrado**. Coincidencia de host **exacta**, nunca por sufijo.
- **Cuatro sitios de aplicación**, no tres: enlazar agente y tarea
  (`cmh_control_routes._validate_task_link`), crear la definición
  (`_assert_definition_zero_cost`), congelar el run (`_snapshot`) y por
  candidato en `cmh_workflows.call_model`. El tercero se añadió porque una
  definición solo guarda un `agent_id`: repuntar el agente después de guardarla
  dejaba pasar una ruta de pago, y hay una prueba que lo demuestra.
  *(Equivalencia con `round5`, que muta ocho lugares de código: SI01 y SI02 son «enlazar
  agente y tarea»; SI03, la definición; SI04, SI07 y SI08, congelar el run —`_snapshot` y
  la lista que arma el router—; SI05 y SI06, `call_model`. Cuatro sitios conceptuales,
  ocho sitios de código.)*
- **Límite declarado, no implícito.** La clasificación es **por host**: no puede
  ver si una cuenta tiene método de pago, así que un nivel gratuito y uno de
  pago sobre el mismo host le resultan idénticos. Esa mitad de la garantía es
  operativa —las cuentas se registran sin tarjeta— y está escrita en el módulo.
- **`endpoint_kind = "auto"` cuenta como local solo con host loopback.**
  *(Reemplazado en este punto por ADR-026 y ADR-032: `auto` cuenta como local sobre
  loopback **o red privada**, y decide el host, no la etiqueta.)* El
  valor por defecto en la base es `auto`; exigir la cadena literal `"local"`
  habría bloqueado un endpoint loopback que nadie reetiquetó. `api` y `proxy`
  nunca cuentan como locales, ni sobre una URL loopback: quien los etiquetó así
  declaró un túnel.
- **Descartado: reutilizar `endpoint_cost_tracked`** (`src/endpoint_resolver.py`).
  Responde «¿contabilizo costo?» con una heurística sobre cualquier host global
  y devuelve verdadero para los tres proveedores gratuitos por igual.
  Reutilizarlo habría bloqueado exactamente lo que D3 quiere usar.

## ADR-020 · Un paso congela una lista de candidatos, no una ruta

- **Contexto.** Decisión D3: APIs gratuitas primero, local como respaldo. Un
  paso que congelaba un solo `endpoint_url` moría con su proveedor.
- **Cadena vigente desde el 2026-09-29: Groq → OpenRouter `:free` → LM
  Studio.** Cerebras salió (ADR-024).
- **Decisión.** El run congela una **lista ordenada** de candidatos
  (`src/cmh_provider_router.resolve_candidates`) y el ejecutor la recorre. Se
  conserva la semántica de «congelado por paso» del punto limpio 3: lo que un
  paso va a llamar no cambia bajo sus pies a mitad de ejecución.
- **Orden de eliminación: costo → cuota → alcanzabilidad.** El costo primero,
  para que una ruta de pago no se intente ni cuando todo lo demás ha fallado;
  la cuota antes de enviar, para que la llamada que cruzaría el límite no se
  haga; la alcanzabilidad al final, porque es lo único que solo se aprende
  intentando.
- **Solo las negativas a responder cambian de proveedor**: 402, 408, 429, 5xx y
  timeouts. Un 401 o un 400 es un defecto de configuración que el proveedor
  siguiente encontraría igual, así que detiene el paso donde ocurrió.
- **Precedencia de política: paso > agente > automatización.** Por
  especificidad, no por quién la escribió último. Un nombre de política no
  reconocido no se honra: cae al valor por defecto en vez de convertirse en
  política por un error de tecleo.
- **Sin respaldo de pago.** Si ningún candidato gratuito sirve, el paso falla.

## ADR-021 · Las cuotas se cuentan aquí, y son una estimación de las del proveedor

- **Decisión.** Tabla nueva `cmh_provider_quota` con ventana **explícita y
  truncada** (`minute`, `day`) por endpoint: «cuánto se gastó hoy» es una
  búsqueda, no un recorrido del historial de peticiones. Los límites viven en
  `config/cmh_free_quotas.json` con `source_url` y `source_date`.
- **Descartado: ventana deslizante.** Necesitaría justo el registro de
  peticiones que esta tabla existe para no llevar.
- **El umbral es 0,9 y es un margen, no un adorno.** Nuestro conteo ve las
  llamadas de esta instalación y no ve ni el reloj del proveedor ni a sus otros
  clientes. El 10 % restante absorbe esa diferencia en vez de fingir que no
  existe.
- **Un límite nulo significa no medido, nunca ilimitado.** Ninguna cifra del
  JSON está verificada todavía: las tres llevan `verified: false` y un
  `PENDIENTE` que nombra qué leer en el panel del proveedor. `GET /api/cmh/quotas`
  propaga ese `verified` para que la interfaz no pueda pintar una suposición
  como medición.

## ADR-022 · Las instrucciones que salen de la máquina se derivan, no se recortan

- **Contexto.** Las instrucciones de los cinco agentes viajan a proveedores
  externos. El plan era una copia depurada: quitar cifras financieras, nombres
  de archivos financieros, rutas locales y nombres de personas.
- **Medición que cambió el enfoque.** Sobre los cinco originales, **35
  instrucciones nombran una capacidad que un paso de Odysseus no tiene**:
  invocar a otro agente (14), leer el canon o `fuentes/` (8), correr Bash (6),
  escribir archivos (5), la web (2). Un paso tiene `read_file, ls, grep, glob` y
  una carpeta sin nada de eso. El recorte línea a línea se intentó primero y
  produjo frases truncadas y un procedimiento que mandaba al verificador
  «correr» una frase.
- **Decisión.** Cada rol se reescribe alrededor de lo que su paso puede hacer,
  conservando las reglas de gobierno del original —no autoevaluarse, conteos y
  no adjetivos, `PENDIENTE` nunca un cero silencioso, el formato del veredicto,
  la tabla de severidad, la cobertura declarada— y soltando su mecánica.
  `scripts/cmh_seed/scrub_instructions.py` genera los cinco archivos y audita:
  cuántas líneas del original sobreviven literales, cuántas no, y las lista.
- **Razón.** Una instrucción que no se puede seguir produce la disculpa que la
  guardia de evidencia rechaza. Copiarla literal no es fidelidad: es un fracaso
  programado.
- **Control de fuga con autoprueba.** Seis patrones (ruta absoluta, OneDrive,
  `.xlsx`, plantilla, importe con moneda, ratio o covenant nombrado) medidos
  contra el cuerpo derivado, no contra la cabecera que el propio guion escribe,
  y probados contra sondas que deben disparar.

## ADR-023 · La guardia de evidencia de herramientas se enciende por rol

- **Contexto.** Pendiente del canon 06 del 2026-09-24: la guardia existía y
  estaba verificada para tareas programadas, pero `cmh_workflows.call_model`
  nunca pasaba la bandera, así que un paso con **cero** llamadas exitosas
  producía artefacto igual y lo pasaba al siguiente.
- **Decisión.** La definición lo decide por paso y el run congela la respuesta.
  Por defecto `true`; `revisor` y `documentador` son las excepciones
  deliberadas, porque trabajan sobre los artefactos que recibieron y no sobre
  los archivos.
- **Un run congelado antes de que esto existiera se lee como `true`.** El valor
  laxo es el tentador y habría eximido en silencio a toda ejecución anterior.
  Fijado por prueba.

## ADR-024 · Cerebras sale de la cadena de costo cero (2026-09-29)

- **Contexto.** D3 (2026-09-28) ordenaba Groq → Cerebras → OpenRouter `:free` →
  LM Studio, sobre la premisa —del autor del encargo, marcada VERIFICAR— de que
  los tres tenían nivel gratuito y podían usarse sin método de pago.
- **Medición.** Cerebras **no tiene nivel gratuito permanente**. Lo que ofrece
  es una prueba de 5 USD en créditos que vence a los 30 días, y la API queda
  inactiva sin un método de pago verificado. Eso contradice de frente la
  condición sobre la que se apoya D1: cuentas sin tarjeta. Canon 05, filas
  VERIFICACION y DECISION del 2026-09-29, con fuente primaria y confirmación
  del refutador.
- **Decisión.** `api.cerebras.ai` sale de `FREE_HOSTS` y del JSON de cuotas. La
  cadena queda **Groq → OpenRouter `:free` → LM Studio**. Sacarlo del conjunto
  no es cosmético: es lo que hace que la compuerta lo **rechace** en vez de
  tratarlo como gratuito.
- **Por qué además hay pruebas y no solo un borrado.** Tres pruebas fijan que
  el host no está en `FREE_HOSTS`, que no está en el JSON, que un paso apuntado
  ahí se rechaza y que ni escrito a mano en el JSON entra a la lista de
  candidatos. Volver a meterlo exige una decisión contra una suite en rojo, no
  un descuido.
- **Efecto en las pruebas.** Cerebras era el segundo candidato gratuito de cada
  prueba de fallback. Su lugar lo toma OpenRouter, lo que las vuelve más
  estrictas: allí un modelo sin sufijo `:free` lo rechaza la compuerta.
- **Descartado.** Conservarlo «para los 30 días de prueba»: una cadena que deja
  de funcionar en una fecha, y que entre tanto exige una tarjeta registrada, no
  es costo cero sino costo diferido.

## ADR-025 · Correcciones de la segunda revisión independiente (2026-09-29)

La ronda 2 midió sobre la etiqueta congelada `revision-fase1-r2` y devolvió
DEVUELTO: **dos de los tres arreglos centrales de la ronda 1 introdujeron
defectos nuevos**. Lo que sigue es lo que cambió y por qué, no un registro de
que se corrigió.

- **Un identificador de endpoint nulo destruía el trabajo que contabilizaba.**
  `_snapshot` congelaba `endpoint_id: None` y `_frozen_candidates` usaba
  `setdefault`, que **no reemplaza una clave presente con valor `None`**. Como
  `cmh_provider_quota.endpoint_id` es `NOT NULL`, el paso llamaba al modelo,
  producía su artefacto y **lo perdía** al contabilizar la cuota. El caso se
  alcanza cuando la URL de la tarea no resuelve a una fila registrada del mismo
  host, que es un caso que el propio módulo declara soportado. Ahora el id se
  resuelve en `_snapshot` y, a falta de fila, se usa la URL; nunca `None`.
- **La simulación del guion de siembra escribía en la base y ya no copiaba.**
  Condicionar la copia a `--apply` fue un error doble: el `import
  core.database` sigue ejecutando `init_db()` y migra lo que apunte
  `DATABASE_URL`, así que la simulación migraba **sin respaldo**. Ahora la
  simulación trabaja sobre una copia desechable; la base real **solo se lee para
  copiarla y nunca se migra** (decía «no se abre», y sí se abre en `mode=ro`).
- **La deduplicación de candidatos es por host y puerto** (el modelo salió en
  ADR-026: un 429 lo aplica el proveedor por cuenta y host, no por modelo). Comparar
  cadenas de URL listaba dos veces al mismo proveedor —una fila
  `https://api.groq.com` y una tarea en `.../openai/v1`—, de modo que un 429
  reintentaba el host que acababa de rechazar. Comparar solo por host tenía el
  defecto opuesto: dos runtimes locales en puertos distintos se fundían en uno
  y uno desaparecía de la lista. Para la nube el host **es** el proveedor; para
  loopback hace falta el puerto.
- **El default por rol tiene una sola casa.** `create_run` mantenía un `True`
  propio, así que toda definición ya almacenada seguía exigiendo evidencia de
  herramientas al revisor y al documentador. Ahora baja a
  `default_tool_evidence`. **Un valor explícito se honra**: no se distingue de
  una elección deliberada, y sobreescribirlo dejaría el campo inservible para
  esos dos roles. Medido antes de decidir: 0 definiciones y 0 ejecuciones
  almacenadas, así que no hay nada que migrar.
- **Una política no reconocida se rechaza con 400.** `local_only` con guion
  bajo se degradaba a `None` y enrutaba a la nube. El único ajuste cuyo
  propósito es que nada salga de la máquina no puede fallar abierto ante un
  error de tecleo.
- **El artefacto lleva el modelo que lo escribió.** La ronda 1 corrigió solo la
  etiqueta del evento; el artefacto —lo que abre una persona— y el detalle de
  la ejecución seguían rotulados con el primer candidato congelado. `call_model`
  devuelve cuál respondió y el paso lo persiste.

### Lecciones de método, registradas porque se repitieron

1. **Los conteos deben reproducirse desde un clon limpio.** Tres pruebas leían
   `data/agent_workspace`, que `.gitignore` excluye: en la etiqueta exportada
   eran 222 aprobadas y 3 fallidas, no 225. Ahora generan sus archivos en un
   `tmp_path`, lo que además ejercita `main()`, que nada ejercitaba.
2. **Una prueba en proceso no puede observar un `import` ya hecho.** La prueba
   del `dry run` pasaba bajo el mutante porque `core.database` ya estaba
   importado por la sesión de pytest. Las dos garantías del guion se miden en
   **subproceso**, que es como el guion se usa.
3. **Los mutantes se versionan.** La cifra «12 de 12» de la ronda 1 no era
   reproducible: vivían en un archivo temporal. `scripts/cmh_mutants/round2.py`
   está en el repositorio.
4. **Una prueba escrita junto a su arreglo comparte sus suposiciones.** Tres
   veces una prueba nueva no podía distinguir el mutante del original: una
   disyunción que aceptaba la forma defectuosa, una aserción sobre el `config`
   en memoria en vez de sobre la fila almacenada, y una comparación entre dos
   cadenas que resultaron ser la misma.

## ADR-026 · Qué es «local», y dónde vive una credencial (2026-09-29)

Dos decisiones del usuario, tomadas sobre mediciones y no sobre preferencia,
después de que la cuarta revisión independiente mostrara que ninguna de las dos
estaba definida y que el vacío era un hueco técnico.

### `local-only` significa loopback **o red privada**

- **Medición que abrió la pregunta.** `is_local_endpoint` decidía por la
  **etiqueta**: una fila `https://gpu.corp.example/v1` marcada
  `endpoint_kind="local"` pasaba la compuerta de costo **y** encabezaba la lista
  bajo `local-only`, una política cuyo docstring promete que nada sale de la
  máquina.
- **Decisión.** Decide el **host**: loopback, RFC1918 (10/8, 172.16/12,
  192.168/16), link-local y `.local` cuentan (ADR-032 añadió `fc00::/7` y los nombres
  `0.0.0.0` y `host.docker.internal`); un host público no, lleve la
  etiqueta que lleve. `api` y `proxy` siguen descalificando incluso sobre
  loopback, porque quien los escribió declaró un túnel.
- **Por qué no «solo loopback».** Una GPU en la LAN de CMH es infraestructura
  propia y el tráfico no sale de la red. *Alternativa descartada:* que mandara
  la etiqueta del administrador — obligaba a renombrar la política, porque el
  tráfico sí saldría de la máquina.
- **Efecto medido:** 9 casos, 9 correctos. Cierra además el mutante R16, que la
  ronda 3 había retirado como «inalcanzable» con una razón que solo cubría una
  de las dos direcciones.

### Una credencial en la URL se traslada a `api_key` al registrar

- **Medición que corrigió una afirmación falsa.** Un commit anterior declaraba
  «verificado que nada pierde acceso: la autenticación sale de `api_key`, nunca
  del userinfo». Es falso: con httpx 0.28.1, `Client._build_request_auth`
  convierte el userinfo en `Authorization: Basic` **al enviar**, y
  `llm_core` construye su `AsyncClient` sin `auth=`. Comprobar `build_request`
  —la capa equivocada— fue lo que lo ocultó, dos veces.
- **Decisión.** `split_url_credentials` la extrae al registrar el endpoint: pasa
  a `api_key` cifrada como cabecera `Basic` y la URL se guarda limpia. Una sola
  forma de la URL viaja, y la que se marca autentica igual. *(Corregido en r8: hasta entonces
  esto era falso. `build_headers` envolvía ese `Basic <base64>` en `Bearer` y el servidor recibía
  `Authorization: Bearer Basic ...`, que ninguno acepta: un endpoint registrado o editado con
  `usuario:clave@` daba 401 donde la URL cruda autenticaba. Lo midieron dos lentes de la segunda
  revisión por separado. Ahora `build_headers` envía un valor que ya empieza por `Basic ` tal
  cual, y una prueba registra el endpoint por POST y por PATCH, por las rutas reales, y captura
  la cabecera que sale.)*
- **Y el paso de flujo la rechaza, no la recorta.** Una tarea cuya URL lleve
  credenciales se refusa con 400 pidiendo re-registrar el endpoint. Recortarla
  habría quitado autenticación que funciona; conservarla la habría persistido en
  el config congelado y emitido por SSE. *Medido:* 0 endpoints con userinfo en
  la base activa, así que nadie queda fuera hoy. *(r8: lo mismo para una FILA registrada
  cuya URL aún lleve credenciales: `create_run` responde 400 pidiendo re-registrarla. r7 la
  recortaba al congelar y el ejecutor, que halla la fila por URL, ya no la encontraba: el paso
  salía sin Authorization, que es peor que el 401 que se quería evitar.)*

### Correcciones de método de esta ronda

- **La deduplicación de candidatos es por proveedor, sobre la lista entera.**
  Depurar solo contra la clave de la tarea dejaba dos caminos para que un
  proveedor apareciera dos veces: una fila de host gratuito registrada como
  `local` la emiten **las dos** ramas de `resolve_candidates`, y dos filas
  habilitadas pueden compartir `base_url`.
- **La guarda de área protegida corre antes de todo import que toque la base.**
  Las reglas se extrajeron a `src/cmh_protected_areas.py`, que no importa
  `core.database`. Antes, rechazar una raíz prohibida imprimía «no se siembra
  nada» **después** de que `init_db()` hubiera migrado el esquema vivo.
  *Medido tras el cambio:* la base queda byte a byte idéntica.
- **Los conteos se miden sobre un export aislado de verdad.** Las tres
  afirmaciones anteriores de «clon limpio» eran falsas: dos por estado heredado
  del scratchpad y una por un fixture sin `git add`. Los originales de los
  agentes **no se versionan** —llevan nombres de archivos financieros—, así que
  las pruebas usan un fixture sintético en `tests/fixtures/agent_sources` con la
  misma forma y ningún dato real. Primer conteo reproducible: **295**.

---

## ADR-027 · El status del proveedor llega al router: el fallback reactivo existe (2026-09-29)

- **Contexto.** La auditoría de 6 lentes del 2026-09-29 midió que un 402, 408, 429,
  5xx, timeout o error de conexión de Groq mataba el paso en su primer candidato: 8
  de 8 fallas reales simuladas sobre la cadena real, con 0 eventos `provider_fallback`
  y 0 peticiones al segundo candidato. El status viaja en el chunk `event: error`
  como entero; `_run_agent_loop` lo aplanaba en un `RuntimeError` sin status,
  `is_fallback_error` respondía `None` y `call_model` relanzaba. Solo funcionaba el
  salto preventivo por cuota. Las pruebas del fallback (16 según el commit `dd87c675`; la revisión de r7 midió 18 líneas
  con `_run_one_candidate` en `tests/` antes de ese commit, y el criterio de las 16 no se
  escribió) sustituían
  `_run_one_candidate` por un doble que lanza una excepción con `.status_code`, la
  única forma que la cadena real nunca produce.
- **Decisión.** `RestrictedStreamError` (subclase de `RuntimeError`, en
  `src/task_scheduler.py`) conserva el entero como `status_code`; el mensaje sigue
  empezando por «Restricted task model stream failed». La prueba nueva recorre
  `call_model` → `_run_agent_loop` → `stream_llm` con un `httpx.MockTransport`: solo
  la red es falsa. Antes 8 fallaban y 5 pasaban; los 5 son los controles (proveedor
  sano; 400/401/403/404, que deben detener el paso).
- **Límite declarado.** Solo se guarda el número, no el texto del proveedor: un 401
  puede repetir parte de la clave rechazada y este mensaje termina en la columna
  `error` del paso y en el flujo SSE (ADR-011). Se decide por status: un
  `ConnectError` interno de `llm_core` llega ya convertido en 503.
- **Descartado.** Respetar el `fallback_eligible: false` que `llm_core` pone en
  algunos errores (timeout genérico, error de protocolo): cada candidato reinicia el
  paso desde cero sobre herramientas de solo lectura, así que reintentar en otro
  proveedor no tiene efecto colateral, y ADR-020 manda que los timeouts cambien de
  proveedor. Habría dejado morir el paso en el primer timeout de Groq, que es el fallo
  que la cadena existe para absorber.
- **Pruebas.** `tests/test_cmh_step_provider_failures.py`; mutantes S01–S03 de `round4`.

## ADR-028 · El modelo de OpenRouter se descubre al crear el run (2026-09-29)

- **Contexto.** La entrada de OpenRouter en `config/cmh_free_quotas.json` dice
  `model: null` porque el catálogo gratuito rota, `resolve_candidates` salta a un
  proveedor sin modelo y `pick_openrouter_free_model` no tenía ningún llamador fuera de
  sus pruebas. Con U1, U2 y U4 hechas, la cadena real era Groq → LM Studio.
- **Decisión.** `create_run` consulta, una vez por run, el catálogo de cada proveedor
  sin modelo que tenga una regla para elegirlo (hoy solo OpenRouter), con la clave que
  el servidor ya guarda, y congela la elección con el resto de la lista. Se pregunta
  primero al listado de la cuenta (`/models/user`), filtrado por los ajustes de
  privacidad, porque eso hace que el ajuste que U2 pide activar decida qué modelos
  `:free` son elegibles; el listado general se usa solo si esa ruta no existe (404; hasta r7 se usaba ante cualquier
  fallo y esta ADR decía lo contrario sin que fuera cierto). Un 200 sin
  ningún modelo elegible **no** se amplía al listado general: es la cuenta diciendo que
  no. Un fallo deja al proveedor fuera de la lista y lo dice un evento
  `provider_discovery`, uno por intento. La elección se cachea por endpoint durante
  `discovery.ttl_s`; un modelo escrito en el config gana siempre. **No corre bajo
  `local-only`**: una consulta de catálogo es una llamada al proveedor con la clave de
  la cuenta (lo encontró la prueba escrita para fijarlo).
- **Límite declarado.** **No verificado** que `/models/user` exista y traiga
  `supported_parameters` y `context_length`: una búsqueda lo nombra, la página de
  detalle de su documentación respondió 404 el 2026-09-29. Un modelo elegido puede
  seguir respondiendo 404 por política de datos; un 404 no cambia de proveedor
  (ADR-020) y el paso muere. El TTL y el timeout son valores iniciales propuestos.
- **Descartado.** Fijar el modelo en el config (sigue permitido y manda, pero como
  valor único un modelo `:free` retirado o excluido por privacidad rompería la cadena);
  descubrirlo al arrancar el proceso (sin clave todavía, y se queda viejo); descubrirlo
  por llamada (una consulta más en cada ronda).
- **Corregido en r7** (revisión independiente del 2026-09-29). El listado general se usaba
  ante cualquier no-200 (401, 429, 5xx, un timeout) y esa elección, hecha sin el filtro de la
  cuenta, se cacheaba seis horas: ahora se amplía solo ante 404, la nota dice por qué y esa
  elección se confía 15 min (`unfiltered_ttl_s`). Sin clave registrada no se consulta nada
  (antes salía anónima y OpenRouter entraba en la lista para morir con un 401), ni por http,
  ni a una `base_url` mal formada; una carga de forma inesperada o una regla que lanza
  dejan al proveedor fuera en vez de tumbar `create_run`; los valores de `discovery` se
  validan; `timeout_s` es el **tiempo total** de las dos consultas (`asyncio.wait_for`); un
  fallo se recuerda `failure_ttl_s` (60 s) para no cobrar el timeout a cada run; y la
  caché se indexa por fila, URL y un hash de la clave, de modo que rotar la clave no sirve
  el modelo de la cuenta anterior.
- **Reemplaza texto del blueprint.** §9.1 dice que OpenRouter elige «el primer `:free` de
  `GET /models`»: rige esta ADR (`/models/user` primero, `/models` solo ante 404, con la
  clave registrada y por https).
- **Pruebas.** `tests/test_cmh_provider_discovery.py`; mutantes D01–D12 (r6) y D13–D33
  (r7) de `round4`; D06–D08 se reapuntaron porque el bucle que mutaban ya no existe.

## ADR-029 · El respaldo local se llama por su identificador, no por el modelo del agente (2026-09-29)

- **Contexto.** El candidato local se llamaba con `agent.model`. Para un agente de Groq
  eso es `openai/gpt-oss-120b`, un nombre que ningún runtime local sirve: el último
  eslabón habría respondido 404, que es un fallo de configuración y detiene el paso, así
  que el respaldo local nunca habría funcionado para un agente configurado en la nube.
  Dos pruebas de la segunda revisión fijaban lo contrario; su razón era real (un paso
  producido por un modelo y rotulado con otro), pero el artefacto ya lleva el modelo que
  lo escribió (ADR-025).
- **Decisión.** Un runtime local se llama con, en orden: `local_model` explícito, el
  `local.model` del config (`cmh-local`, el identificador que fija
  `lms load --identifier`, así que no cambia cuando el banco elige otro ganador), o lo
  que el runtime tenga en caché. Nunca el modelo del agente. Un agente configurado con un
  endpoint local conserva su ruta, antepuesta con su propio modelo.
- **Límite declarado.** Hasta que el usuario cargue un modelo con ese identificador
  (U4, `start.ps1`), el respaldo local responde 404. El blueprint §21-U4 solo pide ver el
  endpoint en `model_endpoints`: U4 tiene que incluir `start.ps1 -Model <modelo> -UnloadOthers` (sin el
  interruptor se niega a descargar lo que el usuario tenga cargado) y comprobar
  con `lms ps` que `cmh-local` está cargado. Además `local.model` se aplica a **todas** las
  filas locales habilitadas, no solo a la que carga `start.ps1`: un Ollama sin deshabilitar
  (U5) se llama también `cmh-local`, responde 404 y ese 404 detiene el paso enmascarando el
  rechazo original. **No verificado en vivo**; por eso U5 pide deshabilitarlo.
- **Descartado.** Descubrir el modelo cargado con `GET /v1/models` de LM Studio: una
  llamada más al crear el run y elegiría lo que esté cargado por casualidad. Un nombre
  en una celda del config es parametrizable y es con el que `start.ps1` ya carga.
- **Pruebas.** `tests/test_cmh_provider_discovery.py` y `tests/test_cmh_review_findings.py`
  (R12 reapuntado); mutantes L01–L02 de `round4` y R12 de `round3`.

## ADR-030 · La cuota cuenta lo que el paso gastó: rondas, tokens y rechazos (2026-09-29)

- **Contexto.** La cuota se cargaba una vez por paso EXITOSO con `requests=1` y sin
  tokens. `tpm` y `tpd` no podían dispararse aunque el JSON los llevara (llenar los
  cuatro límites, blueprint 9.5, no habría cambiado nada respecto de los tokens);
  `rpm` y `rpd` contaban pasos y un paso hace hasta `max_rounds` peticiones; y una
  llamada rechazada no se contaba. Con 4 ejecuciones diarias frente a 200 000 tokens
  diarios de Groq, el límite que importa a 24/7 era el muerto.
- **Decisión.** El bucle reporta sus totales en un solo evento `model_metrics` al final
  de cada intento: tokens sumados sobre todas las rondas y un `usage_bucket` por ronda.
  El planificador reenvía cuántas rondas cubren los totales (solo si el bucle las
  reportó: desconocido no es cero; los buckets no se reenvían) y `call_model` carga al
  candidato desde ese evento. Medido sobre la cadena real: un paso sano carga 1
  petición, 3 tokens de entrada y 2 de salida, y un límite de 10 tokens al umbral 0,9
  saca a Groq de la lista en el tercer paso. Un intento rechazado cuesta 1 petición y 0
  tokens; uno que falla después de reportar su uso no se cobra dos veces; un fallo al
  escribir la cuota se registra y no tumba el paso.
- **Límite declarado.** *(Corregido en r7.)* Esta ADR decía que un intento que muere a
  media ejecución se cobra 1 petición y ningún token «porque el bucle reporta sus totales
  solo al terminar». La causa era falsa: el bucle reporta lo gastado en un chunk
  `agent_terminal` justo antes del chunk de error y el planificador lo ignoraba. Desde r7 se
  reenvía como `model_metrics` con `failed=true` y `rounds` = un texto por ronda HTTP, la
  fallida incluida. Medido sobre la cadena real: dos rondas de 10/5 tokens y un 429 cargan 3
  peticiones y 20/10 tokens. Sigue **sobrestimando** un intento rechazado antes de enviar
  (configuración inválida, cooldown sintético 503): cuenta 1 petición sin que haya salido. Un
  fallo al escribir la cuota se registra en el log, no en un evento del run. El blueprint §7.3
  dice que `model_metrics` se emite «cada ronda»: se emite **uno por intento**, con un bucket
  por ronda, y `provider_discovery` (ADR-028) no figura en su lista de eventos; §7.3 queda
  corregido por esta ADR. Los tokens son
  los del proveedor cuando los informa y una estimación cuando no (`usage_source`). Que
  un rechazo cuente contra el límite del proveedor **no está verificado**.
- **Descartado.** No contar lo rechazado (era la regla anterior, «nunca sirvió una
  petición»): sobrestimar solo hace que el router deje antes a un proveedor, y
  subestimar lo hace caminar hacia un 429. Ventana deslizante (ADR-021).
- **Pruebas.** `tests/test_cmh_step_provider_failures.py` y `tests/test_cmh_restricted_loop.py`;
  mutantes Q01–Q08 (r6) y Q09–Q15 (r7) de `round4`.

## ADR-031 · Un mutante solo cuenta como capturado si una prueba falla, y ningún corredor toca el árbol vivo (2026-09-29)

- **Contexto.** Dos defectos de la herramienta de medición, ambos midiendo mal y ambos
  hallados por casualidad. (1) `round2.py` llevaba escrita la ruta del árbol vivo e
  ignoraba `CMH_MUTANT_REPO`: una campaña lanzada «sobre una copia» mutó archivos
  versionados durante unos 5 minutos y contaminó las pruebas que se corrieron en esa
  ventana; se vio porque `git status` mostró dos archivos que nadie había editado.
  (2) Los corredores contaban como capturado cualquier salida distinta de cero de
  pytest: `R17` de `round3` dejaba `_skip = ` sin valor, un `SyntaxError` en la línea
  248, y figuraba en el «13 de 13 capturados» de `4fca1184` sin que ninguna prueba
  hubiera demostrado detectar la deduplicación que decía retirar.
- **Decisión.** `_target.resolve_repo` es la única forma de elegir el destino y se
  niega ante cualquier carpeta con `.git` (un export no lo tiene; el árbol de trabajo
  sí). `verdict()` distingue SURVIVED, CAUGHT (salida distinta de cero **y** una línea
  `FAILED`) e INVALIDO (rompe la colección). `test_cmh_mutant_validity` aplica en
  memoria cada mutante de las tres campañas y comprueba que el patrón existe y que el
  resultado compila. En su primera corrida halló 3 mutantes de `round2` obsoletos
  (M25, M26 retirados; N1 reapuntado) y un `D01` propio obsoleto.
- **Límite declarado.** «Compila y una prueba falla» no prueba que la prueba que falla
  sea la que debía: `cae:` muestra cuál es, y leerlo sigue siendo trabajo humano. Para
  PowerShell el comprobador solo detecta errores de **sintaxis**: un mutante con una función
  inexistente o una propiedad mal escrita compila y, si cae una prueba por ese motivo, cuenta
  CAUGHT sin que la conducta objetivo se haya observado; por eso los mutantes de `round6`
  designan una prueba por id de nodo, para que eso sea revisable. Sin PowerShell (o sin
  `bash` para los `.sh`) la prueba de validez **se omite** y lo dice: antes daba por bueno un
  mutante que nadie había analizado.
- **Corregido en r7.** El bucle común `campaign()` no tenía prueba propia y tres formas de
  mentir: no corría las pruebas sin mutar (con una prueba roja todo mutante «caía», también
  uno que no cambiaba nada), la negativa a mutar el árbol vivo vivía solo en `resolve_repo`, y
  reescribía con `write_text` (CRLF a la plataforma) sin comparar. Ahora corre una línea base
  (sale con 4 si está roja), rechaza por sí mismo una carpeta con `.git`, lee y escribe bytes,
  compara la restauración y exige el árbol restaurado en verde para salir con 0; `round2` a
  `round4` dejaron de llevar bucles propios.
- **Descartado.** Confiar en la disciplina de lanzar siempre sobre un export: eso es lo
  que ya estaba escrito en el encabezado de `round3` y no impidió el incidente.
- **Pruebas.** `tests/test_cmh_mutant_target.py`, `tests/test_cmh_mutant_validity.py`,
  `tests/test_cmh_mutant_campaign.py` (r7); mutantes T01–T03 (r6) y T04–T11 (r7) de `round4`.

---

## ADR-032 · La compuerta de costo cero nombra sus redes y tiene mutantes versionados (2026-09-29)

- **Contexto.** La regla más importante del proyecto (nada que un agente, paso o
  automatización de CMH llame puede costar) estaba respaldada por 17 pruebas y por
  **ningún mutante versionado**: las campañas de las rondas 2 a 4 mutan el router, la
  siembra y las rutas, y las dos menciones de `cmh_cost_policy` en ellas son nombres de
  archivos de prueba. La primera campaña sobre la compuerta (`round5`, 20 mutantes)
  capturó 18 y dejó vivos 2. CG07 («todo 172.x cuenta como red privada») sobrevivió
  porque nada probaba el borde de 172.16/12. CG09 («link-local deja de contar») sobrevivió
  porque no cambiaba nada: el código decidía con `ipaddress.is_private`, que ya contiene
  link-local (medido en Python 3.13.14: `169.254.x` y `fe80::/10` son privadas).
- **Decisión.** «Local» es loopback más redes **nombradas**: 10/8, 172.16/12, 192.168/16,
  169.254/16, fe80::/10 y fc00::/7 (el análogo IPv6 de RFC1918), y los nombres `localhost`,
  `0.0.0.0`, `host.docker.internal` y `*.local`. `is_private` deja de decidir: incluye
  192.0.2.0/24 (documentación) y 240.0.0.0/4 (reservado), que ADR-026 no lista, y ha
  cambiado entre versiones de Python. Solo estrecha: lo que deja de ser local es
  inenrutable y no es una dirección realista de runtime. 36 casos de frontera (esta ADR y el commit `8c831e50` decían 45: la cuenta era errónea; r7 los
  lleva a 44), ambos lados
  de cada borde, con las etiquetas `auto` y `local`, y `api`/`proxy` comprobadas como
  nunca locales. `round5` cerró con **24 de 24** capturados, 0 sobrevivientes, 0 inválidos en
  r6 (con 39 de 39 en r7: ver ADR-036).
- **Resuelve el VERIFICAR de §9.3.** `endpoint_kind=auto` sobre una red privada **sí** es
  local (lo fijan las pruebas de frontera; la cifra «48 combinaciones» de la versión inicial no
  tenía guion versionado y se retira). La
  frase de ADR-019 («`auto` cuenta como local solo con host loopback») quedó reemplazada por
  ADR-026.
- **Límite declarado.** Los nombres `*.local` cuentan como locales **sin resolverse**: se
  asume mDNS en la LAN, y no se verifica a qué dirección resuelve. 100.64/10 (CGNAT, donde
  vive Tailscale) queda fuera por **SUPUESTO de esta ADR** (ADR-026 no lo dice): una GPU detrás
  de Tailscale no cuenta como `local-only` hasta que alguien decida lo contrario.
- **Descartado.** Conservar `is_private` y solo añadir pruebas: la definición seguiría
  dependiendo de la versión de Python que corra.
- **Corregido en r7.** `enforced()` fallaba **abierto** (cualquier valor fuera de
  `1/true/yes/on` apagaba la compuerta sin decirlo): ahora solo `0/false/no/off` la apagan y
  dejan un aviso en el log; `describe()` prometía «sin secretos» e imprimía `user:pass@` (y el
  evento `zero_cost_blocked` la URL cruda): pasan por `redact_url`; un host gratuito por http
  ya no cuenta como gratuito (mandaría la clave en claro). `endpoint_for_url` sigue eligiendo
  por subcadena en el ejecutor (`task_scheduler`), que es código de Odysseus: la compuerta
  rechaza antes la URL engañosa, pero una tarea fuera de la cadena CMH no pasa por ella.
- **Pruebas.** `tests/test_cmh_cost_policy.py`; mutantes CG01–CG16 y SI01–SI08 (r6: 24) y
  CG11b, CG17–CG30 (r7) de `round5`.

## ADR-033 · Los guiones del banco local miden lo que dicen y no tocan lo que no cargaron (2026-09-29)

- **Contexto.** El paso 3.4 estaba registrado como «guiones listos». No podían arrancar:
  `bench.ps1` abortaba en su primera llamada a `lms.exe` bajo Windows PowerShell 5.1, el único
  instalado, porque `2>&1` sobre un nativo con `ErrorActionPreference=Stop` vuelve error
  terminal la primera línea de stderr. Detrás, medido con `lms ps` y `lms ls` reales: no medía
  el primer token (`stream=false`); sus «3 rondas» eran 3 peticiones idénticas de un turno,
  sin ejecutar nunca la herramienta; sin `-Models` medía los 9 LLM del disco; su
  `lms unload --all` habría descargado el `qwen/qwen3.8-27b` (17,74 GB) que el usuario tenía
  cargado; y `start.ps1` exigía más de 2 líneas de `lms ps`, que con un modelo cargado son 2.
- **Decisión.** `bench.ps1` ejecuta una conversación real (cada herramienta pedida se
  ejecuta y su resultado vuelve al modelo hasta que responde con texto), con streaming para
  separar el primer token de la velocidad de generación (tokens sobre el tiempo posterior al
  primer token, no sobre el total). Valida cada llamada (nombre conocido, argumentos JSON con
  `path`), mide por nombre los tres candidatos del blueprint y dice cuáles no están en disco,
  y **se niega a descargar lo que no cargó** salvo `-UnloadOthers` *(en r6 solo era cierto de
  `bench.ps1`, y ni de él: medía bajo `cmh-local` y descargaba justo lo que `start.ps1` deja
  cargado; r7 mide bajo `cmh-bench` y `start.ps1` exige el mismo interruptor)*. Ambos guiones llaman a
  `lms` por un ayudante que relaja `ErrorActionPreference` solo alrededor de la llamada. Se
  encontró al ejecutarlo: las variables de PowerShell ignoran mayúsculas, y un `$rounds` local
  sombreaba el parámetro `-Rounds`.
- **Límite declarado.** **La velocidad real de LM Studio no está medida**: hace falta el
  usuario (U4: modelos y LM Studio). Las pruebas usan un `lms` y un servidor falsos; miden que
  el guion computa bien, no cuánto tarda un modelo real. Los tokens son los del servidor
  cuando informa `usage` y una estimación marcada cuando no.
- **Descartado.** Reparar solo la línea 92: el resto medía otra cosa de lo prometido. Ejecutar
  la prueba con `-File` a secas: una lista llega como UNA sola cadena `a,b` y no se enlaza a un
  `[string[]]` (medido en r7: `count=1 items=[a,b]`); las pruebas usan `-Command` y, desde r7, el
  guion parte la cadena por comas y recorta cada pieza.
- **Corregido en r7.** Solo cuenta como respuesta final una ronda con `finish_reason` `stop` y
  texto (un flujo cortado o una ronda que gastó `max_tokens` razonando —ahora `-MaxTokens`,
  1024— no ganan); el código de salida de `lms ls`, `ps` y `unload` se comprueba; tok/s solo
  cuenta rondas de al menos 3 trozos y descuenta el primer token; sin ganador sale con 1;
  `start.ps1` comprueba el modelo detrás de un `cmh-local` ya cargado y no dice «Listo» sin
  verlo en `lms ps`. La ayuda documenta `-ExecutionPolicy Bypass` (la política es Restricted
  aquí) y `-Models "a,b"` (con `-File` una lista llega como una sola cadena); existe
  `start.sh`. **Sin medir:** `$request.Proxy = $null`; .NET ya evita el proxy en loopback,
  así que un servidor falso en 127.0.0.1 no distingue.
- **Pruebas.** `tests/test_cmh_local_scripts.py` (16 en r6, 43 en r7, bajo el PowerShell
  5.1.26100 real); mutantes B01–B12 y S01–S05 (r6) y B13–B31 y S06–S16 (r7) de `round6`.

## ADR-034 · La siembra crea la definición, guarda la política y no siembra una cadena vacía (2026-09-29)

- **Contexto.** El paso 3.5 es «cinco agentes y una definición». El guion creaba los
  agentes y **ninguna definición**: esa mitad era un clic manual en `/cmh`, con otro nombre,
  sin que nada registrara su id. Cuatro defectos más, medidos en el código: `--policy` se
  validaba, resolvía los candidatos y se descartaba (con `local-only` quedaba `NULL` y el run
  resolvía `free-cloud-first`); `live_database_path()` ignoraba `ODYSSEUS_DATA_DIR`, con lo
  que tras mover `data/` (22.1) la copia previa sería de la base vieja; sembraba cinco agentes
  sin modelo cuando no había ningún endpoint gratuito; y la copia previa llevaba resolución de
  minuto y no comprobaba si el nombre estaba libre.
- **Decisión.** `ensure_definition` crea una vez la definición con la forma que arma `/cmh`
  (cinco pasos, independencia para verificador y revisor, evidencia de herramientas salvo
  revisor y documentador, compuerta humana antes del revisor hasta el paso 5.4) y escribe una
  **versión nueva**, nunca una edición, cuando la guardada difiere; una idéntica se deja
  quieta, así que sembrar dos veces no cambia nada. La política se guarda en cada agente.
  `--apply` se detiene si no hay candidato gratuito (`--allow-pending` lo permite; *en r6 esto
  no era cierto con los endpoints vivos: los dos Ollama habilitados cuentan como candidatos
  locales y la guarda no se activaba; desde r7, bajo `free-cloud-first`, exige al menos uno
  gratuito de **nube**, y bajo `local-only` uno local*). La ruta
  sigue `ODYSSEUS_DATA_DIR` y resuelve las rutas relativas contra la raíz, como
  `core.database`. La copia previa lleva segundos y nunca reutiliza un nombre. El nombre de la
  definición no lleva flecha: imprimir U+2192 en una consola cp1252 lanzaba
  `UnicodeEncodeError` **después** de escribir en la base; además `main()` reconfigura sus
  flujos para reemplazar lo que no pueda imprimir.
- **Límite declarado.** La negativa a sembrar sin candidatos llega **después** de la copia
  previa: los candidatos exigen abrir la base y abrirla es lo que la migra, así que la copia
  tiene que existir antes (r7: el mensaje decía que la copia podía borrarse y no era cierto,
  porque la base pudo migrarse al abrirla; ahora dice que se conserve). **El guion no se ejecutó
  nunca contra la base activa**: exige la autorización U6.
- **Descartado.** Planificar sobre una réplica y aplicar sobre la real en dos fases: el motor
  de `core.database` se ata al archivo en la importación, así que exigiría dos procesos.
- **Corregido en r7.** La URI de la copia se arma con `Path.as_uri()` (un `#` en la ruta
  cortaba la URI, perdía `mode=ro` y creaba un archivo vacío sobre el que se imprimía
  «integrity ok»), la copia se compara con el origen por tablas, y una simulación sobre una
  base que no existe corre en memoria en vez de crear una completa en disco.
- **Pruebas.** `tests/test_cmh_seed_scripts.py` (9 nuevas en r6 y 6 en r7, sobre bases
  desechables construidas por el `core.database` real); mutantes SD01–SD13 de `round7` y Z01–Z08
  de `round9`.

## ADR-035 · El registro de una ejecución sale de sus filas, no de la memoria del agente (2026-09-29)

- **Contexto.** El encargo pide registrar, por paso, agente, proveedor y modelo resueltos,
  fallbacks, tokens, segundos, **exit de cada herramienta** y tamaño del artefacto. ESTADO y
  blueprint 7.3 decían que los eventos llevaban `exit_code` y el tamaño; la auditoría midió
  que no. El detalle `GET /runs/{id}` tampoco expone tokens, fallbacks ni tamaño.
- **Decisión.** `tool_finished` lleva el `exit_code` numérico y `step_completed` lleva
  `artifact_chars` (ambos aditivos). `scripts/cmh_ops/run_report.py` arma el registro completo
  desde la base y evalúa el criterio de cierre de la Fase 1: run `completed`, 5 artefactos,
  ningún paso en error, evidencia de herramientas donde se exige (una llamada con exit
  distinto de cero no cuenta), aprobación humana registrada como `approved` con quién y
  cuándo, y ningún paso resuelto a una ruta que la compuerta de costo rechace. Su código de
  salida dice si se cumplió todo. Abre el archivo con `mode=ro`, no importa `core.database` y
  nunca selecciona `api_key`.
- **Límite declarado.** La marca `synthetic` no se puede leer en un artefacto: un texto
  escrito por Odysseus **falla el paso** y no se guarda, así que «0 artefactos synthetic»
  equivale a «run `completed`»; el informe lo dice en vez de fingir una cuenta. Los tokens de
  un intento que murió a media ejecución SÍ se suman desde r7 (`model_metrics` con `failed=true`,
  ADR-030) y el informe no los separa de los del intento que respondió: `tokens_in/out` son todo
  lo que gastó el paso.
- **Descartado.** Ampliar `GET /runs/{id}` ahora: es superficie de API para la Fase 2 (4.4);
  aquí basta un guion de solo lectura.
- **Corregido en r7.** El criterio de cierre se podía cumplir por vacío: un paso cuya ruta no
  se resolvía (id que es una URL, fila borrada) quedaba con `paid=[]` y «TODO CUMPLIDO»; sin
  ninguna compuerta la aprobación humana valía `True`, y nunca se miraba quién ni cuándo; la
  evidencia se medía según el `require_tool_evidence` congelado de cada paso. Ahora la ruta se
  juzga por la URL congelada (y un paso completado cuya ruta no se puede resolver falla con
  «NO VERIFICABLE»); la aprobación exige la compuerta en el revisor, una decisión `approved`,
  un autor y una fecha **no posterior al inicio del paso** (comparadas en UTC); la evidencia se
  pide siempre de investigador, constructor y verificador y se avisa aparte de un config que la
  desactive. Los tokens dicen si son reales, estimados o mixtos, y un paso sin `model_metrics`
  dice «sin dato» en vez de 0 / 0.
- **Pruebas.** `tests/test_cmh_run_report.py` (14 en r6, 35 en r7), más una prueba de cada
  evento; mutantes RR01–RR12 (r6) y RR13–RR32 (r7) de `round8`.

---

## ADR-036 · Segunda vuelta de la Fase 1: qué halló la revisión independiente de `revision-fase1-r6` y qué se corrigió (2026-09-30)

- **Contexto.** La revisión independiente de la etiqueta `revision-fase1-r6` (`ea4eee18`) devolvió
  **DEVUELTO**: 0 P1, 19 P2 y 66 P3 (85 filas fusionadas de 98 hallazgos confirmados; 7 refutados;
  el único P1 original, GUI-F01, quedó en P2 al medirlo). Las 5 lentes ejecutaron las cosas: 105
  hallazgos brutos, de 32 a 111 comprobaciones por lente. Ninguna pudo medir OpenRouter, Groq ni LM
  Studio reales: toda la red fue simulada (§ «No medido» abajo).
- **Decisión.** Las correcciones se hicieron por capacidad, cada una en su commit, con sus pruebas y
  sus mutantes, sobre la misma disciplina de ADR-031:

  | Commit | Capacidad | P2 | Mutantes nuevos |
  |---|---|---|---|
  | `bea9b262` | `campaign()` corre línea base, rechaza el árbol vivo y restaura byte a byte | #16, #17 | T04–T11 (`round4`) |
  | `249daeec` | compuerta: `enforced()` cierra por defecto, `describe()` sin credenciales, https obligatorio | — (P3 #30, #31, #33) | CG11b, CG17–CG30 (`round5`) |
  | `352ebde8` | descubrimiento: amplía solo ante 404, exige clave y https, tiempo total acotado | #3, #4, #18 | D13–D33 (`round4`) |
  | `a0048662` | un intento que muere a medias se cobra por lo gastado | #2, #19 | Q09–Q15 (`round4`) |
  | `00f6dc52` | informe del run: la lista vacía ya no significa «verificado» | #5, #8, #9 | RR13–RR32 (`round8`) |
  | `10ad364f` | guiones locales: `cmh-bench`, respuesta final real, códigos de salida de `lms` | #1, #10–#15 | `round6`: 18 B (B13–B31 sin B18, B29, B30; con B14b y B14c) y 10 S (S06–S16 sin S14) |
  | `c1f34f40` | credenciales fuera del run congelado y del PATCH, rutas locales fuera del proxy, siembra | #6, #7 | F01–F04, P01–P05, X01–X03, Z01–Z08 (`round9`) |
  | `82176e19` | la prueba de la réplica de simulación mira solo la suya | — | — |
  | (este) | ADR corregidas (21 cambios) y esta ADR | — (P3 #46–#58) | — |

- **Medido.** Sobre un export limpio (sin `.git`) de `c1f34f40`, `tests/test_cmh_*.py`: **629 aprobadas,
  0 fallidas**, 1 advertencia, 26 min 59 s. Campañas de mutantes, cada una sobre su propio export y
  precedida de una línea base verde que `campaign()` exige: `round3` 13/13, `round4` 64/64, `round5` 39/39, `round6` 45/45, `round7` 13/13, `round8` 32/32 y `round9` 20/20 sobre `c1f34f40`; `round2` no dio veredicto allí (línea base roja por una prueba que miraba el `%TEMP%` compartido; corregida en `82176e19`) y sobre `82176e19` dio 13/13, con `round3`, `round7` y `round9` repetidas: 13/13, 13/13 y 20/20. En total 239 mutantes, 0 sobrevivientes, 0 inválidos y 0 obsoletos, con el árbol restaurado en verde en las ocho. La suite completa no se repitió
  sobre `82176e19`: ese commit solo cambia una prueba del módulo de siembra, que pasó (2 de 2 en su
  selección) y que ejecutaron tres de las cuatro campañas repetidas (`round2`, `round3`, `round9`);
  `round7` ejecuta solo 9 pruebas designadas y ninguna es esa. `bench.ps1`, `start.ps1` y el informe se
  midieron contra un `lms` y un servidor falsos, y contra el formato real de `lms ps` en solo lectura;
  nada contra Groq, OpenRouter ni LM Studio reales. Una prueba que solo pasa si nada más corre a la vez
  (`test_a_dry_run_leaves_no_replica_behind`, que miraba el `%TEMP%` global) la halló la propia línea
  base de `round2`, que se negó a dar veredicto: el bucle nuevo hizo lo que debía.
- **Límites declarados que r7 no cierra** (los tres primeros son supuestos que ningún control puede validar):
  1. **100.64.0.0/10 (CGNAT, Tailscale) fuera de `local-only`** es un SUPUESTO nacido en ADR-032, sin
     fuente; el código citaba ADR-026, que no lo dice. Una GPU detrás de Tailscale no cuenta como local.
  2. **Si las cuentas de Groq y OpenRouter tienen tarjeta** no lo ve la compuerta (ADR-019). Pendiente 412.
  3. **Los nombres `*.local`** se aceptan sin resolverse.
  4. **La tarea gemela** se juzga al crearla o vincularla; si alguien la reactiva por su cuenta, el
     planificador genérico no vuelve a llamar a la compuerta (un paso de flujo sí, en `call_model`). La
     revisión lo refutó como defecto (SEC-08) pero es un límite que conviene tener escrito.
  5. **413 por tokens por minuto** (P3 #28, riesgo no verificado): los pasos tardíos arrastran artefactos
     de hasta 40 000 caracteres y un 4xx fuera de `FALLBACK_STATUS` detiene el paso sin probar el
     siguiente. Se verifica contra Groq real en la primera ejecución.
  6. **Sobrestimación de cuota** en un intento rechazado antes de enviar, y un fallo al escribir la
     cuota va al log, no a un evento (P3 #26, #27).
  7. `$request.Proxy = $null` de `bench.ps1` sin medir (.NET ya evita el proxy en loopback).
- **No medido** (la revisión lo declaró y sigue igual hasta que el usuario haga U1–U4): que `/models/user` de
  OpenRouter exista y traiga `supported_parameters` y `context_length`; que `/models` responda sin clave;
  si un modelo excluido por privacidad responde 404; si un 429 rechazado cuenta contra el límite de Groq; el
  formato real de `lms ls` / `lms load --estimate-only` y si LM Studio acepta el identificador `cmh-local`;
  cómo transmite las llamadas a herramientas (por fragmentos o completas: de eso depende el tok/s); la
  velocidad real. `bench.ps1` y `start.ps1` solo se ejecutaron contra un `lms` falso; el formato de tabla
  de `lms ps` sí se comparó con el real, en solo lectura.
- **Textos del blueprint v4.0 que r7 reemplaza** (el archivo está fuera del repositorio y no se editó): §7.3
  (`model_metrics` se emite por intento, no «cada ronda», y `provider_discovery` es un evento más; ADR-030),
  §9.1 (`/models/user` primero; ADR-028) y §21-U4 (incluye cargar el modelo con `start.ps1` y ver `cmh-local`
  en `lms ps`; ADR-029).
- **Redacción de tres commits.** Los mensajes de `6be2cbff`, `d42638b2` y `76b88c40` dicen «each aimed at its
  own test»: lo exacto es que cada mutante designa **una prueba por id de nodo** y esa es la que debe caer;
  que otras también caigan es normal y no se mide. No se reescriben commits ya hechos.
- **Método (lecciones nuevas).**
  1. Un bucle del que todo depende necesita su propia prueba sobre un repositorio de juguete: `campaign()`
     tenía tres formas de mentir y ningún test que las viera.
  2. Una lista vacía debe significar una sola cosa. El informe usaba `[]` para «verificado» y para «no
     verificable».
  3. Una prueba que lee la base en memoria compartida depende de quién corrió antes:
     `test_workflow_step_declares_itself_foreground_controlled` falló detrás de una prueba que llama a
     `engine.dispose()` (que deja 0 tablas en esa base: `no such table: model_endpoints`), medido con una
     sonda que hace exactamente eso. La segunda revisión no la vio fallar detrás de `test_cmh_seed_scripts.py`
     en las tres secuencias que probó sobre r6, y el orden exacto que la rompe no se registró: es un riesgo
     por construcción. Tiene su propia base.
  4. Un mutante que cambia un patrón que una corrección movió se declara obsoleto en segundos por la prueba
     de validez, no tras una campaña de una hora: se repuntaron D06–D08 y T01 de `round4`, B04 y S03 de
     `round6` (no el S03 de `round4`: los ids se repiten entre rondas, S01–S03 existen en las dos), SD08 y
     SD09 de `round7`, RR05–RR07 y RR09 de `round8` y CG11 de `round5`.
- **Pruebas.** Ver la tabla: `tests/test_cmh_mutant_campaign.py`, `test_cmh_endpoint_patch.py` y
  `test_cmh_llm_core_proxy.py` son nuevos; los demás módulos crecen.

---

## ADR-037 · Tercera vuelta de la Fase 1: qué halló la segunda revisión independiente y qué se corrigió (2026-09-30)

- **Contexto.** La segunda revisión independiente, sobre la etiqueta `revision-fase1-r7` (`662e141e`), devolvió
  **DEVUELTO**: 0 P1, 3 P2 confirmados por refutador y 49 P3. Las cinco lentes entregaron 59 hallazgos brutos
  (7 P2 y 52 P3); de los 7 P2, 4 quedaron confirmados como P2 (dos de ellos, REG-01 y SRV-R7-01, eran el mismo
  defecto visto por dos lentes: 3 distintos), 2 se refutaron (HON7-01, HON7-03) y 1 bajó a P3 (HON7-02). De los 19 P2 de `revision-fase1-r6`, **18 reprodujeron como corregidos** con escenario propio de la
  lente y 1 seguía abierto: el nº6, por una corrección mía. **0 pruebas pasaban en r6 y fallaban en r7**, y las 629 de
  `test_cmh_*` se reproducían. Ninguna lente pudo medir Groq, OpenRouter ni LM Studio reales.
- **El defecto que bloqueaba.** Mi corrección del P2 nº6 trasladaba la credencial de la URL a `api_key` como
  `Basic <base64>`, y `build_headers` la enviaba como `Bearer Basic <base64>`: dos lentes midieron por separado
  un 401 donde r6 autenticaba. Las pruebas de r7 solo miraban la forma guardada. Lo corrige
  `src/endpoint_resolver.py` (un valor que ya empieza por `Basic ` sale tal cual) y lo fijan dos pruebas que
  registran el endpoint por POST y por PATCH **por las rutas reales** (ASGI, base en memoria) y capturan la cabecera.
  Eso cubre también el segundo P2: ninguna prueba ejecutaba la línea de la ruta PATCH.
- **Decisión.** Las correcciones de código y pruebas van por capacidad; los mutantes de todas van juntos en un
  último commit, y por eso cuatro de los cinco commits intermedios no pasan `test_cmh_mutant_validity`. Medido
  en un export limpio de cada uno: `eef71964` falla 4 de 13 casos; `43166b55`, `819579a1` y `7d0e466e`, 5 de 13
  (los patrones de mutantes que sus cambios dejaron obsoletos); `662e141e` (la base), `9a2a94b4` y `b68ab6a9`
  pasan 13 de 13. El mensaje de `b68ab6a9` dice que cada commit intermedio lo declara: solo lo dice el de
  `9a2a94b4`, que es justo uno de los que la pasan. Queda corregido aquí, sin reescribir commits ya citados;
  quien haga un `git bisect` dentro de r8 debe saltar esos cuatro:

  | Commit | Capacidad | Hallazgos de la segunda revisión | Mutantes |
  |---|---|---|---|
  | `9a2a94b4` | `build_headers` envía un `Basic …` tal cual; POST y PATCH probados por las rutas reales | P2 nº1 y nº2 | `round9` P06–P09 |
  | `eef71964` | una fila con credenciales se rechaza; `provider_dropped`; la siembra exige clave | P3 n4, n5, n15, n19, n20, n23, n36, n39 | `round9` F05–F08 y Z09–Z14; `round4` D34 |
  | `43166b55` | guiones locales: modelo por contención, identificador del router, descargas que se verifican | P3 n8–n11, n16–n18, n21, n22 | `round6` B32–B39 y S17–S19 |
  | `819579a1` | informe: la aprobación no precede a la ejecución; un id de endpoint que es URL se acorta | P3 n12, n14, n37, n38 | `round8` RR33–RR37 |
  | `7d0e466e` | evento `quota_write_failed`; el intento muerto se dibuja como error en `/cmh/os` | P3 n6, n7 y nº27 de r6 | `round4` Q16; la interfaz (JS) no tiene mutantes, solo prueba unitaria |
  | `b68ab6a9` | mutantes de todo lo anterior, herramienta de campañas y guarda del método privado de `httpx` | P3 n30, n32, n39, n40, n41 | `round4` T12–T21 (sobre la propia herramienta) |
  | `efe02b56` | pruebas del PATCH de `supports_tools` que U1 le pide enviar al usuario (un PATCH sin cuerpo válido deshabilita el endpoint) | el punto en curso, no un hallazgo | sin mutantes: fijan una ruta de Odysseus, no código nuestro |
  | `a0cb586a` | la prueba del resumen de una campaña usa cuatro conteos distintos (1, 2, 3, 4) | T15 de `round4` **sobrevivió** en la campaña de r8 | `round4` T15 (vuelto a correr solo: cae) |
  | `754cf669` | Z11 de `round9` sustituido por un mutante que deshace las dos puntas de la cadena `if/elif` | Z11 **sobrevivió** en la campaña de r8: era equivalente | `round9` Z11 (vuelto a correr solo: cae) |
  | este commit | ADR-037, diez correcciones in situ de ADR-026, 029, 032, 033, 035 y 036, y el punto en curso | P3 de documentación | sin mutantes |

- **Decisiones de diseño que r8 toma** (las que el veredicto dejaba abiertas):
  1. **Una fila registrada cuya URL lleve credenciales se rechaza, no se recorta** (P3 n4). r7 la congelaba sin
     ellas y el ejecutor, que halla la fila por URL, ya no la encontraba: el paso salía sin `Authorization`. Ahora
     `create_run` responde 400 pidiendo re-registrarla (igual que hace con la URL de la tarea), y el descubrimiento
     no consulta una URL que la lleve. `strip_userinfo` desaparece: `has_userinfo` lo sustituye.
  2. **Un proveedor que la compuerta deja fuera deja un evento** (P3 n5): `provider_dropped` con `endpoint_id`,
     `host` y motivo (`cost_gate`), en vez de desaparecer de la lista.
  3. **La siembra exige clave para el candidato de nube** (P3 n15), no el router: exigirla en `resolve_candidates`
     habría roto el flujo de todo entorno de pruebas sin tocar lo que el usuario hará. Un Groq sin clave deja un
     aviso y `--apply` se niega.
  4. **`start.ps1` compara el modelo por contención, no por igualdad** (P3 n8): `lms` acepta `gemma-4-e4b` y
     `lms ps` imprime `google/gemma-4-e4b`. No se usó `lms ps --json`: con nada cargado devuelve `[]` y no se
     pudo ver su forma.
  5. **Un fallo al escribir la cuota deja un evento `quota_write_failed`** (P3 n27 de r6), con el tipo del error y
     nunca su texto; si falla el evento, queda el log.
  6. **El intento muerto se dibuja como error** en `/cmh/os` (P3 n6), con sus tokens contados.
- **Medido.** Sobre un export limpio (sin `.git`) de `64756140`, cuyo árbol (`a9928523`) es el de `b68ab6a9`: solo se
  enmendó el mensaje del commit. `tests/test_cmh_*.py` más `test_model_routes`, `test_chatgpt_subscription_routes`,
  `test_endpoint_selection_by_url` y las de cabeceras y resolución de endpoints = **949 aprobadas, 1 fallida**,
  13 min 48 s. La fallida es `test_rewrites_loopback_when_in_docker`, preexistente: falla también en r6 y falla
  siempre que algo escuche en el puerto 1234 (LM Studio escucha ahora mismo), porque la prueba no sustituye
  `_container_loopback_reachable`. Las ocho campañas sobre ese mismo export: `round2` 13/13, `round3` 13/13,
  `round4` 75/76, `round5` 39/39, `round6` 56/56, `round7` 13/13, `round8` 37/37 y `round9` 31/32 =
  **277 capturados, 2 sobrevivientes, 0 inválidos, 0 obsoletos, de 279** (239 en r7; 42 añadidos, 2 quitados). Los
  dos sobrevivientes están entre los 42 nuevos y se corrigieron sin tocar código de producción: **T15** de
  `round4` (la prueba del resumen usaba un mutante de cada clase; `a0cb586a`) y **Z11** de `round9` (equivalente:
  la rama que mutaba solo se alcanza con `--apply` ya falso; `754cf669`). El árbol se restauró en verde tras
  cada campaña (318, 318, 173, 267, 50, 9, 39 y 272 pruebas de las que designan los mutantes), también en las dos
  que salieron con código 1 por su sobreviviente.
  Sobre un export limpio de la punta final `754cf669`: la misma suite = **953 aprobadas, 1 fallida** (la misma),
  8 min 55 s (las 4 de diferencia son las del PATCH de U1); los 21 mutantes `T` de `round4`, que son los que usan
  la prueba corregida = **21 de 21**, 0 sobrevivientes, árbol restaurado con 59 pruebas; T15 y Z11, cada uno
  vuelto a correr solo, caen (árboles restaurados con 30 y 51 pruebas). Entre `b68ab6a9` y `754cf669` cambian
  tres archivos, `round9.py`, `test_cmh_endpoint_patch.py` y `test_cmh_mutant_campaign.py`, y ningún código de
  producción (`git diff --stat`). **No se repitieron sobre la punta** las otras siete campañas completas, ni los 55
  mutantes de `round4` que no son `T`, ni los otros 31 de `round9`: el código y las pruebas que designan son los
  mismos, y se infiere (no se midió) que siguen cayendo.
- **Lo que r8 no cierra.** P3 de r6 #28 (riesgo de 413 por tokens por minuto, no verificado), #29 (`local.model`
  vale para todas las filas locales) y #32 (el ejecutor elige la fila por subcadena: es código de Odysseus). De esta
  vuelta: n30 (los ids de mutante se repiten entre rondas: se cita siempre ronda e id, no se renumera), la mitad
  de n32 (tres pruebas de `round6` no las nombra ningún mutante; se declaran sin medir) y n40 (matar una campaña
  desde fuera deja el mutante puesto; en Windows no hay manejador que lo evite, y ahora se anuncia qué archivo está
  mutado antes de mutarlo). `$request.Proxy = $null` sigue sin medir.
- **No medido** (sin cambio): `/models/user` de OpenRouter, `/models` sin clave, un 429 contra el límite de Groq, el
  formato real de `lms ls` y `lms load --estimate-only`, cómo LM Studio entrega las llamadas a herramientas y su
  velocidad real; si Groq con `openai/gpt-oss-120b` recibe herramientas nativas sin `supports_tools` (un refutador
  midió que el bucle cae a llamadas en bloques de texto, que el analizador acepta y la guardia de evidencia cuenta;
  es una ruta distinta de la nativa y su calidad no se midió); `requirements` no fija la versión de `httpx` de la
  que depende `_LocalDirectClient` (método privado `_transport_for_url`, ahora con una prueba que falla si se
  renombra); y el PATCH de `supports_tools` que pide U1, medido solo en memoria por la ruta real (4 pruebas,
  `efe02b56`), no contra una sesión de administrador viva.
- **Lecciones de método que midió la propia campaña de r8** (las dos salieron de mutantes que yo escribí):
  (a) Una prueba de resumen con un caso de cada clase no distingue dos etiquetas intercambiadas: T15
  sobrevivió hasta que la prueba usó 1, 2, 3 y 4. (b) Un mutante sobre una condición inalcanzable es
  equivalente y no mide nada: Z11 cambiaba un `elif not args.apply` al que, por el orden de la cadena,
  solo se llega con `args.apply` ya falso. Se sustituyó por uno que deshace las dos puntas de la cadena
  (19 líneas, cortadas del archivo real) y ahora cae. Antes de escribir un mutante se comprueba que su
  línea es alcanzable. La primera vuelta de los 42 mutantes nuevos dio 2 sobrevivientes (4,8 %); los 237
  anteriores, que ya habían pasado por una campaña, dieron 0.
- **Lección.** La credencial que una función devuelve «lista para usarse» hay que usarla en la capa que la envía:
  se comprobó `api_key.startswith("Basic ")` donde se guarda y nadie miró la cabecera que salía. Dos veces en este
  proyecto una corrección se dio por buena porque se midió la capa de al lado (`build_request` en ADR-026, la forma
  guardada aquí).
