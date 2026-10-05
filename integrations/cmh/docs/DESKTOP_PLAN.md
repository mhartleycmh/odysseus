# Fase E — Aplicación de escritorio (punto limpio 10b)

Plan de la decisión del usuario del 2026-10-04 (opción (b), «aplicación de escritorio empaquetada»). Decisión y
motivos: [ADR-039](DECISIONS.md) y
`CMH_Claude/entregables/AgenticOS_Fase1_20261004/LOG_DECISIONES_AgenticOS_Escritorio_20261004.md` (A1 a A4), que
mandan sobre este plan si difieren. Misma forma que §18 a §20 del blueprint
(`CMH_Claude/Claude outputs/BLUEPRINT_AgenticOS_2026.09_v04.md`).

**Estado al 2026-10-04: planificada. Sin código, sin build y sin ejecutable.** Toda cifra de este plan lleva su
fuente; lo que no se midió dice `PENDIENTE:` o `VERIFICAR`. «Propuesta del plan» marca un detalle de diseño que el
LOG no decide: se confirma o se cambia al construir el paso (nivel B) y se registra.

## Objetivo

Un ejecutable onedir que, con doble clic, arranca el servidor Odysseus sobre `%LOCALAPPDATA%\Odysseus\data`, abre
`/cmh/os` en una ventana de Edge `--app` con perfil propio y se gobierna desde la bandeja; con la guarda de áreas
protegidas probada **en modo congelado**, y con el primer run de cinco pasos completado desde el ejecutable con el
criterio de §18.

## Prerrequisito

- **Punto limpio 10 cerrado** (§18; D5; LOG A4). Al 2026-10-04 no lo está: la revisión independiente de la Fase 1
  sobre la etiqueta `revision-fase1-r10` está en curso. Ningún paso de código de esta fase empieza antes.
- Las acciones del usuario U12 a U14 (abajo) no tocan código y se pueden hacer antes. E.3 necesita U12. E.4a también
  necesita U12 (el exe mínimo se construye con PyInstaller) y su medición es U13; **E.4a va antes de E.3**: el
  producto no se construye sin saber qué hace la máquina con un exe PyInstaller sin firma. **E.4a puede adelantarse**
  a cualquier momento después de U12, incluso antes de E.1 y E.2: no depende del código de E.1 ni de E.2 (el exe
  mínimo no lleva código del Agentic OS) y no es un paso de código de la fase, sino una medición.
- E.6 necesita además U8 (BLOQUEANTE §22.1 y §22.4).

## Pasos

Orden obligatorio: **E.1a va primero** (es de seguridad); ningún ejecutable se construye para usarlo antes de que
E.1a esté cerrado (LOG A4). Orden de ejecución, que es el de la tabla: E.1a → E.1b-e → E.2 → E.2b → E.4a → E.3 →
E.4b → E.5 → E.6. Ese es el orden límite: E.4a puede adelantarse porque no depende del código de E.1 ni de E.2; lo
único que exige es U12 y quedar cerrado antes de E.3. El exe mínimo no ejecuta código del Agentic OS: solo mide el
entorno. Cada capacidad va en su commit con su prueba y **su mutante en el mismo commit**, y cada prueba nueva se
corre primero contra el código anterior para ver que falla (método de ADR-038).

