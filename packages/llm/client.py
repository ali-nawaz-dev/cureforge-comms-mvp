from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    redacted: bool = False


class LLMClient(Protocol):
    provider: str
    model: str

    def complete(self, prompt: str, *, redacted: bool = False) -> LLMResponse:
        """Return a completion for an already safety-checked prompt."""

