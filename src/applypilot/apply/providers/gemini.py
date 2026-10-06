"""Gemini AI Provider for autonomous job applications.

Uses Google Gemini (via OpenAI-compatible endpoint or native API)
driving Playwright over CDP, configured via:
  AUTO_APPLY_AI_PROVIDER=gemini
  GEMINI_API_KEY=...
  GEMINI_MODEL=... (default: gemini-2.0-flash)
"""

import logging
import os
import threading
from typing import Optional

from applypilot.apply.providers.base import AIProvider
from applypilot.apply.providers.agent_runner import run_autonomous_browser_agent

logger = logging.getLogger(__name__)

GEMINI_COMPAT_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"


class GeminiProvider(AIProvider):
    """Google Gemini AI Provider."""

    def __init__(self) -> None:
        super().__init__(name="gemini")
        self._stop_flags: dict[int, bool] = {}
        self._lock = threading.Lock()

    def validate_environment(self) -> None:
        """Validate GEMINI_API_KEY is present."""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY environment variable is required when AUTO_APPLY_AI_PROVIDER=gemini.\n"
                "Get a key at https://aistudio.google.com and set GEMINI_API_KEY in your environment or ~/.applypilot/.env."
            )

    def stop(self, worker_id: int) -> None:
        with self._lock:
            self._stop_flags[worker_id] = True

    def run(
        self,
        job: dict,
        port: int,
        worker_id: int = 0,
        model: Optional[str] = None,
        dry_run: bool = False,
    ) -> tuple[str, int]:
        """Execute autonomous job application using Google Gemini."""
        self.validate_environment()
        api_key = os.environ["GEMINI_API_KEY"]

        # Support GEMINI_MODEL env var or model override or default
        effective_model = os.environ.get("GEMINI_MODEL") or model or DEFAULT_GEMINI_MODEL

        with self._lock:
            self._stop_flags[worker_id] = False

        def _is_stopped() -> bool:
            with self._lock:
                return self._stop_flags.get(worker_id, False)

        return run_autonomous_browser_agent(
            provider_name="gemini",
            endpoint_url=GEMINI_COMPAT_URL,
            api_key=api_key,
            model=effective_model,
            job=job,
            port=port,
            worker_id=worker_id,
            dry_run=dry_run,
            stop_check=_is_stopped,
        )
