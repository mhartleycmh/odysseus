# Estado operativo: Agentic OS CMH

Fecha de corte: 2026-09-30 (hora de Lima; la Fase 1 en curso está en «Punto en curso — Fase 1», el resto es histórico). Este archivo es el punto de reanudación para Claude y Codex. Actualizarlo al cerrar cada punto limpio con evidencia, no con intenciones.

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

## Punto en curso — Fase 1 (2026-09-30)

**La Fase 1 NO está cerrada: 0 de 7 pasos HECHOS.** Son los seis del blueprint (§18: 3.1 inventario y
acciones del usuario, 3.2 compuerta de costo cero, 3.3 router con fallback y cuotas, 3.4 pila local medida,
3.5 cinco agentes y una definición, 3.6 primera ejecución real y cierre) más el **3.3b**, que se nombró con
sufijo de letra como manda el encargo (el total global pasó de 18 a 19): las correcciones de la auditoría
del 29.09 sobre el 3.3, en cuatro partes (estado del proveedor, descubrimiento de OpenRouter, identificador
del candidato local y cuota), definidas en `scripts/cmh_mutants/round4.py`. Bloqueada por el usuario en 3.1
(claves) y en 3.5 (autorización de la siembra); 3.6 depende de ambos. Sin una ejecución real no hay punto
limpio 10.

- **Git.** Rama `dev`; el fix de credenciales quedó en el commit local sin push `9a65ec72`, junto con los cambios e2e de foco y limpieza de Edge. La revisión independiente del candidato posterior a r9 sigue pendiente.
  Etiquetas de revisión: `revision-fase1-r2` a `r8` y `revision-fase1-r9`, que congela el commit de documentos de r9.
- **Revisión independiente de `revision-fase1-r6` (`ea4eee18`): DEVUELTO**, 0 P1, 19 P2 y 66 P3. r7
  corrige los 19 P2 y 59 de los 66 P3 (los otros 7 quedan declarados como límites en ADR-036), en ocho
  commits; `82176e19` no lleva mutantes (resumen y límites en ADR-036):
  `bea9b262` (bucle de mutantes), `249daeec` (compuerta), `352ebde8` (descubrimiento), `a0048662` (cuota de
  un intento que muere a medias), `00f6dc52` (informe del run), `10ad364f` (guiones locales), `c1f34f40`
  (credenciales, proxy y siembra) y `82176e19` (una prueba que dependía del `%TEMP%` compartido).
- **Revisión independiente de `revision-fase1-r7` (`662e141e`): DEVUELTO**, 0 P1, **3 P2** confirmados por
  refutador y 49 P3 (59 hallazgos brutos de cinco lentes; de 7 P2 brutos, 2 se refutaron y 1 bajó a P3). De
  los 19 P2 de r6, 18 reprodujeron como corregidos y 1 seguía abierto, el nº6 (credencial en el PATCH), por
  una corrección mía que enviaba `Bearer Basic`. Ninguna lente pudo medir Groq, OpenRouter ni LM Studio reales.
- **r8 corrigió los 3 P2 de r7 y dejó residuo en 16 de sus 49 P3** (según el veredicto de la tercera
  revisión; la lista está en ADR-038), en nueve commits (ADR-037): `9a2a94b4` (cabecera `Basic` enviada como
  `Bearer Basic`: P2 nº1 y nº2), `eef71964` (fila con credenciales, `provider_dropped`, siembra con clave),
  `43166b55` (guiones locales), `819579a1` (informe), `7d0e466e` (evento de cuota e interfaz), `b68ab6a9`
  (mutantes, herramienta de campañas, guarda de `httpx`), `efe02b56` (pruebas del PATCH de U1), `a0cb586a`
  (mutante T15) y `754cf669` (mutante Z11). No pasan `test_cmh_mutant_validity` `eef71964` (4 de 13
  casos) y `43166b55`, `819579a1` y `7d0e466e` (5 de 13); los demás sí (medido).
- **Revisión independiente de `revision-fase1-r8` (`259d37b9`): DEVUELTO**, 0 P1, **3 P2** y 52 P3 (529
  comprobaciones de cinco lentes; 74 hallazgos brutos fusionados en 55). Los 3 P2 de r7 reprodujeron como
  corregidos. Los nuevos: una regresión mía en `start.ps1` (daba `phi-4-mini` por cargado con
  `phi-4-mini-reasoning` cargado), una prueba de la cabecera que medía el ayudante y no el remitente, y una
  cifra falsa de un mensaje de commit (19 mutantes cambiados; eran 13). Ninguna lente pudo medir Groq,
  OpenRouter ni LM Studio reales.
- **r9 corrige los 3 P2 y 47 de los 52 P3** (los otros 5, #7, #9, #10, #14 y #48 del veredicto de r8, quedan
  declarados sin cambio en ADR-038), en ocho commits, cada uno con sus pruebas y sus mutantes en el mismo
  commit:
  `7ef5dd53` (`start.ps1`), `592c99c5` (la cabecera en el transporte), `48c8b947` (`bench.ps1`), `c000925b`
  (siembra), `e5f6ebfc` (servidor), `85534637` (informe), `76d96bd3` (`/cmh/os`) y `3f758bed` (herramientas de
  campañas). La cuarta revisión, sobre `revision-fase1-r9`, se lanza a continuación: su veredicto se registra
  aquí y en ADR-038.
- **Medido** sobre un export limpio de `c1f34f40` (sin `.git`): `tests/test_cmh_*.py` = **629 aprobadas,
  0 fallidas**, 1 advertencia, 26 min 59 s. Campañas de mutantes sobre exports separados: `round3` 13/13, `round4` 64/64, `round5` 39/39, `round6` 45/45, `round7` 13/13, `round8` 32/32 y `round9` 20/20 sobre `c1f34f40`; `round2` no dio veredicto allí (línea base roja por una prueba que miraba el `%TEMP%` compartido; corregida en `82176e19`) y sobre `82176e19` dio 13/13, con `round3`, `round7` y `round9` repetidas: 13/13, 13/13 y 20/20. En total 239 mutantes, 0 sobrevivientes, 0 inválidos y 0 obsoletos, con el árbol restaurado en verde en las ocho.
