# Estado operativo: Agentic OS CMH

Fecha de corte: 2026-09-24 (hora de Lima). Este archivo es el punto de reanudación para Claude y Codex. Actualizarlo al cerrar cada punto limpio con evidencia, no con intenciones.

## Objetivo acordado

Ampliar Odysseus como interfaz local única para ver y gestionar proyectos, agentes, modelos, flujos, ejecuciones y memorias CMH. Los archivos CMH siguen siendo la fuente de verdad. Los agentes intercambian artefactos persistentes y evidencia; el revisor no hereda el razonamiento del constructor. Los proyectos del índice aparecen primero en lectura.

## Punto limpio 0: línea base

- Commit de partida: `813eac5a` (`Add scheduled task workspace isolation`); árbol de trabajo limpio al comenzar este turno.
- Odysseus está instalado localmente con SQLite y autenticación. La última prueba documentada de chat con Anthropic respondió correctamente; no equivale a una prueba de flujo.
- Último estado documentado de `CMH Researcher - Workspace validation`: pausado. Su ejecución con entrada sintética, ID y prueba de aislamiento no están registrados.
- El workspace de tareas LLM está persistido y validado. La limitación actual cubre las herramientas nativas de archivos; shell, Python, MCP y herramientas externas requieren prohibición efectiva propia.
- Validación anterior: 134 pruebas aprobadas, 10 omitidas, más dos pruebas de migración. No repetir ese conteo como validación de funciones nuevas.
- Fuentes de estado: `integrations/cmh/README.md`, `_agent-control-plane/CMH_ODYSSEUS_NEXT.md`, `CMH_Claude/CLAUDE.md` y `_control/INDICE.md` desde la raíz Claude.

## Reglas de continuación

Al cerrar cada punto: anotar commit o estado Git, capacidad implementada, pruebas ejecutadas y resultado, IDs de ejecuciones y modelos cuando existan, incidentes, decisiones, y una siguiente acción concreta. No almacenar claves, prompts sensibles ni datos financieros en este registro. No marcar como comprobado un proveedor, ejecución o aislamiento que no se haya observado.

## Punto en curso

Punto 1 del plan: verificar y cerrar el piloto con entrada sintética y permisos de herramientas. Después crear el catálogo de proyectos y agentes. El plan completo fue aprobado por el usuario en la conversación del 2026-09-24.

Comprobación inicial de SQLite (2026-09-24): la tarea `07d5899e-9d59-4bad-a7aa-2a69abb68659` existe, está `paused`, es LLM, declara `claude-sonnet-4-5-20250929` y no tiene `crew_member_id`. Al comenzar, `data/app.db` no tenía la columna `workspace`. La importación del módulo de base de datos durante las pruebas aplicó la migración a la base activa antes de reiniciar el servidor: ahora tiene `workspace` y `allowed_tools`, y `integrity_check=ok`. La tarea sigue pausada con ambos campos NULL. No se leyó el prompt ni ningún secreto.

Progreso sin cierre del punto 1: se agregó `allowed_tools` por tarea LLM, validado al guardar y ejecutar. Una lista definida bloquea todas las herramientas nativas fuera de la lista y MCP; el piloto previsto permite solo `read_file`, `ls`, `grep`, `glob`. Una tarea restringida ya no usa el fallback sin trazas si falla el bucle. Copia SQLite anterior creada mediante backup en `data/backups/app-before-agentic-os-20260924.db`, 610304 bytes, `integrity_check=ok`; su migración aislada preservó el piloto pausado. El servidor del puerto 7000 aún ejecuta el código anterior (PID inicialmente 42564). No hay ID de ejecución sintética ni resultado del modelo registrado.

Progreso del punto 2 sin cierre: API `/api/cmh/projects` importa en lectura las siete fichas de `_control/INDICE.md`; `/api/cmh/agents` persiste definiciones con ID estable, instrucciones versionadas, modelo, herramientas y carpeta validados. Vista `/cmh` agregada para búsqueda, ficha, creación, edición, asociación, pausa y activación. Las pruebas de catálogo/registro y workspace suman 14 aprobadas; suite ampliada en curso. No hay aún prueba de interfaz en navegador autenticado ni relación de ejecuciones recientes. No considerar terminado el punto 2.

