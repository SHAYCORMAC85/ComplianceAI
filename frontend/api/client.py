"""
FastAPI Backend API Client
--------------------------
Central HTTP client providing communication between Streamlit frontend and FastAPI backend.
Handles request execution, timeouts, connection errors, and safe JSON parsing.
Never leaks internal stack traces to the user.
"""

import logging
from typing import Any, Dict, List, Optional
import requests
from frontend.config import BACKEND_BASE_URL, API_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class APIClientError(Exception):
    """Clean user-facing API exception with HTTP status code."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class APIClient:
    """Centralized HTTP client for the ComplianceAI backend."""

    def __init__(self, base_url: str = BACKEND_BASE_URL, timeout: int = API_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self, provider=None):
        # This client is shared by Streamlit. Resolve credentials per session and request.
        import streamlit as st
        session = st.session_state.get("officer_session") or {}
        headers = {"Authorization": "Bearer " + session["token"]} if session.get("token") else {}
        if provider and provider != "mock":
            headers["X-Authorized-Provider"] = provider
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _handle_response(self, response: requests.Response) -> Any:
        """Safely parses JSON responses and formats clean error messages."""
        try:
            data = response.json()
        except Exception:
            data = None

        if response.status_code >= 400:
            if response.status_code == 401:
                import streamlit as st
                if st.session_state.get("officer_session"):
                    st.session_state.clear()
            error_detail = None
            if isinstance(data, dict):
                error_detail = data.get("detail") or data.get("message")
            
            clean_message = (
                error_detail
                if error_detail
                else f"Backend request failed with status code {response.status_code}."
            )
            logger.warning("API request rejected (HTTP %d)", response.status_code)
            raise APIClientError(clean_message, status_code=response.status_code)

        return data

    def check_health(self) -> Dict[str, Any]:
        """Checks if the FastAPI backend server is reachable and online."""
        try:
            resp = requests.get(self._url("/health"), timeout=self.timeout)
            return self._handle_response(resp)
        except requests.exceptions.ConnectionError:
            raise APIClientError(
                f"Cannot connect to backend server at '{self.base_url}'. "
                "Ensure FastAPI is running on port 8000."
            )
        except requests.exceptions.Timeout:
            raise APIClientError("Health check request timed out.")
        except Exception as e:
            raise APIClientError(f"Health check failed: {e}")

    def upload_document(
        self,
        filename: str,
        file_bytes: bytes,
        mime_type: Optional[str] = None,
        submission_key: Optional[str] = None,
        provider: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Uploads a document file to POST /api/documents/upload.
        """
        files = {
            "file": (filename, file_bytes, mime_type or "application/octet-stream")
        }
        try:
            resp = requests.post(
                self._url("/api/documents/upload"),
                files=files,
                headers=self._headers(provider) | ({"Idempotency-Key": submission_key} if submission_key else {}),
                timeout=self.timeout
            )
            return self._handle_response(resp)
        except requests.exceptions.ConnectionError:
            raise APIClientError("Could not reach backend server to upload document.")
        except requests.exceptions.Timeout:
            raise APIClientError(
                f"Upload acknowledgment timed out after {self.timeout}s. Resubmit with the same submission key."
            )
        except APIClientError:
            raise
        except Exception as e:
            raise APIClientError(f"Upload failed: {e}")

    def retry_document(self, document_id: str, provider=None) -> Dict[str, Any]:
        """
        Retries analysis of an existing document via POST /api/documents/{doc_id}/retry.
        Reuses cached chunks and respects rate limits.
        """
        try:
            resp = requests.post(
                self._url(f"/api/documents/{document_id}/retry"),
                headers=self._headers(provider),
                timeout=self.timeout
            )
            return self._handle_response(resp)
        except requests.exceptions.ConnectionError:
            raise APIClientError("Could not reach backend server to retry document analysis.")
        except requests.exceptions.Timeout:
            raise APIClientError(
                f"Document retry request timed out after {self.timeout}s."
            )
        except APIClientError:
            raise
        except Exception as e:
            raise APIClientError(f"Retry failed: {e}")

    def get_document_status(self, document_id: str) -> Dict[str, Any]:
        """Retrieves processing status from GET /api/documents/{doc_id}/status."""
        try:
            resp = requests.get(
                self._url(f"/api/documents/{document_id}/status"),
                headers=self._headers(),
                timeout=self.timeout
            )
            return self._handle_response(resp)
        except requests.exceptions.ConnectionError:
            raise APIClientError("Could not reach backend server.")
        except requests.exceptions.Timeout:
            raise APIClientError("Status request timed out.")
        except APIClientError:
            raise
        except Exception as e:
            raise APIClientError(f"Failed to fetch status: {e}")

    def get_document_findings(self, document_id: str) -> Dict[str, Any]:
        """Retrieves verified findings from GET /api/documents/{doc_id}/findings."""
        try:
            resp = requests.get(
                self._url(f"/api/documents/{document_id}/findings"),
                headers=self._headers(),
                timeout=self.timeout
            )
            return self._handle_response(resp)
        except requests.exceptions.ConnectionError:
            raise APIClientError("Could not reach backend server.")
        except requests.exceptions.Timeout:
            raise APIClientError("Findings request timed out.")
        except APIClientError:
            raise
        except Exception as e:
            raise APIClientError(f"Failed to fetch findings: {e}")

    def get_document_text(self, document_id: str) -> Dict[str, Any]:
        """Retrieves original extracted document text from GET /api/documents/{doc_id}/text."""
        try:
            resp = requests.get(
                self._url(f"/api/documents/{document_id}/text"),
                headers=self._headers(),
                timeout=self.timeout
            )
            return self._handle_response(resp)
        except requests.exceptions.ConnectionError:
            raise APIClientError("Could not reach backend server.")
        except requests.exceptions.Timeout:
            raise APIClientError("Document text request timed out.")
        except APIClientError:
            raise
        except Exception as e:
            raise APIClientError(f"Failed to fetch document text: {e}")

    def list_documents(self) -> List[Dict[str, Any]]:
        """Retrieves all tracked documents from GET /api/documents."""
        try:
            resp = requests.get(
                self._url("/api/documents"),
                headers=self._headers(),
                timeout=self.timeout
            )
            data = self._handle_response(resp)
            return data if isinstance(data, list) else []
        except requests.exceptions.ConnectionError:
            raise APIClientError("Could not reach backend server to list documents.")
        except requests.exceptions.Timeout:
            raise APIClientError("List documents request timed out.")
        except APIClientError:
            raise
        except Exception as e:
            raise APIClientError(f"Failed to list documents: {e}")

    def sign_in(self, name, password):
        try:
            response = requests.post(self._url("/api/review/session"), auth=(name, password), timeout=self.timeout)
            return self._handle_response(response)
        except requests.RequestException as exc:
            raise APIClientError("Could not reach the sign-in service.") from exc

    def sign_out(self, token):
        try:
            response = requests.delete(self._url("/api/review/session"), headers={"Authorization": f"Bearer {token}"}, timeout=self.timeout)
            return self._handle_response(response)
        except requests.RequestException as exc:
            raise APIClientError("Could not reach the sign-out service.") from exc

    def submit_review_decision(
        self,
        document_id: str,
        officer_id: Optional[str] = None,
        decision: str = "",
        notes: str = "",
        token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submits human officer decision to POST /api/review/{doc_id}/decision.
        """
        payload = {
            "decision": decision,
            "notes": notes
        }
        if officer_id is not None:
            payload["officer_id"] = officer_id
        try:
            resp = requests.post(
                self._url(f"/api/review/{document_id}/decision"),
                json=payload,
                **({"headers": {"Authorization": f"Bearer {token}"}} if token else {}),
                timeout=self.timeout
            )
            return self._handle_response(resp)
        except requests.exceptions.ConnectionError:
            raise APIClientError("Could not reach backend server to submit decision.")
        except requests.exceptions.Timeout:
            raise APIClientError("Review submission timed out.")
        except APIClientError:
            raise
        except Exception as e:
            raise APIClientError(f"Failed to submit decision: {e}")

    def get_review_history(self, document_id: str) -> List[Dict[str, Any]]:
        try:
            response = requests.get(self._url(f"/api/review/{document_id}/history"), headers=self._headers(), timeout=self.timeout)
            return self._handle_response(response)
        except requests.RequestException as exc:
            raise APIClientError("Could not retrieve review history.") from exc

    def get_review_decision(self, document_id: str) -> Dict[str, Any]:
        """Retrieves recorded decision from GET /api/review/{doc_id}/decision."""
        try:
            resp = requests.get(
                self._url(f"/api/review/{document_id}/decision"),
                headers=self._headers(),
                timeout=self.timeout
            )
            return self._handle_response(resp)
        except requests.exceptions.ConnectionError:
            raise APIClientError("Could not reach backend server.")
        except requests.exceptions.Timeout:
            raise APIClientError("Decision retrieval timed out.")
        except APIClientError:
            raise
        except Exception as e:
            raise APIClientError(f"Failed to fetch review decision: {e}")


# Singleton API client instance
api_client = APIClient()