- **Medido en r8** (detalle y límites en ADR-037). Sobre un export de `64756140` (árbol de `b68ab6a9`): suite =
  **949 aprobadas, 1 fallida** (`test_rewrites_loopback_when_in_docker`, preexistente: falla si algo escucha
  en el 1234) y las ocho campañas = **277 capturados, 2 sobrevivientes, 0 inválidos, 0 obsoletos, de 279**; los
  dos (T15 de `round4`, Z11 de `round9`) eran defectos de mi prueba y de mi mutante, y se corrigieron en
  `a0cb586a` y `754cf669`. Sobre un export de la punta `754cf669`: suite = **953 aprobadas, 1 fallida** (la
  misma), los 21 mutantes `T` de `round4` = 21 de 21, y T15 y Z11 caen. No se repitieron sobre la punta las
  otras siete campañas (código y pruebas designadas idénticos: se infiere, no se midió).
- **Medido en r9** (detalle y límites en ADR-038), sobre exports limpios de `3f758bed`, la punta de código:
  suite = **992 aprobadas, 1 fallida** (la misma preexistente; 953 de r8 + 39 nuevas); **las ocho campañas
  enteras = 332 de 332 mutantes capturados**, 0 sobrevivientes, 0 inválidos, 0 obsoletos (279 en r8: 53
  añadidos, 0 quitados, 14 cambiados); prueba de validez de mutantes **13 de 13 en los nueve árboles** (la
  base de r8 y los ocho commits de r9). Interfaz en r9: tipos 0 errores, lint 0, unitarias 62 de 62; e2e
  31 de 32.
- **Base activa** (solo lectura, `integrity_check=ok`, 811 008 bytes): 1 agente (`CMH Researcher`, pausado),
  0 definiciones, 0 ejecuciones, 3 endpoints (dos Ollama habilitados y Anthropic), ninguna clave gratuita
  registrada. **La siembra no se ha ejecutado nunca contra ella.** Copias previas en
  `%LOCALAPPDATA%\Odysseus\backups\` (la última, `app-antes-de-pytest-r8-20260930-1131.db`, 811 008 bytes,
  con `integrity_check=ok` en origen y copia; la anterior, `app-antes-de-pytest-r7-r2-20260929-2310.db`, con
  42 tablas sin diferencia de conteo).
- **Servidor** del puerto 7000: al 30.09 15:59 no había ningún proceso escuchando (`Get-NetTCPConnection`);
  la última vez que corrió era el código del 25.09. No se reinició. LM Studio sí sirve el 1234.
- **Seguimiento e2e (2026-10-01).** Los cambios locales en `cdp.mjs` y `run.mjs` corrigen la limpieza del
  proceso de Edge y muestrean el foco al montar el detalle y tras cargarlo. Suite e2e ejecutada: **32
  comprobaciones, 32 aprobadas, 0 fallidas**, incluida «A11y: abrir un detalle con Enter lleva el foco a su
  h1». Ambos archivos quedaron incluidos en `9a65ec72`; la revisión independiente del código de r9 y de los commits posteriores
  posteriores sigue pendiente. No se cuenta como cerrada la revisión de Fase 1.
- **Pruebas focalizadas posteriores a r9 (2026-10-01).** Cinco módulos (`test_cmh_provider_discovery.py`,
  `test_cmh_endpoint_patch.py`, `test_cmh_cost_policy.py`, `test_cmh_workflow_routes.py` y
  `test_cmh_step_provider_failures.py`): **284 aprobadas, 0 fallidas**, 1 advertencia. Ocho pruebas
  focalizadas de `start.ps1`: **8 aprobadas**, 73 del módulo no seleccionadas. Se reprodujo y corrigió un
  escape: con `CMH_ZERO_COST=false`, una URL de tarea sin esquema que contenía credenciales llegaba a crear
  el run (201); ahora el snapshot la rechaza (400) aunque la compuerta esté desactivada, sin eco del secreto.
  Mutación `W9` de `round9.py`: **1/1 capturada** por la nueva regresión; árbol del export restaurado en
  **75/75**. Advertencia común: SQLAlchemy `declarative_base()` deprecado. Las dos tareas reproducibles
  están en `.vscode/tasks.json` y usan el `.venv` hermano del workspace.
- **No se hizo, y no está autorizado:** push, borrado de filas o copias, mover `data/`, `cmh_seed_agents.py
  --apply`, `migrate-data.ps1`, aprobar o rechazar un paso en nombre del usuario.

### Acciones del usuario, exactas

1. **U1 · Groq.** Settings → Add Models → Add API Models (Endpoint) → Provider *Groq* → pegar la clave →
   Add. En console.groq.com → Data Controls, activar Zero Data Retention. Dictar en el chat los cuatro
   límites del panel (rpm, rpd, tpm, tpd). **Recomendado:** `supports_tools` no tiene control en la
   interfaz; se pone con un PATCH a `/api/model-endpoints/{id}` (el `id` sale de `GET /api/model-endpoints`)
   desde la consola del navegador, con el cuerpo EXACTO `{"supports_tools": true}`:
   `fetch('/api/model-endpoints/<id>', {method:'PATCH', headers:{'Content-Type':'application/json'},
   credentials:'same-origin', body: JSON.stringify({supports_tools:true})}).then(r=>r.json()).then(console.log)`.
   **Cuidado:** un PATCH sin cuerpo, con JSON mal formado o con `{}` NO da error: alterna `is_enabled` y deja
   el endpoint deshabilitado. Comprobar en la respuesta `is_enabled: true` y `supports_tools: true`; si salió
   `is_enabled: false`, repetir el PATCH sin cambiar nada más para volver a habilitarlo. *Medido en memoria,
   por la ruta real, con 4 pruebas versionadas (`efe02b56`; desde r9 también afirman la respuesta que aquí se
   manda leer); no en vivo: la sesión y las cabeceras reales no se probaron. La interfaz de administración
   hace sus PATCH con ese mismo patrón.* Sin `supports_tools`, el bucle usa
   llamadas a herramientas en bloques de texto (ADR-037), una ruta distinta de la nativa.
2. **U2 · OpenRouter.** Crear la cuenta sin cargar créditos; en su configuración de privacidad, no
   entrenar ni retener; crear una clave (*API Keys*) y **registrarla** igual que la de Groq (Provider
   *OpenRouter*); decidir §10.5. **La siembra no cuenta a OpenRouter** (su modelo se descubre al crear cada
   run, con o sin clave) y su puerta exige Groq con clave (U1). La clave de OpenRouter importa al crear el
   run: sin ella no se descubre su modelo (`provider_discovery: no api key`) y OpenRouter queda fuera de ese
   run.
3. **U3 · Confirmar que ninguna cuenta (Groq, OpenRouter) tiene método de pago** (canon 06, fila 412).
4. **U4 · LM Studio.** Descargar Qwen3.5-4B Q4_K_M y Phi-4-mini Q4_K_M. Registrar `http://127.0.0.1:1234/v1`
   como tipo local. Correr `powershell -NoProfile -ExecutionPolicy Bypass -File
   scripts/cmh_local/bench.ps1 -UnloadOthers` (**descarga lo que haya cargado**: al 30.09 15:59 `lms ps`
   informaba que no había nada cargado; el guion nombra lo que va a descargar antes de hacerlo) y
   después `... start.ps1 -Model <ganador> -UnloadOthers`. Comprobar con `lms ps` que `cmh-local` está
   cargado: sin eso el respaldo local responde 404.
