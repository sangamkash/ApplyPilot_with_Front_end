"""Apply orchestration: acquire jobs, spawn Claude Code sessions, track results.

This is the main entry point for the apply pipeline. It pulls jobs from
the database, launches Chrome + Claude Code for each one, parses the
result, and updates the database. Supports parallel workers via --workers.

Concurrency model:
  - Jobs are claimed via an ATOMIC SQL UPDATE (BEGIN IMMEDIATE + rowcount check).
  - Only the worker that successfully updates exactly one row may continue.
  - Submission states distinguish pre-submit failures (retryable) from
    post-submit ambiguity (not retryable: unknown_submission).
"""

import atexit
import json
import logging
import os
import platform
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.live import Live

from applypilot import config
from applypilot.database import get_connection
from applypilot.apply import chrome, dashboard, prompt as prompt_mod
from applypilot.apply.providers import get_provider, get_active_provider_name
from applypilot.apply.chrome import (
    launch_chrome, cleanup_worker, kill_all_chrome,
    reset_worker_dir, cleanup_on_exit, _kill_process_tree,
    BASE_CDP_PORT,
)
from applypilot.apply.dashboard import (
    init_worker, update_state, add_event, get_state,
    render_full, get_totals,
)

logger = logging.getLogger(__name__)

# Blocked sites loaded from config/sites.yaml
def _load_blocked():
    from applypilot.config import load_blocked_sites
    return load_blocked_sites()

# How often to poll the DB when the queue is empty (seconds)
POLL_INTERVAL = config.DEFAULTS["poll_interval"]

# Thread-safe shutdown coordination
_stop_event = threading.Event()

# Track active Claude Code processes for skip (Ctrl+C) handling
_claude_procs: dict[int, subprocess.Popen] = {}
_claude_lock = threading.Lock()

# Register cleanup on exit
atexit.register(cleanup_on_exit)
if platform.system() != "Windows":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


# ---------------------------------------------------------------------------
# MCP config
# ---------------------------------------------------------------------------

