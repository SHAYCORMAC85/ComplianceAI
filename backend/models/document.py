"""
Document Models
---------------
Pydantic v2 schemas for raw documents and extracted text chunks.
Preserves character offsets to enable highlighting in the review interface.
"""

from datetime import datetime, timezone
from typing import List
import uuid
from pydantic import BaseModel, Field, field_validator


class DocumentChunk(BaseModel):
    """
    Represents a logical section/paragraph extracted from a document.
    
    Attributes:
        index: Sequential chunk identifier starting from 0.
        text: The text content of the chunk.
        char_start: Starting character position in the original document.
        char_end: Ending character position (exclusive) in the original document.
    """
    index: int = Field(ge=0, description="0-based sequential chunk index")
    text: str = Field(min_length=1, description="Cleaned chunk text content")
    char_start: int = Field(ge=0, description="Start offset in original text (inclusive)")
    char_end: int = Field(ge=0, description="End offset in original text (exclusive)")

    @field_validator("char_end")
    @classmethod
    def validate_offset_range(cls, v: int, info) -> int:
        """Ensure char_end is greater than or equal to char_start."""
        char_start = info.data.get("char_start")
        if char_start is not None and v < char_start:
            raise ValueError(f"char_end ({v}) cannot be less than char_start ({char_start})")
        return v


class Document(BaseModel):
    """
    Represents an uploaded document after text extraction and chunking.
    
    Attributes:
        id: Unique identifier for the document (UUID4 string).
        filename: Name of the uploaded file.
        file_type: Extension or MIME category ('txt', 'pdf', 'docx').
        raw_text: Full un-modified extracted text.
        total_chars: Total number of characters in raw_text.
        chunks: List of DocumentChunk instances.
        created_at: ISO UTC timestamp of creation.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique document ID")
    filename: str = Field(min_length=1, description="Original filename")
    file_type: str = Field(pattern=r"^(txt|pdf|docx)$", description="Supported file format")
    raw_text: str = Field(default="", description="Original full text of the document")
    total_chars: int = Field(ge=0, description="Length of the raw text")
    chunks: List[DocumentChunk] = Field(default_factory=list, description="Logical sections/chunks")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC creation timestamp"
    )

    @field_validator("total_chars")
    @classmethod
    def validate_total_chars(cls, v: int, info) -> int:
        """Sync total_chars if raw_text is provided."""
        raw_text = info.data.get("raw_text")
        if raw_text is not None and v != len(raw_text):
            return len(raw_text)
        return v

