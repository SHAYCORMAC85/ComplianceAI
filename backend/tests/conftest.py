"""Select isolated runtime storage before importing application singletons."""
import os
import tempfile

_test_data = tempfile.TemporaryDirectory(prefix="compliance-tests-")
os.environ.update(COMPLIANCE_DATA_DIR=_test_data.name, LLM_PROVIDER="mock",
                  OPENAI_API_KEY="", GEMINI_API_KEY="")

import pytest


@pytest.fixture(autouse=True)
def isolated_inspection_database(tmp_path, monkeypatch):
    from backend.db.store import DocumentStore, document_store
    fresh = DocumentStore(tmp_path / "decisions")
    monkeypatch.setattr(document_store, "path", fresh.path)
    monkeypatch.setattr(document_store, "decisions_dir", fresh.decisions_dir)


@pytest.fixture(scope="session")
def workspace_headers():
    from backend.officers import enroll, sign_in
    enroll("workspace-test", "synthetic-workspace-password")
    token = sign_in("workspace-test", "synthetic-workspace-password")["token"]
    return {"Authorization": "Bearer " + token}


@pytest.fixture(autouse=True)
def independent_request_limits():
    from backend.main import app
    from backend.security import Ingress
    layer = app.middleware_stack
    while layer is not None:
        if isinstance(layer, Ingress):
            for window in (layer.incoming, layer.login, layer.reads, layer.submissions):
                with window.lock:
                    window.entries.clear()
            break
        layer = getattr(layer, "app", None)
