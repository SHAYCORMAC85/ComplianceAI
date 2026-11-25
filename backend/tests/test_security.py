"""Synthetic security regressions. All provider calls remain offline."""
import io
import json
import time

import docx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend import officers
from backend.config import settings
from backend.db.store import document_store
from backend.main import app
from backend.services.document_processor import CorruptFileError, DocumentProcessor


@pytest.mark.parametrize("method,path", [
    ("get", "/api/documents"), ("get", "/api/documents/example/text"),
    ("get", "/api/documents/example/findings"), ("get", "/api/documents/example/status"),
    ("get", "/api/review/example/history"), ("get", "/api/review/example/decision"),
    ("post", "/api/documents/upload"), ("post", "/api/documents/example/retry"),
    ("post", "/api/review/example/decision"),
])
def test_anonymous_access_stops_before_lookup(method, path):
    response = TestClient(app).request(method, path)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_expired_session_and_event_privacy(monkeypatch, caplog):
    token = "synthetic-expired-marker"
    monkeypatch.setitem(officers.sessions, token, ("synthetic-identity", time.monotonic() - 1))
    response = TestClient(app).get("/api/documents", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401 and token not in officers.sessions
    records = [r.getMessage() for r in caplog.records if r.name == "compliance.security"]
    assert any(json.loads(r)["operation"] == "access" for r in records)
    assert all(token not in r and "synthetic-identity" not in r for r in records)


def test_login_budget():
    client = TestClient(app)
    for _ in range(12):
        assert client.post("/api/review/session").status_code == 401
    assert client.post("/api/review/session").status_code == 429


@pytest.mark.parametrize("name,data,status", [
    ("../outside.txt", b"synthetic", 400), ("CON.txt", b"synthetic", 400),
    ("inert.pdf", b"synthetic-private-marker", 422),
    ("inert.txt", b"synthetic\x00record", 422),
])
def test_invalid_upload_no_persistence(name, data, status, workspace_headers):
    response = TestClient(app, headers=workspace_headers).post("/api/documents/upload", files={"file": (name, data)})
    assert response.status_code == status
    assert "synthetic-private-marker" not in response.text
    assert not document_store.list_documents()


def test_cloud_submission_and_retry_require_matching_provider(monkeypatch, workspace_headers):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    with TestClient(app, headers=workspace_headers) as client:
        files = {"file": ("example.txt", b"Synthetic inspection section.")}
        for headers in ({}, {"X-Authorized-Provider": "other"}):
            assert client.post("/api/documents/upload", headers=headers, files=files).status_code == 403
            assert client.post("/api/documents/example/retry", headers=headers).status_code == 403
        response = client.post("/api/documents/upload", files=files, headers={"X-Authorized-Provider": "gemini"})
        assert response.status_code == 202
        assert document_store._get(response.json()["document_id"]).authorized_provider == "gemini"


def test_format_limits_on_ordinary_files(monkeypatch):
    processor = DocumentProcessor()
    with pymupdf.open() as pdf:
        pdf.new_page()
        monkeypatch.setattr(processor, "MAX_PAGES", 0)
        with pytest.raises(CorruptFileError):
            processor.read_pdf_bytes(pdf.tobytes())
    stream = io.BytesIO()
    docx.Document().save(stream)
    monkeypatch.setattr(processor, "MAX_EXPANDED", 64)
    with pytest.raises(CorruptFileError):
        processor.read_docx_bytes(stream.getvalue())

def test_recovered_mock_job_requires_new_cloud_authorization():
    from backend.db.store import RecoveryError
    document = DocumentProcessor().process_raw_text("Synthetic local section.")
    document_store.enqueue(document, None, "synthetic-digest")
    with pytest.raises(RecoveryError, match="authorization"):
        document_store.load_job_document(document.id, None, provider="gemini")
    assert document_store.load_job_document(document.id, None, provider="mock").id == document.id
