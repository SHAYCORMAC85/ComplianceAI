"""
Storage and Persistence Layer
-----------------------------
SQLite persistence for documents, analysis status,
validated compliance findings, and human review decisions.
"""

import hashlib
import sqlite3
from backend.db.schema import connect, migrate
from contextlib import closing, contextmanager
from pydantic import BaseModel, Field, ValidationError
from datetime import datetime, timezone
import json
import logging
from uuid import UUID
from pathlib import Path
from typing import Any, Dict, List, Optional
from backend.config import DECISIONS_DIR
from backend.models.document import Document
from backend.models.finding import ValidatedFinding, FindingValidationResult
from backend.models.review import ReviewDecision

logger = logging.getLogger(__name__)


class RetryConflict(Exception):
    """The inspection is ineligible for retry."""


class RecoveryError(Exception):
    """Canonical evidence could not be recovered safely."""


def evidence_digest(document):
    evidence = document.model_dump_json(include={"raw_text", "chunks"})
    return hashlib.sha256(evidence.encode("utf-8")).hexdigest()


class DocumentRecord(BaseModel):
    document: Document
    status: str = "UPLOADED"
    error_message: Optional[str] = None
    findings: List[ValidatedFinding] = Field(default_factory=list)
    audit_trail: List[FindingValidationResult] = Field(default_factory=list)
    review_decision: Optional[ReviewDecision] = None
    authorized_provider: str = "mock"
    evidence_hash: Optional[str] = None
    processed_chunks: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentStore:
    """SQLite repository for a single local backend process."""

    def __init__(self, decisions_dir: Optional[Path] = None):
        self.decisions_dir = decisions_dir or DECISIONS_DIR
        self.decisions_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.decisions_dir / "inspections.sqlite3"
        with self.connection() as db:
            migrate(db, "inspections")

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def submission(self, key, digest):
        if key:
            with self.connection() as db:
                row = db.execute("SELECT document_id,digest FROM inspection_jobs WHERE submission_key=?", (key,)).fetchone()
            if row:
                if row[1] != digest:
                    raise RetryConflict("Submission key already belongs to different content.")
                return self.get_status(row[0])

    def enqueue(self, document, key, digest, authorized_provider="mock"):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = self.submission(key, digest)
            if existing:
                return existing
            record = DocumentRecord(document=document, status="QUEUED", authorized_provider=authorized_provider, evidence_hash=evidence_digest(document))
            self._write(db, document.id, record)
            db.execute("INSERT INTO inspection_jobs(document_id,stage,updated_at,submission_key,digest) VALUES (?,'QUEUED',?,?,?)",
                       (document.id, self._now(), key, digest))
        return {"document_id": document.id, "filename": document.filename, "file_type": document.file_type, "status": "QUEUED"}

    def _queue(self, db, doc_id):
        db.execute("""
            INSERT INTO inspection_jobs(document_id,stage,updated_at) VALUES (?,'QUEUED',?)
            ON CONFLICT(document_id) DO UPDATE SET stage='QUEUED',updated_at=excluded.updated_at,
            analyzed=0,cached=0,skipped=0,failed=0,retry_at=NULL
        """, (doc_id, self._now()))

    def recover_jobs(self):
        """Called once with exclusive process ownership, before workers start."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for (doc_id,) in db.execute("""SELECT id FROM inspections WHERE
                    json_extract(record,'$.status') IN ('PROCESSING','UPLOADED','QUEUED')
                    AND json_type(record,'$.review_decision') IS NOT 'object'""").fetchall():
                self._queue(db, doc_id)
                db.execute("UPDATE inspections SET record=json_set(record,'$.status','QUEUED','$.processed_chunks',0) WHERE id=?", (doc_id,))

    def claim_job(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document_id FROM inspection_jobs WHERE stage='QUEUED' ORDER BY updated_at,rowid LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE inspection_jobs SET stage='PREPARING',updated_at=? WHERE document_id=?", (self._now(), row[0]))
                db.execute("UPDATE inspections SET record=json_set(record,'$.status','PROCESSING') WHERE id=?", row)
                return row[0]

    def job_progress(self, doc_id, stage, outcome=None, retry_at=None):
        with self.connection() as db:
            db.execute("""UPDATE inspection_jobs SET stage=?,retry_at=?,updated_at=?,
                       analyzed=analyzed+?,cached=cached+?,skipped=skipped+?,failed=failed+?
                       WHERE document_id=? AND stage NOT IN ('FAILED','COMPLETED')""",
                       (stage, retry_at, self._now(), outcome=="analyzed", outcome=="cached",
                        outcome=="skipped", outcome=="failed", doc_id))

    def load_job_document(self, doc_id, restore_original, provider="mock"):
        with self.connection() as db:
            row = db.execute("SELECT record FROM inspections WHERE id=?", (doc_id,)).fetchone()
            data = json.loads(row[0])
            if provider != "mock" and data.get("authorized_provider") != provider:
                raise RecoveryError("External processing authorization required. Review the provider and retry.")
            document = self._recover_document(doc_id, data, restore_original)
            data["document"] = document
            self._write(db, doc_id, DocumentRecord.model_validate(data))
            return document

    @contextmanager
    def connection(self):
        with closing(connect(self.path)) as db, db:
            yield db

    def _write(self, db, doc_id, rec):
        rec.updated_at = datetime.now(timezone.utc)
        db.execute("INSERT INTO inspections VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET record=excluded.record", (doc_id, rec.model_dump_json()))

    def _get(self, doc_id):
        with self.connection() as db:
            row = db.execute("SELECT record FROM inspections WHERE id = ?", (doc_id,)).fetchone()
        return DocumentRecord.model_validate_json(row[0]) if row else None

    def add_document(self, document: Document, status: str = "UPLOADED") -> None:
        with self.connection() as db:
            self._write(db, document.id, DocumentRecord(document=document, status=status, evidence_hash=evidence_digest(document)))

    def claim_retry(self, document_id, restore_original, authorized_provider="mock"):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT record FROM inspections WHERE id=?", (document_id,)).fetchone()
            if row is None:
                raise KeyError(document_id)
            try:
                data = json.loads(row[0])
                if data["status"] != "FAILED" or data.get("review_decision") or self._legacy_decision(document_id):
                    raise RetryConflict("Only a failed, unsigned inspection can be retried.")
                if db.execute("SELECT 1 FROM review_history WHERE document_id=?", (document_id,)).fetchone():
                    raise RetryConflict("This inspection already has a recorded decision.")
                data["document"] = self._recover_document(document_id, data, restore_original)
                record = DocumentRecord.model_validate(data)
                record.authorized_provider = authorized_provider
                record.status = "QUEUED"
                record.error_message = None
                record.processed_chunks = 0
                self._write(db, document_id, record)
                self._queue(db, document_id)
                return record.document
            except (ValidationError, KeyError, TypeError, ValueError) as exc:
                raise RecoveryError("The saved inspection is unreadable. Upload the source as a new inspection.") from exc

    def _recover_document(self, document_id, data, restore_original):
        saved = data["document"]
        expected = data.get("evidence_hash")
        try:
            doc = Document.model_validate(saved)
        except ValidationError:
            doc = None
        if doc and doc.id == document_id and self._valid_chunk_slices(doc):
            if not expected or evidence_digest(doc) == expected:
                return doc
        if not expected:
            raise RecoveryError("Stored evidence cannot be verified. Upload the source as a new inspection.")
        restored = restore_original(document_id, saved["filename"])
        if evidence_digest(restored) != expected:
            raise RecoveryError("The original no longer matches the saved evidence. Upload a new inspection.")
        restored.id = document_id
        saved.update(restored.model_dump(exclude={"created_at"}))
        return Document.model_validate(saved)

    @staticmethod
    def _valid_chunk_slices(doc):
        end = 0
        for i, chunk in enumerate(doc.chunks):
            start = chunk.char_start
            if (chunk.index != i or start < end or chunk.char_end > len(doc.raw_text)
                    or doc.raw_text[end:start].strip() or doc.raw_text[start:chunk.char_end] != chunk.text):
                return False
            end = chunk.char_end
        return bool(doc.chunks) and not doc.raw_text[end:].strip()

    def read_checkpoint(self, key):
        with self.connection() as db:
            row = db.execute("SELECT result FROM chunk_checkpoints WHERE cache_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_checkpoint(self, document_id, key, findings):
        payload = json.dumps([finding.model_dump(mode="json") for finding in findings])
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO chunk_checkpoints SELECT ?,id,? FROM inspections WHERE id=?", (key, payload, document_id))

    def get_document(self, document_id: str) -> Optional[Document]:
        rec = self._get(document_id)
        return rec.document if rec else None

    def update_status(self, document_id, status, error_message=None):
        now = self._now()
        with self.connection() as db:
            changed = db.execute("""
                UPDATE inspections SET record=json_set(record,'$.status',?,'$.error_message',?,'$.updated_at',?)
                WHERE id=?
            """, (status, error_message, now, document_id)).rowcount
            if status == "FAILED":
                db.execute("UPDATE inspection_jobs SET stage='FAILED',updated_at=? WHERE document_id=?", (now, document_id))
        return bool(changed)

    def fail_if_processing(self, doc_id, message):
        with self.connection() as db:
            now = self._now()
            changed = db.execute("""
                UPDATE inspections SET record=json_set(record,'$.status','FAILED','$.error_message',?,'$.updated_at',?)
                WHERE id=? AND json_extract(record,'$.status')='PROCESSING'
            """, (message, now, doc_id)).rowcount
            if changed:
                db.execute("UPDATE inspection_jobs SET stage='FAILED',updated_at=? WHERE document_id=?", (now, doc_id))

    def get_status(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves current processing status details."""
        with self.connection() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("""
                SELECT id AS document_id,json_extract(record,'$.document.filename') AS filename,
                  json_extract(record,'$.document.file_type') AS file_type,json_extract(record,'$.status') AS status,
                  json_array_length(record,'$.document.chunks') AS chunks_count,
                  json_extract(record,'$.document.total_chars') AS total_chars,
                  json_extract(record,'$.error_message') AS error_message,
                  json_type(record,'$.review_decision') IS 'object' AS has_decision,
                  coalesce(j.updated_at,json_extract(record,'$.updated_at')) AS updated_at,
                  coalesce(j.stage,json_extract(record,'$.status')) AS stage,
                  analyzed,cached,skipped,failed,retry_at,json_extract(record,'$.processed_chunks') AS legacy_count
                FROM inspections LEFT JOIN inspection_jobs j ON id=j.document_id WHERE id=?
            """, (document_id,)).fetchone()
        if row is None:
            return None
        info = dict(row)
        legacy = info.pop("legacy_count") or 0
        tracked = info["analyzed"] is not None
        for name in ("analyzed","cached","skipped","failed"):
            info[name] = info[name] or 0
        done = info["analyzed"] + info["cached"]
        info["progress_tracked"] = tracked
        info["processed_chunks"] = done if tracked else legacy
        total = info["chunks_count"] or 0
        info["progress_percent"] = (100 if info["status"] == "COMPLETED" else
                                    min(99, (done + info["skipped"]) * 100 // total) if total else None)
        return info

    def save_findings(
        self,
        document_id: str,
        findings: List[ValidatedFinding],
        audit_trail: List[FindingValidationResult]
    ) -> bool:
        """Stores validated findings and full audit trail for a document."""
        rec = self._get(document_id)
        if not rec:
            return False
        rec.findings = findings
        rec.audit_trail = audit_trail
        rec.status = "COMPLETED"
        rec.processed_chunks = len(rec.document.chunks)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            counts = db.execute("""SELECT analyzed+cached+skipped, failed, analyzed+cached
                                   FROM inspection_jobs WHERE document_id=?""", (document_id,)).fetchone()
            if counts and (counts[0] != len(rec.document.chunks) or counts[1] or not counts[2]):
                raise RuntimeError("Incomplete inspection cannot be finalized.")
            self._write(db, document_id, rec)
            db.execute("UPDATE inspection_jobs SET stage='COMPLETED',updated_at=?,retry_at=NULL WHERE document_id=?", (self._now(), document_id))
            db.execute("DELETE FROM chunk_checkpoints WHERE document_id=?", (document_id,))
        return True

    def get_findings(self, document_id: str) -> Optional[List[ValidatedFinding]]:
        """Returns only strictly validated findings for a document."""
        rec = self._get(document_id)
        if not rec:
            return None
        return list(rec.findings)

    def get_audit_trail(self, document_id: str) -> Optional[List[FindingValidationResult]]:
        """Returns complete validation audit trail for a document."""
        rec = self._get(document_id)
        if not rec:
            return None
        return list(rec.audit_trail)

    def record_decision(self, decision: ReviewDecision) -> ReviewDecision:
        """
        Commits a final officer decision with its completed inspection.
        
        Args:
            decision: Verified ReviewDecision model.
            
        Returns:
            The recorded ReviewDecision.
            
        Raises:
            KeyError: If document_id does not exist.
        """
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT record FROM inspections WHERE id=?", (decision.document_id,)).fetchone()
            if row is None:
                raise KeyError(decision.document_id)
            rec = DocumentRecord.model_validate_json(row[0])
            if rec.status != "COMPLETED" or rec.review_decision or self._legacy_decision(decision.document_id):
                raise ValueError("A decision requires a completed inspection awaiting review.")
            rec.review_decision = decision
            self._write(db, decision.document_id, rec)
            db.execute("INSERT INTO review_history VALUES (?, ?)", (decision.document_id, decision.model_dump_json()))

        return decision

    def get_decision(self, document_id: str) -> Optional[ReviewDecision]:
        """Retrieves the review decision for a document if one has been recorded."""
        rec = self._get(document_id)
        if rec and rec.review_decision:
            return rec.review_decision

        return self._legacy_decision(document_id)

    def review_history(self, document_id: str) -> List[ReviewDecision]:
        with self.connection() as db:
            row = db.execute("SELECT decision FROM review_history WHERE document_id=?", (document_id,)).fetchone()
        if row:
            return [ReviewDecision.model_validate_json(row[0])]
        legacy = self._legacy_decision(document_id)
        return [legacy] if legacy else []

    def _legacy_decision(self, document_id):
        # Legacy JSON files are historical records; never rewrite them.
        try:
            if str(UUID(document_id)) != document_id:
                return None
        except ValueError:
            return None
        decision_file = self.decisions_dir / f"{document_id}.json"
        try:
            decision = ReviewDecision.model_validate_json(decision_file.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise RecoveryError("Historical decision is unreadable. Inspect storage before review.") from exc
        if decision.document_id != document_id:
            raise RecoveryError("Historical decision identity mismatch.")
        return decision

    def get_document_text(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves raw extracted text and metadata for a document."""
        rec = self._get(document_id)
        if not rec:
            return None
        return {
            "document_id": rec.document.id,
            "filename": rec.document.filename,
            "file_type": rec.document.file_type,
            "raw_text": rec.document.raw_text,
            "total_chars": rec.document.total_chars
        }

    def list_documents(self) -> List[Dict[str, Any]]:
        """Returns metadata summaries for all currently tracked documents."""
        with self.connection() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("""
                SELECT id AS document_id,json_extract(record,'$.document.filename') AS filename,
                json_extract(record,'$.document.file_type') AS file_type,json_extract(record,'$.status') AS status,
                json_array_length(record,'$.document.chunks') AS chunks_count,
                json_extract(record,'$.document.total_chars') AS total_chars,
                json_array_length(record,'$.findings') AS findings_count,
                json_type(record,'$.review_decision') IS 'object' AS has_decision,
                json_extract(record,'$.review_decision.decision') AS decision,
                json_extract(record,'$.updated_at') AS updated_at FROM inspections ORDER BY rowid DESC
            """)]

# Global storage singleton
document_store = DocumentStore()