| Paso | Capacidad | Dónde vive | Prueba | Mutante | Criterio |
|---|---|---|---|---|---|
| E.1a | **Raíz del vault explícita que falla CERRADA** (defecto 1, seguridad) | `src/cmh_protected_areas.py:17`; derivados en `routes/cmh_control_routes.py:28-29` y `routes/cmh_memory_routes.py:17-19` | (i) modo congelado simulado y `CMH_VAULT_ROOT` sin definir: `protected_area()` de una carpeta legítima devuelve un área no nula e `in_financial_area()` da `True`; (ii) `CMH_VAULT_ROOT` = vault falso en `tmp` con las 6 áreas: cada área se reconoce aunque `__file__` esté fuera; (iii) sin congelar y sin variable: comportamiento de hoy; (iv) las cuatro rutas derivadas: con `CMH_VAULT_ROOT` = `tmp`, `INDEX_PATH`, `MANAGED_PROJECTS`, `CANON_ROOT` y `MIRROR_ROOT` quedan bajo `tmp`; en modo congelado y sin la variable, `GET /api/cmh/projects` (lee `INDEX_PATH`), `POST /api/cmh/projects` (escribe en `MANAGED_PROJECTS`, `routes/cmh_control_routes.py:263-264`) y `GET /api/cmh/memories` (lee `CANON_ROOT`, `routes/cmh_memory_routes.py:122`) responden el error que nombra la variable y crean 0 archivos | M1: quitar la rama de falla cerrada; M2: ignorar `CMH_VAULT_ROOT` y volver a `parents[2].parent` en `CMH_ROOT`; M3: una ruta derivada (una por corrida: `INDEX_PATH`, `MANAGED_PROJECTS`, `CANON_ROOT` o `MIRROR_ROOT`) sigue usando `parents[2].parent` | (i), (ii) y (iv) fallan contra el código actual; 3 de 3 mutantes capturados (M3 en sus 4 variantes); las pruebas de guarda existentes siguen en verde |
| E.1b | Copias de memoria bajo `DATA_DIR` (defecto 2; propuesta del plan) | `routes/cmh_memory_routes.py:20` | con `ODYSSEUS_DATA_DIR=tmp`, la copia previa a escribir el canon queda en `tmp/cmh_memory_backups` | volver a `parents[1] / "data"` | falla contra el código actual; mutante capturado |
| E.1c | MCP integrado nunca relanza el ejecutable (defecto 3; propuesta del plan) | `src/builtin_mcp.py:169-180` | modo congelado simulado y MCP sin apagar: `connect_server` no se llama con `command=sys.executable`, y el registro dice por qué | quitar la guarda de modo congelado | falla contra el código actual; mutante capturado |
| E.1d | `.env` con ruta explícita, nunca el directorio de trabajo (defecto 4; propuesta del plan) | `app.py:48` | modo congelado simulado y un `.env` con un marcador en el directorio de trabajo: el marcador no se carga | volver a `load_dotenv()` sin ruta | falla contra el código actual (python-dotenv 1.2.3 lee el directorio de trabajo con `sys.frozen`, `dotenv/main.py:361-363`); mutante capturado |
| E.1e | Cuotas fuera del bundle (defecto 5) | `src/cmh_provider_router.py:40`, `:83` | modo congelado simulado: el router lee las cuotas de la carpeta de datos (o de `CMH_FREE_QUOTAS`), no de `config/` del bundle | volver a `_CONFIG` | falla contra el código actual; mutante capturado |
| E.2 | **Lanzador CMH** con `CMH_DESKTOP_SHELL`, perfil propio, entorno fijado antes de importar la app y bandeja Abrir/Salir | Propuesta del plan: lógica en `src/cmh_desktop.py` y punto de entrada `launcher_cmh.py` en la raíz, sin tocar `launcher.py` del original (fusiones, ADR-010) | unitarias sobre funciones puras: elección del contenedor, argumentos de Edge, entorno fijado, menú de bandeja (detalle abajo) | M1: por defecto `browser`; M2: sin `--user-data-dir`; M3: no fija `ODYSSEUS_DISABLE_MCP`; M4: sobrescribe un `ODYSSEUS_DATA_DIR` ya definido; M5: «Abrir» vuelve a `webbrowser.open`; M6: el interruptor de companion se ignora y sus rutas se montan igual | 6 de 6 mutantes capturados |
| E.2b | Arranque al iniciar sesión (absorbido del paso 5.5, LOG A4) | Propuesta del plan: `scripts/cmh_ops/install-autostart.ps1` y `uninstall-autostart.ps1` | modo de ensayo: imprime lo que crearía sin crearlo; desinstalar deja 0 entradas | el ensayo crea la entrada | ensayo: 0 entradas creadas; desinstalar: 0 entradas; 1 de 1 mutante capturado. Activarlo en la máquina es U15; reinicio automático y `health.ps1` siguen en la Fase 3 |
| E.4a | **Medición del entorno corporativo con un exe mínimo** | fuera del repo; resultado en ESTADO | — (medición, no código) | — | 3 de 3 controles medidos con fecha (SAC, AppLocker, XDR) sobre el exe mínimo, y UPX registrado; si alguno bloquea, la fase se detiene aquí |
| E.3 | **Build reproducible desde el venv real** | `Odysseus.spec`, `build-windows-portable.ps1` | propuesta del plan: el guion se niega (sale con ≠ 0 y lo dice) si falta PyInstaller o pystray, en vez de instalarlos (`build-windows-portable.ps1:49-52` hoy instala); dos builds seguidos dan el mismo inventario | el guion vuelve a instalar por su cuenta | build sin errores desde `Documentos\Claude\.venv`; inventario idéntico en 2 de 2 builds; versiones de paquetes registradas |
| E.4b | **XDR y UPX repetidos con el exe de E.3** | fuera del repo; resultado en ESTADO | — (medición, no código) | — | XDR medido con fecha sobre el exe del producto; UPX registrado; misma carpeta que E.4a, o AppLocker (y SAC si aplica) repetido con fecha sobre la carpeta del exe del producto y sin bloqueo; si algo bloquea, la fase se detiene aquí |
| E.5 | **Prueba del ejecutable contra una carpeta de datos DESECHABLE** | `scripts/cmh_os/realmode/run.sh` (ampliado), sondas propias | humo sin sesión, sondas de escape, bundle intacto, procesos, `realmode/run.sh` contra el exe (detalle abajo) | los de E.1 y E.2, corridos ahora contra el exe donde se pueda | umbrales en «Criterio de cierre» |
| E.6 | **Migración de `data/` y primer run desde el exe** | `migrate-data.ps1` (no existe: el blueprint, U8, dice que lo prepara el agente) | `integrity_check=ok` antes y después; primer arranque; run de 5 pasos | — | **BLOQUEANTE §22.1 y §22.4 (U8)**; criterio de §18 sobre el run del exe |