Punto limpio de verificación parcial (2026-09-24, código sin commit): 25 pruebas enfocadas aprobadas, una advertencia. El servidor local se reinició con `DEBUG=false` porque `DEBUG=release` heredado impedía el arranque; `/cmh` responde dentro de la sesión autenticada. En Edge se observaron las siete fichas, la ficha del Ecosistema y la creación del registro `CMH Researcher` ID `3dc7c323ddc54c77963d43dc374092ac`, estado `paused`, proyecto `ecosistema-de-agentes`, modelo `claude-sonnet-4-5-20250929`, carpeta `data/agent_workspace/cmh-researcher` y herramientas `[glob, grep, ls, read_file]`. La tarea programada original `07d5899e-9d59-4bad-a7aa-2a69abb68659` recibió la misma carpeta y allowlist por actualización condicionada en SQLite; continúa `paused`, sin ejecuciones (`run_count=0` al revisar), con `integrity_check=ok`. Se creó `input/piloto_sintetico.txt` con datos inventados. No hay aún prueba de ejecución del modelo ni de escape en vivo. ChromaDB no estaba disponible al arrancar; la aplicación siguió en modo degradado para memoria vectorial.

Incidencia del piloto: el run `c35872d5-9cce-4a93-ad27-ce2b8acbcc5c` terminó `aborted` con `Stopped by user` al lanzar desde la vista de tareas; el control de actividad del navegador interrumpe tareas de fondo. Una ejecución aislada posterior produjo el run `65650f3b-c691-481b-99ee-d534e4981eff`: Anthropic `claude-sonnet-4-5-20250929` no pudo conectar (`503 Cannot reach https://api.anthropic.com`). El código anterior lo marcó erróneamente `success` con `(no output)` y el resumen intentó fallback; no hubo respuesta verificable, herramienta usada ni nota de investigación. El código se corrigió para que las tareas restringidas fallen ante error de stream o salida vacía, sin resumen por otro modelo. La tarea regresó a `paused` con `next_run=NULL`; `run_count=1` refleja el falso éxito histórico y no debe interpretarse como piloto aprobado. Pruebas de la corrección en curso.

## Punto limpio 2: catálogo y registro (2026-09-24)

- Capacidad: `/cmh` lista y busca los siete proyectos del índice en lectura; muestra ficha, ruta, estado, agentes asociados y ejecuciones recientes vinculadas por ID de tarea. API admin `/api/cmh/projects` y `/api/cmh/agents` permite crear, editar, pausar y activar definiciones; valida rutas, herramientas, propiedad de tarea y versiona instrucciones. La importación no escribe archivos fuente. La ficha `CMH_Claude/00_Proyecto_Ecosistema_Agentes.md` enlaza este registro.
- Validación: 27 pruebas enfocadas aprobadas, una advertencia; `git diff --check` sin errores. Interfaz autenticada verificada en Edge: siete proyectos, ficha del Ecosistema, creación y edición del agente, vínculo con tarea y visualización de sus runs. `node --check` no se pudo ejecutar porque Node no está en PATH; el JavaScript sí se ejecutó en el navegador. Migración `cmh_agents.task_id` aplicada a SQLite activa tras copia `data/backups/app-before-task-link-20260924.db` (`integrity_check=ok`); SQLite activa también `integrity_check=ok`.
- IDs: agente `3dc7c323ddc54c77963d43dc374092ac`; tarea `07d5899e-9d59-4bad-a7aa-2a69abb68659`. El run `65650f3b-c691-481b-99ee-d534e4981eff` fue corregido de `success` a `error` con causa 503, preservando `(no output)` como resultado histórico. El piloto sigue `paused`, `run_count=1`; el punto 1 **no está cerrado**.
- Decisión: el proyecto conserva los archivos CMH como fuente de verdad; el registro de agentes y vínculos se guarda en SQLite. Ningún agente se ejecuta por activarlo en el registro; la tarea programada es independiente. No ampliar acceso a carpetas financieras.
- Commit de implementación: `e41e4a90` (`Add CMH project and agent control view with restricted pilot tools`). Este registro se actualiza después en un commit documental separado.

Nueva comprobación del punto 1 tras los commits: la red TCP externa a `api.anthropic.com:443` respondió. La ejecución sintética aislada con el código corregido produjo el run `f620a2b3-89c1-4faf-85f6-0fb8e4ab6088`, estado `error`: Anthropic devolvió `401 invalid x-api-key` para el endpoint configurado. No se produjo respuesta ni llamada a herramienta. Se devolvió la tarea a `paused` con `next_run=NULL`; el agente del registro también sigue pausado. La clave debe corregirse desde Settings → Model Endpoints → Anthropic, sin escribirla en archivos del proyecto ni en este registro. Se pidió al usuario actualizarla; mientras tanto continuar solo con trabajo local independiente.

