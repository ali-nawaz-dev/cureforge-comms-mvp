"""Bus factory: returns InMemoryBus or RedisBus based on BUS_BACKEND env var."""
from __future__ import annotations

import logging
import os

from packages.bus.protocol import MessageBus

logger = logging.getLogger(__name__)


def get_bus() -> MessageBus:
    """Return a bus instance configured by ``BUS_BACKEND``.

    - ``BUS_BACKEND=redis``  -> ``RedisBus(REDIS_URL)``
    - anything else          -> ``InMemoryBus`` (default / tests)

    The Redis URL is *not* logged because it may contain credentials.
    """
    backend = os.getenv("BUS_BACKEND", "memory").lower()
    if backend == "redis":
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            from packages.bus.redis_bus import RedisBus

            bus = RedisBus(url=redis_url)
            logger.info("Bus backend: Redis")
            return bus
        except Exception as exc:
            logger.warning("Redis bus init failed (%s), falling back to InMemoryBus", exc)
    from packages.bus.memory import InMemoryBus

    logger.info("Bus backend: InMemory")
    return InMemoryBus()
