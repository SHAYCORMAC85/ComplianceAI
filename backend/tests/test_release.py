"""Release regressions for evaluation scoring and the history page error state."""
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from evaluation.final_evaluation import evaluate
from frontend.api.client import APIClientError, api_client


@pytest.mark.asyncio
async def test_mock_evaluation_counts_clean_sections_and_exact_findings():
    report = await evaluate()
    assert report["scored"] == report["attempts"] == 20
    assert report["section"]["tn"] == 6
    assert report["finding"]["tp"] == 3
    assert report["exact_quotes"] == report["candidates"] == 5


def test_history_unavailable_reports_error():
    path = Path(__file__).resolve().parents[2] / "frontend/pages/5_Review_History.py"
    page = AppTest.from_file(path)
    page.session_state["officer_session"] = {"officer_id":"test","token":"synthetic"}
    with patch.object(api_client,"check_health",return_value={"llm_provider":"mock"}), patch.object(
        api_client,"list_documents",side_effect=APIClientError("Unavailable",503)
    ):
        page.run()
    assert not page.exception
    assert any("Could not load recorded decisions" in item.value for item in page.error)
