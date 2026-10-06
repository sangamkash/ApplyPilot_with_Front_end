"""OpenAI AI Provider for autonomous job applications.

Uses OpenAI API driving Playwright over CDP, configured via:
  AUTO_APPLY_AI_PROVIDER=openai
  OPENAI_API_KEY=...
  OPENAI_MODEL=... (default: gpt-4o-mini)
"""

import logging
import os
import threading
from typing import Optional

from applypilot.apply.providers.base import AIProvider
from applypilot.apply.providers.agent_runner import run_autonomous_browser_agent

logger = logging.getLogger(__name__)

OPENAI_ENDPOINT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class OpenAIProvider(AIProvider):
    """OpenAI AI Provider."""

    def __init__(self) -> None:
        super().__init__(name="openai")
        self._stop_flags: dict[int, bool] = {}
        self._lock = threading.Lock()

    def validate_environment(self) -> None:
        """Validate OPENAI_API_KEY is present."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY environment variable is required when AUTO_APPLY_AI_PROVIDER=openai.\n"
                "Get an API key at https://platform.openai.com and set OPENAI_API_KEY in your environment or ~/.applypilot/.env."
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
        """Execute autonomous job application using OpenAI."""
        self.validate_environment()
        api_key = os.environ["OPENAI_API_KEY"]

        # Support OPENAI_MODEL env var or model override or default
        effective_model = os.environ.get("OPENAI_MODEL") or model or DEFAULT_OPENAI_MODEL

        with self._lock:
            self._stop_flags[worker_id] = False

        def _is_stopped() -> bool:
            with self._lock:
                return self._stop_flags.get(worker_id, False)

        return run_autonomous_browser_agent(
            provider_name="openai",
            endpoint_url=OPENAI_ENDPOINT_URL,
            api_key=api_key,
            model=effective_model,
            job=job,
            port=port,
            worker_id=worker_id,
            dry_run=dry_run,
            stop_check=_is_stopped,
        )
