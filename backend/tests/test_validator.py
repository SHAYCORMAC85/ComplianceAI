"""
Unit Tests for Validator Service
--------------------------------
Tests the multi-stage quality control gate:
- Schema validation (missing fields, invalid severity enum, malformed structures).
- Rule ID verification (nonexistent rules, inactive rules).
- Exact verbatim passage matching (rejection of hallucinated and paraphrased quotes).
- Strict audit logging and invariant enforcement (rejected findings never appear in verified output).
"""

import json
from pathlib import Path
import pytest
from backend.models.document import DocumentChunk
from backend.models.finding import (
    RawFinding,
    SeverityEnum,
    ValidationStageEnum,
)
from backend.services.rules_engine import RulesEngine
from backend.services.validator import Validator


@pytest.fixture
def document_text():
    return (
        "CONFIDENTIAL INVESTMENT PROSPECTUS\n\n"
        "Article 1: Advisory Terms.\n"
        "The broker will recommend speculative options regardless of customer suitability.\n\n"
        "Article 2: Marketing Guarantees.\n"
        "We promise guaranteed returns of 25% with zero risk to invested capital.\n\n"
        "Article 3: Fee Schedule.\n"
        "A hidden administrative fee of 4% shall be charged unilaterally every quarter."
    )


@pytest.fixture
def validator():
    return Validator()


# ==============================================================================
# Valid Finding Tests
# ==============================================================================

def test_validate_single_raw_finding_success(validator: Validator, document_text: str):
    """Verify that a valid RawFinding passes all checks and gets exact offsets."""
    raw = RawFinding(
        passage="We promise guaranteed returns of 25% with zero risk to invested capital.",
        rule_id="FINRA-2210",
        reason="Promissory guarantee of profit and claim of zero risk violates FINRA 2210.",
        severity=SeverityEnum.CRITICAL
    )

    result = validator.validate_single_finding(raw, document_text, document_id="doc-123")

    assert result.is_valid is True
    assert result.validation_status == "PASSED"
    assert result.failed_stage is None
    assert len(result.failure_reasons) == 0
    assert result.validated_finding is not None

    vf = result.validated_finding
    assert vf.passage == raw.passage
    assert vf.rule_id == "FINRA-2210"
    assert vf.severity == SeverityEnum.CRITICAL
    assert vf.offset_start >= 0
    assert vf.offset_end > vf.offset_start
    # Invariant: slice in document_text equals passage
    assert document_text[vf.offset_start:vf.offset_end] == raw.passage


def test_validate_dict_candidate_success(validator: Validator, document_text: str):
    """Verify that a raw dictionary candidate can be parsed and validated."""
    dict_candidate = {
        "passage": "A hidden administrative fee of 4% shall be charged unilaterally every quarter.",
        "rule_id": "CFPB-UDAAP",
        "reason": "Unilateral assessment of undisclosed or hidden fees.",
        "severity": "HIGH"
    }

    result = validator.validate_single_finding(dict_candidate, document_text, document_id="doc-123")
    assert result.is_valid is True
    assert result.validated_finding is not None
    assert result.validated_finding.rule_id == "CFPB-UDAAP"


# ==============================================================================
# Stage 1: Schema Validation Failure Tests
# ==============================================================================

def test_reject_missing_fields(validator: Validator, document_text: str):
    """Verify rejection when required fields are missing from dictionary."""
    malformed_candidate = {
        "passage": "We promise guaranteed returns of 25% with zero risk to invested capital.",
        # Missing 'rule_id', 'reason', and 'severity'
    }

    result = validator.validate_single_finding(malformed_candidate, document_text)
    assert result.is_valid is False
    assert result.validation_status == "REJECTED"
    assert result.failed_stage == ValidationStageEnum.SCHEMA_VALIDATION.value
    assert result.validated_finding is None
    assert any("rule_id" in r for r in result.failure_reasons)


def test_reject_invalid_severity_enum(validator: Validator, document_text: str):
    """Verify rejection when severity is not a valid enum value."""
    invalid_severity_candidate = {
        "passage": "We promise guaranteed returns of 25% with zero risk to invested capital.",
        "rule_id": "FINRA-2210",
        "reason": "Reason text here",
        "severity": "MEGA_CRITICAL"  # Invalid enum value
    }

    result = validator.validate_single_finding(invalid_severity_candidate, document_text)
    assert result.is_valid is False
    assert result.failed_stage == ValidationStageEnum.SCHEMA_VALIDATION.value
    assert result.validated_finding is None


# ==============================================================================
# Stage 2: Rule Verification Failure Tests
# ==============================================================================

def test_reject_nonexistent_rule_id(validator: Validator, document_text: str):
    """Verify rejection when the rule ID does not exist in the database."""
    raw = RawFinding(
        passage="We promise guaranteed returns of 25% with zero risk to invested capital.",
        rule_id="SEC-NONEXISTENT-999",  # Does not exist
        reason="Fabricated rule reference",
        severity=SeverityEnum.MEDIUM
    )

    result = validator.validate_single_finding(raw, document_text)
    assert result.is_valid is False
    assert result.validation_status == "REJECTED"
    assert result.failed_stage == ValidationStageEnum.RULE_VALIDATION.value
    assert result.validated_finding is None
    assert "does not exist in the active compliance rules database" in result.failure_reasons[0]


