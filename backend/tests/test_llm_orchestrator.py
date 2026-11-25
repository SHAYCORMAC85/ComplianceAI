"""
Unit Tests for LLM Orchestrator & Cache Service
-----------------------------------------------
Tests prompt generation, structured JSON parsing, resilience mechanisms
(rate limits with exponential backoff, timeouts, malformed JSON recovery),
cache hits/misses, and human governance constraints.

All tests use mocked responses — zero paid API calls are required.
"""

import asyncio
import json
import pytest
from backend.models.document import DocumentChunk
from backend.models.finding import RawFinding, SeverityEnum
from backend.models.rule import ComplianceRule
from backend.services.cache_service import CacheService
from unittest.mock import AsyncMock, MagicMock, patch
from backend.services.llm_orchestrator import (
    BaseLLMProvider,
    GeminiLLMProvider,
    LLMOrchestrator,
    MockLLMProvider,
    OpenAILLMProvider,
    LLMError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMServerError,
    LLMMalformedJSONError,
    LLMAuthenticationError,
    LLMModelNotFoundError,
    LLMPermissionDeniedError,
    LLMInvalidRequestError,
)


@pytest.fixture
def sample_rule():
    return ComplianceRule(
        rule_id="FINRA-2210",
        name="Communications with the Public",
        category="Marketing",
        description="Prohibits promissory and guaranteed return statements.",
        keywords=["guarantee", "zero risk"],
        severity_default=SeverityEnum.CRITICAL,
        active=True
    )


@pytest.fixture
def sample_chunk():
    return DocumentChunk(
        index=0,
        text="We offer guaranteed returns of 18% per annum with absolutely no risk of loss.",
        char_start=0,
        char_end=74
    )


# ==============================================================================
# Cache Service Tests
# ==============================================================================

def test_cache_service_lifecycle():
    """Verify build_key, set, get, has, invalidate, and telemetry stats."""
    cache = CacheService()
    key = cache.build_key(document_id="doc-1", prompt_version="v1.0", model_id="gpt-4o", chunk_index=0)

    assert not cache.has(key)
    assert cache.get(key) is None
    assert cache.misses == 1

    dummy_data = [{"dummy": "finding"}]
    cache.set(key, dummy_data)

    assert cache.has(key)
    retrieved = cache.get(key)
    assert retrieved == dummy_data
    assert cache.hits == 1

    stats = cache.get_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["total_keys"] == 1

    # Invalidation by document_id
    deleted = cache.invalidate_document("doc-1")
    assert deleted == 1
    assert not cache.has(key)


# ==============================================================================
# Prompt Construction & Governance Tests
# ==============================================================================

def test_governance_invariant_in_system_prompt():
    """Verify system prompt explicitly forbids the LLM from approving or rejecting documents."""
    orchestrator = LLMOrchestrator(provider_name="mock", prompt_version="v1.0")
    sys_prompt = orchestrator.build_system_prompt()

    assert "NEVER approve or reject documents" in sys_prompt
    assert "reserved for human compliance officers" in sys_prompt
    assert "v1.0" in sys_prompt


def test_user_prompt_construction(sample_rule: ComplianceRule, sample_chunk: DocumentChunk):
    """Verify user prompt embeds rules and chunk text correctly."""
    orchestrator = LLMOrchestrator(provider_name="mock")
    user_prompt = orchestrator.build_user_prompt(sample_chunk.text, [sample_rule])

    assert "FINRA-2210" in user_prompt
    assert sample_chunk.text in user_prompt
    assert "passage" in user_prompt
    assert "rule_id" in user_prompt


# ==============================================================================
# Successful Analysis & Cache Hit Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_llm_orchestrator_successful_analysis(sample_rule: ComplianceRule, sample_chunk: DocumentChunk):
    """Verify analysis returns structured RawFinding models using mock provider."""
    cache = CacheService()
    orchestrator = LLMOrchestrator(provider_name="mock", cache_service=cache)

    findings = await orchestrator.analyze_section(
        document_id="doc-test",
        chunk=sample_chunk,
        rules=[sample_rule]
    )

    assert len(findings) == 1
    assert isinstance(findings[0], RawFinding)
    assert findings[0].rule_id == "FINRA-2210"
    assert "guaranteed returns" in findings[0].passage
    assert findings[0].severity == SeverityEnum.CRITICAL


@pytest.mark.asyncio
async def test_llm_orchestrator_cache_hit(sample_rule: ComplianceRule, sample_chunk: DocumentChunk):
    """Verify that a second call with the same key returns from cache without calling the provider."""
    cache = CacheService()
    orchestrator = LLMOrchestrator(provider_name="mock", cache_service=cache)

    # First call: cache miss
    await orchestrator.analyze_section("doc-cache-test", sample_chunk, [sample_rule])
    assert cache.hits == 0
    assert cache.misses == 1

    # Second call: cache hit
    findings_cached = await orchestrator.analyze_section("doc-cache-test", sample_chunk, [sample_rule])
    assert cache.hits == 1
    assert len(findings_cached) == 1
    assert findings_cached[0].rule_id == "FINRA-2210"


