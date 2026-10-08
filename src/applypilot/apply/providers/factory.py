"""Provider factory for instantiating the configured AIProvider."""

import os
from typing import Optional

from applypilot.apply.providers.base import AIProvider
from applypilot.apply.providers.claude import ClaudeProvider
from applypilot.apply.providers.gemini import GeminiProvider
from applypilot.apply.providers.openai import OpenAIProvider
from applypilot.apply.providers.ollama import OllamaProvider

SUPPORTED_PROVIDERS = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}


def get_active_provider_name() -> str:
    """Read the current configured provider name from environment."""
    return os.environ.get("AUTO_APPLY_AI_PROVIDER", "claude").lower().strip()


def get_provider(provider_name: Optional[str] = None) -> AIProvider:
    """Instantiate and return the appropriate AIProvider based on configuration.

    Args:
        provider_name: Provider name ('claude', 'gemini', 'openai', 'ollama'). If None,
                       reads from AUTO_APPLY_AI_PROVIDER env var (default: 'claude').

    Returns:
        AIProvider instance.

    Raises:
        ValueError if the provider name is unknown.
    """
    name = (provider_name or get_active_provider_name()).lower().strip()
    cls = SUPPORTED_PROVIDERS.get(name)
    if not cls:
        valid_options = ", ".join(f"'{k}'" for k in SUPPORTED_PROVIDERS.keys())
        raise ValueError(
            f"Unsupported AI provider: '{name}'. "
            f"Valid options for AUTO_APPLY_AI_PROVIDER are: {valid_options}."
        )
    return cls()
