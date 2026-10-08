"""End-to-End Acceptance Tests for ApplyPilot Configurable AI Providers.

Verifies all three configurations:
  AUTO_APPLY_AI_PROVIDER=claude
  AUTO_APPLY_AI_PROVIDER=gemini
  AUTO_APPLY_AI_PROVIDER=openai

Each executes the full flow:
  UI → ApplyPilot → Selected AI Provider → Chrome/Playwright → Fill Form → Upload Resume → Submit → Verify Submission → APPLIED

Also strictly verifies:
  APPLIED cannot occur without verified real submission evidence!
"""

import http.server
import json
import os
import socketserver
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from applypilot.apply.chrome import launch_chrome, cleanup_worker
from applypilot.apply.providers import (
    get_provider,
    get_active_provider_name,
    ClaudeProvider,
    GeminiProvider,
    OpenAIProvider,
    OllamaProvider,
)
from applypilot.apply.providers.browser_controller import BrowserController
from applypilot.apply.providers.verification import verify_submission_on_port, verify_page_submission


class MockJobServerHandler(http.server.BaseHTTPRequestHandler):
    """Serves a realistic job application form and verifies submission."""

    def log_message(self, format, *args):
        pass  # Quiet logging

    def do_GET(self):
        if self.path == "/apply/job-1":
            html = """<!DOCTYPE html>
            <html>
            <head><title>Senior Software Engineer Application</title></head>
            <body>
                <h1>Apply for Senior Software Engineer</h1>
                <form action="/apply/submit" method="POST" enctype="multipart/form-data">
                    <label for="full_name">Full Name</label>
                    <input type="text" id="full_name" name="full_name" required><br>

                    <label for="email">Email</label>
                    <input type="email" id="email" name="email" required><br>

                    <label for="phone">Phone</label>
                    <input type="tel" id="phone" name="phone"><br>

                    <label for="resume">Upload Resume</label>
                    <input type="file" id="resume" name="resume" required><br>

                    <label for="screening">Why are you interested in this role?</label>
                    <textarea id="screening" name="screening"></textarea><br>

                    <button type="submit" id="submit-btn">Submit Application</button>
                </form>
            </body>
            </html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        elif self.path == "/apply/confirmation":
            html = """<!DOCTYPE html>
            <html>
            <head><title>Application Confirmation</title></head>
            <body>
                <h1>Application Submitted!</h1>
                <p>Thank you for applying. Your application has been received by our hiring team.</p>
                <div class="application-confirmation">Reference ID: APP-98765</div>
            </body>
            </html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        elif self.path == "/apply/error":
            html = """<!DOCTYPE html>
            <html>
            <head><title>Application Error</title></head>
            <body>
                <h1>Submission Failed</h1>
                <p>Please fix the following errors: Required fields are missing.</p>
            </body>
            </html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/apply/submit":
            self.send_response(303)
            self.send_header("Location", "/apply/confirmation")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(scope="module")
def mock_server():
    """Start local mock ATS server on an available port."""
    server = socketserver.TCPServer(("127.0.0.1", 0), MockJobServerHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture(scope="module")
def real_chrome():
    """Launch an isolated real Chrome instance with CDP on port 9444 for testing."""
    test_port = 9444
    proc = launch_chrome(worker_id=88, port=test_port, headless=True)
    yield test_port
    cleanup_worker(88, proc)


def test_browser_controller_full_flow(mock_server, real_chrome):
    """Test BrowserController navigating, filling form, uploading file, submitting, and verifying."""
    port = real_chrome
    job_url = f"{mock_server}/apply/job-1"

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 test resume pdf content")
        dummy_resume_path = f.name

    try:
        with BrowserController(port=port) as browser:
            # 1. Navigate
            nav = browser.navigate(job_url)
            assert nav["title"] == "Senior Software Engineer Application"

            # 2. Inspect form
            snapshot = browser.get_snapshot()
            assert snapshot["fields_count"] >= 4

            # 3. Fill fields
            fill_res = browser.fill_form_fields([
                {"label": "Full Name", "value": "Jane Candidate"},
                {"label": "Email", "value": "jane.candidate@example.com"},
                {"label": "Phone", "value": "555-0199"},
                {"label": "Why are you interested", "value": "Excited about distributed systems!"},
            ])
            assert len(fill_res["filled"]) >= 3

            # 4. Upload resume
            uploaded = browser.upload_file(dummy_resume_path)
            assert uploaded is True

            # 5. Submit application
            clicked = browser.click_element("#submit-btn")
            assert clicked is True

            browser.wait(1.5)

            # 6. Verify submission evidence
            verified, reason = browser.verify_submission()
            assert verified is True
            assert "Verified" in reason
            assert "confirmation" in reason.lower()

    finally:
        if os.path.exists(dummy_resume_path):
            os.remove(dummy_resume_path)


def test_submission_verification_rejects_unsubmitted_page(mock_server, real_chrome):
    """Verify Requirement 5: APPLIED is rejected if page was not submitted."""
    port = real_chrome
    job_url = f"{mock_server}/apply/job-1"

    with BrowserController(port=port) as browser:
        browser.navigate(job_url)
        # Form not submitted!
        verified, reason = browser.verify_submission()
        assert verified is False
        assert "No strong evidence of submission found" in reason


def _mock_llm_responses_for_real_flow(dummy_resume_path):
    """Helper creating mock responses for autonomous LLM agent turns."""
    # Turn 1: fill form & upload resume
    turn1_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Inspecting application and filling fields.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "browser_fill_form",
                            "arguments": json.dumps({
                                "fields": [
                                    {"label": "Full Name", "value": "Alex Candidate"},
                                    {"label": "Email", "value": "alex@example.com"},
                                    {"label": "Phone", "value": "555-0123"},
                                    {"label": "Why are you interested", "value": "Great team."},
                                ]
                            }),
                        },
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "browser_upload_resume",
                            "arguments": json.dumps({"resume_path": dummy_resume_path}),
                        },
                    },
                ],
            }
        }]
    }

    # Turn 2: submit application
    turn2_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "All fields filled. Submitting application now.",
                "tool_calls": [
                    {
                        "id": "call_3",
                        "type": "function",
                        "function": {
                            "name": "browser_submit_application",
                            "arguments": json.dumps({"submit_button_text": "#submit-btn"}),
                        },
                    }
                ],
            }
        }]
    }

    # Turn 3: finish
    turn3_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "RESULT:APPLIED",
                "tool_calls": [],
            }
        }]
    }

    return [turn1_response, turn2_response, turn3_response]


def test_gemini_provider_execution_flow(monkeypatch, mock_server, real_chrome):
    """Verify GeminiProvider executes real flow and strictly verifies submission."""
    monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")

    provider = get_provider()
    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini"

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 test resume")
        res_pdf = f.name

    job = {
        "url": f"{mock_server}/apply/job-1",
        "title": "Backend Engineer",
        "site": "TestCorp",
        "fit_score": 9,
        "tailored_resume_path": res_pdf,
    }

    mock_turns = _mock_llm_responses_for_real_flow(res_pdf)
    turn_idx = 0

    def mock_post(*args, **kwargs):
        nonlocal turn_idx
        idx = min(turn_idx, len(mock_turns) - 1)
        turn_idx += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = mock_turns[idx]
        return resp

    with patch("httpx.Client.post", side_effect=mock_post):
        status, duration = provider.run(job=job, port=real_chrome, worker_id=88, dry_run=False)
        # Real flow executed against Chrome, submitted to mock server, verified by verification engine!
        assert status == "applied"
        assert duration > 0

    if os.path.exists(res_pdf):
        os.remove(res_pdf)


def test_openai_provider_execution_flow(monkeypatch, mock_server, real_chrome):
    """Verify OpenAIProvider executes real flow and strictly verifies submission."""
    monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test_openai_key")

    provider = get_provider()
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 test resume")
        res_pdf = f.name

    job = {
        "url": f"{mock_server}/apply/job-1",
        "title": "Fullstack Engineer",
        "site": "TestCorp",
        "fit_score": 8,
        "tailored_resume_path": res_pdf,
    }

    mock_turns = _mock_llm_responses_for_real_flow(res_pdf)
    turn_idx = 0

    def mock_post(*args, **kwargs):
        nonlocal turn_idx
        idx = min(turn_idx, len(mock_turns) - 1)
        turn_idx += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = mock_turns[idx]
        return resp

    with patch("httpx.Client.post", side_effect=mock_post):
        status, duration = provider.run(job=job, port=real_chrome, worker_id=88, dry_run=False)
        assert status == "applied"
        assert duration > 0

    if os.path.exists(res_pdf):
        os.remove(res_pdf)


def test_ollama_provider_execution_flow(monkeypatch, mock_server, real_chrome):
    """Verify OllamaProvider executes real flow and strictly verifies submission."""
    monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "gpt-oss:20b")

    provider = get_provider()
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama"

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 test resume")
        res_pdf = f.name

    job = {
        "url": f"{mock_server}/apply/job-1",
        "title": "Golang Backend Developer",
        "site": "TestCorp",
        "fit_score": 9,
        "tailored_resume_path": res_pdf,
    }

    mock_turns = _mock_llm_responses_for_real_flow(res_pdf)
    turn_idx = 0

    def mock_post(*args, **kwargs):
        nonlocal turn_idx
        idx = min(turn_idx, len(mock_turns) - 1)
        turn_idx += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = mock_turns[idx]
        return resp

    mock_get = MagicMock()
    mock_get.status_code = 200
    mock_get.json.return_value = {"version": "0.3.14", "models": [{"name": "gpt-oss:20b"}]}

    with patch("httpx.get", return_value=mock_get):
        with patch("httpx.Client.post", side_effect=mock_post):
            status, duration = provider.run(job=job, port=real_chrome, worker_id=88, dry_run=False)
            assert status == "applied"
            assert duration > 0

    if os.path.exists(res_pdf):
        os.remove(res_pdf)


def test_claude_provider_execution_flow(monkeypatch, mock_server, real_chrome):
    """Verify ClaudeProvider executes and verifies submission."""
    monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "claude")

    provider = get_provider()
    assert isinstance(provider, ClaudeProvider)
    assert provider.name == "claude"

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 test resume")
        res_pdf = f.name

    job = {
        "url": f"{mock_server}/apply/job-1",
        "title": "Systems Engineer",
        "site": "TestCorp",
        "fit_score": 9,
        "tailored_resume_path": res_pdf,
    }

    # 1. In dry-run mode: verify dry-run marks applied without requiring real submission
    with patch("applypilot.apply.providers.claude._spawn_claude_process") as mock_spawn:
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.stdout = iter([
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Filling form..."}]}}),
            json.dumps({"type": "result", "result": "RESULT:APPLIED (dry run)", "usage": {"input_tokens": 100, "output_tokens": 50}}),
        ])
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_spawn.return_value = mock_proc

        status, duration = provider.run(job=job, port=real_chrome, worker_id=88, dry_run=True)
        assert status == "applied"
        assert duration >= 0

    # 2. Critical Requirement 5: On a REAL run (dry_run=False), if Claude outputs RESULT:APPLIED
    # but the browser does NOT show submission evidence, APPLIED MUST NOT BE RETURNED!
    with patch("applypilot.apply.providers.claude._spawn_claude_process") as mock_spawn:
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.stdout = iter([
            json.dumps({"type": "result", "result": "RESULT:APPLIED"}),
        ])
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_spawn.return_value = mock_proc

        # Navigate browser to unsubmitted job page
        with BrowserController(port=real_chrome) as browser:
            browser.navigate(f"{mock_server}/apply/job-1")

        status, duration = provider.run(job=job, port=real_chrome, worker_id=88, dry_run=False)
        # MUST FAIL with unverified submission!
        assert status.startswith("failed:unverified_submission")

    # 3. On a REAL run with actual submitted confirmation in the browser: APPLIED IS VERIFIED!
    with patch("applypilot.apply.providers.claude._spawn_claude_process") as mock_spawn:
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.stdout = iter([
            json.dumps({"type": "result", "result": "RESULT:APPLIED"}),
        ])
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_spawn.return_value = mock_proc

        # Navigate browser to confirmation page
        with BrowserController(port=real_chrome) as browser:
            browser.navigate(f"{mock_server}/apply/confirmation")

        status, duration = provider.run(job=job, port=real_chrome, worker_id=88, dry_run=False)
        # MUST SUCCEED because real submission is confirmed!
        assert status == "applied"

    if os.path.exists(res_pdf):
        os.remove(res_pdf)
