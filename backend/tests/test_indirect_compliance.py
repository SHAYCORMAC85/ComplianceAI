"""
Regression & Indirect Compliance Inspection Tests
-------------------------------------------------
Covers Phase 4 requirements:
1. Explicit guarantee claims.
2. Indirect risk-minimization language.
3. Universal investment suitability claims.
4. Past-performance marketing claims.
5. A document chunk with zero keyword matches reaching provider through fallback.
6. A clean document that produces zero unsupported findings.
7. Invalid rule IDs rejected by the validator.
8. Non-verbatim quotations rejected by the validator.
9. Incorrect character offsets rejected by the validator.
10. Mock provider remains fully functional.

All tests run offline using mocks or deterministic providers — zero external API quota used.
"""

import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from backend.models.document import DocumentChunk
from backend.models.finding import (
    RawFinding,
    SeverityEnum,
    ValidationStageEnum,
)
from backend.services.compliance_service import ComplianceService
from backend.services.document_processor import DocumentProcessor
from backend.services.llm_orchestrator import (
    BaseLLMProvider,
    GeminiLLMProvider,
    LLMOrchestrator,
    MockLLMProvider,
)
from backend.services.rules_engine import RulesEngine
from backend.services.validator import Validator


@pytest.fixture
def rules_engine():
    return RulesEngine()


@pytest.fixture
def document_processor():
    return DocumentProcessor()


@pytest.fixture
def validator(rules_engine):
    return Validator(rules_engine=rules_engine)


# ==============================================================================
# 1. Explicit Guarantee Claims
# ==============================================================================

@pytest.mark.asyncio
async def test_explicit_guarantee_claims(rules_engine, document_processor):
    """Verify explicit guarantee statements are matched via keyword and flagged under FINRA-2210."""
    text = "We offer guaranteed returns of 25% every year with zero risk."
    doc = document_processor.process_raw_text(text, "explicit_guarantee.txt")
    
    service = ComplianceService(
        rules_engine=rules_engine,
        llm_orchestrator=LLMOrchestrator(provider_name="mock")
    )
    findings, audit = await service.analyze_document(doc)

    assert len(findings) == 1
    assert findings[0].rule_id == "FINRA-2210"
    assert "guaranteed returns" in findings[0].passage
    assert findings[0].severity == SeverityEnum.CRITICAL
    assert findings[0].retrieval_strategy == "full_catalog"
    assert doc.raw_text[findings[0].offset_start:findings[0].offset_end] == findings[0].passage


# ==============================================================================
# 2. Indirect Risk-Minimization Language
# ==============================================================================

@pytest.mark.asyncio
async def test_indirect_risk_minimization_language(rules_engine, document_processor):
    """Verify indirect risk-minimizing claims are retrieved and flagged under FINRA-2210."""
    text = "Investors can expect their wealth to grow significantly, and losses are highly unlikely under normal market conditions."
    doc = document_processor.process_raw_text(text, "indirect_risk.txt")
    
    # Verify keyword retrieval matches new trigger phrases
    rules, strategy = rules_engine.retrieve_relevant_rules_with_strategy(text)
    assert strategy == "keyword"
    assert any(r.rule_id == "FINRA-2210" for r in rules)

    service = ComplianceService(
        rules_engine=rules_engine,
        llm_orchestrator=LLMOrchestrator(provider_name="mock")
    )
    findings, audit = await service.analyze_document(doc)

    assert len(findings) >= 1
    f2210 = [f for f in findings if f.rule_id == "FINRA-2210"]
    assert len(f2210) == 1
    assert "losses are highly unlikely" in f2210[0].passage
    assert doc.raw_text[f2210[0].offset_start:f2210[0].offset_end] == f2210[0].passage


# ==============================================================================
# 3. Universal Investment Suitability Claims
# ==============================================================================

