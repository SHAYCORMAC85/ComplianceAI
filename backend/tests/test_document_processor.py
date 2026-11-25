"""
Unit Tests for Document Processor
---------------------------------
Tests text reading, paragraph chunking, strict character offset preservation,
and edge cases (empty files, encoding variants, oversized paragraphs).
"""

import pytest
from pathlib import Path
from backend.services.document_processor import (
    DocumentProcessor,
    DocumentEmptyError,
    UnsupportedFileTypeError,
)


@pytest.fixture
def processor():
    """Returns a default DocumentProcessor instance."""
    return DocumentProcessor(min_chunk_chars=20, max_chunk_chars=500)


@pytest.fixture
def sample_txt_file(tmp_path: Path):
    """Creates a temporary sample multi-paragraph text file."""
    content = (
        "Article 1: Preliminary Provisions.\n"
        "This agreement is entered into between Acme Capital and the Client.\n\n"
        "Article 2: Investment Strategy and Risk Disclosure.\n"
        "We offer guaranteed returns of 18% per annum with absolutely no risk of loss.\n"
        "All customer funds are placed into proprietary high-frequency arbitrage algorithms.\n\n"
        "Article 3: Fees and Termination.\n"
        "A hidden processing fee of 3.5% will be assessed unilaterally without prior notice."
    )
    file_path = tmp_path / "sample_compliance_doc.txt"
    file_path.write_text(content, encoding="utf-8")
    return file_path, content


# ==============================================================================
# File Reading & Validation Tests
# ==============================================================================

def test_read_valid_txt_file(processor: DocumentProcessor, sample_txt_file):
    """Ensure valid text files are read completely."""
    file_path, expected_content = sample_txt_file
    text = processor.read_text_file(file_path)
    assert text == expected_content


def test_read_nonexistent_file(processor: DocumentProcessor, tmp_path: Path):
    """Ensure FileNotFoundError is raised for non-existent files."""
    missing = tmp_path / "does_not_exist.txt"
    with pytest.raises(FileNotFoundError):
        processor.read_text_file(missing)


def test_read_empty_file(processor: DocumentProcessor, tmp_path: Path):
    """Ensure DocumentEmptyError is raised for zero-byte or whitespace files."""
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("   \n\n   ", encoding="utf-8")
    with pytest.raises(DocumentEmptyError):
        processor.read_text_file(empty_file)


def test_unsupported_file_extension(processor: DocumentProcessor, tmp_path: Path):
    """Ensure non-txt files are rejected in Phase 1."""
    pdf_fake = tmp_path / "document.pdf"
    pdf_fake.write_text("dummy text")
    with pytest.raises(UnsupportedFileTypeError):
        processor.process_txt_file(pdf_fake)


# ==============================================================================
# Chunking & Character Offset Integrity Tests
# ==============================================================================

def test_chunk_text_preserves_exact_offsets(processor: DocumentProcessor, sample_txt_file):
    """
    CRITICAL TEST:
    Verifies that for every chunk, raw_text[char_start:char_end] == chunk.text exactly.
    """
    _, raw_text = sample_txt_file
    chunks = processor.chunk_text(raw_text)

    assert len(chunks) == 3

    for chunk in chunks:
        # Exact substring slice verification
        extracted_slice = raw_text[chunk.char_start:chunk.char_end]
        assert extracted_slice == chunk.text, (
            f"Offset mismatch on chunk {chunk.index}!\n"
            f"Expected: {chunk.text!r}\n"
            f"Got slice: {extracted_slice!r}"
        )
        assert chunk.char_end > chunk.char_start


def test_sequential_chunk_indices(processor: DocumentProcessor, sample_txt_file):
    """Verify chunks have 0-indexed, ascending sequential indices."""
    _, raw_text = sample_txt_file
    chunks = processor.chunk_text(raw_text)

    for i, chunk in enumerate(chunks):
        assert chunk.index == i


def test_process_txt_file_creates_document_model(processor: DocumentProcessor, sample_txt_file):
    """Verify process_txt_file returns a valid Document instance."""
    file_path, raw_text = sample_txt_file
    doc = processor.process_txt_file(file_path)

    assert doc.filename == "sample_compliance_doc.txt"
    assert doc.file_type == "txt"
    assert doc.raw_text == raw_text
    assert doc.total_chars == len(raw_text)
    assert len(doc.chunks) == 3


def test_process_raw_text_direct(processor: DocumentProcessor):
    """Test chunking in-memory text directly without disk I/O."""
    text = "Paragraph One is here.\n\nParagraph Two is right after."
    doc = processor.process_raw_text(text, filename="in_memory.txt")

    assert doc.filename == "in_memory.txt"
    assert len(doc.chunks) == 2
    assert text[doc.chunks[0].char_start:doc.chunks[0].char_end] == doc.chunks[0].text
    assert text[doc.chunks[1].char_start:doc.chunks[1].char_end] == doc.chunks[1].text


def test_chunk_oversized_paragraph(processor: DocumentProcessor):
    """Test that a paragraph longer than max_chunk_chars splits on sentences."""
    # Create processor with tiny max_chunk_chars to force splitting
    tiny_processor = DocumentProcessor(min_chunk_chars=10, max_chunk_chars=60)
    
    long_para = (
        "Sentence one is concise. "
        "Sentence two provides additional background. "
        "Sentence three concludes the thought."
    )
    chunks = tiny_processor.chunk_text(long_para)
    
    assert len(chunks) > 1
    # Check that each sub-chunk still points to the exact slice in long_para
    for c in chunks:
        assert long_para[c.char_start:c.char_end] == c.text


def test_empty_raw_text_raises_error(processor: DocumentProcessor):
    """Verifies that empty string passed to chunk_text raises DocumentEmptyError."""
    with pytest.raises(DocumentEmptyError):
        processor.chunk_text("   \n   ")

