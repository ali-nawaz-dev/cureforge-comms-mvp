"""HTTP LLM clients: Groq (Layer 1 parsing), OpenAI GPT-4o (Layer 2 rationale + Layer 3A drafting).

Anthropic client is retained for future phase switches.

Hardening over the previous version:
- Empty API keys raise ``LLMConfigError`` at construction for non-mock providers.
- HTTP / JSON-shape errors map to domain exceptions (``LLMTransientError``,
  ``LLMResponseError``) so callers can act on them instead of catching bare
  ``Exception``.
- All clients use a shared ``_post_json`` helper. Anthropic's bespoke path
  was collapsed into the helper for consistency.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from packages.llm.client import LLMResponse

logger = logging.getLogger(__name__)


class LLMConfigError(RuntimeError):
    """Raised when an LLM client is configured incorrectly (e.g. empty key)."""


class LLMTransientError(RuntimeError):
    """Raised on retriable HTTP/network failures from an LLM provider."""


class LLMResponseError(RuntimeError):
    """Raised when an LLM response is malformed or missing expected fields."""


class _HTTPLLMClient:
    """Shared parts of an HTTP LLM client."""

    provider = "http"

    def __init__(
        self,
        *,
        api_key_env: str,
        model_env: str,
        default_model: str,
        api_key: str | None,
        model: str | None,
    ) -> None:
        self.api_key = api_key or os.getenv(api_key_env, "")
        self.model = model or os.getenv(model_env, default_model)
        if not self.api_key:
            raise LLMConfigError(
                f"{self.provider} client requires {api_key_env} "
                "(or an explicit api_key argument). Use the mock provider for tests."
            )


class GroqLLMClient(_HTTPLLMClient):
    provider = "groq"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(
            api_key_env="GROQ_API_KEY",
            model_env="GROQ_MODEL",
            default_model="llama-3.3-70b-versatile",
            api_key=api_key,
            model=model,
        )

    def complete(self, prompt: str, *, redacted: bool = False) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        data = _post_json(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
            },
            payload=payload,
        )
        return LLMResponse(
            text=_extract_chat_text(data),
            provider=self.provider,
            model=self.model,
            redacted=redacted,
        )


class AnthropicLLMClient(_HTTPLLMClient):
    provider = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(
            api_key_env="ANTHROPIC_API_KEY",
            model_env="ANTHROPIC_MODEL",
            default_model="claude-3-5-sonnet-latest",
            api_key=api_key,
            model=model,
        )

    def complete(self, prompt: str, *, redacted: bool = False) -> LLMResponse:
        payload = {
            "model": self.model,
            "max_tokens": 800,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            payload=payload,
        )
        try:
            text = data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(f"Unexpected Anthropic response shape: {exc}") from exc
        return LLMResponse(
            text=text,
            provider=self.provider,
            model=self.model,
            redacted=redacted,
        )


class OpenAILLMClient(_HTTPLLMClient):
    """GPT-4o client for matching rationale and outreach drafting."""

    provider = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(
            api_key_env="OPENAI_API_KEY",
            model_env="OPENAI_MODEL",
            default_model="gpt-4o",
            api_key=api_key,
            model=model,
        )

    def complete(self, prompt: str, *, redacted: bool = False) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        data = _post_json(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
            },
            payload=payload,
        )
        return LLMResponse(
            text=_extract_chat_text(data),
            provider=self.provider,
            model=self.model,
            redacted=redacted,
        )


def _post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout: int = 30,
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="ignore")
        if 500 <= exc.code < 600:
            raise LLMTransientError(f"HTTP {exc.code}: {body}") from exc
        raise LLMResponseError(f"HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise LLMTransientError(f"Network error: {exc}") from exc


def _extract_chat_text(data: dict[str, object]) -> str:
    try:
        return data["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMResponseError(f"Unexpected chat response shape: {exc}") from exc