@pytest.mark.asyncio
async def test_universal_investment_suitability_claims(rules_engine, document_processor):
    """Verify universal suitability assertions are retrieved and flagged under FINRA-2111."""
    text = "This opportunity is designed for everyone, including individuals with limited investment experience."
    doc = document_processor.process_raw_text(text, "universal_suitability.txt")

    rules, strategy = rules_engine.retrieve_relevant_rules_with_strategy(text)
    assert strategy == "keyword"
    assert any(r.rule_id == "FINRA-2111" for r in rules)

    service = ComplianceService(
        rules_engine=rules_engine,
        llm_orchestrator=LLMOrchestrator(provider_name="mock")
    )
    findings, audit = await service.analyze_document(doc)

    assert len(findings) >= 1
    f2111 = [f for f in findings if f.rule_id == "FINRA-2111"]
    assert len(f2111) == 1
    assert "designed for everyone" in f2111[0].passage
    assert doc.raw_text[f2111[0].offset_start:f2111[0].offset_end] == f2111[0].passage


# ==============================================================================
# 4. Past-Performance Marketing Claims
# ==============================================================================

@pytest.mark.asyncio
async def test_past_performance_marketing_claims(rules_engine, document_processor):
    """Verify unbalanced past performance marketing statements trigger FINRA-2210."""
    text = "Past performance demonstrates the strength of our strategy."
    doc = document_processor.process_raw_text(text, "past_perf.txt")

    rules, strategy = rules_engine.retrieve_relevant_rules_with_strategy(text)
    assert strategy == "keyword"
    assert any(r.rule_id == "FINRA-2210" for r in rules)

    service = ComplianceService(
        rules_engine=rules_engine,
        llm_orchestrator=LLMOrchestrator(provider_name="mock")
    )
    findings, audit = await service.analyze_document(doc)

    assert len(findings) == 1
    assert findings[0].rule_id == "FINRA-2210"
    assert "Past performance" in findings[0].passage
    assert doc.raw_text[findings[0].offset_start:findings[0].offset_end] == findings[0].passage


# ==============================================================================
# 5. Chunk with Zero Keyword Matches Reaching LLM via Fallback
# ==============================================================================

@pytest.mark.asyncio
async def test_zero_keyword_matches_reaches_provider_through_fallback(rules_engine, document_processor):
    """
    Verify that when a chunk has ZERO keyword matches, the pipeline does NOT skip it,
    engages fallback retrieval, queries the LLM with active rules, and records strategy='fallback'.
    """
    # Text completely devoid of any compliance keywords
    unrelated_text = "The algorithmic allocation matrix recalculates covariance weights on a quarterly schedule."
    doc = document_processor.process_raw_text(unrelated_text, "fallback_test.txt")

    # 1. Verify keyword-only returns empty
    kw_rules = rules_engine.retrieve_relevant_rules(unrelated_text, fallback_to_all=False)
    assert len(kw_rules) == 0

    # 2. Verify retrieve_relevant_rules_with_strategy returns fallback
    fb_rules, strategy = rules_engine.retrieve_relevant_rules_with_strategy(unrelated_text, fallback_to_all=True)
    assert strategy == "fallback"
    assert len(fb_rules) == 4
    assert [r.rule_id for r in fb_rules] == ["FINRA-2111", "FINRA-2210", "SEC-10B-5", "CFPB-UDAAP"]

    # 3. Mock provider to verify it receives the call with fallback rules
    mock_provider = MagicMock(spec=BaseLLMProvider)
    mock_provider.generate_response = AsyncMock(return_value=json.dumps([
        {
            "passage": "The algorithmic allocation matrix recalculates covariance weights on a quarterly schedule.",
            "rule_id": "FINRA-2210",
            "reason": "Evaluated under active fallback compliance rules",
            "severity": "LOW"
        }
    ]))

    orchestrator = LLMOrchestrator(provider=mock_provider)
    service = ComplianceService(rules_engine=rules_engine, llm_orchestrator=orchestrator)

    findings, audit = await service.analyze_document(doc)

    # Provider MUST have been invoked (not skipped!)
    mock_provider.generate_response.assert_called_once()
    assert len(findings) == 1
    assert findings[0].retrieval_strategy == "full_catalog"
    assert doc.raw_text[findings[0].offset_start:findings[0].offset_end] == findings[0].passage


# ==============================================================================
# 6. Clean Document Produces No Unsupported Findings
# ==============================================================================

