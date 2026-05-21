"""Redis Pub/Sub bus implementation.

Implements the same subscribe/publish interface as InMemoryBus so every
layer can work without knowing which backend is active.

Pattern-subscriptions use Redis keyspace patterns:
  - Exact topic  "signal.ingested"
  - Wildcard     "signal.*"  → translated to Redis pattern "signal.*"

Usage:
    bus = RedisBus(url="redis://localhost:6379/0")
    bus.subscribe("signal.*", handler)
    bus.publish(envelope)   # fire-and-forget to Redis channel
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


class RedisBus:
    """Redis-backed message bus with in-process fan-out to subscribers."""

    def __init__(self, url: str = "redis://localhost:6379/0") -> None:
        import redis  # imported lazily so tests without Redis can skip

        self._client = redis.from_url(url, decode_responses=True)
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._pubsub = self._client.pubsub(ignore_subscribe_messages=True)
        self._listener_thread: threading.Thread | None = None
        self._started = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Register a handler for a topic (wildcards supported)."""
        self._handlers[topic].append(handler)
        if topic.endswith(".*"):
            redis_pattern = topic  # Redis psubscribe supports glob patterns
            self._pubsub.psubscribe(**{redis_pattern: self._dispatch_pattern})
        else:
            self._pubsub.subscribe(**{topic: self._dispatch_exact})
        self._ensure_listener()

    def publish(self, envelope: EventEnvelope) -> None:
        """Publish an event to Redis.

        Delivery to local subscribers happens exclusively through the Redis
        listener thread, so handlers run exactly once per publish even when
        the same process is both publisher and subscriber.
        """
        payload = envelope.model_dump_json()
        self._client.publish(envelope.topic, payload)

    def close(self) -> None:
        """Stop the listener thread and release the Redis connection."""
        self._started = False
        thread = self._listener_thread
        if thread is not None and hasattr(thread, "stop"):
            try:
                thread.stop()
            except Exception as exc:
                logger.debug("RedisBus listener stop error: %s", exc)
        try:
            self._pubsub.close()
        except Exception as exc:
            logger.debug("RedisBus pubsub close error: %s", exc)
        try:
            self._client.close()
        except Exception as exc:
            logger.debug("RedisBus client close error: %s", exc)
        self._listener_thread = None

    def __enter__(self) -> "RedisBus":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dispatch_exact(self, message: dict) -> None:
        try:
            envelope = EventEnvelope.model_validate_json(message["data"])
            self._fan_out(envelope)
        except Exception as exc:
            logger.warning("RedisBus dispatch error: %s", exc)

    def _dispatch_pattern(self, message: dict) -> None:
        try:
            envelope = EventEnvelope.model_validate_json(message["data"])
            self._fan_out(envelope)
        except Exception as exc:
            logger.warning("RedisBus pattern dispatch error: %s", exc)

    def _fan_out(self, envelope: EventEnvelope) -> None:
        for topic, handlers in self._handlers.items():
            if topic_matches(topic, envelope.topic):
                for h in handlers:
                    try:
                        h(envelope)
                    except Exception as exc:
                        logger.error("Handler %s raised: %s", h, exc)

    def _ensure_listener(self) -> None:
        if self._started:
            return
        self._started = True
        # ``run_in_thread`` is the modern redis-py listener; fall back to a
        # manual ``get_message`` loop if the backend (older redis-py, custom
        # pubsub) does not provide it.
        if hasattr(self._pubsub, "run_in_thread"):
            self._listener_thread = self._pubsub.run_in_thread(
                sleep_time=0.01, daemon=True
            )
            return
        self._listener_thread = threading.Thread(
            target=self._poll_messages,
            kwargs={"sleep_time": 0.01},
            daemon=True,
        )
        self._listener_thread.start()

    def _poll_messages(self, sleep_time: float = 0.01) -> None:
        import time

        while self._started:
            try:
                msg = self._pubsub.get_message(timeout=sleep_time)
            except Exception as exc:
                logger.debug("RedisBus poll error: %s", exc)
                time.sleep(sleep_time)
                continue
            if not msg:
                continue
            # subscribe-style messages register a callback via kwargs to
            # subscribe/psubscribe, so they fire automatically. Anything that
            # reaches here is for a topic without an installed callback.
