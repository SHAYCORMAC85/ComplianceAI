"""
Unit Tests for Expanded Document Processor (PDF & DOCX Support)
--------------------------------------------------------------
Tests multi-format extraction for PDF (PyMuPDF) and DOCX (python-docx),
verifying that the character offset preservation invariant holds across all formats:
    raw_text[chunk.char_start:chunk.char_end] == chunk.text
Also tests corrupt files, empty documents, and unsupported format detection.
"""

import io
from pathlib import Path
import docx
import pymupdf
import pytest
from backend.services.document_processor import (
    DocumentProcessor,
    DocumentEmptyError,
    UnsupportedFileTypeError,
    CorruptFileError,
)


@pytest.fixture
def processor():
    return DocumentProcessor(min_chunk_chars=10, max_chunk_chars=1000)


@pytest.fixture
def sample_pdf_path(tmp_path: Path):
    """Creates a real test PDF document with multiple paragraphs."""
    pdf_doc = pymupdf.open()
    page1 = pdf_doc.new_page()
    page1.insert_text((50, 72), "Article 1: Preliminary Terms.\n\nAll investments carry market risk.")
    
    page2 = pdf_doc.new_page()
    page2.insert_text((50, 72), "Article 2: Marketing Representations.\n\nWe offer guaranteed returns of 20% per year.")
    
    file_path = tmp_path / "test_sample.pdf"
    pdf_doc.save(str(file_path))
    pdf_doc.close()
    return file_path


@pytest.fixture
def sample_docx_path(tmp_path: Path):
    """Creates a real test DOCX document with multiple paragraphs."""
    doc = docx.Document()
    doc.add_paragraph("Article 1: Scope of Engagement.")
    doc.add_paragraph("The advisor must ensure client suitability before executing trades.")
    doc.add_paragraph("Article 2: Fee Structure.")
    doc.add_paragraph("A hidden processing fee of 2.5% will be assessed unilaterally.")
    
    file_path = tmp_path / "test_sample.docx"
    doc.save(str(file_path))
    return file_path


# ==============================================================================
# PDF Extraction & Invariant Tests
# ==============================================================================

def test_process_pdf_file_offsets_invariant(processor: DocumentProcessor, sample_pdf_path: Path):
    """
    CRITICAL INVARIANT TEST FOR PDF:
    Verifies raw_text[chunk.char_start:chunk.char_end] == chunk.text for all chunks.
    """
    doc = processor.process_pdf_file(sample_pdf_path)

    assert doc.file_type == "pdf"
    assert doc.filename == "test_sample.pdf"
    assert len(doc.chunks) >= 2
    assert doc.total_chars == len(doc.raw_text)

    for chunk in doc.chunks:
        actual_slice = doc.raw_text[chunk.char_start:chunk.char_end]
        assert actual_slice == chunk.text, (
            f"PDF chunk offset mismatch on chunk {chunk.index}!\n"
            f"Expected: {chunk.text!r}\n"
            f"Actual slice: {actual_slice!r}"
        )


def test_process_pdf_bytes(processor: DocumentProcessor, sample_pdf_path: Path):
    """Verify processing PDF from in-memory byte stream."""
    pdf_bytes = sample_pdf_path.read_bytes()
    doc = processor.process_bytes(data=pdf_bytes, filename="uploaded.pdf")

    assert doc.file_type == "pdf"
    assert len(doc.chunks) >= 2
    assert "guaranteed returns" in doc.raw_text


def test_empty_pdf_raises_error(processor: DocumentProcessor, tmp_path: Path):
    """Verify DocumentEmptyError when a PDF has pages with zero text."""
    empty_pdf = pymupdf.open()
    empty_pdf.new_page()  # Page without text
    path = tmp_path / "empty.pdf"
    empty_pdf.save(str(path))
    empty_pdf.close()

    with pytest.raises(DocumentEmptyError):
        processor.process_pdf_file(path)


def test_corrupt_pdf_raises_error(processor: DocumentProcessor, tmp_path: Path):
    """Verify CorruptFileError when PDF content is malformed or damaged."""
    corrupt_file = tmp_path / "corrupt.pdf"
    corrupt_file.write_bytes(b"%PDF-1.4\nJUNK_INVALID_CONTENT_NOT_A_REAL_PDF")

    with pytest.raises(CorruptFileError):
        processor.process_pdf_file(corrupt_file)


