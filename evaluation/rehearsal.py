"""Local release rehearsal. Optional measurement dependency: psutil."""
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from statistics import mean

import psutil
import requests


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def service(args, health):
    process = subprocess.Popen([sys.executable, "-m", *args], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        for _ in range(200):
            if process.poll() is not None:
                raise RuntimeError("Local service exited during startup")
            try:
                if requests.get(health, timeout=1).ok:
                    break
            except requests.ConnectionError:
                pass
            time.sleep(.1)
        else:
            raise RuntimeError("Local service readiness timed out")
        yield psutil.Process(process.pid)
    finally:
        process.terminate()
        process.wait(10)


def run(root):
    api_port, ui_port = port(), port()
    base = f"http://127.0.0.1:{api_port}"
    data = root / "source"
    os.environ.update(COMPLIANCE_DATA_DIR=str(data), LLM_PROVIDER="mock", BACKEND_URL=base,
                      GEMINI_API_KEY="", OPENAI_API_KEY="", INSPECTION_WORKERS="1")
    from backend.officers import enroll
    from backend.services.document_processor import DocumentProcessor
    from backend.storage_backup import backup, restore
    from frontend.utils.highlighting import highlight_document_text
    password = secrets.token_urlsafe(24)
    enroll("demo-reviewer", password)
    api = ["uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(api_port)]
    ui = ["streamlit", "run", "frontend/app.py", "--server.headless=true",
          "--server.address=127.0.0.1", f"--server.port={ui_port}"]
    def login():
        session = requests.Session()
        response = session.post(base+"/api/review/session", auth=("demo-reviewer", password), timeout=5)
        response.raise_for_status()
        session.headers.update(Authorization="Bearer "+response.json()["token"])
        return session
    source = "\n\n".join(f"Section {i}. We guarantee a profit every quarter." for i in range(30))
    payload = source.encode()
    proc = DocumentProcessor()
    start = time.perf_counter()
    for _ in range(20):
        proc.process_bytes(payload, "demo.txt")
    results = {"extraction_mean_ms": (time.perf_counter()-start)*50}
    with service(api, base+"/health") as backend, service(ui, f"http://127.0.0.1:{ui_port}/_stcore/health") as frontend:
        results.update(api_idle_mib=backend.memory_info().rss/2**20, ui_idle_mib=frontend.memory_info().rss/2**20)
        session = login()
        cpu = backend.cpu_times()
        wall = time.perf_counter()
        ids, acks, durations = [], [], []
        for i in range(3):
            start = time.perf_counter()
            response = session.post(base+"/api/documents/upload", files={"file":(f"demo{i}.txt",payload)},timeout=10)
            assert response.status_code == 202
            acks.append(time.perf_counter()-start)
            ids.append((response.json()["document_id"],start))
        for doc, start in ids:
            url = base+"/api/documents/"+doc
            deadline = time.monotonic()+30
            while time.monotonic()<deadline:
                state = session.get(url+"/status",timeout=5).json()
                if state["status"]=="COMPLETED":
                    break
                assert state["status"]!="FAILED"
                time.sleep(.02)
            assert state["status"]=="COMPLETED" and state["progress_percent"]==100
            durations.append(time.perf_counter()-start)
        delta = backend.cpu_times()
        results.update(backend_one_core_cpu_pct=100*(delta.user+delta.system-cpu.user-cpu.system)/(time.perf_counter()-wall),
                       ack_ms=[round(1000*n,2) for n in acks], submit_to_observed_complete_s=durations)
        findings = session.get(url+"/findings",timeout=5).json()["findings"]
        text = session.get(url+"/text",timeout=5).json()["raw_text"]
        assert text == source and findings
        assert all(text[f["offset_start"]:f["offset_end"]] == f["passage"] for f in findings)
        markup, warnings = highlight_document_text(text,findings)
        assert "<mark" in markup and not warnings
        review = base+"/api/review/"+doc
        assert session.post(review+"/decision",json={"decision":"REJECTED"},timeout=5).status_code==200
        history = session.get(review+"/history",timeout=5).json()
        assert len(history)==1
    with service(api,base+"/health"):
        assert login().get(review+"/history",timeout=5).json()==history
    # Use a separate scratch database to time individual durable commits.
    with sqlite3.connect(root/"timing.sqlite") as db:
        db.execute("CREATE TABLE timings(id INTEGER PRIMARY KEY, value TEXT)")
        samples = []
        for i in range(100):
            start = time.perf_counter()
            db.execute("INSERT INTO timings VALUES (?,?)", (i, "synthetic"))
            db.commit()
            samples.append(time.perf_counter()-start)
        results["sqlite_commit_mean_ms"] = mean(samples)*1000
        start = time.perf_counter()
        for i in range(100):
            assert db.execute("SELECT value FROM timings WHERE id=?", (i,)).fetchone()
        results["sqlite_read_mean_ms"] = (time.perf_counter()-start)*10
    db.close()
    backup(data,root/"backup")
    restore(root/"backup",root/"restored")
    os.environ["COMPLIANCE_DATA_DIR"]=str(root/"restored")
    with service(api,base+"/health"):
        assert login().get(review+"/history",timeout=5).json()==history
    return results


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp:
        print(json.dumps(run(Path(temp)),indent=2))
