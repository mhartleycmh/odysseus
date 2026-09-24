"""CMH source-file memory proposals with explicit approval and recovery."""

import difflib
import hashlib
import os
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.database import CMHMemoryProposal, SessionLocal
from routes.cmh_control_routes import CMH_ROOT, _admin, _owner, catalog, in_financial_area

CANON_ROOT = CMH_ROOT / "CMH_Canon"
# The vault keeps a byte-identical copy of the canon inside CMH_Claude.
MIRROR_ROOT = CMH_ROOT / "CMH_Claude" / "CMH_Canon"
BACKUP_ROOT = Path(__file__).resolve().parents[1] / "data" / "cmh_memory_backups"
MAX_BYTES = 200_000
# Decision 2026-09-24 (canon 05): "no widening of access to financial
# folders" wins over editing every card from Odysseus. Set True to allow it.
CARDS_IN_FINANCIAL_AREAS_WRITABLE = False
# Approve and restore check a hash and then write. Handlers run in a
# threadpool, so serialize them: two decisions on one file must not both pass.
_WRITE_LOCK = threading.Lock()


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "Memory file is not UTF-8 text") from exc


def _match_newlines(before: bytes, proposed: str) -> str:
    """Keep CRLF files CRLF: a browser textarea hands content back with bare LF."""
    if b"\r\n" in before and "\r\n" not in proposed:
        return proposed.replace("\n", "\r\n")
    return proposed


def _sync_mirror(target: Path, expected: bytes, data: bytes) -> str:
    """Update the canon mirror only if it held exactly the bytes the write replaced.

    Anything else means the mirror has rows the master lacks; overwriting it
    would lose them, so it is left for a manual row-union merge.
    """
    canon = CANON_ROOT.resolve()
    if not target.is_relative_to(canon):
        return "not_applicable"
    mirror = MIRROR_ROOT / target.relative_to(canon)
    try:
        if not mirror.is_file():
            return "missing"
        if mirror.resolve() == target:
            return "not_applicable"
        if mirror.read_bytes() != expected:
            return "diverged"
        _atomic_write(mirror, data)
    except OSError:
        return "error"
    return "synchronized"


def _authorized_file(raw: str) -> Path:
    try:
        path = Path(raw).resolve(strict=True)
        canon = CANON_ROOT.resolve(strict=True)
        cards = {Path(p["card_path"]).resolve(strict=True) for p in catalog()}
    except (OSError, ValueError) as exc:
        raise HTTPException(400, "Memory file is unavailable") from exc
    if not path.is_file() or path.suffix.lower() != ".md":
        raise HTTPException(400, "Only existing Markdown files may be proposed")
    if any(part.casefold() == "fuentes" for part in path.parts):
        raise HTTPException(403, "Source folders are read-only")
    is_card = path in cards and path.name.casefold().startswith("00_proyecto")
    if not is_card and not path.is_relative_to(canon):
        raise HTTPException(403, "Memory file is outside approved sources")
    # Odysseus gets no write path into financial or production folders, not
    # even for the project card they hold: those cards are edited in the vault.
    if is_card and not CARDS_IN_FINANCIAL_AREAS_WRITABLE and in_financial_area(path):
        raise HTTPException(403, "Project card lies in a protected folder; edit it in the vault")
    if path.stat().st_size > MAX_BYTES:
        raise HTTPException(413, "Memory file is too large")
    return path


