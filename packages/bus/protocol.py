"""MessageBus protocol shared by InMemoryBus and RedisBus.

Workers and services should type-hint ``MessageBus`` so the backend can be
swapped without touching call sites. A ``DLQ_PREFIX`` convention is shared
so subscribers can publish failed events to ``dlq.<original_topic>`` for
out-of-band inspection.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from packages.common.schemas import EventEnvelope

Handler = Callable[[EventEnvelope], None]

DLQ_PREFIX = "dlq."


@runtime_checkable
class MessageBus(Protocol):
    def subscribe(self, topic: str, handler: Handler) -> None: ...

    def publish(self, envelope: EventEnvelope) -> None: ...

    def close(self) -> None: ...
