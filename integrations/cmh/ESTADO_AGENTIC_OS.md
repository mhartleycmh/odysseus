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

## Próxima acción exacta

Resolver la conectividad de Anthropic, repetir un caso sintético y registrar herramienta por herramienta y escapes bloqueados, sin tomar el run fallido como aprobación. Mantener el piloto pausado hasta aprobarlo. Después implementar flujos persistentes de cinco pasos con dos modelos, eventos SSE recuperables y propuestas de memoria con vista previa, aprobación, escritura atómica y recuperación.