### E.1 — Los cinco defectos de modo congelado

Los cinco se **leyeron** en el código el 2026-10-04 y no se ejecutaron (ADR-039, Contexto 4). Cada prueba simula el
modo congelado (`sys.frozen = True` y, donde haga falta, un `__file__` fuera del vault) dentro de pytest, sin
construir nada.

- **E.1a — `CMH_VAULT_ROOT` (propuesta del plan; el nombre es provisional).** Si la variable está definida, manda en
  los dos modos. Si no lo está **y** el proceso está congelado, la guarda falla CERRADA: `protected_area()` devuelve
  un nombre no nulo para cualquier ruta, `in_financial_area()` devuelve `True`, y las rutas que leen el índice, los
  proyectos y el canon responden un error que nombra la variable en lugar de leer otra carpeta. Sin congelar y sin
  variable, se conserva la derivación de hoy (`parents[2].parent`), para no mover nada en el árbol de desarrollo.
  `CMH_ROOT` y las cuatro rutas que se derivan de ella (`INDEX_PATH`, `MANAGED_PROJECTS`, `CANON_ROOT`, `MIRROR_ROOT`)
  salen de una sola función. Si una de las cuatro se queda con la ruta vieja, la atrapa la prueba (iv), no la (ii):
  la (ii) solo mira `protected_area()`; la (iv) mira dónde quedan las cuatro rutas con la variable y qué responden
  sus rutas HTTP sin ella, y el mutante M3 la pone a prueba con cada una. La forma exacta del error y el código HTTP:
  PENDIENTE (nivel B en E.1a).
- **E.1b (propuesta del plan).** `BACKUP_ROOT` pasa a `Path(DATA_DIR) / "cmh_memory_backups"`. Sin congelar y sin
  `ODYSSEUS_DATA_DIR`, la ruta resultante es la misma de hoy (`DATA_DIR` = `data/` del repo,
  `src/runtime_paths.py:30`).
- **E.1c (propuesta del plan).** Además de que el lanzador fija `ODYSSEUS_DISABLE_MCP=1` (E.2),
  `register_builtin_servers` no usa `sys.executable` si el proceso está congelado: segunda barrera para quien arranque el exe sin el lanzador CMH.
  **No cubre** los MCP registrados por el usuario (`app.py:1116-1117`): declarado en ADR-039.
