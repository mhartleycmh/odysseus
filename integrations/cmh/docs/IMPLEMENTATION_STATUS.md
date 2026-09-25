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

- **No verificado contra un Odysseus real con sesión de administrador.** El modo real se probó con la API falsa, que tiene el mismo contrato de claves y está comprobada por pytest contra los manejadores reales. Hace falta abrir `/cmh/os` en Edge con sesión.
- `/static/cmh-os/*` es público porque Odysseus exime `/static` de autenticación (ADR-016). No expone datos.
- El presupuesto de build está al 94 % (140,7 de 150 KB gzip). La próxima vista grande obliga a dividir `es.js` por módulo o a cargar vistas bajo demanda.
- Demo: en las ejecuciones creadas en vivo, las duraciones de herramientas (tiempo simulado) pueden superar la del paso (tiempo real) en la cascada.
- Límites de iteraciones, tiempo y presupuesto, y prioridad: solo se aplican en demo. El backend usa `max_steps=12` por paso y no guarda la prioridad.
- El rechazo de paso en modo real detiene la ejecución; no hay rechazo nativo. Las justificaciones viven en la auditoría local del navegador.
- Evaluaciones, roles y sesiones: sin backend; se sirven desde la demo con la etiqueta «Demo · sin backend».
- ESLint no está disponible sin npm; lo sustituyen `lint.mjs` y TypeScript estricto.

## 6. Siguiente bloque

1. El usuario abre `/cmh/os` en Edge con sesión de administrador y revisa el modo real con agentes y ejecuciones verdaderos.
2. Hecho: commit `bba01a65`.
3. Backend: endpoint de rechazo de paso y persistencia de justificaciones; límites por ejecución; `static/cmh-os` fuera de la exención de autenticación.
