# Investigación — Interfaz Agentic OS CMH

Fecha: 2026-09-24.

## 1. Qué es un Agentic OS en este proyecto

Una capa de control sobre agentes de IA que **planifican, ejecutan
herramientas, observan resultados y reflexionan** dentro de límites explícitos,
coordinados por un supervisor, con memoria persistente y con personas que
aprueban lo que tiene consecuencias. En CMH hay un principio previo que manda
sobre la estética: **los agentes no conversan, dejan rastro** (plan del
ecosistema, §2). Cada paso produce un artefacto persistente; el revisor recibe
el entregable y la verificación, nunca el razonamiento del constructor.

Consecuencia para la interfaz: el objeto central no es una conversación sino
una **ejecución** con pasos, artefactos, eventos, costos y aprobaciones. El chat
es un atajo de operación, no el lugar donde ocurre el trabajo.

## 2. Cómo representarlo visualmente

| Concepto | Representación elegida | Por qué |
|---|---|---|
| Coordinador y trabajadores | Núcleo central con agentes alrededor (imagen de referencia), conectado a un grafo de dependencias del flujo | La imagen del usuario muestra un núcleo coordinador con agentes en paneles; el DAG real del backend exige mostrar dependencias |
| Movimiento | Solo por eventos reales (o simulados con el mismo contrato): pulso, órbita de herramienta, partícula de artefacto | «Movimiento real»: el movimiento informa, no decora |
| Ciclo del agente | Anillo Plan → Ejecutar → Observar → Reflexionar con la fase activa marcada | NN/g: ciclo acción → evaluación → decisión |
| Estado | Color **más** etiqueta **más** glifo (● ▲ ■ ○) | Regla CMH de semáforo; daltonismo e impresión en B/N |
| Confianza y riesgo | Riesgo alto/medio/bajo con acción sugerida | PAIR: calibrar confianza |
| Aprobación | Tarjeta con agente, acción, argumentos, impacto, riesgo y justificación obligatoria si el riesgo es alto | HAX G16; NN/g: la fricción de control se mantiene |
| Trazas | Cascada de spans con duración y tokens | Patrón común (Langfuse, Temporal, Prefect) |
| Procedencia | Insignia «Real» / «Demo» en cada panel y franja global en modo demo | Honestidad de medición (CLAUDE.md) |

## 3. Hallazgos del repositorio que condicionan el diseño

1. **Sin Node/npm**: se descarta todo stack que requiera empaquetador (ADR-002).
2. **CSP estricta**: nada de CDN; todo propio y del mismo origen.
3. **El backend ya emite los eventos necesarios** para animar agentes reales:
   `step_started`, `tool_started`, `tool_finished` (con duración y error),
   `model_metrics` (tokens de entrada/salida, tiempo), `step_completed` (con
   duración), `step_approval_requested`, `run_*`.
4. **Límites reales**: los flujos solo admiten herramientas de lectura
   (`read_file`, `ls`, `grep`, `glob`), `max_steps=12` fijo, hasta 2 pasos en
   paralelo, sin presupuesto ni timeout configurables por ejecución. La interfaz
   no finge controles que el backend no aplica: en modo real se muestran como
   «No soportado por el backend».
5. **Rechazo de paso**: no existe endpoint; «Rechazar» un paso equivale a
   detener la ejecución, y la interfaz lo dice antes de confirmar.
6. **Secretos**: `/api/mcp/servers` devuelve `env`; se filtra en la capa de
   servicios (ADR-011).
7. **Autenticación**: `/api/cmh/*` exige sesión admin. Sin sesión → modo demo.

## 4. Fuentes

Proyectos y guías, con licencias verificadas: [OPEN_SOURCE_REFERENCES.md](OPEN_SOURCE_REFERENCES.md).
Atribuciones: [LICENSES_AND_ATTRIBUTIONS.md](LICENSES_AND_ATTRIBUTIONS.md).

## 5. Qué no se hizo y por qué

- No se descargó ningún repositorio ni paquete.
- No se tomó ningún componente de Dify, n8n, Phoenix ni Open WebUI (riesgo de
  licencia o de marca).
- No se generaron imágenes de operación minera: la identidad CMH lo prohíbe
  (riesgo de EPP o sostenimiento inverosímil ante Seguridad).