def test_reject_inactive_rule_id(tmp_path: Path, document_text: str):
    """Verify rejection when the cited rule is inactive."""
    custom_rules = [
        {
            "rule_id": "EXPIRED-RULE-101",
            "name": "Expired Regulation",
            "category": "Legacy",
            "description": "Inactive rule.",
            "keywords": ["guaranteed"],
            "severity_default": "LOW",
            "active": False  # Inactive
        }
    ]
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps(custom_rules), encoding="utf-8")

    custom_engine = RulesEngine(rules_path=rules_file)
    custom_validator = Validator(rules_engine=custom_engine)

    raw = RawFinding(
        passage="We promise guaranteed returns of 25% with zero risk to invested capital.",
        rule_id="EXPIRED-RULE-101",
        reason="Citing inactive rule",
        severity=SeverityEnum.LOW
    )

    result = custom_validator.validate_single_finding(raw, document_text)
    assert result.is_valid is False
    assert result.validation_status == "REJECTED"
    assert result.failed_stage == ValidationStageEnum.RULE_VALIDATION.value
    assert result.validated_finding is None
    assert "marked inactive" in result.failure_reasons[0]


# ==============================================================================
# Stage 3: Verbatim Passage Matching Failure Tests
# ==============================================================================

def test_reject_hallucinated_passage(validator: Validator, document_text: str):
    """Verify rejection when the LLM hallucinates a passage not in the document."""
    hallucinated = RawFinding(
        passage="The CEO personally guaranteed that stock prices would double next month.",
        rule_id="FINRA-2210",
        reason="Promissory statement",
        severity=SeverityEnum.CRITICAL
    )

    result = validator.validate_single_finding(hallucinated, document_text)
    assert result.is_valid is False
    assert result.validation_status == "REJECTED"
    assert result.failed_stage == ValidationStageEnum.PASSAGE_VERBATIM_CHECK.value
    assert result.validated_finding is None
    assert "not appear verbatim" in result.failure_reasons[0]


def test_reject_paraphrased_passage(validator: Validator, document_text: str):
    """
    CRITICAL CHECK:
    Ensure subtle paraphrasing is rejected. The passage must be an exact verbatim match.
    Original: 'We promise guaranteed returns of 25% with zero risk to invested capital.'
    Paraphrased: 'We promise 25% guaranteed returns with zero risk to capital.'
    """
    paraphrased = RawFinding(
        passage="We promise 25% guaranteed returns with zero risk to capital.",  # Paraphrased!
        rule_id="FINRA-2210",
        reason="Promissory language",
        severity=SeverityEnum.CRITICAL
    )

    result = validator.validate_single_finding(paraphrased, document_text)
    assert result.is_valid is False
    assert result.failed_stage == ValidationStageEnum.PASSAGE_VERBATIM_CHECK.value
    assert result.validated_finding is None


# ==============================================================================
# Batch Validation & Invariant Tests
# ==============================================================================

def test_batch_validation_strict_separation(validator: Validator, document_text: str):
    """
    Ensure validate_findings returns ONLY valid findings in the verified list,
    while capturing the audit history of all rejected findings.
    """
    candidates = [
        # Candidate 1: Completely valid
        RawFinding(
            passage="The broker will recommend speculative options regardless of customer suitability.",
            rule_id="FINRA-2111",
            reason="Unsuitable recommendation without regard to client profile.",
            severity=SeverityEnum.HIGH
        ),
        # Candidate 2: Hallucinated passage
        RawFinding(
            passage="We will hide customer losses under offshore subsidiary accounts.",
            rule_id="SEC-10B-5",
            reason="Fraudulent accounting",
            severity=SeverityEnum.CRITICAL
        ),
        # Candidate 3: Nonexistent rule
        RawFinding(
            passage="A hidden administrative fee of 4% shall be charged unilaterally every quarter.",
            rule_id="FAKE-REGULATION-99",
            reason="Deceptive fee",
            severity=SeverityEnum.MEDIUM
        )
    ]

    verified_findings, audit_trail = validator.validate_findings(candidates, document_text)

    # Invariant: exactly 1 finding was valid
    assert len(verified_findings) == 1
    assert verified_findings[0].rule_id == "FINRA-2111"

    # Invariant: audit trail contains all 3 candidates
    assert len(audit_trail) == 3
    assert audit_trail[0].is_valid is True
    assert audit_trail[1].is_valid is False
    assert audit_trail[1].failed_stage == ValidationStageEnum.PASSAGE_VERBATIM_CHECK.value
    assert audit_trail[2].is_valid is False
    assert audit_trail[2].failed_stage == ValidationStageEnum.RULE_VALIDATION.value

    # Invariant: rejected findings must have None for validated_finding
    assert audit_trail[1].validated_finding is None
    assert audit_trail[2].validated_finding is None


def test_chunk_context_passed_to_offset_calculator(validator: Validator, document_text: str):
    """Verify that chunk context is accepted and propagates into ValidatedFinding."""
    chunk = DocumentChunk(
        index=2,
        text="Article 3: Fee Schedule.\nA hidden administrative fee of 4% shall be charged unilaterally every quarter.",
        char_start=document_text.index("Article 3: Fee Schedule."),
        char_end=len(document_text)
    )
    raw = RawFinding(
        passage="A hidden administrative fee of 4% shall be charged unilaterally every quarter.",
        rule_id="CFPB-UDAAP",
        reason="Unilateral hidden fee",
        severity=SeverityEnum.HIGH
    )

    result = validator.validate_single_finding(raw, document_text, chunk=chunk)
    assert result.is_valid is True
    assert result.validated_finding is not None
    assert result.validated_finding.chunk_index == 2

    wrong_chunk = DocumentChunk(index=0, text=document_text[:12], char_start=0, char_end=12)
    assert not validator.validate_single_finding(raw, document_text, chunk=wrong_chunk).is_valid
