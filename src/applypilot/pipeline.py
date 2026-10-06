"""ApplyPilot Pipeline Orchestrator.

Runs pipeline stages in sequence or concurrently (streaming mode).

Usage (via CLI):
    applypilot run                        # all stages, sequential
    applypilot run --stream               # all stages, concurrent
    applypilot run discover enrich        # specific stages
    applypilot run score tailor cover     # LLM-only stages
    applypilot run --dry-run              # preview without executing
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from applypilot.config import load_env, ensure_dirs
from applypilot.database import init_db, get_connection, get_stats

log = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

STAGE_ORDER = ("discover", "enrich", "score", "tailor", "cover", "pdf", "apply")

STAGE_META: dict[str, dict] = {
    "discover": {"desc": "Job discovery (JobSpy + Workday + smart extract)"},
    "enrich":   {"desc": "Detail enrichment (full descriptions + apply URLs)"},
    "score":    {"desc": "LLM scoring (fit 1-10)"},
    "tailor":   {"desc": "Resume tailoring (LLM + validation)"},
    "cover":    {"desc": "Cover letter generation"},
    "pdf":      {"desc": "PDF conversion (tailored resumes + cover letters)"},
    "apply":    {"desc": "Autonomous application submission & live verification"},
}

# Upstream dependency: a stage only finishes when its upstream is done AND
# it has no remaining pending work.
_UPSTREAM: dict[str, str | None] = {
    "discover": None,
    "enrich":   "discover",
    "score":    "enrich",
    "tailor":   "score",
    "cover":    "tailor",
    "pdf":      "cover",
    "apply":    "pdf",
}


# ---------------------------------------------------------------------------
# Individual stage runners
# ---------------------------------------------------------------------------

def _run_discover(workers: int = 1) -> dict:
    """Stage: Job discovery — JobSpy, Workday, and smart-extract scrapers."""
    stats: dict = {"jobspy": None, "workday": None, "smartextract": None}

    # JobSpy
    console.print("  [cyan]JobSpy full crawl...[/cyan]")
    try:
        from applypilot.discovery.jobspy import run_discovery
        run_discovery()
        stats["jobspy"] = "ok"
    except Exception as e:
        log.error("JobSpy crawl failed: %s", e)
        console.print(f"  [red]JobSpy error:[/red] {e}")
        stats["jobspy"] = f"error: {e}"

    # Workday corporate scraper
    console.print("  [cyan]Workday corporate scraper...[/cyan]")
    try:
        from applypilot.discovery.workday import run_workday_discovery
        run_workday_discovery(workers=workers)
        stats["workday"] = "ok"
    except Exception as e:
        log.error("Workday scraper failed: %s", e)
        console.print(f"  [red]Workday error:[/red] {e}")
        stats["workday"] = f"error: {e}"

    # Smart extract
    console.print("  [cyan]Smart extract (AI-powered scraping)...[/cyan]")
    try:
        from applypilot.discovery.smartextract import run_smart_extract
        run_smart_extract(workers=workers)
        stats["smartextract"] = "ok"
    except Exception as e:
        log.error("Smart extract failed: %s", e)
        console.print(f"  [red]Smart extract error:[/red] {e}")
        stats["smartextract"] = f"error: {e}"

    return stats


def _run_enrich(workers: int = 1) -> dict:
    """Stage: Detail enrichment — scrape full descriptions and apply URLs."""
    try:
        from applypilot.enrichment.detail import run_enrichment
        run_enrichment(workers=workers)
        return {"status": "ok"}
    except Exception as e:
        log.error("Enrichment failed: %s", e)
        return {"status": f"error: {e}"}


def _run_score() -> dict:
    """Stage: LLM scoring — assign fit scores 1-10."""
    try:
        from applypilot.scoring.scorer import run_scoring
        run_scoring()
        return {"status": "ok"}
    except Exception as e:
        log.error("Scoring failed: %s", e)
        return {"status": f"error: {e}"}


def _run_tailor(min_score: int = 7, validation_mode: str = "normal") -> dict:
    """Stage: Resume tailoring — generate tailored resumes for high-fit jobs."""
    try:
        from applypilot.scoring.tailor import run_tailoring
        run_tailoring(min_score=min_score, validation_mode=validation_mode)
        return {"status": "ok"}
    except Exception as e:
        log.error("Tailoring failed: %s", e)
        return {"status": f"error: {e}"}


def _run_cover(min_score: int = 7, validation_mode: str = "normal") -> dict:
    """Stage: Cover letter generation."""
    try:
        from applypilot.scoring.cover_letter import run_cover_letters
        run_cover_letters(min_score=min_score, validation_mode=validation_mode)
        return {"status": "ok"}
    except Exception as e:
        log.error("Cover letter generation failed: %s", e)
        return {"status": f"error: {e}"}


def _run_pdf() -> dict:
    """Stage: PDF conversion — convert tailored resumes and cover letters to PDF."""
    try:
        from applypilot.scoring.pdf import batch_convert
        batch_convert()
        return {"status": "ok"}
    except Exception as e:
        log.error("PDF conversion failed: %s", e)
        return {"status": f"error: {e}"}


def _run_apply(limit: int = 0, min_score: int = 7, workers: int = 1, headless: bool = False) -> dict:
    """Stage: Autonomous apply — apply to ready jobs using configured AI provider."""
    try:
        from applypilot.apply.launcher import main as apply_main
        apply_main(
            limit=limit,
            min_score=min_score,
            headless=headless,
            workers=workers,
        )
        return {"status": "ok"}
    except Exception as e:
        log.error("Apply stage failed: %s", e)
        return {"status": f"error: {e}"}


# Map stage names to their runner functions
_STAGE_RUNNERS: dict[str, callable] = {
    "discover": _run_discover,
    "enrich":   _run_enrich,
    "score":    _run_score,
    "tailor":   _run_tailor,
    "cover":    _run_cover,
    "pdf":      _run_pdf,
    "apply":    _run_apply,
}


# ---------------------------------------------------------------------------
# Stage resolution
# ---------------------------------------------------------------------------

def _resolve_stages(stage_names: list[str]) -> list[str]:
    """Resolve 'all' and validate/order stage names."""
    if "all" in stage_names:
        return list(STAGE_ORDER)

    resolved = []
    for name in stage_names:
        if name not in STAGE_META:
            console.print(
                f"[red]Unknown stage:[/red] '{name}'. "
                f"Available: {', '.join(STAGE_ORDER)}, all"
            )
            raise SystemExit(1)
        if name not in resolved:
            resolved.append(name)

    # Maintain canonical order
    return [s for s in STAGE_ORDER if s in resolved]


# ---------------------------------------------------------------------------
# Streaming pipeline helpers
# ---------------------------------------------------------------------------

class _StageTracker:
    """Thread-safe tracker for which stages have finished producing work."""

    def __init__(self):
        self._events: dict[str, threading.Event] = {
            stage: threading.Event() for stage in STAGE_ORDER
        }
        self._results: dict[str, dict] = {}
        self._lock = threading.Lock()

    def mark_done(self, stage: str, result: dict | None = None) -> None:
        with self._lock:
            self._results[stage] = result or {"status": "ok"}
        self._events[stage].set()

    def is_done(self, stage: str) -> bool:
        return self._events[stage].is_set()

    def wait(self, stage: str, timeout: float | None = None) -> bool:
        return self._events[stage].wait(timeout=timeout)

    def get_results(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._results)


# SQL to count pending work for each stage
_PENDING_SQL: dict[str, str] = {
    "enrich": "SELECT COUNT(*) FROM jobs WHERE detail_scraped_at IS NULL",
    "score":  "SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL",
    "tailor": (
        "SELECT COUNT(*) FROM jobs WHERE fit_score >= ? "
        "AND full_description IS NOT NULL "
        "AND tailored_resume_path IS NULL "
        "AND COALESCE(tailor_attempts, 0) < 5"
    ),
    "cover": (
        "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL "
        "AND (cover_letter_path IS NULL OR cover_letter_path = '') "
        "AND COALESCE(cover_attempts, 0) < 5"
    ),
    "pdf": (
        "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL "
        "AND tailored_resume_path LIKE '%.txt'"
    ),
    "apply": (
        "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL "
        "AND (apply_status IS NULL OR apply_status = 'failed') "
        "AND (apply_attempts IS NULL OR apply_attempts < 3) "
        "AND fit_score >= ?"
    ),
}

# How long to sleep between polling loops in streaming mode (seconds)
_STREAM_POLL_INTERVAL = 10


def _count_pending(stage: str, min_score: int = 7) -> int:
    """Count pending work items for a stage."""
    sql = _PENDING_SQL.get(stage)
    if sql is None:
        return 0
    conn = get_connection()
    if "?" in sql:
        return conn.execute(sql, (min_score,)).fetchone()[0]
    return conn.execute(sql).fetchone()[0]


def _run_stage_streaming(
    stage: str,
    tracker: _StageTracker,
    stop_event: threading.Event,
    min_score: int = 7,
    workers: int = 1,
    validation_mode: str = "normal",
) -> None:
    """Run a single stage in streaming mode: loop until upstream done + no work.

    For discover: runs once, then marks done.
    For all others: polls DB for pending work, runs the batch processor,
    and repeats until upstream is done and no pending work remains.
    """
    runner = _STAGE_RUNNERS[stage]
    kwargs: dict = {}
    if stage in ("tailor", "cover"):
        kwargs["min_score"] = min_score
        kwargs["validation_mode"] = validation_mode
    if stage in ("discover", "enrich"):
        kwargs["workers"] = workers
    if stage == "apply":
        kwargs["min_score"] = min_score
        kwargs["workers"] = workers

    upstream = _UPSTREAM[stage]

    if stage == "discover":
        # Discover runs once (its sub-scrapers already do their full crawl)
        try:
            result = runner(**kwargs)
            tracker.mark_done(stage, result)
        except Exception as e:
            log.exception("Stage '%s' crashed", stage)
            tracker.mark_done(stage, {"status": f"error: {e}"})
        return

    # For downstream stages: loop until upstream done + no pending work
    passes = 0
    while not stop_event.is_set():
        # Wait for upstream to start producing work (first pass only)
        if passes == 0 and upstream and not tracker.is_done(upstream):
            # Wait a bit for upstream to produce some work before first run
            tracker.wait(upstream, timeout=_STREAM_POLL_INTERVAL)

        pending = _count_pending(stage, min_score)

        if pending > 0:
            try:
                runner(**kwargs)
                passes += 1
            except Exception as e:
                log.error("Stage '%s' error (pass %d): %s", stage, passes, e)
                passes += 1
        else:
            # No work right now
            upstream_done = upstream is None or tracker.is_done(upstream)
            if upstream_done:
                # No work and upstream is done — this stage is finished
                break
            # Upstream still running, wait and retry
            if stop_event.wait(timeout=_STREAM_POLL_INTERVAL):
                break  # Stop requested

    tracker.mark_done(stage, {"status": "ok", "passes": passes})


# ---------------------------------------------------------------------------
# Pipeline orchestrators
# ---------------------------------------------------------------------------

def _run_sequential(ordered: list[str], min_score: int, workers: int = 1,
                    validation_mode: str = "normal") -> dict:
    """Execute stages one at a time (original behavior)."""
    results: list[dict] = []
    errors: dict[str, str] = {}
    pipeline_start = time.time()

    for name in ordered:
        meta = STAGE_META[name]
        console.print(f"\n{'=' * 70}")
        console.print(f"  [bold]STAGE: {name}[/bold] — {meta['desc']}")
        console.print(f"  Started: {datetime.now().strftime('%H:%M:%S')}")
        console.print(f"{'=' * 70}")

        t0 = time.time()
        runner = _STAGE_RUNNERS[name]

        try:
            kwargs: dict = {}
            if name in ("tailor", "cover"):
                kwargs["min_score"] = min_score
                kwargs["validation_mode"] = validation_mode
            if name in ("discover", "enrich"):
                kwargs["workers"] = workers
            if name == "apply":
                kwargs["min_score"] = min_score
                kwargs["workers"] = workers
            result = runner(**kwargs)
            elapsed = time.time() - t0

            status = "ok"
            if isinstance(result, dict):
                status = result.get("status", "ok")
                if name == "discover":
                    sub_errors = [
                        f"{k}: {v}" for k, v in result.items()
                        if isinstance(v, str) and v.startswith("error")
                    ]
                    if sub_errors:
                        status = "partial"

        except Exception as e:
            elapsed = time.time() - t0
            status = f"error: {e}"
            log.exception("Stage '%s' crashed", name)
            console.print(f"\n  [red]STAGE FAILED:[/red] {e}")

        results.append({"stage": name, "status": status, "elapsed": elapsed})
        if status not in ("ok", "partial"):
            errors[name] = status

        console.print(f"\n  Stage '{name}' completed in {elapsed:.1f}s — {status}")

    total_elapsed = time.time() - pipeline_start
    return {"stages": results, "errors": errors, "elapsed": total_elapsed}


def _run_streaming(ordered: list[str], min_score: int, workers: int = 1,
                   validation_mode: str = "normal") -> dict:
    """Execute stages concurrently with DB as conveyor belt."""
    tracker = _StageTracker()
    stop_event = threading.Event()
    pipeline_start = time.time()

    console.print(f"\n  [bold cyan]STREAMING MODE[/bold cyan] — stages run concurrently")
    console.print(f"  Poll interval: {_STREAM_POLL_INTERVAL}s\n")

    # Mark stages NOT in `ordered` as done so downstream doesn't wait for them
    for stage in STAGE_ORDER:
        if stage not in ordered:
            tracker.mark_done(stage, {"status": "skipped"})

    # Launch each stage in its own thread
    threads: dict[str, threading.Thread] = {}
    start_times: dict[str, float] = {}

    for name in ordered:
        start_times[name] = time.time()
        t = threading.Thread(
            target=_run_stage_streaming,
            args=(name, tracker, stop_event, min_score, workers, validation_mode),
            name=f"stage-{name}",
            daemon=True,
        )
        threads[name] = t
        t.start()
        console.print(f"  [dim]Started thread:[/dim] {name}")

    # Wait for all threads to finish
    try:
        for name in ordered:
            threads[name].join()
            elapsed = time.time() - start_times[name]
            console.print(
                f"  [green]Completed:[/green] {name} ({elapsed:.1f}s)"
            )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted — stopping stages...[/yellow]")
        stop_event.set()
        for t in threads.values():
            t.join(timeout=10)

    total_elapsed = time.time() - pipeline_start

    # Build results from tracker
    all_results = tracker.get_results()
    results: list[dict] = []
    errors: dict[str, str] = {}

    for name in ordered:
        r = all_results.get(name, {"status": "unknown"})
        elapsed = time.time() - start_times.get(name, pipeline_start)
        status = r.get("status", "ok")

        results.append({"stage": name, "status": status, "elapsed": elapsed})
        if status not in ("ok", "partial", "skipped"):
            errors[name] = status

    return {"stages": results, "errors": errors, "elapsed": total_elapsed}


def run_pipeline(
    stages: list[str] | None = None,
    min_score: int = 7,
    dry_run: bool = False,
    stream: bool = False,
    workers: int = 1,
    validation_mode: str = "normal",
) -> dict:
    """Run pipeline stages.

    Args:
        stages: List of stage names, or None / ["all"] for full pipeline.
        min_score: Minimum fit score for tailor/cover stages.
        dry_run: If True, preview stages without executing.
        stream: If True, run stages concurrently (streaming mode).
        workers: Number of parallel threads for discovery/enrichment stages.

    Returns:
        Dict with keys: stages (list of result dicts), errors (dict), elapsed (float).
    """
    # Bootstrap
    load_env()
    ensure_dirs()
    init_db()

    # Resolve stages
    if stages is None:
        stages = ["all"]
    ordered = _resolve_stages(stages)

    # Banner
    mode = "streaming" if stream else "sequential"
    console.print()
    console.print(Panel.fit(
        f"[bold]ApplyPilot Pipeline[/bold] ({mode})",
        border_style="blue",
    ))
    console.print(f"  Min score:  {min_score}")
    console.print(f"  Workers:    {workers}")
    console.print(f"  Validation: {validation_mode}")
    console.print(f"  Stages:     {' -> '.join(ordered)}")

    # Pre-run stats
    pre_stats = get_stats()
    console.print(f"  DB:        {pre_stats['total']} jobs, {pre_stats['pending_detail']} pending enrichment")

    if dry_run:
        console.print(f"\n  [yellow]DRY RUN[/yellow] — would execute ({mode}):")
        for name in ordered:
            meta = STAGE_META[name]
            console.print(f"    {name:<12s}  {meta['desc']}")
        console.print(f"\n  No changes made.")
        return {"stages": [], "errors": {}, "elapsed": 0.0}

    # Execute
    if stream:
        result = _run_streaming(ordered, min_score, workers=workers,
                                validation_mode=validation_mode)
    else:
        result = _run_sequential(ordered, min_score, workers=workers,
                                 validation_mode=validation_mode)

    # Summary table
    console.print(f"\n{'=' * 70}")
    summary = Table(title="Pipeline Summary", show_header=True, header_style="bold")
    summary.add_column("Stage", style="bold")
    summary.add_column("Status")
    summary.add_column("Time", justify="right")

    for r in result["stages"]:
        elapsed_str = f"{r['elapsed']:.1f}s"
        status_display = r["status"][:30]
        if r["status"] == "ok":
            style = "green"
        elif r["status"] in ("partial", "skipped"):
            style = "yellow"
        else:
            style = "red"
        summary.add_row(r["stage"], f"[{style}]{status_display}[/{style}]", elapsed_str)

    summary.add_row("", "", "")
    summary.add_row("[bold]Total[/bold]", "", f"[bold]{result['elapsed']:.1f}s[/bold]")
    console.print(summary)

    # Final DB stats
    final = get_stats()
    console.print(f"\n  [bold]DB Final State:[/bold]")
    console.print(f"    Total jobs:     {final['total']}")
    console.print(f"    With desc:      {final['with_description']}")
    console.print(f"    Scored:         {final['scored']}")
    console.print(f"    Tailored:       {final['tailored']}")
    console.print(f"    Cover letters:  {final['with_cover_letter']}")
    console.print(f"    Ready to apply: {final['ready_to_apply']}")
    console.print(f"    Applied:        {final['applied']}")
    console.print(f"{'=' * 70}\n")

    return result


def run_single_job_pipeline(
    url: str,
    min_score: int = 0,
    validation_mode: str = "normal",
    force: bool = True,
) -> dict:
    """Run pipeline stages 2 (enrich), 3 (score), and 4 (tailor) specifically for one job row.

    Args:
        url: Job URL or application URL matching the target row.
        min_score: Minimum fit score threshold.
        validation_mode: "strict", "normal", or "lenient".
        force: If True, re-enriches and re-tailors even if previous data exists.

    Returns:
        Dict with canonical url, title, fit_score, tailored_resume_path, etc.
    """
    import json
    import re
    from datetime import timezone
    from pathlib import Path

    load_env()
    ensure_dirs()
    conn = get_connection()

    clean_url = url.split("?")[0].rstrip("/")
    like = f"%{clean_url}%" if clean_url else url
    row = conn.execute("""
        SELECT * FROM jobs
        WHERE url = ? OR application_url = ? OR application_url LIKE ? OR url LIKE ?
        LIMIT 1
    """, (url, url, like, like)).fetchone()

    if not row:
        row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
        if not row:
            raise ValueError(f"Job not found in database for URL: {url}")

    if hasattr(row, "keys"):
        job = dict(row)
    else:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE url = ?", (row[0],))
        cols = [col[0] for col in cursor.description]
        job = dict(zip(cols, row))
    canonical_url = job["url"]

    console.print(Panel.fit(
        f"[bold cyan]Single-Job Pipeline (Stages 2 -> 3 -> 4)[/bold cyan]\n"
        f"Job: [bold]{job.get('title', 'Unknown Role')}[/bold] at [bold]{job.get('site', 'Company')}[/bold]\n"
        f"URL: {canonical_url}",
        border_style="cyan",
    ))

    # ──────────────────────────────────────────────────────────────────────────
    # Stage 2: Detail Enrichment (Data enrichment)
    # ──────────────────────────────────────────────────────────────────────────
    console.print(f"\n[bold cyan]════════════════════════════════════════════════════════════════[/bold cyan]")
    console.print(f"[bold cyan]▶ [STAGE 2: Detail Enrichment][/bold cyan] Scraping job requirements & direct application URL...")
    console.print(f"[bold cyan]════════════════════════════════════════════════════════════════[/bold cyan]")

    from applypilot.enrichment.detail import resolve_url, scrape_detail_page, UA

    target_scrape_url = job.get("application_url") or job.get("url") or canonical_url
    resolved = resolve_url(target_scrape_url, job.get("site", ""))
    if resolved:
        target_scrape_url = resolved

    needs_scrape = force or not job.get("full_description") or len(str(job.get("full_description", "")).strip()) < 100
    scrape_success = False

    if needs_scrape:
        try:
            from playwright.sync_api import sync_playwright
            console.print("  [dim]Launching headless browser for detail extraction...[/dim]")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent=UA)
                page = context.new_page()
                result = scrape_detail_page(page, target_scrape_url)
                browser.close()

                if result.get("full_description") and len(result["full_description"].strip()) >= 50:
                    now = datetime.now(timezone.utc).isoformat()
                    app_url = result.get("application_url") or job.get("application_url") or target_scrape_url
                    conn.execute(
                        "UPDATE jobs SET full_description = ?, application_url = ?, detail_scraped_at = ?, detail_error = NULL WHERE url = ?",
                        (result["full_description"], app_url, now, canonical_url),
                    )
                    conn.commit()
                    job["full_description"] = result["full_description"]
                    job["application_url"] = app_url
                    scrape_success = True
                    console.print(f"  [bold green]✓ [STAGE 2][/bold green] Enriched full description ({len(result['full_description'])} characters)")
                    if app_url != target_scrape_url:
                        console.print(f"  [green]  Direct Apply URL: {app_url}[/green]")
                else:
                    console.print(f"  [yellow]! [STAGE 2] Scrape returned partial or empty description: {result.get('error', 'no content')}[/yellow]")
        except Exception as e:
            console.print(f"  [yellow]! [STAGE 2] Scrape attempt error: {e}[/yellow]")

    if not scrape_success:
        if job.get("full_description") and len(str(job["full_description"]).strip()) >= 50:
            console.print(f"  [green]✓ [STAGE 2][/green] Using existing enriched description ({len(job['full_description'])} characters)")
        elif job.get("description") and len(str(job["description"]).strip()) >= 30:
            desc = job["description"].strip()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE jobs SET full_description = ?, detail_scraped_at = ? WHERE url = ?", (desc, now, canonical_url))
            conn.commit()
            job["full_description"] = desc
            console.print(f"  [yellow]! [STAGE 2][/yellow] Using discovery description fallback ({len(desc)} characters)")
        else:
            fallback = f"{job.get('title', 'Role')} at {job.get('site', 'Company')} - Location: {job.get('location', 'Remote')}"
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE jobs SET full_description = ?, detail_scraped_at = ? WHERE url = ?", (fallback, now, canonical_url))
            conn.commit()
            job["full_description"] = fallback
            console.print(f"  [yellow]! [STAGE 2][/yellow] Using title/location metadata fallback")

    # ──────────────────────────────────────────────────────────────────────────
    # Stage 3: AI Match Scoring (AI match score)
    # ──────────────────────────────────────────────────────────────────────────
    console.print(f"\n[bold cyan]════════════════════════════════════════════════════════════════[/bold cyan]")
    console.print(f"[bold cyan]▶ [STAGE 3: AI Match Scoring][/bold cyan] Evaluating candidate profile match with LLM...")
    console.print(f"[bold cyan]════════════════════════════════════════════════════════════════[/bold cyan]")

    from applypilot.config import RESUME_PATH
    if not RESUME_PATH.exists():
        raise FileNotFoundError(f"Resume file not found at {RESUME_PATH}. Please provide a resume in profile first.")

    resume_text = RESUME_PATH.read_text(encoding="utf-8")

    if not force and job.get("fit_score") is not None:
        score = job["fit_score"]
        console.print(f"  [bold green]✓ [STAGE 3][/bold green] Using existing AI Match Score: [bold]{score}/10[/bold]")
    else:
        from applypilot.scoring.scorer import score_job
        score_data = score_job(resume_text, job)
        score = max(1, min(10, score_data.get("score", 0)))
        keywords = score_data.get("keywords", "")
        reasoning = score_data.get("reasoning", "")

        now = datetime.now(timezone.utc).isoformat()
        full_reasoning = f"{keywords}\n{reasoning}" if keywords else reasoning
        conn.execute(
            "UPDATE jobs SET fit_score = ?, score_reasoning = ?, scored_at = ? WHERE url = ?",
            (score, full_reasoning, now, canonical_url),
        )
        conn.commit()
        job["fit_score"] = score
        job["score_reasoning"] = full_reasoning
        console.print(f"  [bold green]✓ [STAGE 3][/bold green] AI Match Score: [bold]{score}/10[/bold]")
        if keywords:
            console.print(f"  [dim]Keywords: {keywords[:80]}[/dim]")
        if reasoning:
            console.print(f"  [dim]Reasoning: {reasoning[:120]}[/dim]")

    # ──────────────────────────────────────────────────────────────────────────
    # Stage 4: Resume Tailoring (Resume tailoring)
    # ──────────────────────────────────────────────────────────────────────────
    console.print(f"\n[bold cyan]════════════════════════════════════════════════════════════════[/bold cyan]")
    console.print(f"[bold cyan]▶ [STAGE 4: Resume Tailoring][/bold cyan] Crafting ATS-tailored resume & PDF...")
    console.print(f"[bold cyan]════════════════════════════════════════════════════════════════[/bold cyan]")

    from applypilot.config import TAILORED_DIR, load_profile
    from applypilot.scoring.tailor import tailor_resume
    from applypilot.scoring.pdf import convert_to_pdf

    profile = load_profile()
    TAILORED_DIR.mkdir(parents=True, exist_ok=True)

    existing_path = job.get("tailored_resume_path")
    is_custom = existing_path and "_custom" in str(existing_path).lower()

    if (not force or is_custom) and existing_path and Path(existing_path).exists():
        console.print(f"  [green]✓ [STAGE 4][/green] Preserving existing Tailored Resume: {Path(existing_path).name}")
        txt_path = Path(existing_path)
        try:
            pdf_path = convert_to_pdf(txt_path)
            console.print(f"  [green]✓ [STAGE 4][/green] PDF verified: {pdf_path.name}")
        except Exception as e:
            log.debug("PDF conversion for resume: %s", e)
    else:
        tailored_text, report = tailor_resume(
            resume_text, job, profile, validation_mode=validation_mode
        )

        safe_title = re.sub(r"[^\w\s-]", "", job.get("title", "Role"))[:50].strip().replace(" ", "_")
        safe_site = re.sub(r"[^\w\s-]", "", job.get("site", "Company"))[:20].strip().replace(" ", "_")
        prefix = f"{safe_site}_{safe_title}"

        txt_path = TAILORED_DIR / f"{prefix}.txt"
        txt_path.write_text(tailored_text, encoding="utf-8")

        job_path = TAILORED_DIR / f"{prefix}_JOB.txt"
        job_desc = (
            f"Title: {job.get('title')}\n"
            f"Company: {job.get('site')}\n"
            f"Location: {job.get('location', 'N/A')}\n"
            f"Score: {job.get('fit_score', 'N/A')}\n"
            f"URL: {canonical_url}\n\n"
            f"{job.get('full_description', '')}"
        )
        job_path.write_text(job_desc, encoding="utf-8")

        report_path = TAILORED_DIR / f"{prefix}_REPORT.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        pdf_path = None
        try:
            pdf_path = convert_to_pdf(txt_path)
        except Exception as e:
            log.warning("PDF conversion for %s: %s", txt_path, e)

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE jobs SET tailored_resume_path = ?, tailored_at = ?, tailor_attempts = COALESCE(tailor_attempts, 0) + 1 WHERE url = ?",
            (str(txt_path), now, canonical_url),
        )
        conn.commit()
        job["tailored_resume_path"] = str(txt_path)
        job["tailored_at"] = now
        console.print(f"  [bold green]✓ [STAGE 4][/bold green] Resume tailored successfully: [bold]{txt_path.name}[/bold]")
        if pdf_path:
            console.print(f"  [green]  PDF compiled: {pdf_path.name}[/green]")

    console.print(f"\n[bold green]════════════════════════════════════════════════════════════════[/bold green]")
    console.print(f"[bold green]✓ Stages 2 (Enrichment), 3 (AI Score), and 4 (Tailoring) Ready![/bold green]")
    console.print(f"[bold cyan]Proceeding to Stage 5: Autonomous Apply...[/bold cyan]")
    console.print(f"[bold green]════════════════════════════════════════════════════════════════[/bold green]\n")

    return job
