"""Start the single-process backend and local Streamlit demo from the project root."""
from contextlib import closing
from pathlib import Path
import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent


def main():
    for port in (8000, 8501):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(f"Port {port} is in use. Close the existing demo or use the manual launch commands.")
    from backend.officers import database, enroll_interactively
    with closing(database()) as db:
        needs_officer = db.execute("SELECT 1 FROM officers LIMIT 1").fetchone() is None
    if needs_officer:
        print("Create the first local compliance officer.")
        enroll_interactively()

    env = dict(os.environ, BACKEND_URL="http://127.0.0.1:8000")
    processes = []
    try:
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app",
                                "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT, env=env)
        processes.append(api)
        for _ in range(100):
            if api.poll() is not None:
                raise SystemExit("The backend stopped during startup.")
            try:
                with urlopen(env["BACKEND_URL"] + "/health", timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise SystemExit("The backend did not become ready.")
        ui = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "frontend/app.py",
                               "--server.address", "127.0.0.1", "--server.port", "8501"],
                              cwd=ROOT, env=env)
        processes.append(ui)
        print("ComplianceAI is available at http://127.0.0.1:8501. Press Ctrl+C here to stop.")
        while all(process.poll() is None for process in processes):
            time.sleep(.3)
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            process.wait()


if __name__ == "__main__":
    main()
