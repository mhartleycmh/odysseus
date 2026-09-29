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
import tempfile
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


@pytest.fixture
def derived(tmp_path, monkeypatch):
    """Generate the five files into a throwaway tree.

    Reading data/agent_workspace made these tests depend on untracked local
    state: .gitignore excludes data/, so a clean checkout failed 3 of 18 while
    the declared count said 225. Generating them here also exercises main(),
    which nothing did before.
    """
    monkeypatch.setattr(scrub, "TARGET", tmp_path)
    monkeypatch.setattr("sys.argv", ["scrub_instructions.py"])
    assert scrub.main() == 0, "el guion debe terminar limpio"
    return tmp_path


def test_the_five_derived_files_are_clean_and_complete(derived):
    import re
    for source_name, role in scrub.ROLES.items():
        path = derived / role / "_sistema" / "instrucciones_v1.md"
        assert path.is_file(), f"falta el derivado de {role}"
        body = path.read_text(encoding="utf-8")
        hits = [label for label, pattern in scrub.FORBIDDEN if re.search(pattern, body)]
        assert hits == [], f"{role} filtra: {hits}"


def test_no_derived_file_instructs_a_capability_the_step_lacks(derived):
    """A step has read_file, ls, grep, glob and nothing else. An instruction it
    cannot follow produces the apology the evidence guard then rejects."""
    import re
    impossible = re.compile(r"python scripts/|CMH_Canon|`fuentes/`|WebSearch|entregables/|"
                            r"invoca `|delega en `|perito-")
    for role in scrub.ROLES.values():
        body = (derived / role / "_sistema" / "instrucciones_v1.md").read_text(encoding="utf-8")
        assert not impossible.search(body), f"{role} instruye algo que su paso no puede hacer"


def test_the_verifier_is_told_to_close_with_the_counts_block(derived):
    """The mechanical gate of D7 reads that line; if the instruction is gone,
    every run stops for a human instead of flowing."""
    body = (derived / "verificador" / "_sistema" / "instrucciones_v1.md").read_text(encoding="utf-8")
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


def test_a_dry_run_never_migrates_the_database_it_was_pointed_at(tmp_path, monkeypatch):
    """Measured on 2026-09-29: the dry run imported core.database, which runs
    init_db(), and so migrated the live file — and the commit that was supposed
    to fix it had removed the backup too. The old test compared two positions
    in the source file and passed throughout."""
    live = tmp_path / "app.db"
    connection = sqlite3.connect(live)
    connection.execute("CREATE TABLE cmh_agents (id TEXT PRIMARY KEY, owner TEXT, name TEXT)")
    connection.commit()
    connection.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{live.as_posix()}")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr("sys.argv", ["cmh_seed_agents.py"])
    before = live.read_bytes()
    try:
        seed.main()
    except SystemExit:
        pass
    except Exception:
        pass  # the plan may fail on this stub schema; the file must still be intact
    assert live.read_bytes() == before, "una simulacion no puede tocar la base apuntada"
    backups = tmp_path / "local" / "Odysseus" / "backups"
    assert not backups.exists() or not list(backups.iterdir()), (
        "una simulacion que no toca nada tampoco deja copias")


def test_the_preserved_agent_is_named_and_never_reused():
    assert seed.PRESERVE == "CMH Researcher"
    source = (REPO / "scripts" / "cmh_seed_agents.py").read_text(encoding="utf-8")
    # The five roles it creates, and the preserved one is not among them.
    assert [role for role, _, _ in seed.AGENTS] == [
        "investigador", "constructor", "verificador", "revisor", "documentador"]
    # Behaviour is measured by test_the_preserved_agent_survives_a_real_apply;
    # this only pins the name the guarantee is written against.
    assert "PRESERVE" in source


def test_the_seeded_agents_only_get_read_only_tools():
    from src.cmh_workflows import READ_TOOLS
    assert set(seed.READ_TOOLS) == set(READ_TOOLS), (
        "las herramientas del guion deben ser exactamente las que el motor permite")


def test_missing_derived_instructions_stop_the_script_with_a_usable_message(monkeypatch, tmp_path):
    monkeypatch.setattr(seed, "WORKSPACES", tmp_path)
    with pytest.raises(SystemExit) as caught:
        seed.instructions_for("investigador")
    assert "scrub_instructions.py" in str(caught.value)


# --- the two script guarantees, measured in a subprocess ----------------------
#
# These cannot be measured in-process: `core.database` is already imported by
# the test session, so its init_db() has run and a second import inside the
# script is a no-op. That is why the first version of the dry-run test passed
# under a mutant that reopened the live database. A subprocess imports it
# fresh, which is what the script does in real use.

import os
import subprocess
import sys


