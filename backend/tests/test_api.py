"""
Integration Tests for FastAPI REST API Layer
--------------------------------------------
Tests endpoints:
- POST /api/documents/upload (TXT, PDF, DOCX, validation, size limits, errors)
- GET /api/documents/{doc_id}/findings (validated findings, 404 handling)
- GET /api/documents/{doc_id}/status (status polling, 404 handling)
- POST /api/review/{doc_id}/decision (human approval, rejection, validation)
- GET /api/review/{doc_id}/decision (decision retrieval)
"""

import json
import time
import io
from pathlib import Path
import docx
from fastapi.testclient import TestClient
import pymupdf
import pytest
from backend.db.store import document_store
from backend.officers import enroll
from backend.main import app
from backend.services.compliance_service import compliance_service
from backend.services.llm_orchestrator import LLMOrchestrator

client = TestClient(app)


def post_inspection(url, **kwargs):
    """Wait only in tests that need the outcome; return the original HTTP response."""
    response = client.post(url, **kwargs)
    if response.status_code == 202:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = client.get(response.json()["status_url"]).json()
            if status["status"] in ("FAILED", "COMPLETED"):
                break
            time.sleep(.01)
        else:
            pytest.fail("Inspection did not reach a terminal state")
    return response


@pytest.fixture(scope="module", autouse=True)
def workers(workspace_headers):
    client.headers.update(workspace_headers)
    with client:
        yield


@pytest.fixture(scope="module")
def officer_headers():
    enroll("test_officer", "synthetic-test-password")
    response = client.post("/api/review/session", auth=("test_officer", "synthetic-test-password"))
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


@pytest.fixture(autouse=True)
def clean_store():
    """Clears in-memory store before each test for total isolation."""
    original_orchestrator = compliance_service.llm_orchestrator
    compliance_service.llm_orchestrator = LLMOrchestrator(provider_name="mock")
    yield
    compliance_service.llm_orchestrator = original_orchestrator


@pytest.fixture
def sample_txt_bytes():
    content = (
        "Article 1: Preliminary Disclosure.\n"
        "All investments involve risk.\n\n"
        "Article 2: Returns Policy.\n"
        "We offer guaranteed returns of 18% per annum with absolutely no risk of loss."
    )
    return content.encode("utf-8")


@pytest.fixture
def sample_pdf_bytes():
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text(
        (50, 72),
        "Section 1: Guarantees.\n\n"
        "We offer guaranteed returns of 18% per annum with absolutely no risk of loss."
    )
    data = pdf.tobytes()
    pdf.close()
    return data


