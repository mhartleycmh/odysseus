"""Which paths an agent workspace may never lie in or contain.

Extracted from ``routes.cmh_control_routes`` so a script can consult the rule
without importing it: that module imports ``core.database``, whose ``init_db()``
migrates whatever ``DATABASE_URL`` points at. The seeding script refused a
forbidden workspace root AFTER that import, so it printed "nothing was seeded"
having already altered the schema of the live file.

Only the rules live here. The project catalogue (``INDEX_PATH``,
``MANAGED_PROJECTS``) stays with the routes: it answers a different question.
"""

import os
from pathlib import Path
from typing import Optional

CMH_ROOT = Path(__file__).resolve().parents[2].parent
# Financial, production and canon folders stay outside every agent workspace
# (integrations/cmh/README.md), as does any fuentes/ folder, which is read-only.
FINANCIAL_AREAS = ("Base Matriz Nueva", "Modelo Financiero Nuevo",
                   "Dashboard Financiero", "Producción")
PROTECTED_AREAS = FINANCIAL_AREAS + ("CMH_Canon", "CMH_Claude/CMH_Canon")
_FUENTES_SCAN_DEPTH = 3


def in_financial_area(path) -> bool:
    target = Path(path).resolve()
    return any(target.is_relative_to((CMH_ROOT / name).resolve())
               for name in FINANCIAL_AREAS)


def protected_area(path) -> Optional[str]:
    """Name the protected area a workspace lies in or contains, or None."""
    target = Path(path).resolve()
    if any(part.casefold() == "fuentes" for part in target.parts):
        return "fuentes"
    for name in PROTECTED_AREAS:
        area = (CMH_ROOT / name).resolve()
        if target.is_relative_to(area) or area.is_relative_to(target):
            return name
    base_depth = len(target.parts)
    for current, dirs, _files in os.walk(target):
        if any(d.casefold() == "fuentes" for d in dirs):
            return "fuentes"
        if len(Path(current).parts) - base_depth >= _FUENTES_SCAN_DEPTH:
            dirs.clear()
    return None