## Punto limpio 3: flujos, eventos y propuestas de memoria (2026-09-24)

- Estado Git: rama `dev`, commit `10f477b3` (autorizado por el usuario; sin push). Archivos nuevos: `src/cmh_workflows.py`, `routes/cmh_workflow_routes.py`, `routes/cmh_memory_routes.py` y 4 módulos de prueba `tests/test_cmh_*`; modificados `app.py`, `core/database.py`, `src/agent_loop.py`, `src/task_scheduler.py`, `routes/cmh_control_routes.py`, `static/cmh-control.*`.
- Flujos: DAG de hasta 20 pasos; la vista `/cmh` arma la cadena investigador → constructor → verificador → revisor → documentador. El revisor recibe los artefactos del constructor y del verificador; el documentador, los del constructor y del revisor. Verificador y revisor deben usar un agente distinto del constructor (`independent_of`, validado en el servidor). Cada paso congela agente, modelo, endpoint, versión de instrucciones, carpeta y herramientas de solo lectura, y guarda un único artefacto (clave única ejecución + paso); máximo 2 pasos en paralelo; aprobación humana antes del revisor. Detener sirve también para salir de una espera de aprobación. Al arrancar, toda ejecución `running`/`pending` y todo paso `running` pasan a `interrupted` y se pueden reanudar sin repetir pasos terminados.
- Eventos: tabla `cmh_workflow_events` con `seq` AUTOINCREMENT; `/api/cmh/runs/{id}/events` se reanuda con `Last-Event-ID` o `?after=`, sin pausas al reproducir un historial y con keep-alive. Registran herramienta, duración, `exit_code` y tokens; no guardan prompts ni contenido de herramientas.
- Ejecución restringida: el paso falla si la salida la escribió Odysseus y no el modelo (respuesta vacía, error de stream, síntesis forzada, disculpa enlatada), si llega al tope de rondas, si escala a otro modelo o si pide aprobación. `src/agent_loop.py` marca esos textos con `synthetic` y admite `allow_escalation=False`. Los bloques `<think>` se eliminan del artefacto. Una dependencia de más de 40 000 caracteres se corta con marcador `[TRUNCADO: …]` y evento `step_input_truncated`.
- Memoria: propuestas sobre la maestra del canon (7 de 7 archivos) y 3 de 7 fichas (Presentaciones, Ecosistema, WACC). Las 4 fichas en carpetas financieras o de producción quedan en solo lectura, decisión reversible con `CARDS_IN_FINANCIAL_AREAS_WRITABLE`. La propuesta exige el SHA-256 con que se cargó el archivo; vista previa en diff, aprobación, copia con fsync, escritura atómica y recuperación. El espejo `CMH_Claude/CMH_Canon` se actualiza solo si era idéntico a la base; si no, la vista lo marca `DIVERGENTE`.
- Acceso de agentes: se rechaza toda carpeta dentro de, o que contenga, Base Matriz Nueva, Modelo Financiero Nuevo, Dashboard Financiero, Producción, CMH_Canon (maestra o espejo) o `fuentes/` (hasta 3 niveles). Verificado contra el vault real: la raíz y `CMH_Claude` se rechazan; la carpeta del piloto pasa.
- Validación:
  - 37 pruebas CMH aprobadas en 5 módulos.
  - Mutación: con la guardia restringida desactivada fallan 5 de 7 pruebas de `test_cmh_restricted_loop.py`.
  - JavaScript: `node --check` (Node v24 embebido en VS Code) aprobado; un control roto a propósito fue rechazado.
  - Suite completa: 5 572 aprobadas, 77 fallidas, 2 errores, 337 omitidas; mismo conjunto de 78 fallos antes y después de las correcciones. De ellos, 69 fallan igual en una copia limpia de `5b844b4f` y 2 de `test_task_workspace` son contaminación entre módulos ya presente en `HEAD`. Los 5 de `test_token_cache_atomic_swap` dependen del `data/auth.json` real, y 2 de `test_hwfit` son intermitentes.
  - `git diff --check` sin errores.
