# Estado de implementación — Interfaz Agentic OS CMH

Corte: 2026-09-25 (Lima). Rama `dev`. Commit de la interfaz: `bba01a65`
(autorizado por el usuario el 2026-09-25) sobre `6db87031`.

## 1. Tareas

| ID | Tarea | Estado |
|---|---|---|
| T01 | Investigación y planificación (9 documentos) | COMPLETED |
| T02 | Herramientas de verificación sin instalar nada | COMPLETED |
| T03 | Tokens y CSS base (marca CMH, claro/oscuro) | COMPLETED |
| T04 | Núcleo JS (dom, router, i18n, validate, format, storage, prefs, audit, log) | COMPLETED |
| T05 | Servicios: `DataSource` real y demo, simulador, reductor, run-feed, chat | COMPLETED |
| T06 | Componentes | COMPLETED |
| T07 | Marco, router y rutas FastAPI (`/cmh/os`, `/api/cmh/os/config`) | COMPLETED |
| T08–T20 | 12 vistas + chat del coordinador | COMPLETED |
| T21 | End-to-end, accesibilidad, responsive | COMPLETED |
| T22 | Revisión independiente y cierre | COMPLETED (veredicto «With fixes»; 5 importantes corregidos, ver §4) |

## 2. Resultados verificados (última ejecución, 2026-09-25)

| Comando | Resultado |
|---|---|
| `bash scripts/cmh_os/check.sh --screens` | todas las etapas aprobadas |
| · tipos (`typecheck.mjs`) | TypeScript 6.0.3, 49 archivos, **0 errores** |
| · lint (`lint.mjs`) | 54 archivos, 11 reglas, **0 hallazgos** |
| · build (`build.mjs`) | 49 módulos, 56 archivos cargados, 444 868 B sin comprimir, **140 709 B gzip** (presupuesto 150 000) |
| · unitarias (`node --test`) | **55 de 55** |
| · end-to-end (Edge sin ventana) | **31 de 31** comprobaciones |
| pytest CMH + tareas (conjunto de la línea base + `test_cmh_os_routes.py`) | **95 aprobadas** (83 previas + 12 nuevas) |
| `pytest tests/test_task_workspace.py` (aparte, por contaminación conocida) | 13 de 13 |
| `git diff --check` | sin errores |
| Suite completa de pytest, árbol actual vs. HEAD limpio exportado con `git archive` | 76 vs. 71 fallos; las **5 diferencias son `test_token_cache_atomic_swap`**, que fallan solo en esta instalación porque existe `data/auth.json` (documentado antes). **0 regresiones** |

Las comprobaciones de verificación se probaron a sí mismas:

- el typecheck detectó 3 de 3 errores inyectados;
- el lint detectó 5 de 5 infracciones inyectadas;
- con los dos defectos principales reintroducidos, el end-to-end falló 3 comprobaciones: respuesta final en vivo, fugas de streams y foco.

Capturas: `data/cmh-os-screens/` (15 rutas × 390/820/1440 px y 7 vistas finales; carpeta ignorada por git).

## 3. Errores encontrados durante la construcción y cómo se resolvieron

| Encontrado por | Error | Solución |
|---|---|---|
| build | `core/store.js` no lo usaba nadie; el presupuesto medía `types.js`, que el navegador nunca descarga | Módulo eliminado; presupuesto sobre lo cargado y comprimido (ADR-008) |
| unitaria | El chat no reconocía preguntas que empiezan con «¿» ni quitaba «el flujo …» | Normalización de puntuación inicial y bucle de palabras de relleno |
| unitaria | Nodos superpuestos en flujos de 5 capas tras agrandar el grafo | Ancho del lienzo según número de capas |
| e2e | Página 404 sin `h1`; desbordamiento horizontal a 820 px por hijos de rejilla sin `min-width: 0` | `h1` en la 404; `minmax(0, 1fr)` en vistas, pilas y paneles |
| e2e | Límite de iteraciones por defecto (12) cortaba el flujo de 7 pasos | 40 por ejecución (ADR-013) |
| e2e | La interfaz no reaccionaba al cambiar el movimiento reducido del sistema | Escucha de `prefers-reduced-motion` |
| captura | «Coordinador» se salía del círculo; texto del grafo pequeño; «1 servicios» | Etiqueta junto al anillo, tipografía mayor, singular |
| pytest | Los eventos SSE no traían hora: trazas sin tiempos reales | `at` en cada evento (ADR-014, backend) |
| contraste | Verde «En meta» 4,41:1 y gris «No iniciado» 4,28:1 bajo AA | Variantes AA solo para texto (ADR-015) |