# ==============================================================================
# DOCX Extraction & Invariant Tests
# ==============================================================================

def test_process_docx_file_offsets_invariant(processor: DocumentProcessor, sample_docx_path: Path):
    """
    CRITICAL INVARIANT TEST FOR DOCX:
    Verifies raw_text[chunk.char_start:chunk.char_end] == chunk.text for all chunks.
    """
    doc = processor.process_docx_file(sample_docx_path)

    assert doc.file_type == "docx"
    assert doc.filename == "test_sample.docx"
    assert len(doc.chunks) >= 2
    assert doc.total_chars == len(doc.raw_text)

    for chunk in doc.chunks:
        actual_slice = doc.raw_text[chunk.char_start:chunk.char_end]
        assert actual_slice == chunk.text, (
            f"DOCX chunk offset mismatch on chunk {chunk.index}!\n"
            f"Expected: {chunk.text!r}\n"
            f"Actual slice: {actual_slice!r}"
        )


def test_process_docx_bytes(processor: DocumentProcessor, sample_docx_path: Path):
    """Verify processing DOCX from in-memory byte stream."""
    docx_bytes = sample_docx_path.read_bytes()
    doc = processor.process_bytes(data=docx_bytes, filename="uploaded.docx")

    assert doc.file_type == "docx"
    assert len(doc.chunks) >= 2
    assert "hidden processing fee" in doc.raw_text


def test_empty_docx_raises_error(processor: DocumentProcessor, tmp_path: Path):
    """Verify DocumentEmptyError when DOCX has no paragraphs."""
    doc = docx.Document()
    path = tmp_path / "empty.docx"
    doc.save(str(path))

    with pytest.raises(DocumentEmptyError):
        processor.process_docx_file(path)


def test_corrupt_docx_raises_error(processor: DocumentProcessor, tmp_path: Path):
    """Verify CorruptFileError when DOCX file is not a valid zip archive."""
    corrupt_file = tmp_path / "corrupt.docx"
    corrupt_file.write_bytes(b"NOT_A_VALID_ZIP_PACKAGE_FILE")

    with pytest.raises(CorruptFileError):
        processor.process_docx_file(corrupt_file)


# ==============================================================================
# Universal Dispatcher Tests
# ==============================================================================

def test_process_file_universal_dispatcher(
    processor: DocumentProcessor,
    tmp_path: Path,
    sample_pdf_path: Path,
    sample_docx_path: Path
):
    """Verify process_file automatically handles .txt, .pdf, and .docx."""
    # TXT
    txt_path = tmp_path / "sample.txt"
    txt_path.write_text("Paragraph one.\n\nParagraph two.")
    txt_doc = processor.process_file(txt_path)
    assert txt_doc.file_type == "txt"

    # PDF
    pdf_doc = processor.process_file(sample_pdf_path)
    assert pdf_doc.file_type == "pdf"

    # DOCX
    docx_doc = processor.process_file(sample_docx_path)
    assert docx_doc.file_type == "docx"


def test_process_file_unsupported_type(processor: DocumentProcessor, tmp_path: Path):
    """Verify UnsupportedFileTypeError on unknown extensions like .csv or .exe."""
    bad_file = tmp_path / "data.csv"
    bad_file.write_text("col1,col2\nval1,val2")

    with pytest.raises(UnsupportedFileTypeError):
        processor.process_file(bad_file)


def test_docx_table_evidence_and_bounded_offsets():
    source = docx.Document()
    source.add_paragraph("Introduction")
    source.add_table(rows=1, cols=1).cell(0, 0).text = "Guaranteed returns"
    source.add_paragraph("X" * 100)
    buf = io.BytesIO()
    source.save(buf)
    doc = DocumentProcessor(max_chunk_chars=20).process_bytes(buf.getvalue(), "table.docx")
    assert doc.raw_text == "Introduction\n\nGuaranteed returns\n\n" + "X" * 100
    assert all(len(c.text) <= 20 and doc.raw_text[c.char_start:c.char_end] == c.text for c in doc.chunks)