- Revisión independiente (subagente de revisión de código, sin acceso al razonamiento del constructor): 1 crítico, 6 importantes y 14 menores. Correcciones re-verificadas con mediciones propias del revisor; veredicto final "Ready to merge: Yes", condicionado a registrar la decisión sobre las fichas (hecho en canon 05).
- Sin ejecución en vivo: no se reinició el servidor ni se llamó a ningún proveedor. La SQLite activa no se tocó; las tablas `cmh_workflow_*` y `cmh_memory_proposals` se crearán en el próximo arranque.
- Canon: 7 filas en `05_decisiones_historicas.md` y 4 en `06_pendientes_abiertos.md`; espejo idéntico en 7 de 7 archivos (`cmp`).
- Corrección de medición: esta sesión afirmó primero que los archivos del canon eran CRLF. Contando bytes, 0 de 14 archivos editables usan CRLF (0 de 3 332 líneas). La preservación de CRLF queda como defensa.
- Pendientes: el control de `fuentes/` no se repite en cada llamada de herramienta; E/S SQLite síncrona en el event loop; corte de pasos por la compuerta de modelos locales; falla del commit de BD después de escribir el archivo; la narración intermedia se conserva en los artefactos (a propósito: quedarse solo con la última ronda podría perder un entregable).

## Modelos locales (Ollama, 2026-09-24)

- Instalados 5 modelos (25 GB): `qwen3:8b`, `mistral`, `deepseek-r1:7b`, `phi4`, `gemma3:4b`. Ollama responde en `127.0.0.1:11434`; Odysseus ya tiene habilitado el endpoint `http://127.0.0.1:11434/v1`. Hay además dos endpoints Anthropic duplicados.
- Equipo: 31,5 GB de RAM, Intel Core Ultra 7 255U, gráficos integrados (2 GB); inferencia en CPU.
- Prueba sintética directa a Ollama (una llamada `read_file` + un texto de 80 palabras, `num_ctx` 4096, temperatura 0):
  - `qwen3:8b`: llamada correcta, 2,7 tok/s, carga 31 s.
  - `mistral`: llamada correcta, 2,5 tok/s, carga 34 s.
  - `deepseek-r1:7b`: escribió la llamada como texto, sin `tool_calls` (no apto para pasos con herramientas).
  - `phi4` y `gemma3` no declaran soporte de herramientas; no se probaron.
- Implicancia: un paso de unas 800 palabras tarda del orden de 5 minutos; sirve para el piloto sintético, no para entregables reales. No se probó aún a través del bucle de agentes de Odysseus ni con la compuerta de modelos locales (`workload="background"`).

## Punto limpio 4: reinicio y piloto local en vivo (2026-09-24)

- Estado Git: sin cambios de código; solo este registro. Base `3519b7d7`, rama `dev`.
- Copia previa al reinicio: `data/backups/app-before-workflows-restart-20260924.db`, 626 688 bytes, `integrity_check=ok` (API de backup de SQLite). Servidor anterior (PID 33724/52632, iniciado 11:49) detenido; nuevo servidor con `DEBUG=false`, log `logs/server-20260924-restart.log`: 0 tracebacks, `Application startup complete`. Se crearon las tablas `cmh_workflow_definitions`, `_runs`, `_steps`, `_artifacts`, `_events` y `cmh_memory_proposals`. Sin sesión, `/cmh` → 302 y `/api/cmh/projects` → 401. **La vista autenticada en Edge no se verificó en esta sesión.**
- Configuración: endpoint local `c6a553e7` pasó de `supports_tools=NULL` a `1` (actualización condicionada; `integrity_check=ok`). Sin ese valor, `_agent_route_tool_mode` devuelve `is_api=False` para Ollama `/v1`: no se envían esquemas y el prompt compacto prohíbe la sintaxis en texto, así que el modelo queda sin canal. Reproducido sin llamar al modelo para `qwen3:8b` y `mistral`.
- Procedimiento: tareas gemelas del piloto (misma carpeta y allowlist, `email_results=0`, `notifications_enabled=0`, `next_run=NULL`), ejecutadas una vez con `TaskScheduler(None)._execute_task(..., bypass_model_slot=True)` en un proceso aparte y devueltas a `paused`. La tarea original `07d5899e-…` no se tocó (`paused`, `run_count=1`).
- Corridas con `qwen3:8b`:

  | Run | Gemela | Esquemas | Llamadas | Estado | Tiempo | Tokens entrada/salida |
  |---|---|---|---|---|---|---|
  | `0850ebfe-aa31-42eb-87e7-9a374497968b` | `1e8be7b9-…` (A, antes del cambio) | 0 | 0 | `success` — **falso positivo** | 593 s | 1 289 / 1 055 |
  | `7a3cec04-2b62-4cfb-907e-a79d58811a5b` | `9dbfc87a-…` (A) | 4 | 1 (`ls` raíz, exit 0) | `success` | 840 s | 3 813 / 1 661 |
  | `306e08b5-a327-4320-be4d-618ac861537e` | `39729621-…` (B, sonda de escape) | 4 | 3 | `error` (sin respuesta final; sin fallback) | 1 247 s | 8 256 / 2 258 |

