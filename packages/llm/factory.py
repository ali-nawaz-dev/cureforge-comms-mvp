"""LLM client factory.

Provider routing:
  Layer 1 parsing     → Groq + LLaMA 3.3 70B  (LLM_PROVIDER=groq)
  Layer 2 rationale   → GPT-4o                 (LLM_PROVIDER=openai)
  Layer 3A drafting   → GPT-4o                 (LLM_PROVIDER=openai)
  Default / testing   → Mock                   (LLM_PROVIDER=mock)

Anthropic client is retained for future phase switches.
The provider is swappable without touching any prompt logic.
"""
from __future__ import annotations

import os

from packages.llm.client import LLMClient
from packages.llm.http_clients import AnthropicLLMClient, GroqLLMClient, OpenAILLMClient
from packages.llm.mock import MockLLMClient


def build_llm_client(provider: str | None = None, **kwargs) -> LLMClient:
    """Build an LLM client from provider name (or LLM_PROVIDER env var)."""
    selected = (provider or os.getenv("LLM_PROVIDER", "mock")).lower()
    if selected == "mock":
        return MockLLMClient()
    if selected == "groq":
        return GroqLLMClient(**{k: v for k, v in kwargs.items() if k in ("api_key", "model")})
    if selected == "openai":
        return OpenAILLMClient(**{k: v for k, v in kwargs.items() if k in ("api_key", "model")})
    if selected == "anthropic":
        # Retained for future phase — not the active default
        return AnthropicLLMClient(**{k: v for k, v in kwargs.items() if k in ("api_key", "model")})
    raise ValueError(
        f"Unsupported LLM provider: {selected!r}. "
        "Valid values: mock, groq, openai, anthropic"
    )


def build_parser_llm() -> LLMClient:
    """Layer 1 parsing LLM — Groq + LLaMA 3.3 70B (falls back to mock)."""
    provider = os.getenv("PARSER_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "mock"))
    return build_llm_client(provider=provider)


def build_rationale_llm() -> LLMClient:
    """Layer 2 rationale LLM — GPT-4o (falls back to mock)."""
    provider = os.getenv("RATIONALE_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "mock"))
    return build_llm_client(provider=provider)


def build_drafting_llm() -> LLMClient:
    """Layer 3A drafting LLM — GPT-4o (falls back to mock)."""
    provider = os.getenv("DRAFTING_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "mock"))
    return build_llm_client(provider=provider)