# ==============================================================================
# Resilience: Rate Limits & Exponential Backoff Tests
# ==============================================================================

class FlakyRateLimitProvider(BaseLLMProvider):
    """Fails with HTTP 429 rate limit errors for initial attempts, then succeeds."""
    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.call_count = 0

    async def generate_response(self, system_prompt: str, user_prompt: str, timeout_seconds: int) -> str:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise LLMRateLimitError("HTTP 429: Too Many Requests")
        return json.dumps([
            {
                "passage": "guaranteed returns of 18%",
                "rule_id": "FINRA-2210",
                "reason": "Promissory claim",
                "severity": "CRITICAL"
            }
        ])


@pytest.mark.asyncio
async def test_rate_limit_exponential_backoff_recovery(sample_rule: ComplianceRule, sample_chunk: DocumentChunk):
    """Verify orchestrator retries and recovers after 2 rate limits when max_retries=3."""
    flaky_provider = FlakyRateLimitProvider(fail_times=2)
    orchestrator = LLMOrchestrator(
        provider=flaky_provider,
        max_retries=3,
        initial_backoff_seconds=0.01  # fast backoff for tests
    )

    findings = await orchestrator.analyze_section("doc-retry", sample_chunk, [sample_rule])
    assert len(findings) == 1
    assert flaky_provider.call_count == 3


@pytest.mark.asyncio
async def test_rate_limit_exhausted_raises_error(sample_rule: ComplianceRule, sample_chunk: DocumentChunk):
    """Verify orchestrator raises LLMRateLimitError when retries are exhausted (never converts to valid finding)."""
    always_failing_provider = FlakyRateLimitProvider(fail_times=5)
    orchestrator = LLMOrchestrator(
        provider=always_failing_provider,
        max_retries=2,
        initial_backoff_seconds=0.01
    )

    with pytest.raises(LLMRateLimitError):
        await orchestrator.analyze_section("doc-exhausted", sample_chunk, [sample_rule])


# ==============================================================================
# Resilience: Timeouts & Malformed JSON Tests
# ==============================================================================

class TimeoutProvider(BaseLLMProvider):
    """Simulates an API call that exceeds the timeout."""
    async def generate_response(self, system_prompt: str, user_prompt: str, timeout_seconds: int) -> str:
        raise LLMTimeoutError(f"Request timed out after {timeout_seconds} seconds")


@pytest.mark.asyncio
async def test_timeout_handling(sample_rule: ComplianceRule, sample_chunk: DocumentChunk):
    """Verify orchestrator raises LLMTimeoutError on provider timeout."""
    orchestrator = LLMOrchestrator(
        provider=TimeoutProvider(),
        max_retries=1,
        initial_backoff_seconds=0.01
    )

    with pytest.raises(LLMTimeoutError):
        await orchestrator.analyze_section("doc-timeout", sample_chunk, [sample_rule])


def test_malformed_json_markdown_recovery():
    """Verify that JSON wrapped in markdown code blocks is recovered successfully."""
    orchestrator = LLMOrchestrator(provider_name="mock")
    markdown_wrapped = (
        "Here are the findings based on your rules:\n"
        "```json\n"
        "[\n"
        "  {\n"
        '    "passage": "guaranteed returns of 18%",\n'
        '    "rule_id": "FINRA-2210",\n'
        '    "reason": "Promissory claims",\n'
        '    "severity": "CRITICAL"\n'
        "  }\n"
        "]\n"
        "```\n"
        "Hope this helps!"
    )
    parsed = orchestrator.extract_and_parse_json(markdown_wrapped)
    assert len(parsed) == 1
    assert parsed[0]["rule_id"] == "FINRA-2210"


def test_unrepairable_malformed_json_raises_error():
    """Verify that completely unparseable text raises LLMMalformedJSONError."""
    orchestrator = LLMOrchestrator(provider_name="mock")
    bad_text = "I apologize, but as an AI I am unable to inspect financial documents."

    with pytest.raises(LLMMalformedJSONError):
        orchestrator.extract_and_parse_json(bad_text)


# ==============================================================================
# Gemini SDK (google-genai) Provider Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_gemini_provider_success():
    """Verify GeminiLLMProvider calls generate_content and returns text."""
    provider = GeminiLLMProvider(model_id="gemini-3.5-flash", api_key="fake-test-key")
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = '[{"passage": "guaranteed 25%", "rule_id": "FINRA-2210", "reason": "Guarantees", "severity": "CRITICAL"}]'
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)
    provider._client = mock_client
    provider._client_loop = asyncio.get_running_loop()

    result = await provider.generate_response("system prompt", "user prompt", timeout_seconds=10)
    assert "guaranteed 25%" in result
    mock_client.aio.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_gemini_provider_timeout():
    """Verify GeminiLLMProvider translates asyncio.TimeoutError into LLMTimeoutError."""
    provider = GeminiLLMProvider(model_id="gemini-3.5-flash", api_key="fake-test-key")
    mock_client = MagicMock()
    async def slow_call(*args, **kwargs):
        await asyncio.sleep(0.5)
    mock_client.aio.models.generate_content = slow_call
    provider._client = mock_client
    provider._client_loop = asyncio.get_running_loop()

    with pytest.raises(LLMTimeoutError):
        await provider.generate_response("system", "user", timeout_seconds=0)