def _make_mcp_config(cdp_port: int) -> dict:
    """Build MCP config dict for a specific CDP port."""
    return {
        "mcpServers": {
            "playwright": {
                "command": "npx",
                "args": [
                    "@playwright/mcp@latest",
                    f"--cdp-endpoint=http://localhost:{cdp_port}",
                    f"--viewport-size={config.DEFAULTS['viewport']}",
                ],
            },
            "gmail": {
                "command": "npx",
                "args": ["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
            },
        }
    }


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

# Statuses that mean a submission attempt was made — NEVER auto-retry these.
SUBMISSION_ATTEMPTED_STATUSES: frozenset[str] = frozenset({
    "applied",
    "unknown_submission",
    "submitted_unverified",
})

# Statuses that allow the queue to pick the job up again.
RETRYABLE_STATUSES: frozenset[str] = frozenset({
    "failed",
    "pending",
})


def _structured_log(level: str, job_url: str, attempt_id: str | None = None,
                    worker_id: int | None = None, provider: str | None = None,
                    status: str | None = None, reason: str | None = None,
                    **extra: object) -> None:
    """Emit a structured AutoApply log line for observability."""
    parts = [f"[AutoApply] job={job_url[:60]}"]
    if attempt_id:
        parts.append(f"attempt={attempt_id}")
    if worker_id is not None:
        parts.append(f"worker={worker_id}")
    if provider:
        parts.append(f"provider={provider}")
    if status:
        parts.append(f"status={status}")
    if reason:
        parts.append(f"reason={reason}")
    for k, v in extra.items():
        parts.append(f"{k}={v}")
    msg = " ".join(parts)
    getattr(logger, level, logger.info)(msg)


def acquire_job(target_url: str | None = None, min_score: int = 7,
                worker_id: int = 0) -> dict | None:
    """Atomically acquire the next job to apply to.

    Uses an ATOMIC claim pattern: BEGIN IMMEDIATE → row candidate selection →
    conditional UPDATE with a strict WHERE clause → rowcount check.
    Only the worker that updates exactly 1 row may continue.

    Args:
        target_url: Apply to a specific URL instead of picking from queue.
        min_score: Minimum fit_score threshold.
        worker_id: Worker claiming this job (for tracking).

    Returns:
        Job dict with an additional 'attempt_id' field, or None.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        if target_url:
            like = f"%{target_url.split('?')[0].rstrip('/')}%"
            row = conn.execute("""
                SELECT url, title, site, application_url, tailored_resume_path,
                       fit_score, location, full_description, cover_letter_path,
                       apply_status, applied_at
                FROM jobs
                WHERE (url = ? OR application_url = ? OR application_url LIKE ? OR url LIKE ?)
                LIMIT 1
            """, (target_url, target_url, like, like)).fetchone()
        else:
            blocked_sites, blocked_patterns = _load_blocked()
            # Build parameterized filters to avoid SQL injection
            params: list = [min_score]
            site_clause = ""
            if blocked_sites:
                placeholders = ",".join("?" * len(blocked_sites))
                site_clause = f"AND site NOT IN ({placeholders})"
                params.extend(blocked_sites)
            url_clauses = ""
            if blocked_patterns:
                url_clauses = " ".join(f"AND url NOT LIKE ?" for _ in blocked_patterns)
                params.extend(blocked_patterns)
            row = conn.execute(f"""
                SELECT url, title, site, application_url, tailored_resume_path,
                       fit_score, location, full_description, cover_letter_path,
                       apply_status, applied_at
                FROM jobs
                WHERE tailored_resume_path IS NOT NULL
                  AND (
                      apply_status IS NULL
                      OR apply_status IN ('failed', 'pending')
                  )
                  AND applied_at IS NULL
                  AND (apply_attempts IS NULL OR apply_attempts < ?)
                  AND fit_score >= ?
                  {site_clause}
                  {url_clauses}
                ORDER BY fit_score DESC, url
                LIMIT 1
            """, [config.DEFAULTS["max_apply_attempts"]] + params).fetchone()

        if not row:
            conn.rollback()
            return None

        current_status = row["apply_status"]
        current_applied_at = row["applied_at"]
        job_url = row["url"]

        # --- Guard: reject terminal states ---
        if current_applied_at or current_status == "applied":
            conn.rollback()
            _structured_log("warning", job_url, worker_id=worker_id,
                            status="claim_rejected", reason="already_applied")
            return None

        if current_status == "in_progress":
            conn.rollback()
            _structured_log("warning", job_url, worker_id=worker_id,
                            status="claim_rejected", reason="already_in_progress")
            return None

        if current_status in SUBMISSION_ATTEMPTED_STATUSES:
            conn.rollback()
            _structured_log("warning", job_url, worker_id=worker_id,
                            status="claim_rejected",
                            reason=f"submission_already_attempted:{current_status}")
            return None

        # Skip manual ATS sites (unsolvable CAPTCHAs)
        from applypilot.config import is_manual_ats
        apply_url = row["application_url"] or row["url"]
        if is_manual_ats(apply_url):
            conn.execute(
                "UPDATE jobs SET apply_status = 'manual', apply_error = 'manual ATS' WHERE url = ?",
                (job_url,),
            )
            conn.commit()
            logger.info("Skipping manual ATS: %s", job_url[:80])
            return None

        now = datetime.now(timezone.utc).isoformat()
        attempt_id = str(uuid.uuid4())[:12]
        agent_label = f"worker-{worker_id}"

        # ATOMIC CLAIM: The WHERE clause ensures no other worker can race us.
        # We require apply_status NOT IN ('in_progress', 'applied', 'unknown_submission',
        # 'submitted_unverified') AND applied_at IS NULL.
        cur = conn.execute("""
            UPDATE jobs
            SET apply_status = 'in_progress',
                agent_id = ?,
                apply_task_id = ?,
                last_attempted_at = ?
            WHERE url = ?
              AND applied_at IS NULL
              AND (
                  apply_status IS NULL
                  OR apply_status NOT IN ('in_progress', 'applied',
                                          'unknown_submission', 'submitted_unverified')
              )
        """, (agent_label, attempt_id, now, job_url))
        conn.commit()

        if cur.rowcount != 1:
            # Another worker claimed this job between our SELECT and UPDATE.
            _structured_log("warning", job_url, worker_id=worker_id,
                            status="claim_rejected", reason="lost_race")
            return None

        job = dict(row)
        job["attempt_id"] = attempt_id
        _structured_log("info", job_url,
                        attempt_id=attempt_id, worker_id=worker_id,
                        status="claimed")
        return job
    except Exception:
        conn.rollback()
        raise


def mark_result(url: str, status: str, error: str | None = None,
                permanent: bool = False, duration_ms: int | None = None,
                task_id: str | None = None,
                attempt_id: str | None = None) -> None:
    """Update a job's apply status in the database.

    Special status values:
      'applied'              — terminal success; sets applied_at.
      'unknown_submission'   — submit was clicked but verification ambiguous;
                               NOT retried by default.
      'submitted_unverified' — alias for unknown_submission.
      'failed'               — retryable (increments apply_attempts).
    """
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    tid = task_id or attempt_id
    if status == "applied":
        conn.execute("""
            UPDATE jobs SET apply_status = 'applied', applied_at = ?,
                           apply_error = NULL, agent_id = NULL,
                           apply_duration_ms = ?, apply_task_id = ?
            WHERE url = ?
        """, (now, duration_ms, tid, url))
        _structured_log("info", url, attempt_id=attempt_id, status="applied")
    elif status in ("unknown_submission", "submitted_unverified"):
        # Submit was attempted but we cannot verify; do NOT increment apply_attempts
        # so the job is NOT auto-retried as if nothing happened.
        conn.execute("""
            UPDATE jobs SET apply_status = 'unknown_submission',
                           apply_error = ?,
                           agent_id = NULL,
                           apply_duration_ms = ?, apply_task_id = ?
            WHERE url = ?
        """, (error or "submission_unverified", duration_ms, tid, url))
        _structured_log("warning", url, attempt_id=attempt_id,
                        status="unknown_submission",
                        reason=error or "verification_failed_after_submit")
    else:
        attempts = 99 if permanent else "COALESCE(apply_attempts, 0) + 1"
        conn.execute(f"""
            UPDATE jobs SET apply_status = ?, apply_error = ?,
                           apply_attempts = {attempts}, agent_id = NULL,
                           apply_duration_ms = ?, apply_task_id = ?
            WHERE url = ?
        """, (status, error or "unknown", duration_ms, tid, url))
        _structured_log("info", url, attempt_id=attempt_id, status=status,
                        reason=error or "")
    conn.commit()


def release_lock(url: str) -> None:
    """Release the in_progress lock without changing status."""
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET apply_status = NULL, agent_id = NULL WHERE url = ? AND apply_status = 'in_progress'",
        (url,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Utility modes (--gen, --mark-applied, --mark-failed, --reset-failed)
# ---------------------------------------------------------------------------

def gen_prompt(target_url: str, min_score: int = 7,
               model: str = "sonnet", worker_id: int = 0) -> Path | None:
    """Generate a prompt file and print the Claude CLI command for manual debugging.

    Returns:
        Path to the generated prompt file, or None if no job found.
    """
    job = acquire_job(target_url=target_url, min_score=min_score, worker_id=worker_id)
    if not job:
        return None

    # Read resume text
    resume_path = job.get("tailored_resume_path")
    if not resume_path or not Path(resume_path).exists():
        if config.RESUME_PATH.exists():
            resume_path = str(config.RESUME_PATH)
            job["tailored_resume_path"] = resume_path

    txt_path = Path(resume_path).with_suffix(".txt") if resume_path else None
    resume_text = ""
    if txt_path and txt_path.exists() and txt_path.stat().st_size > 0:
        resume_text = txt_path.read_text(encoding="utf-8")
    elif config.RESUME_PATH.exists():
        resume_text = config.RESUME_PATH.read_text(encoding="utf-8")

    prompt = prompt_mod.build_prompt(job=job, tailored_resume=resume_text)

    # Release the lock so the job stays available
    release_lock(job["url"])

    # Write prompt file
    config.ensure_dirs()
    site_slug = re.sub(r"[^\w\s-]", "", job.get("site") or "unknown")[:20].strip().replace(" ", "_")
    title_slug = re.sub(r"[^\w\s-]", "", job.get("title") or "job")[:30].strip().replace(" ", "_")
    prompt_file = config.LOG_DIR / f"prompt_{site_slug}_{title_slug}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    # Write MCP config for reference
    port = BASE_CDP_PORT + worker_id
    mcp_path = config.APP_DIR / f".mcp-apply-{worker_id}.json"
    mcp_path.write_text(json.dumps(_make_mcp_config(port)), encoding="utf-8")

    return prompt_file


def mark_job(url: str, status: str, reason: str | None = None) -> None:
    """Manually mark a job's apply status in the database.

    Args:
        url: Job URL to mark.
        status: Either 'applied' or 'failed'.
        reason: Failure reason (only for status='failed').
    """
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    if status == "applied":
        conn.execute("""
            UPDATE jobs SET apply_status = 'applied', applied_at = ?,
                           apply_error = NULL, agent_id = NULL
            WHERE url = ?
        """, (now, url))
    else:
        conn.execute("""
            UPDATE jobs SET apply_status = 'failed', apply_error = ?,
                           apply_attempts = 99, agent_id = NULL
            WHERE url = ?
        """, (reason or "manual", url))
    conn.commit()


def reset_failed() -> int:
    """Reset all failed jobs so they can be retried.

    Returns:
        Number of jobs reset.
    """
    conn = get_connection()
    cursor = conn.execute("""
        UPDATE jobs SET apply_status = NULL, apply_error = NULL,
                       apply_attempts = 0, agent_id = NULL
        WHERE apply_status = 'failed'
          OR (apply_status IS NOT NULL AND apply_status != 'applied'
              AND apply_status != 'in_progress')
    """)
    conn.commit()
    return cursor.rowcount


# ---------------------------------------------------------------------------
# Per-job execution
# ---------------------------------------------------------------------------

def run_job(job: dict, port: int, worker_id: int = 0,
            model: str = "sonnet", dry_run: bool = False) -> tuple[str, int]:
    """Execute an application session for one job using the configured AI provider.

    Returns:
        Tuple of (status_string, duration_ms). Status is one of:
        'applied', 'expired', 'captcha', 'login_issue',
        'failed:reason', or 'skipped'.
    """
    provider = get_provider()
    return provider.run(job=job, port=port, worker_id=worker_id, model=model, dry_run=dry_run)



# ---------------------------------------------------------------------------
# Permanent failure classification
# ---------------------------------------------------------------------------

PERMANENT_FAILURES: set[str] = {
    "expired", "captcha", "login_issue",
    "not_eligible_location", "not_eligible_salary",
    "already_applied", "account_required",
    "not_a_job_application", "unsafe_permissions",
    "unsafe_verification", "sso_required",
    "site_blocked", "cloudflare_blocked", "blocked_by_cloudflare",
    "quota_exceeded", "auth_error", "invalid_api_key", "model_not_found",
}

PERMANENT_PREFIXES: tuple[str, ...] = ("site_blocked", "cloudflare", "blocked_by")


def _is_permanent_failure(result: str) -> bool:
    """Determine if a failure should never be retried."""
    reason = result.split(":", 1)[-1] if ":" in result else result
    return (
        result in PERMANENT_FAILURES
        or reason in PERMANENT_FAILURES
        or any(reason.startswith(p) for p in PERMANENT_PREFIXES)
        or "quota" in reason.lower()
    )


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

def worker_loop(worker_id: int = 0, limit: int = 1,
                target_url: str | None = None,
                min_score: int = 7, headless: bool = False,
                model: str = "sonnet", dry_run: bool = False) -> tuple[int, int]:
    """Run jobs sequentially until limit is reached or queue is empty.

    Args:
        worker_id: Numeric worker identifier.
        limit: Max jobs to process (0 = continuous).
        target_url: Apply to a specific URL.
        min_score: Minimum fit_score threshold.
        headless: Run Chrome headless.
        model: Claude model name.
        dry_run: Don't click Submit.

    Returns:
        Tuple of (applied_count, failed_count).
    """
    applied = 0
    failed = 0
    continuous = limit == 0
    jobs_done = 0
    empty_polls = 0
    port = BASE_CDP_PORT + worker_id

    while not _stop_event.is_set():
        if not continuous and jobs_done >= limit:
            break

        update_state(worker_id, status="idle", job_title="", company="",
                     last_action="waiting for job", actions=0)

        job = acquire_job(target_url=target_url, min_score=min_score,
                          worker_id=worker_id)
        if not job:
            if not continuous:
                add_event(f"[W{worker_id}] Queue empty")
                update_state(worker_id, status="done", last_action="queue empty")
                break
            # If targeting a specific URL and claim failed, stop immediately
            if target_url:
                add_event(f"[W{worker_id}] Target already claimed/applied, stopping")
                update_state(worker_id, status="done", last_action="target unavailable")
                break
            empty_polls += 1
            update_state(worker_id, status="idle",
                         last_action=f"polling ({empty_polls})")
            if empty_polls == 1:
                add_event(f"[W{worker_id}] Queue empty, polling every {POLL_INTERVAL}s...")
            # Use Event.wait for interruptible sleep
            if _stop_event.wait(timeout=POLL_INTERVAL):
                break  # Stop was requested during wait
            continue

        empty_polls = 0

        chrome_proc = None
        try:
            add_event(f"[W{worker_id}] Launching Chrome...")
            chrome_proc = launch_chrome(worker_id, port=port, headless=headless)

            attempt_id = job.get("attempt_id", "")

            from applypilot.apply.providers import get_active_provider_name
            provider_name = get_active_provider_name()
            _structured_log("info", job["url"],
                            attempt_id=attempt_id, worker_id=worker_id,
                            provider=provider_name, status="starting")

            result, duration_ms = run_job(job, port=port, worker_id=worker_id,
                                            model=model, dry_run=dry_run)

            if result == "skipped":
                release_lock(job["url"])
                add_event(f"[W{worker_id}] Skipped: {job['title'][:30]}")
                continue
            elif result == "applied":
                mark_result(job["url"], "applied", duration_ms=duration_ms,
                            attempt_id=attempt_id)
                applied += 1
                update_state(worker_id, jobs_applied=applied,
                             jobs_done=applied + failed)
                _structured_log("info", job["url"],
                                attempt_id=attempt_id, status="applied")
            elif result in ("unknown_submission", "submitted_unverified") or \
                    "unverified_submission" in result or "submitted_unverified" in result:
                # Submit was clicked but verification failed — use safe unknown_submission state.
                # Do NOT increment apply_attempts; this is NOT retryable automatically.
                err_snippet = result.split(":", 1)[-1] if ":" in result else result
                mark_result(job["url"], "unknown_submission",
                            error=err_snippet[:120],
                            duration_ms=duration_ms,
                            attempt_id=attempt_id)
                failed += 1
                update_state(worker_id, jobs_failed=failed,
                             jobs_done=applied + failed)
                _structured_log("warning", job["url"],
                                attempt_id=attempt_id,
                                status="unknown_submission",
                                reason="verification_failed_after_submit")
            else:
                reason = result.split(":", 1)[-1] if ":" in result else result
                mark_result(job["url"], "failed", reason,
                            permanent=_is_permanent_failure(result),
                            duration_ms=duration_ms,
                            attempt_id=attempt_id)
                failed += 1
                update_state(worker_id, jobs_failed=failed,
                             jobs_done=applied + failed)

                # Halt batch loop on fatal AI provider failures (e.g. quota exhausted or invalid auth)
                # to prevent launching Chrome and hammering provider for all remaining jobs in queue
                if reason in ("quota_exceeded", "auth_error", "invalid_api_key", "model_not_found") or "quota" in reason.lower():
                    logger.error("Halting worker %d: Fatal AI provider error (%s). Halting queue.", worker_id, reason)
                    add_event(f"[W{worker_id}] Auto-apply halted: {reason.replace('_', ' ').title()}")
                    break

        except KeyboardInterrupt:
            release_lock(job["url"])
            if _stop_event.is_set():
                break
            add_event(f"[W{worker_id}] Job skipped (Ctrl+C)")
            continue
        except Exception as e:
            logger.exception("Worker %d launcher error", worker_id)
            add_event(f"[W{worker_id}] Launcher error: {str(e)[:40]}")
            mark_result(job["url"], "failed", error=str(e)[:100], permanent=False)
            failed += 1
            update_state(worker_id, jobs_failed=failed)
        finally:
            if chrome_proc:
                cleanup_worker(worker_id, chrome_proc)

        jobs_done += 1
        if target_url:
            break

    update_state(worker_id, status="done", last_action="finished")
    return applied, failed


# ---------------------------------------------------------------------------
# Main entry point (called from cli.py)
# ---------------------------------------------------------------------------

def main(limit: int = 1, target_url: str | None = None,
         min_score: int = 7, headless: bool = False, model: str = "sonnet",
         dry_run: bool = False, continuous: bool = False,
         poll_interval: int = 60, workers: int = 1) -> None:
    """Launch the apply pipeline.

    Args:
        limit: Max jobs to apply to (0 or with continuous=True means run forever).
        target_url: Apply to a specific URL.
        min_score: Minimum fit_score threshold.
        headless: Run Chrome in headless mode.
        model: Claude model name.
        dry_run: Don't click Submit.
        continuous: Run forever, polling for new jobs.
        poll_interval: Seconds between DB polls when queue is empty.
        workers: Number of parallel workers (default 1).
    """
    global POLL_INTERVAL
    POLL_INTERVAL = poll_interval
    _stop_event.clear()

    config.ensure_dirs()
    console = Console()

    if continuous:
        effective_limit = 0
        mode_label = "continuous"
    else:
        effective_limit = limit
        mode_label = f"{limit} jobs"

    # Initialize dashboard for all workers
    for i in range(workers):
        init_worker(i)

    worker_label = f"{workers} worker{'s' if workers > 1 else ''}"
    console.print(f"Launching apply pipeline ({mode_label}, {worker_label}, poll every {POLL_INTERVAL}s)...")
    console.print("[dim]Ctrl+C = skip current job(s) | Ctrl+C x2 = stop[/dim]")

    # Double Ctrl+C handler
    _ctrl_c_count = 0

    def _sigint_handler(sig, frame):
        nonlocal _ctrl_c_count
        _ctrl_c_count += 1
        if _ctrl_c_count == 1:
            console.print("\n[yellow]Skipping current job(s)... (Ctrl+C again to STOP)[/yellow]")
            # Stop all active provider processes/threads
            try:
                prov = get_provider()
                for wid in range(workers):
                    prov.stop(wid)
            except Exception:
                pass
            with _claude_lock:
                for wid, cproc in list(_claude_procs.items()):
                    if cproc.poll() is None:
                        _kill_process_tree(cproc.pid)
        else:
            console.print("\n[red bold]STOPPING[/red bold]")
            _stop_event.set()
            try:
                prov = get_provider()
                for wid in range(workers):
                    prov.stop(wid)
            except Exception:
                pass
            with _claude_lock:
                for wid, cproc in list(_claude_procs.items()):
                    if cproc.poll() is None:
                        _kill_process_tree(cproc.pid)
            kill_all_chrome()
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _sigint_handler)

    try:
        with Live(render_full(), console=console, refresh_per_second=2) as live:
            # Daemon thread for display refresh only (no business logic)
            _dashboard_running = True

            def _refresh():
                while _dashboard_running:
                    live.update(render_full())
                    time.sleep(0.5)

            refresh_thread = threading.Thread(target=_refresh, daemon=True)
            refresh_thread.start()

            if workers == 1:
                # Single worker — run directly in main thread
                total_applied, total_failed = worker_loop(
                    worker_id=0,
                    limit=effective_limit,
                    target_url=target_url,
                    min_score=min_score,
                    headless=headless,
                    model=model,
                    dry_run=dry_run,
                )
            else:
                # Multi-worker — distribute limit across workers
                if effective_limit:
                    base = effective_limit // workers
                    extra = effective_limit % workers
                    limits = [base + (1 if i < extra else 0)
                              for i in range(workers)]
                else:
                    limits = [0] * workers  # continuous mode

                with ThreadPoolExecutor(max_workers=workers,
                                        thread_name_prefix="apply-worker") as executor:
                    futures = {
                        executor.submit(
                            worker_loop,
                            worker_id=i,
                            limit=limits[i],
                            target_url=target_url,
                            min_score=min_score,
                            headless=headless,
                            model=model,
                            dry_run=dry_run,
                        ): i
                        for i in range(workers)
                    }

                    results: list[tuple[int, int]] = []
                    for future in as_completed(futures):
                        wid = futures[future]
                        try:
                            results.append(future.result())
                        except Exception:
                            logger.exception("Worker %d crashed", wid)
                            results.append((0, 0))

                total_applied = sum(r[0] for r in results)
                total_failed = sum(r[1] for r in results)

            _dashboard_running = False
            refresh_thread.join(timeout=2)
            live.update(render_full())

        totals = get_totals()
        console.print(
            f"\n[bold]Done: {total_applied} applied, {total_failed} failed "
            f"(${totals['cost']:.3f})[/bold]"
        )
        console.print(f"Logs: {config.LOG_DIR}")

    except KeyboardInterrupt:
        pass
    finally:
        _stop_event.set()
        kill_all_chrome()
