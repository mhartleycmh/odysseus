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


#: Synthetic originals, versioned with the tests. The real ones live outside
#: the repository and are deliberately not versioned: they carry financial file
#: names, so committing them to make a count reproduce would be the leak the
#: scrubber exists to prevent.
SOURCES = REPO / "tests" / "fixtures" / "agent_sources"


@pytest.fixture
def derived(tmp_path, monkeypatch):
    """Generate the five files into a throwaway tree.

    Reading data/agent_workspace made these tests depend on untracked local
    state: .gitignore excludes data/, so a clean checkout failed 3 of 18 while
    the declared count said 225. Generating them here also exercises main(),
    which nothing did before.
    """
    monkeypatch.setattr(scrub, "TARGET", tmp_path)
    monkeypatch.setattr(scrub, "SOURCE", SOURCES)
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
                   env={**os.environ, "CMH_AGENT_WORKSPACES": str(root),
                        "CMH_AGENT_SOURCES": str(SOURCES)})
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
    result = _run_script(["--apply", "--authorized-by", "prueba", "--allow-pending"],
                         {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
                          "LOCALAPPDATA": str(tmp_path / "local"),
                          "CMH_AGENT_WORKSPACES": str(_derived_tree(tmp_path))})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "provider_policy" in columns(), "la migracion no corrio"


