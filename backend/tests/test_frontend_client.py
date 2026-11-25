"""
Unit Tests for Frontend API Client
----------------------------------
Tests client request dispatching, response parsing, error translation,
timeout handling, and network failure management using mocked requests.
"""

from unittest.mock import MagicMock, patch
import pytest
import requests
from frontend.api.client import APIClient, APIClientError


@pytest.fixture
def client():
    return APIClient(base_url="http://test-server:8000", timeout=5)


def test_api_client_health_check_success(client: APIClient):
    """Verify health check parses successful JSON."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "healthy", "llm_provider": "mock"}

    with patch("requests.get", return_value=mock_resp) as mock_get:
        data = client.check_health()
        assert data["status"] == "healthy"
        mock_get.assert_called_once_with("http://test-server:8000/health", timeout=5)


def test_api_client_connection_failure(client: APIClient):
    """Verify clean APIClientError when backend server is unreachable."""
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("Connection refused")):
        with pytest.raises(APIClientError) as exc_info:
            client.check_health()
        assert "Cannot connect to backend server" in exc_info.value.message


def test_api_client_timeout_handling(client: APIClient):
    """Verify clean APIClientError on request timeout."""
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Read timed out")):
        with pytest.raises(APIClientError) as exc_info:
            client.check_health()
        assert "timed out" in exc_info.value.message


def test_api_client_upload_success(client: APIClient):
    """Verify document upload response handling."""
    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.json.return_value = {
        "document_id": "doc-12345",
        "filename": "test.pdf",
        "file_type": "pdf",
        "status": "QUEUED",
        "message": "Inspection registered"
    }

    with patch("requests.post", return_value=mock_resp):
        res = client.upload_document(filename="test.pdf", file_bytes=b"dummy content")
        assert res["document_id"] == "doc-12345"
        assert res["status"] == "QUEUED"


def test_api_client_upload_failure_status_code(client: APIClient):
    """Verify APIClientError with status code when backend returns 400 Bad Request."""
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"detail": "Unsupported file format '.exe'."}

    with patch("requests.post", return_value=mock_resp):
        with pytest.raises(APIClientError) as exc_info:
            client.upload_document(filename="virus.exe", file_bytes=b"content")
        assert exc_info.value.status_code == 400
        assert "Unsupported file format" in exc_info.value.message


def test_api_client_findings_retrieval(client: APIClient):
    """Verify findings retrieval endpoint response parsing."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "document_id": "doc-999",
        "total_findings": 1,
        "findings": [{"rule_id": "FINRA-2210", "severity": "CRITICAL"}]
    }

    with patch("requests.get", return_value=mock_resp):
        res = client.get_document_findings("doc-999")
        assert res["total_findings"] == 1
        assert res["findings"][0]["rule_id"] == "FINRA-2210"


def test_api_client_findings_invalid_document_id(client: APIClient):
    """Verify 404 response raises APIClientError with status 404."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.json.return_value = {"detail": "Document 'unknown-doc' not found."}

    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(APIClientError) as exc_info:
            client.get_document_findings("unknown-doc")
        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.message


def test_api_client_submit_review_decision_success(client: APIClient):
    """Verify human review submission response parsing."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "document_id": "doc-123",
        "officer_id": "officer_dan",
        "decision": "APPROVED",
        "notes": "Reviewed and cleared.",
        "decided_at": "2026-11-07T12:00:00Z"
    }

    with patch("requests.post", return_value=mock_resp):
        res = client.submit_review_decision(
            document_id="doc-123",
            officer_id="officer_dan",
            decision="APPROVED",
            notes="Reviewed and cleared."
        )
        assert res["decision"] == "APPROVED"
        assert res["officer_id"] == "officer_dan"


def test_api_client_submit_review_missing_officer_id(client: APIClient):
    """Verify 422 Unprocessable Content error handling."""
    mock_resp = MagicMock()
    mock_resp.status_code = 422
    mock_resp.json.return_value = {"detail": "Officer ID cannot be empty or whitespace."}

    with patch("requests.post", return_value=mock_resp):
        with pytest.raises(APIClientError) as exc_info:
            client.submit_review_decision(
                document_id="doc-123",
                officer_id="",
                decision="APPROVED"
            )
        assert exc_info.value.status_code == 422
        assert "Officer ID cannot be empty" in exc_info.value.message


def test_api_client_invalid_json_response_handling(client: APIClient):
    """Verify graceful handling when backend returns non-JSON or HTML error page."""
    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_resp.json.side_effect = ValueError("Invalid JSON")

    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(APIClientError) as exc_info:
            client.get_document_status("doc-502")
        assert exc_info.value.status_code == 502
        assert "status code 502" in exc_info.value.message


def test_upload_size_limit_15mb_configuration():
    """Verify that frontend upload size constraints consistently enforce 15 MB."""
    from frontend.config import MAX_FILE_SIZE_MB, MAX_FILE_SIZE_BYTES

    assert MAX_FILE_SIZE_MB == 15
    assert MAX_FILE_SIZE_BYTES == 15 * 1024 * 1024

    valid_file_size = 15 * 1024 * 1024  # Exactly 15 MB
    oversized_file_size = 15 * 1024 * 1024 + 1  # 15 MB + 1 byte

    assert valid_file_size <= MAX_FILE_SIZE_BYTES
    assert oversized_file_size > MAX_FILE_SIZE_BYTES


def test_api_client_upload_oversized_file_error(client: APIClient):
    """Verify APIClientError handling when backend returns HTTP 413 File Too Large."""
    mock_resp = MagicMock()
    mock_resp.status_code = 413
    mock_resp.json.return_value = {"detail": "File size exceeds the 15 MB upload limit."}

    with patch("requests.post", return_value=mock_resp):
        with pytest.raises(APIClientError) as exc_info:
            client.upload_document(filename="giant.pdf", file_bytes=b"0" * (16 * 1024 * 1024))
        assert exc_info.value.status_code == 413
        assert "15 MB upload limit" in exc_info.value.message


def test_api_client_retry_document_success(client: APIClient):
    """Verify document retry response handling."""
    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.json.return_value = {
        "document_id": "doc-retry-123",
        "filename": "test.txt",
        "file_type": "txt",
        "status": "QUEUED",
        "message": "Document analyzed successfully."
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = client.retry_document("doc-retry-123")
        assert res["document_id"] == "doc-retry-123"
        assert res["status"] == "QUEUED"
        mock_post.assert_called_once_with(
            "http://test-server:8000/api/documents/doc-retry-123/retry",
            headers={}, timeout=5
        )


def test_api_client_retry_document_timeout(client: APIClient):
    """Verify clean APIClientError on retry timeout."""
    with patch("requests.post", side_effect=requests.exceptions.Timeout("Read timed out")):
        with pytest.raises(APIClientError) as exc_info:
            client.retry_document("doc-retry-123")
        assert "timed out" in exc_info.value.message

