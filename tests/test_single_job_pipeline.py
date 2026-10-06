"""Unit tests for targeted single-row pipeline (stages 2, 3, 4)."""

import sqlite3
from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from applypilot.database import init_db
from applypilot.pipeline import run_single_job_pipeline


def test_run_single_job_pipeline(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    conn = init_db(test_db)

    # Insert a raw discovered job
    job_url = "https://jobs.example.com/software-engineer-101"
    conn.execute("""
        INSERT INTO jobs (url, title, site, location, description, apply_status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (job_url, "Senior Golang Developer", "TechCorp", "Remote", "Looking for Golang dev", "pending"))
    conn.commit()

    # Create dummy profile and resume
    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Experienced Golang and Python Engineer with 6 years experience.", encoding="utf-8")

    tailored_dir = tmp_path / "tailored_resumes"
    tailored_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("applypilot.pipeline.get_connection", lambda: sqlite3.connect(test_db))
    monkeypatch.setattr("applypilot.config.RESUME_PATH", resume_file)
    monkeypatch.setattr("applypilot.config.TAILORED_DIR", tailored_dir)

    # Mock Stage 2 Playwright / scrape_detail_page
    mock_scrape = {
        "full_description": "We are seeking a Senior Golang Developer with Kubernetes and PostgreSQL experience.",
        "application_url": "https://jobs.example.com/apply/101",
        "status": "ok",
    }

    # Mock Stage 3 LLM scoring
    mock_score = {
        "score": 9,
        "keywords": "golang, kubernetes, postgresql",
        "reasoning": "Strong match with candidate background.",
    }

    # Mock Stage 4 Tailoring
    mock_tailor_text = "Tailored Resume Content for Senior Golang Developer"
    mock_report = {"status": "approved", "attempts": 1}

    with patch("playwright.sync_api.sync_playwright") as mock_pw, \
         patch("applypilot.enrichment.detail.scrape_detail_page", return_value=mock_scrape), \
         patch("applypilot.scoring.scorer.score_job", return_value=mock_score), \
         patch("applypilot.scoring.tailor.tailor_resume", return_value=(mock_tailor_text, mock_report)), \
         patch("applypilot.scoring.pdf.convert_to_pdf", return_value=tailored_dir / "TechCorp_Senior_Golang_Developer.pdf"):

        # Run targeted pipeline
        res = run_single_job_pipeline(url=job_url, force=True)

        assert res["url"] == job_url

        # Check DB state after running stages 2, 3, 4
        check_conn = sqlite3.connect(test_db)
        row = check_conn.execute("SELECT full_description, application_url, fit_score, score_reasoning, tailored_resume_path FROM jobs WHERE url = ?", (job_url,)).fetchone()
        
        # Stage 2 verified
        assert row[0] == mock_scrape["full_description"]
        assert row[1] == mock_scrape["application_url"]

        # Stage 3 verified
        assert row[2] == 9
        assert "golang, kubernetes" in row[3]

        # Stage 4 verified
        assert row[4] is not None
        assert "TechCorp_Senior_Golang_Developer.txt" in row[4]


def test_reapply_single_row_pipeline(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    conn = init_db(test_db)

    # Insert a job that was already applied previously (Reapply scenario)
    job_url = "https://jobs.example.com/software-engineer-reapply"
    conn.execute("""
        INSERT INTO jobs (url, title, site, location, description, apply_status, applied_at, fit_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (job_url, "Lead Python Engineer", "AlphaCorp", "Remote", "Initial snippet", "applied", "2026-10-01T00:00:00", 6))
    conn.commit()

    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Senior Python Developer specializing in backend APIs.", encoding="utf-8")
    tailored_dir = tmp_path / "tailored_resumes"
    tailored_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("applypilot.pipeline.get_connection", lambda: sqlite3.connect(test_db))
    monkeypatch.setattr("applypilot.config.RESUME_PATH", resume_file)
    monkeypatch.setattr("applypilot.config.TAILORED_DIR", tailored_dir)

    mock_scrape = {
        "full_description": "AlphaCorp seeks Lead Python Engineer with FastAPI experience.",
        "application_url": "https://jobs.example.com/apply/reapply",
        "status": "ok",
    }
    mock_score = {
        "score": 10,
        "keywords": "fastapi, python, backend",
        "reasoning": "Flawless match with candidate experience.",
    }
    mock_tailor_text = "Tailored Resume Content for AlphaCorp Lead Python Engineer"
    mock_report = {"status": "approved", "attempts": 1}

    with patch("playwright.sync_api.sync_playwright"), \
         patch("applypilot.enrichment.detail.scrape_detail_page", return_value=mock_scrape), \
         patch("applypilot.scoring.scorer.score_job", return_value=mock_score), \
         patch("applypilot.scoring.tailor.tailor_resume", return_value=(mock_tailor_text, mock_report)), \
         patch("applypilot.scoring.pdf.convert_to_pdf", return_value=tailored_dir / "AlphaCorp_Lead_Python_Engineer.pdf"):

        res = run_single_job_pipeline(url=job_url, force=True)
        assert res["url"] == job_url

        check_conn = sqlite3.connect(test_db)
        row = check_conn.execute("SELECT full_description, fit_score, tailored_resume_path FROM jobs WHERE url = ?", (job_url,)).fetchone()
        assert "FastAPI experience" in row[0]
        assert row[1] == 10
        assert "AlphaCorp_Lead_Python_Engineer.txt" in row[2]
