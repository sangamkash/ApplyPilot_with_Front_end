#!/usr/bin/env python3
"""ApplyPilot Dynamic Real-Time Web Dashboard Server.

Non-invasive backend server:
- Connects to SQLite databases (WAL read-only safe) for Golang, GameDev, or active profiles.
- Monitors active background processes (applypilot run, auto-apply, workers).
- Streams live search, scoring, tailoring, and application status.
- Serves tailored resumes, reports, and PDF downloads.
- Exposes REST API and serves modern single-page dashboard UI.
"""

from __future__ import annotations

import http.server
import json
import os
import re
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
PROFILE_DIRS = {
    "golang": BASE_APPLYPILOT / "profiles" / "golang",
    "gamedev": BASE_APPLYPILOT / "profiles" / "gamedev",
    "default": BASE_APPLYPILOT,
}


def get_profile_dir(profile_name: str | None) -> Path:
    if profile_name and profile_name.lower() in PROFILE_DIRS:
        target = PROFILE_DIRS[profile_name.lower()]
        if target.exists():
            return target
    # Default preference: check golang first, then base
    if PROFILE_DIRS["golang"].exists():
        return PROFILE_DIRS["golang"]
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
        # Fallback to standard connect
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception:
            return None


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
                # Detect stage
                stage = "pipeline"
                for s in ("discover", "enrich", "score", "tailor", "cover", "pdf", "apply", "auto-apply"):
                    if s in cmd:
                        stage = s
                        break
                # Detect profile
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
    except Exception as e:
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
            lines = searches_yaml.read_text().splitlines()
            for line in lines:
                m_q = re.search(r'query:\s*["\']?([^"\']+)["\']?', line)
                if m_q:
                    activity["searches_configured"].append(m_q.group(1))
                m_loc = re.search(r'location:\s*["\']?([^"\']+)["\']?', line)
                if m_loc:
                    activity["locations_configured"].append(m_loc.group(1))
        except Exception:
            pass

    # 2. Inspect tailored_resumes dir for most recently modified files
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

    # 3. Inspect worker logs
    log_dir = profile_dir / "logs"
    if log_dir.exists():
        try:
            log_files = sorted(
                log_dir.glob("worker-*.log"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
            if log_files:
                last_log = log_files[0]
                lines = last_log.read_text().splitlines()
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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/"):
            self.handle_api(path, query)
            return

        # Serve static assets or default to index.html
        if path == "/" or not (STATIC_DIR / path.lstrip("/")).exists():
            self.path = "/index.html"
        return super().do_GET()

    def send_json(self, data: dict | list, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def handle_api(self, path: str, query: dict):
        profile_name = query.get("profile", ["golang"])[0]
        profile_dir = get_profile_dir(profile_name)

        if path == "/api/profiles":
            profiles = []
            for name, pdir in PROFILE_DIRS.items():
                db_p = pdir / "applypilot.db"
                exists = db_p.exists()
                size = db_p.stat().st_size if exists else 0
                mtime = (
                    datetime.fromtimestamp(db_p.stat().st_mtime, timezone.utc).isoformat()
                    if exists else None
                )
                profiles.append({
                    "name": name,
                    "path": str(pdir),
                    "active": (pdir == profile_dir),
                    "exists": exists,
                    "db_size": size,
                    "last_modified": mtime,
                })
            self.send_json({"current": profile_dir.name, "profiles": profiles})
            return

        if path == "/api/stats":
            conn = get_db_connection(profile_dir)
            if not conn:
                self.send_json({"error": f"Database not found in {profile_dir}"}, status=404)
                return

            try:
                # Basic metrics
                total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                with_desc = conn.execute("SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL").fetchone()[0]
                pending_enrich = conn.execute("SELECT COUNT(*) FROM jobs WHERE detail_scraped_at IS NULL").fetchone()[0]
                enrich_errors = conn.execute("SELECT COUNT(*) FROM jobs WHERE detail_error IS NOT NULL").fetchone()[0]
                scored = conn.execute("SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL").fetchone()[0]
                pending_score = conn.execute("SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL").fetchone()[0]
                
                # Average fit score
                avg_score_row = conn.execute("SELECT AVG(fit_score) FROM jobs WHERE fit_score IS NOT NULL").fetchone()
                avg_score = round(avg_score_row[0], 1) if avg_score_row and avg_score_row[0] is not None else 0.0

                # Score distribution
                score_dist_rows = conn.execute("""
                    SELECT fit_score, COUNT(*) as cnt 
                    FROM jobs 
                    WHERE fit_score IS NOT NULL 
                    GROUP BY fit_score 
                    ORDER BY fit_score DESC
                """).fetchall()
                score_dist = {r[0]: r[1] for r in score_dist_rows}

                # Tailoring stats
                tailored = conn.execute("SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL").fetchone()[0]
                pending_tailor_7 = conn.execute("""
                    SELECT COUNT(*) FROM jobs 
                    WHERE fit_score >= 7 AND full_description IS NOT NULL AND tailored_resume_path IS NULL
                """).fetchone()[0]
                pending_tailor_5 = conn.execute("""
                    SELECT COUNT(*) FROM jobs 
                    WHERE fit_score >= 5 AND full_description IS NOT NULL AND tailored_resume_path IS NULL
                """).fetchone()[0]

                # Files on disk check for tailored resumes
                tailored_files_count = 0
                tailored_dir = profile_dir / "tailored_resumes"
                if tailored_dir.exists():
                    tailored_files_count = len([f for f in tailored_dir.iterdir() if f.is_file() and f.suffix == ".txt" and not f.name.endswith("_JOB.txt")])

                # Cover letters
                cover_letters = conn.execute("SELECT COUNT(*) FROM jobs WHERE cover_letter_path IS NOT NULL").fetchone()[0]

                # Application stage
                ready_to_apply = conn.execute("""
                    SELECT COUNT(*) FROM jobs 
                    WHERE fit_score >= 7 AND full_description IS NOT NULL AND application_url IS NOT NULL AND applied_at IS NULL
                """).fetchone()[0]
                applied = conn.execute("SELECT COUNT(*) FROM jobs WHERE applied_at IS NOT NULL").fetchone()[0]
                apply_errors = conn.execute("SELECT COUNT(*) FROM jobs WHERE apply_error IS NOT NULL").fetchone()[0]
                in_progress = conn.execute("SELECT COUNT(*) FROM jobs WHERE apply_status = 'applying' OR apply_status = 'starting'").fetchone()[0]

                # Site breakdown
                site_rows = conn.execute("""
                    SELECT site, 
                           COUNT(*) as total,
                           SUM(CASE WHEN fit_score >= 7 THEN 1 ELSE 0 END) as high_fit,
                           SUM(CASE WHEN fit_score >= 5 THEN 1 ELSE 0 END) as mid_fit,
                           ROUND(AVG(fit_score), 1) as avg_score,
                           SUM(CASE WHEN applied_at IS NOT NULL THEN 1 ELSE 0 END) as applied
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
                self.send_json({"error": "DB not found"}, status=404)
                return

            try:
                min_score = query.get("min_score", [None])[0]
                stage = query.get("stage", ["all"])[0]
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

                if stage == "applied":
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
                           detail_scraped_at, application_url, fit_score, score_reasoning,
                           tailored_resume_path, tailored_at, cover_letter_path,
                           applied_at, apply_status, apply_error, apply_attempts,
                           verification_confidence
                    FROM jobs
                    {where_sql}
                    ORDER BY 
                        CASE WHEN applied_at IS NOT NULL THEN 0 ELSE 1 END,
                        CASE WHEN fit_score IS NOT NULL THEN fit_score ELSE -1 END DESC,
                        discovered_at DESC
                    LIMIT ? OFFSET ?
                """
                rows = conn.execute(sql, params + [limit, offset]).fetchall()

                # Check available tailored files on disk to map back to jobs if path was not updated in DB
                tailored_dir = profile_dir / "tailored_resumes"
                tailored_files_map = {}
                if tailored_dir.exists():
                    for tf in tailored_dir.iterdir():
                        if tf.is_file() and tf.suffix == ".txt" and not tf.name.endswith("_JOB.txt"):
                            tailored_files_map[tf.stem.lower()] = tf.name

                jobs = []
                for r in rows:
                    j = dict(r)
                    # Resolve tailored resume filename if available
                    t_path = j.get("tailored_resume_path")
                    t_filename = Path(t_path).name if t_path else None
                    if not t_filename:
                        # try matching title/site slug
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

            job_dict = dict(row)
            self.send_json(job_dict)
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

            # Sanitize filename
            safe_name = Path(filename).name
            resume_file = profile_dir / "tailored_resumes" / safe_name
            if not resume_file.exists():
                # check in default base
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

            # Check if there is an associated report file
            report_name = safe_name.replace(".txt", "_REPORT.json")
            report_file = resume_file.parent / report_name
            report_data = None
            if report_file.exists():
                try:
                    report_data = json.loads(report_file.read_text())
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
                # Render clean HTML with print styles that triggers instant PDF download/print
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
  @media print {{
    body {{ padding: 0; }}
    .no-print {{ display: none; }}
  }}
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
window.onload = function() {
  setTimeout(function() { window.print(); }, 400);
};
</script>
</body></html>"""
                body = html.encode("utf-8")
                download_name = safe_name.replace(".txt", ".html")
                content_type = "text/html; charset=utf-8"
            else:  # txt
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


def run_server(port: int = PORT):
    os.chdir(str(STATIC_DIR))
    server_address = ("", port)
    
    # Enable socket address reuse to prevent 'Address already in use' errors
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(server_address, DashboardHandler) as httpd:
        print(f"\n==================================================")
        print(f" ApplyPilot Dynamic Frontend Dashboard")
        print(f" URL: http://localhost:{port}")
        print(f" Real-time live monitoring active")
        print(f" Press Ctrl+C to stop")
        print(f"==================================================\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down ApplyPilot dashboard server...")


if __name__ == "__main__":
    run_server()
