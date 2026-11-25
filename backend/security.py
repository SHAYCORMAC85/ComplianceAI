"""Per-process application ingress limits for the single-workstation deployment."""
from collections import deque
from threading import Lock
import time

from fastapi import HTTPException
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from backend.officers import authenticate_token
from backend.security_events import event


class Window:
    def __init__(self, limit, seconds=60):
        self.limit = limit
        self.seconds = seconds
        self.entries = deque()
        self.lock = Lock()

    def admit(self):
        now = time.monotonic()
        with self.lock:
            while self.entries and self.entries[0] <= now - self.seconds:
                self.entries.popleft()
            if len(self.entries) >= self.limit:
                return False
            self.entries.append(now)
            return True


class Ingress:
    def __init__(self, app):
        self.app = app
        self.login = Window(12)
        self.incoming = Window(1800)
        self.reads = Window(1200)
        self.submissions = Window(60)
        self.uploads = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"].rstrip("/")
        if not path.startswith("/api/") or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        signin = path == "/api/review/session" and scope["method"] == "POST"
        upload = path == "/api/documents/upload" and scope["method"] == "POST"
        write = scope["method"] == "POST"
        try:
            if not self.incoming.admit():
                raise HTTPException(429, "Application request limit reached. Try again shortly.")
            if signin:
                budget = self.login
            else:
                scheme, _, token = headers.get(b"authorization", b"").partition(b" ")
                officer = authenticate_token(token.decode("latin1") if scheme.lower()==b"bearer" else "")
                scope.setdefault("state", {})["officer_id"] = officer
                budget = self.submissions if write else self.reads
            if not budget.admit():
                event("request_limit", "denied")
                raise HTTPException(429, "Application request limit reached. Try again shortly.")
            maximum = 16*1024*1024 if upload else 32*1024
            try:
                length = int(headers.get(b"content-length", b"0"))
            except ValueError:
                raise HTTPException(400, "Invalid content length.") from None
            if length < 0 or length > maximum:
                raise HTTPException(413, "Request size exceeds the maximum allowed size.")
            if upload and self.uploads >= 3:
                raise HTTPException(429, "Upload processing is busy.")
        except HTTPException as exc:
            if path.endswith("/decision") and write and exc.status_code != 429:
                event("decision_submit", "rejected")
            return await JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                                      headers={"Cache-Control": "no-store"})(scope, receive, send)

        received = 0
        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > maximum:
                # Multipart parser closes its temporary files on this exception.
                raise MultiPartException("Request body is too large.")
            return message

        async def safe_send(message):
            if message["type"] == "http.response.start":
                if received > maximum:
                    message["status"] = 413
                if signin and message["status"] == 401 and not headers.get(b"authorization", b"").lower().startswith(b"basic "):
                    event("sign_in", "denied")
                if path.endswith("/decision") and write and message["status"] >= 400:
                    event("decision_submit", "rejected", scope.get("state",{}).get("officer_id"))
                message["headers"] = list(message.get("headers", [])) + [(b"cache-control",b"no-store")]
            await send(message)
        if upload:
            self.uploads += 1
        try:
            await self.app(scope,bounded_receive,safe_send)
        finally:
            if upload:
                self.uploads -= 1
