"""Unit tests for submission verification (Requirement 5)."""

import pytest
from unittest.mock import MagicMock
from applypilot.apply.providers.verification import verify_page_submission


def _make_mock_page(url: str, body_text: str, has_ats_element: bool = False):
    page = MagicMock()
    page.url = url
    page.inner_text.return_value = body_text

    def _locator(sel):
        loc = MagicMock()
        if sel == "body":
            loc.count.return_value = 1
        else:
            loc.count.return_value = 1 if has_ats_element else 0
            loc.first.is_visible.return_value = has_ats_element
        return loc

    page.locator.side_effect = _locator
    return page


def test_verify_submission_positive_text():
    page = _make_mock_page(
        url="https://jobs.example.com/apply",
        body_text="Thank you for applying! Your application has been received by our hiring team.",
    )
    verified, reason = verify_page_submission(page)
    assert verified is True
    assert "Verified by confirmation text" in reason


def test_verify_submission_positive_url():
    page = _make_mock_page(
        url="https://boards.greenhouse.io/company/jobs/12345/confirmation",
        body_text="All done.",
    )
    verified, reason = verify_page_submission(page)
    assert verified is True
    assert "Verified by confirmation URL" in reason


def test_verify_submission_rejected_due_to_form_error():
    page = _make_mock_page(
        url="https://jobs.example.com/apply",
        body_text="Please fix the following errors before submitting: Required fields are missing. Thank you for applying.",
    )
    verified, reason = verify_page_submission(page)
    # Even if "thank you for applying" was somewhere in the footer, error banner takes precedence!
    assert verified is False
    assert "Submission error detected" in reason


def test_verify_submission_rejected_no_evidence():
    page = _make_mock_page(
        url="https://jobs.example.com/apply",
        body_text="Submit your application. Fill in your details below.",
    )
    verified, reason = verify_page_submission(page)
    assert verified is False
    assert "No strong evidence of submission found" in reason


def test_verify_submission_ats_element():
    page = _make_mock_page(
        url="https://jobs.example.com/apply",
        body_text="Welcome to the portal",
        has_ats_element=True,
    )
    verified, reason = verify_page_submission(page)
    assert verified is True
    assert "Verified by ATS confirmation element" in reason
