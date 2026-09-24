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

## Punto limpio 3: flujos, eventos y propuestas de memoria (2026-09-24, sin commit)

- Estado Git: rama `dev`, base `5b844b4f`, **cambios sin commit** (pendiente de autorización del usuario). Archivos nuevos: `src/cmh_workflows.py`, `routes/cmh_workflow_routes.py`, `routes/cmh_memory_routes.py` y 4 módulos de prueba `tests/test_cmh_*`; modificados `app.py`, `core/database.py`, `src/agent_loop.py`, `src/task_scheduler.py`, `routes/cmh_control_routes.py`, `static/cmh-control.*`.
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

## Próxima acción exacta

1. Con autorización del usuario, commit local de este punto limpio (sin push).
2. Copia de seguridad de `data/app.db` y reinicio del servidor para crear las tablas nuevas; verificar `/cmh` en Edge.
3. Cuando la clave de Anthropic esté corregida en Settings → Model Endpoints: repetir el caso sintético del piloto (herramienta por herramienta y escapes bloqueados) y luego un flujo sintético de cinco pasos con dos proveedores (verificar también OpenAI). Registrar los IDs de ejecución. El piloto sigue pausado hasta aprobarlo.
