#!/usr/bin/env python3
"""ApplyPilot Dynamic Real-Time Web Dashboard & Automation Server.

Non-invasive backend server:
- Multi-profile management (Create, Edit, Delete, Switch).
- Interactive execution pipeline control (Search, Score, Tailor, Apply).
- Connects to SQLite databases (WAL read-only safe) for any profile.
- Monitors active background processes and streams live logs.
- Serves tailored resumes, ATS formatting, AI reports, and PDF downloads.
- Prominently surfaces job applications and failure diagnostics.
- Exposes full REST API and serves modern single-page dashboard UI.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import signal
import socketserver
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

PORT = int(os.environ.get("PORT", 8080))
REPO_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
HOME_DIR = Path.home()

BASE_APPLYPILOT = HOME_DIR / ".applypilot"
USER_PROFILES_DIR = BASE_APPLYPILOT / "profiles"

# Track active background executions launched from the web interface
ACTIVE_RUNS: dict[str, dict] = {}


def get_applypilot_bin() -> list[str]:
    """Resolve the executable command for running ApplyPilot CLI."""
    venv_bin = REPO_DIR / ".venv" / "bin" / "applypilot"
    if venv_bin.exists():
        return [str(venv_bin)]

    # Check uv
    uv_bin = shutil.which("uv")
    if uv_bin:
        return [uv_bin, "run", "applypilot"]

    # Check global PATH
    ap_bin = shutil.which("applypilot")
    if ap_bin:
        return [ap_bin]

    # Fallback to python module
    return ["python3", "-m", "applypilot"]


def _sync_repo_profile_to_user_dir(profile_id: str, target_dir: Path):
    """Sync template files from repo into the user's active profile directory if missing."""
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "logs").mkdir(parents=True, exist_ok=True)
    (target_dir / "tailored_resumes").mkdir(parents=True, exist_ok=True)

    # Profile JSON
    repo_profile = REPO_DIR / "profiles" / f"profile_{profile_id}.json"
    dest_profile = target_dir / "profile.json"
    if repo_profile.exists() and not dest_profile.exists():
        shutil.copy2(repo_profile, dest_profile)

    # Searches YAML
    repo_searches = REPO_DIR / "searches" / f"searches_{profile_id}.yaml"
    dest_searches = target_dir / "searches.yaml"
    if repo_searches.exists() and not dest_searches.exists():
        shutil.copy2(repo_searches, dest_searches)

    # Resume TXT
    repo_resume = REPO_DIR / "resumes" / f"resume_{profile_id}.txt"
    dest_resume = target_dir / "resume.txt"
    if repo_resume.exists() and not dest_resume.exists():
        shutil.copy2(repo_resume, dest_resume)

    # .env
    dest_env = target_dir / ".env"
    if not dest_env.exists():
        if (REPO_DIR / ".env").exists():
            shutil.copy2(REPO_DIR / ".env", dest_env)
        elif (BASE_APPLYPILOT / ".env").exists():
            shutil.copy2(BASE_APPLYPILOT / ".env", dest_env)


def get_profile_dir(profile_name: str | None) -> Path:
    """Resolve directory for a given profile name."""
    if not profile_name or profile_name.strip() == "":
        profile_name = "golang"
    name = profile_name.strip().lower()

    if name == "default":
        return BASE_APPLYPILOT

    target = USER_PROFILES_DIR / name
    if target.exists():
        return target

    # Check repo profiles
    repo_prof = REPO_DIR / "profiles" / f"profile_{name}.json"
    if repo_prof.exists():
        _sync_repo_profile_to_user_dir(name, target)
        return target

    # Fallback default: check golang, then base
    golang_target = USER_PROFILES_DIR / "golang"
    if golang_target.exists():
        return golang_target
    return BASE_APPLYPILOT


def get_db_connection(profile_dir: Path) -> sqlite3.Connection | None:
    db_path = profile_dir / "applypilot.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception:
            return None


