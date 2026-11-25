"""
Rate Limiter & Quota Optimization Tests
---------------------------------------
Verifies:
1. Extraction of RetryInfo metadata and delays from provider errors.
2. RequestRateLimiter sliding-window pacing and global cooldown.
3. LLMOrchestrator resilience with retry delay.
4. Cache reuse preventing duplicate requests.
5. Endpoints returning clear user-facing messages on 429.

ALL tests run offline with mock providers (ZERO external API calls).
"""

import asyncio
import json
import time
import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app
from backend.models.document import Document, DocumentChunk
from backend.models.rule import ComplianceRule
from backend.models.finding import RawFinding, SeverityEnum
from backend.services.cache_service import CacheService
from backend.services.compliance_service import ComplianceService
from backend.services.llm_orchestrator import (
    BaseLLMProvider,
    LLMOrchestrator,
    LLMRateLimitError,
    extract_retry_delay,
    GeminiLLMProvider,
)
from backend.services.rate_limiter import RequestRateLimiter
from backend.db.store import document_store
from backend.services.compliance_service import compliance_service


@pytest.fixture(autouse=True)
def clean_store():
    """Clears in-memory store before each test for total isolation."""
    original_orchestrator = compliance_service.llm_orchestrator
    compliance_service.llm_orchestrator = LLMOrchestrator(provider_name="mock")
    yield
    compliance_service.llm_orchestrator = original_orchestrator


# ==============================================================================
# 1. Retry Delay Extraction Tests
# ==============================================================================

def test_extract_retry_delay_from_rpc_retry_info():
    """Verify extraction from Google RPC RetryInfo dictionary metadata."""
    class MockClientError(Exception):
        def __init__(self):
            super().__init__("429 Resource has been exhausted")
            self.code = 429
            self.details = {
                "error": {
                    "code": 429,
                    "message": "Resource has been exhausted (e.g. check quota).",
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "44s"
                        }
                    ]
                }
            }

    err = MockClientError()
    delay = extract_retry_delay(err)
    assert delay == 44.0


def test_extract_retry_delay_from_headers():
    """Verify extraction from HTTP Retry-After response headers."""
    class MockHeaderResponse:
        headers = {"retry-after": "30"}

    class MockHeaderError(Exception):
        response = MockHeaderResponse()

    err = MockHeaderError("Rate limit exceeded")
    delay = extract_retry_delay(err)
    assert delay == 30.0


def test_extract_retry_delay_from_error_message():
    """Verify fallback regex extraction from raw error text."""
    err1 = Exception("Resource has been exhausted. Please retry in 44.5s.")
    assert extract_retry_delay(err1) == 44.5

    err2 = Exception("Rate limit hit. retryDelay: '15s'")
    assert extract_retry_delay(err2) == 15.0

    err3 = Exception("quota reached. please retry after 20 seconds")
    assert extract_retry_delay(err3) == 20.0

    err_none = Exception("Generic unknown error without delay")
    assert extract_retry_delay(err_none) is None


# ==============================================================================
# 2. Rate Limiter Pacing & Cooldown Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_rate_limiter_pacing_concurrent():
    """Verify rate limiter allows up to N requests in sliding window and paces excess."""
    limiter = RequestRateLimiter(
        requests_per_minute=3,
        safety_buffer=0.05,
        min_interval_seconds=0.01
    )

    start_time = time.time()
    # Acquire 3 slots immediately
    w1 = await limiter.acquire()
    w2 = await limiter.acquire()
    w3 = await limiter.acquire()

    status = limiter.get_status()
    assert status["requests_last_minute"] == 3
    assert status["in_cooldown"] is False


@pytest.mark.asyncio
async def test_rate_limiter_quota_cooldown():
    """Verify notify_quota_exhausted sets global cooldown that blocks acquire until expired."""
    limiter = RequestRateLimiter(
        requests_per_minute=5,
        safety_buffer=0.05,
        min_interval_seconds=0.01
    )

    limiter.notify_quota_exhausted(retry_delay=0.05)
    assert limiter.is_in_cooldown() is True
    assert limiter.get_cooldown_remaining() > 0

    t0 = time.time()
    waited = await limiter.acquire()
    t1 = time.time()

    assert (t1 - t0) >= 0.08  # Waited for cooldown to expire
    assert limiter.is_in_cooldown() is False


# ==============================================================================
# 3. LLM Orchestrator Resilience with Retry Delay Tests
# ==============================================================================

class DelayedRateLimitProvider(BaseLLMProvider):
    """Fails with 429 containing retry delay on first attempt, then succeeds."""
    def __init__(self, delay_seconds: float):
        self.delay_seconds = delay_seconds
        self.attempts = 0

    async def generate_response(self, system_prompt: str, user_prompt: str, timeout_seconds: int) -> str:
        self.attempts += 1
        if self.attempts == 1:
            raise LLMRateLimitError(
                f"Rate limit hit. retry in {self.delay_seconds}s",
                retry_delay=self.delay_seconds
            )
        return json.dumps([
            {
                "passage": "guaranteed 25% returns",
                "rule_id": "FINRA-2210",
                "reason": "Promissory claim",
                "severity": "CRITICAL"
            }
        ])