5. **U5 · Deshabilitar (no borrar) los Ollama `c6a553e7` y `2345ab42`**, una vez cada fila.
6. **U6 · Autorizar en el chat `cmh_seed_agents.py --apply`**, después de U1, U4 y U5. Antes se corre el
   ensayo sin `--apply`. Con solo endpoints locales la siembra se niega (`--allow-pending` la fuerza).
7. **U7 · Reinicio del servidor.** Lo hace el agente, con copia previa y `--host 127.0.0.1 --port 7000`;
   `CMH_OS_DEFAULT_MODE` admite `auto|demo`.
8. **U8 · Decidir el traslado de `data/` fuera de OneDrive** (22.1).
9. **U9 · Autorizar el push** de los 50 commits.
10. **U10 · Decidir sobre el stash y las copias de seguridad acumuladas.**
11. **U11 · Revisar `/cmh/os` con datos propios** tras el reinicio.

### Secuencia cuando se desbloquee

Ensayo de la siembra → U6 → `--apply` con copia previa → reinicio (U7) → primer run real de cinco pasos →
`python scripts/cmh_ops/run_report.py --latest` (sale con 0 si se cumple todo, 3 si no) → punto limpio 10
en este archivo con la plantilla del Apéndice C, ficha y revisión hasta APROBADO.

### Para el canon al cerrar la fase (solo filas NUEVAS)

- `05_decisiones_historicas.md`: VERIFICACIÓN de que `endpoint_kind=auto` sobre una red privada cuenta como
  local (ADR-032); el identificador local `cmh-local` en vez del modelo del agente (ADR-029); la cuota cuenta
  peticiones y tokens, también los de un intento fallido (ADR-030); la red privada se define por redes
  nombradas, con CGNAT/Tailscale fuera como SUPUESTO (ADR-032, ADR-036).
- `06_pendientes_abiertos.md`: velocidad real de LM Studio sin medir; `/models/user` de OpenRouter sin
  verificar; `supports_tools` sin control en la interfaz; un PUT de agentes desvincula el `task_id`; los
  textos del blueprint §7.3, §9.1 y §21-U4 quedan reemplazados por ADR-030, ADR-028 y ADR-029; las filas
  390 y 391 quedan superadas; riesgo de 413 por tokens por minuto; `local.model` se aplica a todas las
  filas locales habilitadas; la suite e2e de `/cmh/os` tiene 1 de 32 comprobaciones fallida desde su primer
  commit (A11y, foco tras abrir un detalle).