@pytest.fixture
def sample_docx_bytes():
    doc = docx.Document()
    doc.add_paragraph("Section 1: Regulatory Standard.")
    doc.add_paragraph("A hidden processing fee of 3.5% will be assessed unilaterally without prior notice.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ==============================================================================
# Health & Root Endpoint Tests
# ==============================================================================

def test_root_endpoint():
    """Verify root endpoint returns 200 with service information."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "AI Compliance" in data["service"]


def test_health_check_endpoint():
    """Verify health check endpoint returns 200 and configuration details."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "llm_provider" in data


# ==============================================================================
# Document Upload Tests
# ==============================================================================

def test_upload_txt_successful(sample_txt_bytes: bytes):
    """Verify uploading a TXT document triggers extraction, inspection, and persistence."""
    response = post_inspection(
        "/api/documents/upload",
        files={"file": ("prospectus.txt", sample_txt_bytes, "text/plain")}
    )
    assert response.status_code == 202
    data = response.json()
    assert "document_id" in data
    assert data["filename"] == "prospectus.txt"
    assert data["file_type"] == "txt"
    assert data["status"] == "QUEUED"


def test_upload_pdf_successful(sample_pdf_bytes: bytes):
    """Verify uploading a PDF document is extracted via PyMuPDF and inspected."""
    response = post_inspection(
        "/api/documents/upload",
        files={"file": ("contract.pdf", sample_pdf_bytes, "application/pdf")}
    )
    assert response.status_code == 202
    data = response.json()
    assert data["file_type"] == "pdf"
    assert data["status"] == "QUEUED"


def test_upload_docx_successful(sample_docx_bytes: bytes):
    """Verify uploading a DOCX document is extracted via python-docx and inspected."""
    response = post_inspection(
        "/api/documents/upload",
        files={"file": ("agreement.docx", sample_docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    assert response.status_code == 202
    data = response.json()
    assert data["file_type"] == "docx"
    assert data["status"] == "QUEUED"


def test_upload_unsupported_format():
    """Verify uploading an unsupported extension (.png) returns 400 Bad Request."""
    response = post_inspection(
        "/api/documents/upload",
        files={"file": ("image.png", b"\x89PNG\r\n\x1a\nfakeimage", "image/png")}
    )
    assert response.status_code == 400
    assert "Unsupported file format" in response.json()["detail"]


def test_upload_empty_file():
    """Verify uploading a 0-byte file returns 400 Bad Request."""
    response = post_inspection(
        "/api/documents/upload",
        files={"file": ("empty.txt", b"", "text/plain")}
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_upload_oversized_file(monkeypatch):
    """Verify uploading a file exceeding size limits returns 413 Payload Too Large."""
    import backend.api.routes_documents as rd
    # Temporarily set tiny upload limit of 100 bytes
    monkeypatch.setattr(rd, "MAX_UPLOAD_BYTES", 100)

    oversized_data = b"A" * 200
    response = post_inspection(
        "/api/documents/upload",
        files={"file": ("large.txt", oversized_data, "text/plain")}
    )
    assert response.status_code == 413
    assert "exceeds the maximum allowed size" in response.json()["detail"]


# ==============================================================================
# Findings Retrieval Tests
# ==============================================================================

def test_get_findings_success(sample_txt_bytes: bytes):
    """Verify retrieving strictly validated findings after document upload."""
    upload_res = post_inspection(
        "/api/documents/upload",
        files={"file": ("doc_with_violations.txt", sample_txt_bytes, "text/plain")}
    )
    doc_id = upload_res.json()["document_id"]

    findings_res = client.get(f"/api/documents/{doc_id}/findings")
    assert findings_res.status_code == 200
    data = findings_res.json()

    assert data["document_id"] == doc_id
    assert data["total_findings"] >= 1
    
    first_finding = data["findings"][0]
    assert first_finding["rule_id"] == "FINRA-2210"
    assert "guaranteed returns" in first_finding["passage"]
    assert first_finding["severity"] == "CRITICAL"
    assert first_finding["offset_start"] >= 0
    assert first_finding["offset_end"] > first_finding["offset_start"]


def test_get_findings_unknown_document_id():
    """Verify 404 response when querying findings for a nonexistent document ID."""
    response = client.get("/api/documents/nonexistent-id-0000/findings")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


# ==============================================================================
# Status Polling Tests
# ==============================================================================

def test_get_status_success(sample_txt_bytes: bytes):
    """Verify status polling endpoint returns 200 with lifecycle details."""
    upload_res = post_inspection(
        "/api/documents/upload",
        files={"file": ("test_doc.txt", sample_txt_bytes, "text/plain")}
    )
    doc_id = upload_res.json()["document_id"]

    status_res = client.get(f"/api/documents/{doc_id}/status")
    assert status_res.status_code == 200
    data = status_res.json()

    assert data["document_id"] == doc_id
    assert data["status"] == "COMPLETED"
    assert data["chunks_count"] >= 1
    assert data["has_decision"] is False


def test_get_status_unknown_document_id():
    """Verify 404 response when polling status for a nonexistent document ID."""
    response = client.get("/api/documents/nonexistent-id-0000/status")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


# ==============================================================================
# Human Review Decision Tests
# ==============================================================================

def test_human_review_approval_success(sample_txt_bytes: bytes, officer_headers):
    """Verify a human compliance officer can submit an APPROVED decision."""
    upload_res = post_inspection(
        "/api/documents/upload",
        files={"file": ("approval_test.txt", sample_txt_bytes, "text/plain")}
    )
    doc_id = upload_res.json()["document_id"]

    review_payload = {
        "officer_id": "test_officer",
        "decision": "APPROVED",
        "notes": "Verified all flags. Mitigations on file."
    }
    decision_res = client.post(f"/api/review/{doc_id}/decision", json=review_payload, headers=officer_headers)
    assert decision_res.status_code == 200
    data = decision_res.json()

    assert data["document_id"] == doc_id
    assert data["officer_id"] == "test_officer"
    assert data["decision"] == "APPROVED"
    assert "Mitigations on file" in data["notes"]
    assert "decided_at" in data

    # Verify status reflects that a decision has been recorded
    status_res = client.get(f"/api/documents/{doc_id}/status")
    assert status_res.json()["has_decision"] is True

    # Verify decision retrieval endpoint
    get_dec_res = client.get(f"/api/review/{doc_id}/decision")
    assert get_dec_res.status_code == 200
    assert get_dec_res.json()["decision"] == "APPROVED"


def test_human_review_rejection_success(sample_txt_bytes: bytes, officer_headers):
    """Verify a human compliance officer can submit a REJECTED decision."""
    upload_res = post_inspection(
        "/api/documents/upload",
        files={"file": ("rejection_test.txt", sample_txt_bytes, "text/plain")}
    )
    doc_id = upload_res.json()["document_id"]

    review_payload = {
        "officer_id": "test_officer",
        "decision": "REJECTED",
        "notes": "Critical promissory claims violate FINRA 2210. Unacceptable."
    }
    decision_res = client.post(f"/api/review/{doc_id}/decision", json=review_payload, headers=officer_headers)
    assert decision_res.status_code == 200
    assert decision_res.json()["decision"] == "REJECTED"


def test_human_review_invalid_decision_pending(sample_txt_bytes: bytes, officer_headers):
    """Verify that submitting 'PENDING' as a final review decision is rejected with 422."""
    upload_res = post_inspection(
        "/api/documents/upload",
        files={"file": ("pending_test.txt", sample_txt_bytes, "text/plain")}
    )
    doc_id = upload_res.json()["document_id"]

    review_payload = {
        "officer_id": "test_officer",
        "decision": "PENDING",
        "notes": "Cannot be pending"
    }
    decision_res = client.post(f"/api/review/{doc_id}/decision", json=review_payload, headers=officer_headers)
    assert decision_res.status_code == 422
    assert "must be APPROVED or REJECTED" in decision_res.json()["detail"]


def test_human_review_missing_officer_id(sample_txt_bytes: bytes, officer_headers):
    """Verify that an empty or whitespace officer_id is rejected with 422."""
    upload_res = post_inspection(
        "/api/documents/upload",
        files={"file": ("officer_test.txt", sample_txt_bytes, "text/plain")}
    )
    doc_id = upload_res.json()["document_id"]

    review_payload = {
        "officer_id": "   ",
        "decision": "APPROVED",
        "notes": "Missing officer"
    }
    decision_res = client.post(f"/api/review/{doc_id}/decision", json=review_payload, headers=officer_headers)
    assert decision_res.status_code == 422


def test_human_review_unknown_document_id(officer_headers):
    """Verify 404 response when submitting a review decision for an unknown document ID."""
    review_payload = {
        "officer_id": "test_officer",
        "decision": "APPROVED",
        "notes": "Nonexistent"
    }
    decision_res = client.post("/api/review/nonexistent-id-0000/decision", json=review_payload, headers=officer_headers)
    assert decision_res.status_code == 404


# ==============================================================================
# Failure & Resilience Tests
# ==============================================================================

def test_llm_processing_failure_updates_status(sample_txt_bytes: bytes, monkeypatch):
    """
    Verify that an unhandled LLM failure updates the document status to FAILED
    without crashing the backend or leaving the document in limbo.
    """
    async def mock_fail_analyze(*args, **kwargs):
        raise RuntimeError("Simulated connection timeout to LLM provider.")

    monkeypatch.setattr(compliance_service.llm_orchestrator, "analyze_section", mock_fail_analyze)

    upload_res = post_inspection(
        "/api/documents/upload",
        files={"file": ("failing_doc.txt", sample_txt_bytes, "text/plain")}
    )
    assert upload_res.status_code == 202
    data = upload_res.json()
    assert data["status"] == "QUEUED"

    # Check status endpoint confirms failure
    status_res = client.get(f"/api/documents/{data['document_id']}/status")
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "FAILED"
    assert status_res.json()["error_message"] is not None


@pytest.mark.parametrize("ext", ["txt", "pdf", "docx"])
def test_background_retry_preserves_document(ext, request, monkeypatch):
    original = compliance_service.llm_orchestrator.analyze_section
    async def fail(**kwargs):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(compliance_service.llm_orchestrator, "analyze_section", fail)
    content = request.getfixturevalue(f"sample_{ext}_bytes")
    upload = post_inspection("/api/documents/upload", files={"file": (f"demo.{ext}", content)})
    assert upload.json()["status"] == "QUEUED"
    path = "/api/documents/" + upload.json()["document_id"]
    assert client.get(path + "/status").json()["status"] == "FAILED"
    before = client.get(path + "/text").json()
    monkeypatch.setattr(compliance_service.llm_orchestrator, "analyze_section", original)
    assert post_inspection(path + "/retry").json()["status"] == "QUEUED"
    state = client.get(path + "/status").json()
    assert state["status"] == "COMPLETED"
    assert state["processed_chunks"] == state["chunks_count"]
    assert client.get(path + "/text").json() == before
    findings = client.get(path + "/findings").json()["findings"]
    assert findings
    for finding in findings:
        assert before["raw_text"][finding["offset_start"]:finding["offset_end"]] == finding["passage"]


def test_signed_decision_guards_and_restart(sample_txt_bytes, officer_headers):
    from backend.db.store import DocumentStore
    upload = post_inspection("/api/documents/upload", files={"file": ("demo.txt", sample_txt_bytes)})
    doc_id = upload.json()["document_id"]
    path = f"/api/review/{doc_id}/decision"
    body = {"officer_id": "test_officer", "decision": "APPROVED"}
    assert client.post(path, headers={"Authorization": ""}, json=body).status_code == 401
    assert client.post(path, headers=officer_headers, json=dict(body, officer_id="other")).status_code == 403
    document_store.update_status(doc_id, "FAILED")
    assert client.post(path, headers=officer_headers, json=body).status_code == 409
    assert post_inspection(f"/api/documents/{doc_id}/retry").status_code == 202
    assert client.post(path, headers=officer_headers, json=body).status_code == 200
    assert client.post(path, headers=officer_headers, json=body).status_code == 409
    assert post_inspection(f"/api/documents/{doc_id}/retry").status_code == 409
    reopened = DocumentStore(document_store.decisions_dir)
    assert reopened.get_document(doc_id) == document_store.get_document(doc_id)
    assert reopened.get_decision(doc_id).officer_id == "test_officer"
    assert reopened.get_audit_trail(doc_id) == document_store.get_audit_trail(doc_id)

def test_failed_decision_commit_leaves_review_open(sample_txt_bytes, officer_headers, monkeypatch):
    import sqlite3
    upload = post_inspection("/api/documents/upload", files={"file": ("demo.txt", sample_txt_bytes)})
    doc_id = upload.json()["document_id"]
    def fail_commit(*args):
        raise sqlite3.OperationalError("synthetic write failure")
    monkeypatch.setattr(document_store, "_write", fail_commit)
    result = client.post(f"/api/review/{doc_id}/decision", headers=officer_headers,
                         json={"officer_id": "test_officer", "decision": "REJECTED"})
    assert result.status_code == 500
    assert document_store.get_decision(doc_id) is None


def test_officer_logout_revokes_token(officer_headers):
    assert client.post("/api/review/session", auth=("test_officer", "wrong")).status_code == 401
    token = client.post("/api/review/session", auth=("test_officer", "synthetic-test-password")).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert client.delete("/api/review/session", headers=headers).status_code == 200
    assert client.post("/api/review/demo/decision", headers=headers,
                       json={"decision": "APPROVED", "officer_id": "test_officer"}).status_code == 401

@pytest.mark.parametrize("state", ["UPLOADED", "PROCESSING", "FAILED"])
def test_incomplete_inspections_have_no_decision_history(sample_txt_bytes, officer_headers, state):
    doc_id = post_inspection("/api/documents/upload", files={"file": ("sample.txt", sample_txt_bytes)}).json()["document_id"]
    path = f"/api/review/{doc_id}"
    document_store.update_status(doc_id, state)
    assert client.post(path + "/decision", headers=officer_headers, json={"decision": "APPROVED"}).status_code == 409
    assert client.get(path + "/history").json() == []


def test_concurrent_signoff_has_one_attributed_history_entry(sample_txt_bytes, officer_headers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from backend.db.store import DocumentStore

    doc_id = post_inspection("/api/documents/upload", files={"file": ("sample.txt", sample_txt_bytes)}).json()["document_id"]
    path = f"/api/review/{doc_id}"
    barrier = Barrier(2)
    def submit(outcome):
        barrier.wait(timeout=5)
        return client.post(path + "/decision", headers=officer_headers, json={"decision": outcome, "notes": "Synthetic review."})
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(submit, ["APPROVED", "REJECTED"]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r.json() for r in responses if r.status_code == 200)
    assert winner["officer_id"] == "test_officer"
    assert client.get(path + "/history").json() == [winner]
    reopened = DocumentStore(document_store.decisions_dir)
    assert reopened.review_history(doc_id) == [reopened.get_decision(doc_id)]


def test_history_write_failure_rolls_back_signoff(sample_txt_bytes, officer_headers):
    doc_id = post_inspection("/api/documents/upload", files={"file": ("sample.txt", sample_txt_bytes)}).json()["document_id"]
    path = f"/api/review/{doc_id}"
    with document_store.connection() as db:
        db.execute("CREATE TRIGGER simulate_failure BEFORE INSERT ON review_history BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    try:
        assert client.post(path + "/decision", headers=officer_headers, json={"decision": "APPROVED"}).status_code == 500
        assert client.get(path + "/history").json() == []
        assert client.get(path + "/decision").status_code == 404
    finally:
        with document_store.connection() as db:
            db.execute("DROP TRIGGER simulate_failure")
    assert client.post(path + "/decision", headers=officer_headers, json={"decision": "APPROVED"}).status_code == 200


def test_invalid_bearer_cannot_create_history(sample_txt_bytes):
    doc_id = post_inspection("/api/documents/upload", files={"file": ("sample.txt", sample_txt_bytes)}).json()["document_id"]
    path = f"/api/review/{doc_id}"
    res = client.post(path + "/decision", headers={"Authorization": "Bearer invalid"},
                      json={"officer_id": "test_officer", "decision": "APPROVED"})
    assert res.status_code == 401
    assert client.get(path + "/history").json() == []

def test_existing_sqlite_decision_is_backfilled_and_preserved(tmp_path, sample_txt_bytes):
    import sqlite3
    from backend.db.store import DocumentRecord, DocumentStore
    from backend.models.review import ReviewDecision
    from backend.services.document_processor import DocumentProcessor

    doc = DocumentProcessor().process_bytes(sample_txt_bytes, "legacy.txt")
    signed = ReviewDecision(document_id=doc.id, decision="REJECTED", officer_id="previous_officer", notes="Original rationale")
    record = DocumentRecord(document=doc, status="COMPLETED", review_decision=signed)
    with sqlite3.connect(tmp_path / "inspections.sqlite3") as db:
        db.execute("CREATE TABLE inspections (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        db.execute("INSERT INTO inspections VALUES (?, ?)", (doc.id, record.model_dump_json()))
    store = DocumentStore(tmp_path)
    assert store.review_history(doc.id) == [signed]
    with pytest.raises(sqlite3.IntegrityError):
        store.update_status(doc.id, "PROCESSING")
    with store.connection() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM review_history WHERE document_id=?", (doc.id,))
    assert DocumentStore(tmp_path).review_history(doc.id) == [signed]

@pytest.mark.parametrize("failure,reason", [
    ("429", "rate limit"), ("timeout", "timed out"), ("network", "network"),
    ("malformed", "malformed"), ("invalid_fields", "malformed"),
])
def test_middle_chunk_recovery_after_cold_cache(failure, reason, monkeypatch):
    import json
    from backend.services.llm_orchestrator import LLMRateLimitError, LLMTimeoutError, LLMServerError
    first = "Guaranteed returns for everyone."
    second = "This second paragraph is neutral."
    calls = []
    class Provider:
        async def generate_response(self, system_prompt, user_prompt, timeout_seconds):
            section = json.loads(user_prompt)["target"]
            calls.append(section)
            if section == first:
                item = dict(passage=first, rule_id="FINRA-2210", reason="Promissory claim", severity="HIGH")
                return json.dumps([item, item])
            if len(calls) == 2:
                if failure == "malformed":
                    return "malformed"
                if failure == "invalid_fields":
                    return "[{}]"
                raise {"429": LLMRateLimitError("HTTP 429", retry_delay=1),
                       "timeout": LLMTimeoutError("timeout"), "network": LLMServerError("network")}[failure]
            return "[]"

    def cold_orchestrator():
        return LLMOrchestrator(provider=Provider(), max_retries=1)
    monkeypatch.setattr(compliance_service, "llm_orchestrator", cold_orchestrator())
    source = first + "\n\n" + second
    response = post_inspection("/api/documents/upload", files={"file": ("recovery.txt", source.encode())}).json()
    doc_id = response["document_id"]
    assert reason in client.get(response["status_url"]).json()["error_message"].lower()
    snapshot = document_store.get_document(doc_id)
    monkeypatch.setattr(compliance_service, "llm_orchestrator", cold_orchestrator())
    path = "/api/documents/" + doc_id
    assert post_inspection(path + "/retry").status_code == 202
    assert calls == [first, second, second]
    assert document_store.get_document(doc_id) == snapshot
    findings = client.get(path + "/findings").json()["findings"]
    assert len(findings) == 1
    assert source[findings[0]["offset_start"]:findings[0]["offset_end"]] == first
    assert len(document_store.get_audit_trail(doc_id)) == 2


@pytest.mark.parametrize("original,snapshot_ok,expected", [
    ("missing", True, 202), ("corrupt", True, 202), ("intact", False, 202),
    ("missing", False, 422), ("corrupt", False, 422),
])
def test_pdf_retry_recovers_only_verifiable_evidence(original, snapshot_ok, expected, sample_pdf_bytes):
    from backend.config import UPLOADS_DIR
    doc_id = post_inspection("/api/documents/upload", files={"file": ("example.pdf", sample_pdf_bytes)}).json()["document_id"]
    snapshot = document_store.get_document(doc_id)
    document_store.update_status(doc_id, "FAILED")
    if not snapshot_ok:
        with document_store.connection() as db:
            db.execute("UPDATE inspections SET record=json_remove(record,'$.document.chunks','$.document.raw_text') WHERE id=?", (doc_id,))
    file = UPLOADS_DIR / f"{doc_id}_example.pdf"
    if original == "missing":
        file.unlink()
    elif original == "corrupt":
        file.write_bytes(b"not a PDF")
    result = post_inspection(f"/api/documents/{doc_id}/retry")
    assert result.status_code == expected
    if expected == 202:
        assert client.get(result.json()["status_url"]).json()["status"] == "COMPLETED"
        assert document_store.get_document(doc_id) == snapshot
    else:
        assert document_store.get_status(doc_id)["status"] == "FAILED"


def test_overlapping_retry_is_claimed_once(sample_txt_bytes, monkeypatch):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    doc_id = post_inspection("/api/documents/upload", files={"file": ("demo.txt", sample_txt_bytes)}).json()["document_id"]
    document_store.update_status(doc_id, "FAILED")
    entered, release = Event(), Event()
    original = compliance_service.analyze_document
    async def pause(document):
        entered.set()
        await asyncio.to_thread(release.wait, 5)
        return await original(document)
    monkeypatch.setattr(compliance_service, "analyze_document", pause)
    path = f"/api/documents/{doc_id}/retry"
    with ThreadPoolExecutor(1) as pool:
        winner = pool.submit(post_inspection, path)
        try:
            assert entered.wait(5)
            assert client.post(path).status_code == 409
        finally:
            release.set()
        assert winner.result().status_code == 202

@pytest.mark.parametrize("new_version,expected_first_calls", [("v1", 1), ("v2", 2)])
def test_empty_checkpoint_requires_same_prompt_version(monkeypatch, new_version, expected_first_calls):
    from backend.services.llm_orchestrator import LLMTimeoutError
    calls = []
    class Provider:
        async def generate_response(self, system_prompt, user_prompt, timeout_seconds):
            calls.append("first" if "First section." in json.loads(user_prompt)["target"] else "second")
            if len(calls) == 2:
                raise LLMTimeoutError("synthetic timeout")
            return "[]"
    def model(version):
        return LLMOrchestrator(provider=Provider(), prompt_version=version, max_retries=1)
    monkeypatch.setattr(compliance_service, "llm_orchestrator", model("v1"))
    response = post_inspection("/api/documents/upload", files={"file": ("empty.txt", b"First section.\n\nSecond section.")}).json()
    assert client.get(response["status_url"]).json()["status"] == "FAILED"
    monkeypatch.setattr(compliance_service, "llm_orchestrator", model(new_version))
    retry = client.post("/api/documents/" + response["document_id"] + "/retry")
    assert client.get(retry.json()["status_url"]).json()["status"] == "COMPLETED"
    assert calls.count("first") == expected_first_calls
    assert calls.count("second") == 2


@pytest.mark.asyncio
async def test_gemini_transport_failure_is_retryable_offline(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    import httpx
    from backend.services.llm_orchestrator import GeminiLLMProvider, LLMServerError
    adapter = GeminiLLMProvider(model_id="synthetic")
    sdk = MagicMock()
    sdk.aio.models.generate_content = AsyncMock(side_effect=httpx.ConnectError("offline simulation"))
    monkeypatch.setattr(adapter, "_get_client", lambda: sdk)
    with pytest.raises(LLMServerError, match="connection failure"):
        await adapter.generate_response("system", "user", 1)