def discover_all_profiles() -> list[dict]:
    """Discover all available profiles from user directory and repository."""
    profiles_dict: dict[str, dict] = {}

    # 1. Discover in ~/.applypilot/profiles/*
    if USER_PROFILES_DIR.exists():
        for d in USER_PROFILES_DIR.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                profiles_dict[d.name.lower()] = {
                    "id": d.name.lower(),
                    "dir": d,
                    "source": "user",
                }

    # 2. Discover in repo profiles/profile_*.json
    repo_profiles_dir = REPO_DIR / "profiles"
    if repo_profiles_dir.exists():
        for f in repo_profiles_dir.glob("profile_*.json"):
            slug = f.stem.replace("profile_", "").lower()
            if slug not in profiles_dict:
                profiles_dict[slug] = {
                    "id": slug,
                    "dir": USER_PROFILES_DIR / slug,
                    "source": "repo",
                    "repo_file": f,
                }

    # 3. Include default profile if profile.json exists in root ~/.applypilot
    if (BASE_APPLYPILOT / "profile.json").exists():
        if "default" not in profiles_dict:
            profiles_dict["default"] = {
                "id": "default",
                "dir": BASE_APPLYPILOT,
                "source": "default",
            }

    # Enrich metadata for each discovered profile
    result = []
    for pid, pdata in profiles_dict.items():
        pdir = pdata["dir"]
        prof_file = pdir / "profile.json"
        if not prof_file.exists() and "repo_file" in pdata:
            prof_file = pdata["repo_file"]

        candidate_name = ""
        target_role = ""
        city = ""
        country = ""
        skills_summary = []
        if prof_file.exists():
            try:
                p_json = json.loads(prof_file.read_text(encoding="utf-8"))
                personal = p_json.get("personal", {})
                candidate_name = personal.get("full_name") or personal.get("preferred_name") or ""
                city = personal.get("city", "")
                country = personal.get("country", "")
                exp = p_json.get("experience", {})
                target_role = exp.get("target_role", "")
                sb = p_json.get("skills_boundary", {})
                all_skills = (
                    sb.get("languages", []) +
                    sb.get("frameworks", []) +
                    sb.get("tools", [])
                )
                skills_summary = all_skills[:6]
            except Exception:
                pass

        # Searches info
        searches_file = pdir / "searches.yaml"
        if not searches_file.exists():
            searches_file = REPO_DIR / "searches" / f"searches_{pid}.yaml"
        queries_count = 0
        locations_count = 0
        sample_queries = []
        if searches_file.exists():
            try:
                lines = searches_file.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    m_q = re.search(r'query:\s*["\']?([^"\']+)["\']?', line)
                    if m_q:
                        queries_count += 1
                        if len(sample_queries) < 3:
                            sample_queries.append(m_q.group(1))
                    m_l = re.search(r'location:\s*["\']?([^"\']+)["\']?', line)
                    if m_l:
                        locations_count += 1
            except Exception:
                pass

        # DB info
        db_path = pdir / "applypilot.db"
        has_db = db_path.exists()
        db_size = db_path.stat().st_size if has_db else 0
        last_mtime = (
            datetime.fromtimestamp(db_path.stat().st_mtime, timezone.utc).isoformat()
            if has_db else None
        )
        stats = {
            "total_jobs": 0,
            "scored": 0,
            "tailored": 0,
            "applied": 0,
            "apply_errors": 0,
        }
        if has_db:
            conn = get_db_connection(pdir)
            if conn:
                try:
                    stats["total_jobs"] = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                    stats["scored"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL").fetchone()[0]
                    stats["applied"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE applied_at IS NOT NULL").fetchone()[0]
                    stats["apply_errors"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE apply_error IS NOT NULL").fetchone()[0]
                    stats["tailored"] = conn.execute("SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL").fetchone()[0]
                except Exception:
                    pass
                finally:
                    conn.close()

        # Tailored resume count from disk
        tailored_dir = pdir / "tailored_resumes"
        if tailored_dir.exists():
            try:
                txt_resumes = len([
                    f for f in tailored_dir.iterdir()
                    if f.is_file() and f.suffix == ".txt" and not f.name.endswith("_JOB.txt")
                ])
                stats["tailored"] = max(stats["tailored"], txt_resumes)
            except Exception:
                pass

        display_name = pid.replace("_", " ").title()
        if target_role:
            display_name = f"{display_name} - {target_role}"

        result.append({
            "id": pid,
            "display_name": display_name,
            "candidate_name": candidate_name or "Applicant",
            "target_role": target_role or pid.replace("_", " ").title(),
            "location": f"{city}, {country}".strip(", "),
            "skills": skills_summary,
            "queries_count": queries_count,
            "sample_queries": sample_queries,
            "locations_count": locations_count,
            "has_db": has_db,
            "db_size": db_size,
            "last_modified": last_mtime,
            "stats": stats,
            "path": str(pdir),
            "is_system_default": pid in ("golang", "gamedev", "default"),
        })

    def sort_key(p):
        if p["id"] == "golang":
            return (0, p["id"])
        if p["id"] == "gamedev":
            return (1, p["id"])
        return (2, p["id"])

    result.sort(key=sort_key)
    return result


def get_running_tasks() -> list[dict]:
    """Inspect system processes to detect ApplyPilot commands running."""
    tasks = []
    try:
        res = subprocess.run(
            ["ps", "-ax", "-o", "pid,etime,%cpu,%mem,command"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in res.stdout.splitlines():
            line_strip = line.strip()
            if not line_strip or "ps -ax" in line_strip:
                continue
            parts = line_strip.split(None, 4)
            if len(parts) < 5:
                continue
            pid, etime, cpu, mem, cmd = parts
            is_applypilot = "applypilot" in cmd or "auto-apply" in cmd or "pipeline-" in cmd or "switch_profile" in cmd
            if is_applypilot and "grep" not in cmd and "server.py" not in cmd:
                stage = "pipeline"
                for s in ("discover", "enrich", "score", "tailor", "cover", "pdf", "apply", "auto-apply"):
                    if s in cmd:
                        stage = s
                        break
                profile = "unknown"
                if "golang" in cmd:
                    profile = "golang"
                elif "gamedev" in cmd:
                    profile = "gamedev"

                tasks.append({
                    "pid": pid,
                    "elapsed": etime,
                    "cpu": cpu,
                    "mem": mem,
                    "stage": stage,
                    "profile": profile,
                    "command": cmd[:180],
                })
    except Exception:
        pass
    return tasks


def get_recent_activity(profile_dir: Path) -> dict:
    """Detect current live activity (e.g., active searches, latest tailored files, logs)."""
    activity = {
        "latest_event": None,
        "recent_tailored": [],
        "active_log_line": None,
        "searches_configured": [],
        "locations_configured": [],
    }

    # 1. Inspect searches.yaml
    searches_yaml = profile_dir / "searches.yaml"
    if searches_yaml.exists():
        try:
            lines = searches_yaml.read_text(encoding="utf-8").splitlines()
            for line in lines:
                m_q = re.search(r'query:\s*["\']?([^"\']+)["\']?', line)
                if m_q:
                    activity["searches_configured"].append(m_q.group(1))
                m_loc = re.search(r'location:\s*["\']?([^"\']+)["\']?', line)
                if m_loc:
                    activity["locations_configured"].append(m_loc.group(1))
        except Exception:
            pass

    # 2. Inspect tailored_resumes dir
    tailored_dir = profile_dir / "tailored_resumes"
    if tailored_dir.exists():
        try:
            files = [
                f for f in tailored_dir.iterdir()
                if f.is_file() and not f.name.endswith(".tmp")
            ]
            files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            for f in files[:8]:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()
                file_type = "resume"
                if f.name.endswith("_REPORT.json"):
                    file_type = "report"
                elif f.name.endswith("_JOB.txt"):
                    file_type = "job_desc"
                activity["recent_tailored"].append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "mtime": mtime,
                    "type": file_type,
                })
            if files:
                latest = files[0]
                activity["latest_event"] = f"Generated {latest.name} ({time.strftime('%H:%M:%S', time.localtime(latest.stat().st_mtime))})"
        except Exception:
            pass

    # 3. Inspect worker logs or pipeline_run.log
    log_dir = profile_dir / "logs"
    if log_dir.exists():
        try:
            # Check pipeline_run.log first, then worker logs
            p_run = log_dir / "pipeline_run.log"
            if p_run.exists() and p_run.stat().st_size > 0:
                p_lines = p_run.read_text(encoding="utf-8", errors="replace").splitlines()
                non_empty = [l.strip() for l in p_lines if l.strip()]
                if non_empty:
                    activity["active_log_line"] = non_empty[-1]

            if not activity["active_log_line"]:
                log_files = sorted(
                    log_dir.glob("worker-*.log"),
                    key=lambda x: x.stat().st_mtime,
                    reverse=True,
                )
                if log_files:
                    last_log = log_files[0]
                    lines = last_log.read_text(encoding="utf-8", errors="replace").splitlines()
                    if lines:
                        activity["active_log_line"] = lines[-1].strip()
        except Exception:
            pass

    return activity


def parse_resume_text(text: str) -> dict:
    """Parse resume text into structured sections."""
    lines = [line.rstrip() for line in text.strip().split("\n")]
    header_lines = []
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip().upper() in ("SUMMARY", "PROFESSIONAL SUMMARY", "OBJECTIVE"):
            body_start = i
            break
        if line.strip():
            header_lines.append(line.strip())

    name = header_lines[0] if len(header_lines) > 0 else ""
    title = header_lines[1] if len(header_lines) > 1 else ""
    contact_parts = header_lines[2:]

    sections = {}
    current_section = "SUMMARY"
    current_lines = []

    for line in lines[body_start:]:
        stripped = line.strip()
        if (
            stripped
            and stripped == stripped.upper()
            and not stripped.startswith("-")
            and not stripped.startswith("*")
            and not stripped.startswith("•")
            and len(stripped) > 3
        ):
            if current_lines:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = stripped
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_section] = "\n".join(current_lines).strip()

    return {
        "name": name,
        "title": title,
        "contact": " | ".join(contact_parts),
        "sections": sections,
        "raw": text,
    }


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/"):
            self.handle_api_get(path, query)
            return

        # Serve static assets or default to index.html
        if path == "/" or not (STATIC_DIR / path.lstrip("/")).exists():
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception as e:
                self.send_json({"error": f"Invalid JSON payload: {str(e)}"}, status=400)
                return

            self.handle_api_post(path, data)
            return

        self.send_json({"error": "Not found"}, status=404)

    def send_json(self, data: dict | list, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def handle_api_get(self, path: str, query: dict):
        profile_name = query.get("profile", ["golang"])[0]
        profile_dir = get_profile_dir(profile_name)

        if path == "/api/profiles":
            profiles = discover_all_profiles()
            self.send_json({
                "current": profile_dir.name,
                "profiles": profiles,
            })
            return

        if path == "/api/profile-detail":
            p_name = query.get("profile", ["golang"])[0].strip().lower()
            p_dir = get_profile_dir(p_name)
            
            # Load profile JSON
            prof_file = p_dir / "profile.json"
            if not prof_file.exists():
                prof_file = REPO_DIR / "profiles" / f"profile_{p_name}.json"
            
            p_json = {}
            if prof_file.exists():
                try:
                    p_json = json.loads(prof_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            # Load searches YAML
            searches_file = p_dir / "searches.yaml"
            if not searches_file.exists():
                searches_file = REPO_DIR / "searches" / f"searches_{p_name}.yaml"
            searches_yaml = ""
            if searches_file.exists():
                try:
                    searches_yaml = searches_file.read_text(encoding="utf-8")
                except Exception:
                    pass

            # Load resume TXT
            resume_file = p_dir / "resume.txt"
            if not resume_file.exists():
                resume_file = REPO_DIR / "resumes" / f"resume_{p_name}.txt"
            resume_text = ""
            if resume_file.exists():
                try:
                    resume_text = resume_file.read_text(encoding="utf-8")
                except Exception:
                    pass

            self.send_json({
                "id": p_name,
                "profile_dir": str(p_dir),
                "profile_json": p_json,
                "searches_yaml": searches_yaml,
                "resume_text": resume_text,
            })
            return

        if path == "/api/pipeline/status":
            p_name = query.get("profile", ["golang"])[0].strip().lower()
            p_dir = get_profile_dir(p_name)

            run_info = ACTIVE_RUNS.get(p_name)
            is_running = False
            exit_code = None
            elapsed_sec = None
            action = None
            pid = None

            if run_info:
                proc = run_info.get("proc")
                pid = run_info.get("pid")
                action = run_info.get("action")
                start_time = run_info.get("start_time")
                if start_time:
                    elapsed_sec = int(time.time() - start_time)

                if proc:
                    exit_code = proc.poll()
                    if exit_code is None:
                        is_running = True
                    else:
                        is_running = False
                elif pid:
                    try:
                        os.kill(pid, 0)
                        is_running = True
                    except OSError:
                        is_running = False

            # Read last 35 lines from pipeline_run.log
            log_tail = []
            log_file = p_dir / "logs" / "pipeline_run.log"
            if log_file.exists():
                try:
                    content = log_file.read_text(encoding="utf-8", errors="replace")
                    lines = [l for l in content.splitlines() if l.strip()]
                    log_tail = lines[-35:]
                except Exception:
                    pass

            self.send_json({
                "profile": p_name,
                "is_running": is_running,
                "pid": pid,
                "action": action,
                "elapsed_seconds": elapsed_sec,
                "exit_code": exit_code,
                "log_tail": log_tail,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        if path == "/api/stats":
            conn = get_db_connection(profile_dir)
            if not conn:
                self.send_json({
                    "profile": profile_dir.name,
                    "total": 0,
                    "with_description": 0,
                    "pending_enrichment": 0,
                    "enrichment_errors": 0,
                    "scored": 0,
                    "pending_scoring": 0,
                    "avg_score": 0.0,
                    "score_distribution": {},
                    "tailored": 0,
                    "pending_tailor_7": 0,
                    "pending_tailor_5": 0,
                    "cover_letters": 0,
                    "ready_to_apply": 0,
                    "applied": 0,
                    "apply_errors": 0,
                    "in_progress": 0,
                    "error_breakdown": [],
                    "sites": [],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return

            try:
                total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                with_desc = conn.execute("SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL").fetchone()[0]
                pending_enrich = conn.execute("SELECT COUNT(*) FROM jobs WHERE detail_scraped_at IS NULL").fetchone()[0]
                enrich_errors = conn.execute("SELECT COUNT(*) FROM jobs WHERE detail_error IS NOT NULL").fetchone()[0]
                scored = conn.execute("SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL").fetchone()[0]
                pending_score = conn.execute("SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL").fetchone()[0]

                avg_score_row = conn.execute("SELECT AVG(fit_score) FROM jobs WHERE fit_score IS NOT NULL").fetchone()
                avg_score = round(avg_score_row[0], 1) if avg_score_row and avg_score_row[0] is not None else 0.0

                score_dist_rows = conn.execute("""
                    SELECT fit_score, COUNT(*) as cnt 
                    FROM jobs 
                    WHERE fit_score IS NOT NULL 
                    GROUP BY fit_score 
                    ORDER BY fit_score DESC
                """).fetchall()
                score_dist = {r[0]: r[1] for r in score_dist_rows}

                tailored = conn.execute("SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL").fetchone()[0]
                pending_tailor_7 = conn.execute("""
                    SELECT COUNT(*) FROM jobs 
                    WHERE fit_score >= 7 AND full_description IS NOT NULL AND tailored_resume_path IS NULL
                """).fetchone()[0]
                pending_tailor_5 = conn.execute("""
                    SELECT COUNT(*) FROM jobs 
                    WHERE fit_score >= 5 AND full_description IS NOT NULL AND tailored_resume_path IS NULL
                """).fetchone()[0]

                tailored_files_count = 0
                tailored_dir = profile_dir / "tailored_resumes"
                if tailored_dir.exists():
                    tailored_files_count = len([f for f in tailored_dir.iterdir() if f.is_file() and f.suffix == ".txt" and not f.name.endswith("_JOB.txt")])

                cover_letters = conn.execute("SELECT COUNT(*) FROM jobs WHERE cover_letter_path IS NOT NULL").fetchone()[0]

                ready_to_apply = conn.execute("""
                    SELECT COUNT(*) FROM jobs 
                    WHERE fit_score >= 7 AND full_description IS NOT NULL AND application_url IS NOT NULL AND applied_at IS NULL
                """).fetchone()[0]
                applied = conn.execute("SELECT COUNT(*) FROM jobs WHERE applied_at IS NOT NULL").fetchone()[0]
                apply_errors = conn.execute("SELECT COUNT(*) FROM jobs WHERE apply_error IS NOT NULL").fetchone()[0]
                in_progress = conn.execute("SELECT COUNT(*) FROM jobs WHERE apply_status = 'applying' OR apply_status = 'starting'").fetchone()[0]

                # Detailed application error breakdown
                error_breakdown = []
                try:
                    err_rows = conn.execute("""
                        SELECT apply_error, COUNT(*) as count, MIN(title) as sample_job, MIN(site) as sample_site
                        FROM jobs
                        WHERE apply_error IS NOT NULL
                        GROUP BY apply_error
                        ORDER BY count DESC
                        LIMIT 10
                    """).fetchall()
                    for er in err_rows:
                        error_breakdown.append({
                            "error": er["apply_error"],
                            "count": er["count"],
                            "sample_job": er["sample_job"],
                            "site": er["sample_site"],
                        })
                except Exception:
                    pass

                site_rows = conn.execute("""
                    SELECT site, 
                           COUNT(*) as total,
                           SUM(CASE WHEN fit_score >= 7 THEN 1 ELSE 0 END) as high_fit,
                           SUM(CASE WHEN fit_score >= 5 THEN 1 ELSE 0 END) as mid_fit,
                           ROUND(AVG(fit_score), 1) as avg_score,
                           SUM(CASE WHEN applied_at IS NOT NULL THEN 1 ELSE 0 END) as applied,
                           SUM(CASE WHEN apply_error IS NOT NULL THEN 1 ELSE 0 END) as errors
                    FROM jobs 
                    GROUP BY site 
                    ORDER BY total DESC
                """).fetchall()

                sites = [
                    {
                        "site": r["site"] or "Unknown",
                        "total": r["total"],
                        "high_fit": r["high_fit"],
                        "mid_fit": r["mid_fit"],
                        "avg_score": r["avg_score"] or 0,
                        "applied": r["applied"],
                        "errors": r["errors"] if "errors" in r.keys() else 0,
                    }
                    for r in site_rows
                ]

                conn.close()

                self.send_json({
                    "profile": profile_dir.name,
                    "total": total,
                    "with_description": with_desc,
                    "pending_enrichment": pending_enrich,
                    "enrichment_errors": enrich_errors,
                    "scored": scored,
                    "pending_scoring": pending_score,
                    "avg_score": avg_score,
                    "score_distribution": score_dist,
                    "tailored": max(tailored, tailored_files_count),
                    "pending_tailor_7": pending_tailor_7,
                    "pending_tailor_5": pending_tailor_5,
                    "cover_letters": cover_letters,
                    "ready_to_apply": ready_to_apply,
                    "applied": applied,
                    "apply_errors": apply_errors,
                    "in_progress": in_progress,
                    "error_breakdown": error_breakdown,
                    "sites": sites,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                if conn:
                    conn.close()
                self.send_json({"error": str(e)}, status=500)
            return

        if path == "/api/jobs":
            conn = get_db_connection(profile_dir)
            if not conn:
                self.send_json({"total": 0, "limit": 100, "offset": 0, "jobs": []})
                return

            try:
                min_score = query.get("min_score", [None])[0]
                stage = query.get("stage", ["all"])[0].lower()
                search = query.get("search", [""])[0].strip()
                site = query.get("site", ["all"])[0]
                limit = int(query.get("limit", [100])[0])
                offset = int(query.get("offset", [0])[0])

                where_clauses = []
                params = []

                if min_score is not None and min_score != "":
                    where_clauses.append("fit_score >= ?")
                    params.append(int(min_score))

                if site and site != "all":
                    where_clauses.append("site = ?")
                    params.append(site)

                if stage in ("error", "errors", "issues"):
                    where_clauses.append("(apply_error IS NOT NULL OR detail_error IS NOT NULL)")
                elif stage == "applied":
                    where_clauses.append("(applied_at IS NOT NULL OR apply_status IS NOT NULL)")
                elif stage == "tailored":
                    where_clauses.append("tailored_resume_path IS NOT NULL")
                elif stage == "ready":
                    where_clauses.append("fit_score >= 7 AND full_description IS NOT NULL AND applied_at IS NULL")
                elif stage == "scored":
                    where_clauses.append("fit_score IS NOT NULL")
                elif stage == "high":
                    where_clauses.append("fit_score >= 7")

                if search:
                    where_clauses.append("(title LIKE ? OR site LIKE ? OR location LIKE ? OR score_reasoning LIKE ?)")
                    kw = f"%{search}%"
                    params.extend([kw, kw, kw, kw])

                where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                count_sql = f"SELECT COUNT(*) FROM jobs {where_sql}"
                total_filtered = conn.execute(count_sql, params).fetchone()[0]

                sql = f"""
                    SELECT url, title, salary, location, site, strategy, discovered_at,
                           detail_scraped_at, detail_error, application_url, fit_score, score_reasoning,
                           tailored_resume_path, tailored_at, cover_letter_path,
                           applied_at, apply_status, apply_error, apply_attempts,
                           verification_confidence
                    FROM jobs
                    {where_sql}
                    ORDER BY 
                        CASE WHEN apply_error IS NOT NULL THEN 0 ELSE 1 END,
                        CASE WHEN applied_at IS NOT NULL THEN 0 ELSE 1 END,
                        CASE WHEN fit_score IS NOT NULL THEN fit_score ELSE -1 END DESC,
                        discovered_at DESC
                    LIMIT ? OFFSET ?
                """
                rows = conn.execute(sql, params + [limit, offset]).fetchall()

                tailored_dir = profile_dir / "tailored_resumes"
                tailored_files_map = {}
                if tailored_dir.exists():
                    for tf in tailored_dir.iterdir():
                        if tf.is_file() and tf.suffix == ".txt" and not tf.name.endswith("_JOB.txt"):
                            tailored_files_map[tf.stem.lower()] = tf.name

                jobs = []
                for r in rows:
                    j = dict(r)
                    t_path = j.get("tailored_resume_path")
                    t_filename = Path(t_path).name if t_path else None
                    if not t_filename:
                        slug = re.sub(r'[^a-zA-Z0-9]+', '_', f"{j.get('site','')}_{j.get('title','')}")[:40].lower()
                        for k, v in tailored_files_map.items():
                            if slug in k or k in slug:
                                t_filename = v
                                break
                    j["tailored_filename"] = t_filename
                    jobs.append(j)

                conn.close()
                self.send_json({
                    "total": total_filtered,
                    "limit": limit,
                    "offset": offset,
                    "jobs": jobs,
                })
            except Exception as e:
                if conn:
                    conn.close()
                self.send_json({"error": str(e)}, status=500)
            return

        if path == "/api/job-detail":
            conn = get_db_connection(profile_dir)
            url = query.get("url", [""])[0]
            if not conn or not url:
                self.send_json({"error": "Missing url or db"}, status=400)
                return

            row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
            conn.close()
            if not row:
                self.send_json({"error": "Job not found"}, status=404)
                return

            self.send_json(dict(row))
            return

        if path == "/api/live-status":
            running_tasks = get_running_tasks()
            activity = get_recent_activity(profile_dir)
            self.send_json({
                "is_active": len(running_tasks) > 0,
                "running_tasks": running_tasks,
                "activity": activity,
                "profile": profile_dir.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        if path == "/api/resume":
            filename = query.get("file", [""])[0]
            if not filename:
                self.send_json({"error": "Missing file param"}, status=400)
                return

            safe_name = Path(filename).name
            resume_file = profile_dir / "tailored_resumes" / safe_name
            if not resume_file.exists():
                resume_file = BASE_APPLYPILOT / "tailored_resumes" / safe_name
                if not resume_file.exists():
                    self.send_json({"error": f"Resume file {safe_name} not found"}, status=404)
                    return

            text = resume_file.read_text(encoding="utf-8", errors="replace")
            is_fallback = False
            if not text.strip():
                base_resume = profile_dir / "resume.txt"
                if not base_resume.exists():
                    base_resume = BASE_APPLYPILOT / "resume.txt"
                if base_resume.exists():
                    text = base_resume.read_text(encoding="utf-8", errors="replace")
                    is_fallback = True

            parsed_resume = parse_resume_text(text)

            report_name = safe_name.replace(".txt", "_REPORT.json")
            report_file = resume_file.parent / report_name
            report_data = None
            if report_file.exists():
                try:
                    report_data = json.loads(report_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            self.send_json({
                "filename": safe_name,
                "parsed": parsed_resume,
                "is_fallback": is_fallback,
                "report": report_data,
            })
            return

        if path == "/api/download-resume":
            filename = query.get("file", [""])[0]
            fmt = query.get("format", ["txt"])[0].lower()
            if not filename:
                self.send_response(400)
                self.end_headers()
                return

            safe_name = Path(filename).name
            resume_file = profile_dir / "tailored_resumes" / safe_name
            if not resume_file.exists():
                resume_file = BASE_APPLYPILOT / "tailored_resumes" / safe_name
                if not resume_file.exists():
                    self.send_response(404)
                    self.end_headers()
                    return

            raw_text = resume_file.read_text(encoding="utf-8", errors="replace")
            if not raw_text.strip():
                base_resume = profile_dir / "resume.txt"
                if not base_resume.exists():
                    base_resume = BASE_APPLYPILOT / "resume.txt"
                if base_resume.exists():
                    raw_text = base_resume.read_text(encoding="utf-8", errors="replace")

            if fmt == "md":
                parsed = parse_resume_text(raw_text)
                md_content = f"# {parsed['name']}\n**{parsed['title']}**\n{parsed['contact']}\n\n"
                for sec, content in parsed["sections"].items():
                    md_content += f"## {sec}\n{content}\n\n"
                body = md_content.encode("utf-8")
                download_name = safe_name.replace(".txt", ".md")
                content_type = "text/markdown; charset=utf-8"
            elif fmt == "pdf":
                parsed = parse_resume_text(raw_text)
                html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{parsed['name']} - Tailored Resume</title>
<style>
  @page {{ margin: 0.5in; size: letter; }}
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #111; line-height: 1.4; margin: 0; padding: 20px; font-size: 10.5pt; }}
  h1 {{ margin: 0 0 4px 0; font-size: 18pt; text-transform: uppercase; letter-spacing: 0.5px; color: #0f172a; text-align: center; }}
  .subtitle {{ font-size: 11pt; font-weight: 600; color: #334155; text-align: center; margin-bottom: 4px; }}
  .contact {{ font-size: 9pt; color: #64748b; text-align: center; margin-bottom: 16px; border-bottom: 2px solid #0f172a; padding-bottom: 8px; }}
  h2 {{ font-size: 11pt; font-weight: bold; text-transform: uppercase; color: #0f172a; border-bottom: 1px solid #cbd5e1; margin-top: 14px; margin-bottom: 6px; padding-bottom: 2px; }}
  p, pre {{ margin: 0 0 6px 0; font-family: inherit; font-size: 10pt; white-space: pre-wrap; }}
  @media print {{ body {{ padding: 0; }} .no-print {{ display: none; }} }}
  .no-print-bar {{
    background: #1e293b; color: white; padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; border-radius: 8px; margin-bottom: 20px; font-family: sans-serif;
  }}
  .no-print-bar button {{
    background: #0284c7; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer;
  }}
</style>
</head>
<body>
  <div class="no-print no-print-bar">
    <span>Print / Save as PDF dialog will open automatically. If not, click Print:</span>
    <button onclick="window.print()">Print to PDF</button>
  </div>
  <h1>{parsed['name']}</h1>
  <div class="subtitle">{parsed['title']}</div>
  <div class="contact">{parsed['contact']}</div>
"""
                for sec, content in parsed["sections"].items():
                    html += f"<h2>{sec}</h2><pre>{content}</pre>\n"
                html += """
<script>
window.onload = function() { setTimeout(function() { window.print(); }, 400); };
</script>
</body></html>"""
                body = html.encode("utf-8")
                download_name = safe_name.replace(".txt", ".html")
                content_type = "text/html; charset=utf-8"
            else:
                body = raw_text.encode("utf-8")
                download_name = safe_name
                content_type = "text/plain; charset=utf-8"

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if fmt != "pdf":
                self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_json({"error": "Endpoint not found"}, status=404)

    def handle_api_post(self, path: str, data: dict):
        """Handle POST actions: profile creation/update/deletion, pipeline runs/stops."""
        if path in ("/api/profiles/create", "/api/profiles/update"):
            raw_id = data.get("id", "").strip()
            if not raw_id:
                self.send_json({"error": "Profile ID is required"}, status=400)
                return

            profile_id = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_id).lower().strip("_")
            if not profile_id:
                self.send_json({"error": "Invalid Profile ID"}, status=400)
                return

            profile_json = data.get("profile_json") or {}
            searches_yaml = data.get("searches_yaml") or ""
            resume_text = data.get("resume_text") or ""

            # Target user profile directory: ~/.applypilot/profiles/<profile_id>
            target_dir = USER_PROFILES_DIR / profile_id
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "logs").mkdir(parents=True, exist_ok=True)
            (target_dir / "tailored_resumes").mkdir(parents=True, exist_ok=True)

            # Write profile.json
            with open(target_dir / "profile.json", "w", encoding="utf-8") as f:
                json.dump(profile_json, f, indent=2)

            # Write searches.yaml
            with open(target_dir / "searches.yaml", "w", encoding="utf-8") as f:
                f.write(searches_yaml.strip() + "\n")

            # Write resume.txt
            with open(target_dir / "resume.txt", "w", encoding="utf-8") as f:
                f.write(resume_text.strip() + "\n")

            # Copy .env if not exists
            if not (target_dir / ".env").exists():
                if (REPO_DIR / ".env").exists():
                    shutil.copy2(REPO_DIR / ".env", target_dir / ".env")
                elif (BASE_APPLYPILOT / ".env").exists():
                    shutil.copy2(BASE_APPLYPILOT / ".env", target_dir / ".env")

            # Also mirror to repo files if desired
            try:
                repo_pdir = REPO_DIR / "profiles"
                repo_sdir = REPO_DIR / "searches"
                repo_rdir = REPO_DIR / "resumes"
                repo_pdir.mkdir(exist_ok=True)
                repo_sdir.mkdir(exist_ok=True)
                repo_rdir.mkdir(exist_ok=True)

                with open(repo_pdir / f"profile_{profile_id}.json", "w", encoding="utf-8") as f:
                    json.dump(profile_json, f, indent=2)
                with open(repo_sdir / f"searches_{profile_id}.yaml", "w", encoding="utf-8") as f:
                    f.write(searches_yaml.strip() + "\n")
                with open(repo_rdir / f"resume_{profile_id}.txt", "w", encoding="utf-8") as f:
                    f.write(resume_text.strip() + "\n")
            except Exception as e:
                print(f"Warning: Could not mirror to repo files: {e}")

            action_type = "created" if path.endswith("create") else "updated"
            self.send_json({
                "success": True,
                "id": profile_id,
                "message": f"Profile '{profile_id}' {action_type} successfully.",
                "path": str(target_dir),
            })
            return

        if path == "/api/profiles/delete":
            raw_id = data.get("id", "").strip().lower()
            if not raw_id or raw_id in ("default", ".", "..", "/", "\\"):
                self.send_json({"error": "Cannot delete root or default profile."}, status=400)
                return

            # Check if active process is running for this profile
            if raw_id in ACTIVE_RUNS:
                try:
                    proc = ACTIVE_RUNS[raw_id].get("proc")
                    if proc and proc.poll() is None:
                        proc.terminate()
                except Exception:
                    pass
                del ACTIVE_RUNS[raw_id]

            # Remove from user profiles dir
            target_dir = USER_PROFILES_DIR / raw_id
            deleted = False
            if target_dir.exists():
                try:
                    shutil.rmtree(target_dir)
                    deleted = True
                except Exception as e:
                    self.send_json({"error": f"Failed to delete directory: {e}"}, status=500)
                    return

            # Also clean up mirrored repo files if they exist
            try:
                rf = REPO_DIR / "profiles" / f"profile_{raw_id}.json"
                if rf.exists():
                    rf.unlink()
                sf = REPO_DIR / "searches" / f"searches_{raw_id}.yaml"
                if sf.exists():
                    sf.unlink()
                rmf = REPO_DIR / "resumes" / f"resume_{raw_id}.txt"
                if rmf.exists():
                    rmf.unlink()
                deleted = True
            except Exception:
                pass

            if not deleted:
                self.send_json({"error": f"Profile '{raw_id}' was not found."}, status=404)
                return

            self.send_json({
                "success": True,
                "id": raw_id,
                "message": f"Profile '{raw_id}' deleted successfully.",
            })
            return

        if path == "/api/pipeline/run":
            profile_name = data.get("profile", "golang").strip().lower()
            action = data.get("action", "search").strip().lower()
            workers = int(data.get("workers", 2))
            min_score = int(data.get("min_score", 7))
            dry_run = bool(data.get("dry_run", False))
            stages = data.get("stages", "").strip()

            target_dir = get_profile_dir(profile_name)
            target_dir.mkdir(parents=True, exist_ok=True)
            log_dir = target_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)

            cmd_base = get_applypilot_bin()

            # Build command args
            if stages:
                cmd = [*cmd_base, "run", *stages.split(), "-w", str(workers), "--min-score", str(min_score)]
            elif action == "search":
                cmd = [*cmd_base, "run", "discover", "enrich", "-w", str(workers)]
            elif action == "score":
                cmd = [*cmd_base, "run", "score", "--min-score", str(min_score)]
            elif action == "tailor":
                cmd = [*cmd_base, "run", "tailor", "--min-score", str(min_score)]
            elif action == "cover":
                cmd = [*cmd_base, "run", "cover", "--min-score", str(min_score)]
            elif action == "apply":
                cmd = [*cmd_base, "apply", "--min-score", str(min_score), "-w", str(workers)]
            elif action == "all":
                cmd = [*cmd_base, "run", "all", "-w", str(workers), "--min-score", str(min_score)]
            else:
                cmd = [*cmd_base, "run", "discover", "enrich", "-w", str(workers)]

            if dry_run:
                cmd.append("--dry-run")

            log_file = log_dir / "pipeline_run.log"
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            with open(log_file, "a", encoding="utf-8") as lf:
                lf.write(f"\n\n=======================================================\n")
                lf.write(f" [PIPELINE RUN] Triggered: {timestamp}\n")
                lf.write(f" Profile:  {profile_name} ({target_dir})\n")
                lf.write(f" Command:  {' '.join(cmd)}\n")
                lf.write(f"=======================================================\n\n")

            env = os.environ.copy()
            env["APPLYPILOT_DIR"] = str(target_dir)
            env["PYTHONUNBUFFERED"] = "1"

            log_fd = open(log_file, "a", encoding="utf-8")
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(REPO_DIR),
                    env=env,
                    stdout=log_fd,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                ACTIVE_RUNS[profile_name] = {
                    "proc": proc,
                    "pid": proc.pid,
                    "action": action,
                    "start_time": time.time(),
                    "profile": profile_name,
                    "log_file": str(log_file),
                    "command": " ".join(cmd),
                }

                self.send_json({
                    "success": True,
                    "pid": proc.pid,
                    "profile": profile_name,
                    "action": action,
                    "command": " ".join(cmd),
                    "log_file": str(log_file),
                })
            except Exception as e:
                self.send_json({"error": f"Failed to start pipeline: {str(e)}"}, status=500)
            return

        if path == "/api/pipeline/stop":
            profile_name = data.get("profile", "").strip().lower()
            run_info = ACTIVE_RUNS.get(profile_name)
            if not run_info or not run_info.get("proc"):
                self.send_json({"error": f"No active pipeline running for '{profile_name}'"}, status=404)
                return

            proc = run_info["proc"]
            try:
                proc.terminate()
                time.sleep(0.5)
                if proc.poll() is None:
                    proc.kill()
                del ACTIVE_RUNS[profile_name]
                self.send_json({"success": True, "message": f"Pipeline for '{profile_name}' stopped."})
            except Exception as e:
                self.send_json({"error": f"Could not stop process: {str(e)}"}, status=500)
            return

        self.send_json({"error": "Endpoint not found"}, status=404)


def run_server(port: int = PORT):
    os.chdir(str(STATIC_DIR))
    server_address = ("", port)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(server_address, DashboardHandler) as httpd:
        print(f"\n==================================================")
        print(f" ApplyPilot Dynamic Multi-Profile Server")
        print(f" URL: http://localhost:{port}")
        print(f" Full Profile CRUD & Pipeline Control Active")
        print(f" Press Ctrl+C to stop")
        print(f"==================================================\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down ApplyPilot server...")


if __name__ == "__main__":
    run_server()