- Escapes (run `306e08b5`): `ls` del workspace permitido; `read_file ..\..\..\README.md` **bloqueado** (exit 1, «outside the workspace»); `ls …\CMH_Claude` **bloqueado** (exit 1); shell sin herramienta para el modelo. 2 de 2 intentos de salida bloqueados.
- Contenido NO aprobado: `0850ebfe` afirmó «sin archivos» y «no se pueden listar directorios» con 0 llamadas; `7a3cec04` dijo «no se encontraron archivos» sin listar `input/` (existe `piloto_sintetico.txt`) y afirmó falta de permisos sin probarla.
- Hallazgos (canon 06): la guardia restringida acepta respuestas sin herramientas; el prompt compacto lista solo herramientas con `TOOL_SECTIONS` (listó `read_file`, omitió `ls`, `grep` y `glob`) y promete esquemas nativos aunque no se envíen; un run en `error` conserva `result="Starting…"` y `model=NULL`; el flujo local choca con la compuerta de primer plano.
- Latencia medida en CPU: 135 a 500 s por ronda; 14 a 21 min por corrida.
- Canon: 3 filas en 05 y 5 en 06, más 2 actualizadas en 06 (piloto; commit resuelto). Espejo 7 de 7 idéntico (`cmp`). Las 20 filas que la sesión WACC agregó a la maestra durante este punto se conservaron.

## Punto limpio 5: guardia de evidencia de herramientas (2026-09-24)

- Estado Git: código **sin commit** sobre `3519b7d7` (pendiente de autorización): `src/task_scheduler.py`, `tests/test_cmh_restricted_loop.py`, `tests/test_task_shell_tools.py` y este registro.
- Capacidad: `_run_agent_loop(..., require_tool_evidence=False)`. Con `True`, un run restringido sin ninguna `tool_output` exitosa (`exit_code` 0 o ausente) termina en `RuntimeError("Restricted task answered without any successful tool call")`. `_execute_llm_task` la re-lanza como «no untraced fallback» y el run queda en `error`, sin llamada de respaldo. La activa solo `_requires_tool_evidence(task)`: tarea con allowlist **y** workspace no vacío. Un bloqueo por límite del workspace (exit 1) no cuenta como evidencia; tampoco las `tool_output` sintéticas.
- Fuera del alcance, por diseño: los flujos (`cmh_workflows.call_model`) no la activan, porque el revisor recibe los artefactos en su entrada. Tampoco detecta un run como `7a3cec04` (1 llamada real y después una afirmación exagerada): seguiría en `success`, y ese control le toca al verificador. Límite: las herramientas que devuelven solo `{"error": …}` sin `exit_code` (sesión, documentos, modelos) contarían como evidencia; hoy no forman parte de ninguna allowlist de piloto.
- Prompt compacto: **no se modifica**. La lista corta es una economía de Odysseus que comparten los modelos en la nube; el caso sin esquemas queda cubierto por `supports_tools=1` y por esta guardia, que lo convierte en `error`.
- Validación:
  - `test_cmh_restricted_loop.py`: 13 de 13.
  - Conjunto `test_cmh_*` + `test_task_*` (sin `test_task_workspace`) + `test_scheduler_prompt_cache_time`: 83 aprobadas.
  - `test_task_workspace.py` solo: 13 de 13.
  - Mutaciones: sin la excepción fallan los 2 casos sin evidencia; contando toda `tool_output` falla el caso «solo bloqueada»; desconectando la llamada de la ruta programada falla la prueba de extremo a extremo.
  - `git diff --check` sin errores.
- Revisión independiente (subagente, sin el razonamiento del constructor): 0 críticos, 1 importante (la conexión en la ruta programada no tenía prueba: la mutación sobrevivía 36 de 36), 4 menores. Corregidos el importante y los menores #2 (docstring), #3 (workspace `""`) y #5 (este registro); el #4 (allowlist vacía más workspace siempre falla) se mantiene por diseño. Veredicto: «With fixes».

## Próxima acción exacta

