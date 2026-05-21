from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    event_id: UUID
    topic: str
    payload: dict[str, Any]
    provenance_hash: str | None = None


class InstituteClassification(BaseModel):
    institute_id: str
    confidence: float = Field(ge=0, le=1)


class ExternalSignalEvent(BaseModel):
    event_id: UUID
    source: Literal["telegram", "pubmed", "clinicaltrials_gov", "biorxiv"]
    source_url: str
    ingest_timestamp: str
    content_hash: str
    parsed_summary: str = Field(max_length=500)
    institutes: list[InstituteClassification]
    topics: list[str]
    raw_text_ref: str
    classifier_confidence: float = Field(ge=0, le=1)
    parser_confidence: float = Field(ge=0, le=1)
    provenance_hash: str


class ConfidentialityTier(str, Enum):
    PUBLIC = "PUBLIC"
    INVESTOR_NDA = "INVESTOR_NDA"
    INTERNAL_ONLY = "INTERNAL_ONLY"


class InternalMilestoneEvent(BaseModel):
    event_id: UUID
    milestone_type: str
    institute_id: str
    title: str = Field(max_length=120)
    summary: str = Field(max_length=500)
    narrative_for_outreach: str = Field(max_length=1000)
    supporting_evidence_refs: list[str]
    confidentiality_tier: ConfidentialityTier
    occurred_at: str
    ingest_timestamp: str
    provenance_hash: str


class OutreachCandidateEvent(BaseModel):
    candidate_id: UUID
    contact_id: UUID
    triggering_event_id: UUID
    match_score: float
    match_rationale: str
    suggested_message_angle: str
    suggested_channel: Literal["email", "linkedin", "x"]
    confidence: float = Field(ge=0, le=1)

