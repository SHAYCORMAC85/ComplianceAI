"""
Unit Tests for Pydantic Models
------------------------------
Validates data contracts, field validations, offset range rules,
and enum enforcement across Document, Finding, and Review schemas.
"""

import pytest
from pydantic import ValidationError
from backend.models.document import Document, DocumentChunk
from backend.models.finding import (
    SeverityEnum,
    RawFinding,
    ValidatedFinding,
    FindingValidationResult,
)
from backend.models.review import ReviewDecision, ReviewStatusEnum


# ==============================================================================
# Document & DocumentChunk Model Tests
# ==============================================================================

def test_document_chunk_valid():
    """Verify standard valid chunk creation."""
    chunk = DocumentChunk(
        index=0,
        text="Section 1: General provisions.",
        char_start=0,
        char_end=30
    )
    assert chunk.index == 0
    assert chunk.text == "Section 1: General provisions."
    assert chunk.char_start == 0
    assert chunk.char_end == 30


def test_document_chunk_invalid_offset_range():
    """Ensure char_end cannot be less than char_start."""
    with pytest.raises(ValidationError) as exc_info:
        DocumentChunk(
            index=0,
            text="Invalid offset snippet",
            char_start=50,
            char_end=20  # Invalid: end < start
        )
    assert "char_end" in str(exc_info.value)


def test_document_chunk_negative_index():
    """Ensure chunk index cannot be negative."""
    with pytest.raises(ValidationError):
        DocumentChunk(
            index=-1,
            text="Negative index",
            char_start=0,
            char_end=14
        )


def test_document_model_creation_and_char_sync():
    """Verify Document model auto-syncs total_chars when not matching raw_text."""
    raw = "Sample compliance contract text."
    doc = Document(
        filename="contract.txt",
        file_type="txt",
        raw_text=raw,
        total_chars=0  # Should be auto-corrected to len(raw)
    )
    assert doc.total_chars == len(raw)
    assert doc.file_type == "txt"
    assert doc.id is not None


def test_document_unsupported_file_type():
    """Verify that unsupported extensions are rejected by regex validation."""
    with pytest.raises(ValidationError):
        Document(
            filename="script.exe",
            file_type="exe",  # Not in (txt|pdf|docx)
            raw_text="print('bad')",
            total_chars=12
        )


# ==============================================================================
# Finding Model Tests
# ==============================================================================

def test_raw_finding_valid():
    """Verify valid RawFinding parsing and automatic whitespace stripping."""
    finding = RawFinding(
        passage="  We guarantee a 25% annual return with zero risk.  ",
        rule_id=" FINRA-2210 ",
        reason="Promissory language and guaranteed returns violate public communication rules.",
        severity=SeverityEnum.CRITICAL
    )
    assert finding.passage == "We guarantee a 25% annual return with zero risk."
    assert finding.rule_id == "FINRA-2210"
    assert finding.severity == SeverityEnum.CRITICAL


def test_raw_finding_invalid_severity():
    """Verify rejection of invalid severity strings."""
    with pytest.raises(ValidationError):
        RawFinding(
            passage="Some text excerpt",
            rule_id="RULE-1",
            reason="Some reason here",
            severity="SUPER_URGENT"  # Not a valid SeverityEnum
        )


def test_validated_finding_offset_bounds():
    """Ensure ValidatedFinding enforces offset_end >= offset_start."""
    with pytest.raises(ValidationError):
        ValidatedFinding(
            passage="Sample passage",
            rule_id="FINRA-2111",
            reason="Unsuitable investment recommendation",
            severity=SeverityEnum.HIGH,
            offset_start=150,
            offset_end=100,  # Invalid: end < start
            document_id="doc-12345"
        )


def test_finding_validation_result():
    """Verify audit structure for tracking discarded or accepted findings."""
    raw = RawFinding(
        passage="Sample passage for check",
        rule_id="FINRA-2111",
        reason="Reason text",
        severity=SeverityEnum.HIGH
    )
    audit = FindingValidationResult(
        finding=raw,
        is_valid=False,
        failure_reasons=["Passage text not found verbatim in original document"]
    )
    assert not audit.is_valid
    assert len(audit.failure_reasons) == 1
    assert "not found verbatim" in audit.failure_reasons[0]


# ==============================================================================
# Review Model Tests
# ==============================================================================

def test_review_decision_approved():
    """Verify human officer approval."""
    decision = ReviewDecision(
        document_id="doc-999",
        officer_id="officer_sarah",
        decision=ReviewStatusEnum.APPROVED,
        notes="Document reviewed. All flags checked and mitigated."
    )
    assert decision.decision == ReviewStatusEnum.APPROVED
    assert decision.officer_id == "officer_sarah"
    assert decision.decided_at is not None


def test_review_decision_rejected():
    """Verify human officer rejection."""
    decision = ReviewDecision(
        document_id="doc-999",
        officer_id="officer_mike",
        decision=ReviewStatusEnum.REJECTED,
        notes="Multiple critical FINRA violations identified."
    )
    assert decision.decision == ReviewStatusEnum.REJECTED


def test_review_decision_rejects_pending():
    """A submitted decision cannot be 'PENDING'."""
    with pytest.raises(ValidationError) as exc_info:
        ReviewDecision(
            document_id="doc-999",
            officer_id="officer_mike",
            decision=ReviewStatusEnum.PENDING
        )
    assert "PENDING" in str(exc_info.value)


def test_review_decision_empty_officer_id():
    """Ensure an empty or whitespace officer_id is rejected."""
    with pytest.raises(ValidationError):
        ReviewDecision(
            document_id="doc-999",
            officer_id="   ",
            decision=ReviewStatusEnum.APPROVED
        )

