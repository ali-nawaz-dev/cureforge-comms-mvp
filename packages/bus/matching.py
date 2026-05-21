"""Shared topic-pattern matching for all bus backends.

Subscriptions support exact matches (``"signal.ingested"``) and a single
trailing wildcard (``"signal.*"``). Both ``InMemoryBus`` and ``RedisBus``
must agree on the rules; keep the single implementation here.
"""
from __future__ import annotations


def topic_matches(subscription: str, topic: str) -> bool:
    if subscription == topic:
        return True
    if subscription.endswith(".*"):
        return topic.startswith(subscription[:-1])
    return False