- **Advertencia:** la maestra `Documentos\Claude\CMH_Canon\` necesita las mismas filas. Se escribe en la
  maestra y se copia al espejo `CMH_Claude/CMH_Canon/` verificando con `cmp`. No tocar las líneas 359–371 de
  `05`.

## Próxima acción exacta

### AVISO ANTES DE CERRAR LA FASE 1: el canon YA está escrito

**No volver a escribir las filas D1–D7.** Verificado el 2026-09-29 en
`CMH_Claude/CMH_Canon/05_decisiones_historicas.md`: las siete están en las
líneas **359–365** (costo cero, Gemini excluido, APIs gratuitas con local de
respaldo, REVERTIDA la de modelos locales solo en verificador, orden de fases,
Ollama retirado, aprobación por conteos). Escribirlas de nuevo al cerrar la
fase las **duplica**.

Además, el canon ya tiene seis filas del **2026-09-29** que el encargo pedía
como VERIFICAR y que no hay que repetir (líneas 366–371):

| Línea | Contenido |
|---|---|
| 366 | Groq nivel Free con Zero Data Retention activado en Data Controls (VERIFICACION) |
| 367 | Cerebras NO califica como costo cero: sin nivel gratuito permanente (VERIFICACION) |
| 368 | OpenRouter solo `:free` y cuenta configurada para no entrenar ni retener |
| 369 | Gemini free excluido, motivo verificado (cierra el VERIFICAR de D2) |
| 370 | **Cerebras sale de la cadena: D3 queda Groq → OpenRouter `:free` → LM Studio** |
| 371 | Se permiten los `:free` de OpenRouter servidos por Google AI Studio |

En `06_pendientes_abiertos.md`: las filas 417 y 418 ya están **RESUELTAS**; la
**412** sigue abierta (confirmar que las cuentas no tengan método de pago).

Lo que sí falta escribir al cerrar la Fase 1 es **solo** lo que esta fase
produzca: el pendiente de evidencia de herramientas que quedó cerrado, el
pendiente nuevo «constructor sin escritura de archivos», y los conteos del
punto limpio 10.


**Lista histórica del 2026-09-28, superada por «Punto en curso — Fase 1» (arriba).** Conservada
como estaba: sus pasos 1 y 2 hablan de un agente y de LM Studio que ya cambiaron.

Actualizada el 2026-09-28 al cerrar el punto limpio 9. Los pasos 1 y 2
**bloquean todo lo demás**: sin ellos no existe ningún flujo que ejecutar.

1. **Crear un segundo agente y activar los dos.** Hoy hay **1** agente y está
   `paused`, así que `cmh_workflow_definitions` no puede pasar de 0: cada uno
   de los cinco pasos exige agente `active` con `task_id`, tarea LLM con
   `endpoint_url` y `task.model` idéntico al del agente, y además
   `verificador` y `revisor` deben usar un agente distinto del `constructor`.
   Mínimo real: **2 agentes activos y vinculados**. Se hace en `/cmh`.
2. **Registrar el endpoint de LM Studio** por Settings → Model Endpoints:
   `http://127.0.0.1:1234/v1`, tipo `local`, **`supports_tools` marcado** (sin
   eso no se envían esquemas y se reproduce el falso positivo del punto 4).
   Antes, fijar el GPU offload del modelo en la GUI de LM Studio (≈0,5) o el
   endpoint fallará de forma intermitente: la carga automática usa los
   ajustes por defecto, que crashean (punto 9).
3. **Decidir sobre el endpoint duplicado `2345ab42`** (`localhost:11434`,
   `supports_tools` vacío, Ollama caído). Es un borrado y necesita
   autorización explícita.
4. **Crear el flujo** en `/cmh` → panel *Flujo CMH*. Ese submit **crea y
   lanza** en un solo acto; no existe un camino «crear definición sin
   ejecutar». Registrar los IDs de la ejecución y de cada paso.
5. **Revisión de contenido de `/cmh/os` con datos propios**, que sigue
   abierta desde el punto 7. El comportamiento ya está verificado por
   `scripts/cmh_os/realmode/run.sh` (12 de 12 contra backend real); lo que
   falta es mirar que los proyectos, agentes y ejecuciones **propios** se vean
   como se espera. El servidor en el puerto 7000 **no autoarranca**: si no
   responde, relanzarlo desacoplado con `DEBUG=false` y `APP_PORT=7000`.
   - Medido el 2026-09-25: la instalación tiene **una sola cuenta**,
     `mijhael hartley`, y pasa el control de administrador, porque
     `owner_is_admin_or_single_user` trata al único usuario de una
     instalación monousuario como administrador. No hace falta ningún rol
     extra ni permisos de Windows.
6. **Aprobación humana del piloto**, con la evidencia de los puntos limpios
   6, 7, 8 y 9. El piloto y sus agentes **siguen pausados**; nada en el punto
   9 los aprueba.
7. **Sin push:** HEAD queda 2 commits por delante de `origin/dev`
   (`e3ae1915`, `7f7795e5`). Decidir si se publica.
8. **Pendiente de código, en su propio commit:** la inversión de prioridad que
   el revisor midió y que sobrevive al punto 9 (`llm_core.py:123` deja el
   contador en 0 mientras un llamador de primer plano todavía genera). Exige
   su propia prueba; no debe colarse en un commit que arregle otra cosa.

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

- **Estado Git:** rama `dev`, commit **`0c4e33c8`** (`Close CMH backend gaps: asset auth gate, endpoint choice, MCP clamp, step reject`), autorizado por el usuario el 2026-09-25, sobre `7e21b7c4`. 32 archivos, 1 313 inserciones, 65 eliminaciones. Árbol de trabajo limpio; **sin push** (HEAD queda 1 commit por delante de `origin/dev`). Modificados: `app.py`, `core/database.py`, `routes/cmh_os_routes.py`, `routes/cmh_workflow_routes.py`, `src/endpoint_resolver.py`, `src/task_scheduler.py`, `src/tool_policy.py`, `src/tool_execution.py`, 8 archivos de `static/cmh-os/`, `scripts/cmh_os/serve.mjs`, 4 documentos de `integrations/cmh/docs/` y 6 módulos de prueba. Nuevos: `tests/test_cmh_restricted_tool_surface.py`, `tests/test_endpoint_selection_by_url.py`, `tests/test_cmh_workflow_step_decision_migration.py`.

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
- **Corrección de un dato del registro anterior:** la ficha afirmaba «rama `dev`, 7 commits por delante de `origin/dev`, sin push». Medido el 2026-09-25 antes de commitear, `origin/dev` ya contenía `7e21b7c4` y HEAD coincidía exactamente con él (0/0). Los commits previos sí estaban publicados en el fork `mhartleycmh/odysseus`. `upstream` (`odysseus-dev/odysseus`) es otro remoto y no se tocó.

### Evidencia en vivo tras el commit (2026-09-25, 19:03)

Reinicio del servidor local con el código de `0c4e33c8`, siguiendo el
procedimiento registrado. **Copia previa hecha antes esta vez**:
`data/backups/app-before-restart-20260925.db`, 802 816 bytes,
`integrity_check=ok`.

