"""Per-contact-type scoring modules.

Each scorer exposes a ``score(contact, event_institutes, topics, taxonomy)``
method with weights tailored to the contact type. The MatchingEngine
dispatches to the correct scorer based on ``contact.contact_type``.

Overlap gate
------------
Previously the score floor (``warm_signal`` + ``recency``) could push a
contact above zero even when there was no institute or topic overlap with
the signal, producing spurious candidates. The base scorer now returns
``0.0`` unless there is at least one institute or topic overlap.

The ``recency`` field used to be a constant additive bonus, which is not
"recency" at all. It is renamed to ``freshness`` and remains at zero until
a real time-based signal is wired in.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringWeights:
    institute_overlap: float = 0.45
    topic_overlap: float = 0.25
    warm_signal: float = 0.20
    freshness: float = 0.10
    cooldown_penalty: float = 1.0


class BaseScorer:
    weights: ScoringWeights = ScoringWeights()

    def score(
        self,
        contact,
        event_institutes: list[str],
        topics: list[str],
        taxonomy,
        rollup: bool = True,
        weights: ScoringWeights | None = None,
    ) -> float:
        effective = weights or self.weights
        normalized_event_ids = {
            taxonomy.parent_for_matching(i, rollup) for i in event_institutes
        }
        normalized_contact_ids = {
            taxonomy.parent_for_matching(i, rollup) for i in contact.focus_areas
        }
        institute_overlap = 1.0 if normalized_event_ids & normalized_contact_ids else 0.0
        topic_overlap = 1.0 if set(topics) & set(contact.stated_thesis_tags) else 0.0

        # Overlap gate: warm_signal alone must not produce a candidate.
        if institute_overlap == 0.0 and topic_overlap == 0.0:
            return 0.0

        return (
            effective.institute_overlap * institute_overlap
            + effective.topic_overlap * topic_overlap
            + effective.warm_signal * (contact.warm_signal_score / 100)
            + effective.freshness  # currently 0 until real freshness signal exists
        )


class InvestorScorer(BaseScorer):
    """Investors care most about institute overlap and warm signal."""
    weights = ScoringWeights(
        institute_overlap=0.50,
        topic_overlap=0.15,
        warm_signal=0.25,
        freshness=0.10,
    )


class GrantOfficerScorer(BaseScorer):
    """Grant officers care about topic/programme alignment."""
    weights = ScoringWeights(
        institute_overlap=0.35,
        topic_overlap=0.40,
        warm_signal=0.15,
        freshness=0.10,
    )


class KOLScorer(BaseScorer):
    """Key Opinion Leaders weight institute overlap and freshness."""
    weights = ScoringWeights(
        institute_overlap=0.40,
        topic_overlap=0.30,
        warm_signal=0.15,
        freshness=0.15,
    )


class PartnerScorer(BaseScorer):
    """Partners weight topic overlap and warm signal equally."""
    weights = ScoringWeights(
        institute_overlap=0.30,
        topic_overlap=0.35,
        warm_signal=0.25,
        freshness=0.10,
    )


class DataCustodianScorer(BaseScorer):
    """Data custodians are highly institute-specific."""
    weights = ScoringWeights(
        institute_overlap=0.60,
        topic_overlap=0.20,
        warm_signal=0.10,
        freshness=0.10,
    )


_SCORER_MAP: dict[str, BaseScorer] = {
    "INVESTOR": InvestorScorer(),
    "GRANT_OFFICER": GrantOfficerScorer(),
    "KOL": KOLScorer(),
    "PARTNER": PartnerScorer(),
    "DATA_CUSTODIAN": DataCustodianScorer(),
}


def get_scorer(contact_type: str) -> BaseScorer:
    """Return the appropriate scorer for a contact type (falls back to BaseScorer)."""
    return _SCORER_MAP.get(contact_type.upper(), BaseScorer())