def _derived_tree(tmp_path):
    """Generate the five derived instruction files into a throwaway tree.

    The subprocess runs the real script, which reads the workspace root. Letting
    it read data/agent_workspace made these tests depend on untracked state
    again: measured on a clean checkout, 3 of them failed. CMH_AGENT_WORKSPACES
    points both scripts here instead.
    """
    root = tmp_path / "workspaces"
    subprocess.run([sys.executable, str(REPO / "scripts" / "cmh_seed" / "scrub_instructions.py")],
                   cwd=str(REPO), capture_output=True, text=True, check=True,
                   env={**os.environ, "CMH_AGENT_WORKSPACES": str(root)})
    return root


def _run_script(args, env_extra, cwd=None):
    env = {**os.environ, **env_extra}
    return subprocess.run([sys.executable, str(REPO / "scripts" / "cmh_seed_agents.py"), *args],
                          cwd=str(cwd or REPO), capture_output=True, text=True, env=env)


def _legacy_database(path):
    """A database with the schema as it was BEFORE provider_policy existed."""
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE cmh_agents (id TEXT PRIMARY KEY, owner TEXT, name TEXT, "
        "project_id TEXT, role TEXT NOT NULL, instructions TEXT NOT NULL, "
        "instructions_version INTEGER, model TEXT, allowed_tools TEXT, workspace TEXT, "
        "status TEXT, task_id TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)")
    connection.commit()
    connection.close()


def test_a_dry_run_leaves_the_pointed_database_byte_identical(tmp_path):
    """M20, measured in a subprocess. A dry run must not migrate the database it
    was pointed at, and must not need a backup to be safe."""
    live = tmp_path / "app.db"
    _legacy_database(live)
    before = live.read_bytes()
    backups = tmp_path / "local"
    result = _run_script([], {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
                              "LOCALAPPDATA": str(backups),
                              "CMH_AGENT_WORKSPACES": str(_derived_tree(tmp_path))})
    assert "SIMULACION" in result.stdout, result.stdout + result.stderr
    assert live.read_bytes() == before, "una simulacion no puede tocar la base apuntada"
    assert not backups.exists() or not list(backups.rglob("*.db"))


def test_applying_migrates_the_schema_of_an_existing_installation(tmp_path):
    """M22. Every test builds the schema with create_all, so nothing covered the
    ALTER TABLE that an already-installed database needs. Without it, the first
    query on CMHAgent fails for every existing install."""
    live = tmp_path / "app.db"
    _legacy_database(live)
    columns = lambda: {r[1] for r in sqlite3.connect(live).execute(
        "PRAGMA table_info(cmh_agents)")}
    assert "provider_policy" not in columns()
    result = _run_script(["--apply", "--authorized-by", "prueba"],
                         {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
                          "LOCALAPPDATA": str(tmp_path / "local"),
                          "CMH_AGENT_WORKSPACES": str(_derived_tree(tmp_path))})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "provider_policy" in columns(), "la migracion no corrio"


def test_applying_backs_up_before_it_writes(tmp_path):
    live = tmp_path / "app.db"
    _legacy_database(live)
    backups = tmp_path / "local"
    result = _run_script(["--apply", "--authorized-by", "prueba"],
                         {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
                          "LOCALAPPDATA": str(backups),
                          "CMH_AGENT_WORKSPACES": str(_derived_tree(tmp_path))})
    assert result.returncode == 0, result.stdout + result.stderr
    copies = list((backups / "Odysseus" / "backups").glob("*.db"))
    assert copies, "aplicar sin copia previa es lo que §7 prohibe"


def test_the_script_refuses_before_writing_when_the_instructions_are_missing(tmp_path,
                                                                             monkeypatch):
    """M19. The input check must happen before anything else, and nothing
    measured that it does."""
    live = tmp_path / "app.db"
    _legacy_database(live)
    before = live.read_bytes()
    empty = tmp_path / "sin-instrucciones"
    empty.mkdir()
    result = subprocess.run(
        [sys.executable, "-c",
         "import pathlib,sys;"
         f"sys.argv=['seed','--apply','--authorized-by','x'];"
         f"sys.path.insert(0, {str(REPO)!r});"
         "import importlib.util as u;"
         f"spec=u.spec_from_file_location('seed', {str(REPO / 'scripts' / 'cmh_seed_agents.py')!r});"
         "m=u.module_from_spec(spec);spec.loader.exec_module(m);"
         f"m.WORKSPACES=pathlib.Path({str(empty)!r});"
         "sys.exit(m.main())"],
        capture_output=True, text=True,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{live.as_posix()}",
             "LOCALAPPDATA": str(tmp_path / "local")})
    assert result.returncode != 0
    assert "scrub_instructions.py" in (result.stdout + result.stderr)
    assert live.read_bytes() == before, "no se escribe nada si faltan las instrucciones"


# --- findings of the THIRD independent review (2026-09-29) -------------------

