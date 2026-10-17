"""LLM provider factory: mock | openai_compatible | anthropic (| malicious, scenario suite only)."""
from __future__ import annotations

from typing import Optional

from ...config import Settings, get_settings
from .base import LLMError, LLMProvider, LLMResponse, ToolCall
from .malicious import MaliciousLLM, ScriptedLLM
from .mock import MockLLM

__all__ = ["LLMError", "LLMProvider", "LLMResponse", "ToolCall", "MockLLM", "MaliciousLLM", "ScriptedLLM",
           "get_provider"]


def get_provider(settings: Optional[Settings] = None, name: Optional[str] = None) -> LLMProvider:
    s = settings or get_settings()
    provider = (name or s.llm_provider).lower()
    if provider == "mock":
        return MockLLM()
    if provider == "openai_compatible":
        from .openai_compatible import OpenAICompatibleLLM

        return OpenAICompatibleLLM(s.llm_base_url, s.llm_api_key, s.llm_model)
    if provider == "anthropic":
        from .anthropic import AnthropicLLM

        return AnthropicLLM(s.anthropic_api_key, s.anthropic_model)
    if provider == "malicious":
        return MaliciousLLM()
    raise LLMError(f"Unknown LLM_PROVIDER '{provider}'.")