@pytest.mark.asyncio
async def test_gemini_provider_invalid_key_permanent_error():
    """Verify GeminiLLMProvider translates 401/403 ClientError into LLMAuthenticationError."""
    from google.genai import errors
    provider = GeminiLLMProvider(model_id="gemini-3.5-flash", api_key="invalid-key")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=errors.ClientError(401, "API_KEY_INVALID: API key not valid.", None)
    )
    provider._client = mock_client
    provider._client_loop = asyncio.get_running_loop()

    with pytest.raises(LLMAuthenticationError):
        await provider.generate_response("system", "user", timeout_seconds=10)


@pytest.mark.asyncio
async def test_gemini_provider_model_not_found_permanent_error():
    """Verify GeminiLLMProvider translates 404 ClientError into LLMModelNotFoundError."""
    from google.genai import errors
    provider = GeminiLLMProvider(model_id="non-existent-model", api_key="test-key")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=errors.ClientError(404, "models/non-existent-model is not found.", None)
    )
    provider._client = mock_client
    provider._client_loop = asyncio.get_running_loop()

    with pytest.raises(LLMModelNotFoundError):
        await provider.generate_response("system", "user", timeout_seconds=10)


@pytest.mark.asyncio
async def test_gemini_provider_rate_limit_transient_error():
    """Verify GeminiLLMProvider translates 429 ClientError into LLMRateLimitError."""
    from google.genai import errors
    provider = GeminiLLMProvider(model_id="gemini-3.5-flash", api_key="test-key")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=errors.ClientError(429, "Resource exhausted: rate limit exceeded", None)
    )
    provider._client = mock_client
    provider._client_loop = asyncio.get_running_loop()

    with pytest.raises(LLMRateLimitError):
        await provider.generate_response("system", "user", timeout_seconds=10)


@pytest.mark.asyncio
async def test_gemini_provider_server_error_transient_error():
    """Verify GeminiLLMProvider translates 503 ServerError into LLMServerError."""
    from google.genai import errors
    provider = GeminiLLMProvider(model_id="gemini-3.5-flash", api_key="test-key")
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=errors.ServerError(503, "This model is currently experiencing high demand.", None)
    )
    provider._client = mock_client
    provider._client_loop = asyncio.get_running_loop()

    with pytest.raises(LLMServerError):
        await provider.generate_response("system", "user", timeout_seconds=10)


@pytest.mark.asyncio
async def test_orchestrator_fast_fails_on_permanent_errors(sample_rule: ComplianceRule, sample_chunk: DocumentChunk):
    """Verify orchestrator NEVER retries permanent errors (e.g. LLMAuthenticationError, LLMModelNotFoundError)."""
    class PermanentFailProvider(BaseLLMProvider):
        def __init__(self):
            self.call_count = 0
        async def generate_response(self, system_prompt: str, user_prompt: str, timeout_seconds: int) -> str:
            self.call_count += 1
            raise LLMAuthenticationError("Invalid API key")

    provider = PermanentFailProvider()
    orchestrator = LLMOrchestrator(provider=provider, max_retries=3, initial_backoff_seconds=0.01)

    with pytest.raises(LLMAuthenticationError):
        await orchestrator.analyze_section("doc-auth", sample_chunk, [sample_rule])

    # Must have stopped after exactly 1 attempt! No retries!
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_orchestrator_retries_server_errors(sample_rule: ComplianceRule, sample_chunk: DocumentChunk):
    """Verify orchestrator retries transient 503 LLMServerError with backoff."""
    class FlakyServerProvider(BaseLLMProvider):
        def __init__(self):
            self.call_count = 0
        async def generate_response(self, system_prompt: str, user_prompt: str, timeout_seconds: int) -> str:
            self.call_count += 1
            if self.call_count == 1:
                raise LLMServerError("503 High demand")
            return json.dumps([{
                "passage": "guaranteed returns of 18%",
                "rule_id": "FINRA-2210",
                "reason": "Promissory claim",
                "severity": "CRITICAL"
            }])

    provider = FlakyServerProvider()
    orchestrator = LLMOrchestrator(provider=provider, max_retries=2, initial_backoff_seconds=0.01)

    findings = await orchestrator.analyze_section("doc-503", sample_chunk, [sample_rule])
    assert len(findings) == 1
    assert provider.call_count == 2


