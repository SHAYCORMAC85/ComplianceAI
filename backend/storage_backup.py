"""Offline backup/restore for ComplianceAI. Run python -m backend.storage_backup --help."""
import argparse
from backend.security_events import event
from contextlib import closing
import hashlib
import json
from pathlib import Path, PureWindowsPath
import shutil
import sqlite3
import stat
import tempfile
import time
from uuid import UUID

from backend.db.schema import VERSION, exclusive_owner, tables, version, connect, migrate
from backend.models.document import Document
from backend.models.finding import FindingValidationResult, RawFinding, ValidatedFinding
from backend.models.review import ReviewDecision

INSPECTIONS = "decisions/inspections.sqlite3"
OFFICERS = "officers.sqlite3"
MANIFEST = "manifest.json"


def checked_path(path):
    if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("Linked files and directories cannot be backed up or restored.")


def safe_name(relative):
    parts = relative.split("/")
    name = parts[-1]
    if any(not part or part in (".","..") or "\\" in part or ":" in part or
           part.rstrip(" .") != part or PureWindowsPath(part).is_reserved() for part in parts):
        return False
    if relative in (INSPECTIONS, OFFICERS):
        return True
    if len(parts) != 2:
        return False
    try:
        uid = str(UUID(name[:36]))
    except ValueError:
        return False
    if not name.startswith(uid):
        return False
    return ((parts[0] == "uploads" and name[36:37] == "_" and Path(name).suffix.lower() in (".txt",".pdf",".docx"))
            or (parts[0] == "decisions" and name == uid + ".json"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)


def inspect_database(root, relative):
    kind = "inspections" if relative == INSPECTIONS else "officers"
    with closing(readonly(root / relative)) as db:
        number = version(db, kind)
        present = tables(db)
        required = {"officers"} if kind == "officers" else {"inspections","review_history","chunk_checkpoints","inspection_jobs"}
        if present - required or (number == VERSION and present != required) or kind not in present:
            raise ValueError("Unexpected database schema.")
        if number == VERSION:
            # Compare app-owned DDL against a clean schema, including immutable-history triggers.
            with closing(connect(":memory:")) as reference:
                migrate(reference, kind)
                schema_sql = ("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                              "AND name != 'inspections' ORDER BY type,name")
                if list(db.execute(schema_sql)) != list(reference.execute(schema_sql)):
                    raise ValueError("Database constraints, triggers or indexes differ from the supported schema.")
        if kind == "inspections" and [r[1] for r in db.execute("PRAGMA table_info(inspections)")] != ["id","record"]:
            raise ValueError("Unsupported inspection table.")
        if list(db.execute("PRAGMA integrity_check")) != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("SQLite integrity verification failed.")
        if kind == "officers":
            if db.execute("SELECT 1 FROM officers WHERE name IS NULL OR trim(name)='' OR length(salt) IS NOT 16 OR length(digest) IS NOT 64").fetchone():
                raise ValueError("Invalid stored officer account.")
            return number
        for child in present - {"inspections"}:
            if number and not any(r[2:5] == ("inspections","document_id","id") for r in db.execute(f"PRAGMA foreign_key_list({child})")):
                raise ValueError("Missing inspection foreign key.")
            if db.execute(f"SELECT 1 FROM {child} c LEFT JOIN inspections i ON i.id=c.document_id WHERE i.id IS NULL LIMIT 1").fetchone():
                raise ValueError("Unlinked database records.")
        for doc_id, payload in db.execute("SELECT id,record FROM inspections"):
            record = json.loads(payload)
            if record["status"] not in {"UPLOADED","QUEUED","PROCESSING","FAILED","COMPLETED"}:
                raise ValueError("Unknown inspection state.")
            doc = Document.model_validate(record["document"])
            relative_source = f"uploads/{doc_id}_{PureWindowsPath(doc.filename).name}"
            if doc.id != doc_id or not safe_name(relative_source) or not (root/relative_source).is_file():
                raise ValueError("Original evidence missing or document identity inconsistent.")
            if record.get("evidence_hash"):
                canonical = doc.model_dump_json(include={"raw_text","chunks"}).encode()
                if hashlib.sha256(canonical).hexdigest() != record["evidence_hash"]:
                    raise ValueError("Canonical evidence digest mismatch.")
            for chunk in doc.chunks:
                if doc.raw_text[chunk.char_start:chunk.char_end] != chunk.text:
                    raise ValueError("Chunk offsets disagree with source evidence.")
            findings = [ValidatedFinding.model_validate(f) for f in record.get("findings", [])]
            for audit in record.get("audit_trail", []):
                validated = FindingValidationResult.model_validate(audit).validated_finding
                if validated:
                    findings.append(validated)
            if any(f.document_id != doc_id or f.offset_end > len(doc.raw_text) or
                   doc.raw_text[f.offset_start:f.offset_end] != f.passage for f in findings):
                raise ValueError("Finding offsets disagree with source evidence.")
            signed = record.get("review_decision")
            decision = ReviewDecision.model_validate(signed) if signed else None
            if decision and (decision.document_id != doc_id or record["status"] != "COMPLETED"):
                raise ValueError("Invalid signed inspection.")
            if "review_history" in present:
                row = db.execute("SELECT decision FROM review_history WHERE document_id=?",(doc_id,)).fetchone()
                if (ReviewDecision.model_validate_json(row[0]) if row else None) != decision:
                    raise ValueError("Inspection and audit history disagree.")
            if "inspection_jobs" in present:
                row = db.execute("SELECT digest,stage FROM inspection_jobs WHERE document_id=?", (doc_id,)).fetchone()
                if row:
                    stage = row[1]
                    state = "PROCESSING" if stage in {"PREPARING","ANALYZING","VALIDATING","FINALIZING","WAITING_FOR_QUOTA"} else stage
                    if state != record["status"]:
                        raise ValueError("Job and inspection lifecycle states disagree.")
                if row and row[0]:
                    digest = hashlib.sha256(("."+doc.file_type).encode()+b"\0")
                    with (root/relative_source).open("rb") as stream:
                        for block in iter(lambda: stream.read(1024*1024), b""):
                            digest.update(block)
                    if digest.hexdigest() != row[0]:
                        raise ValueError("Original file differs from submission digest.")
        if "chunk_checkpoints" in present:
            for (payload,) in db.execute("SELECT result FROM chunk_checkpoints"):
                values = json.loads(payload)
                if not isinstance(values,list):
                    raise ValueError("Invalid checkpoint.")
                for value in values:
                    RawFinding.model_validate(value)
        return number


def manifest(root):
    files = {}
    schemas = {}
    for path in sorted(root.rglob("*")):
        checked_path(path)
        name = path.relative_to(root).as_posix()
        if path.is_dir():
            if name not in ("uploads","decisions"):
                raise ValueError("Unexpected directory in backup.")
            continue
        if name == MANIFEST:
            continue
        if not safe_name(name) or not path.is_file():
            raise ValueError("Unexpected file in backup.")
        files[name] = {"bytes":path.stat().st_size,"sha256":sha(path)}
        if name.startswith("decisions/") and name.endswith(".json"):
            if ReviewDecision.model_validate_json(path.read_bytes()).document_id != path.stem:
                raise ValueError("Legacy decision identity mismatch.")
    if INSPECTIONS not in files:
        raise ValueError("Inspection database missing.")
    for relative in (INSPECTIONS, OFFICERS):
        if relative in files:
            schemas[relative] = inspect_database(root,relative)
    return {"format":1,"schemas":schemas,"files":files}


def verify(root):
    checked_path(root)
    checked_path(root/MANIFEST)
    saved = json.loads((root/MANIFEST).read_text(encoding="utf-8"))
    if saved != manifest(root):
        raise ValueError("Backup manifest or integrity check failed.")
    return saved


def publish(source, destination, operation):
    checked_path(source)
    source, destination = source.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Choose a fresh destination outside the source directory.")
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".compliance-staging-") as temp:
        stage = Path(temp)/"data"
        stage.mkdir()
        operation(source,stage)
        if destination.exists():
            raise FileExistsError("Destination already exists.")
        stage.rename(destination)


def backup(source, destination):
    def create(root, stage):
        checked_path(root/"decisions")
        with exclusive_owner(root/"decisions"):
            for name in (INSPECTIONS, OFFICERS):
                path = root/name
                if name == OFFICERS and not path.exists():
                    continue
                checked_path(path)
                target = stage/name
                target.parent.mkdir(exist_ok=True)
                with closing(readonly(path)) as src, closing(sqlite3.connect(target)) as dst:
                    deadline = time.monotonic() + 5
                    def check_lock(status, remaining, total):
                        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) and time.monotonic() >= deadline:
                            raise TimeoutError("Database backup is blocked by a writer.")
                    src.backup(dst, pages=256, progress=check_lock)
                    dst.execute("PRAGMA journal_mode=DELETE")
            for folder in ("uploads","decisions"):
                (stage/folder).mkdir(exist_ok=True)
                if not (root/folder).exists():
                    continue
                checked_path(root/folder)
                for path in (root/folder).iterdir():
                    name = path.relative_to(root).as_posix()
                    if safe_name(name):
                        checked_path(path)
                        shutil.copyfile(path, stage/name)
            (stage/MANIFEST).write_text(json.dumps(manifest(stage),indent=2),encoding="utf-8")
            verify(stage)
    publish(source,destination,create)


def restore(source, destination):
    def copy(root, stage):
        saved = verify(root)
        for name in saved["files"]:
            target = stage/name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(root/name,target)
        if manifest(stage) != saved:
            raise ValueError("Staged restore failed verification.")
    publish(source,destination,copy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action",required=True)
    for name in ("backup","verify","restore"):
        sub = commands.add_parser(name)
        sub.add_argument("source",type=Path)
        if name != "verify":
            sub.add_argument("destination",type=Path)
    args = parser.parse_args()
    event(args.action, "started")
    try:
        if args.action == "verify":
            verify(args.source)
        elif args.action == "backup":
            backup(args.source,args.destination)
        else:
            restore(args.source,args.destination)
    except (ValueError, OSError, RuntimeError, sqlite3.Error, KeyError, TypeError):
        event(args.action, "failed")
        parser.exit(1,"Operation failed. Check storage integrity, free space, supported schema, offline access and destination.\n")
    event(args.action, "success")
    print("Verification passed." if args.action=="verify" else "Verified copy created.")


if __name__ == "__main__":
    main()
