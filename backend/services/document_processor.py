"""
Document Processor Service
--------------------------
Extracts text from documents and splits text into logical sections/paragraphs
while preserving exact character start and end offsets relative to the original text.

Supported formats:
- TXT: Plaintext with UTF-8 and fallback encodings.
- PDF: Extracted via PyMuPDF (fitz) page-by-page.
- DOCX: Extracted via python-docx paragraph-by-paragraph.

Guarantees:
- Every chunk preserves its exact (char_start, char_end) offsets in the original raw text.
- raw_text[chunk.char_start:chunk.char_end] == chunk.text for all chunks.
"""

import io
from pathlib import Path
import zipfile
import re
from typing import List, Union
import docx
import pymupdf
from backend.models.document import Document, DocumentChunk


class DocumentProcessorError(Exception):
    """Base exception for document processing errors."""
    pass


class DocumentEmptyError(DocumentProcessorError):
    """Raised when an uploaded document contains no readable text."""
    pass


class UnsupportedFileTypeError(DocumentProcessorError):
    """Raised when a file extension is not supported."""
    pass


class CorruptFileError(DocumentProcessorError):
    """Raised when a document file is corrupted or cannot be parsed."""
    pass


class DocumentProcessor:
    """
    Handles multi-format document text extraction and semantic chunking.
    """

    MAX_TEXT = 1_000_000
    MAX_PAGES = 300
    MAX_PARTS = 1024
    MAX_EXPANDED = 64 * 1024 * 1024
    MAX_CHUNKS = 4096
    SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}

    def __init__(self, min_chunk_chars: int = 40, max_chunk_chars: int = 2500):
        """
        Args:
            min_chunk_chars: Minimum character length for a standalone chunk.
            max_chunk_chars: Maximum character length before a paragraph is split at sentences.
        """
        self.min_chunk_chars = min_chunk_chars
        self.max_chunk_chars = max_chunk_chars

    # ==========================================================================
    # TXT Extraction
    # ==========================================================================

    def read_text_file(self, file_path: Union[str, Path]) -> str:
        """
        Reads a text file from disk supporting multiple encodings.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document file not found at: {file_path}")

        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                text = path.read_text(encoding=encoding)
                if not text.strip():
                    raise DocumentEmptyError(f"File '{path.name}' is empty or contains only whitespace.")
                return text
            except UnicodeDecodeError:
                continue

        raise DocumentProcessorError(f"Could not decode text file '{path.name}' with supported encodings.")

    def read_text_bytes(self, data: bytes, filename: str = "document.txt") -> str:
        """
        Reads in-memory text bytes supporting multiple encodings.
        """
        if not data or not data.strip():
            raise DocumentEmptyError(f"File '{filename}' contains no data.")

        if b"\x00" in data or data.startswith((b"PK\x03\x04", b"%PDF-", b"\x7fELF")):
            raise CorruptFileError("Expected a plain-text document.")
        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                text = data.decode(encoding)
                if not text.strip():
                    raise DocumentEmptyError(f"File '{filename}' contains only whitespace.")
                return text
            except UnicodeDecodeError:
                continue

        raise DocumentProcessorError(f"Could not decode bytes for '{filename}'.")

    # ==========================================================================
    # PDF Extraction (PyMuPDF)
    # ==========================================================================

    def read_pdf_file(self, file_path: Union[str, Path]) -> str:
        """
        Extracts textual content from a PDF document page-by-page.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found at: {file_path}")

        return self.read_pdf_bytes(path.read_bytes(), path.name)

    def read_pdf_bytes(self, data: bytes, filename: str = "document.pdf") -> str:
        """
        Extracts text from in-memory PDF bytes.
        """
        if not data or len(data) == 0:
            raise DocumentEmptyError(f"PDF '{filename}' is empty (0 bytes).")

        if b"%PDF-" not in data[:1024]:
            raise CorruptFileError("Expected PDF content.")
        pages_text = []
        size = 0
        try:
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                if doc.needs_pass or len(doc) > self.MAX_PAGES:
                    raise CorruptFileError("Unsupported encrypted or oversized PDF.")
                for page in doc:
                    text = page.get_text("text").strip()
                    if text:
                        size += len(text) + 2
                        if size > self.MAX_TEXT:
                            raise CorruptFileError("Extracted text limit exceeded.")
                        pages_text.append(text)
        except Exception:
            raise CorruptFileError("Invalid PDF or extraction limit exceeded.") from None
        if not pages_text:
            raise DocumentEmptyError(f"PDF '{filename}' contains no readable text.")

        return "\n\n".join(pages_text)

    # ==========================================================================
    # DOCX Extraction (python-docx)
    # ==========================================================================

    def _docx_blocks(self, container):
        """Yield body and table text in document order, including nested tables."""
        for block in container.iter_inner_content():
            if isinstance(block, docx.text.paragraph.Paragraph):
                if block.text.strip():
                    yield block.text.strip()
            else:
                visited = set()
                for row in block.rows:
                    for cell in row.cells:
                        if cell._tc not in visited:
                            visited.add(cell._tc)
                            yield from self._docx_blocks(cell)

    def read_docx_file(self, file_path: Union[str, Path]) -> str:
        """
        Extracts paragraphs in their original sequential order from a DOCX file.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"DOCX file not found at: {file_path}")

        return self.read_docx_bytes(path.read_bytes(), path.name)

    def read_docx_bytes(self, data: bytes, filename: str = "document.docx") -> str:
        """
        Extracts paragraphs from in-memory DOCX bytes.
        """
        if not data or len(data) == 0:
            raise DocumentEmptyError(f"DOCX '{filename}' is empty (0 bytes).")

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                parts = archive.infolist()
                names = set(archive.namelist())
                if (len(parts) > self.MAX_PARTS or len(names) != len(parts)
                        or sum(p.file_size for p in parts) > self.MAX_EXPANDED
                        or not {"[Content_Types].xml","word/document.xml"}.issubset(names)
                        or any(p.flag_bits & 1 for p in parts)):
                    raise CorruptFileError("Invalid or oversized DOCX package.")
            doc = docx.Document(io.BytesIO(data))
            paragraphs = []
            size = 0
            for text in self._docx_blocks(doc):
                size += len(text) + 2
                if size > self.MAX_TEXT or len(paragraphs) >= self.MAX_CHUNKS:
                    raise CorruptFileError("DOCX extraction limit exceeded.")
                paragraphs.append(text)
        except Exception:
            raise CorruptFileError("Invalid DOCX or extraction limit exceeded.") from None

        if not paragraphs:
            raise DocumentEmptyError(f"DOCX '{filename}' contains no readable text.")

        return "\n\n".join(paragraphs)

    # ==========================================================================
    # Chunking & Offset Tracking
    # ==========================================================================

    def chunk_text(self, raw_text: str) -> List[DocumentChunk]:
        """
        Split raw text into logical paragraph sections and record exact character offsets.
        
        Crucial requirement:
            raw_text[chunk.char_start:chunk.char_end] MUST equal chunk.text.
        """
        if not raw_text or not raw_text.strip():
            raise DocumentEmptyError("Cannot chunk empty or whitespace-only text.")

        chunks: List[DocumentChunk] = []
        pattern = re.compile(r"\S.*?(?=(?:\r?\n\s*\r?\n)|\Z)", re.DOTALL)
        if len(raw_text) > self.MAX_TEXT:
            raise CorruptFileError("Extracted text limit exceeded.")
        raw_matches = pattern.finditer(raw_text)

        chunk_index = 0
        for match in raw_matches:
            if len(chunks) >= self.MAX_CHUNKS:
                raise CorruptFileError("Section limit exceeded.")
            block_start = match.start()
            block_end = match.end()
            block_text = match.group(0)

            leading_whitespace = len(block_text) - len(block_text.lstrip())
            trailing_whitespace = len(block_text) - len(block_text.rstrip())

            clean_start = block_start + leading_whitespace
            clean_end = block_end - trailing_whitespace
            clean_text = raw_text[clean_start:clean_end]

            if not clean_text:
                continue

            if len(clean_text) > self.max_chunk_chars:
                sub_chunks = self._split_long_paragraph(raw_text, clean_start, clean_end, chunk_index)
                chunks.extend(sub_chunks)
                chunk_index += len(sub_chunks)
            else:
                chunk = DocumentChunk(
                    index=chunk_index,
                    text=clean_text,
                    char_start=clean_start,
                    char_end=clean_end
                )
                chunks.append(chunk)
                chunk_index += 1

        if not chunks:
            leading = len(raw_text) - len(raw_text.lstrip())
            trailing = len(raw_text) - len(raw_text.rstrip())
            start = leading
            end = len(raw_text) - trailing
            chunks.append(
                DocumentChunk(
                    index=0,
                    text=raw_text[start:end],
                    char_start=start,
                    char_end=end
                )
            )

        if len(chunks) > self.MAX_CHUNKS:
            raise CorruptFileError("Section limit exceeded.")
        # Integrity invariant check
        for c in chunks:
            actual_slice = raw_text[c.char_start:c.char_end]
            assert actual_slice == c.text, (
                f"Chunk offset mismatch at index {c.index}: "
                f"raw_text[{c.char_start}:{c.char_end}] != chunk.text"
            )

        return chunks

    def _split_long_paragraph(
        self,
        raw_text: str,
        start_pos: int,
        end_pos: int,
        start_index: int
    ) -> List[DocumentChunk]:
        """
        Subdivides an oversized paragraph by sentence boundaries while preserving offsets.
        """
        para_text = raw_text[start_pos:end_pos]
        sentence_regex = re.compile(r".+?(?:[.!?](?=\s)|$)", re.DOTALL)
        matches = list(sentence_regex.finditer(para_text))

        sub_chunks: List[DocumentChunk] = []
        current_sentences: List[re.Match] = []
        current_len = 0
        current_index = start_index

        for m in matches:
            sentence_str = m.group(0)
            if not sentence_str.strip():
                continue

            current_sentences.append(m)
            current_len += len(sentence_str)

            if current_len >= self.max_chunk_chars:
                first_match = current_sentences[0]
                last_match = current_sentences[-1]
                sub_start = start_pos + first_match.start()
                sub_end = start_pos + last_match.end()

                leading = len(raw_text[sub_start:sub_end]) - len(raw_text[sub_start:sub_end].lstrip())
                trailing = len(raw_text[sub_start:sub_end]) - len(raw_text[sub_start:sub_end].rstrip())
                final_start = sub_start + leading
                final_end = sub_end - trailing

                sub_chunks.append(
                    DocumentChunk(
                        index=current_index,
                        text=raw_text[final_start:final_end],
                        char_start=final_start,
                        char_end=final_end
                    )
                )
                current_index += 1
                current_sentences = []
                current_len = 0

        if current_sentences:
            first_match = current_sentences[0]
            last_match = current_sentences[-1]
            sub_start = start_pos + first_match.start()
            sub_end = start_pos + last_match.end()

            leading = len(raw_text[sub_start:sub_end]) - len(raw_text[sub_start:sub_end].lstrip())
            trailing = len(raw_text[sub_start:sub_end]) - len(raw_text[sub_start:sub_end].rstrip())
            final_start = sub_start + leading
            final_end = sub_end - trailing

            sub_chunks.append(
                DocumentChunk(
                    index=current_index,
                    text=raw_text[final_start:final_end],
                    char_start=final_start,
                    char_end=final_end
                )
            )

        bounded = []
        for section in sub_chunks:
            for start in range(section.char_start, section.char_end, self.max_chunk_chars):
                end = min(start + self.max_chunk_chars, section.char_end)
                text = raw_text[start:end]
                if text.strip():
                    bounded.append(DocumentChunk(index=start_index + len(bounded), text=text,
                                                 char_start=start, char_end=end))
        return bounded

    # ==========================================================================
    # Unified Processing Entry Points
    # ==========================================================================

    def process_txt_file(self, file_path: Union[str, Path]) -> Document:
        """Full pipeline for a TXT document file."""
        path = Path(file_path)
        if path.suffix.lower() != ".txt":
            raise UnsupportedFileTypeError(
                f"Expected .txt file, received '{path.suffix}'. "
                "Phase 1 only supports TXT files."
            )
        raw_text = self.read_text_file(path)
        chunks = self.chunk_text(raw_text)
        return Document(
            filename=path.name,
            file_type="txt",
            raw_text=raw_text,
            total_chars=len(raw_text),
            chunks=chunks
        )

    def process_pdf_file(self, file_path: Union[str, Path]) -> Document:
        """Full pipeline for a PDF document file."""
        path = Path(file_path)
        if path.suffix.lower() != ".pdf":
            raise UnsupportedFileTypeError(f"Expected .pdf file, received '{path.suffix}'.")
        raw_text = self.read_pdf_file(path)
        chunks = self.chunk_text(raw_text)
        return Document(
            filename=path.name,
            file_type="pdf",
            raw_text=raw_text,
            total_chars=len(raw_text),
            chunks=chunks
        )

    def process_docx_file(self, file_path: Union[str, Path]) -> Document:
        """Full pipeline for a DOCX document file."""
        path = Path(file_path)
        if path.suffix.lower() != ".docx":
            raise UnsupportedFileTypeError(f"Expected .docx file, received '{path.suffix}'.")
        raw_text = self.read_docx_file(path)
        chunks = self.chunk_text(raw_text)
        return Document(
            filename=path.name,
            file_type="docx",
            raw_text=raw_text,
            total_chars=len(raw_text),
            chunks=chunks
        )

    def process_file(self, file_path: Union[str, Path]) -> Document:
        """
        Universal file processor: detects extension and delegates to appropriate handler.
        """
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".txt":
            return self.process_txt_file(path)
        elif suffix == ".pdf":
            return self.process_pdf_file(path)
        elif suffix == ".docx":
            return self.process_docx_file(path)
        else:
            raise UnsupportedFileTypeError(
                f"Unsupported file type '{suffix}'. Allowed formats: .txt, .pdf, .docx"
            )

    def process_bytes(self, data: bytes, filename: str) -> Document:
        """
        Processes in-memory bytes for uploaded files.
        """
        path = Path(filename)
        suffix = path.suffix.lower()

        if suffix == ".txt":
            raw_text = self.read_text_bytes(data, filename)
            file_type = "txt"
        elif suffix == ".pdf":
            raw_text = self.read_pdf_bytes(data, filename)
            file_type = "pdf"
        elif suffix == ".docx":
            raw_text = self.read_docx_bytes(data, filename)
            file_type = "docx"
        else:
            raise UnsupportedFileTypeError(
                f"Unsupported file format '{suffix}'. Allowed formats: .txt, .pdf, .docx"
            )

        chunks = self.chunk_text(raw_text)
        return Document(
            filename=filename,
            file_type=file_type,
            raw_text=raw_text,
            total_chars=len(raw_text),
            chunks=chunks
        )

    def process_raw_text(self, raw_text: str, filename: str = "document.txt") -> Document:
        """Direct in-memory string processor."""
        if not raw_text or not raw_text.strip():
            raise DocumentEmptyError("raw_text cannot be empty.")

        chunks = self.chunk_text(raw_text)
        return Document(
            filename=filename,
            file_type="txt",
            raw_text=raw_text,
            total_chars=len(raw_text),
            chunks=chunks
        )
