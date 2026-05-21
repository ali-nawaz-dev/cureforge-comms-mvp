"""Polling worker base.

External connectors (Telegram, PubMed, ClinicalTrials.gov, …) all share the
same loop shape: sleep, fetch, normalise, hand off to the ingestion
pipeline, repeat. The previous code duplicated this logic five different
times. This base owns:

- The sleep / backoff schedule (exponential up to ``max_backoff_seconds``).
- A graceful ``stop()`` so daemons can shut down cleanly.
- A structured log per cycle.

Subclasses only implement ``fetch_batch`` which returns ``RawSignal``s.
"""
from __future__ import annotations

import abc
import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass

from services.ingestion.pipeline import IngestionPipeline, RawSignal

logger = logging.getLogger(__name__)


@dataclass
class PollingConfig:
    name: str
    interval_seconds: int
    max_backoff_seconds: int = 7200


class PollingWorker(abc.ABC):
    def __init__(self, pipeline: IngestionPipeline, config: PollingConfig) -> None:
        self._pipeline = pipeline
        self._config = config
        self._stop_event = threading.Event()

    @abc.abstractmethod
    def fetch_batch(self) -> Iterable[RawSignal]:
        """Return the next batch of raw signals for this connector."""

    def run(self) -> None:
        backoff = self._config.interval_seconds
        logger.info(
            "Polling worker started",
            extra={"name": self._config.name, "interval_seconds": backoff},
        )
        while not self._stop_event.is_set():
            try:
                count = 0
                for signal in self.fetch_batch():
                    if self._stop_event.is_set():
                        break
                    if self._pipeline.ingest(signal) is not None:
                        count += 1
                logger.info(
                    "Polling cycle complete",
                    extra={"name": self._config.name, "ingested": count},
                )
                backoff = self._config.interval_seconds
            except Exception as exc:
                logger.warning(
                    "Polling cycle failed",
                    extra={"name": self._config.name, "error": str(exc), "backoff": backoff},
                )
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, self._config.max_backoff_seconds)
                continue
            self._stop_event.wait(self._config.interval_seconds)

    def stop(self) -> None:
        self._stop_event.set()
