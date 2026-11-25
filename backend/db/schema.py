"""Transactional migrations for the two local SQLite databases."""
from contextlib import contextmanager
import json
import os
import sqlite3

VERSION = 1
APPLICATION_IDS = {"inspections": 0x43414949, "officers": 0x4341494F}


def connect(path):
    db = sqlite3.connect(path, timeout=3)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA recursive_triggers=ON")
    return db


@contextmanager
def exclusive_owner(directory):
    """The backend and offline backup share this OS-released lock."""
    with (directory / "worker.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("The data directory is in use. Stop the backend before maintenance.") from exc
        yield


def tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def version(db, kind):
    number = db.execute("PRAGMA user_version").fetchone()[0]
    app_id = db.execute("PRAGMA application_id").fetchone()[0]
    if number not in (0, VERSION) or app_id != (APPLICATION_IDS[kind] if number else 0):
        raise ValueError("Unsupported database version or application ID.")
    return number


def replace_table(db, table, definition, columns):
    # Single explicit transaction in migrate() includes every DDL and copy.
    exists = table in tables(db)
    if exists:
        db.execute(f"ALTER TABLE {table} RENAME TO migrate_old_{table}")
    db.execute(f"CREATE TABLE {table} ({definition})")
    if exists:
        db.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM migrate_old_{table}")
        db.execute(f"DROP TABLE migrate_old_{table}")


def migrate(db, kind):
    if version(db, kind) == VERSION:
        return
    with db:
        db.execute("BEGIN IMMEDIATE")
        if version(db, kind) == VERSION:
            return
        existing = tables(db)
        allowed = {"officers"} if kind == "officers" else {"inspections","review_history","chunk_checkpoints","inspection_jobs"}
        if existing - allowed or (existing and kind == "inspections" and "inspections" not in existing):
            raise ValueError("Unrecognized legacy database layout.")
        if kind == "officers":
            replace_table(db, "officers", """name TEXT PRIMARY KEY NOT NULL CHECK(length(trim(name))>0),
                salt BLOB NOT NULL CHECK(length(salt)=16), digest BLOB NOT NULL CHECK(length(digest)=64)""", "name,salt,digest")
        else:
            migrate_inspections(db)
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Database contains unlinked records.")
        db.execute(f"PRAGMA application_id={APPLICATION_IDS[kind]}")
        db.execute(f"PRAGMA user_version={VERSION}")


def migrate_inspections(db):
    db.execute("CREATE TABLE IF NOT EXISTS inspections (id TEXT PRIMARY KEY NOT NULL, record TEXT NOT NULL)")
    parent = "TEXT NOT NULL REFERENCES inspections(id) ON DELETE RESTRICT"
    replace_table(db, "review_history", f"document_id {parent} PRIMARY KEY, decision TEXT NOT NULL CHECK(json_valid(decision))",
                  "document_id,decision")
    replace_table(db, "chunk_checkpoints", f"cache_key TEXT PRIMARY KEY NOT NULL, document_id {parent}, result TEXT NOT NULL CHECK(json_type(result)='array')",
                  "cache_key,document_id,result")
    replace_table(db, "inspection_jobs", f"""document_id {parent} PRIMARY KEY, stage TEXT NOT NULL,
        updated_at TEXT NOT NULL, analyzed INTEGER NOT NULL DEFAULT 0 CHECK(analyzed>=0),
        cached INTEGER NOT NULL DEFAULT 0 CHECK(cached>=0), skipped INTEGER NOT NULL DEFAULT 0 CHECK(skipped>=0),
        failed INTEGER NOT NULL DEFAULT 0 CHECK(failed>=0), retry_at TEXT, submission_key TEXT UNIQUE, digest TEXT""",
        "document_id,stage,updated_at,analyzed,cached,skipped,failed,retry_at,submission_key,digest")
    db.execute("""INSERT INTO review_history(document_id,decision)
        SELECT id,json_extract(record,'$.review_decision') FROM inspections
        WHERE json_type(record,'$.review_decision')='object' ON CONFLICT(document_id) DO NOTHING""")
    if db.execute("""SELECT 1 FROM inspections WHERE id IS NULL OR length(id)=0
            OR json_extract(record,'$.document.id') IS NOT id LIMIT 1""").fetchone():
        raise ValueError("Inspection identity mismatch.")
    if db.execute("""SELECT 1 FROM review_history h JOIN inspections i ON i.id=h.document_id
            WHERE json_extract(i.record,'$.status') IS NOT 'COMPLETED'
            OR json_extract(h.decision,'$.document_id') IS NOT i.id LIMIT 1""").fetchone():
        raise ValueError("Historical decision conflicts with inspection.")
    # Compare JSON objects semantically; whitespace or property order is irrelevant.
    for original, history in db.execute("""SELECT json_extract(record,'$.review_decision'),decision
            FROM inspections JOIN review_history ON id=document_id"""):
        if not original or json.loads(original) != json.loads(history):
            raise ValueError("Decision history conflicts with recorded sign-off.")
    for op in ("UPDATE","DELETE"):
        db.execute(f"""CREATE TRIGGER protect_history_{op} BEFORE {op} ON review_history
            BEGIN SELECT RAISE(ABORT,'Decision history is immutable'); END""")
    db.execute("DROP TRIGGER IF EXISTS freeze_signed_inspection")
    db.execute("""CREATE TRIGGER freeze_signed_inspection BEFORE UPDATE ON inspections
        WHEN json_type(OLD.record,'$.review_decision')='object' BEGIN SELECT RAISE(ABORT,'Signed inspection'); END""")
    db.execute("""CREATE TRIGGER prevent_signed_delete BEFORE DELETE ON inspections
        WHEN json_type(OLD.record,'$.review_decision')='object' BEGIN SELECT RAISE(ABORT,'Signed inspection'); END""")
    db.execute("CREATE INDEX jobs_stage ON inspection_jobs(stage, updated_at)")
    db.execute("CREATE INDEX checkpoint_document ON chunk_checkpoints(document_id)")