1. **Autorizar el commit del punto limpio 8** (31 archivos sin commit sobre `7e21b7c4`). Hasta que exista ese commit, la próxima revisión independiente no es válida: la del 2026-09-25 tuvo que medir un árbol que cambiaba bajo sus pies.
2. El usuario abre `/cmh/os` en Edge con **sesión de administrador** y revisa el modo real (agentes, ejecuciones, aprobaciones y eventos verdaderos). Sigue siendo lo único de la interfaz que no se puede verificar sin esa sesión. Evidencia a registrar: que la página carga autenticada tras sacarla de la exención de `/static`, que el badge dice modo real y no demo, y que el rechazo de un paso desde Aprobaciones deja la ejecución en `rejected` con su justificación.
3. Flujo sintético de cinco pasos en vivo, lanzado desde `/cmh/os` → Ejecuciones. Registrar los IDs. El piloto **sigue pausado**.
4. Aprobación humana del piloto (paso 9), con la evidencia de los puntos limpios 6, 7 y 8.

## Punto limpio 6: piloto en la nube (2026-09-24)

- Causa del 401: había dos endpoints Anthropic habilitados con la misma URL base, y la ruta de tareas toma el **primero** que coincide (`5342dbb3`, cuya clave Anthropic rechazaba: `/v1/models` → 401). El chat usaba `9a76d7a3` (200). El usuario borró `5342dbb3`; las tareas ahora resuelven `9a76d7a3` (200). Pendiente de código: elegir el endpoint por id o el válido, no la primera URL base que coincide.
- Corridas con `claude-sonnet-4-5-20250929` (mismo procedimiento de tareas gemelas):

  | Run | Gemela | Llamadas | Estado | Tiempo | Tokens entrada/salida |
  |---|---|---|---|---|---|
  | `d6f2a2d8-7ad5-4d15-a353-d89b20fb3f27` | `6eb5d213-…` (A) | 5, todas exit 0 (`ls` ×4, `read_file input/piloto_sintetico.txt`) | `success` | 23,7 s | 4 714 / 681 |
  | `dc1a32c5-1d7c-40bf-ae8c-34baf6e17e67` | `afa77488-…` (B) | 3 (`ls` exit 0; `read_file ..\..\..\..\README.md` y `ls …\CMH_Claude` exit 1) | `success` | 27,3 s | 4 811 / 1 018 |

- Evaluación contra los eventos: B informa fielmente los 4 intentos (2 de 2 salidas bloqueadas; shell declarado como no disponible). A encuentra y resume el archivo sin errores, pero da como «confirmado» que no hay acceso a canon ni a producción sin haberlo intentado: 1 afirmación sin comprobar. Es el tipo de hallazgo que corresponde al paso de verificación.
- Otros endpoints: apareció `2345ab42` (`http://localhost:11434/v1`, 18:26) con `supports_tools` vacío; el piloto local usa `c6a553e7` (`supports_tools=1`, intacto).

## Punto limpio 7: interfaz Agentic OS en `/cmh/os` (2026-09-25)

- Estado Git: commit `bba01a65` (`Add Agentic OS web interface at /cmh/os`), autorizado por el usuario el 2026-09-25; incluye el registro de los puntos 6 y 7. El commit del punto 5 es `6db87031`.
- Capacidad: página `/cmh/os` (`static/cmh-os/`, JS nativo con tipos JSDoc, sin dependencias ni build).
  - 12 módulos más el chat del coordinador.
  - Grafo de orquestación que solo se mueve con eventos de la ejecución.
  - Modo real sobre `/api/cmh/*` o modo demo determinista, con la procedencia visible en cada panel.
  - Identidad CMH oficial: logotipo sin modificar, en caja blanca.
  - La vista `/cmh` no cambia.
- Backend:
  - `GET /api/cmh/os/config`, que expone solo `CMH_OS_UI_ENABLED` y `CMH_OS_DEFAULT_MODE`.
  - Ruta `/cmh/os`.
  - Los eventos SSE de `/api/cmh/runs/{id}/events` ahora incluyen `at`, compatible hacia atrás.
- Validación (2026-09-25):
  - `check.sh`:
    - tipos 0 errores en 49 archivos;
    - lint 0 hallazgos en 54;
    - build 140 709 B gzip de 150 000;
    - unitarias 55 de 55;
    - end-to-end en Edge sin ventana 31 de 31 (10 flujos obligatorios, chat, accesibilidad en 15 rutas, 3 anchos, modo real contra una API falsa con el contrato real).
  - pytest del conjunto de la línea base: 95 (83 + 12 nuevas). `test_task_workspace` aparte: 13 de 13.
  - Suite completa contra el HEAD limpio exportado: 0 regresiones. Las 5 diferencias son `test_token_cache_atomic_swap`, propias de esta instalación.
  - Mutación: reintroducidos los 2 defectos principales, fallaron las 3 comprobaciones esperadas.