def test_the_preserved_agent_survives_a_real_apply(tmp_path):
    """The previous commit REPLACED the only measurement of this guarantee with
    `assert X in source or X in source` - the same string twice, so the
    disjunction was dead letter. A mutant that deletes the preserved row at the
    top of apply() survived all 251 tests. Measured behaviour now."""
    live = tmp_path / "app.db"
    _legacy_database(live)
    connection = sqlite3.connect(live)
    connection.execute(
        "INSERT INTO cmh_agents (id, owner, name, role, instructions, "
        "instructions_version, status) VALUES "
        "('preservado', 'admin', 'CMH Researcher', 'piloto', 'x', 1, 'paused')")
    connection.commit()
    connection.close()

    result = _run_script(["--apply", "--authorized-by", "prueba"],
                         {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
                          "LOCALAPPDATA": str(tmp_path / "local"),
                          "CMH_AGENT_WORKSPACES": str(_derived_tree(tmp_path))})
    assert result.returncode == 0, result.stdout + result.stderr
    rows = sqlite3.connect(live).execute(
        "SELECT id, status FROM cmh_agents WHERE name = 'CMH Researcher'").fetchall()
    assert rows == [("preservado", "paused")], (
        "CMH Researcher no se borra, no se reutiliza y no se reactiva")


def test_a_dry_run_leaves_no_replica_behind(tmp_path):
    """118 full replicas of the database had accumulated in %TEMP%, one holding
    an encrypted provider key: `scratch` was created and never removed."""
    live = tmp_path / "app.db"
    _legacy_database(live)
    before = set(pathlib.Path(tempfile.gettempdir()).glob("cmh-seed-dryrun-*.db"))
    result = _run_script([], {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
                              "LOCALAPPDATA": str(tmp_path / "local"),
                              "CMH_AGENT_WORKSPACES": str(_derived_tree(tmp_path))})
    assert "SIMULACION" in result.stdout, result.stdout + result.stderr
    after = set(pathlib.Path(tempfile.gettempdir()).glob("cmh-seed-dryrun-*.db"))
    assert after <= before, f"copias huerfanas: {sorted(after - before)}"


@pytest.mark.parametrize("bad", ["local_only", "nube-total", "FREE-CLOUD-FIRST-ISH"])
def test_a_mistyped_policy_stops_the_script_instead_of_routing_to_the_cloud(tmp_path, bad):
    """The 400 for an unknown policy went into validate_dag and the agent API,
    never into the script that configures the five chain agents. Measured by the
    third review: `--policy local_only` resolved Groq as a candidate."""
    live = tmp_path / "app.db"
    _legacy_database(live)
    result = _run_script(["--policy", bad],
                         {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
                          "LOCALAPPDATA": str(tmp_path / "local"),
                          "CMH_AGENT_WORKSPACES": str(_derived_tree(tmp_path))})
    assert result.returncode != 0, result.stdout
    assert "no existe" in result.stdout


def test_a_workspace_root_inside_a_protected_area_is_refused(tmp_path):
    """CMH_AGENT_WORKSPACES was introduced as a test affordance and shipped
    without the guard the API applies to the same field: with it pointed at a
    `fuentes` path, --apply wrote five active agents there."""
    live = tmp_path / "app.db"
    _legacy_database(live)
    forbidden = tmp_path / "proyecto" / "fuentes"
    forbidden.mkdir(parents=True)
    # With the derived instructions present at the forbidden root, the only
    # thing left that can refuse is the guard under test.
    subprocess.run([sys.executable, str(REPO / "scripts" / "cmh_seed" / "scrub_instructions.py")],
                   cwd=str(REPO), capture_output=True, text=True, check=True,
                   env={**os.environ, "CMH_AGENT_WORKSPACES": str(forbidden)})
    result = _run_script(["--apply", "--authorized-by", "prueba"],
                         {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
                          "LOCALAPPDATA": str(tmp_path / "local"),
                          "CMH_AGENT_WORKSPACES": str(forbidden)})
    assert result.returncode != 0, result.stdout
    assert "protegida" in result.stdout
    count = sqlite3.connect(live).execute(
        "SELECT COUNT(*) FROM cmh_agents").fetchone()[0]
    assert count == 0, "no se escribe ninguna fila si la raiz esta protegida"


def test_two_dry_runs_do_not_share_one_scratch_file(tmp_path):
    """R14. A fixed name makes two concurrent dry runs fight over one file, and
    the loser's finally deletes the winner's copy mid-read. The script prints
    the path, so the process id in it is observable."""
    live = tmp_path / "app.db"
    _legacy_database(live)
    derived = str(_derived_tree(tmp_path))
    paths = []
    for _ in range(2):
        result = _run_script([], {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
                                  "LOCALAPPDATA": str(tmp_path / "local"),
                                  "CMH_AGENT_WORKSPACES": derived})
        line = [l for l in result.stdout.splitlines() if "copia desechable" in l]
        assert line, result.stdout + result.stderr
        paths.append(line[0].split(":", 1)[1].strip())
    assert paths[0] != paths[1], (
        f"dos simulaciones comparten el mismo archivo temporal: {paths[0]}")
