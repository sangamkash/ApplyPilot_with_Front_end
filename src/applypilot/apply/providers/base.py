"""Base AI Provider abstraction for autonomous job application agents.

All providers (Claude, Gemini, OpenAI) inherit from AIProvider and implement
the same lifecycle:
  1. Validate environment configuration & credentials.
  2. Drive Chrome via CDP + Playwright.
  3. Navigate, fill form, upload tailored resume, answer screening questions.
  4. Submit application and strictly verify real submission before marking APPLIED.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ProviderResult:
    """Outcome of an AI application attempt."""
    status: str            # 'applied', 'expired', 'captcha', 'login_issue', 'failed:reason', 'skipped'
    duration_ms: int       # Elapsed time in milliseconds
    error: Optional[str] = None
    actions_count: int = 0
    total_cost_usd: float = 0.0
    verified: bool = False


class AIProvider(ABC):
    """Abstract base class for auto-apply AI providers."""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def validate_environment(self) -> None:
        """Validate that all credentials and binaries needed for this provider are present.

        Raises:
            RuntimeError or ValueError if configuration is missing or invalid.
        """
        pass

    @abstractmethod
    def run(
        self,
        job: dict,
        port: int,
        worker_id: int = 0,
        model: Optional[str] = None,
        dry_run: bool = False,
    ) -> tuple[str, int]:
        """Execute autonomous job application session for one job.

        Args:
            job: Job dict from database.
            port: CDP debugging port of Chrome.
            worker_id: Numeric worker ID for concurrency.
            model: Optional model override.
            dry_run: If True, do not click final submit button.

        Returns:
            Tuple of (status_string, duration_ms).
        """
        pass

    @abstractmethod
    def stop(self, worker_id: int) -> None:
        """Terminate any running process/task for the given worker."""
        pass