## 4. Revisión independiente (subagente sin el razonamiento del constructor)

Veredicto: **With fixes**. 0 críticos, 5 importantes, 14 menores. El revisor
reprodujo cada importante con sondas propias.

| # | Hallazgo | Estado |
|---|---|---|
| 1 | Modo real: la respuesta final quedaba en el artefacto equivocado, porque el `step_completed` real no trae contenido | Corregido: `run-feed.js` recarga el artefacto. Prueba e2e con la API falsa realista y unitaria |
| 2 | Fugas de EventSource al salir de una vista antes de que termine de cargar | Corregido: `asyncView.dispose()`, verificación después de cada `await` y `destroy` en todas las vistas. Prueba e2e que cuenta los streams abiertos en el servidor |
| 3 | Trazas reales cortadas en el primer evento terminal | Corregido: la reproducción termina por inactividad. Prueba unitaria error → reanudar → completar |
| 4 | Demo: tras rechazar un paso y reintentar, no se podía aprobar | Corregido: el reintento borra los rechazos del intento anterior. Prueba unitaria |
| 5 | Demo: el grafo no se movía al aprobar la ejecución sembrada | Corregido: los eventos en vivo llevan la hora real. Prueba unitaria |
| 6 | Foco perdido en rutas de detalle; 0 `h1` mientras carga | Corregido: encabezado mutable y foco al `h1` en cada navegación. Prueba e2e |
| 7 | URL de proveedores y errores MCP sin redactar | Corregido: `redactUrl` / `redactText`. Prueba unitaria |
| 8 | Animaciones continuas sin eventos | Corregido: trazos estáticos; órbitas solo con el paso en curso |
| 9 | Sondeo pesado, incluso con la pestaña oculta | Corregido: pausa con la pestaña oculta; listas compartidas por refresco |
| 10 | Ceros no medidos mostrados como reales | Corregido: `usage.measured` y `trace.measured`, que se muestran como «—» |
| 11 | Propuestas restauradas rotuladas como aprobadas; decisiones de paso fuera del historial | Corregido |
| 12 | Botones activos durante la petición | Corregido |
| 13 | Diálogos abiertos al cambiar de ruta | Corregido: se cierran al navegar |
| 14 | `CMH_OS_UI_ENABLED` cosmético | Parcial: la interfaz lo respeta. `/static` sigue exento de autenticación en Odysseus (ADR-016, pendiente) |
| 15 | Mensajes del backend en inglés; «para» como detener; `aria-label` en `span` | Corregido: `i18n/server-es.js`, verbos explícitos, texto accesible real |
| 16 | Pruebas que no podían fallar | Corregido: API falsa con estado y aprobación realista; doble decisión prohibida; conteo absoluto; nombres accesibles sin `textContent` para campos |
| 17–19 | Documentos desactualizados o ausentes | Corregido (TEST_PLAN, este archivo, README) |

## 5. Deuda técnica