- Servidor anterior PID 4584 (arrancado 13:17:55, código previo al punto 8)
  detenido; nuevo PID **28036**, log `logs/server-20260925-punto8.log`:
  **0 tracebacks**, `Application startup complete`, `Uvicorn running`.
- Se comprobó primero que el servidor anterior **sí tenía la fuga**:
  `/static/cmh-os/index.html` respondía **200 sin sesión**. La corrección no
  estaba activa hasta este reinicio.
- Humo sin sesión sobre el servidor nuevo: `/` 302, `/cmh` 302, `/cmh/os` 302,
  `/api/cmh/projects` 401, `/api/cmh/os/config` 401, `/login` 200,
  `/api/health` 200.
- **Compuerta de activos medida sobre el despliegue real con socket crudo**
  (ni curl ni los navegadores pueden expresar estas grafías: colapsan `.` y
  `..` en el cliente). 10 grafías de la página —literal, `/./`, `/foo/../`,
  `/../static/`, `//`, `%2e`, `%2e%2e`, mayúsculas, `js/main.js`,
  `css/tokens.css`— **todas 302, 0 bytes**. `/static/cmh-control.html`
  (4 649 B) e `icon.ico` (174 B) siguen en **200**, así que la compuerta no es
  un 302 indiscriminado. **0 fugas.**
- **No medido en vivo:** el 404 con `CMH_OS_UI_ENABLED=false` —exigiría otro
  reinicio con la bandera apagada— y todo el modo real autenticado, que
  necesita sesión de administrador.

#### Inventario MCP medido en el arranque real

Cierra una de las preguntas que la revisión independiente dejó sin medir:

| Servidor | Resultado en esta máquina |
|---|---|
| Built-in: Email | conectado, 16 herramientas |
| Built-in: Image Generation | conectado, 1 herramienta |
| Built-in: Memory | conectado, 1 herramienta |
| Built-in: RAG | conectado, 1 herramienta |
| Built-in: Browser (`builtin_browser`) | **falla**: `[WinError 2] The system cannot find the file specified` — no hay npx en PATH |

La superficie de control de navegador que habría tumbado el argumento de
severidad media **no existe en este equipo**. La rebaja de alta a media se
sostiene aquí, y solo aquí: otra máquina con npx sí levantaría
`builtin_browser` y sus 12 herramientas. La corrección de ADR-018 no depende
de ese dato, porque la cláusula bloquea los cinco servidores por igual.

### Modo real verificado en navegador contra un Odysseus real (2026-09-25)

Cierra el punto que llevaba abierto desde el punto limpio 7. El usuario
autorizó hacerlo sobre una **instancia desechable** en vez de su instalación.

- `bash scripts/cmh_os/realmode/run.sh` levanta un Odysseus con base, carpeta
  de datos, puerto y cuenta propios; siembra datos sintéticos; conduce Edge
  contra los manejadores reales de FastAPI; y borra todo al salir. La
  contraseña se genera al azar y no se guarda en ningún archivo. La instancia
  del usuario (puerto 7000) no se contacta en ningún momento.
- **12 de 12 comprobaciones.** Sin sesión, `/cmh/os` redirige y sus activos no
  se sirven. Con sesión, la página carga entera, los módulos ES responden 200
  y la interfaz se declara en modo real sin franja demo. Los agentes y la
  ejecución sembrados llegan del backend. El rechazo exige justificación —sin
  ella ni siquiera abre el diálogo—, llama al endpoint nativo y termina la
  ejecución; la decisión queda en el servidor; una ejecución rechazada
  devuelve 409 a reanudar y a decidir otra vez; el artefacto sobrevive.
- Estado real de la base al terminar, impreso por el propio guion:
  ejecución `rejected`; paso `revisor` `rejected` con
  `{outcome: rejected, justification: "El artefacto no cita la evidencia
  medida.", by: prueba}`; eventos `… step_approval_requested, step_rejected,
  run_rejected`; 1 artefacto conservado.
- **Defecto encontrado en la propia verificación, no en el producto.** La
  primera versión de estas comprobaciones **pasó sin poder fallar**:
  `page.waitFor` envuelve la expresión en `Boolean(...)` y `Boolean(<Promise>)`
  siempre es cierto, así que la condición asíncrona nunca se evaluaba. Ocultó
  que el rechazo por interfaz no se había completado —la base mostraba
  `step_approved` y `run_error`, sin ningún `step_rejected`—. Reescrita con un
  sondeo que espera la promesa, detectó el problema y, corregido el guion,
  pasa de verdad. Es el mismo defecto que la revisión independiente ya había
  señalado en este proyecto: «pruebas que no podían fallar».
- Mutación: devolviendo la interfaz a `/stop` fallan 3 de las 12. El archivo
  se restauró verificando su sha256.
- **Lo que esto NO cubre:** que el usuario mire la página con **sus** datos.
  El guion verifica comportamiento sobre datos inventados, no contenido.

### Decisión registrada

Los **límites por ejecución** (iteraciones, tiempo, presupuesto y prioridad) que el estado listaba como pendientes de backend **no se implementaron**, y no por falta de tiempo: la especificación UX documenta lo contrario —«en modo real se elige una definición de flujo existente; presupuesto, iteraciones y timeout se muestran deshabilitados con el motivo»—. Implementarlos sería diseño nuevo sin criterios de aceptación, no completar una función incompleta. ADR-013 fija el límite de iteraciones por ejecución en 40 para la interfaz, mientras el backend usa `max_steps=12` **por paso** y no guarda la prioridad. Lo que falta antes de construir: definir qué cuenta como iteración del lado del servidor, dónde se persiste el límite y qué hace una ejecución que lo alcanza.


## Punto limpio 9: compuerta de primer plano y pila local (2026-09-28)

