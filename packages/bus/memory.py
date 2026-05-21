"""In-process message bus.

Single-process delivery for tests and the MVP dashboard. Drop-in compatible
with ``RedisBus`` because both implement ``MessageBus``.

Concurrency: ``publish`` and ``subscribe`` are guarded by a re-entrant lock
so handlers that publish further events do not deadlock.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable

from packages.bus.matching import topic_matches
from packages.common.schemas import EventEnvelope

logger = logging.getLogger(__name__)

Handler = Callable[[EventEnvelope], None]

# Cap the introspection list so long-running processes do not retain every
# event indefinitely. The dashboard reads this for the "published" preview.
_PUBLISHED_CAP = 10_000


class InMemoryBus:
    """Typed bus used by tests and the MVP."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self.published: list[EventEnvelope] = []
        self._lock = threading.RLock()

    def subscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            self._handlers[topic].append(handler)

    def publish(self, envelope: EventEnvelope) -> None:
        with self._lock:
            self.published.append(envelope)
            if len(self.published) > _PUBLISHED_CAP:
                # Drop the oldest entry – this list is for visibility only.
                self.published.pop(0)
            handlers_snapshot = [
                (topic, list(handlers))
                for topic, handlers in self._handlers.items()
                if topic_matches(topic, envelope.topic)
            ]

        for _topic, handlers in handlers_snapshot:
            for handler in handlers:
                try:
                    handler(envelope)
                except Exception as exc:
                    logger.error("InMemoryBus handler %s raised: %s", handler, exc)

    def close(self) -> None:
        # Nothing to release for in-process delivery.
        return None

    def __enter__(self) -> "InMemoryBus":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
