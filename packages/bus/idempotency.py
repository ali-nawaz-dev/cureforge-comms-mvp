"""Per-consumer idempotency cache.

Bus delivery is at-least-once: the same envelope may arrive twice across a
worker restart or a Redis reconnect. Every subscriber should keep an LRU of
event ids it has already processed and skip the duplicates.

``IdempotencyCache`` is intentionally tiny so it can be embedded in any
worker without a hard runtime dependency on Redis.
"""
from __future__ import annotations

import threading
from collections import OrderedDict


class IdempotencyCache:
    def __init__(self, capacity: int = 10_000) -> None:
        self._capacity = capacity
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def claim(self, event_id: str) -> bool:
        """Return True if ``event_id`` has not been seen before."""
        if not event_id:
            return True
        with self._lock:
            if event_id in self._seen:
                # Move to end to mark as most-recently-seen.
                self._seen.move_to_end(event_id)
                return False
            self._seen[event_id] = None
            if len(self._seen) > self._capacity:
                self._seen.popitem(last=False)
            return True

    def __len__(self) -> int:
        return len(self._seen)
