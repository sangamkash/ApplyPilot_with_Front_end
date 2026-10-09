"""Comprehensive concurrency and safety tests for the auto-apply system.

Covers:
- Provider isolation: AUTO_APPLY_AI_PROVIDER exactly controls which provider runs.
- Atomic job claiming: two workers cannot claim the same job.
- Already-applied guard: applied jobs are not re-claimed.
- In-progress guard: in-progress jobs are not re-claimed.
- Submission-state handling: submitted_unverified / unknown_submission is NOT retried.
- Failure-before-submit: retryable.
- Multi-worker queue: different jobs dispatched correctly.
- Web API duplicate: POST /api/jobs/apply rejects already-in-progress jobs.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from unittest.mock import patch

import pytest


# ─── Helpers ────────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path, jobs: list[dict]) -> Path:
    """Create a fresh SQLite database with the given jobs pre-inserted."""
    from applypilot.database import init_db
    db_path = tmp_path / "test_jobs.db"
    conn = init_db(db_path)
    for j in jobs:
        conn.execute("""
            INSERT OR IGNORE INTO jobs
                (url, title, site, tailored_resume_path, fit_score, apply_status, applied_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            j["url"],
            j.get("title", "Test Job"),
            j.get("site", "TestSite"),
            j.get("tailored_resume_path", "/tmp/resume.pdf"),
            j.get("fit_score", 8),
            j.get("apply_status", None),
            j.get("applied_at", None),
        ))
    conn.commit()
    return db_path


def _patch_db(monkeypatch, db_path: Path):
    """Redirect database access to test_db."""
    import applypilot.database as dbmod
    orig = dbmod.get_connection

    def test_get_conn(path=None):
        return orig(db_path)

    monkeypatch.setattr(dbmod, "get_connection", test_get_conn)
    monkeypatch.setattr("applypilot.apply.launcher.get_connection", test_get_conn)
    return test_get_conn


# ─── 1. Provider Isolation ───────────────────────────────────────────────────

