"""
Unit Tests for Offset Calculator Service
----------------------------------------
Tests exact character offset calculation, document boundary conditions,
repeated passages across chunks, occurrence disambiguation, and edge cases
(empty passages, missing passages, empty documents).
"""

import pytest
from backend.models.document import DocumentChunk
from backend.services.offset_calculator import (
    OffsetCalculator,
    EmptyPassageError,
    PassageNotFoundError,
    OffsetMismatchError,
)


@pytest.fixture
def calculator():
    return OffsetCalculator()


@pytest.fixture
def sample_text():
    return (
        "START_HEADER: Compliance Guidelines.\n"
        "Section 1: The broker offers guaranteed returns with zero risk.\n"
        "Section 2: Another department also claims guaranteed returns with zero risk.\n"
        "END_FOOTER"
    )


# ==============================================================================
# Exact Match & Boundary Tests
# ==============================================================================

def test_exact_single_match(calculator: OffsetCalculator, sample_text: str):
    """Verify calculating start and end offsets for a unique passage."""
    passage = "Section 1: The broker offers"
    start, end = calculator.calculate_offsets(sample_text, passage)

    assert sample_text[start:end] == passage
    assert start > 0
    assert end == start + len(passage)


def test_boundary_start_of_document(calculator: OffsetCalculator, sample_text: str):
    """Verify offset calculation for a passage at index 0."""
    passage = "START_HEADER:"
    start, end = calculator.calculate_offsets(sample_text, passage)

    assert start == 0
    assert end == len(passage)
    assert sample_text[start:end] == passage


def test_boundary_end_of_document(calculator: OffsetCalculator, sample_text: str):
    """Verify offset calculation for a passage at the very end of the document."""
    passage = "END_FOOTER"
    start, end = calculator.calculate_offsets(sample_text, passage)

    assert end == len(sample_text)
    assert start == len(sample_text) - len(passage)
    assert sample_text[start:end] == passage


# ==============================================================================
# Repeated Passages & Chunk Context Disambiguation
# ==============================================================================

def test_repeated_passages_disambiguated_by_chunk(calculator: OffsetCalculator, sample_text: str):
    """
    Ensure identical passages in different sections resolve to their
    respective chunk offsets when chunk context is provided.
    """
    repeated_passage = "guaranteed returns with zero risk"

    # Define chunk 1 boundaries (enclosing the first occurrence)
    chunk1_text = "Section 1: The broker offers guaranteed returns with zero risk."
    c1_start = sample_text.find(chunk1_text)
    c1_end = c1_start + len(chunk1_text)
    chunk1 = DocumentChunk(index=0, text=chunk1_text, char_start=c1_start, char_end=c1_end)

    # Define chunk 2 boundaries (enclosing the second occurrence)
    chunk2_text = "Section 2: Another department also claims guaranteed returns with zero risk."
    c2_start = sample_text.find(chunk2_text)
    c2_end = c2_start + len(chunk2_text)
    chunk2 = DocumentChunk(index=1, text=chunk2_text, char_start=c2_start, char_end=c2_end)

    # When querying with chunk1 context:
    start1, end1 = calculator.calculate_offsets(sample_text, repeated_passage, chunk=chunk1)
    assert sample_text[start1:end1] == repeated_passage
    assert c1_start <= start1 < c1_end

    # When querying with chunk2 context:
    start2, end2 = calculator.calculate_offsets(sample_text, repeated_passage, chunk=chunk2)
    assert sample_text[start2:end2] == repeated_passage
    assert c2_start <= start2 < c2_end

    # Crucially, the offsets for chunk 1 and chunk 2 must differ
    assert start1 != start2
    assert start2 > start1


def test_repeated_passages_by_occurrence_index(calculator: OffsetCalculator, sample_text: str):
    """Verify selecting specific occurrences using occurrence_index."""
    repeated_passage = "guaranteed returns with zero risk"

    all_matches = calculator.find_all_occurrences(sample_text, repeated_passage)
    assert len(all_matches) == 2

    # First occurrence
    s0, e0 = calculator.calculate_offsets(sample_text, repeated_passage, occurrence_index=0)
    assert (s0, e0) == all_matches[0]

    # Second occurrence
    s1, e1 = calculator.calculate_offsets(sample_text, repeated_passage, occurrence_index=1)
    assert (s1, e1) == all_matches[1]


# ==============================================================================
# Edge Cases & Error Handling Tests
# ==============================================================================

def test_empty_passage_raises_error(calculator: OffsetCalculator, sample_text: str):
    """Verify EmptyPassageError for empty or whitespace strings."""
    with pytest.raises(EmptyPassageError):
        calculator.calculate_offsets(sample_text, "")

    with pytest.raises(EmptyPassageError):
        calculator.calculate_offsets(sample_text, "   \n\t  ")


def test_passage_not_found_raises_error(calculator: OffsetCalculator, sample_text: str):
    """Verify PassageNotFoundError when text does not exist in document."""
    with pytest.raises(PassageNotFoundError):
        calculator.calculate_offsets(sample_text, "This text does not exist at all.")


def test_empty_document_raises_error(calculator: OffsetCalculator):
    """Verify PassageNotFoundError when document text is empty."""
    with pytest.raises(PassageNotFoundError):
        calculator.calculate_offsets("", "Some passage")