- **Estado Git:** rama `dev`, commits **`e3ae1915`** (`Let a watched workflow step hold the local model slot`) y **`7f7795e5`** (`Correct the local-slot rationale and close the review's coverage gaps`), sobre `9854abf4`. Árbol limpio; **sin push** (HEAD queda 2 commits por delante de `origin/dev`). Modificados: `src/llm_core.py`, `src/task_scheduler.py`, `static/index.html`, `tests/test_cmh_restricted_loop.py`, `tests/test_cmh_os_routes.py`. Nuevo: `tests/test_local_model_slot_counter.py`.
- **Queda un stash colgado:** `stash@{0}: On dev: fase3b-temp`. `git stash push -u` sobre OneDrive creó el stash pero **solo quitó el archivo no rastreado**, dejando las modificaciones rastreadas en el árbol. Su contenido ya está en los dos commits. Descartarlo es decisión del usuario. Lección: sobre OneDrive, medir HEAD limpio se hace con `git archive`, no con stash.

### Capacidades cerradas

1. **Un paso de flujo lanzado a mano ya puede adquirir el modelo local.** `_run_agent_loop` pasaba `workload="background"` sin condición, así que en un endpoint local `_local_model_slot` lo hacía esperar mientras el navegador estuviera activo y lo cancelaba en plena generación ante cualquier pedido de primer plano. El latido del navegador sale cada 15 s (`static/app.js`) y mantiene `has_foreground_activity()` en cierto durante 45 s (`BACKGROUND_TASK_BROWSER_ACTIVE_SECONDS`), de modo que **el paso que el usuario estaba mirando nunca podía tomar el candado**. La bandera `foreground_controlled` ya existía desde el punto 3 pero solo salteaba el `wait_for_interactive_quiet` previo al bucle; ahora llega a la compuerta. Los dos llamadores del planificador (`:1525`, `:1674`) la omiten y siguen cediendo el paso.
2. **Contabilidad exacta del contador de esperadores.** Un llamador de primer plano que adquiría el candado decrementaba `_LOCAL_MODEL_WAITING_FOREGROUND` dos veces —una tras adquirir y otra en el `finally`—, borrando la cuenta de un hermano todavía encolado. El `finally` es para el cancelado **mientras esperaba** y ahora corre solo entonces. Latente antes de este cambio, porque el chat era el único llamador de primer plano.
3. **`/cmh/os` tiene entrada en la interfaz.** No había enlace en ninguna parte: la única vía era escribir la URL. Botón `OS` en el riel de iconos, junto al `CMH` que va a `/cmh` (el registro, no el Agentic OS).

### Trueque declarado, no descubierto

Primer plano no cancela a primer plano, así que **el chat ya no puede expropiar un paso de flujo**: se encola detrás. El candado se toma por generación HTTP y el FIFO descarta la inanición, pero con un modelo local esa generación puede ser de minutos (`agent_stream_timeout` por defecto 300 s) y el chat se ve colgado. Medido: `['step-in', 'step-out', 'chat-in after 0.61s']` sobre un paso simulado de 0,60 s. Que un paso lanzado a mano le gane al chat sobre la única GPU local es **decisión de operación, no técnica**; queda fijada por `test_foreground_callers_serialize_without_pre_emption`.

### Pruebas realmente ejecutadas

| Conjunto | Resultado |
|---|---|
| `test_local_model_slot_counter.py` (nuevo) | **8 de 8** |
| `test_cmh_os_routes.py` | **27 de 27** |
| 74 módulos que tocan `llm_core` | **1 019 aprobadas, 9 omitidas, 1 fallida** |
| 23 módulos `test_cmh_*` + `test_task_*` + `test_endpoint*` | **256 de 256** |
| `test_task_workspace.py` aparte | **13 de 13** |
| `git diff --check` | sin errores |

La única fallida es **preexistente y ambiental**: `test_model_routes.py::TestDockerLoopbackRewrite::test_rewrites_loopback_when_in_docker` falla **siempre que algo escuche en el puerto 1234**. Sustituye `_docker_host_gateway_reachable` pero no `_container_loopback_reachable`, que `_rewrite_loopback_for_docker` consulta primero (`routes/model_routes.py:317`). Medido: con el puerto 1234 vivo devuelve la URL sin tocar; con un puerto muerto (59999) reescribe a `host.docker.internal` como la prueba espera. **Defecto de la prueba, no del producto.** El revisor lo reprodujo y diagnosticó de forma independiente.

### Revisión independiente

Subagente `revisor-cmh` sobre el árbol congelado en `e3ae1915`, sin acceso al razonamiento del constructor. **Veredicto inicial DEVUELTO**: 0 críticos, 3 importantes, 3 menores, con 15 mutantes propios de los que **6 sobrevivieron** y 1 colgó. Midió el balance del contador en **6 de 6 caminos de salida: todos correctos**, y confirmó que no hay fuga del candado ni estado inconsistente de tarea o de run.

Lo que devolvió el commit no fue la aritmética, sino **la razón registrada**:

- La justificación escrita en `llm_core.py` afirmaba que un llamador de fondo «se adelantaba al de primer plano». **No se reproduce.** Verificado con medición propia además de la del revisor, mismo escenario (A primer plano con el candado, B primer plano encolado, C fondo sondeando): **orden idéntico con y sin el arreglo — `A, B, C`**. `asyncio.Lock` es FIFO, así que un llamador de fondo que sale del sondeo antes de tiempo igual se encola detrás del de primer plano que ya esperaba. La afirmación de orden fue **retirada** del comentario y del mensaje del commit.
- El trueque contra el chat no estaba declarado (ver arriba).
- Una prueba nueva **podía colgarse en vez de fallar**: el sondeo que esperaba el registro del esperador no tenía cota, y `pytest-timeout` **no está instalado** en este venv. El revisor lo midió como `HANG > 90 s` bajo la mutación que deja de contar esperadores. Todas las esperas pasan ahora por un ayudante con plazo que llama `pytest.fail`; re-medido bajo la misma mutación: **falla en 4,3 s**.

Las tres mutaciones que habían sobrevivido a la revisión **ahora caen**:

