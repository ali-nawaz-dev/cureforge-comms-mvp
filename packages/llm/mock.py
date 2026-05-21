from __future__ import annotations

from packages.llm.client import LLMResponse

# Markers we never want to echo verbatim in mock output – callers may log it.
_REDACTED_MARKERS = (
    "[INVESTOR_NDA]",
    "[INTERNAL_ONLY]",
    "INVESTOR_NDA:",
    "INTERNAL_ONLY:",
)


class MockLLMClient:
    """Deterministic mock client.

    Echoes the first line of the prompt so existing tests can assert prompt
    intent ("Summarize this...", "Write a short plain-English rationale..."),
    but scrubs any known NDA/INTERNAL_ONLY markers before echoing so the
    mock cannot accidentally surface confidential payload fragments in logs
    or downstream rationale fields.
    """

    provider = "mock"
    model = "mock-safe-local"

    def complete(self, prompt: str, *, redacted: bool = False) -> LLMResponse:
        safe = prompt
        for marker in _REDACTED_MARKERS:
            safe = safe.replace(marker, "[REDACTED]")
        first_line = safe.strip().splitlines()[0] if safe.strip() else "No prompt"
        return LLMResponse(
            text=f"Mock response: {first_line[:180]}",
            provider=self.provider,
            model=self.model,
            redacted=redacted,
        )

