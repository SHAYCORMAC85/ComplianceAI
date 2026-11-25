"""
Review Models
-------------
Pydantic v2 schemas for human compliance officer approval/rejection decisions.
Ensures compliance governance: the LLM never decides, only human officers can approve or reject.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class ReviewStatusEnum(str, Enum):
    """Permitted human review decisions."""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


class ReviewDecision(BaseModel):
    """
    Formal record of a human compliance officer's decision on a document.
    
    Attributes:
        document_id: The document being decided upon.
        officer_id: Identifier / username of the human compliance officer.
        decision: Final status ('APPROVED' or 'REJECTED').
        notes: Optional explanation or notes from the officer.
        decided_at: UTC timestamp when the review was submitted.
    """
    document_id: str = Field(min_length=1, description="Target document ID")
    officer_id: str = Field(min_length=1, description="Officer ID or username")
    decision: ReviewStatusEnum = Field(description="APPROVED or REJECTED")
    notes: Optional[str] = Field(default="", description="Optional human officer rationale/notes")
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the review decision"
    )

    @field_validator("officer_id")
    @classmethod
    def validate_officer_id(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("officer_id cannot be empty or purely whitespace")
        return trimmed

    @field_validator("decision")
    @classmethod
    def validate_actionable_decision(cls, v: ReviewStatusEnum) -> ReviewStatusEnum:
        """When submitting a decision, it must be either APPROVED or REJECTED."""
        if v == ReviewStatusEnum.PENDING:
            raise ValueError("A submitted review decision must be APPROVED or REJECTED, not PENDING")
        return v

