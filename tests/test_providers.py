"""Unit tests for ApplyPilot AI Provider selection, abstraction, and environment configuration."""

import os
import pytest

from applypilot.apply.providers import (
    AIProvider,
    ClaudeProvider,
    GeminiProvider,
    OpenAIProvider,
    get_provider,
    get_active_provider_name,
)
from applypilot.config import get_tier, check_tier


def test_get_active_provider_name(monkeypatch):
    monkeypatch.delenv("AUTO_APPLY_AI_PROVIDER", raising=False)
    assert get_active_provider_name() == "claude"

    monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "gemini")
    assert get_active_provider_name() == "gemini"

    monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "OPENAI")
    assert get_active_provider_name() == "openai"


def test_get_provider_instances(monkeypatch):
    monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "claude")
    prov_claude = get_provider()
    assert isinstance(prov_claude, ClaudeProvider)
    assert prov_claude.name == "claude"

    monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "gemini")
    prov_gemini = get_provider()
    assert isinstance(prov_gemini, GeminiProvider)
    assert prov_gemini.name == "gemini"

    monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "openai")
    prov_openai = get_provider()
    assert isinstance(prov_openai, OpenAIProvider)
    assert prov_openai.name == "openai"


def test_get_provider_unsupported(monkeypatch):
    monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", "unsupported_ai")
    with pytest.raises(ValueError, match="Unsupported AI provider"):
        get_provider()


def test_gemini_provider_validation(monkeypatch):
    prov = GeminiProvider()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY environment variable is required"):
        prov.validate_environment()

    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key_123")
    prov.validate_environment()  # Should succeed without error


def test_openai_provider_validation(monkeypatch):
    prov = OpenAIProvider()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY environment variable is required"):
        prov.validate_environment()

    monkeypatch.setenv("OPENAI_API_KEY", "test_openai_key_123")
    prov.validate_environment()  # Should succeed without error


def test_provider_switching_without_code_changes(monkeypatch):
    """Verify Requirement 6: changing AUTO_APPLY_AI_PROVIDER switches provider without code changes."""
    providers = ["claude", "gemini", "openai"]
    for p_name in providers:
        monkeypatch.setenv("AUTO_APPLY_AI_PROVIDER", p_name)
        p = get_provider()
        assert p.name == p_name
