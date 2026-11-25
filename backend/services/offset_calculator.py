"""
Offset Calculator Service
-------------------------
Calculates exact start and end character offsets of a passage within the original
document text.

Supports:
- Chunk-context disambiguation for repeated passages across different sections.
- Multiple occurrence discovery.
- Strict offset verification ensuring document_text[start:end] == passage.
"""

from typing import List, Optional, Tuple
from backend.models.document import DocumentChunk


class OffsetCalculatorError(Exception):
    """Base exception for offset calculation errors."""
    pass


class EmptyPassageError(OffsetCalculatorError):
    """Raised when an empty or whitespace-only passage is provided."""
    pass


class PassageNotFoundError(OffsetCalculatorError):
    """Raised when the passage cannot be located within the document text."""
    pass


class OffsetMismatchError(OffsetCalculatorError):
    """Raised when the calculated slice does not exactly equal the target passage."""
    pass


class OffsetCalculator:
    """
    Computes and verifies character positions of text excerpts within documents.
    """

    @staticmethod
    def find_all_occurrences(document_text: str, passage: str) -> List[Tuple[int, int]]:
        """
        Finds all (start, end) character offset tuples for a passage in document_text.
        
        Args:
            document_text: Full document string.
            passage: Target substring.
            
        Returns:
            List of (start, end) integer tuples. Empty list if not found.
        """
        if not passage or not passage.strip():
            raise EmptyPassageError("Passage cannot be empty or whitespace-only.")

        occurrences: List[Tuple[int, int]] = []
        passage_len = len(passage)
        start_pos = 0

        while True:
            idx = document_text.find(passage, start_pos)
            if idx == -1:
                break
            end_pos = idx + passage_len
            occurrences.append((idx, end_pos))
            start_pos = idx + 1  # Advance by 1 to detect overlapping or adjacent matches

        return occurrences

    def calculate_offsets(
        self,
        document_text: str,
        passage: str,
        chunk: Optional[DocumentChunk] = None,
        occurrence_index: int = 0
    ) -> Tuple[int, int]:
        """
        Locates the exact (start, end) character positions for a passage in document_text.
        
        Algorithm:
        1. Validates that passage is non-empty.
        2. If a DocumentChunk is provided, searches inside the chunk's offset window first:
           [chunk.char_start, chunk.char_end]. This disambiguates repeated passages
           occurring in different sections of a document.
        3. When no chunk is provided, searches across document_text
           using occurrence_index.
        4. Verifies the invariant: document_text[start:end] == passage.
        
        Args:
            document_text: Full un-modified document text.
            passage: Verbatim text excerpt.
            chunk: Optional DocumentChunk providing section context.
            occurrence_index: Which match to select (0-based) when multiple exist.
            
        Returns:
            Tuple of (start, end) integer offsets.
            
        Raises:
            EmptyPassageError: If passage is empty.
            PassageNotFoundError: If passage is not in the document.
            OffsetMismatchError: If the slice does not match the passage verbatim.
        """
        if not passage or not passage.strip():
            raise EmptyPassageError("Cannot calculate offsets for an empty or whitespace passage.")

        if not document_text:
            raise PassageNotFoundError("Cannot find passage in empty document text.")

        target_start = -1
        target_end = -1

        # 1. Attempt chunk-context local search first
        if chunk is not None:
            c_start = max(0, chunk.char_start)
            c_end = min(len(document_text), chunk.char_end)
            chunk_slice = document_text[c_start:c_end]

            rel_idx = chunk_slice.find(passage)
            if rel_idx == -1:
                raise PassageNotFoundError("Passage does not occur in the source chunk.")
            target_start = c_start + rel_idx
            target_end = target_start + len(passage)

        # 2. Fallback to global search across document_text
        if target_start == -1:
            all_matches = self.find_all_occurrences(document_text, passage)
            if not all_matches:
                raise PassageNotFoundError(
                    f"Passage not found in document text: '{passage[:60]}...'"
                )
            if occurrence_index < len(all_matches):
                target_start, target_end = all_matches[occurrence_index]
            else:
                # If occurrence_index is out of range, default to last available
                target_start, target_end = all_matches[-1]

        # 3. Invariant check: verify slice equals passage exactly
        actual_slice = document_text[target_start:target_end]
        if actual_slice != passage:
            raise OffsetMismatchError(
                f"Offset verification failed! Expected slice {target_start}:{target_end} "
                f"to equal '{passage}', but got '{actual_slice}'."
            )

        return target_start, target_end

