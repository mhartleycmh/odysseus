# Especificación UI/UX — Interfaz Agentic OS CMH

## 1. Principios

1. **Sobrio, sólido, legible** (identidad CMH): informe de directorio, no folleto.
2. **El movimiento informa**: solo se anima lo que ocurre (evento real o simulado).
3. **Procedencia siempre visible**: «Real» o «Demo» en cada panel.
4. **Traducir tecnología a consecuencia**: cada estado dice qué significa para
   la operación («Esperando aprobación: el documentador no empieza hasta que
   alguien apruebe al revisor»).
5. **Control humano con fricción justa**: confirmar lo irreversible, justificar
   lo de riesgo alto; lo reversible no se interrumpe.

## 2. Design system

### Tokens (en `css/tokens.css`)

| Grupo | Tokens | Valor claro | Valor oscuro |
|---|---|---|---|
| Marca | `--cmh-azul`, `--cmh-azul-profundo`, `--cmh-azul-medio`, `--cmh-oro`, `--cmh-oro-texto` | `#002D46`, `#001B2B`, `#17607F`, `#B19A3B`, `#8A7623` | iguales (marca fija) |
| Superficie | `--bg`, `--surface`, `--surface-2`, `--border` | `#F4F6F8`, `#FFFFFF`, `#F4F6F8`, `#E3E7EB` | `#001B2B`, `#062638`, `#0B3148`, `#1D4A63` |
| Texto | `--text`, `--text-muted`, `--text-accent` | `#1F2933`, `#5A6672`, `#002D46` | `#E8EEF2`, `#A9B8C3`, `#D9C87A` |
| Acento | `--accent` (gráfico), `--accent-text` | `#B19A3B`, `#8A7623` | `#B19A3B`, `#D9C87A` |
| Estado | `--ok`, `--warn`, `--risk`, `--idle` + `-bg` | `#2E7D4F/#E8F2EC`, `#9A5C00/#FBF1E3`, `#B3261E/#FBEAE8`, `#6B7681/#F4F6F8` | `#6CC795/#123A2A`, `#F0B35A/#3A2A10`, `#F28B82/#3D1714`, `#A9B8C3/#15303F` |
| Info/activo | `--live` | `#17607F` | `#7FA6BA` |
| Espaciado | `--sp-1..6` | 4, 8, 12, 16, 24, 32 px | — |
| Radio | `--radius`, `--radius-lg` | 4 px, 8 px | — |
| Sombra | `--shadow-1`, `--shadow-2` | `0 1px 2px rgba(0,45,70,.08)`, `0 8px 24px rgba(0,27,43,.16)` | más densas |
| Tipografía | `--font`, `--font-mono` | `'Aptos','Segoe UI',system-ui,Arial,sans-serif`; `'Cascadia Mono',Consolas,monospace` | — |
| Escala | `--fs-xs..2xl` | 12, 13, 14, 16, 20, 28 px | — |

Reglas duras (verificadas por prueba unitaria de contraste): texto normal
≥ 4.5:1 y texto grande ≥ 3:1 contra su superficie en ambos temas; el oro
`#B19A3B` nunca se usa como texto sobre superficie clara.

### Componentes

| Componente | Archivo | Variantes / estados |
|---|---|---|
| Botón | `components.css` `.btn` | primario, secundario, fantasma, peligro; `:hover`, `:focus-visible` (anillo 2 px `--live`), `:disabled`, `aria-busy` |
| Campo de formulario | `components/form.js` | texto, número, área, selección, casillas; etiqueta visible, ayuda, error en línea con `aria-describedby` e `aria-invalid` |
| Panel | `.panel` | con encabezado, acciones e insignia de procedencia |
| Tabla | `components/table.js` | ordenable por columna (`aria-sort`), fila seleccionable con teclado, vacía |
| KPI | `components/kpi.js` | etiqueta, cifra, meta/contexto, variación con palabra; filete oro a la izquierda |
| Insignia de estado | `components/badge.js` | ok/atención/riesgo/pendiente/en curso; glifo + texto |
| Insignia de procedencia | `badge.js` `originBadge` | Real / Demo / Demo — sin backend |
| Alerta | `.alert` | info, éxito, atención, error; `role="status"` o `alert` |
| Modal | `components/modal.js` | `<dialog>` nativo, foco atrapado, Esc cierra, foco vuelve al disparador |
| Aviso flotante | `components/toast.js` | región `aria-live="polite"` |
| Tooltip | `[data-tip]` + `aria-describedby` | teclado y ratón |
| Esqueleto | `components/states.js` | bloques animados (sin animación con movimiento reducido) |
| Estados de vista | `states.js` `asyncView` | carga, vacío, error con reintento, listo |
| Grafo | `components/graph.js` | SVG accesible (`role="img"` + lista textual equivalente) |
| Línea de tiempo | `components/timeline.js` | eventos de ejecución |
| Gráfico | `components/chart.js` | barras horizontales, línea, cascada; eje desde cero, título = conclusión |
| Panel de chat | `components/chat-panel.js` | acoplado a la derecha (escritorio) o a pantalla completa (móvil) |

