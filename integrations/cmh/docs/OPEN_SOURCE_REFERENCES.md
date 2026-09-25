# Referencias open source consultadas

Fecha de consulta: **2026-09-24**. Licencias verificadas leyendo el archivo
`LICENSE` de la rama por defecto de cada repositorio, o la documentación oficial
cuando no había archivo. Uso: **inspiración conceptual de patrones de interfaz**.
No se copió ni se descargó código, CSS, iconos ni diseños de ninguno.
«NO VERIFICADO» = no se pudo comprobar; no se asume.

| Nombre | URL | Licencia verificada | Elementos tomados como inspiración | Riesgos de compatibilidad |
|---|---|---|---|---|
| Langfuse | https://github.com/langfuse/langfuse | MIT, salvo `ee/`, `web/src/ee/`, `worker/src/ee/` (Langfuse Enterprise License) | Árbol de traza con cascada de tiempos y costo por span; puntajes pegados a cada traza | `ee/` propietaria: no tocar |
| Arize Phoenix | https://github.com/Arize-ai/phoenix | Elastic License 2.0 (no OSI) + aviso de patentes (IP_NOTICE) | Tipos de span (LLM, herramienta, recuperación) diferenciados | No OSI y patentes: solo idea general |
| Flowise | https://github.com/FlowiseAI/Flowise | Apache-2.0, salvo `packages/server/src/enterprise` (comercial) | Panel de chat de prueba junto al lienzo del flujo | Carpeta enterprise comercial |
| Langflow | https://github.com/langflow-ai/langflow | MIT | Inspección de la salida de cada nodo al seleccionarlo | Bajo |
| n8n | https://github.com/n8n-io/n8n | Sustainable Use License v1.0 (source-available, no OSI); archivos `.ee.` enterprise | Historial de ejecuciones con estado por nodo y re-ejecución | No reutilizar código |
| Dify | https://github.com/langgenius/dify | Apache-2.0 modificada (sin multi-tenant sin permiso; conservar logo en `web/`); declara patente de apariencia | Solo el concepto genérico de registro de ejecución nodo por nodo | **Riesgo alto**: se evitó deliberadamente parecerse a su editor |
| AutoGen Studio | https://github.com/microsoft/autogen | MIT (`LICENSE-CODE`) | Mensajes de cada agente separados en la vista en vivo | Proyecto en mantenimiento; no apto para producción según su README |
| CrewAI | https://github.com/crewAIInc/crewAI | MIT (núcleo). Crew Studio: NO VERIFICADO (producto enterprise) | Tarjetas de agente con rol y objetivo visibles | Studio comercial: no usado |
| OpenHands | https://github.com/OpenHands/OpenHands | MIT | Flujo de acciones del agente con observaciones expandibles; pausa y reanudación | Bajo |
| MCP Inspector | https://github.com/modelcontextprotocol/inspector | Apache-2.0 (código nuevo) + MIT (aportes antiguos) + CC-BY-4.0 (docs) | Estado de conexión por servidor y transporte (stdio/SSE/HTTP); herramientas por servidor | Bajo |
| LangGraph | https://github.com/langchain-ai/langgraph | MIT (librería). LangGraph Studio: NO VERIFICADO (parte de LangSmith, comercial) | Interrupciones human-in-the-loop antes de continuar un paso | Studio cerrado: solo concepto |
| Open WebUI | https://github.com/open-webui/open-webui | BSD-3-Clause con cláusula de marca | Selector de modelo en el chat | Cláusula de marca: no reutilizar código |
| LibreChat | https://github.com/danny-avila/LibreChat | MIT | Asignación de herramientas y MCP por agente | Bajo |
| React Flow / xyflow | https://github.com/xyflow/xyflow | MIT (núcleo); ejemplos «Pro» por suscripción | Aristas animadas para flujos activos; color por estado del nodo | Se descartó como dependencia porque exige React (ADR-002) |
| Temporal UI | https://github.com/temporalio/ui | MIT | Historial de eventos del workflow en línea de tiempo; reintentos visibles | Bajo |
| Prefect | https://github.com/PrefectHQ/prefect | Apache-2.0 (raíz); licencia específica de la UI NO VERIFICADO | Vista tipo Gantt de tareas de una ejecución | Asumida la de la raíz, no usada como código |
| Dagster | https://github.com/dagster-io/dagster | Apache-2.0 (raíz); `js_modules/dagster-ui` NO VERIFICADO | Grafo de dependencias con estado de cada nodo | Ídem |

## Guías de experiencia consultadas

| Guía | URL | Qué se aplicó |
|---|---|---|
| Microsoft HAX — Guidelines for Human-AI Interaction | https://www.microsoft.com/en-us/haxtoolkit/library/ | G1-2 (qué puede hacer cada agente: capacidades y permisos visibles), G11 (por qué: evidencia y artefactos por paso), G16 (consecuencias de la acción en la tarjeta de aprobación), G17 (control global: pausar y detener) |
| Google PAIR — People + AI Guidebook | https://pair.withgoogle.com/chapter/explainability-trust/ | Calibrar confianza: riesgo en categorías alto/medio/bajo con la acción a seguir; fuentes visibles de cada dato |
| NN/g — «AI Agents as Users» (Gibbons y Moran, 10-abr-2026) | https://www.nngroup.com/articles/ai-agents-as-users/ | No eliminar la fricción de control en dominios regulados: confirmaciones y justificación se mantienen; HTML semántico |
| NN/g — «A Concrete Definition of an AI Agent» (Sponheim, 3-abr-2026) | https://www.nngroup.com/articles/definition-ai-agent/ | Ciclo acción → evaluación → decisión, representado como Plan → Ejecutar → Observar → Reflexionar |