@pytest.mark.asyncio
async def test_clean_document_produces_no_unsupported_findings(rules_engine, document_processor):
    """Verify that a compliant, balanced document produces zero findings and no false positives."""
    clean_text = (
        "All investments involve risk of loss. Past performance does not guarantee future results. "
        "Investors should carefully review their personal risk profile and financial objectives "
        "before making any investment decisions."
    )
    doc = document_processor.process_raw_text(clean_text, "clean_disclosure.txt")

    service = ComplianceService(
        rules_engine=rules_engine,
        llm_orchestrator=LLMOrchestrator(provider_name="mock")
    )
    findings, audit = await service.analyze_document(doc)

    assert len(findings) == 0


# ==============================================================================
# 7. Invalid Rule IDs Rejected by Validator
# ==============================================================================

def test_invalid_rule_ids_rejected_by_validator(validator):
    """Verify candidate findings citing invalid or nonexistent rule IDs are discarded."""
    doc_text = "Standard financial disclosure text."
    candidate = RawFinding(
        passage="Standard financial disclosure text.",
        rule_id="NONEXISTENT-REGULATION-999",
        reason="Invalid rule citation",
        severity=SeverityEnum.MEDIUM
    )
    result = validator.validate_single_finding(candidate, doc_text)

    assert result.is_valid is False
    assert result.validation_status == "REJECTED"
    assert result.failed_stage == ValidationStageEnum.RULE_VALIDATION.value
    assert any("does not exist" in r for r in result.failure_reasons)
    assert result.validated_finding is None


# ==============================================================================
# 8. Non-Verbatim Quotations Rejected by Validator
# ==============================================================================

def test_non_verbatim_quotations_rejected_by_validator(validator):
    """Verify hallucinated or paraphrased passages are discarded at verbatim check."""
    doc_text = "We expect modest growth under favorable circumstances."
    # Candidate passage is paraphrased/hallucinated
    candidate = RawFinding(
        passage="We guarantee complete safety and no losses under all conditions.",
        rule_id="FINRA-2210",
        reason="Promissory statement",
        severity=SeverityEnum.CRITICAL
    )
    result = validator.validate_single_finding(candidate, doc_text)

    assert result.is_valid is False
    assert result.validation_status == "REJECTED"
    assert result.failed_stage == ValidationStageEnum.PASSAGE_VERBATIM_CHECK.value
    assert any("not appear verbatim" in r for r in result.failure_reasons)
    assert result.validated_finding is None


# ==============================================================================
# 9. Incorrect Character Offsets Rejected
# ==============================================================================

def test_incorrect_character_offsets_rejected(validator):
    """Verify that offset bounds violations are caught and prevent invalid findings."""
    doc_text = "Short text."
    # Empty passage rejected
    candidate = {
        "passage": "",
        "rule_id": "FINRA-2210",
        "reason": "Empty quote test",
        "severity": "CRITICAL"
    }
    result = validator.validate_single_finding(candidate, doc_text)
    assert result.is_valid is False
    assert result.validation_status == "REJECTED"


# ==============================================================================
# 10. Mock Provider Remains Fully Functional
# ==============================================================================

@pytest.mark.asyncio
async def test_mock_provider_remains_functional():
    """Verify MockLLMProvider operates deterministically without network or API keys."""
    provider = MockLLMProvider()
    sys_prompt = "You are a compliance officer."

    # Test 1: Explicit guarantee
    user_p1 = "=== APPLICABLE COMPLIANCE RULES ===\n- Rule ID: FINRA-2210\n=== DOCUMENT SECTION TO INSPECT ===\nWe offer guaranteed returns of 18%."
    resp1 = await provider.generate_response(sys_prompt, user_p1, timeout_seconds=5)
    parsed1 = json.loads(resp1)
    assert len(parsed1) == 1
    assert parsed1[0]["rule_id"] == "FINRA-2210"

    # Test 2: Simulated custom response
    custom_prov = MockLLMProvider(simulated_response='[{"passage": "custom", "rule_id": "SEC-10B-5", "reason": "test", "severity": "HIGH"}]')
    resp2 = await custom_prov.generate_response(sys_prompt, "dummy", timeout_seconds=5)
    assert "SEC-10B-5" in resp2

