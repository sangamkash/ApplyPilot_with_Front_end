"""Claude Code AI Provider for autonomous job applications.

Uses Claude Code CLI with Playwright MCP to automate Chrome,
while supporting ANTHROPIC_API_KEY and CLAUDE_MODEL environment variables,
and strictly verifying submission evidence before marking APPLIED.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from applypilot import config
from applypilot.apply import prompt as prompt_mod
from applypilot.apply.chrome import reset_worker_dir, _kill_process_tree
from applypilot.apply.dashboard import update_state, add_event, get_state
from applypilot.apply.providers.base import AIProvider
from applypilot.apply.providers.verification import verify_submission_on_port

logger = logging.getLogger(__name__)

# Active Claude processes for cancellation / stop handling
_claude_procs: dict[int, subprocess.Popen] = {}
_claude_lock = threading.Lock()


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


def _spawn_claude_process(cmd: list[str], env: dict, cwd: Path) -> subprocess.Popen:
    """Helper to spawn Claude CLI subprocess."""
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(cwd),
    )


class ClaudeProvider(AIProvider):
    """Claude Code CLI AI Provider."""

    def __init__(self) -> None:
        super().__init__(name="claude")

    def validate_environment(self) -> None:
        """Validate that claude CLI executable or ANTHROPIC_API_KEY is present."""
        if not shutil.which("claude") and not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "Claude Code CLI is not installed and ANTHROPIC_API_KEY is not set.\n"
                "Install from https://claude.ai/code or set ANTHROPIC_API_KEY in ~/.applypilot/.env"
            )

    def stop(self, worker_id: int) -> None:
        """Terminate the active Claude process for this worker."""
        with _claude_lock:
            proc = _claude_procs.pop(worker_id, None)
            if proc and proc.poll() is None:
                _kill_process_tree(proc.pid)

    def run(
        self,
        job: dict,
        port: int,
        worker_id: int = 0,
        model: Optional[str] = None,
        dry_run: bool = False,
    ) -> tuple[str, int]:
        """Spawn a Claude Code session for one job application."""
        start = time.time()
        self.validate_environment()

        # Resolve model name: CLAUDE_MODEL env var takes precedence
        effective_model = os.environ.get("CLAUDE_MODEL") or model or "sonnet"

        # Read tailored resume text
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

        # Build prompt
        agent_prompt = prompt_mod.build_prompt(
            job=job,
            tailored_resume=resume_text,
            dry_run=dry_run,
        )

        # Write per-worker MCP config
        mcp_config_path = config.APP_DIR / f".mcp-apply-{worker_id}.json"
        mcp_config_path.write_text(json.dumps(_make_mcp_config(port)), encoding="utf-8")

        # Build claude command
        cmd = [
            "claude",
            "--model", effective_model,
            "-p",
            "--mcp-config", str(mcp_config_path),
            "--permission-mode", "bypassPermissions",
            "--no-session-persistence",
            "--disallowedTools", (
                "mcp__gmail__draft_email,mcp__gmail__modify_email,"
                "mcp__gmail__delete_email,mcp__gmail__download_attachment,"
                "mcp__gmail__batch_modify_emails,mcp__gmail__batch_delete_emails,"
                "mcp__gmail__create_label,mcp__gmail__update_label,"
                "mcp__gmail__delete_label,mcp__gmail__get_or_create_label,"
                "mcp__gmail__list_email_labels,mcp__gmail__create_filter,"
                "mcp__gmail__list_filters,mcp__gmail__get_filter,"
                "mcp__gmail__delete_filter"
            ),
            "--output-format", "stream-json",
            "--verbose", "-",
        ]

        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        if "ANTHROPIC_API_KEY" in os.environ:
            env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]

        worker_dir = reset_worker_dir(worker_id)

        update_state(worker_id, status="applying", job_title=job["title"],
                     company=job.get("site", ""), score=job.get("fit_score", 0),
                     start_time=time.time(), actions=0, last_action="starting Claude Code")
        add_event(f"[W{worker_id}] Starting (Claude): {job['title'][:35]} @ {job.get('site', '')}")

        worker_log = config.LOG_DIR / f"worker-{worker_id}.log"
        ts_header = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_header = (
            f"\n{'=' * 60}\n"
            f"[{ts_header}] [Claude Provider: {effective_model}] {job['title']} @ {job.get('site', '')}\n"
            f"URL: {job.get('application_url') or job['url']}\n"
            f"Score: {job.get('fit_score', 'N/A')}/10\n"
            f"{'=' * 60}\n"
        )

        stats: dict = {}
        proc = None

        try:
            proc = _spawn_claude_process(cmd, env, worker_dir)
            with _claude_lock:
                _claude_procs[worker_id] = proc

            proc.stdin.write(agent_prompt)
            proc.stdin.close()

            text_parts: list[str] = []
            with open(worker_log, "a", encoding="utf-8") as lf:
                lf.write(log_header)

                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        msg_type = msg.get("type")
                        if msg_type == "assistant":
                            for block in msg.get("message", {}).get("content", []):
                                bt = block.get("type")
                                if bt == "text":
                                    text_parts.append(block["text"])
                                    lf.write(block["text"] + "\n")
                                elif bt == "tool_use":
                                    name = (
                                        block.get("name", "")
                                        .replace("mcp__playwright__", "")
                                        .replace("mcp__gmail__", "gmail:")
                                    )
                                    inp = block.get("input", {})
                                    if "url" in inp:
                                        desc = f"{name} {inp['url'][:60]}"
                                    elif "ref" in inp:
                                        desc = f"{name} {inp.get('element', inp.get('text', ''))}"[:50]
                                    elif "fields" in inp:
                                        desc = f"{name} ({len(inp['fields'])} fields)"
                                    elif "paths" in inp:
                                        desc = f"{name} upload"
                                    else:
                                        desc = name

                                    lf.write(f"  >> {desc}\n")
                                    ws = get_state(worker_id)
                                    cur_actions = ws.actions if ws else 0
                                    update_state(worker_id,
                                                 actions=cur_actions + 1,
                                                 last_action=desc[:35])
                        elif msg_type == "result":
                            stats = {
                                "input_tokens": msg.get("usage", {}).get("input_tokens", 0),
                                "output_tokens": msg.get("usage", {}).get("output_tokens", 0),
                                "cost_usd": msg.get("total_cost_usd", 0),
                            }
                            text_parts.append(msg.get("result", ""))
                    except json.JSONDecodeError:
                        text_parts.append(line)
                        lf.write(line + "\n")

            proc.wait(timeout=300)
            returncode = proc.returncode
            proc = None

            if returncode and returncode < 0:
                return "skipped", int((time.time() - start) * 1000)

            output = "\n".join(text_parts)
            elapsed = int(time.time() - start)
            duration_ms = int((time.time() - start) * 1000)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            job_log = config.LOG_DIR / f"claude_{ts}_w{worker_id}_{job.get('site', 'unknown')[:20]}.txt"
            job_log.write_text(output, encoding="utf-8")

            if stats:
                cost = stats.get("cost_usd", 0)
                ws = get_state(worker_id)
                prev_cost = ws.total_cost if ws else 0.0
                update_state(worker_id, total_cost=prev_cost + cost)

            def _clean_reason(s: str) -> str:
                return re.sub(r'[*`"]+$', '', s).strip()

            # Critical Requirement 5: Never set APPLIED merely because Claude returned RESULT:APPLIED.
            # Perform strong submission verification on the live Chrome instance!
            if "RESULT:APPLIED" in output:
                if dry_run:
                    add_event(f"[W{worker_id}] APPLIED (dry run, {elapsed}s)")
                    update_state(worker_id, status="applied", last_action=f"APPLIED (dry run, {elapsed}s)")
                    return "applied", duration_ms

                is_verified, reason = verify_submission_on_port(port)
                if is_verified:
                    add_event(f"[W{worker_id}] APPLIED & VERIFIED ({elapsed}s): {job['title'][:25]}")
                    update_state(worker_id, status="applied", last_action=f"VERIFIED ({elapsed}s)")
                    return "applied", duration_ms
                else:
                    add_event(f"[W{worker_id}] SUBMISSION UNVERIFIED ({elapsed}s): {reason[:30]}")
                    update_state(worker_id, status="failed", last_action=f"UNVERIFIED: {reason[:25]}")
                    return f"failed:unverified_submission ({reason[:60]})", duration_ms

            for result_status in ["EXPIRED", "CAPTCHA", "LOGIN_ISSUE"]:
                if f"RESULT:{result_status}" in output:
                    add_event(f"[W{worker_id}] {result_status} ({elapsed}s): {job['title'][:30]}")
                    update_state(worker_id, status=result_status.lower(),
                                 last_action=f"{result_status} ({elapsed}s)")
                    return result_status.lower(), duration_ms

            if "RESULT:FAILED" in output:
                for out_line in output.split("\n"):
                    if "RESULT:FAILED" in out_line:
                        reason = (
                            out_line.split("RESULT:FAILED:")[-1].strip()
                            if ":" in out_line[out_line.index("FAILED") + 6:]
                            else "unknown"
                        )
                        reason = _clean_reason(reason)
                        PROMOTE_TO_STATUS = {"captcha", "expired", "login_issue"}
                        if reason in PROMOTE_TO_STATUS:
                            add_event(f"[W{worker_id}] {reason.upper()} ({elapsed}s): {job['title'][:30]}")
                            update_state(worker_id, status=reason,
                                         last_action=f"{reason.upper()} ({elapsed}s)")
                            return reason, duration_ms
                        add_event(f"[W{worker_id}] FAILED ({elapsed}s): {reason[:30]}")
                        update_state(worker_id, status="failed",
                                     last_action=f"FAILED: {reason[:25]}")
                        return f"failed:{reason}", duration_ms
                return "failed:unknown", duration_ms

            add_event(f"[W{worker_id}] NO RESULT ({elapsed}s)")
            update_state(worker_id, status="failed", last_action=f"no result ({elapsed}s)")
            return "failed:no_result_line", duration_ms

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            elapsed = int(time.time() - start)
            add_event(f"[W{worker_id}] TIMEOUT ({elapsed}s)")
            update_state(worker_id, status="failed", last_action=f"TIMEOUT ({elapsed}s)")
            return "failed:timeout", duration_ms
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            add_event(f"[W{worker_id}] ERROR: {str(e)[:40]}")
            update_state(worker_id, status="failed", last_action=f"ERROR: {str(e)[:25]}")
            return f"failed:{str(e)[:100]}", duration_ms
        finally:
            with _claude_lock:
                _claude_procs.pop(worker_id, None)
            if proc is not None and proc.poll() is None:
                _kill_process_tree(proc.pid)