def test_applying_backs_up_before_it_writes(tmp_path):
    live = tmp_path / "app.db"
    _legacy_database(live)
    backups = tmp_path / "local"
    result = _run_script(["--apply", "--authorized-by", "prueba", "--allow-pending"],
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

    result = _run_script(["--apply", "--authorized-by", "prueba", "--allow-pending"],
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
    result = _run_script([], {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
                              "LOCALAPPDATA": str(tmp_path / "local"),
                              "CMH_AGENT_WORKSPACES": str(_derived_tree(tmp_path))})
    assert "SIMULACION" in result.stdout, result.stdout + result.stderr
    # Only THIS process's replica is looked at, by the path the script prints. The test
    # used to compare every cmh-seed-dryrun-*.db in the shared temp folder before and
    # after, so another run in parallel (a mutation campaign, a second pytest) that
    # created its own replica in that window made it fail: the baseline of round2 came
    # out red for exactly that reason on 2026-09-30.
    lines = [l for l in result.stdout.splitlines() if "copia desechable" in l]
    assert lines, result.stdout
    replica = pathlib.Path(lines[0].split(":", 1)[1].strip())
    assert replica.name.startswith("cmh-seed-dryrun-") and replica.suffix == ".db"
    assert not replica.exists(), f"copia huerfana: {replica}"


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
                   env={**os.environ, "CMH_AGENT_WORKSPACES": str(forbidden),
                        "CMH_AGENT_SOURCES": str(SOURCES)})
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


def test_a_valid_but_unnormalised_policy_is_normalised_before_planning(tmp_path):
    """M16 of the fourth review: the three typo tests only covered INVALID
    values, so passing the raw string to plan() survived all 275 tests. A valid
    spelling in the wrong case is the case that slips through — and its effect
    is the same one the script is supposed to prevent: five agents on the cloud
    under a banner that reads local-only."""
    live = tmp_path / "app.db"
    _legacy_database(live)
    connection = sqlite3.connect(live)
    connection.execute(
        "CREATE TABLE model_endpoints (id TEXT PRIMARY KEY, name TEXT, base_url TEXT, "
        "api_key TEXT, is_enabled BOOLEAN, hidden_models TEXT, cached_models TEXT, "
        "pinned_models TEXT, model_type TEXT, endpoint_kind TEXT, "
        "model_refresh_mode TEXT, model_refresh_interval INTEGER, "
        "model_refresh_timeout INTEGER, supports_tools BOOLEAN, owner TEXT, "
        "provider_auth_id TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)")
    connection.execute(
        "INSERT INTO model_endpoints (id, name, base_url, is_enabled, endpoint_kind, "
        "cached_models) VALUES ('groq', 'groq', 'https://api.groq.com/openai/v1', 1, "
        "'api', '[\"openai/gpt-oss-120b\"]')")
    connection.commit()
    connection.close()

    result = _run_script(["--policy", "LOCAL-ONLY"],
                         {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
                          "LOCALAPPDATA": str(tmp_path / "local"),
                          "CMH_AGENT_WORKSPACES": str(_derived_tree(tmp_path)),
                          "CMH_AGENT_SOURCES": str(SOURCES)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "politica: local-only" in result.stdout
    assert "'groq'" not in result.stdout, (
        "una grafia valida sin normalizar no puede resolver candidatos de nube")


# --- step 3.5: the definition, the stored policy, the empty chain, the backup name ---
#
# Found by the audit of 2026-09-29. Until then the script created five agents and
# NO definition (that half of 3.5 was a manual click with a different name), did not
# store the policy it was given, would seed five agents with no model, ignored
# ODYSSEUS_DATA_DIR when locating the database it backs up, and named its backup with
# minute resolution and no check that the name was free.

GROQ_URL = "https://api.groq.com/openai/v1"
LM_STUDIO_URL = "http://127.0.0.1:1234/v1"


def _database_with_endpoints(path, endpoints):
    """A full-schema database with the given (url, kind) endpoints, made by the real
    core.database in a subprocess: importing it in-process would point it at the
    test session's database."""
    script = (
        "import json, sys\n"
        "import core.database as c\n"
        "with c.SessionLocal() as db:\n"
        "    for i, entry in enumerate(json.loads(sys.argv[1])):\n"
        "        url, kind = entry[0], entry[1]\n"
        "        key = entry[2] if len(entry) > 2 else ('gsk-TEST-DUMMY' if kind == 'api' else None)\n"
        "        db.add(c.ModelEndpoint(id=f'e{i}', name=f'e{i}', base_url=url,\n"
        "                               endpoint_kind=kind, is_enabled=True, api_key=key))\n"
        "    db.commit()\n")
    subprocess.run([sys.executable, "-c", script, json.dumps(endpoints)], cwd=str(REPO),
                   check=True, capture_output=True, text=True,
                   env={**os.environ, "DATABASE_URL": f"sqlite:///{path.as_posix()}"})


def _seed_env(tmp_path, live, **extra):
    return {"DATABASE_URL": f"sqlite:///{live.as_posix()}",
            "LOCALAPPDATA": str(tmp_path / "local"),
            "CMH_AGENT_WORKSPACES": str(_derived_tree(tmp_path)),
            "CMH_AGENT_SOURCES": str(SOURCES), **extra}


def _stored(live):
    con = sqlite3.connect(live)
    try:
        return {
            "agents": con.execute(
                "SELECT id, name, status, instructions_version, provider_policy, model, task_id "
                "FROM cmh_agents ORDER BY name").fetchall(),
            "tasks": con.execute("SELECT COUNT(*) FROM scheduled_tasks").fetchone()[0],
            "definitions": con.execute(
                "SELECT id, version, name, steps FROM cmh_workflow_definitions "
                "ORDER BY version").fetchall(),
        }
    finally:
        con.close()


APPLY = ["--apply", "--authorized-by", "prueba"]


def test_seeding_twice_gives_five_agents_and_one_definition_and_the_second_run_changes_nothing(
        tmp_path):
    """H16 of the audit: the docstring promised idempotence and no test ran --apply
    twice and counted. Rows, ids and versions must be byte-for-byte what they were."""
    live = tmp_path / "app.db"
    _database_with_endpoints(live, [(GROQ_URL, "api")])
    env = _seed_env(tmp_path, live)
    first = _run_script(APPLY, env)
    assert first.returncode == 0, first.stdout + first.stderr
    once = _stored(live)
    assert len(once["agents"]) == 5 and once["tasks"] == 5 and len(once["definitions"]) == 1
    second = _run_script(APPLY, env)
    assert second.returncode == 0, second.stdout + second.stderr
    assert _stored(live) == once
    assert "igual" in second.stdout


def test_the_definition_has_the_shape_the_control_view_builds(tmp_path):
    live = tmp_path / "app.db"
    _database_with_endpoints(live, [(GROQ_URL, "api")])
    result = _run_script(APPLY, _seed_env(tmp_path, live))
    assert result.returncode == 0, result.stdout + result.stderr
    stored = _stored(live)
    (_, version, name, steps_json), = stored["definitions"]
    steps = json.loads(steps_json)
    assert (version, name) == (1, seed.DEFINITION_NAME)
    assert [s["key"] for s in steps] == ["investigador", "constructor", "verificador",
                                         "revisor", "documentador"]
    assert {s["key"]: s["depends_on"] for s in steps} == {
        "investigador": [], "constructor": ["investigador"], "verificador": ["constructor"],
        "revisor": ["constructor", "verificador"], "documentador": ["constructor", "revisor"]}
    assert {s["key"]: s["independent_of"] for s in steps} == {
        "investigador": [], "constructor": [], "verificador": ["constructor"],
        "revisor": ["constructor"], "documentador": []}
    assert {s["key"]: s["requires_approval"] for s in steps} == {
        "investigador": False, "constructor": False, "verificador": False,
        "revisor": True, "documentador": False}
    assert {s["key"]: s["require_tool_evidence"] for s in steps} == {
        "investigador": True, "constructor": True, "verificador": True,
        "revisor": False, "documentador": False}
    by_name = {row[1]: row[0] for row in stored["agents"]}
    assert {s["key"]: s["agent_id"] for s in steps} == {
        "investigador": by_name["Investigador"], "constructor": by_name["Constructor"],
        "verificador": by_name["Verificador"], "revisor": by_name["Revisor"],
        "documentador": by_name["Documentador"]}
    assert len({s["agent_id"] for s in steps}) == 5   # independent_of needs distinct agents


def test_a_stored_definition_that_differs_gets_a_new_version_and_the_old_one_is_left_alone(
        tmp_path):
    """Definitions are never edited in place: a run freezes the steps it started from."""
    live = tmp_path / "app.db"
    _database_with_endpoints(live, [(GROQ_URL, "api")])
    env = _seed_env(tmp_path, live)
    assert _run_script(APPLY, env).returncode == 0
    (definition_id, _, _, original), = _stored(live)["definitions"]
    tampered = json.loads(original)
    tampered[3]["requires_approval"] = False          # someone removed the human gate
    con = sqlite3.connect(live)
    con.execute("UPDATE cmh_workflow_definitions SET steps = ? WHERE id = ?",
                (json.dumps(tampered), definition_id))
    con.commit()
    con.close()
    second = _run_script(APPLY, env)
    assert second.returncode == 0, second.stdout + second.stderr
    rows = _stored(live)["definitions"]
    assert [row[1] for row in rows] == [1, 2]
    assert json.loads(rows[0][3]) == tampered            # the old version is untouched
    assert json.loads(rows[1][3]) == json.loads(original)  # the new one is the real shape
    assert "nueva version" in second.stdout


def test_it_refuses_to_seed_an_empty_chain_and_writes_nothing(tmp_path):
    live = tmp_path / "app.db"
    _database_with_endpoints(live, [])
    env = _seed_env(tmp_path, live)
    refused = _run_script(APPLY, env)
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert "No se sembro nada" in refused.stdout and "--allow-pending" in refused.stdout
    assert "puedes borrarla" not in refused.stdout      # opening the base may have migrated it
    stored = _stored(live)
    assert stored["agents"] == [] and stored["definitions"] == [] and stored["tasks"] == 0


def test_allow_pending_seeds_anyway_and_the_agents_have_no_model_until_it_is_run_again(tmp_path):
    live = tmp_path / "app.db"
    _database_with_endpoints(live, [])
    env = _seed_env(tmp_path, live)
    assert _run_script(APPLY + ["--allow-pending"], env).returncode == 0
    assert [row[5] for row in _stored(live)["agents"]] == [None] * 5


def test_the_policy_is_stored_on_every_agent(tmp_path):
    """--policy used to be validated, used to resolve candidates and dropped, so
    local-only left NULL and the run resolved free-cloud-first."""
    for policy, model in (("free-cloud-first", "openai/gpt-oss-120b"),
                          ("local-only", "cmh-local")):
        live = tmp_path / f"{policy}.db"
        _database_with_endpoints(live, [(GROQ_URL, "api"), (LM_STUDIO_URL, "local")])
        result = _run_script(APPLY + ["--policy", policy],
                             _seed_env(tmp_path / policy, live))
        assert result.returncode == 0, result.stdout + result.stderr
        agents = _stored(live)["agents"]
        assert [row[4] for row in agents] == [policy] * 5, policy
        assert [row[5] for row in agents] == [model] * 5, policy


def test_the_live_path_follows_odysseus_data_dir_like_core_database_does(tmp_path, monkeypatch):
    """After the data folder moves out of OneDrive (22.1) the backup must be taken of
    the NEW file. Ignoring the variable backed up the old one, or none, and then wrote
    to the new one with no copy."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ODYSSEUS_DATA_DIR", str(tmp_path / "datos"))
    assert seed.live_database_path() == tmp_path / "datos" / "app.db"
    monkeypatch.delenv("ODYSSEUS_DATA_DIR")
    assert seed.live_database_path() == seed.REPO / "data" / "app.db"
    # a relative DATABASE_URL is resolved against the app root, as core.database does
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/otra.db")
    assert seed.live_database_path() == seed.REPO / pathlib.Path("./data/otra.db")


def test_a_second_backup_in_the_same_second_does_not_overwrite_the_first(tmp_path, monkeypatch):
    import datetime as real
    import types

    class Frozen(real.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 29, 12, 0, 0)

    monkeypatch.setattr(seed, "datetime", types.SimpleNamespace(datetime=Frozen))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    source = tmp_path / "app.db"
    con = sqlite3.connect(source)
    con.execute("CREATE TABLE t (a TEXT)")
    con.execute("INSERT INTO t VALUES ('antes')")
    con.commit()
    first = seed.backup_database(source, "prueba")
    con.execute("UPDATE t SET a = 'despues'")
    con.commit()
    con.close()
    second = seed.backup_database(source, "prueba")
    assert first != second and first.exists() and second.exists()
    read = lambda p: sqlite3.connect(p).execute("SELECT a FROM t").fetchone()[0]
    assert (read(first), read(second)) == ("antes", "despues")


def test_a_console_that_cannot_print_the_names_does_not_end_the_script(tmp_path):
    """The summary comes after the database write. A print that raised
    UnicodeEncodeError ended the script with a traceback where a report was owed."""
    live = tmp_path / "app.db"
    _database_with_endpoints(live, [(GROQ_URL, "api")])
    result = _run_script(APPLY, _seed_env(tmp_path, live, PYTHONIOENCODING="ascii"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Definicion" in result.stdout


# --- review of 2026-09-29: the backup URI, the dry run on nothing, the empty-chain guard ------

def test_the_backup_of_a_path_with_a_hash_and_a_space_copies_the_real_database(
        tmp_path, monkeypatch):
    """The URI was built by hand: an unescaped '#' cut it short, dropped mode=ro and made
    SQLite create an empty file beside the folder, and the script printed
    'integrity origen=ok copia=ok' over an empty copy."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    folder = tmp_path / "datos #1 de prueba"
    folder.mkdir()
    source = folder / "app.db"
    con = sqlite3.connect(source)
    con.execute("CREATE TABLE t (a TEXT)")
    con.execute("INSERT INTO t VALUES ('x')")
    con.commit()
    con.close()
    before = {p.name for p in tmp_path.iterdir()}
    target = seed.backup_database(source, "prueba")
    assert sqlite3.connect(target).execute("SELECT a FROM t").fetchone()[0] == "x"
    assert {p.name for p in tmp_path.iterdir()} - before == {"local"}    # nothing stray beside it


def test_a_copy_that_lacks_the_tables_of_the_source_is_refused(tmp_path, monkeypatch):
    """integrity_check answers 'ok' for an EMPTY file too."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    source = tmp_path / "app.db"
    con = sqlite3.connect(source)
    con.execute("CREATE TABLE t (a TEXT)")
    con.commit()
    con.close()
    answers = iter([["a", "b"], []])                   # the source has two tables, the copy none
    monkeypatch.setattr(seed, "_table_names", lambda connection: next(answers))
    with pytest.raises(RuntimeError, match="mismas tablas"):
        seed.backup_database(source, "prueba")


def test_a_dry_run_on_a_database_that_does_not_exist_creates_nothing(tmp_path):
    """Importing core.database creates a complete database at whatever path it is pointed
    at: the script then ended with 'SIMULACION: no se escribio nada'."""
    missing = tmp_path / "no-existe" / "app.db"
    result = _run_script([], _seed_env(tmp_path, missing))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no existe" in result.stdout and "en memoria" in result.stdout
    assert not missing.exists() and not missing.parent.exists()


def test_local_endpoints_alone_do_not_open_the_gate_of_apply_under_free_cloud_first(tmp_path):
    """ADR-034 said --apply stops when there is no free candidate. With the live endpoints
    (two Ollama rows still enabled) the guard never fired: they count as local candidates
    under the local identifier, and five agents were written pointing at a runtime nobody
    serves. Under free-cloud-first a free CLOUD candidate is what makes them usable."""
    live = tmp_path / "app.db"
    _database_with_endpoints(live, [("http://127.0.0.1:11434", "local")])
    before = _stored(live)
    dry = _run_script([], _seed_env(tmp_path, live))
    assert "solo hay endpoints locales" in dry.stdout, dry.stdout + dry.stderr
    refused = _run_script(APPLY, _seed_env(tmp_path, live))
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert "No se sembro nada" in refused.stdout and "puedes borrarla" not in refused.stdout
    assert _stored(live) == before


def test_under_local_only_a_local_endpoint_is_enough(tmp_path):
    live = tmp_path / "app.db"
    _database_with_endpoints(live, [("http://127.0.0.1:11434", "local")])
    result = _run_script(APPLY + ["--policy", "local-only"], _seed_env(tmp_path, live))
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_stored(live)["agents"]) == 5


def test_has_usable_route_by_policy():
    local = {"host": "127.0.0.1"}
    groq = {"host": "api.groq.com"}
    assert seed.has_usable_route([groq, local], "free-cloud-first") is True
    assert seed.has_usable_route([local], "free-cloud-first") is False
    assert seed.has_usable_route([], "free-cloud-first") is False
    assert seed.has_usable_route([local], "local-only") is True
    assert seed.has_usable_route([], "local-only") is False


# --- review of revision-fase1-r7: keys, a '#' in every path, and --apply on nothing ---------

def test_a_cloud_candidate_without_a_registered_key_is_not_a_usable_route():
    groq = {"host": "api.groq.com", "endpoint_id": "g"}
    assert seed.has_usable_route([groq], "free-cloud-first", keyed={"g"}) is True
    assert seed.has_usable_route([groq], "free-cloud-first", keyed=set()) is False
    assert seed.has_usable_route([groq], "free-cloud-first", keyed=None) is True   # not asked
    local = {"host": "127.0.0.1", "endpoint_id": "l"}
    assert seed.has_usable_route([local], "local-only", keyed=set()) is True       # no key needed


def test_groq_registered_without_its_key_does_not_open_the_gate_of_apply(tmp_path):
    """Groq answers 401 to a request with no key and 401 is not a reason to change provider:
    the first step would stop before it reached the local fallback, and --apply had written
    five agents pointing at it."""
    live = tmp_path / "app.db"
    _database_with_endpoints(live, [(GROQ_URL, "api", None)])
    before = _stored(live)
    dry = _run_script([], _seed_env(tmp_path, live))
    assert "SIN clave" in dry.stdout, dry.stdout + dry.stderr
    refused = _run_script(APPLY, _seed_env(tmp_path, live))
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert "No se sembro nada" in refused.stdout and _stored(live) == before
    keyed = tmp_path / "keyed.db"
    _database_with_endpoints(keyed, [(GROQ_URL, "api")])                   # the default key
    assert _run_script(APPLY, _seed_env(tmp_path, keyed)).returncode == 0


def test_the_plan_says_which_rows_the_router_left_out_and_why(tmp_path):
    live = tmp_path / "app.db"
    _database_with_endpoints(live, [("http://api.groq.com/openai/v1", "api")])      # plain http
    result = _run_script([], _seed_env(tmp_path, live))
    assert "DESCARTADO: endpoint e0 (api.groq.com)" in result.stdout, result.stdout
    assert "compuerta de costo cero" in result.stdout
    assert _run_script(APPLY, _seed_env(tmp_path, live)).returncode == 2


def _hash_folder(tmp_path):
    folder = tmp_path / "datos #1 de prueba"
    folder.mkdir()
    return folder / "app.db"


def test_a_dry_run_on_a_database_in_a_folder_with_a_hash_reads_the_real_database(tmp_path):
    """Built by hand, the URI of the simulation was cut at the '#': SQLite opened an EMPTY
    database with integrity 'ok' beside the folder, and the plan was computed on nothing."""
    live = _hash_folder(tmp_path)
    _database_with_endpoints(live, [(GROQ_URL, "api")])
    env = _seed_env(tmp_path, live)
    before = sorted(p.name for p in tmp_path.iterdir())
    result = _run_script([], env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Candidatos resueltos: ['e0']" in result.stdout        # it SAW the endpoint
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_apply_on_a_database_in_a_folder_with_a_hash_checks_the_real_database(tmp_path):
    live = _hash_folder(tmp_path)
    _database_with_endpoints(live, [(GROQ_URL, "api")])
    env = _seed_env(tmp_path, live)
    before = {p.name for p in tmp_path.iterdir()}
    result = _run_script(APPLY, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "integrity_check posterior: ok" in result.stdout
    assert len(_stored(live)["agents"]) == 5
    assert {p.name for p in tmp_path.iterdir()} - before == {"local"}   # only the backup folder


def test_apply_on_a_database_that_does_not_exist_writes_it_to_disk_and_not_to_memory(tmp_path):
    """The in-memory escape is for the SIMULATION only. --apply with no file must never seed
    a database in memory, throw it away and print a success."""
    folder = tmp_path / "vacio"
    folder.mkdir()
    missing = folder / "app.db"
    result = _run_script(APPLY + ["--allow-pending"], _seed_env(tmp_path, missing))
    assert result.returncode == 0, result.stdout + result.stderr
    assert missing.exists()
    assert len(_stored(missing)["agents"]) == 5
    assert "en memoria" not in result.stdout
