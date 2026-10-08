"""Ollama AI Provider for autonomous job applications.

Uses local Ollama driving Playwright over CDP, configured via:
  AUTO_APPLY_AI_PROVIDER=ollama
  OLLAMA_BASE_URL=http://localhost:11434 (default)
  OLLAMA_MODEL=gpt-oss:20b (default)
  OLLAMA_TIMEOUT=180 (seconds, default)
"""

import logging
import os
import threading
from typing import Optional

import httpx

from applypilot.apply.providers.base import AIProvider
from applypilot.apply.providers.agent_runner import run_autonomous_browser_agent

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gpt-oss:20b"
DEFAULT_OLLAMA_TIMEOUT = 180


def get_ollama_base_url() -> str:
    """Return the normalized base URL for local Ollama server."""
    url = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("LLM_URL") or DEFAULT_OLLAMA_BASE_URL
    url = url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3].rstrip("/")
    return url or DEFAULT_OLLAMA_BASE_URL


def get_ollama_model(override: Optional[str] = None) -> str:
    """Resolve effective Ollama model name."""
    chosen = override if override and override.lower() not in ("haiku", "sonnet", "opus") else None
    return (
        os.environ.get("OLLAMA_MODEL")
        or chosen
        or os.environ.get("LLM_MODEL")
        or DEFAULT_OLLAMA_MODEL
    )


class OllamaProvider(AIProvider):
    """Local Ollama AI Provider for Apple Silicon / local execution."""

    def __init__(self) -> None:
        super().__init__(name="ollama")
        self._stop_flags: dict[int, bool] = {}
        self._lock = threading.Lock()

    def validate_environment(self) -> None:
        """Validate Ollama server is running and reachable."""
        base_url = get_ollama_base_url()
        effective_model = get_ollama_model()

        try:
            resp = httpx.get(f"{base_url}/api/version", timeout=4.0)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Ollama server at {base_url} returned status code {resp.status_code}.\n"
                    f"Ensure Ollama is properly running via `ollama serve`."
                )
        except Exception as e:
            raise RuntimeError(
                f"Ollama server is not reachable at {base_url} ({e}).\n"
                f"Please ensure Ollama is running (`ollama serve`) and model '{effective_model}' is available (`ollama run {effective_model}`)."
            ) from e

        # Optional check for model availability
        try:
            tags_resp = httpx.get(f"{base_url}/api/tags", timeout=4.0)
            if tags_resp.status_code == 200:
                models_data = tags_resp.json().get("models", [])
                installed_names = [m.get("name", "") for m in models_data]
                if installed_names and not any(effective_model in name or name in effective_model for name in installed_names):
                    logger.warning(
                        "Configured Ollama model '%s' was not found in installed models: %s. "
                        "You may need to run `ollama pull %s`.",
                        effective_model,
                        installed_names,
                        effective_model,
                    )
        except Exception:
            pass

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
        """Execute autonomous job application using local Ollama."""
        self.validate_environment()
        base_url = get_ollama_base_url()
        endpoint_url = f"{base_url}/v1/chat/completions"
        effective_model = get_ollama_model(override=model)
        timeout_sec = int(os.environ.get("OLLAMA_TIMEOUT", str(DEFAULT_OLLAMA_TIMEOUT)))

        with self._lock:
            self._stop_flags[worker_id] = False

        def _is_stopped() -> bool:
            with self._lock:
                return self._stop_flags.get(worker_id, False)

        return run_autonomous_browser_agent(
            provider_name="ollama",
            endpoint_url=endpoint_url,
            api_key=os.environ.get("OLLAMA_API_KEY", "ollama"),
            model=effective_model,
            job=job,
            port=port,
            worker_id=worker_id,
            dry_run=dry_run,
            stop_check=_is_stopped,
            timeout=timeout_sec,
        )