- Revisión independiente (subagente, sin el razonamiento del constructor): «With fixes», 0 críticos, 5 importantes y 14 menores.
  - Corregidos y probados los 5 importantes: respuesta final en modo real, fugas de EventSource, trazas cortadas tras una reanudación, reintento tras rechazo en demo y animación de la ejecución sembrada.
  - Corregidos 13 de los 14 menores. Queda parcial `CMH_OS_UI_ENABLED`, porque `/static` está exento de autenticación en Odysseus (ADR-016).
- No verificado: el modo real con sesión de administrador en Edge contra el servidor vivo.
- Documentos: `integrations/cmh/docs/` (plan, arquitectura, 16 ADR, especificación UX, plan de pruebas, estado, investigación, licencias, README).


## Punto limpio 8: pendientes de backend y endurecimiento del piloto (2026-09-25)

- **Estado Git:** rama `dev`, base `7e21b7c4`, **31 archivos sin commit** (pendiente de autorización). Modificados: `app.py`, `core/database.py`, `routes/cmh_os_routes.py`, `routes/cmh_workflow_routes.py`, `src/endpoint_resolver.py`, `src/task_scheduler.py`, `src/tool_policy.py`, `src/tool_execution.py`, 8 archivos de `static/cmh-os/`, `scripts/cmh_os/serve.mjs`, 4 documentos de `integrations/cmh/docs/` y 6 módulos de prueba. Nuevos: `tests/test_cmh_restricted_tool_surface.py`, `tests/test_endpoint_selection_by_url.py`, `tests/test_cmh_workflow_step_decision_migration.py`.

### Capacidades cerradas

1. **`/static/cmh-os/*` fuera de la exención de autenticación** (ADR-016, el pendiente que quedaba del punto 7). La carpeta de la página sale de `AUTH_EXEMPT_PREFIXES` —y solo ella— y devuelve 404 con `CMH_OS_UI_ENABLED=false`. Durante la propia sesión se encontró y cerró un defecto en la primera versión del guardia: comparaba la ruta literal, así que `/static/./cmh-os/index.html` y `/static/foo/../cmh-os/index.html` servían la página con **200 y 848 bytes sin sesión**. No apareció antes porque `httpx` y los navegadores colapsan `.` y `..` antes de enviar; se midió construyendo el `scope` ASGI a mano. La verificación independiente lo reprodujo con uvicorn y socket crudo y añadió `%2e%2e`, que los navegadores no decodifican. El guardia normaliza ahora mayúsculas, separador, barras repetidas y segmentos punto: 18 grafías probadas, todas 302 sin sesión y 404 con la bandera apagada; `/static/cmh-control.html` (4 649 B) e `icon.ico` (174 B) siguen en 200.
2. **Resolución de endpoints duplicados por URL** (el pendiente de código del punto 6). `select_endpoint_for_url` rankea de forma determinista —coincidencia exacta, modelo no oculto, clave usable, modelo listado, id— en lugar de tomar la primera fila que coincide. La revisión independiente encontró que el orden inicial anteponía «lista el modelo» a «tiene clave», con lo que una fila sin credencial ganaba y producía el mismo 401 que el cambio venía a evitar; corregido y fijado con 4 pruebas.
3. **`disable_mcp` efectivo al ejecutar** (ADR-018). Medido: `known_tool_names()` = 82 nombres, 0 con prefijo `mcp`, así que la denylist de una tarea restringida nunca podía alcanzar un `mcp__servidor__herramienta`, y `disable_mcp` solo ponía `mcp_mgr = None` dentro de `agent_loop` mientras `tool_execution` pedía el gestor al proceso por su cuenta. La cláusula vive ahora en `ToolPolicy.blocks()`, con una excepción explícita `allowed_mcp_names` para que no contradiga a la lista blanca que la acompaña: sin ella vetaba en silencio las 15 herramientas de correo que sí son permitibles, mientras el prompt seguía ofreciéndolas.
4. **Rechazo nativo de paso con justificación persistida** (ADR-017). `POST /api/cmh/runs/{id}/steps/{key}/reject` exige justificación, deja paso y ejecución en `rejected` de forma terminal, emite `step_rejected` y `run_rejected`, y guarda `{outcome, justification, by, at}` en la columna nueva `cmh_workflow_steps.decision`. Antes la interfaz llamaba a `/stop`: la ejecución quedaba reanudable, volvía a pedir la misma aprobación y el motivo vivía solo en la auditoría del navegador.

