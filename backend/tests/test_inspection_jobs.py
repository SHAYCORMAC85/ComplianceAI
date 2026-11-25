"""Phase 8 queue, restart, real HTTP and Streamlit contract tests. Offline providers only."""
import json
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import socket
import threading
import time
from unittest.mock import patch

import pytest
import requests
import uvicorn
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.config import settings
from backend.db.store import document_store
from backend.main import app
from backend.officers import enroll
from backend.services.compliance_service import compliance_service
from backend.services.llm_orchestrator import LLMOrchestrator, LLMRateLimitError


def status_until(client, url, predicate):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = client.get(url).json()
        if predicate(result):
            return result
        time.sleep(.015)
    pytest.fail(f"Unexpected final stage: {result.get('stage')}")


def use_provider(monkeypatch, provider):
    model = LLMOrchestrator(provider=provider, max_retries=2)
    monkeypatch.setattr(compliance_service, "llm_orchestrator", model)
    return model


def test_real_http_submission_progress_and_review(monkeypatch):
    """Block the second section until the client observes the first validated result."""
    release = threading.Event()
    class Provider:
        async def generate_response(self, system_prompt, user_prompt, timeout_seconds):
            if "Second section" in json.loads(user_prompt)["target"]:
                await asyncio.to_thread(release.wait, 6)
            else:
                await asyncio.sleep(.2)
            return "[]"
    use_provider(monkeypatch, Provider())
    enroll("queue-http-test", "synthetic-http-password")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            for _ in range(200):
                if server.started:
                    break
                time.sleep(.015)
            assert server.started
            login = requests.post(base+"/api/review/session", auth=("queue-http-test","synthetic-http-password"),timeout=3)
            headers = {"Authorization": "Bearer "+login.json()["token"]}
            session = requests.Session()
            session.headers.update(headers)
            start = time.monotonic()
            response = session.post(base+"/api/documents/upload",files={"file":("demo.txt", b"First section.\n\nSecond section.")},timeout=3)
            elapsed = time.monotonic()-start
            assert response.status_code == 202 and response.json()["status"] == "QUEUED"
            url = base + response.json()["status_url"]
            middle = status_until(session, url, lambda s: s["analyzed"] == 1)
            assert middle["progress_percent"] == 50 and middle["status"] == "PROCESSING"
            doc_id = response.json()["document_id"]
            review = base+f"/api/review/{doc_id}/decision"
            findings = base+f"/api/documents/{doc_id}/findings"
            assert session.get(findings, timeout=3).status_code == 409
            assert requests.post(review, headers=headers, json={"decision":"APPROVED"}, timeout=3).status_code == 409
            release.set()
            final = status_until(session, url, lambda s: s["status"]=="COMPLETED")
            assert final["progress_percent"] == 100 and final["analyzed"] == 2
            assert session.get(findings,timeout=3).status_code == 200
            assert requests.post(review, headers=headers, json={"decision":"APPROVED"}, timeout=3).status_code == 200
            print(f"Loopback upload {elapsed:.3f}s (202); observed 1/2 at 50%, then 2/2 at 100%; review 409 then 200.")
        finally:
            release.set()
            server.should_exit = True
            thread.join(8)
            assert not thread.is_alive()


def test_simultaneous_idempotent_submissions(monkeypatch, workspace_headers):
    monkeypatch.setattr(settings,"INSPECTION_WORKERS",2)
    calls = []
    class Provider:
        async def generate_response(self, **kwargs):
            calls.append(1)
            await asyncio.sleep(.1)
            return "[]"
    use_provider(monkeypatch,Provider())
    with TestClient(app, headers=workspace_headers) as client:
        def submit(data):
            return client.post("/api/documents/upload", headers={"Idempotency-Key":"once"},
                               files={"file":("same.txt",data)})
        with ThreadPoolExecutor(3) as pool:
            responses = list(pool.map(submit,[b"First section."]*3))
        assert {r.status_code for r in responses} == {202}
        assert len({r.json()["document_id"] for r in responses}) == 1
        assert submit(b"Other section.").status_code == 409
        status_until(client,responses[0].json()["status_url"],lambda s:s["status"]=="COMPLETED")
        assert len(calls)==1 and len(document_store.list_documents())==1


def test_quota_wait_and_failure_isolation(monkeypatch, workspace_headers):
    calls = []
    class Provider:
        async def generate_response(self, system_prompt,user_prompt,timeout_seconds):
            calls.append(1)
            if len(calls)==1:
                raise LLMRateLimitError("synthetic",retry_delay=.25)
            if "Fail this section" in json.loads(user_prompt)["target"]:
                raise ValueError("synthetic")
            return "[]"
    model = use_provider(monkeypatch,Provider())
    from backend.services.rate_limiter import RequestRateLimiter
    model.rate_limiter = RequestRateLimiter(safety_buffer=.01)
    with TestClient(app, headers=workspace_headers) as client:
        def submit(data):
            return client.post("/api/documents/upload", files={"file":("sample.txt",data)}).json()["status_url"]
        first = submit(b"Fail this section.")
        wait = status_until(client,first,lambda s:s["stage"]=="WAITING_FOR_QUOTA")
        assert wait["status"]=="PROCESSING" and wait["retry_at"] and wait["progress_percent"]==0
        second = submit(b"x\n\nValid section.")
        failed = status_until(client,first,lambda s:s["status"]=="FAILED")
        assert failed["failed"]==1 and failed["analyzed"]==0
        done = status_until(client,second,lambda s:s["status"]=="COMPLETED")
        assert done["skipped"]==1 and done["analyzed"]==1


