"""All storage and disaster recovery tests operate on synthetic, isolated data."""
from contextlib import closing
import errno
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from backend import officers, storage_backup as recovery
from backend.api import routes_documents
from backend.db.schema import VERSION, exclusive_owner
from backend.db.store import DocumentStore, document_store
from backend.main import app
from backend.models.review import ReviewDecision


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = document_store.decisions_dir.parent
    uploads = root / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(routes_documents, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(officers, "DATA_DIR", root)
    officers.enroll("test-reviewer", "synthetic-password")
    (root/".env").write_text("synthetic excluded environment")
    token = officers.sign_in("test-reviewer", "synthetic-password")["token"]
    with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
        def inspect(name, content):
            upload = client.post("/api/documents/upload", headers={"Idempotency-Key":name},
                                 files={"file":(name, content)})
            assert upload.status_code == 202
            url = upload.json()["status_url"]
            for _ in range(200):
                state = client.get(url).json()
                if state["status"] in ("COMPLETED","FAILED"):
                    return state
                time.sleep(.01)
            pytest.fail("Timed out")
        signed = inspect("example.txt",b"Our fund offers guaranteed returns.")
        failed = inspect("short.txt",b"abc")
        assert failed["status"] == "FAILED"
        token = client.post("/api/review/session",auth=("test-reviewer","synthetic-password")).json()["token"]
        result = client.post("/api/review/"+signed["document_id"]+"/decision",headers={"Authorization":"Bearer "+token},
                             json={"decision":"REJECTED","notes":"Synthetic review."})
        assert result.status_code == 200
    return root, signed["document_id"], failed["document_id"]


def test_real_restart_and_restored_store(source,tmp_path):
    root,signed,failed = source
    # Use new interpreters to discard every session, singleton and memory cache.
    probe = """
import hashlib,json,sys
from backend.db.store import document_store as store
from backend.officers import sessions, sign_in
from backend.config import UPLOADS_DIR
assert not sessions
assert sign_in('test-reviewer','synthetic-password')['officer_id']=='test-reviewer'
rows=[]
for doc_id in sys.argv[1:]:
    doc=store.get_document(doc_id)
    status=store.get_status(doc_id)
    findings=store.get_findings(doc_id)
    assert all(doc.raw_text[f.offset_start:f.offset_end]==f.passage for f in findings)
    history=store.review_history(doc_id)
    with store.connection() as db:
        record=db.execute('SELECT record FROM inspections WHERE id=?',(doc_id,)).fetchone()[0]
        job=db.execute('SELECT * FROM inspection_jobs WHERE document_id=?',(doc_id,)).fetchone()
    original=(UPLOADS_DIR/(doc_id+'_'+doc.filename)).read_bytes()
    rows.append([record,job,original.hex(),[x.model_dump(mode='json') for x in history]])
    if doc_id==sys.argv[1]:
        assert findings and store.get_audit_trail(doc_id) and history[0].officer_id=='test-reviewer'
    else:
        assert status['status']=='FAILED' and status['error_message']
print(hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest())
"""
    def restarted_digest(data):
        return subprocess.check_output([sys.executable,"-B","-c",probe,signed,failed],
                                       env=dict(os.environ,COMPLIANCE_DATA_DIR=str(data)),text=True).strip()
    before = restarted_digest(root)
    archive = tmp_path.parent / (tmp_path.name+"-backup")
    dest = tmp_path.parent / (tmp_path.name+"-restored")
    recovery.backup(root,archive)
    manifest = recovery.verify(archive)
    assert manifest["schemas"] == {recovery.INSPECTIONS:VERSION,recovery.OFFICERS:VERSION}
    assert ".env" not in manifest["files"] and not (archive/".env").exists()
    recovery.restore(archive,dest)
    assert restarted_digest(dest)==before


def test_fk_uniqueness_and_rollback(source):
    root,signed,_ = source
    with document_store.connection() as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        for table in ("review_history","chunk_checkpoints","inspection_jobs"):
            assert db.execute(f"PRAGMA foreign_key_list({table})").fetchone()[2]=="inspections"
    with pytest.raises(sqlite3.IntegrityError), document_store.connection() as db:
        db.execute("INSERT INTO chunk_checkpoints VALUES ('transient',?,'[]')",(signed,))
        db.execute("INSERT INTO chunk_checkpoints VALUES ('orphan','missing','[]')")
    assert document_store.read_checkpoint("transient") is None
    with pytest.raises(sqlite3.IntegrityError), document_store.connection() as db:
        db.execute("INSERT INTO inspection_jobs(document_id,stage,updated_at) VALUES (?,'QUEUED','now')",(signed,))


def test_dirty_legacy_migration_is_atomic(tmp_path):
    path=tmp_path/"legacy"
    path.mkdir()
    dbfile=path/"inspections.sqlite3"
    with closing(sqlite3.connect(dbfile)) as db, db:
        db.execute("CREATE TABLE inspections(id TEXT PRIMARY KEY,record TEXT NOT NULL)")
        db.execute("CREATE TABLE chunk_checkpoints(cache_key TEXT PRIMARY KEY,document_id TEXT,result TEXT)")
        db.execute("INSERT INTO chunk_checkpoints VALUES ('old','unknown','[]')")
    with pytest.raises(sqlite3.IntegrityError):
        DocumentStore(path)
    with closing(sqlite3.connect(dbfile)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==0
        assert db.execute("SELECT cache_key FROM chunk_checkpoints").fetchone()==("old",)
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'migrate_old_%' OR name='review_history'").fetchone()


def test_backup_refuses_active_or_missing_evidence(source,tmp_path):
    root,_,_ = source
    dest=tmp_path.parent/(tmp_path.name+"-invalid")
    with exclusive_owner(root/"decisions"), pytest.raises(RuntimeError):
        recovery.backup(root,dest)
    next((root/"uploads").glob("*.txt")).unlink()
    with pytest.raises(ValueError):
        recovery.backup(root,dest)
    assert not dest.exists()


@pytest.mark.parametrize("fault",["content","version","manifest","extra","full","existing"])
def test_failed_restore_is_not_published(source,tmp_path,monkeypatch,fault):
    root,_,_ = source
    archive=tmp_path.parent/(tmp_path.name+"-backup")
    dest=tmp_path.parent/(tmp_path.name+"-destination")
    recovery.backup(root,archive)
    if fault=="content":
        next((archive/"uploads").glob("*.txt")).write_bytes(b"damaged")
    elif fault=="version":
        with closing(sqlite3.connect(archive/recovery.INSPECTIONS)) as db:
            db.execute("PRAGMA user_version=999")
    elif fault=="manifest":
        (archive/recovery.MANIFEST).write_text("{}")
    elif fault=="extra":
        (archive/".env").write_text("unlisted")
    elif fault=="full":
        def full(*args):
            raise OSError(errno.ENOSPC,"simulated capacity failure")
        monkeypatch.setattr(recovery.shutil,"copyfile",full)
    else:
        dest.mkdir()
        (dest/"marker").write_text("unchanged")
    with pytest.raises((ValueError,OSError)):
        recovery.restore(archive,dest)
    if fault=="existing":
        assert (dest/"marker").read_text()=="unchanged"
    else:
        assert not dest.exists()


def test_write_lock_never_reports_success(source):
    _, signed, _ = source
    with document_store.connection() as lock:
        lock.execute("BEGIN IMMEDIATE")
        with document_store.connection() as blocked:
            blocked.execute("PRAGMA busy_timeout=20")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                blocked.execute("UPDATE inspection_jobs SET stage='FAILED' WHERE document_id=?",(signed,))
    assert document_store.get_status(signed)["stage"]=="COMPLETED"

def test_checkpoint_and_unlinked_evidence_survive_backup(source,tmp_path):
    from uuid import uuid4
    root,_,failed = source
    document_store.save_checkpoint(failed,"valid-empty",[])
    historical = str(uuid4())
    legacy = ReviewDecision(document_id=historical,officer_id="former-reviewer",decision="REJECTED")
    (root/"decisions"/(historical+".json")).write_text(legacy.model_dump_json())
    original = root/"uploads"/(historical+"_older.txt")
    original.write_bytes(b"unindexed synthetic original")
    archive=tmp_path.parent/(tmp_path.name+"-backup")
    dest=tmp_path.parent/(tmp_path.name+"-restored")
    recovery.backup(root,archive)
    recovery.restore(archive,dest)
    store=DocumentStore(dest/"decisions")
    assert store.read_checkpoint("valid-empty")==[]
    assert store.review_history(historical)==[legacy]
    assert (dest/"uploads"/original.name).read_bytes()==original.read_bytes()


def test_sqlite_full_rolls_back_without_partial_history(source):
    root,_,failed=source
    with document_store.connection() as db:
        pages=db.execute("PRAGMA page_count").fetchone()[0]
        db.execute(f"PRAGMA max_page_count={pages}")
        with pytest.raises(sqlite3.OperationalError,match="full"):
            db.execute("INSERT INTO chunk_checkpoints VALUES ('too-large',?,json_array(hex(zeroblob(2000000))))",(failed,))
    assert document_store.read_checkpoint("too-large") is None
    assert document_store.get_status(failed)["status"]=="FAILED"


def test_bad_historical_decision_blocks_signoff(source):
    root,_,doc_id=source
    document_store.update_status(doc_id,"COMPLETED")
    legacy=root/"decisions"/(doc_id+".json")
    legacy.write_text("damaged")
    from backend.db.store import RecoveryError
    with pytest.raises(RecoveryError):
        document_store.record_decision(ReviewDecision(document_id=doc_id,officer_id="synthetic",decision="APPROVED"))
    assert not document_store.get_status(doc_id)["has_decision"]
    assert legacy.read_text()=="damaged"

def test_replace_cannot_bypass_immutable_history(source):
    _,signed,_=source
    with pytest.raises(sqlite3.IntegrityError), document_store.connection() as db:
        db.execute("INSERT OR REPLACE INTO review_history SELECT * FROM review_history WHERE document_id=?",(signed,))
    assert document_store.review_history(signed)[0].decision.value=="REJECTED"


def test_legacy_snapshot_restores_then_migrates(source,tmp_path):
    root,signed,_=source
    # Model the audited older layout: signed inspection JSON without a jobs/history table.
    old=tmp_path.parent/(tmp_path.name+"-legacy")
    (old/"decisions").mkdir(parents=True)
    (old/"uploads").mkdir()
    with document_store.connection() as db:
        row=db.execute("SELECT id,record FROM inspections WHERE id=?",(signed,)).fetchone()
    with closing(sqlite3.connect(old/recovery.INSPECTIONS)) as db,db:
        db.execute("CREATE TABLE inspections(id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        db.execute("INSERT INTO inspections VALUES (?,?)",row)
    recovery.shutil.copyfile(root/"uploads"/(signed+"_example.txt"),old/"uploads"/(signed+"_example.txt"))
    archive=tmp_path.parent/(tmp_path.name+"-backup")
    dest=tmp_path.parent/(tmp_path.name+"-restored")
    recovery.backup(old,archive)
    assert recovery.verify(archive)["schemas"]=={recovery.INSPECTIONS:0}
    recovery.restore(archive,dest)
    restored=DocumentStore(dest/"decisions")
    assert restored.get_decision(signed)==document_store.get_decision(signed)
    assert restored.review_history(signed)==document_store.review_history(signed)
    assert not restored.get_status(signed)["progress_tracked"]
