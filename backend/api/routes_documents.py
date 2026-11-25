"""
Document API Routes
-------------------
REST endpoints for uploading documents, polling processing status,
and retrieving strictly verified compliance findings.
"""

import asyncio
import hashlib
import logging
from pathlib import Path, PureWindowsPath
import uuid
from fastapi import APIRouter, Header, Request, File, HTTPException, UploadFile, status
from backend.config import UPLOADS_DIR, settings
from backend.db.store import document_store, RecoveryError, RetryConflict
from backend.models.api_schemas import (
    DocumentUploadResponse,
    DocumentStatusResponse,
    DocumentFindingsResponse,
    DocumentTextResponse,
    ProcessingStatusEnum,
)
from backend.services.document_processor import (
    DocumentProcessorError,
    DocumentProcessor,
    DocumentEmptyError,
    UnsupportedFileTypeError,
    CorruptFileError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["Documents"])

processor = DocumentProcessor(settings.CHUNK_MIN_CHARS, settings.CHUNK_MAX_CHARS)

# Maximum allowed file upload size: 15 MB
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def authorized_provider(request):
    provider = settings.LLM_PROVIDER.lower()
    if provider != "mock" and request.headers.get("X-Authorized-Provider") != provider:
        raise HTTPException(403, "Confirm authorization to send this document to the configured external provider.")
    return provider


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload and inspect a document",
    description="Uploads a TXT, PDF, or DOCX document and executes the compliance inspection pipeline."
)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, min_length=1, max_length=200)
):
    """
    Receives document file, performs size & extension validation, extracts text,
    and runs the full rules & LLM inspection pipeline.
    """
    provider = authorized_provider(request)
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename cannot be empty."
        )

    name = file.filename
    if (name != PureWindowsPath(name).name or PureWindowsPath(name).is_reserved()
            or len(name.encode("utf-8")) > 190 or name.rstrip(" .") != name
            or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)):
        raise HTTPException(400, "Invalid document filename.")
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in processor.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{file_ext}'. Allowed formats: .txt, .pdf, .docx"
        )

    # Read uploaded bytes with size validation
    try:
        content_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read uploaded file stream."
        )

    if len(content_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes)."
        )

    if len(content_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded file exceeds the maximum allowed size of {MAX_UPLOAD_BYTES // (1024 * 1024)}MB."
        )

    digest = hashlib.sha256(file_ext.encode() + b"\0" + content_bytes).hexdigest()
    try:
        previous = document_store.submission(idempotency_key, digest)
    except RetryConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if previous:
        return accepted(previous)
    doc_id = str(uuid.uuid4())
    saved_file_path = UPLOADS_DIR / f"{doc_id}_{Path(file.filename).name}"

    # Process and chunk document
    try:
        document = await asyncio.to_thread(processor.process_bytes, data=content_bytes, filename=file.filename)
        # Assign generated UUID
        document.id = doc_id
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document format.")
    except DocumentEmptyError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document contains no readable text.")
    except CorruptFileError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid document or extraction safety limit exceeded."
        )
    except Exception as e:
        logger.error("Document extraction failed (%s)", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while parsing the document."
        )

    try:
        saved_file_path.write_bytes(content_bytes)
        info = document_store.enqueue(document, idempotency_key, digest, provider)
    except RetryConflict as exc:
        saved_file_path.unlink(missing_ok=True)
        raise HTTPException(409, str(exc)) from exc
    except Exception:
        saved_file_path.unlink(missing_ok=True)
        raise HTTPException(500, "Could not persist inspection submission.") from None
    if info["document_id"] != doc_id:
        saved_file_path.unlink(missing_ok=True)
    request.app.state.workers.wake.set()
    return accepted(info)


def accepted(info):
    doc_id = info["document_id"]
    return DocumentUploadResponse(document_id=doc_id, filename=info["filename"], file_type=info["file_type"],
                                  status=info["status"], status_url=f"/api/documents/{doc_id}/status",
                                  message="Inspection registered.")


@router.post(
    "/{doc_id}/retry",
    status_code=202,
    response_model=DocumentUploadResponse,
    summary="Retry compliance inspection for an existing document",
    description="Re-runs inspection on an existing document, reusing cached chunks to avoid redundant API quota consumption."
)
async def retry_document_analysis(doc_id: str, request: Request):
    """
    Retries inspection for a document whose previous analysis failed (e.g. on rate limit).
    Chunks that already passed and were cached will not consume new LLM quota.
    """
    try:
        document_store.claim_retry(doc_id, restore_original, authorized_provider(request))
    except KeyError:
        raise HTTPException(404, "Document not found.")
    except RetryConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except RecoveryError as exc:
        raise HTTPException(422, str(exc)) from exc
    request.app.state.workers.wake.set()
    return accepted(document_store.get_status(doc_id))


def restore_original(doc_id, filename):
    original = UPLOADS_DIR / f"{doc_id}_{Path(filename).name}"
    try:
        with original.open("rb") as stream:
            data = stream.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise RecoveryError("The original exceeds the upload limit. Upload a new inspection.")
        return processor.process_bytes(data, filename)
    except (OSError, DocumentProcessorError) as exc:
        raise RecoveryError("Stored evidence is damaged and the original is missing or unreadable. Upload a new inspection.") from exc


@router.get(
    "/{doc_id}/findings",
    response_model=DocumentFindingsResponse,
    summary="Retrieve verified compliance findings",
    description="Returns strictly validated compliance findings. Evidence must match the source. Officers assess the significance of each finding."
)
async def get_document_findings(doc_id: str):
    """
    Retrieves strictly validated findings for a document.
    """
    info = document_store.get_status(doc_id)
    if info and info["status"] != "COMPLETED":
        raise HTTPException(409, "Findings are available after a completed inspection.")
    findings = document_store.get_findings(doc_id)
    if findings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found."
        )

    return DocumentFindingsResponse(
        document_id=doc_id,
        total_findings=len(findings),
        findings=findings
    )


@router.get(
    "/{doc_id}/status",
    response_model=DocumentStatusResponse,
    summary="Retrieve document processing status",
    description="Returns job stage, section counts, quota timing and lifecycle state."
)
async def get_document_status(doc_id: str):
    """
    Returns the processing status of a document.
    """
    status_info = document_store.get_status(doc_id)
    if status_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found."
        )

    return DocumentStatusResponse(**status_info)


@router.get(
    "",
    summary="List all tracked documents",
    description="Returns metadata and status summaries for all tracked documents."
)
async def list_documents():
    """
    Returns summaries of all documents currently tracked in the system.
    """
    return document_store.list_documents()


@router.get(
    "/{doc_id}/text",
    response_model=DocumentTextResponse,
    summary="Retrieve raw extracted document text",
    description="Returns full un-modified extracted text and character metrics for precise frontend highlighting."
)
async def get_document_text(doc_id: str):
    """
    Retrieves original extracted document text for offset verification and highlighting.
    """
    doc_text_info = document_store.get_document_text(doc_id)
    if doc_text_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found."
        )

    return DocumentTextResponse(
        document_id=doc_text_info["document_id"],
        filename=doc_text_info["filename"],
        file_type=doc_text_info["file_type"],
        raw_text=doc_text_info["raw_text"],
        total_chars=doc_text_info["total_chars"]
    )


