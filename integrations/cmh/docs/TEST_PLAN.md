# Plan de pruebas — Interfaz Agentic OS CMH

Todas las pruebas corren sin instalar dependencias (ADR-009). Un solo comando:

```bash
bash scripts/cmh_os/check.sh          # typecheck, lint, build, unitarias, e2e
../../.venv/Scripts/python.exe -m pytest tests/test_cmh_os_routes.py -q -p no:cacheprovider
```

## 1. Niveles

| Nivel | Herramienta | Ubicación | Qué cubre |
|---|---|---|---|
| Tipos | TypeScript 6.0.3 `checkJs strict` | `scripts/cmh_os/typecheck.mjs` | Todo `static/cmh-os/js` |
| Lint | Reglas propias | `scripts/cmh_os/lint.mjs` | HTML inseguro, `eval`, secretos, `console.log`, TODO/FIXME, `any` en JSDoc, `fetch` fuera de `http.js`, colores fuera de `tokens.css`, `localStorage` fuera de `storage.js` |
| Build | Grafo de módulos | `scripts/cmh_os/build.mjs` | Importaciones resueltas, huérfanos, recursos, presupuesto 150 KB gzip sobre lo que la página carga |
| Unitarias | `node --test` | `tests/cmh_os/unit/*.test.mjs` | router, validate, format, i18n, http, live (mapeo y secretos), demo, simulator, chat, contraste de tokens, grafo (layout) |
| Componentes | Edge + CDP | `tests/cmh_os/e2e/run.mjs` (sección «Componentes») | h(), table (orden y teclado), modal (foco, Esc, justificación), states (error y reintento) |
| Integración | Edge + CDP + API falsa | `tests/cmh_os/e2e/run.mjs` (modo real) | `LiveSource` contra una API HTTP que reproduce las fijaciones del backend real, incluido SSE |
| Contrato | pytest | `tests/test_cmh_os_routes.py` | Claves de las respuestas reales de `/api/cmh/*` = fijaciones JSON de la API falsa |
| End-to-end | Edge + CDP | `tests/cmh_os/e2e/run.mjs` | 10 flujos obligatorios, chat, 15 rutas, 3 anchos, a11y básica, foco, movimiento reducido, fugas de streams |

## 2. Flujos obligatorios (e2e)

| # | Flujo | Aserciones |
|---|---|---|
| F1 | Navegar por los módulos principales | 12 módulos desde el menú y la página 404; `h1` correcto; `aria-current="page"`; sin errores de consola |
| F2 | Crear y editar un agente | formulario vacío → errores; válido → aparece en la tabla; editar → versión de instrucciones +1 |
| F3 | Iniciar una ejecución simulada | formulario con límites; estado pasa a «En curso» y el grafo recibe eventos |
| F4 | Consultar pasos de una ejecución | detalle con pasos, herramientas, eventos y respuesta final al terminar |
| F5 | Revisar una solicitud de aprobación | la ejecución llega a `waiting_approval`; la cola la muestra con riesgo e impacto |
| F6 | Aprobar o rechazar | rechazo sin justificación → error; con justificación → historial auditable |
| F7 | Buscar un registro de memoria | búsqueda filtra por texto y tipo; archivar pide confirmación |
| F8 | Filtros en observabilidad | filtro por estado/agente reduce las filas; cascada de la ejecución |
| F9 | Cambiar configuración sin exponer secretos | cambiar tema/límites persiste; el DOM no contiene ninguna clave; claves enmascaradas |
| F10 | Recuperarse de errores simulados | activar «Simular fallos» → vista en error → «Reintentar» → vista lista |

## 3. Accesibilidad básica (cada ruta)

- Un solo `h1`; `main`, `nav`, `header` presentes; enlace «Ir al contenido».
- Todos los `button`, `a`, `input`, `select`, `textarea` con nombre accesible.
- `img` con `alt`. Ningún `id` duplicado.
- Foco visible (el estilo `:focus-visible` existe y tiene contorno).
- El primer Tab enfoca «Ir al contenido» y Enter lleva el foco a `main`.
- Abrir un detalle con Enter deja el foco en su `h1` (que existe desde el primer instante).

## 4. Responsive

Anchos 390, 820, 1440 px: `document.documentElement.scrollWidth <= innerWidth`
en cada ruta; captura PNG por ruta y ancho en `data/cmh-os-screens/`.

## 5. Registro

Cada ejecución de `check.sh` imprime conteos por nivel. Los resultados reales
se copian a [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) con fecha y
comando; nunca «debería pasar».