def test_shutdown_restart_reuses_checkpoint(monkeypatch, workspace_headers):
    calls=[]
    entered=threading.Event()
    class Provider:
        async def generate_response(self,system_prompt,user_prompt,timeout_seconds):
            section="second" if "Second section" in json.loads(user_prompt)["target"] else "first"
            calls.append(section)
            if calls==["first","second"]:
                entered.set()
                await asyncio.sleep(30)
            return "[]"
    monkeypatch.setattr(settings,"WORKER_SHUTDOWN_SECONDS",.05)
    use_provider(monkeypatch,Provider())
    with TestClient(app, headers=workspace_headers) as client:
        url=client.post("/api/documents/upload",files={"file":("demo.txt",b"First section.\n\nSecond section.")}).json()["status_url"]
        assert entered.wait(3)
    assert document_store.get_status(url.split("/")[-2])["status"]=="PROCESSING"
    use_provider(monkeypatch,Provider())
    with TestClient(app, headers=workspace_headers) as client:
        done=status_until(client,url,lambda s:s["status"]=="COMPLETED")
        assert done["cached"]==1 and done["analyzed"]==1
        assert calls==["first","second","second"]


def test_streamlit_reopens_and_stops_polling():
    from frontend.api.client import api_client
    doc="synthetic-id"
    row=dict(document_id=doc,filename="demo.txt",status="PROCESSING",has_decision=False)
    info=dict(row,stage="WAITING_FOR_QUOTA",retry_at="test reset time",analyzed=1,cached=0,failed=0,skipped=0,
              processed_chunks=1,chunks_count=2,progress_percent=50)
    with patch.object(api_client,"check_health",return_value={"llm_provider":"mock"}), \
         patch.object(api_client,"list_documents",side_effect=lambda:[row.copy()]), \
         patch.object(api_client,"get_document_status",side_effect=lambda key: info.copy()):
        page=AppTest.from_file(Path(__file__).resolve().parents[2] / "frontend/pages/2_Upload_Document.py")
        page.session_state["officer_session"] = {"officer_id":"test", "token":"synthetic"}
        page.run()
        next(b for b in page.button if b.label=="Open inspection").click().run()
        assert not page.exception and page.session_state["active_document_id"]==doc
        assert any("Waiting for provider quota" in item.value for item in page.info)
        assert page.get("progress")[0].proto.value==50
        info.update(status="COMPLETED",stage="COMPLETED",progress_percent=100,analyzed=2,processed_chunks=2)
        row.update(status="COMPLETED")
        page.run()
        assert not page.exception and any(b.label=="View inspection findings" for b in page.button)
        assert not any(b.label=="Retry inspection" for b in page.button)

def test_failed_final_commit_keeps_checkpoint_and_results_private(monkeypatch, workspace_headers):
    class Provider:
        async def generate_response(self, **kwargs):
            return "[]"
    use_provider(monkeypatch, Provider())
    with TestClient(app, headers=workspace_headers) as client:
        with document_store.connection() as db:
            db.execute("""CREATE TRIGGER reject_completion BEFORE UPDATE OF stage ON inspection_jobs
                       WHEN NEW.stage='COMPLETED' BEGIN SELECT RAISE(ABORT,'test fault'); END""")
        try:
            response = client.post("/api/documents/upload", files={"file":("sample.txt", b"Evaluated section.")})
            doc_id = response.json()["document_id"]
            url = response.json()["status_url"]
            failed = status_until(client,url,lambda s:s["status"]=="FAILED")
            assert failed["progress_percent"] < 100
            assert client.get(f"/api/documents/{doc_id}/findings").status_code == 409
        finally:
            with document_store.connection() as db:
                db.execute("DROP TRIGGER reject_completion")
        use_provider(monkeypatch,Provider())
        assert client.post(f"/api/documents/{doc_id}/retry").status_code == 202
        done=status_until(client,url,lambda s:s["status"]=="COMPLETED")
        assert done["cached"]==1 and done["progress_percent"]==100


def test_all_skipped_document_is_not_reviewable(workspace_headers):
    with TestClient(app, headers=workspace_headers) as client:
        accepted=client.post("/api/documents/upload",files={"file":("tiny.txt",b"abc")}).json()
        info=status_until(client,accepted["status_url"],lambda s:s["status"]=="FAILED")
        assert info["skipped"]==1 and info["processed_chunks"]==0
        assert info["progress_percent"]<100 and info["error_message"]