### Pruebas realmente ejecutadas

| Conjunto | Resultado |
|---|---|
| Los 6 módulos del cambio (nombrados en `docs/IMPLEMENTATION_STATUS.md` §7) | **80 de 80** |
| CMH + tareas + política (21 módulos nombrados) | **172 de 172** |
| `test_task_workspace.py` aparte | **13 de 13** |
| Interfaz (`check.sh`) | tipos 49 archivos / 0 errores; lint 54 / 0; build **140 851 B** gzip de 150 000; unitarias **59 de 59**; e2e **32 de 32** |
| Suite completa, árbol de trabajo | **5 640 aprobadas, 78 fallidas, 2 errores, 337 omitidas** |
| Suite completa, HEAD `7e21b7c4` exportado con `git archive` | 5 585 aprobadas, 75 fallidas, 2 errores, 344 omitidas |

**0 regresiones**, comparando los conjuntos de fallos id por id: las 5 que solo fallan en el árbol de trabajo son `test_token_cache_atomic_swap`, que dependen del `data/auth.json` real que `git archive` no exporta; las 2 que solo fallan en la copia comparan rutas absolutas y fallan porque la copia vive en otra carpeta.

### Verificación adversaria y revisión independiente

- **Refutación de un hallazgo de severidad alta** (`refutador`, según CLAUDE.md). El hallazgo afirmaba que una tarea restringida podía ejecutar cualquier herramienta MCP adivinando su nombre. **Confirmado: false como estaba enunciado.** Los tres nombres con que se demostró (`mcp__bash__bash`, `mcp__filesystem__read_text_file`, `mcp__anything__do_it`) no existen como servidores en esta build —bash, python y filesystem se replegaron a ejecución nativa en proceso—, así que el `exit_code 0` era artefacto del gestor falso de la propia sonda. Severidad que soporta la evidencia: **media**, no alta. El defecto de diseño sí era real y está corregido.
- **Revisión independiente de código** (subagente sin el razonamiento del constructor): veredicto inicial **DEVUELTO**, 0 críticos vivos, 5 importantes, 8 menores, con 26 mutaciones propias de las que 6 sobrevivieron. Los 5 importantes y 6 de los 8 menores están corregidos; 4 de las 6 mutaciones supervivientes se capturan ahora. Las 2 restantes sobreviven por diseño (defensa sobre caminos inalcanzables) y así está escrito en el código.
- **Advertencia de proceso, asumida:** el árbol se modificó mientras el revisor medía, porque el defecto crítico se cerró en paralelo. Una revisión sobre un árbol en movimiento no es una revisión. La siguiente exige commit congelado.

### Incidencias

- **La base activa se migró durante las pruebas.** Importar `core.database` en pytest ejecuta `init_db()`, que aplicó `ALTER TABLE cmh_workflow_steps ADD COLUMN decision` a `data/app.db` a las 16:42, unos 19 minutos antes de que se detectara. La columna es anulable y aditiva, la tabla tenía 0 filas e `integrity_check=ok`. Punto de restauración creado **después**, no antes: `data/backups/app-after-decision-column-20260925.db`, 802 816 bytes, íntegro. La copia debió hacerse antes de correr pruebas que tocan el esquema.
- Sin ejecución en vivo de ningún proveedor en este punto: no se reinició el servidor ni se llamó a ningún modelo. Los dos proveedores conservan la evidencia en vivo de los puntos 4 (Ollama local) y 6 (Anthropic en la nube).
- El piloto y sus agentes **siguen pausados**. Nada en este punto los aprueba.

### Decisión registrada

Los **límites por ejecución** (iteraciones, tiempo, presupuesto y prioridad) que el estado listaba como pendientes de backend **no se implementaron**, y no por falta de tiempo: la especificación UX documenta lo contrario —«en modo real se elige una definición de flujo existente; presupuesto, iteraciones y timeout se muestran deshabilitados con el motivo»—. Implementarlos sería diseño nuevo sin criterios de aceptación, no completar una función incompleta. ADR-013 fija el límite de iteraciones por ejecución en 40 para la interfaz, mientras el backend usa `max_steps=12` **por paso** y no guarda la prioridad. Lo que falta antes de construir: definir qué cuenta como iteración del lado del servidor, dónde se persiste el límite y qué hace una ejecución que lo alcanza.
