"""Signal ingestion pipeline.

Deduplication now prefers Postgres (via SignalRepository) when a DATABASE_URL
is set. Falls back to an in-memory set so the codebase keeps working in
tests and development without a live DB.
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

from packages.bus import InMemoryBus
from packages.common.hashing import canonical_json, normalized_content_hash, sha256_hex
from packages.common.logging import configure_json_logging
from packages.common.metrics import SIGNALS_DEDUPED, SIGNALS_INGESTED
from packages.common.schemas import (
    ConfidentialityTier,
    EventEnvelope,
    ExternalSignalEvent,
    InstituteClassification,
)
from packages.common.time import utc_now_iso
from packages.llm import LLMClient, LLMGateway, MockLLMClient, RedactionPolicy
from packages.taxonomy import Taxonomy

logger = logging.getLogger(__name__)
configure_json_logging()


# Cap the in-memory dedup window so long-running workers cannot grow unbounded.
_SEEN_HASH_CAP = 100_000


@dataclass(frozen=True)
class RawSignal:
    source: str
    source_url: str
    raw_text: str
    topics: list[str] = field(default_factory=list)


class IngestionPipeline:
    def __init__(
        self,
        bus: InMemoryBus,
        taxonomy: Taxonomy,
        relevance_keywords: set[str] | None = None,
        threshold: float = 0.2,
        parser_llm: LLMClient | None = None,
        signal_repo=None,
        ledger=None,
    ) -> None:
        self.bus = bus
        self.taxonomy = taxonomy
        self.relevance_keywords = relevance_keywords or {"longevity", "aging", "clinical", "trial"}
        self.threshold = threshold
        self.parser_llm = parser_llm or MockLLMClient()
        # All LLM calls run through the gateway, so any prompt that leaks an
        # NDA marker is refused before reaching the upstream provider.
        self._gateway = LLMGateway(self.parser_llm, RedactionPolicy())
        # LRU dedup window. OrderedDict preserves insertion order so we can
        # evict the oldest entry when we hit ``_SEEN_HASH_CAP``.
        self._seen_hashes: OrderedDict[str, None] = OrderedDict()
        self._dedup_lock = threading.Lock()
        self._signal_repo = signal_repo  # optional SignalRepository
        self._ledger = ledger

    def _try_get_signal_repo(self):
        """Lazily build the SignalRepository if DATABASE_URL is set."""
        if self._signal_repo is not None:
            return self._signal_repo
        import os
        if not os.getenv("DATABASE_URL"):
            return None
        try:
            from packages.db.repositories import SignalRepository
            self._signal_repo = SignalRepository()
            return self._signal_repo
        except Exception as exc:
            logger.warning("Could not init SignalRepository: %s – using in-memory dedup", exc)
            return None

    def _claim_hash(self, content_hash: str) -> bool:
        """Return True iff this call is the first to claim ``content_hash``.

        Race-safe under concurrent ingest. Falls back to in-memory LRU when
        no Postgres repo is available.
        """
        repo = self._try_get_signal_repo()
        if repo and hasattr(repo, "claim_hash"):
            try:
                return repo.claim_hash(content_hash)
            except Exception as exc:
                logger.warning(
                    "Postgres dedup claim failed: %s – falling back to in-memory", exc
                )

        with self._dedup_lock:
            if content_hash in self._seen_hashes:
                return False
            self._seen_hashes[content_hash] = None
            if len(self._seen_hashes) > _SEEN_HASH_CAP:
                self._seen_hashes.popitem(last=False)
            return True

    def _persist_event(
        self, content_hash: str, event: ExternalSignalEvent, signal: RawSignal
    ) -> None:
        repo = self._try_get_signal_repo()
        if not repo:
            return
        try:
            from packages.db.repositories import SignalRecord
            repo.insert(
                SignalRecord(
                    signal_id=str(event.event_id),
                    topic=f"external_signal.{event.source}",
                    source=event.source,
                    content_hash=content_hash,
                    raw_text=signal.raw_text[:4000],
                    event_json=event.model_dump(mode="json"),
                )
            )
        except Exception as exc:
            logger.warning("Could not persist signal to Postgres: %s", exc)

    def ingest(self, signal: RawSignal) -> ExternalSignalEvent | None:
        content_hash = normalized_content_hash(signal.raw_text)

        # Insert-first dedup: only the worker that wins the claim runs the
        # downstream LLM + publish work. This eliminates the prior
        # check-then-act race where two workers could both produce events
        # for the same content.
        if not self._claim_hash(content_hash):
            SIGNALS_DEDUPED.labels(source=signal.source).inc()
            return None

        if self._relevance_score(signal.raw_text) < self.threshold:
            return None

        institute_id = self._classify(signal)
        parsed_summary = self._summarize(signal.raw_text)
        event = ExternalSignalEvent(
            event_id=uuid.uuid4(),
            source=signal.source,  # type: ignore[arg-type]
            source_url=signal.source_url,
            ingest_timestamp=utc_now_iso(),
            content_hash=content_hash,
            parsed_summary=parsed_summary[:500],
            institutes=[InstituteClassification(institute_id=institute_id, confidence=0.8)],
            topics=signal.topics,
            raw_text_ref=f"raw:{content_hash}",
            classifier_confidence=0.8,
            parser_confidence=0.8,
            provenance_hash=sha256_hex(canonical_json({"content_hash": content_hash})),
        )
        self._persist_event(content_hash, event, signal)
        self.bus.publish(
            EventEnvelope(
                event_id=event.event_id,
                topic=f"external_signal.{event.source}.{institute_id}",
                payload=event.model_dump(mode="json"),
                provenance_hash=event.provenance_hash,
            )
        )
        if self._ledger:
            try:
                self._ledger.append(
                    "signal_ingested",
                    {
                        "event_id": str(event.event_id),
                        "source": event.source,
                        "content_hash": content_hash,
                    },
                )
            except Exception as exc:
                logger.warning("Pipeline ledger append failed: %s", exc)
        SIGNALS_INGESTED.labels(source=signal.source).inc()
        logger.info(
            "Ingested signal",
            extra={"content_hash": content_hash, "source": signal.source},
        )
        return event

    def _relevance_score(self, text: str) -> float:
        words = set(text.lower().split())
        if not words:
            return 0.0
        return len(words & self.relevance_keywords) / len(self.relevance_keywords)

    def _classify(self, signal: RawSignal) -> str:
        text = f"{signal.raw_text} {' '.join(signal.topics)}".lower()
        if "brain" in text or "alzheim" in text:
            return "13"
        if "stem" in text or "regenerative" in text:
            return "48"
        if "payor" in text or "aging-as-disease" in text:
            return "34-AaD"
        return "3"

    def _summarize(self, text: str) -> str:
        # External signals are public by definition; the gateway scans for
        # NDA markers as a backstop and refuses to send if any are present.
        payload = {"raw_text": text}

        def _build(safe: dict) -> str:
            return (
                "Summarize this external longevity signal in plain English for a "
                "non-technical reviewer. Keep it under 500 characters.\n\n"
                f"{safe.get('raw_text', '')[:3000]}"
            )

        response = self._gateway.complete_redacted(
            _build, payload, tier=ConfidentialityTier.PUBLIC
        )
        return response.text.removeprefix("Mock response: ").strip()