| Mutante | Antes | Ahora |
|---|---|---|
| M8 · sobre-decremento en la guarda nueva (`-1` a `-2`) | SOBREVIVIÓ | **CAUGHT** |
| M17 · borrar el chequeo del contador del bucle de espera | SOBREVIVIÓ | **CAUGHT** |
| M10 · el enlace del riel apuntando a `/cmh` | SOBREVIVIÓ | **CAUGHT** |

M17 era el que más importaba: **el mecanismo que esta serie arregla podía borrarse con todas las pruebas en verde.**

### Hallazgo abierto, no corregido a propósito

El revisor midió una **inversión de prioridad que sobrevive a esta serie**: `llm_core.py:123` deja el contador en 0 mientras un llamador de primer plano todavía genera, así que una tarea programada que sondee en esa ventana puede tomar el candado antes que un llamador de primer plano que llegue después, y no es cancelada porque `_LOCAL_MODEL_CURRENT` todavía informa el `workload` de primer plano anterior. Traza del revisor:

```
A(fg step) holds slot
counter while A holds = 0
CURRENT workload seen by a newcomer = foreground
A(fg step) released
>>> C(bg task) GOT the slot
>>> B(fg chat) GOT the slot
```

Es **preexistente**, pero esta serie convierte su ventana en la normal, porque al hacer primer plano al paso de flujo el contador queda en 0 durante toda la generación. Va en su propio commit con su propia prueba; no la tapa esta.

### Pila local: LM Studio medido, Ollama caído

- **Ollama (`:11434`) no responde.** Los **dos** endpoints locales de la base (`c6a553e7` y el duplicado `2345ab42`) apuntan ahí. El duplicado sigue con `supports_tools` vacío y **no se borró**: es un borrado y necesita autorización del usuario.
- **LM Studio (`:1234`) está corriendo** y ningún endpoint lo apunta.
- **Crash al cargar, causa raíz:** el runtime seleccionado es `llama.cpp-win-x86_64-vulkan-avx2@2.46.0` e intenta offload completo de **5,89 GiB** (`lms load --estimate-only`) sobre una iGPU Intel de **2,0 GB**. `exitCode=3221226505` = `0xC0000409`, *stack buffer overrun*. Reproducible 2 de 2. **Se resuelve con `--gpu 0.3` a `0.6`.**
- **Velocidades medidas** (`google/gemma-4-e4b`, 7,5B / 6,33 GB, ctx 8192): CPU puro **1,68 tok/s**; `--gpu 0.3` **4,16**; `--gpu 0.6` **4,24**. Meseta en ~4,2 tok/s — el cuello es ancho de banda de memoria compartida del chip de 15W, no cómputo. Referencia del punto 4: Ollama `qwen3:8b` daba 2,7.
- **Tool calling: PASA.** `finish_reason: tool_calls` con estructura nativa correcta y argumentos bien formados. `deepseek-r1:7b` fallaba justo ahí.
- **Trampa al integrarlo:** si el endpoint pide el modelo y no hay nada cargado, LM Studio lo carga **con los ajustes por defecto, los que crashean**. Hay que fijar el offload como preferencia del modelo en la GUI. El endpoint necesita `supports_tools=1` o no se envían esquemas.
- **No hecho, bloqueado:** registrar el endpoint de LM Studio en la base. El intento de escritura directa a `data/app.db` fue **denegado por clasificador** (modificar sistema en producción). Copia previa hecha: `data/backups/app-before-lmstudio-endpoint-20260927.db`, 802 816 bytes, `integrity_check=ok`. Debe hacerse por Settings → Model Endpoints, que además es la vía correcta.
- **«Bionic» es un producto de LM Studio**, no BionicGPT: app Electron aparte, agente sobre el mismo runtime, con «Secure Cloud» (modelos abiertos frontier, retención cero). **No se pudo confirmar que exponga API para terceros**, así que como proveedor de modelos para Odysseus queda sin verificar; como aplicación es un par del Agentic OS, no un acelerador.

### Implicancia para la mezcla de modelos

A 4,2 tok/s una cadena de 5 pasos generando unos 5 500 tokens tarda **~22 minutos solo en generación**; la misma cadena en la nube tarda ~2 minutos. Además el contexto cargado fue 8 192 tokens y las dependencias de un flujo se truncan en 40 000 caracteres (~10 000 tokens), así que **un artefacto real no entra**. Los pasos tardíos (revisor, documentador), que son los que más dependencias acumulan, son los peores candidatos para local. Criterio registrado: local **solo** en `verificador` —entrada acotada, salida corta, conteos mecánicos— y nunca en `constructor` ni `revisor`, y solo después de que una corrida local supere la guardia `require_tool_evidence`.

### Incidencias

- Se corrió pytest, así que `core.database.init_db()` volvió a tocar la base activa. Esta vez **la copia se hizo antes**, no después.
- La interfaz `/cmh/os` **sigue sin revisión de contenido con datos propios**, y el piloto y sus agentes **siguen pausados**. Nada en este punto los aprueba. `cmh_workflow_definitions` sigue en **0** y `cmh_agents` en **1**, con el único agente en `paused`: con un solo agente **no se puede crear ningún flujo**, porque `verificador` y `revisor` deben usar un agente distinto del `constructor` (`independent_of`, validado en servidor). Eso, y no un defecto, es lo que produce el mensaje «No hay flujos definidos» en `/cmh/os` a Nueva ejecución.
- **La barra izquierda de Odysseus no está fallando.** El riel es un gestor de ventanas flotantes: `modalManager.js` documenta «closed → open, minimized → restore, open → minimize», con acople (`modalSnap.js`), mosaico (`tileManager.js`) y orden de apilado (`toolWindowZOrder.js`). La única ventana real del navegador en todo el código es `codeRunner.js:363`, que no es un botón del riel.