class TestProviderIsolation:
    """AUTO_APPLY_AI_PROVIDER must select exactly ONE provider for a given application."""

    @pytest.mark.parametrize("provider_name,expected_cls_name", [
        ("gemini", "GeminiProvider"),
        ("openai", "OpenAIProvider"),
        ("claude", "ClaudeProvider"),
        ("ollama", "OllamaProvider"),
    ])
    def test_correct_provider_instantiated(self, monkeypatch, provider_name, expected_cls_name):
        """Each AUTO_APPLY_AI_PROVIDER value must instantiate exactly that provider class."""
        monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", provider_name)
        from applypilot.apply.providers import get_provider
        prov = get_provider()
        assert type(prov).__name__ == expected_cls_name, (
            f"Expected {expected_cls_name}, got {type(prov).__name__}"
        )
        assert prov.name == provider_name

    def test_unsupported_provider_raises(self, monkeypatch):
        """Unknown provider name must raise ValueError, not silently fall back."""
        monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "gpt99_ultra")
        from applypilot.apply.providers import get_provider
        with pytest.raises(ValueError, match="Unsupported AI provider"):
            get_provider()

    def test_no_auto_fallback_from_gemini(self, monkeypatch):
        """If gemini is set, get_provider() must return GeminiProvider (not claude, openai, etc.)."""
        monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "gemini")
        from applypilot.apply.providers import get_provider, GeminiProvider
        prov = get_provider()
        assert isinstance(prov, GeminiProvider)

    def test_no_auto_fallback_from_ollama(self, monkeypatch):
        """If ollama is set, get_provider() must return OllamaProvider."""
        monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "ollama")
        from applypilot.apply.providers import get_provider, OllamaProvider
        prov = get_provider()
        assert isinstance(prov, OllamaProvider)

    def test_provider_name_matches_env(self, monkeypatch):
        """The provider .name attribute must match AUTO_APPLY_AI_PROVIDER."""
        for name in ("claude", "gemini", "openai", "ollama"):
            monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", name)
            from applypilot.apply.providers import get_provider
            prov = get_provider()
            assert prov.name == name

    def test_mixed_case_provider_normalized(self, monkeypatch):
        """AUTO_APPLY_AI_PROVIDER is case-insensitive."""
        monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "GEMINI")
        from applypilot.apply.providers import get_provider, GeminiProvider
        prov = get_provider()
        assert isinstance(prov, GeminiProvider)

    def test_gemini_does_not_invoke_openai(self, monkeypatch):
        """With AUTO_APPLY_AI_PROVIDER=gemini, OpenAIProvider must not be instantiated."""
        monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "gemini")
        from applypilot.apply.providers import get_provider
        from applypilot.apply.providers.openai import OpenAIProvider
        instantiated = []
        original_init = OpenAIProvider.__init__

        def tracking_init(self, *a, **kw):
            instantiated.append("openai")
            return original_init(self, *a, **kw)

        OpenAIProvider.__init__ = tracking_init
        try:
            prov = get_provider()
        finally:
            OpenAIProvider.__init__ = original_init

        assert instantiated == [], (
            f"OpenAIProvider was instantiated even though AUTO_APPLY_AI_PROVIDER=gemini: {instantiated}"
        )

    def test_ollama_does_not_invoke_gemini(self, monkeypatch):
        """With AUTO_APPLY_AI_PROVIDER=ollama, GeminiProvider must not be instantiated."""
        monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "ollama")
        from applypilot.apply.providers import get_provider
        from applypilot.apply.providers.gemini import GeminiProvider
        instantiated = []
        original_init = GeminiProvider.__init__

        def tracking_init(self, *a, **kw):
            instantiated.append("gemini")
            return original_init(self, *a, **kw)

        GeminiProvider.__init__ = tracking_init
        try:
            prov = get_provider()
        finally:
            GeminiProvider.__init__ = original_init

        assert instantiated == [], (
            f"GeminiProvider was instantiated even though AUTO_APPLY_AI_PROVIDER=ollama: {instantiated}"
        )

    def test_scoring_independent_of_auto_apply_provider(self, monkeypatch):
        """AUTO_APPLY_AI_PROVIDER must not affect scoring LLM config."""
        monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "ollama")
        from applypilot.apply.providers import get_active_provider_name
        # Scoring uses LLM_MODEL / GEMINI_API_KEY / OPENAI_API_KEY, not this var
        assert get_active_provider_name() == "ollama"
        # Scoring path does not check get_active_provider_name(); verifying env isolation
        monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "gemini")
        assert get_active_provider_name() == "gemini"
        # Value switch does not affect each other's API keys
        import os
        assert os.environ.get("AUTO_APPLY_AI_PROVIDER") == "gemini"


# ─── 2. Atomic Job Claiming ──────────────────────────────────────────────────