- ~~No verificado contra un Odysseus real con sesión de administrador~~ **Cerrado el 2026-09-25**: `bash scripts/cmh_os/realmode/run.sh` levanta un Odysseus desechable, crea una cuenta de un solo uso y conduce Edge contra los manejadores reales. 12 de 12 comprobaciones, con el estado de la base impreso como prueba. Queda por hacer, y es distinto, que el usuario mire la página con **sus** datos: lo que el guion verifica es el comportamiento, no tu contenido.
- ~~`/static/cmh-os/*` es público~~ **Cerrado el 2026-09-25** (ADR-016): la carpeta de la página sale de la exención de `/static` y devuelve 404 con la bandera apagada. El resto de `/static` no cambia.
- El presupuesto de build está al 94 % (140,7 de 150 KB gzip). La próxima vista grande obliga a dividir `es.js` por módulo o a cargar vistas bajo demanda.
- Demo: en las ejecuciones creadas en vivo, las duraciones de herramientas (tiempo simulado) pueden superar la del paso (tiempo real) en la cascada.
- Límites de iteraciones, tiempo y presupuesto, y prioridad: solo se aplican en demo. El backend usa `max_steps=12` por paso y no guarda la prioridad.
- ~~El rechazo de paso en modo real detiene la ejecución~~ **Cerrado el 2026-09-25** (ADR-017): `POST /runs/{id}/steps/{key}/reject` exige justificación, deja la ejecución en `rejected` de forma terminal y guarda la decisión en `cmh_workflow_steps.decision`.
- Evaluaciones, roles y sesiones: sin backend; se sirven desde la demo con la etiqueta «Demo · sin backend».
- ESLint no está disponible sin npm; lo sustituyen `lint.mjs` y TypeScript estricto.

## 6. Siguiente bloque

1. Comportamiento verificado automáticamente con `scripts/cmh_os/realmode/run.sh` (12 de 12). Lo que queda es una revisión de contenido: el usuario abre `/cmh/os` con su propia sesión y mira sus proyectos, agentes y ejecuciones reales.
2. Hecho: commit `bba01a65`.
3. Hecho el 2026-09-25: rechazo de paso con justificación persistida (ADR-017) y `static/cmh-os` fuera de la exención de autenticación (ADR-016).
4. Pendiente de backend: límites de iteraciones, tiempo y presupuesto por ejecución, y prioridad —hoy solo se aplican en demo; el backend usa `max_steps=12` por paso y no guarda la prioridad.

## 7. Punto 8 — cierre de pendientes de backend (2026-09-25)

| Capacidad | Estado | Evidencia |
|---|---|---|
| `/static/cmh-os/*` fuera de la exención de `/static` y apagado por la bandera (ADR-016) | COMPLETED | `test_cmh_os_routes.py` colecta 26, de las cuales 15 son nuevas |
| Selección determinista de endpoint cuando varias filas comparten URL base | COMPLETED | `test_endpoint_selection_by_url.py`, 13 de 13 |
| `disable_mcp` efectivo al ejecutar, sin contradecir la allowlist (ADR-018) | COMPLETED | `test_cmh_restricted_tool_surface.py`, 15 de 15 |
| Rechazo nativo de paso con justificación persistida (ADR-017) | COMPLETED | `test_cmh_workflow_routes.py` 13, `test_cmh_workflows.py` 11 |
| Migración de la columna `decision` sobre una base con el esquema anterior | COMPLETED | `test_cmh_workflow_step_decision_migration.py`, 2 de 2 |

### Conteos reproducibles

Los conjuntos se nombran archivo a archivo para que cualquiera repita la cifra.

| Conjunto | Comando | Resultado |
|---|---|---|
| Los 6 módulos del cambio | `pytest tests/test_cmh_os_routes.py tests/test_cmh_restricted_tool_surface.py tests/test_endpoint_selection_by_url.py tests/test_cmh_workflow_routes.py tests/test_cmh_workflows.py tests/test_cmh_workflow_step_decision_migration.py` | **80 de 80** (80 colectadas) |
| CMH + tareas + política (21 módulos: los 6 anteriores más `test_cmh_control_routes`, `test_cmh_memory_routes`, `test_cmh_restricted_loop`, `test_task_chain_owner_scope`, `test_task_cookbook_admin_gate`, `test_task_endpoint_normalization`, `test_task_routes_shim`, `test_task_scheduler_cache`, `test_task_scheduler_cancel`, `test_task_scheduler_session_delivery`, `test_task_session_folder`, `test_task_shell_tools`, `test_scheduler_prompt_cache_time`, `test_chat_preprocess_tool_policy`, `test_chat_route_tool_policy`) | **172 de 172** |
| `test_task_workspace.py` aparte (contaminación conocida entre módulos) | `pytest tests/test_task_workspace.py` | **13 de 13** |
| Interfaz | `bash scripts/cmh_os/check.sh` | tipos 49 archivos / 0 errores · lint 54 / 0 · build **140 851 B** gzip de 150 000 · unitarias **59 de 59** · e2e **32 de 32** |

