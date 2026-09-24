# Revisión de apoyo para VS Code — 2026-09-23

## Continuación: workspace de tareas implementado y validado

Se completó la implementación encontrada en el checkout: persistencia y migración
del campo `workspace`, API de creación/actualización y propagación al agente.
Se añadió validación compartida (`src/task_workspace.py`) para restringir la
asignación a administradores/modo monousuario y tareas LLM. Al ejecutar se
comprueban permisos, existencia y destino canónico; un fallo detiene la tarea
sin llamada alternativa al modelo. Los check-ins con workspace pasan por el
agente normal en lugar de consultar integraciones directamente.

Validación conjunta: **134 passed, 10 skipped, 1 warning**. Cubre API, persistencia,
permisos, eliminación/redirección del workspace, ausencia de fallback, migración,
entrega a sesiones, cancelación y aislamiento de rutas.
Además pasaron dos comprobaciones de migración: esquema existente y reconstrucción
de tabla antigua, con conservación de datos y ejecución repetible.

Pendientes para el piloto real: lista de herramientas efectivamente restringida,
regla de no sobrescritura, ejecución sintética con proveedor y registro de su ID.
La revocación de sesiones tras recuperar contraseña también sigue pendiente.
No se reinició el servidor ni se ejecutaron tareas con un proveedor. El texto
siguiente es histórico y no reemplaza esta actualización.

## Actualización: correcciones aplicadas directamente

Tras la solicitud del usuario de intervenir directamente, se corrigieron:

- La detección de rutas sensibles con separadores normales, invertidos o mezclados en Windows (`src/tool_execution.py`).
- El directorio temporal permitido en Windows, usando `tempfile.gettempdir()`; POSIX conserva `/tmp` y su resolución canónica.
- La serialización JSON de rutas en las pruebas de aislamiento, usando `json.dumps` para escapar correctamente las barras invertidas.
- Se añadieron regresiones para separadores Windows en el helper y en el resolutor de workspace; también una prueba específica de semántica POSIX, omitida al ejecutar en Windows.

Validación final de los tres archivos indicados más abajo: **110 passed, 10 skipped, 1 warning** (21,53 segundos). `git diff --check` no detectó errores de espacios. No se ejecutó la suite completa ni se reinició el servidor.

Los hallazgos de propagación del workspace en tareas programadas y revocación de sesiones siguen pendientes. Las secciones siguientes conservan el diagnóstico inicial como antecedente; el fallo Windows descrito en el punto 2 ya está corregido.

## Alcance y estado comprobado

Revisión del checkout local solicitada por el usuario para apoyar al modelo de VS Code. No se recibió todavía su tarea concreta. Este documento deja evidencia y próximos pasos; no acredita una ejecución del piloto.

- `GET http://127.0.0.1:7000/health`: HTTP 200. Esto no valida autenticación, proveedores ni una tarea completa.
- HEAD observado: `3b6c1691`.
- Cambios preexistentes: `SECURITY.md`, `integrations/cmh/` y `scripts/reset_admin_password.py`.
- Existen `data/agent_workspace/cmh-researcher/{input,working,output}`.
- `integrations/cmh/README.md` marca como siguiente paso provisionar el piloto y registrar una ejecución. No se consultó la base de tareas autenticada; no se comprobó si ya está provisionado.
- Esta revisión añade únicamente este documento; no modifica código ni credenciales.

## Hallazgos para continuar

### 1. Comprobar propagación del workspace en tareas programadas

`src/tool_execution.py::_resolve_tool_path` utiliza el workspace activo cuando existe. Sin él, recurre a raíces generales, que incluyen el workspace compartido y otros directorios de contenido permitidos.

En la llamada a `stream_agent_loop` de `src/task_scheduler.py` alrededor de la línea 1918 no se pasa `workspace`. La firma de `stream_agent_loop` en `src/agent_loop.py` lo declara opcional con valor `None`. `TaskCreate`, en `routes/task/task_routes.py`, tampoco expone ese campo.

Consecuencia: el prompt `researcher.md` por sí solo no demuestra aislamiento técnico al subdirectorio `cmh-researcher`. Antes de ejecutar el piloto con herramientas de archivos, verificar la ruta real de ejecución y cómo se liga el workspace al agente/tarea. Reutilizar el aislamiento existente y comprobar que el contexto llega a todas las invocaciones de herramientas, incluidas las tareas en segundo plano.

El scheduler sí contempla una lista de herramientas habilitadas del crew (`crew.enabled_tools`, alrededor de la línea 1611). Verificar que el piloto realmente usa ese crew y que se aplican las prohibiciones declaradas. La prohibición de sobrescribir archivos también requiere validación específica; el confinamiento de rutas no la demuestra.

### 2. Fallo reproducido en pruebas sobre Windows

Intérprete funcional: la `.venv` de la carpeta Claude, dos niveles por encima del repositorio. El Python global no tiene pytest.

```powershell
& '../../.venv/Scripts/python.exe' -m pytest tests/test_workspace_confine.py tests/test_tool_path_confinement.py tests/test_agent_state_dir_confinement.py -q --disable-warnings --maxfail=1
```

Resultado fuera del sandbox, tras autorización: **25 passed, 1 failed, 1 warning**. Se detuvo en el primer fallo; no se completaron los tres archivos.

Fallo: `tests/test_tool_path_confinement.py::test_sensitive_ssh_dir`. La llamada directa `_is_sensitive_path('/home/user/.ssh/authorized_keys')` devuelve False. El helper divide con `os.sep`, que en Windows es una barra invertida, mientras esta prueba pasa barras normales.

Revisar el contrato del helper y la portabilidad del test. Los resolutores llaman a `realpath` antes de ese helper, por lo que este fallo unitario no basta para afirmar que exista una evasión en la ruta de producción. Validar rutas Windows con ambos separadores a través del resolutor antes de decidir el arreglo.

El primer intento dentro del sandbox falló por permisos al escribir un temporal; ese resultado era ambiental, distinto del fallo anterior.

### 3. Recuperación de contraseña y sesiones persistidas

El script nuevo `scripts/reset_admin_password.py` sustituye el hash en `auth.json`; no revoca sesiones. `core/auth.py::_load_sessions` vuelve a cargar sesiones no vencidas desde `sessions.json` al reiniciar. Por tanto, reiniciar después de usar el script no invalida por sí mismo sesiones existentes.

Definir si la recuperación debe cerrar las sesiones del usuario afectado y, si corresponde, implementar revocación selectiva con el servicio detenido o mediante un mecanismo coordinado. Probar con archivos temporales y dos usuarios, conservando las sesiones del usuario no afectado. No se ejecutó el script ni se leyeron archivos de autenticación.

## Siguiente entrega sugerida

1. Confirmar con el trabajo en curso de VS Code cuál de estos puntos está dentro de su tarea.
2. Resolver o justificar el fallo Windows con una prueba de la ruta real.
3. Demostrar workspace y herramientas restringidas en la ruta elegida para el piloto.
4. Ejecutar una tarea de prueba con entradas sintéticas y registrar ID, resultado y evidencia de aislamiento antes de ampliar acceso.

Los proveedores y su configuración no se verificaron en esta revisión. No se efectuaron llamadas a modelos, creación de tareas ni cambios del servidor.
