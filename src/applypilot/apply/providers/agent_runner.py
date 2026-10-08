"""Autonomous Browser Agent Runner for OpenAI-compatible APIs (Gemini and OpenAI).

Executes a ReAct loop:
1. Formulates the prompt with candidate profile and job details.
2. Interacts with Chrome via BrowserController.
3. Invokes tool calling on the LLM (navigate, snapshot, fill fields, upload resume, submit).
4. Strictly verifies real submission evidence before returning APPLIED.
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import httpx

from applypilot import config
from applypilot.apply import prompt as prompt_mod
from applypilot.apply.dashboard import add_event, get_state, update_state
from applypilot.apply.providers.browser_controller import BrowserController

logger = logging.getLogger(__name__)

# Standard function calling tools exposed to LLMs
BROWSER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Navigate Chrome to a specific job portal URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to navigate to"}
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_snapshot",
            "description": "Inspect the current page to retrieve visible text, form fields, and buttons.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill_form",
            "description": "Autofill application form fields (name, email, phone, address, salary, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "array",
                        "description": "List of field mappings to fill.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "Field label text or placeholder"},
                                "value": {"type": "string", "description": "Value to enter into the field"},
                                "selector": {"type": "string", "description": "Optional CSS selector"},
                            },
                            "required": ["value"],
                        },
                    }
                },
                "required": ["fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_upload_resume",
            "description": "Upload the candidate's tailored resume PDF to file inputs on the page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resume_path": {"type": "string", "description": "Path to tailored resume PDF file"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_upload_cover_letter",
            "description": "Upload candidate's cover letter PDF if an upload field is present.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cover_letter_path": {"type": "string", "description": "Path to cover letter PDF"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click a button, tab, link, or radio button.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Button text or CSS selector to click"},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_select",
            "description": "Select an option from a dropdown / select menu.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector_or_label": {"type": "string", "description": "Label or selector of dropdown"},
                    "option_value": {"type": "string", "description": "Option value or visible text to select"},
                },
                "required": ["selector_or_label", "option_value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait",
            "description": "Pause execution to wait for network responses or animations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "number", "description": "Seconds to wait (default 2)"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_submit_application",
            "description": "Click the final Submit Application button and run verification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "submit_button_text": {
                        "type": "string",
                        "description": "Text or selector for submit button (e.g. 'Submit Application')",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_switch_tab",
            "description": "Switch focus to another open tab or window by tab index (0, 1..) or URL/title substring.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tab": {"type": "string", "description": "Tab index (e.g. '1') or URL/title keyword"},
                },
                "required": ["tab"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_finish",
            "description": "Conclude the application process with a final status code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["applied", "failed", "expired", "captcha", "login_issue"],
                        "description": "Final outcome status",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Explanation or failure reason",
                    },
                },
                "required": ["status"],
            },
        },
    },
]


def run_autonomous_browser_agent(
    provider_name: str,
    endpoint_url: str,
    api_key: str,
    model: str,
    job: dict,
    port: int,
    worker_id: int = 0,
    dry_run: bool = False,
    extra_headers: Optional[Dict[str, str]] = None,
    stop_check: Optional[Callable[[], bool]] = None,
    timeout: Optional[int] = None,
) -> Tuple[str, int]:
    """Execute an autonomous browser agent session using an OpenAI-compatible endpoint."""
    start_time = time.time()
    worker_log = config.LOG_DIR / f"worker-{worker_id}.log"

    # Resolve resume paths
    resume_path = job.get("tailored_resume_path")
    if not resume_path or not Path(resume_path).exists() or (Path(resume_path).exists() and Path(resume_path).stat().st_size == 0):
        if config.RESUME_PATH.exists() and config.RESUME_PATH.stat().st_size > 0:
            resume_path = str(config.RESUME_PATH)
            job["tailored_resume_path"] = resume_path

    txt_path = Path(resume_path).with_suffix(".txt") if resume_path else None
    resume_text = ""
    if txt_path and txt_path.exists() and txt_path.stat().st_size > 0:
        resume_text = txt_path.read_text(encoding="utf-8")
    elif config.RESUME_PATH.exists() and config.RESUME_PATH.stat().st_size > 0:
        resume_text = config.RESUME_PATH.read_text(encoding="utf-8")

    # Build prompt instructions
    full_prompt = prompt_mod.build_prompt(
        job=job,
        tailored_resume=resume_text,
        dry_run=dry_run,
    )

    # Derive PDF resume path
    src_pdf = Path(resume_path).with_suffix(".pdf").resolve() if resume_path else None
    if src_pdf and src_pdf.exists() and src_pdf.stat().st_size > 0:
        resolved_pdf_path = str(src_pdf)
    elif resume_path and Path(resume_path).exists() and Path(resume_path).stat().st_size > 0:
        try:
            from applypilot.scoring.pdf import convert_to_pdf
            c_pdf = convert_to_pdf(Path(resume_path))
            resolved_pdf_path = str(c_pdf)
        except Exception:
            resolved_pdf_path = str(config.APP_DIR / "resume.pdf")
    else:
        base_pdf = config.APP_DIR / "resume.pdf"
        if base_pdf.exists() and base_pdf.stat().st_size > 0:
            resolved_pdf_path = str(base_pdf)
        elif config.RESUME_PATH.exists() and config.RESUME_PATH.stat().st_size > 0:
            try:
                from applypilot.scoring.pdf import convert_to_pdf
                resolved_pdf_path = str(convert_to_pdf(config.RESUME_PATH))
            except Exception:
                resolved_pdf_path = str(base_pdf)
        else:
            resolved_pdf_path = str(base_pdf)

    # Log header
    ts_header = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_header = (
        f"\n{'=' * 60}\n"
        f"[{ts_header}] [{provider_name.upper()} Provider: {model}] {job['title']} @ {job.get('site', '')}\n"
        f"URL: {job.get('application_url') or job['url']}\n"
        f"Score: {job.get('fit_score', 'N/A')}/10\n"
        f"{'=' * 60}\n"
    )
    with open(worker_log, "a", encoding="utf-8") as lf:
        lf.write(log_header)

    update_state(
        worker_id,
        status="applying",
        job_title=job["title"],
        company=job.get("site", ""),
        score=job.get("fit_score", 0),
        start_time=time.time(),
        actions=0,
        last_action=f"starting {provider_name}",
    )
    add_event(f"[W{worker_id}] Starting ({provider_name}): {job['title'][:35]} @ {job.get('site', '')}")

    req_timeout = timeout or int(os.environ.get("AUTO_APPLY_TIMEOUT", "120"))
    client = httpx.Client(timeout=req_timeout)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)

    messages: List[dict] = [
        {"role": "system", "content": full_prompt},
        {
            "role": "user",
            "content": (
                f"Begin applying to this job now.\n"
                f"Job URL: {job.get('application_url') or job['url']}\n"
                f"Candidate Resume PDF: {resolved_pdf_path}\n"
                f"Dry run mode: {dry_run}\n"
                f"Step 1: Inspect the page, fill fields, upload resume, and submit."
            ),
        },
    ]

    action_count = 0
    final_status = "failed:unknown"
    submission_verified = False

    try:
        with BrowserController(port=port) as browser:
            # Auto navigate to start
            initial_url = job.get("application_url") or job["url"]
            browser.navigate(initial_url)
            action_count += 1
            update_state(worker_id, actions=action_count, last_action=f"navigate {initial_url[:30]}")

            # Supply initial snapshot directly to agent so it has immediate visibility
            init_snap = browser.get_snapshot()
            messages.append({
                "role": "user",
                "content": (
                    f"Initial Page Loaded:\n"
                    f"Title: {init_snap.get('title')}\n"
                    f"Current URL: {init_snap.get('url')}\n"
                    f"Open Tabs: {json.dumps(init_snap.get('open_tabs', []))}\n"
                    f"Detected Form Fields ({init_snap.get('fields_count')}): {json.dumps(init_snap.get('fields', []))}\n"
                    f"Buttons: {json.dumps(init_snap.get('buttons', []))}\n\n"
                    f"Proceed to fill form fields, upload resume ({resolved_pdf_path}), or click Apply if on a job listing page."
                ),
            })

            max_turns = 25
            for turn in range(max_turns):
                if stop_check and stop_check():
                    return "skipped", int((time.time() - start_time) * 1000)

                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": BROWSER_TOOLS,
                    "temperature": 0.1,
                }

                resp = None
                max_api_retries = 3
                retry_wait = 5.0
                for attempt in range(max_api_retries):
                    if stop_check and stop_check():
                        return "skipped", int((time.time() - start_time) * 1000)
                    try:
                        resp = client.post(endpoint_url, json=payload, headers=headers)
                    except httpx.HTTPError as net_err:
                        logger.warning(
                            "Provider %s network error (attempt %d/%d): %s",
                            provider_name, attempt + 1, max_api_retries, net_err,
                        )
                        if attempt < max_api_retries - 1:
                            time.sleep(retry_wait)
                            retry_wait *= 2
                            continue
                        return "failed:network_error", int((time.time() - start_time) * 1000)

                    if resp.status_code == 429:
                        body_lower = resp.text.lower()
                        is_quota_exhausted = any(k in body_lower for k in [
                            "quota exceeded", "resource_exhausted", "quota_limit_value",
                            "check google api quota"
                        ])
                        if is_quota_exhausted:
                            logger.error(
                                "Provider %s quota exhausted (HTTP 429 RESOURCE_EXHAUSTED). Aborting immediately without retry.",
                                provider_name,
                            )
                            add_event(f"[W{worker_id}] Quota Exceeded (429): API quota exhausted for {provider_name}")
                            return "failed:quota_exceeded", int((time.time() - start_time) * 1000)

                    if resp.status_code in (401, 403):
                        logger.error("Provider %s authentication error (HTTP %d): %s", provider_name, resp.status_code, resp.text[:150])
                        add_event(f"[W{worker_id}] Auth Error ({resp.status_code}): Check API key for {provider_name}")
                        return "failed:auth_error", int((time.time() - start_time) * 1000)

                    if resp.status_code in (429, 503) and attempt < max_api_retries - 1:
                        logger.warning(
                            "Provider %s rate-limited (HTTP %d, attempt %d/%d). Retrying in %.1fs...",
                            provider_name, resp.status_code, attempt + 1, max_api_retries, retry_wait,
                        )
                        add_event(f"[W{worker_id}] Rate-limited ({resp.status_code}), waiting {int(retry_wait)}s...")
                        time.sleep(retry_wait)
                        retry_wait *= 2
                        continue
                    break

                if not resp or resp.status_code != 200:
                    status_code = resp.status_code if resp else 0
                    resp_snippet = resp.text[:200] if resp else "no response"
                    err_msg = f"{provider_name} API returned {status_code}: {resp_snippet}"
                    logger.error(err_msg)
                    if status_code == 429 and any(w in resp_snippet.lower() for w in ["quota", "resource_exhausted"]):
                        add_event(f"[W{worker_id}] Quota Exceeded (429): Check Google API quota")
                        return "failed:quota_exceeded", int((time.time() - start_time) * 1000)
                    else:
                        add_event(f"[W{worker_id}] API Error: {err_msg[:40]}")
                    return f"failed:{provider_name}_api_error", int((time.time() - start_time) * 1000)

                data = resp.json()
                choice = data["choices"][0]
                msg = choice.get("message", {})
                messages.append(msg)

                tool_calls = msg.get("tool_calls", [])
                assistant_content = msg.get("content", "")
                assistant_reasoning = msg.get("reasoning", "")
                if assistant_reasoning:
                    with open(worker_log, "a", encoding="utf-8") as lf:
                        lf.write(f"[{provider_name} Reasoning] {assistant_reasoning}\n")
                if assistant_content:
                    with open(worker_log, "a", encoding="utf-8") as lf:
                        lf.write(f"[{provider_name}] {assistant_content}\n")

                if not tool_calls:
                    # Model stopped calling tools; check if completed or gave result line
                    upper_content = assistant_content.upper()
                    if "RESULT:APPLIED" in upper_content:
                        final_status = "applied"
                    elif "RESULT:EXPIRED" in upper_content:
                        final_status = "expired"
                    elif "RESULT:CAPTCHA" in upper_content:
                        final_status = "captcha"
                    elif "RESULT:LOGIN_ISSUE" in upper_content:
                        final_status = "login_issue"
                    else:
                        if submission_verified:
                            final_status = "applied"
                        else:
                            is_v, v_reason = browser.verify_submission()
                            if is_v:
                                submission_verified = True
                                final_status = "applied"
                            elif dry_run and any(w in assistant_content.lower() for w in ["submit", "applied", "completed", "finish"]):
                                final_status = "applied"
                    break

                for tc in tool_calls:
                    call_id = tc["id"]
                    func = tc.get("function", {})
                    fn_name = func.get("name", "")
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except Exception:
                        args = {}

                    action_count += 1
                    desc = f"{fn_name}"
                    if "url" in args:
                        desc = f"{fn_name} {args['url'][:30]}"
                    elif "target" in args:
                        desc = f"{fn_name} {args['target'][:30]}"
                    elif "fields" in args:
                        desc = f"{fn_name} ({len(args['fields'])} fields)"

                    with open(worker_log, "a", encoding="utf-8") as lf:
                        lf.write(f"  >> [{fn_name}] {json.dumps(args)}\n")

                    update_state(worker_id, actions=action_count, last_action=desc[:35])

                    tool_output = ""
                    # Execute tool call in BrowserController
                    try:
                        if fn_name == "browser_navigate":
                            tool_output = json.dumps(browser.navigate(args.get("url", "")))
                        elif fn_name == "browser_snapshot":
                            tool_output = json.dumps(browser.get_snapshot())
                        elif fn_name == "browser_fill_form":
                            res = browser.fill_form_fields(args.get("fields", []))
                            tool_output = json.dumps(res)
                        elif fn_name == "browser_upload_resume":
                            r_path = args.get("resume_path") or resolved_pdf_path
                            ok = browser.upload_file(r_path)
                            tool_output = json.dumps({"uploaded": ok, "file": r_path})
                        elif fn_name == "browser_upload_cover_letter":
                            cl_path = args.get("cover_letter_path", "")
                            ok = browser.upload_file(cl_path) if cl_path else False
                            tool_output = json.dumps({"uploaded": ok, "file": cl_path})
                        elif fn_name == "browser_click":
                            ok = browser.click_element(args.get("target", ""))
                            tool_output = json.dumps({"clicked": ok, "target": args.get("target", "")})
                        elif fn_name == "browser_select":
                            ok = browser.select_option(args.get("selector_or_label", ""), args.get("option_value", ""))
                            tool_output = json.dumps({"selected": ok})
                        elif fn_name == "browser_wait":
                            browser.wait(float(args.get("seconds", 2)))
                            tool_output = json.dumps({"waited": True})
                        elif fn_name == "browser_switch_tab":
                            tab_val = args.get("tab", "0")
                            try:
                                res = browser.switch_to_tab(int(tab_val))
                            except ValueError:
                                res = browser.switch_to_tab(str(tab_val))
                            tool_output = json.dumps(res)
                        elif fn_name == "browser_submit_application":
                            if dry_run:
                                tool_output = json.dumps({"dry_run": True, "note": "Submit skipped in dry run mode"})
                                final_status = "applied"
                            else:
                                sub_btn = args.get("submit_button_text") or "Submit"
                                clicked = browser.click_element(sub_btn)
                                browser.wait(4.0)
                                is_v, v_reason = browser.verify_submission()
                                if is_v:
                                    submission_verified = True
                                    final_status = "applied"
                                    tool_output = json.dumps({"submitted": clicked, "verified": True, "evidence": v_reason})
                                else:
                                    tool_output = json.dumps({"submitted": clicked, "verified": False, "evidence": v_reason})
                        elif fn_name == "browser_finish":
                            status_arg = args.get("status", "failed")
                            reason_arg = args.get("reason", "")
                            if status_arg == "applied":
                                if dry_run:
                                    final_status = "applied"
                                else:
                                    browser.wait(2.0)
                                    is_v, v_reason = browser.verify_submission()
                                    if is_v or submission_verified:
                                        submission_verified = True
                                        final_status = "applied"
                                    else:
                                        final_status = f"failed:unverified_submission ({v_reason})"
                            else:
                                final_status = f"{status_arg}:{reason_arg}" if reason_arg else status_arg
                            tool_output = json.dumps({"finished": True, "status": final_status})
                        else:
                            tool_output = json.dumps({"error": f"Unknown tool: {fn_name}"})

                    except Exception as exc:
                        logger.warning("Error executing tool %s: %s", fn_name, exc)
                        tool_output = json.dumps({"error": str(exc)})

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_output,
                    })

                # Check if final outcome reached
                if final_status in ("applied", "expired", "captcha", "login_issue") or final_status.startswith("failed"):
                    if final_status == "applied":
                        break
                    elif final_status != "failed:unknown":
                        break

            # Requirement 5 Verification: If marked 'applied', verify page has strong evidence!
            duration_ms = int((time.time() - start_time) * 1000)
            elapsed = int(time.time() - start_time)

            if final_status == "applied":
                if dry_run:
                    add_event(f"[W{worker_id}] APPLIED (dry run, {elapsed}s)")
                    update_state(worker_id, status="applied", last_action=f"APPLIED (dry run, {elapsed}s)")
                    return "applied", duration_ms

                is_v, v_reason = browser.verify_submission()
                if is_v or submission_verified:
                    add_event(f"[W{worker_id}] APPLIED & VERIFIED ({elapsed}s): {job['title'][:30]}")
                    update_state(worker_id, status="applied", last_action=f"VERIFIED ({elapsed}s)")
                    return "applied", duration_ms
                else:
                    add_event(f"[W{worker_id}] SUBMISSION UNVERIFIED ({elapsed}s): {v_reason[:30]}")
                    update_state(worker_id, status="failed", last_action=f"UNVERIFIED: {v_reason[:25]}")
                    return f"failed:unverified_submission ({v_reason[:60]})", duration_ms

            # Non-applied outcomes
            if ":" in final_status:
                reason = final_status.split(":", 1)[1]
                add_event(f"[W{worker_id}] FAILED ({elapsed}s): {reason[:30]}")
                update_state(worker_id, status="failed", last_action=f"FAILED: {reason[:25]}")
            else:
                add_event(f"[W{worker_id}] {final_status.upper()} ({elapsed}s)")
                update_state(worker_id, status=final_status, last_action=f"{final_status.upper()} ({elapsed}s)")

            return final_status, duration_ms

    except Exception as e:
        logger.exception("Error during autonomous browser agent execution: %s", e)
        duration_ms = int((time.time() - start_time) * 1000)
        add_event(f"[W{worker_id}] ERROR: {str(e)[:40]}")
        update_state(worker_id, status="failed", last_action=f"ERROR: {str(e)[:25]}")
        return f"failed:{str(e)[:100]}", duration_ms
    finally:
        client.close()