def _atomic_write(path: Path, data: bytes):
    handle, temporary = tempfile.mkstemp(prefix=".cmh-memory-", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ProposalInput(BaseModel):
    target_path: str
    proposed_content: str = Field(max_length=MAX_BYTES)
    # SHA-256 of the file as the author loaded it. Without it, rows another
    # session appended in between would show up only as deletions.
    base_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def setup_cmh_memory_routes() -> APIRouter:
    router = APIRouter(prefix="/api/cmh", tags=["cmh-memory"])

    @router.get("/memories")
    def memories(request: Request):
        owner = _owner(request); _admin(owner)
        files = [Path(p["card_path"]) for p in catalog()]
        files.extend(sorted(CANON_ROOT.rglob("*.md")))
        result = []
        for candidate in files:
            try:
                path = _authorized_file(str(candidate))
                result.append({"path": str(path), "name": path.name,
                               "modified": path.stat().st_mtime,
                               "source": "Canon CMH" if path.is_relative_to(CANON_ROOT.resolve()) else "Ficha de proyecto"})
            except HTTPException:
                continue
        return {"memories": result}

    @router.get("/memories/content")
    def content(request: Request, path: str):
        owner = _owner(request); _admin(owner)
        target = _authorized_file(path)
        data = target.read_bytes()
        return {"path": str(target), "content": _decode(data), "sha256": _hash(data)}

    @router.post("/memory-proposals", status_code=201)
    def propose(request: Request, body: ProposalInput):
        owner = _owner(request); _admin(owner)
        target = _authorized_file(body.target_path)
        before = target.read_bytes()
        if _hash(before) != body.base_sha256:
            raise HTTPException(409, "File changed since it was loaded; reload it before proposing")
        before_text = _decode(before)
        proposed = _match_newlines(before, body.proposed_content)
        after = proposed.encode("utf-8")
        if len(after) > MAX_BYTES:
            raise HTTPException(413, "Proposal is too large")
        if before == after:
            raise HTTPException(400, "Proposal has no changes")
        diff = "".join(difflib.unified_diff(before_text.splitlines(True),
                                            proposed.splitlines(True),
                                            fromfile=str(target), tofile="proposed"))
        with SessionLocal() as db:
            row = CMHMemoryProposal(id=str(uuid.uuid4()), owner=owner,
                                    target_path=str(target), base_hash=_hash(before),
                                    proposed_content=proposed, diff=diff, status="pending")
            db.add(row); db.commit()
            return {"id": row.id, "status": row.status, "diff": diff}

    @router.get("/memory-proposals")
    def proposals(request: Request):
        owner = _owner(request); _admin(owner)
        with SessionLocal() as db:
            rows = db.query(CMHMemoryProposal).filter(CMHMemoryProposal.owner == owner).order_by(
                CMHMemoryProposal.created_at.desc()).limit(50).all()
            return {"proposals": [{"id": r.id, "path": r.target_path, "status": r.status,
                                   "mirror": r.mirror_status,
                                   "created_at": r.created_at.isoformat() if r.created_at else None}
                                  for r in rows]}

    @router.get("/memory-proposals/{proposal_id}")
    def proposal_detail(request: Request, proposal_id: str):
        owner = _owner(request); _admin(owner)
        with SessionLocal() as db:
            row = db.query(CMHMemoryProposal).filter_by(id=proposal_id, owner=owner).first()
            if not row:
                raise HTTPException(404, "Proposal not found")
            return {"id": row.id, "path": row.target_path, "status": row.status,
                    "diff": row.diff, "base_hash": row.base_hash,
                    "applied_hash": row.applied_hash, "mirror": row.mirror_status}

    @router.post("/memory-proposals/{proposal_id}/reject")
    def reject(request: Request, proposal_id: str):
        owner = _owner(request); _admin(owner)
        with SessionLocal() as db:
            row = db.query(CMHMemoryProposal).filter_by(id=proposal_id, owner=owner).first()
            if not row:
                raise HTTPException(404, "Proposal not found")
            if row.status != "pending":
                raise HTTPException(409, "Proposal already decided")
            row.status = "rejected"
            db.commit()
            return {"id": row.id, "status": row.status}

    @router.post("/memory-proposals/{proposal_id}/approve")
    def approve(request: Request, proposal_id: str):
        owner = _owner(request); _admin(owner)
        with _WRITE_LOCK, SessionLocal() as db:
            row = db.query(CMHMemoryProposal).filter_by(id=proposal_id, owner=owner).first()
            if not row:
                raise HTTPException(404, "Proposal not found")
            if row.status != "pending":
                raise HTTPException(409, "Proposal already decided")
            target = _authorized_file(row.target_path)
            before = target.read_bytes()
            if _hash(before) != row.base_hash:
                raise HTTPException(409, "Source changed after proposal; preview again")
            BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
            backup = BACKUP_ROOT / (row.id + ".md")
            if backup.exists():
                raise HTTPException(409, "Backup already exists")
            with backup.open("xb") as stream:
                stream.write(before)
                stream.flush()
                os.fsync(stream.fileno())
            new_data = row.proposed_content.encode("utf-8")
            try:
                _atomic_write(target, new_data)
            except OSError as exc:
                # The replace never happened, so the source is intact; drop
                # the backup so the proposal can be approved again.
                backup.unlink(missing_ok=True)
                raise HTTPException(503, "Memory file could not be written; nothing changed") from exc
            row.backup_path = str(backup)
            row.applied_hash = _hash(new_data)
            row.mirror_status = _sync_mirror(target, before, new_data)
            row.status = "approved"
            db.commit()
            return {"id": row.id, "status": row.status, "backup_path": row.backup_path,
                    "mirror": row.mirror_status}

    @router.post("/memory-proposals/{proposal_id}/restore")
    def restore(request: Request, proposal_id: str):
        owner = _owner(request); _admin(owner)
        with _WRITE_LOCK, SessionLocal() as db:
            row = db.query(CMHMemoryProposal).filter_by(id=proposal_id, owner=owner).first()
            if not row:
                raise HTTPException(404, "Proposal not found")
            if row.status != "approved" or not row.backup_path:
                raise HTTPException(409, "No approved backup to restore")
            target = _authorized_file(row.target_path)
            current = target.read_bytes()
            if _hash(current) != row.applied_hash:
                raise HTTPException(409, "Source changed after approval; cannot restore automatically")
            try:
                backup = Path(row.backup_path).resolve(strict=True)
            except OSError as exc:
                raise HTTPException(409, "Backup file is missing; restore manually") from exc
            if not backup.is_relative_to(BACKUP_ROOT.resolve()):
                raise HTTPException(403, "Backup path is invalid")
            original = backup.read_bytes()
            try:
                _atomic_write(target, original)
            except OSError as exc:
                raise HTTPException(503, "Memory file could not be restored; nothing changed") from exc
            row.mirror_status = _sync_mirror(target, current, original)
            row.status = "restored"
            db.commit()
            return {"id": row.id, "status": row.status, "mirror": row.mirror_status}

    return router
