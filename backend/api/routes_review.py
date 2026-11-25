"""
Human Review API Routes
-----------------------
Enforces human governance in compliance workflows:
Only authorized human compliance officers can approve or reject inspected documents.
AI models never make, submit, or override review decisions.
"""

from datetime import datetime, timezone
import logging
from fastapi import Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from backend.officers import current_officer, sign_in, bearer, revoke
from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError
from backend.db.store import document_store
from backend.models.api_schemas import (
    ReviewDecisionRequest,
    ReviewDecisionResponse,
)
from backend.models.review import ReviewDecision, ReviewStatusEnum

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/review", tags=["Review"])


@router.post("/session")
def login(credentials: HTTPBasicCredentials = Depends(HTTPBasic())):
    return sign_in(credentials.username, credentials.password)


@router.delete("/session")
def logout(credentials=Depends(bearer)):
    if credentials:
        revoke(credentials.credentials)
    return {"signed_out": True}


@router.post(
    "/{doc_id}/decision",
    response_model=ReviewDecisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit human review decision",
    description="Records formal human officer approval or rejection of an inspected document."
)
async def submit_review_decision(
    doc_id: str,
    payload: ReviewDecisionRequest,
    authenticated_id: str = Depends(current_officer)
):
    """
    Submits an APPROVED or REJECTED decision signed by a human compliance officer.
    """
    # 1. Verify document exists
    doc = document_store.get_document(doc_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found."
        )

    # 2. Strict validation of decision value
    if payload.decision == ReviewStatusEnum.PENDING:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A submitted review decision must be APPROVED or REJECTED, not PENDING."
        )

    if payload.officer_id is not None:
        claimed = payload.officer_id.strip()
        if not claimed:
            raise HTTPException(422, "Officer ID cannot be blank.")
        if claimed != authenticated_id:
            raise HTTPException(403, "Decision identity must match the signed-in officer.")

    # 4. Construct and record ReviewDecision model
    try:
        decision = ReviewDecision(
            document_id=doc_id,
            officer_id=authenticated_id,
            decision=payload.decision,
            notes=payload.notes or "",
            decided_at=datetime.now(timezone.utc)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid review submission."
        )

    try:
        recorded = document_store.record_decision(decision)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found in records."
        )
    except Exception as e:
        logger.error("Decision write failed (%s)", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while saving the review decision."
        )

    return ReviewDecisionResponse(
        document_id=recorded.document_id,
        officer_id=recorded.officer_id,
        decision=recorded.decision,
        notes=recorded.notes or "",
        decided_at=recorded.decided_at
    )


@router.get(
    "/{doc_id}/decision",
    dependencies=[Depends(current_officer)],
    response_model=ReviewDecisionResponse,
    summary="Retrieve recorded review decision",
    description="Returns the human review decision recorded for a document."
)
async def get_review_decision(doc_id: str):
    """
    Retrieves the review decision for a document.
    """
    decision = document_store.get_decision(doc_id)
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No review decision has been recorded yet for document '{doc_id}'."
        )

    return ReviewDecisionResponse(
        document_id=decision.document_id,
        officer_id=decision.officer_id,
        decision=decision.decision,
        notes=decision.notes or "",
        decided_at=decision.decided_at
    )


@router.get("/{doc_id}/history", dependencies=[Depends(current_officer)], response_model=list[ReviewDecisionResponse])
async def get_review_history(doc_id: str):
    history = document_store.review_history(doc_id)
    if not history and document_store.get_document(doc_id) is None:
        raise HTTPException(404, "Document not found.")
    return [decision.model_dump() for decision in history]
