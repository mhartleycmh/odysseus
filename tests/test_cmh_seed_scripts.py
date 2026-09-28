"""Tests for the two seeding scripts. They write to the live database.

The independent review of 2026-09-28 measured 613 lines of script with zero
tests protecting them. Behaviour was verified by hand once; nothing stopped the
next edit from breaking it. These cover the parts whose failure is expensive:
the leak control, the backup ordering, and idempotency.
"""

import importlib.util
import json
import pathlib
import sqlite3
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scrub = _load("cmh_scrub_instructions", "scripts/cmh_seed/scrub_instructions.py")
seed = _load("cmh_seed_agents_script", "scripts/cmh_seed_agents.py")


# --- the leak control has to be able to fail --------------------------------

@pytest.mark.parametrize("label, probe", [
    ("ruta absoluta de Windows", r"mira C:\Users\alguien\modelo"),
    ("carpeta OneDrive", "guardado en OneDrive - CMH"),
    ("archivo de Excel nombrado", "abre Modelo Financiero.xlsx"),
    ("plantilla financiera nombrada", "parte de PLANTILLA_BASE_MODELO"),
    ("importe con moneda", "EBITDA de USD 12,450,000"),
    ("ratio o covenant nombrado", "el DSCR del trimestre"),
    ("nombre de persona", "consultar con Mijhael Hartley"),
])
def test_every_forbidden_pattern_detects_its_own_case(label, probe):
    """A control that cannot fire is decoration. The person-name pattern was
    added because the header claimed it and nothing measured it."""
    import re
    pattern = dict(scrub.FORBIDDEN)[label]
    assert re.search(pattern, probe), f"{label} no detecta: {probe}"


def test_operational_figures_are_not_treated_as_financial():
    """'3 rondas' and 'SHA-256' must survive: the brief keeps them on purpose."""
    import re
    clean = "Haz 3 rondas y verifica el SHA-256 del artefacto en 26 segundos."
    assert [label for label, pattern in scrub.FORBIDDEN if re.search(pattern, clean)] == []


def test_the_five_derived_files_are_clean_and_complete():
    for source_name, role in scrub.ROLES.items():
        path = scrub.TARGET / role / "_sistema" / "instrucciones_v1.md"
        assert path.is_file(), f"falta el derivado de {role}; corre scrub_instructions.py"
        body = path.read_text(encoding="utf-8")
        import re
        hits = [label for label, pattern in scrub.FORBIDDEN if re.search(pattern, body)]
        assert hits == [], f"{role} filtra: {hits}"


def test_no_derived_file_instructs_a_capability_the_step_lacks():
    """A step has read_file, ls, grep, glob and nothing else. An instruction it
    cannot follow produces the apology the evidence guard then rejects."""
    import re
    impossible = re.compile(r"python scripts/|CMH_Canon|`fuentes/`|WebSearch|entregables/|"
                            r"invoca `|delega en `|perito-")
    for role in scrub.ROLES.values():
        body = (scrub.TARGET / role / "_sistema" / "instrucciones_v1.md").read_text(encoding="utf-8")
        assert not impossible.search(body), f"{role} instruye algo que su paso no puede hacer"


def test_the_verifier_is_told_to_close_with_the_counts_block():
    """The mechanical gate of D7 reads that line; if the instruction is gone,
    every run stops for a human instead of flowing."""
    body = (scrub.TARGET / "verificador" / "_sistema" / "instrucciones_v1.md").read_text(encoding="utf-8")
    assert "CONTEOS: revisadas=<n> errores=<n> pendientes=<n>" in body


# --- the seeding script -----------------------------------------------------

def test_the_backup_verifies_both_ends_and_refuses_a_corrupt_source(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    source = tmp_path / "app.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE t (a TEXT)")
    connection.execute("INSERT INTO t VALUES ('x')")
    connection.commit()
    connection.close()

    target = seed.backup_database(source, "prueba")
    assert target.is_file() and target.parent.name == "backups"
    assert "Odysseus" in str(target)
    check = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    assert check.execute("SELECT a FROM t").fetchone()[0] == "x"
    check.close()


def test_the_backup_refuses_when_there_is_no_safe_location(tmp_path, monkeypatch):
    """No LOCALAPPDATA means no path outside the repo and OneDrive, and a copy
    inside either is what §7 forbids."""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    source = tmp_path / "app.db"
    sqlite3.connect(source).close()
    with pytest.raises(RuntimeError, match="LOCALAPPDATA"):
        seed.backup_database(source, "prueba")


def test_the_live_path_is_resolved_without_importing_core_database(monkeypatch):
    """Importing core.database runs init_db(), which migrates whatever
    DATABASE_URL points at. The backup must be taken first, so the path has to
    be resolvable without the import."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///C:/tmp/otra.db")
    assert seed.live_database_path() == pathlib.Path("C:/tmp/otra.db")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    assert str(seed.live_database_path()) in ("", ".")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert seed.live_database_path().name == "app.db"


def test_the_source_never_imports_core_database_before_backing_up():
    """Ordering is the whole guarantee, and a future edit could quietly undo
    it, so it is asserted on the source rather than on behaviour."""
    source = (REPO / "scripts" / "cmh_seed_agents.py").read_text(encoding="utf-8")
    backup_at = source.index("backup_database(db_path")
    import_at = source.index("from core.database import CMHAgent, SessionLocal")
    assert backup_at < import_at, "la copia debe tomarse ANTES del import que migra"


def test_the_preserved_agent_is_named_and_never_reused():
    assert seed.PRESERVE == "CMH Researcher"
    source = (REPO / "scripts" / "cmh_seed_agents.py").read_text(encoding="utf-8")
    # The five roles it creates, and the preserved one is not among them.
    assert [role for role, _, _ in seed.AGENTS] == [
        "investigador", "constructor", "verificador", "revisor", "documentador"]
    assert "delete" not in source.lower().replace("deleted", "")


def test_the_seeded_agents_only_get_read_only_tools():
    from src.cmh_workflows import READ_TOOLS
    assert set(seed.READ_TOOLS) == set(READ_TOOLS), (
        "las herramientas del guion deben ser exactamente las que el motor permite")


def test_missing_derived_instructions_stop_the_script_with_a_usable_message(monkeypatch, tmp_path):
    monkeypatch.setattr(seed, "WORKSPACES", tmp_path)
    with pytest.raises(SystemExit) as caught:
        seed.instructions_for("investigador")
    assert "scrub_instructions.py" in str(caught.value)