### Iconografía

Glifos geométricos Unicode y trazos SVG propios de 1.5 px. Nunca un icono solo:
siempre con texto visible o `aria-label`.

## 3. Marco de la aplicación

- **Encabezado** (franja `--cmh-azul-profundo`): logotipo en caja blanca,
  «Agentic OS» y alcance, indicador de modo (Real/Demo), estado del sistema,
  botón de chat, botón de tema.
- **Navegación lateral** (escritorio ≥ 1024 px): 12 módulos con contador de
  aprobaciones pendientes. En tablet se colapsa a iconos con etiqueta en
  tooltip; en móvil pasa a un menú desplegable.
- **Contenido**: título de la vista = conclusión cuando hay datos; subtítulo
  con la explicación; ayuda contextual «¿Qué es esto?».
- **Pie**: `Fuente: <sistema> · Corte: <hora> · Modo: <real/demo>` (regla CMH).
- **Enlace de salto** «Ir al contenido» como primer elemento enfocable.

## 4. Inventario de páginas

| Ruta | Página | Contenido mínimo |
|---|---|---|
| `#/` | Vista general | 5 KPI (agentes activos, ejecuciones en curso, aprobaciones pendientes, tasa de éxito 7 d, consumo estimado); estado de servicios; alertas; actividad reciente; mini-grafo en vivo |
| `#/agentes` | Centro de agentes | búsqueda, filtros (estado, permisos, proyecto), tabla, crear |
| `#/agentes/:id` | Detalle de agente | capacidades, modelo, herramientas, permisos, instrucciones versionadas, historial; editar, pausar/activar |
| `#/ejecuciones` | Ejecuciones | nueva ejecución (flujo, objetivo, prioridad, agente, presupuesto, iteraciones, timeout), lista filtrable |
| `#/ejecuciones/:id` | Detalle | pasos, herramientas, errores, respuesta final, artefactos, eventos; cancelar, reintentar |
| `#/orquestacion` | Orquestación | núcleo supervisor + trabajadores, dependencias, estado global, ciclo PEOR, selector de ejecución, chat acoplado |
| `#/memoria` | Memoria | pestañas trabajo/episódica/semántica, búsqueda, filtros, metadatos, relevancia, archivar con confirmación |
| `#/herramientas` | Herramientas e integraciones | catálogo, categorías, permisos, estado, uso, servidores MCP, operaciones sensibles |
| `#/aprobaciones` | Aprobaciones humanas | cola, detalle (agente, acción, argumentos, impacto, riesgo), aprobar/rechazar con justificación, historial |
| `#/observabilidad` | Observabilidad | filtros, trazas, cascada, eventos, logs, latencia, tokens, costos, errores, tasa de éxito |
| `#/evaluaciones` | Evaluaciones | casos, datasets, ejecuciones, resultados, comparación contra línea base, historial, vacío |
| `#/seguridad` | Seguridad | roles, permisos, políticas, secretos enmascarados, sesiones, auditoría, riesgo |
| `#/configuracion` | Configuración | proveedores, parámetros, límites, apariencia, idioma, feature flags, variables de entorno |
| `#/ayuda` | Documentación | descripción de cada módulo, leyendas, glosario, enlaces a docs locales |

## 5. Interacciones clave

- **Crear agente**: diálogo con validación en línea; en modo real, las reglas
  del backend (carpeta autorizada, herramientas) se muestran como error del
  campo cuando la API responde 400.
- **Nueva ejecución**: en modo real se elige una definición de flujo existente;
  presupuesto, iteraciones y timeout se muestran deshabilitados con el motivo.
- **Aprobar**: botón primario; **Rechazar**: exige justificación (mín. 10
  caracteres); riesgo alto exige justificación también para aprobar.
- **Detener**: confirmación con consecuencia («Los pasos en curso se
  interrumpen; podrás reanudar»).
- **Chat**: `/` enfoca el chat; `Esc` lo cierra; los comandos sugeridos son
  botones; una acción sensible abre su diálogo, nunca se ejecuta sola.

## 6. Accesibilidad

WCAG 2.2 AA como objetivo: contraste verificado por prueba, navegación completa
con teclado, foco visible, `aria-live` para cambios de estado, formularios con
etiquetas, `prefers-reduced-motion` desactiva partículas y pulsos (el estado se
sigue mostrando por texto), el grafo tiene equivalente textual, objetivos
táctiles ≥ 40 px en móvil.

## 7. Responsive

| Ancho | Diseño |
|---|---|
| < 640 px (móvil, prueba a 390) | una columna; navegación en menú; chat a pantalla completa; tablas → tarjetas apiladas |
| 640–1023 px (tablet, prueba a 820) | navegación en iconos; dos columnas de KPI |
| ≥ 1024 px (escritorio, prueba a 1440) | navegación completa; rejilla de 12 columnas; chat acoplado en Orquestación |

## 8. Internacionalización

Todas las cadenas en `js/i18n/es.js`; `t()` con interpolación `{var}`;
formatos con `Intl` y `es-PE`; `lang="es"` en el documento. Añadir un idioma =
un archivo nuevo del mismo formato.