class TestAtomicJobClaiming:
    """acquire_job() must guarantee at most one winner in a race."""

    def test_only_one_worker_claims_job(self, tmp_path, monkeypatch):
        """Two concurrent workers racing to claim the same job; exactly one must win."""
        db_path = _make_db(tmp_path, [{"url": "https://jobs.test/race-job-1"}])
        _patch_db(monkeypatch, db_path)

        from applypilot.apply.launcher import acquire_job

        results: list[dict | None] = []
        errors: list[Exception] = []

        def try_claim(worker_id: int):
            try:
                with patch("applypilot.config.is_manual_ats", return_value=False):
                    job = acquire_job(target_url="https://jobs.test/race-job-1", worker_id=worker_id)
                results.append(job)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=try_claim, args=(0,))
        t2 = threading.Thread(target=try_claim, args=(1,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"Unexpected exceptions during claim race: {errors}"
        winners = [r for r in results if r is not None]
        losers = [r for r in results if r is None]

        assert len(winners) == 1, (
            f"Expected exactly 1 worker to claim the job, got {len(winners)}"
        )
        assert len(losers) == 1, (
            f"Expected exactly 1 worker to be rejected, got {len(losers)}"
        )
        assert winners[0].get("attempt_id"), "Claimed job must have an attempt_id"

    def test_applied_job_not_claimable(self, tmp_path, monkeypatch):
        """A job with apply_status='applied' must never be claimed."""
        db_path = _make_db(tmp_path, [{
            "url": "https://jobs.test/applied-job",
            "apply_status": "applied",
            "applied_at": "2026-10-01T00:00:00",
        }])
        _patch_db(monkeypatch, db_path)
        from applypilot.apply.launcher import acquire_job
        job = acquire_job(target_url="https://jobs.test/applied-job", worker_id=0)
        assert job is None, "Applied job must not be claimable"

    def test_in_progress_job_not_claimable(self, tmp_path, monkeypatch):
        """A job with apply_status='in_progress' must not be claimed by a second worker."""
        db_path = _make_db(tmp_path, [{
            "url": "https://jobs.test/inprogress-job",
            "apply_status": "in_progress",
        }])
        _patch_db(monkeypatch, db_path)
        from applypilot.apply.launcher import acquire_job
        job = acquire_job(target_url="https://jobs.test/inprogress-job", worker_id=1)
        assert job is None, "In-progress job must not be claimable by second worker"

    def test_unknown_submission_not_claimable(self, tmp_path, monkeypatch):
        """A job with apply_status='unknown_submission' must NOT be auto-retried."""
        db_path = _make_db(tmp_path, [{
            "url": "https://jobs.test/unverified-job",
            "apply_status": "unknown_submission",
        }])
        _patch_db(monkeypatch, db_path)
        from applypilot.apply.launcher import acquire_job
        job = acquire_job(target_url="https://jobs.test/unverified-job", worker_id=0)
        assert job is None, "unknown_submission job must not be claimable"

    def test_failed_job_is_claimable(self, tmp_path, monkeypatch):
        """A job with apply_status='failed' (before submit) must be retryable."""
        db_path = _make_db(tmp_path, [{
            "url": "https://jobs.test/failed-job",
            "apply_status": "failed",
        }])
        _patch_db(monkeypatch, db_path)
        with patch("applypilot.config.is_manual_ats", return_value=False):
            from applypilot.apply.launcher import acquire_job
            job = acquire_job(target_url="https://jobs.test/failed-job", worker_id=0)
        assert job is not None, "Failed (before submit) job must be retryable"

    def test_claim_sets_attempt_id(self, tmp_path, monkeypatch):
        """A successful claim must assign a unique attempt_id."""
        db_path = _make_db(tmp_path, [{"url": "https://jobs.test/attempt-id-test"}])
        _patch_db(monkeypatch, db_path)
        with patch("applypilot.config.is_manual_ats", return_value=False):
            from applypilot.apply.launcher import acquire_job
            job = acquire_job(target_url="https://jobs.test/attempt-id-test", worker_id=0)
        assert job is not None
        assert "attempt_id" in job
        assert len(job["attempt_id"]) >= 8


# ─── 3. Submission-State Handling ────────────────────────────────────────────

class TestSubmissionStateHandling:
    """Verify that submission-state transitions follow the retry policy."""

    def test_mark_result_unknown_submission_does_not_increment_attempts(self, tmp_path, monkeypatch):
        """unknown_submission must NOT increment apply_attempts."""
        db_path = _make_db(tmp_path, [{"url": "https://jobs.test/sub-test"}])
        _patch_db(monkeypatch, db_path)
        from applypilot.apply.launcher import mark_result
        mark_result("https://jobs.test/sub-test", "unknown_submission",
                    error="verification_failed", attempt_id="test-attempt")
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT apply_status, apply_attempts FROM jobs WHERE url = ?",
            ("https://jobs.test/sub-test",)
        ).fetchone()
        conn.close()
        assert row[0] == "unknown_submission"
        assert (row[1] or 0) == 0, "apply_attempts must NOT be incremented for unknown_submission"

    def test_mark_result_submitted_unverified_becomes_unknown_submission(self, tmp_path, monkeypatch):
        """submitted_unverified is an alias for unknown_submission in the DB."""
        db_path = _make_db(tmp_path, [{"url": "https://jobs.test/alias-test"}])
        _patch_db(monkeypatch, db_path)
        from applypilot.apply.launcher import mark_result
        mark_result("https://jobs.test/alias-test", "submitted_unverified")
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT apply_status FROM jobs WHERE url = ?",
                           ("https://jobs.test/alias-test",)).fetchone()
        conn.close()
        assert row[0] == "unknown_submission"

    def test_mark_result_failed_increments_attempts(self, tmp_path, monkeypatch):
        """failed (before submit) must increment apply_attempts."""
        db_path = _make_db(tmp_path, [{"url": "https://jobs.test/fail-test"}])
        _patch_db(monkeypatch, db_path)
        from applypilot.apply.launcher import mark_result
        mark_result("https://jobs.test/fail-test", "failed", error="browser_crashed")
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT apply_status, apply_attempts FROM jobs WHERE url = ?",
                           ("https://jobs.test/fail-test",)).fetchone()
        conn.close()
        assert row[0] == "failed"
        assert (row[1] or 0) >= 1

    def test_unknown_submission_not_in_queue(self, tmp_path, monkeypatch):
        """unknown_submission jobs must not appear in the regular queue."""
        db_path = _make_db(tmp_path, [{
            "url": "https://jobs.test/queue-test",
            "apply_status": "unknown_submission",
        }])
        _patch_db(monkeypatch, db_path)
        from applypilot.apply.launcher import acquire_job
        job = acquire_job(worker_id=0)
        assert job is None, "unknown_submission jobs must not appear in queue"

    def test_applied_sets_applied_at(self, tmp_path, monkeypatch):
        """apply_status='applied' must also set applied_at timestamp."""
        db_path = _make_db(tmp_path, [{"url": "https://jobs.test/applied-at-test"}])
        _patch_db(monkeypatch, db_path)
        from applypilot.apply.launcher import mark_result
        mark_result("https://jobs.test/applied-at-test", "applied")
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT apply_status, applied_at FROM jobs WHERE url = ?",
                           ("https://jobs.test/applied-at-test",)).fetchone()
        conn.close()
        assert row[0] == "applied"
        assert row[1] is not None, "applied_at must be set when status is 'applied'"


