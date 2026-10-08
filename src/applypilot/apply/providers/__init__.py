"""AI Providers package for ApplyPilot autonomous application agents."""

from applypilot.apply.providers.base import AIProvider, ProviderResult
from applypilot.apply.providers.claude import ClaudeProvider
from applypilot.apply.providers.gemini import GeminiProvider
from applypilot.apply.providers.openai import OpenAIProvider
from applypilot.apply.providers.ollama import OllamaProvider
from applypilot.apply.providers.factory import get_provider, get_active_provider_name

__all__ = [
    "AIProvider",
    "ProviderResult",
    "ClaudeProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "OllamaProvider",
    "get_provider",
    "get_active_provider_name",
]
