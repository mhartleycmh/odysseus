# Agentic OS CMH — interfaz web (`/cmh/os`)

Interfaz para ver y operar agentes, ejecuciones, orquestación en vivo,
aprobaciones humanas, memoria, herramientas, observabilidad, evaluaciones,
seguridad y configuración. Vive dentro de Odysseus y usa su backend
(`/api/cmh/*`). Sin sesión, Odysseus redirige a `/login`; con una sesión que no
es de administrador, o si el modo demo está forzado, muestra datos de
demostración claramente etiquetados.

## Ejecutar

No hay instalación ni paso de build: los archivos de `static/cmh-os/` se
sirven tal como están.

**Con el servidor de Odysseus (datos reales):**

1. Arranca Odysseus como siempre (`python app.py` o el servicio instalado).
2. Inicia sesión como administrador.
3. Abre `http://<host>:<puerto>/cmh/os`.

**Vista previa sin backend (modo demo) o con API falsa:**

```bash
bash scripts/cmh_os/node.sh scripts/cmh_os/serve.mjs --port 8765          # demo
bash scripts/cmh_os/node.sh scripts/cmh_os/serve.mjs --port 8765 --api    # API falsa con el contrato real
# abrir http://127.0.0.1:8765/cmh/os
```

`node.sh` usa `node` del PATH si existe y, si no, el Node 24 que trae VS Code.

Parámetros útiles en la dirección: `?modo=demo` fuerza la demo;
`?velocidad=rapida` acelera las ejecuciones simuladas.

## Variables de entorno

| Variable | Valores | Por defecto | Efecto |
|---|---|---|---|
| `CMH_OS_UI_ENABLED` | `true` / `false` | `true` | Habilita la ruta `/cmh/os` (404 si es `false`) |
| `CMH_OS_DEFAULT_MODE` | `auto` / `demo` | `auto` | `demo` fuerza datos de demostración para todos |

Ninguna es secreta; ambas se exponen en `GET /api/cmh/os/config`. Ver
`.env.example`.

## Verificar

```bash
bash scripts/cmh_os/check.sh              # tipos, lint, build, unitarias y end-to-end
bash scripts/cmh_os/check.sh --screens    # además guarda capturas en data/cmh-os-screens/
../../.venv/Scripts/python.exe -m pytest tests/test_cmh_os_routes.py -q -p no:cacheprovider
```

Requisitos para el end-to-end: Microsoft Edge o Chrome instalado (o
`CMH_OS_BROWSER=<ruta>`).

## Documentos

| Documento | Contenido |
|---|---|
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | Estado real de cada tarea, pruebas y resultados |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Módulos, contratos, flujos y diagramas |
| [DECISIONS.md](DECISIONS.md) | Decisiones (ADR) |
| [UI_UX_SPECIFICATION.md](UI_UX_SPECIFICATION.md) | Design system, páginas, accesibilidad |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Plan, tareas y criterios de aceptación |
| [TEST_PLAN.md](TEST_PLAN.md) | Niveles de prueba y flujos obligatorios |
| [RESEARCH.md](RESEARCH.md) · [OPEN_SOURCE_REFERENCES.md](OPEN_SOURCE_REFERENCES.md) · [LICENSES_AND_ATTRIBUTIONS.md](LICENSES_AND_ATTRIBUTIONS.md) | Investigación y licencias |