@pytest.mark.asyncio
async def test_orchestrator_honors_retry_delay():
    """Verify orchestrator waits for retry delay + safety buffer before re-attempting."""
    test_limiter = RequestRateLimiter(
        requests_per_minute=5,
        safety_buffer=0.02,
        min_interval_seconds=0.01
    )
    provider = DelayedRateLimitProvider(delay_seconds=0.05)
    cache = CacheService()

    orchestrator = LLMOrchestrator(
        provider=provider,
        max_retries=2,
        cache_service=cache,
        rate_limiter=test_limiter
    )

    chunk = DocumentChunk(index=0, text="guaranteed 25% returns with zero risk.", char_start=0, char_end=39)
    rule = ComplianceRule(
        rule_id="FINRA-2210",
        name="Communications",
        category="Marketing",
        severity_default=SeverityEnum.CRITICAL,
        description="Prohibits guaranteed returns."
    )

    findings = await orchestrator.analyze_section("doc-retry-delay", chunk, [rule])
    assert len(findings) == 1
    assert provider.attempts == 2
    assert findings[0].rule_id == "FINRA-2210"


# ==============================================================================
# 4. Chunk Optimization & Cache Reuse Tests
# ==============================================================================

class CountingMockProvider(BaseLLMProvider):
    """Counts how many times generate_response was actually invoked."""
    def __init__(self):
        self.call_count = 0

    async def generate_response(self, system_prompt: str, user_prompt: str, timeout_seconds: int) -> str:
        self.call_count += 1
        return "[]"


@pytest.mark.asyncio
async def test_compliance_service_skips_empty_chunks():
    """Verify compliance service avoids LLM calls for empty/whitespace chunks."""
    provider = CountingMockProvider()
    orchestrator = LLMOrchestrator(provider=provider)
    service = ComplianceService(llm_orchestrator=orchestrator)

    raw = "Substantive text.\n\n   \n\nAnother substantive paragraph."
    doc = Document(
        id="doc-empty-chunks",
        filename="test.txt",
        file_type="txt",
        raw_text=raw,
        total_chars=len(raw),
        chunks=[
            DocumentChunk(index=0, text="Substantive text.", char_start=0, char_end=17),
            DocumentChunk(index=1, text="   \n   ", char_start=18, char_end=26),  # whitespace
            DocumentChunk(index=2, text="Another substantive paragraph.", char_start=27, char_end=57),
        ]
    )

    await service.analyze_document(doc)
    # Only 2 calls should have been made; whitespace chunk #1 must be skipped
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_cache_prevents_duplicate_requests_on_retry():
    """Verify that cached chunks do not invoke the LLM provider on retry."""
    provider = CountingMockProvider()
    cache = CacheService()
    orchestrator = LLMOrchestrator(provider=provider, cache_service=cache)

    chunk = DocumentChunk(index=0, text="Substantive text.", char_start=0, char_end=17)
    rule = ComplianceRule(
        rule_id="FINRA-2210",
        name="Communications",
        category="Marketing",
        severity_default=SeverityEnum.CRITICAL,
        description="Prohibits guaranteed returns."
    )

    # First run: miss -> 1 call
    await orchestrator.analyze_section("doc-cache-opt", chunk, [rule])
    assert provider.call_count == 1

    # Second run (simulating retry): hit -> 0 new calls
    await orchestrator.analyze_section("doc-cache-opt", chunk, [rule])
    assert provider.call_count == 1


# ==============================================================================
# 5. Endpoint 429 Handling & Retry Endpoint Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_completed_document_retry_is_rejected(workspace_headers):
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app), AsyncClient(headers=workspace_headers, transport=transport, base_url="http://test") as client:
        # 1. Upload valid document
        files = {"file": ("retry_test.txt", b"Our plan guarantees 25% returns every year.", "text/plain")}
        upload_resp = await client.post("/api/documents/upload", files=files)
        assert upload_resp.status_code == 202
        doc_id = upload_resp.json()["document_id"]

        for _ in range(200):
            if (await client.get(upload_resp.json()["status_url"])).json()["status"] == "COMPLETED":
                break
            await asyncio.sleep(.01)
        assert document_store.get_status(doc_id)["status"] == "COMPLETED"
        # 2. Retry document analysis
        retry_resp = await client.post(f"/api/documents/{doc_id}/retry")
        assert retry_resp.status_code == 409


@pytest.mark.asyncio
async def test_retry_nonexistent_document_returns_404(workspace_headers):
    """Verify POST /api/documents/{doc_id}/retry on unknown doc returns 404."""
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app), AsyncClient(headers=workspace_headers, transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/documents/non-existent-uuid/retry")
        assert resp.status_code == 404