### Suite completa contra HEAD limpio

Medida antes de las correcciones de la revisión; se repite al cerrar el punto.

| Árbol | Resultado |
|---|---|
| Trabajo | 5 628 aprobadas, 77 fallidas, 2 errores, 337 omitidas |
| HEAD `7e21b7c4` exportado con `git archive` | 5 585 aprobadas, 75 fallidas, 2 errores, 344 omitidas |

Diferencia de conjuntos, comparada id por id: **0 regresiones**. Las 5 que solo
fallan en el árbol de trabajo son `test_token_cache_atomic_swap`, que dependen
del `data/auth.json` real que `git archive` no exporta. Las 3 que solo fallan
en la copia son `test_atomic_io` (intermitente: aislada falla en ambos) y
`test_chat_helpers` + `test_workspace_confine`, que comparan rutas absolutas y
fallan porque la copia vive en otra carpeta.

### Revisión independiente (subagente, sin el razonamiento del constructor)

Veredicto inicial **DEVUELTO**: 0 críticos vivos, 5 importantes, 8 menores, con
26 mutaciones propias de las que 6 sobrevivieron. Estado tras las correcciones:

| # | Hallazgo | Estado |
|---|---|---|
| 0 | Crítico: grafías sin normalizar servían la página sin sesión | Cerrado durante la propia revisión; re-medido con 18 grafías |
| 1 | `disable_mcp` vetaba las 15 herramientas de correo que la allowlist sí permite | Corregido: `allowed_mcp_names` (ADR-018). 4 pruebas nuevas |
| 2 | El ranking anteponía «lista el modelo» a «tiene clave»: una fila sin credencial ganaba | Corregido: el orden es coincidencia exacta → modelo no oculto → clave → modelo listado → id. 4 pruebas nuevas |
| 3 | ADR-018 citaba 3 servidores builtin | Corregido a 5, con el límite de lo no medido declarado |
| 4 | Documentación por detrás del código y conteos no reproducibles | Corregido: ADR-016 y este archivo, con los conjuntos nombrados |
| 5 | La migración SQLite no la cubría ninguna prueba (mutación M16 sobrevivía) | Corregido: `test_cmh_workflow_step_decision_migration.py`; M16 ahora se captura |
| 6, 8 | `stop()` en el rechazo y el colapso de barras son código inalcanzable | Se conservan como defensa; comentarios corregidos para no afirmar un escenario imposible |
| 7 | Pasos hermanos quedan `pending` bajo una ejecución rechazada | Documentado en ADR-017 |
| 9 | La rama MCP de `reason_for` no se probaba ni se usaba | Corregido: la compuerta usa `reason_for`, y el mensaje ya no dice «guide-only» para toda política |
| 10 | El estado `rejected` de la interfaz no lo verificaba nada | Corregido: 3 unitarias nuevas |
| 11 | No se podía filtrar por «Rechazada» | Corregido en ejecuciones, observabilidad y leyenda del grafo |
| 12 | Una justificación de más de 2 000 caracteres da 422, no 400 | Documentado en ADR-017 |
| 13 | `logger.info` por resolución ambigua de endpoint | Se conserva: solo se emite cuando hay más de un candidato, que es justo el caso a diagnosticar. Solo ids |

Mutaciones tras las correcciones: las 6 que sobrevivían se volvieron a correr y
**4 se capturan ahora** (M16 migración, M21/M21b enum `rejected`, M22
`TERMINAL_RUN_EVENTS`, M23 rama MCP de `reason_for`). Las 2 restantes —M17
`stop()` y M04b colapso de barras— sobreviven **por diseño**: son defensa sobre
caminos hoy inalcanzables, y así queda escrito en el código.

**Advertencia de proceso registrada por el revisor:** el árbol se modificó
mientras revisaba, porque el defecto crítico se cerró en paralelo. Una revisión
sobre un árbol en movimiento no es una revisión. La siguiente debe hacerse
sobre un commit congelado.
