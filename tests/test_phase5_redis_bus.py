"""Phase 5: RedisBus tests using fakeredis.

Asserts:
- An envelope published by RedisBus reaches a subscriber registered on the
  *same* bus exactly once (no double delivery).
- Wildcard subscriptions match topics that start with the prefix.
- ``close()`` releases resources without raising.
"""
from __future__ import annotations

import threading
import time
from uuid import uuid4

import pytest

from packages.common.schemas import EventEnvelope

fakeredis = pytest.importorskip("fakeredis")


@pytest.fixture
def redis_bus(monkeypatch):
    """Construct a RedisBus backed by an in-memory fakeredis server.

    fakeredis itself depends on the real ``redis`` package, so we keep the
    package loaded and only replace ``redis.from_url`` with a constructor
    that returns a fakeredis client.
    """
    import redis as real_redis

    server = fakeredis.FakeServer()

    def _from_url(url, decode_responses=True):
        return fakeredis.FakeRedis(server=server, decode_responses=decode_responses)

    monkeypatch.setattr(real_redis, "from_url", _from_url)

    from packages.bus.redis_bus import RedisBus

    bus = RedisBus(url="redis://fake")
    yield bus
    bus.close()


def _wait_for(predicate, timeout_s: float = 1.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("predicate not satisfied within timeout")


def test_redis_bus_delivers_exactly_once(redis_bus) -> None:
    """Listener thread is the only delivery path; no in-process double fire."""
    received: list[EventEnvelope] = []
    received_lock = threading.Lock()

    def handler(env: EventEnvelope) -> None:
        with received_lock:
            received.append(env)

    redis_bus.subscribe("external_signal.telegram.13", handler)
    envelope = EventEnvelope(
        event_id=uuid4(),
        topic="external_signal.telegram.13",
        payload={"k": 1},
    )
    redis_bus.publish(envelope)
    _wait_for(lambda: len(received) >= 1)
    # Give the listener a beat to surface any spurious second delivery.
    time.sleep(0.05)
    assert len(received) == 1


def test_redis_bus_wildcard_match(redis_bus) -> None:
    received: list[EventEnvelope] = []
    lock = threading.Lock()

    def handler(env: EventEnvelope) -> None:
        with lock:
            received.append(env)

    redis_bus.subscribe("external_signal.*", handler)
    redis_bus.publish(
        EventEnvelope(
            event_id=uuid4(),
            topic="external_signal.telegram.99",
            payload={"k": 2},
        )
    )
    _wait_for(lambda: len(received) >= 1)
    assert received[0].topic == "external_signal.telegram.99"


def test_redis_bus_close_is_idempotent(redis_bus) -> None:
    redis_bus.close()
    redis_bus.close()