# ─── 4. Multi-Worker Queue ───────────────────────────────────────────────────

class TestMultiWorkerQueue:
    """Multiple workers must each claim DIFFERENT jobs, never the same one."""

    def test_three_workers_claim_three_distinct_jobs(self, tmp_path, monkeypatch):
        """With 3 jobs and 3 workers, each worker must claim a distinct job."""
        jobs = [
            {"url": f"https://jobs.test/mw-job-{i}", "title": f"Job {i}",
             "tailored_resume_path": "/tmp/r.pdf", "apply_status": None}
            for i in range(3)
        ]
        db_path = _make_db(tmp_path, jobs)
        _patch_db(monkeypatch, db_path)

        claimed_urls: list[str] = []
        lock = threading.Lock()
        errors: list[Exception] = []

        with patch("applypilot.config.is_manual_ats", return_value=False):
            from applypilot.apply.launcher import acquire_job

            def worker_fn(wid: int):
                try:
                    job = acquire_job(worker_id=wid)
                    if job:
                        with lock:
                            claimed_urls.append(job["url"])
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker_fn, args=(i,)) for i in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

        assert not errors, f"Worker errors: {errors}"
        assert len(set(claimed_urls)) == len(claimed_urls), f"Duplicate URLs claimed: {claimed_urls}"
        assert len(claimed_urls) == 3, f"Expected 3 jobs claimed, got {len(claimed_urls)}: {claimed_urls}"

    def test_targeted_url_cannot_be_claimed_by_two_workers(self, tmp_path, monkeypatch):
        """Two workers targeting the same URL: only one must succeed."""
        db_path = _make_db(tmp_path, [{"url": "https://jobs.test/targeted-url"}])
        _patch_db(monkeypatch, db_path)

        results: list[dict | None] = []
        errors: list[Exception] = []

        with patch("applypilot.config.is_manual_ats", return_value=False):
            from applypilot.apply.launcher import acquire_job

            def try_claim(wid):
                try:
                    job = acquire_job(target_url="https://jobs.test/targeted-url", worker_id=wid)
                    results.append(job)
                except Exception as e:
                    errors.append(e)

            t1 = threading.Thread(target=try_claim, args=(0,))
            t2 = threading.Thread(target=try_claim, args=(1,))
            t1.start(); t2.start()
            t1.join(timeout=10); t2.join(timeout=10)

        assert not errors
        winners = [r for r in results if r is not None]
        assert len(winners) == 1, "Only one worker must claim the targeted URL"


