"""
API Request and Response Schemas
--------------------------------
Pydantic v2 schemas for FastAPI endpoints.
Ensures strict validation for document uploads, findings queries,
processing statuses, and human officer review submissions.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
from backend.models.finding import ValidatedFinding
from backend.models.review import ReviewStatusEnum


class ProcessingStatusEnum(str, Enum):
    """Lifecycle states for uploaded document inspection."""
    QUEUED = "QUEUED"
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DocumentUploadResponse(BaseModel):
    """Response returned upon uploading a document."""
    document_id: str = Field(description="Unique UUID assigned to the document")
    filename: str = Field(description="Original filename")
    file_type: str = Field(description="Detected format (txt, pdf, docx)")
    status: ProcessingStatusEnum = Field(description="Current processing state")
    status_url: str
    message: str = Field(description="Status description")


class DocumentStatusResponse(BaseModel):
    """Response detailing document processing lifecycle."""
    document_id: str
    filename: str
    file_type: str
    status: ProcessingStatusEnum
    stage: str
    analyzed: int
    cached: int
    skipped: int
    failed: int
    progress_tracked: bool
    progress_percent: Optional[int]
    retry_at: Optional[datetime]
    processed_chunks: int = 0
    chunks_count: int
    total_chars: int
    error_message: Optional[str] = None
    has_decision: bool = False
    updated_at: str


class DocumentFindingsResponse(BaseModel):
    """Response containing strictly verified compliance findings."""
    document_id: str
    total_findings: int
    findings: List[ValidatedFinding]


class DocumentTextResponse(BaseModel):
    """Response containing raw extracted text and character metrics for highlighting."""
    document_id: str
    filename: str
    file_type: str
    raw_text: str
    total_chars: int


class ReviewDecisionRequest(BaseModel):
    """Payload submitted by a human compliance officer."""
    officer_id: Optional[str] = Field(default=None, min_length=1, max_length=128, description="Optional compatibility check against the signed-in officer")
    decision: ReviewStatusEnum = Field(description="APPROVED or REJECTED")
    notes: Optional[str] = Field(default="", max_length=8000, description="Optional rationale or mitigation notes")


class ReviewDecisionResponse(BaseModel):
    """Response confirming recorded review decision."""
    document_id: str
    officer_id: str
    decision: ReviewStatusEnum
    notes: Optional[str] = ""
    decided_at: datetime