- **E.1d (propuesta del plan).** Ubicación del `.env` del ejecutable: PENDIENTE (nivel B en E.1d); candidatos, junto
  a la carpeta de datos o junto al exe. Lo que propone el plan para cualquiera de los dos: nunca el directorio de
  trabajo.
- **E.1e.** El lanzador fija `CMH_FREE_QUOTAS` en la carpeta de datos. Qué pasa en el primer arranque si el archivo
  no existe (copiar la plantilla del bundle o arrancar sin límites): PENDIENTE (nivel B). En ningún caso se inventan
  límites: un límite ausente significa «no medido» y el router cae de forma reactiva
  (`src/cmh_provider_router.py:80-81`).

### E.2 — Lanzador CMH

- `CMH_DESKTOP_SHELL=edge-app|browser|webview`, por defecto `edge-app` (LOG A1).
  - `edge-app`: `msedge.exe --app=http://127.0.0.1:<APP_PORT>/cmh/os --user-data-dir=<carpeta de datos>\<perfil>`.
    El nombre de la subcarpeta del perfil: propuesta del plan, `edge-profile`. Búsqueda de `msedge.exe`: en esta
    máquina está en `C:\Program Files (x86)\Microsoft\Edge\Application\` (medido el 2026-10-04).
  - Sin `msedge.exe`: respaldo automático a `browser` (navegador por defecto) y una línea en el registro que lo dice.
  - `webview`: declarado y sin implementar (LOG A1). Qué hace si se elige: propuesta del plan, se niega a arrancar
    con un mensaje que nombra la variable, en lugar de cambiar en silencio a otro contenedor. Lo mismo con un valor
    desconocido.
- Entorno fijado **antes** de `from app import app` (`launcher.py:137`; `DATA_DIR` se lee al importar,
  `src/constants.py:12`):
  - `ODYSSEUS_DATA_DIR=%LOCALAPPDATA%\Odysseus\data` **solo si no viene ya definida**: así se revierte A2 y así E.5
    apunta a una carpeta desechable sin tocar la real (LOG A2, «Como se revierte»).
  - `ODYSSEUS_DISABLE_MCP=1` (`src/builtin_mcp.py:89`).
  - Companion apagado: **no hay interruptor** (`app.py:912-913` monta sus rutas sin condición). Hay que añadir uno;
    nombre y forma: PENDIENTE (nivel B en E.2). Prueba: con el interruptor puesto, las rutas de companion responden
    404. Mutante M6: el interruptor se ignora y las rutas se montan igual.
  - `CMH_FREE_QUOTAS` (E.1e) y la ruta del `.env` (E.1d).
  - No se toca `LOCALHOST_BYPASS` (por defecto `false`, `app.py:259`); el humo de E.5 comprueba que sigue así.
- La ventana se abre cuando `/api/health` (`app.py:991`) responde 200, no tras la espera fija de 3,5 s de
  `launcher.py:121` (propuesta del plan).
- Bandeja: **Abrir** reabre la ventana del contenedor elegido (hoy «Open Odysseus» llama a `webbrowser.open`,
  `launcher.py:91-92`); **Salir** detiene el servidor. Hoy «Exit» es `os._exit(0)` (`launcher.py:95-97`); el apagado
  ordenado queda PENDIENTE (ADR-039, Consecuencias).
- Forma de arrancar el exe **sin abrir ventana** para las pruebas de E.5: PENDIENTE (nivel B en E.2); el LOG no la
  decide.

### E.3 — Build

- Desde `Documentos\Claude\.venv` (Python 3.13.14 de Microsoft Store, `pyvenv.cfg`). Hoy el guion busca `.\.venv`
  dentro del repo (`build-windows-portable.ps1:30`), que no existe, y cae al Python del PATH.
- Requiere instalar PyInstaller y pystray en ese venv: **U12**, porque descarga paquetes. Medido el 2026-10-04: no
  están instalados; `PIL`, que usa el ícono de bandeja (`launcher.py:78`), sí.
- Una sola fuente de verdad para el build: propuesta del plan, la spec (`Odysseus.spec`, ya onedir, `:37-45`), con el
  punto de entrada cambiado al lanzador CMH. Hoy el guion construye por línea de comandos (`:66`) y no lee la spec.
- `build/` y `dist/` **están ignorados** por git: `git check-ignore -v build/ dist/` devuelve `.gitignore:7:build/` y
  `.gitignore:6:dist/` (corrido el 2026-10-04; sin la barra final el patrón no aplica a carpetas que aún no existen y
  no devuelve nada). PyInstaller los escribe dentro del repo al correr `build-windows-portable.ps1:66` (la línea `:55`
  solo los borra antes), y el repo vive en OneDrive. El riesgo que queda es el peso del build sincronizándose en
  OneDrive (tamaño no medido). Propuesta del plan: escribirlos fuera de OneDrive; la ruta: PENDIENTE.
- VERIFICAR en el primer build: que PyInstaller funcione sobre el Python de Microsoft Store (lo adelanta el exe
  mínimo de E.4a) y el tamaño del bundle. Si `upx=True` (`Odysseus.spec:28`, `:42`) usa un UPX presente se registra
  en E.4a y otra vez en E.4b.
- Propuesta del plan, como en la tabla: el guion se niega si falta PyInstaller o pystray, en vez de instalarlos.
- «Reproducible» aquí significa: mismo inventario de rutas y tamaños en dos builds seguidos y lista de versiones de
  paquetes registrada. La igualdad byte a byte del exe no se exige (no medida).

### E.4a y E.4b — Entorno corporativo (U13)

Lo que se mide es **qué hace la máquina con un exe PyInstaller sin firma**, y eso exige un exe. Por eso la medición va
en dos tiempos:

- **E.4a, antes de E.3, con un exe mínimo.** Propuesta del plan: un programa de una línea, sin código del Agentic
  OS, construido con la misma PyInstaller del venv real (requiere U12), en modo onedir, `--noconsole` y con UPX
  pedido como en la spec, y escrito fuera de OneDrive. Mide los tres controles de la tabla y adelanta si PyInstaller
  funciona sobre el Python de Microsoft Store. Si el log del build informa si UPX está disponible, se registra
  (VERIFICAR qué línea lo dice).
- **E.4b, después de E.3 y antes de E.5, con el exe del producto.** Se repite Cortex XDR (el exe del producto es más
  grande y abre un puerto local; el mínimo no lo hace) y se registra UPX. SAC y AppLocker no se repiten si la carpeta
  del exe es la misma que midió E.4a; si cambia, se repiten.

| Control | Qué se mide | Quién |
|---|---|---|
| Smart App Control | estado (activo, evaluación, apagado) | usuario |
| AppLocker | política efectiva sobre ejecutables en `%LOCALAPPDATA%` y en la carpeta del build | usuario o TI |
| Cortex XDR | si bloquea, pone en cuarentena o alerta al correr el exe | TI |

El camino exacto de cada medición: PENDIENTE (lo fija el usuario con TI; no se midió nada aún). Si alguno bloquea,
la fase se detiene en E.4a o en E.4b: firmar el ejecutable o pedir una excepción es decisión del usuario o de TI, no
se rodea.

### E.5 — Prueba del ejecutable contra una carpeta de datos desechable

Todo contra una carpeta creada para la prueba y borrada al final, con `APP_PORT` distinto de 7000 (como
`realmode/run.sh`, que usa 7101 por defecto) y una cuenta desechable. **Nunca contra `data/` ni contra
`%LOCALAPPDATA%\Odysseus\data`.**

1. **Humo sin sesión.** `GET /cmh/os` → 302 hacia `/login` y `GET /api/cmh/agents` → 401, que es lo que hace el
   middleware de autenticación leído en el código: sin cuentas, `app.py:416-423`; con cuenta y sin cookie válida,
   `app.py:479-487`. Se mide en los dos estados (antes y después de crear la cuenta desechable) y primero contra el
   servidor de desarrollo como control (VERIFICAR: no se ejecutó).
2. **Sondas de escape.** Con la cuenta desechable, intentar registrar un agente con carpeta de trabajo dentro de cada
   área protegida del vault real (solo se lee la ruta, no se escribe nada ahí): las 4 financieras, `CMH_Canon`,
   `CMH_Claude/CMH_Canon` y una carpeta que contiene `fuentes/` = 7 sondas. Segunda pasada con `CMH_VAULT_ROOT` sin
   definir: las 7 y una carpeta legítima, todas rechazadas (falla cerrada).
3. **Bundle intacto.** Huella (rutas y SHA-256) de la carpeta del build antes y después de toda la prueba: idéntica.
   Es una guarda general contra escrituras dentro del bundle; por sí sola no ejercita ningún defecto concreto (las
   sondas solo registran agentes), así que los defectos 2 y 5 tienen sus pasos 4 y 5.
4. **Copia de memoria (defecto 2).** Segundo arranque del exe con `CMH_VAULT_ROOT` = un vault falso en `tmp` (con su
   `CMH_Canon/` de prueba, nunca el canon real): crear una propuesta de memoria (`POST /api/cmh/memory-proposals`,
   `routes/cmh_memory_routes.py:141`) y aprobarla (`POST .../{id}/approve`, `:200`). La copia previa se escribe en
   `:213-217` y su ruta queda en `backup_path` (`:229`): debe estar bajo la carpeta de datos desechable, y el bundle
   debe seguir con la huella del paso 3. Qué archivos del canon acepta una propuesta, para armar el vault falso:
   VERIFICAR al construir E.5.
5. **Cuotas (defecto 5).** Poner en la carpeta de datos desechable un archivo de cuotas con un marcador (por ejemplo
   un `threshold` que no use el bundle) y comprobar que `GET /api/cmh/quotas` (`routes/cmh_control_routes.py:290-333`,
   que devuelve el `threshold` de la configuración que cargó) devuelve ese marcador y no el valor del bundle.
6. **Procesos.** Un solo proceso escuchando en `APP_PORT` y 0 `Odysseus.exe` lanzados con un guion como argumento
   (defecto 3).
7. **Perfil.** La línea de comandos de Edge lleva `--user-data-dir` bajo la carpeta desechable.
8. **`realmode/run.sh` contra el exe.** Hoy arranca `"$PY" -m uvicorn app:app` (`scripts/cmh_os/realmode/run.sh:52`);
   hay que permitirle arrancar el exe en su lugar (mecanismo: PENDIENTE, nivel B en E.5). La siembra sigue con el
   Python del venv sobre la carpeta desechable (`:49`). El e2e de `check.sh` corre contra un servidor falso, no
   contra el exe: no cuenta para esta fase y se declara.

### E.6 — Migración y primer run (BLOQUEANTE)

Solo con autorización explícita del usuario (U8; §22.1 y §22.4). Antes: copia con la API de backup de SQLite a
`%LOCALAPPDATA%\Odysseus\backups` e `integrity_check=ok`. Después: `integrity_check=ok` en la base movida, primer
arranque del exe sobre `%LOCALAPPDATA%\Odysseus\data`, `/api/health` 200, recuento de servidores MCP registrados por
el usuario (VERIFICAR: se conectan pese a `ODYSSEUS_DISABLE_MCP`), y el primer run de cinco pasos lanzado desde la
ventana del exe. `python scripts/cmh_ops/run_report.py --latest` sobre ese run debe salir con 0.

## Criterio de cierre (todos)

- **E.1:** 5 de 5 defectos con prueba que falló contra el commit base (anotado) y pasa después; 7 de 7 mutantes de
  E.1 capturados (3 de E.1a, con M3 capturado en sus 4 variantes, y 1 de cada uno de los otros cuatro); la prueba de
  validez de mutantes en verde sobre un export limpio de cada commit.
- **E.2:** 6 de 6 mutantes del lanzador capturados (M1 a M6); companion: sus rutas responden 404 con el interruptor
  puesto.
- **E.2b:** ensayo con 0 entradas creadas; desinstalar deja 0 entradas; 1 de 1 mutante capturado.
- **E.4a:** 3 de 3 controles medidos con fecha sobre el exe mínimo, UPX registrado, y ninguno bloquea.
- **E.3:** build sin errores desde el venv real; inventario idéntico en 2 de 2 builds.
- **E.4b:** XDR medido con fecha sobre el exe del producto, UPX registrado, y no bloquea; misma carpeta que E.4a, o
  AppLocker (y SAC si aplica) repetido con fecha sobre la carpeta del exe del producto y sin bloqueo.
- **E.5:** humo 4 de 4 con el código esperado (2 rutas en 2 estados); sondas **7 de 7 rechazadas** con la raíz
  definida y **8 de 8** sin ella; bundle con huella idéntica; copia de memoria 1 de 1 bajo la carpeta desechable;
  cuotas leídas de la carpeta desechable (marcador devuelto); 1 proceso escuchando y 0 relanzados; `realmode/run.sh`
  contra el exe con el mismo número de comprobaciones que contra uvicorn sobre el mismo commit y **0 fallidas
  nuevas**.
- **E.6:** el criterio de §18 sobre el run lanzado desde el exe: `run.status = completed`, 5 artefactos, 0 con marca
  `synthetic`, guardia de evidencia satisfecha en investigador, constructor y verificador, 0 llamadas a endpoints que
  no pasen la compuerta; `run_report.py --latest` = 0.
- **Tabla obligatoria del punto limpio 10b:** pruebas nuevas por paso (contadas por recolección), mutantes por paso
  (capturados / total), resultado de cada sonda, huella del bundle antes y después, tamaño del bundle, tiempo de
  arranque hasta `/api/health` 200, resultado de las mediciones de E.4a y E.4b, ID del run de E.6 y su `run_report`.

## Acciones del usuario

Continúan la numeración de §21 del blueprint (U1 a U11 no se renumeran).

| # | Acción | Camino exacto | Verificación |
|---|---|---|---|
| U8 | (ya existente) Decidir la migración de `data/` fuera de OneDrive | §21 y §22.1 del blueprint | desbloquea E.6 |
| U12 | **Instalar PyInstaller y pystray** en `Documentos\Claude\.venv` (descarga paquetes de PyPI) | `<venv>\Scripts\python.exe -m pip install pyinstaller pystray`. No correr `build-windows-portable.ps1` tal como está: instala también `requirements.txt` y actualiza `pip` (`:50-51`) | `pip show pyinstaller pystray` con sus versiones, que se registran en E.3 |
| U13 | **Medir con TI** Smart App Control, AppLocker efectivo y Cortex XDR frente a un exe sin firma: primero el exe mínimo (E.4a, antes de E.3), después el del producto (E.4b) | E.4a y E.4b | tabla de E.4a y E.4b con fecha |
| U14 | **Revisar la compatibilidad de licencias** de PyInstaller, pystray y Pillow con AGPL-3.0, la de los recursos de terceros que ya trae `static/` (KaTeX, Mermaid, OpenDyslexic; textos en `licenses/`), y el alcance de distribución (el logotipo no sale de CMH) | `LICENSES_AND_ATTRIBUTIONS.md`, nota PENDIENTE | nota sustituida por una conclusión con su fuente |
| U15 | Decidir si se **activa el arranque al iniciar sesión** en la máquina | `install-autostart.ps1` (E.2b) | entrada creada; `uninstall-autostart.ps1` la quita |

## Fuera de alcance

- **Extraer un núcleo propio** (bucle de agente con las 4 herramientas de lectura, sin el resto del fork). Solo con
  un prototipo medido: hoy el tamaño de ese núcleo no existe como cifra, y lo que se reemplazaría mide 330 + 3 037
  líneas de bucle, 691 de herramientas y 448 de guarda (ADR-039, Contexto 5; LOG A3). La extracción puede abrirse en
  cualquier momento: el empaquetado no la impide.
- `CMH_DESKTOP_SHELL=webview` (pywebview): declarado, no se implementa en esta fase.
- Firma de código, instalador (MSI o similar) y actualización automática: no decididos.
- Reinicio automático del servidor y `health.ps1`: siguen en la Fase 3 (paso 5.5).
- Distribución fuera de esta máquina o fuera de CMH: no decidida; el logotipo no puede salir de CMH
  (`LICENSES_AND_ATTRIBUTIONS.md`, fila del logotipo) y las licencias no se verificaron (U14).