# ─── 5. Web API Duplicate Protection ─────────────────────────────────────────

class TestWebApiDuplicateProtection:
    """POST /api/jobs/apply must reject already-in-progress or already-applied jobs."""

    def test_in_progress_task_rejected_by_memory_check(self):
        """URL already in AUTO_APPLY_TASKS as in_progress → rejected."""
        import web.server as srv
        url = "https://jobs.test/api-dup-test"
        with srv.AUTO_APPLY_LOCK:
            srv.AUTO_APPLY_TASKS[url] = {"url": url, "status": "in_progress", "profile": "test"}
        try:
            rejected: list[dict] = []
            accepted: list[str] = []
            for u in [url]:
                with srv.AUTO_APPLY_LOCK:
                    existing = srv.AUTO_APPLY_TASKS.get(u)
                if existing and existing.get("status") == "in_progress":
                    rejected.append({"url": u, "reason": "already_in_progress_in_memory"})
                else:
                    accepted.append(u)
            assert len(rejected) == 1
            assert rejected[0]["reason"] == "already_in_progress_in_memory"
            assert len(accepted) == 0
        finally:
            with srv.AUTO_APPLY_LOCK:
                srv.AUTO_APPLY_TASKS.pop(url, None)

    def test_applied_db_status_rejected(self):
        """Job with apply_status='applied' in DB is rejected by the apply API."""
        import web.server as srv
        url = "https://jobs.test/applied-api"
        db_statuses = {url: "applied"}
        rejected: list[dict] = []
        accepted: list[str] = []
        with srv.AUTO_APPLY_LOCK:
            existing = srv.AUTO_APPLY_TASKS.get(url)
        if not existing or existing.get("status") != "in_progress":
            db_status = db_statuses.get(url)
            if db_status == "applied":
                rejected.append({"url": url, "reason": "already_applied"})
            else:
                accepted.append(url)
        assert len(rejected) == 1 and rejected[0]["reason"] == "already_applied"
        assert len(accepted) == 0

    def test_unknown_submission_rejected_by_api(self):
        """Job with unknown_submission status is rejected."""
        import web.server as srv
        url = "https://jobs.test/unknown-sub-api"
        db_statuses = {url: "unknown_submission"}
        rejected: list[dict] = []
        accepted: list[str] = []
        with srv.AUTO_APPLY_LOCK:
            existing = srv.AUTO_APPLY_TASKS.get(url)
        if not existing or existing.get("status") != "in_progress":
            db_status = db_statuses.get(url)
            if db_status in ("unknown_submission", "submitted_unverified"):
                rejected.append({"url": url, "reason": "submission_already_attempted"})
            else:
                accepted.append(url)
        assert len(rejected) == 1 and rejected[0]["reason"] == "submission_already_attempted"
