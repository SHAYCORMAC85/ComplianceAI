"""
Finding Models
--------------
Pydantic v2 schemas for raw LLM outputs, post-validation compliance findings,
and detailed validation audit results.
Enforces strict enum values for severity and verifies passage integrity.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import uuid
from pydantic import BaseModel, Field, field_validator


class SeverityEnum(str, Enum):
    """Compliance violation severity levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ValidationStageEnum(str, Enum):
    """Pipeline stages where finding validation can pass or fail."""
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    RULE_VALIDATION = "RULE_VALIDATION"
    PASSAGE_VERBATIM_CHECK = "PASSAGE_VERBATIM_CHECK"
    OFFSET_CALCULATION = "OFFSET_CALCULATION"
    NONE = "NONE"


class RawFinding(BaseModel):
    """
    Direct structured finding output produced by the LLM before verification.
    
    Attributes:
        passage: Text excerpt flagged as potentially violating a rule.
        rule_id: The identifier of the compliance rule (e.g. 'FINRA-2111').
        reason: Plain-text explanation of why this passage was flagged.
        severity: Assessed severity level (LOW, MEDIUM, HIGH, CRITICAL).
    """
    passage: str = Field(min_length=3, description="Verbatim quote flagged from the text")
    rule_id: str = Field(min_length=2, description="ID of the violated compliance rule")
    reason: str = Field(min_length=5, description="Explanation of the suspected violation")
    severity: SeverityEnum = Field(description="Violation severity level")

    @field_validator("passage", "rule_id", "reason", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v


class ValidatedFinding(BaseModel):
    """
    A finding that has passed all three verification checks:
    1. Schema conforms to specification.
    2. rule_id exists in the active rules database.
    3. passage exists verbatim in the source document.
    
    Includes character offsets for frontend highlighting.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique finding ID")
    passage: str = Field(min_length=1, description="Verbatim passage verified in source text")
    rule_id: str = Field(min_length=1, description="Verified active rule identifier")
    reason: str = Field(min_length=1, description="Explanation of violation")
    severity: SeverityEnum = Field(description="Assessed severity level")
    offset_start: int = Field(ge=0, description="Start character offset in full document text")
    offset_end: int = Field(ge=0, description="End character offset in full document text")
    document_id: str = Field(min_length=1, description="Associated document ID")
    chunk_index: Optional[int] = Field(default=None, description="Index of source chunk if applicable")
    retrieval_strategy: Optional[str] = Field(default=None, description="Strategy used: 'keyword' or 'fallback'")
    is_valid: bool = Field(default=True, description="Always True for verified findings")
    found_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when finding was validated"
    )

    @field_validator("offset_end")
    @classmethod
    def validate_offset_range(cls, v: int, info) -> int:
        start = info.data.get("offset_start")
        if start is not None and v < start:
            raise ValueError(f"offset_end ({v}) cannot be less than offset_start ({start})")
        return v


class FindingValidationResult(BaseModel):
    """
    Detailed audit result for a single candidate finding, recording whether
    it passed or why it was discarded at any stage of the pipeline.
    """
    finding_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Audit identifier for this validation record"
    )
    finding: Union[RawFinding, Dict[str, Any]] = Field(
        description="Original finding candidate (RawFinding or dictionary)"
    )
    is_valid: bool = Field(description="True if finding passed all checks")
    validation_status: str = Field(
        default="PENDING",
        description="'PASSED' or 'REJECTED'"
    )
    failed_stage: Optional[str] = Field(
        default=None,
        description="Pipeline stage where validation failed, if any"
    )
    failure_reasons: List[str] = Field(
        default_factory=list,
        description="Detailed explanation if finding was rejected"
    )
    retrieval_strategy: Optional[str] = Field(
        default=None,
        description="Rule retrieval strategy used: 'keyword' or 'fallback'"
    )
    validated_finding: Optional[ValidatedFinding] = Field(
        default=None,
        description="The populated ValidatedFinding instance if valid, else None"
    )