### Cierre del hallazgo abierto y segunda revisión (2026-09-28)

Dos commits más sobre los tres del punto 9: **`27754585`** (`Stop background work queueing while a foreground caller generates`) y **`f17af6aa`** (`Bound the module's own waits and correct what defers a scheduled task`). HEAD queda **5 commits** por delante de `origin/dev`, sin push.

**La inversión que el punto 9 dejó abierta está cerrada.** Reproducida primero de forma independiente, sin fiarse de la traza del revisor: con solo `/cmh/os` abierto —que no manda latido, así que `has_foreground_activity()` es falso y el contador es lo único que frena al fondo— el orden medido era `['C(bg task)', 'B(fg chat)']`. Un llamador de primer plano gasta su cuenta al adquirir, así que durante toda su generación el contador marca 0. El bucle de espera de la rama de fondo cede ahora también mientras un primer plano **tiene** el candado. Después del arreglo: `['B(fg chat)', 'C(bg task)']`, y el de fondo **ni siquiera entra a la cola**.

**La cláusula del contador es defensa, no garantía de orden.** Al correr mutaciones apareció que la cláusula nueva volvía superviviente a M17. Medido en la única ventana donde la vieja es el único guardia (candado libre, primer plano contado pero sin reanudar de `acquire()`, `CURRENT` vacío): el orden es `['fg','bg']` **con y sin** la cláusula, porque `asyncio.Lock` es FIFO. Lo único observable es si el llamador de fondo entra o no en la cola: **1 esperador contra 2**. Eso es lo que fija la prueba, y con eso M17 quedó cerrado de verdad. El revisor lo confirmó con 8+8 ensayos, 16 de 16 consistentes.

**Segunda revisión independiente, sobre `27754585`: veredicto DEVUELTO** — 0 críticos, 2 importantes, 2 menores, con 18 mutantes propios de los que 6 sobrevivieron y **3 se colgaron**. Confirmó el arreglo cargando ambos commits como módulos separados y reconstruyendo el escenario, y fuzzeó el candado **2 882 253 muestras en 40 rondas con 0 violaciones** del invariante «`CURRENT` poblado ⟹ candado tomado». No halló `CURRENT` obsoleto alcanzable, ni interbloqueo, ni inanición indefinida.

Los dos importantes, ambos sobre afirmaciones y cobertura, no sobre el arreglo:

1. **El módulo de prueba afirmaba en falso su propio invariante.** Su cabecera dice «Every wait in this module is bounded» y dos `gather` escritos en la ronda anterior no lo estaban. Tres mutantes **no daban veredicto**: cláusula del contador que siempre cede, no limpiar nunca `CURRENT`, y `CURRENT` registrando `task=None`. El del medio es justo la regresión que la cláusula nueva vuelve catastrófica —antes de `27754585` un `CURRENT` viejo era inocuo para la rama de fondo; ahora la hace ceder para siempre— y `pytest-timeout` **no está instalado** en este venv. Acotadas las dos esperas; re-medido: los tres **fallan en ~30 s** en vez de colgarse más allá de 600.
2. **«La ruta de cancelación del planificador ya aterriza limpio» no aplica donde se ofreció.** Verificado en el código: `_cancel_if_foreground_active` (`task_scheduler.py:916-934`) solo dispara con `has_foreground_activity()` en cierto, y el caso para el que existe esta serie es el contrario. La tarea diferida gira en `llm_core.py:124` con su `TaskRun.status = "running"` (`:889`) y el único permiso de `_run_semaphore(1)` (`:376`, tomado en `:787`) retenido, así que **toda otra tarea programada espera detrás** mientras dure la cadena. Acotado por la cadena y sin interbloqueo, pero la mitigación invocada no existe en esa ventana. La afirmación fue **retirada** y sustituida por lo medido, en el comentario del código, con `TaskDeferred` nombrado como el arreglo y la razón de no tomarlo aquí: exige elegir un plazo, que es diseño nuevo.

Los dos menores también cerrados, en una sola prueba: un mutante que blanquea `has_foreground_activity()` y otro que convierte el sondeo de 0,25 s en `sleep(0)` dejaban el módulo en verde. El segundo **no es equivalente**: quema un núcleo exactamente mientras la compuerta protege al primer plano. La prueba cuenta sondeos en una ventana fija, así que fija la cláusula y el sueño a la vez.

**Los cinco mutantes que la revisión dejó abiertos ahora caen, ninguno cuelga:**

| Mutante | Antes | Ahora |
|---|---|---|
| M5 · la cláusula del contador siempre cede | COLGABA | **CAUGHT** |
| M9 · nunca limpiar `CURRENT` | COLGABA | **CAUGHT** |
| M18 · `CURRENT` registra `task=None` | COLGABA | **CAUGHT** |
| M4 · cláusula del navegador blanqueada | SOBREVIVÍA | **CAUGHT** |
| M14 · el sondeo se vuelve bucle ocupado | SOBREVIVÍA | **CAUGHT** |

**Pruebas:** 1 022 aprobadas, 9 omitidas en los 74 módulos que tocan `llm_core`; el módulo del candado 11 de 11. La única fallida sigue siendo la ambiental del puerto 1234, que el revisor volvió a confirmar con `netstat` (PID 24716 escuchando).

**Queda abierto, registrado en `06_pendientes_abiertos.md`:** la tarea diferida que retiene el semáforo con su corrida en `running`, y la inversión residual con **dos** llamadores de fondo concurrentes —cuando `bg1` tiene el candado, `CURRENT` vale `"background"` y ninguna cláusula frena a `bg2`; el primer plano que llega cancela a `bg1` pero queda detrás de `bg2`—. Medida por el revisor, idéntica antes y después: `['bg1-in', 'bg1-cancelled', 'bg2', 'FG']`. Preexistente; cerrarla depende de si hay dos productores de fondo concurrentes en la práctica, que es decisión de operación.
