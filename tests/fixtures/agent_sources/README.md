# Fuentes sinteticas para probar el depurador de instrucciones

Los originales viven fuera del repositorio (`../.claude/agents`) y **no se
versionan**: llevan nombres de archivos financieros y la tabla de peritos, que
es justo lo que `scripts/cmh_seed/scrub_instructions.py` existe para no dejar
salir. Versionarlos para que las pruebas pasen habria sido la fuga que el
depurador previene.

Estos cinco archivos imitan su FORMA —cabecera YAML, secciones, y lineas con
un archivo financiero, un ratio, un importe, un nombre de persona y una ruta
local— para que las pruebas ejerciten el depurador y su control de fuga sin
versionar nada real. El guion los toma con `CMH_AGENT_SOURCES`.
