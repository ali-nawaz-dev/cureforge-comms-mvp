"""Optional Prometheus metrics.

If ``prometheus_client`` is not installed (tests, minimal envs) the helpers
degrade to no-ops so callers can use them unconditionally.
"""
from __future__ import annotations

from typing import Any

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )

    _ENABLED = True
except Exception:  # pragma: no cover - tested only in the test env
    _ENABLED = False
    CONTENT_TYPE_LATEST = "text/plain"

    def generate_latest() -> bytes:  # type: ignore[override]
        return b""

    class _Noop:
        def labels(self, **_kwargs: Any) -> "_Noop":
            return self

        def inc(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def observe(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    Counter = _Noop  # type: ignore[assignment]
    Histogram = _Noop  # type: ignore[assignment]


if _ENABLED:
    SIGNALS_INGESTED = Counter(
        "cureforge_signals_ingested_total",
        "Signals accepted by the ingestion pipeline.",
        ["source"],
    )
    SIGNALS_DEDUPED = Counter(
        "cureforge_signals_deduped_total",
        "Signals dropped because the content hash was already seen.",
        ["source"],
    )
    OUTREACH_CANDIDATES_PUBLISHED = Counter(
        "cureforge_outreach_candidates_total",
        "Outreach candidates published by the matcher worker.",
        ["topic"],
    )
    OUTREACH_SENT = Counter(
        "cureforge_outreach_sent_total",
        "Outreach emails handed off to the sender.",
        ["mode", "delivered"],
    )
    LLM_LATENCY = Histogram(
        "cureforge_llm_latency_seconds",
        "Latency of LLM completion requests, by provider.",
        ["provider"],
    )
else:  # pragma: no cover
    SIGNALS_INGESTED = Counter()
    SIGNALS_DEDUPED = Counter()
    OUTREACH_CANDIDATES_PUBLISHED = Counter()
    OUTREACH_SENT = Counter()
    LLM_LATENCY = Histogram()


def metrics_response() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for a Prometheus scrape."""
    return generate_latest(), CONTENT_TYPE_LATEST
