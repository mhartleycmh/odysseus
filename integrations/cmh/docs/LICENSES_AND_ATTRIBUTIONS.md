# Licencias y atribuciones — Interfaz Agentic OS CMH

## Dependencias incorporadas al producto

**Ninguna.** La interfaz (`static/cmh-os/`) no incluye código, hojas de estilo,
fuentes, iconos ni imágenes de terceros. Todo el código es original de este
repositorio y queda bajo la licencia del repositorio (`LICENSE`, raíz de Odysseus).

> **PENDIENTE (2026-10-04, ADR-039):** la Fase E ([DESKTOP_PLAN.md](DESKTOP_PLAN.md)) empaquetaría Odysseus como
> ejecutable con **PyInstaller** (su bootloader queda dentro del exe) y **pystray** (ícono de bandeja). Si se
> construye, esta sección deja de ser cierta para el ejecutable. Licencias según el informe del investigador del
> 2026-10-04, no verificadas contra el archivo de licencia de cada paquete (ninguno está instalado): PyInstaller
> GPL-2.0 con excepción para el bootloader; pystray LGPL-3.0; Odysseus AGPL-3.0-or-later (`LICENSE`, `README.md`).
> **No se afirma que sean compatibles ni que cumplan las obligaciones de la AGPL: no se verificó.** También
> entrarían al bundle, sin revisar: Pillow (no está en `requirements.txt`; lo instala `build-windows-portable.ps1:51`
> y lo importa `launcher.py:78` para el ícono de bandeja) y las dependencias de `requirements.txt`.
> **PENDIENTE:** el bundle incluye `static/` entero, y `static/` ya trae recursos de terceros que esta página no
> lista: KaTeX (`static/lib/katex/`, con 20 archivos de fuente en `fonts/`), Mermaid (`static/lib/mermaid.min.js`) y
> OpenDyslexic (`static/fonts/OpenDyslexic-*.woff2`); sus textos de licencia están en `licenses/` en la raíz del repo
> (`KaTeX-MIT-LICENSE.txt`, `Mermaid-MIT-LICENSE.txt`, `OpenDyslexic-OFL.txt`; leídos solo por el nombre del
> archivo). No son parte de la interfaz `static/cmh-os/`, que es lo que cubre «Ninguna» arriba. El ejecutable
> incluye también el logotipo, que no sale de CMH (fila de abajo). Revisión: acción U14 del plan.

| Recurso | Origen | Licencia / autorización |
|---|---|---|
| Logotipo `static/cmh-os/assets/logo-cmh.png` (460 × 189 px) | Recurso de identidad corporativa de Consorcio Minero Horizonte provisto por el usuario (skill `identidad-cmh`) | Marca de CMH; uso interno autorizado por el titular de la cuenta. No redistribuir fuera de CMH. Reglas: sin redibujar, sin recolorear, proporción 2.43:1, caja blanca sobre fondos azules |
| Paleta y tipografía | Mismo recurso de identidad CMH | Ídem |
| Iconografía | Glifos Unicode geométricos (● ▲ ■ ○ ◆ ▸) y trazos SVG propios | Original |
| Tipografía | `Aptos` → `Segoe UI` → `system-ui` (fuentes del sistema; no se sirven archivos de fuente) | Licencias del sistema operativo del usuario |

## Herramientas usadas solo para verificar (no se distribuyen)

| Herramienta | Uso | Licencia | Origen |
|---|---|---|---|
| TypeScript 6.0.3 (`typescript.js` embebido en VS Code) | Validación de tipos JSDoc | Apache-2.0 | Instalación local de VS Code |
| Node.js 24.20.0 embebido en VS Code (Electron) | Ejecutar pruebas y scripts | MIT (Node.js) | Instalación local de VS Code |
| Microsoft Edge (modo sin ventana + DevTools Protocol) | Pruebas end-to-end y capturas | Propietaria, instalada en la máquina | Instalación local |
| pytest (venv existente) | Pruebas de rutas FastAPI | MIT | Ya presente en el proyecto |

## Proyectos consultados como referencia conceptual

Ver [OPEN_SOURCE_REFERENCES.md](OPEN_SOURCE_REFERENCES.md). No se incorporó
código de ninguno. Se evitó a propósito la semejanza visual con Dify (declara
patente de apariencia) y con productos de licencia no OSI (n8n, Phoenix).
