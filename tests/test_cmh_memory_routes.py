"""Memory proposals write only after approval and remain recoverable."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as cdb
from routes import cmh_control_routes as control
from routes import cmh_memory_routes as memory


@pytest.fixture
def api(monkeypatch, tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    canon = root / "CMH_Canon"
    canon.mkdir()
    target = canon / "decision.md"
    target.write_bytes(b"# Before\n")  # explicit LF: write_text emits CRLF on Windows
    monkeypatch.setattr(memory, "CANON_ROOT", canon)
    monkeypatch.setattr(memory, "MIRROR_ROOT", root / "CMH_Claude" / "CMH_Canon")
    monkeypatch.setattr(memory, "BACKUP_ROOT", tmp_path / "backups")
    monkeypatch.setattr(memory, "catalog", lambda: [])
    monkeypatch.setattr(control, "owner_is_admin_or_single_user", lambda owner: owner == "admin")
    engine = create_engine("sqlite:///:memory:")
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(memory, "SessionLocal", factory)
    router = memory.setup_cmh_memory_routes()

    def endpoint(method, path):
        return next(r.endpoint for r in router.routes if r.path == path and method in r.methods)

    yield endpoint, target, tmp_path
    engine.dispose()


def request(owner="admin"):
    return SimpleNamespace(state=SimpleNamespace(current_user=owner))


def loaded(target, proposed_content):
    """A proposal made from the file exactly as it is on disk right now."""
    return memory.ProposalInput(target_path=str(target), proposed_content=proposed_content,
                                base_sha256=memory._hash(target.read_bytes()))


def test_reject_keeps_source_and_approve_can_restore(api):
    endpoint, target, _ = api
    propose = endpoint("POST", "/api/cmh/memory-proposals")
    reject = endpoint("POST", "/api/cmh/memory-proposals/{proposal_id}/reject")
    approve = endpoint("POST", "/api/cmh/memory-proposals/{proposal_id}/approve")
    restore = endpoint("POST", "/api/cmh/memory-proposals/{proposal_id}/restore")
    body = loaded(target, proposed_content="# After\n")
    first = propose(request(), body)
    assert "-# Before" in first["diff"] and "+# After" in first["diff"]
    reject(request(), first["id"])
    assert target.read_text(encoding="utf-8") == "# Before\n"
    second = propose(request(), body)
    applied = approve(request(), second["id"])
    assert target.read_text(encoding="utf-8") == "# After\n"
    assert memory.Path(applied["backup_path"]).read_text(encoding="utf-8") == "# Before\n"
    restore(request(), second["id"])
    assert target.read_text(encoding="utf-8") == "# Before\n"


def test_canon_mirror_follows_master_only_when_it_matched_the_base(api):
    endpoint, target, _ = api
    mirror = memory.MIRROR_ROOT / target.name
    mirror.parent.mkdir(parents=True)
    mirror.write_bytes(target.read_bytes())
    propose = endpoint("POST", "/api/cmh/memory-proposals")
    approve = endpoint("POST", "/api/cmh/memory-proposals/{proposal_id}/approve")
    restore = endpoint("POST", "/api/cmh/memory-proposals/{proposal_id}/restore")
    first = propose(request(), loaded(target, proposed_content="# After\n"))
    assert approve(request(), first["id"])["mirror"] == "synchronized"
    assert mirror.read_bytes() == target.read_bytes() == b"# After\n"
    assert restore(request(), first["id"])["mirror"] == "synchronized"
    assert mirror.read_bytes() == target.read_bytes() == b"# Before\n"
    mirror.write_text("# Mirror-only row\n", encoding="utf-8")
    second = propose(request(), loaded(target, proposed_content="# Again\n"))
    assert approve(request(), second["id"])["mirror"] == "diverged"
    assert mirror.read_text(encoding="utf-8") == "# Mirror-only row\n"


def test_changed_source_blocks_approval_and_other_owner(api):
    endpoint, target, _ = api
    proposal = endpoint("POST", "/api/cmh/memory-proposals")(
        request(), loaded(target, proposed_content="new\n"))
    target.write_text("external edit\n", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        endpoint("POST", "/api/cmh/memory-proposals/{proposal_id}/approve")(request(), proposal["id"])
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        endpoint("GET", "/api/cmh/memories")(request("other"))
    assert exc.value.status_code == 403
    assert target.read_text(encoding="utf-8") == "external edit\n"


def test_textarea_lf_keeps_crlf_file_crlf_and_diff_shows_only_real_change(api):
    endpoint, target, _ = api
    target.write_bytes(b"| a | b |\r\n| 1 | 2 |\r\n")
    propose = endpoint("POST", "/api/cmh/memory-proposals")
    approve = endpoint("POST", "/api/cmh/memory-proposals/{proposal_id}/approve")
    proposal = propose(request(), loaded(target, 
                                                       proposed_content="| a | b |\n| 1 | 2 |\n| 3 | 4 |\n"))
    removed = [line for line in proposal["diff"].splitlines() if line.startswith("-") and not line.startswith("---")]
    assert removed == []
    approve(request(), proposal["id"])
    assert target.read_bytes() == b"| a | b |\r\n| 1 | 2 |\r\n| 3 | 4 |\r\n"


def test_failed_write_leaves_source_and_allows_retry(api, monkeypatch):
    endpoint, target, _ = api
    propose = endpoint("POST", "/api/cmh/memory-proposals")
    approve = endpoint("POST", "/api/cmh/memory-proposals/{proposal_id}/approve")
    proposal = propose(request(), loaded(target, proposed_content="# After\n"))
    real_write = memory._atomic_write

    def locked(path, data):
        raise PermissionError("file locked by sync client")
    monkeypatch.setattr(memory, "_atomic_write", locked)
    with pytest.raises(HTTPException) as exc:
        approve(request(), proposal["id"])
    assert exc.value.status_code == 503
    assert target.read_text(encoding="utf-8") == "# Before\n"
    assert not (memory.BACKUP_ROOT / (proposal["id"] + ".md")).exists()
    monkeypatch.setattr(memory, "_atomic_write", real_write)
    assert approve(request(), proposal["id"])["status"] == "approved"
    assert target.read_text(encoding="utf-8") == "# After\n"


def test_rows_added_after_loading_block_the_proposal(api):
    endpoint, target, _ = api
    stale = loaded(target, "# Before\n| mine |\n")
    target.write_bytes(b"# Before\n| appended by another session |\n")
    with pytest.raises(HTTPException) as exc:
        endpoint("POST", "/api/cmh/memory-proposals")(request(), stale)
    assert exc.value.status_code == 409
    assert target.read_bytes() == b"# Before\n| appended by another session |\n"


def test_only_canon_and_cards_outside_financial_folders_are_writable(api, monkeypatch):
    endpoint, target, tmp_path = api
    vault = tmp_path / "vault"
    monkeypatch.setattr(control, "CMH_ROOT", vault)
    open_folder = vault / "Presentaciones"
    financial = vault / "Modelo Financiero Nuevo"
    (open_folder / "fuentes").mkdir(parents=True)
    financial.mkdir()
    card = open_folder / "00_Proyecto_Presentaciones.md"
    other = open_folder / "notas.md"
    source = open_folder / "fuentes" / "00_Proyecto_Falso.md"
    financial_card = financial / "00_Proyecto_Modelo_Financiero.md"
    for path in (card, other, source, financial_card):
        path.write_bytes(b"# x\n")
    monkeypatch.setattr(memory, "catalog",
                        lambda: [{"card_path": str(p)} for p in (card, other, source, financial_card)])
    propose = endpoint("POST", "/api/cmh/memory-proposals")
    assert propose(request(), loaded(card, "# y\n"))["status"] == "pending"
    for forbidden in (other, source, financial_card):
        with pytest.raises(HTTPException) as exc:
            propose(request(), loaded(forbidden, "# y\n"))
        assert exc.value.status_code == 403
    listed = {m["name"] for m in endpoint("GET", "/api/cmh/memories")(request())["memories"]}
    assert listed == {"00_Proyecto_Presentaciones.md", "decision.md"}
    assert financial_card.read_bytes() == b"# x\n"


