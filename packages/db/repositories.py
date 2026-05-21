"""Repository classes for all Postgres tables.

Each repository wraps a psycopg connection/pool and exposes typed CRUD
methods that correspond to the DDL in migrations/001_core_schema.sql.
All methods accept an optional `conn` parameter; if None they open one
via get_connection(). This makes them easy to test with a fixture conn.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from packages.db.connection import get_connection


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


def _row_to_dict(row, cursor) -> dict:
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Signal repository
#
# Schema is owned by migrations/001_core_schema.sql – this module must not
# create or alter tables. Run ``packages.db.connection.run_migrations`` (or
# the migration init container in production) before using these repos.
# ---------------------------------------------------------------------------


@dataclass
class SignalRecord:
    signal_id: str
    topic: str
    source: str
    content_hash: str
    raw_text: str | None
    event_json: dict
    created_at: datetime | None = None


class SignalRepository:
    def __init__(self, conn=None):
        self._conn = conn

    def _ctx(self):
        if self._conn:
            from contextlib import nullcontext
            return nullcontext(self._conn)
        return get_connection()

    def exists_by_hash(self, content_hash: str) -> bool:
        with self._ctx() as conn:
            row = conn.execute(
                "SELECT 1 FROM signals WHERE content_hash = %s LIMIT 1", (content_hash,)
            ).fetchone()
            return row is not None

    def claim_hash(self, content_hash: str) -> bool:
        """Atomically claim a content_hash.

        Returns True only if this call inserted a new row. Other concurrent
        ingests that lose the race get False and skip downstream work.
        """
        with self._ctx() as conn:
            row = conn.execute(
                """
                INSERT INTO signals (signal_id, topic, source, content_hash, raw_text, event_json)
                VALUES (gen_random_uuid(), 'external_signal.pending', 'pending', %s, NULL, '{}'::jsonb)
                ON CONFLICT (content_hash) DO NOTHING
                RETURNING content_hash
                """,
                (content_hash,),
            ).fetchone()
            conn.commit()
            return row is not None

    def insert(self, record: SignalRecord) -> None:
        with self._ctx() as conn:
            # On conflict update fields other than the immutable identifiers so
            # the row that was claimed via `claim_hash` is filled in atomically.
            conn.execute(
                """
                INSERT INTO signals (signal_id, topic, source, content_hash, raw_text, event_json)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (content_hash) DO UPDATE SET
                    topic = EXCLUDED.topic,
                    source = EXCLUDED.source,
                    raw_text = EXCLUDED.raw_text,
                    event_json = EXCLUDED.event_json
                """,
                (
                    record.signal_id,
                    record.topic,
                    record.source,
                    record.content_hash,
                    record.raw_text,
                    json.dumps(record.event_json),
                ),
            )
            conn.commit()

    def list_recent(self, limit: int = 50) -> list[SignalRecord]:
        with self._ctx() as conn:
            rows = conn.execute(
                "SELECT signal_id, topic, source, content_hash, raw_text, event_json, created_at "
                "FROM signals ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
            return [
                SignalRecord(
                    signal_id=str(r[0]),
                    topic=r[1],
                    source=r[2],
                    content_hash=r[3],
                    raw_text=r[4],
                    event_json=r[5] if isinstance(r[5], dict) else json.loads(r[5]),
                    created_at=r[6],
                )
                for r in rows
            ]


# ---------------------------------------------------------------------------
# Contact repository
# ---------------------------------------------------------------------------

@dataclass
class ContactRecord:
    contact_id: str
    contact_type: str
    name: str
    organization: str | None
    role: str | None
    focus_areas: list[str]
    stated_thesis_tags: list[str]
    under_nda: bool
    disinterest_flag: bool
    active_conversation_token: str | None
    last_contact_from_us_date: date | None
    warm_signal_score: int
    source_provenance: dict


class ContactRepository:
    def __init__(self, conn=None):
        self._conn = conn

    def _ctx(self):
        if self._conn:
            from contextlib import nullcontext
            return nullcontext(self._conn)
        return get_connection()

    def upsert(self, record: ContactRecord) -> None:
        with self._ctx() as conn:
            conn.execute(
                """
                INSERT INTO contacts (
                    contact_id, contact_type, name, organization, role,
                    focus_areas, stated_thesis_tags, under_nda, disinterest_flag,
                    active_conversation_token, last_contact_from_us_date,
                    warm_signal_score, source_provenance, updated_at
                ) VALUES (
                    %s, %s::contact_type, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s::jsonb, now()
                )
                ON CONFLICT (contact_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    organization = EXCLUDED.organization,
                    role = EXCLUDED.role,
                    focus_areas = EXCLUDED.focus_areas,
                    stated_thesis_tags = EXCLUDED.stated_thesis_tags,
                    under_nda = EXCLUDED.under_nda,
                    disinterest_flag = EXCLUDED.disinterest_flag,
                    active_conversation_token = EXCLUDED.active_conversation_token,
                    last_contact_from_us_date = EXCLUDED.last_contact_from_us_date,
                    warm_signal_score = EXCLUDED.warm_signal_score,
                    source_provenance = EXCLUDED.source_provenance,
                    updated_at = now()
                """,
                (
                    record.contact_id,
                    record.contact_type,
                    record.name,
                    record.organization,
                    record.role,
                    record.focus_areas,
                    record.stated_thesis_tags,
                    record.under_nda,
                    record.disinterest_flag,
                    record.active_conversation_token,
                    record.last_contact_from_us_date,
                    record.warm_signal_score,
                    json.dumps(record.source_provenance),
                ),
            )
            conn.commit()

    def get_last_contact_date(self, contact_id: str) -> date | None:
        with self._ctx() as conn:
            row = conn.execute(
                "SELECT last_contact_from_us_date FROM contacts WHERE contact_id = %s",
                (contact_id,),
            ).fetchone()
            return row[0] if row else None

    def get_active_conversation_token(self, contact_id: str) -> str | None:
        with self._ctx() as conn:
            row = conn.execute(
                "SELECT active_conversation_token FROM contacts WHERE contact_id = %s",
                (contact_id,),
            ).fetchone()
            return row[0] if row else None

    def update_conversation_token(self, contact_id: str, token: str | None) -> None:
        """Set or clear the active_conversation_token. None clears it (revocation)."""
        with self._ctx() as conn:
            conn.execute(
                "UPDATE contacts SET active_conversation_token = %s, updated_at = now() WHERE contact_id = %s",
                (token, contact_id),
            )
            conn.commit()

    def set_last_contact_date(self, contact_id: str, when: date) -> None:
        """Stamp last_contact_from_us_date – used by sender after a successful send."""
        with self._ctx() as conn:
            conn.execute(
                "UPDATE contacts SET last_contact_from_us_date = %s, updated_at = now() WHERE contact_id = %s",
                (when, contact_id),
            )
            conn.commit()

    def list_all(self) -> list[ContactRecord]:
        with self._ctx() as conn:
            rows = conn.execute(
                """
                SELECT contact_id, contact_type, name, organization, role,
                       focus_areas, stated_thesis_tags, under_nda, disinterest_flag,
                       active_conversation_token, last_contact_from_us_date,
                       warm_signal_score, source_provenance
                FROM contacts
                """
            ).fetchall()
            return [
                ContactRecord(
                    contact_id=str(r[0]),
                    contact_type=str(r[1]),
                    name=r[2],
                    organization=r[3],
                    role=r[4],
                    focus_areas=list(r[5]) if r[5] else [],
                    stated_thesis_tags=list(r[6]) if r[6] else [],
                    under_nda=bool(r[7]),
                    disinterest_flag=bool(r[8]),
                    active_conversation_token=r[9],
                    last_contact_from_us_date=r[10],
                    warm_signal_score=int(r[11]),
                    source_provenance=r[12] if isinstance(r[12], dict) else json.loads(r[12] or "{}"),
                )
                for r in rows
            ]


# ---------------------------------------------------------------------------
# MatchingRun repository
# ---------------------------------------------------------------------------

@dataclass
class MatchingRunRecord:
    matching_run_id: str
    triggering_event_id: str
    triggering_topic: str
    scoring_config: dict
    created_at: datetime | None = None


class MatchingRunRepository:
    def __init__(self, conn=None):
        self._conn = conn

    def _ctx(self):
        if self._conn:
            from contextlib import nullcontext
            return nullcontext(self._conn)
        return get_connection()

    def insert(self, record: MatchingRunRecord) -> None:
        with self._ctx() as conn:
            conn.execute(
                """
                INSERT INTO matching_runs (matching_run_id, triggering_event_id,
                    triggering_topic, scoring_config)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (
                    record.matching_run_id,
                    record.triggering_event_id,
                    record.triggering_topic,
                    json.dumps(record.scoring_config),
                ),
            )
            conn.commit()


# ---------------------------------------------------------------------------
# OutreachCandidate repository
# ---------------------------------------------------------------------------

@dataclass
class OutreachCandidateRecord:
    candidate_id: str
    matching_run_id: str
    contact_id: str
    triggering_event_id: str
    match_score: float
    match_rationale: str
    suggested_message_angle: str | None
    suggested_channel: str | None
    confidence: float
    suppressed_reason: str | None
    provenance_hash: str | None


class OutreachCandidateRepository:
    def __init__(self, conn=None):
        self._conn = conn

    def _ctx(self):
        if self._conn:
            from contextlib import nullcontext
            return nullcontext(self._conn)
        return get_connection()

    def insert(self, record: OutreachCandidateRecord) -> None:
        with self._ctx() as conn:
            conn.execute(
                """
                INSERT INTO outreach_candidates (
                    candidate_id, matching_run_id, contact_id, triggering_event_id,
                    match_score, match_rationale, suggested_message_angle,
                    suggested_channel, confidence, suppressed_reason, provenance_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    record.candidate_id,
                    record.matching_run_id,
                    record.contact_id,
                    record.triggering_event_id,
                    record.match_score,
                    record.match_rationale,
                    record.suggested_message_angle,
                    record.suggested_channel,
                    record.confidence,
                    record.suppressed_reason,
                    record.provenance_hash,
                ),
            )
            conn.commit()

    def list_by_run(self, matching_run_id: str) -> list[OutreachCandidateRecord]:
        with self._ctx() as conn:
            rows = conn.execute(
                """
                SELECT candidate_id, matching_run_id, contact_id, triggering_event_id,
                       match_score, match_rationale, suggested_message_angle,
                       suggested_channel, confidence, suppressed_reason, provenance_hash
                FROM outreach_candidates WHERE matching_run_id = %s
                """,
                (matching_run_id,),
            ).fetchall()
            return [
                OutreachCandidateRecord(
                    candidate_id=str(r[0]),
                    matching_run_id=str(r[1]),
                    contact_id=str(r[2]),
                    triggering_event_id=str(r[3]),
                    match_score=float(r[4]),
                    match_rationale=r[5],
                    suggested_message_angle=r[6],
                    suggested_channel=r[7],
                    confidence=float(r[8]),
                    suppressed_reason=r[9],
                    provenance_hash=r[10],
                )
                for r in rows
            ]


# ---------------------------------------------------------------------------
# Approval repository
# ---------------------------------------------------------------------------

@dataclass
class ApprovalRecord:
    approval_id: str
    draft_id: str
    state: str
    required_role: str
    reviewer_identity: str | None
    reviewer_role: str | None
    token_hash: str | None
    created_at: datetime | None = None


class ApprovalRepository:
    """Persists HITL draft state.

    Token storage policy: tokens are stored hashed (SHA-256), never raw. The
    in-memory ``ApprovalToken`` holds the raw value the reviewer authenticated
    with; the database only retains a hash so a DB leak does not equate to a
    sender authorization.
    """

    def __init__(self, conn=None):
        self._conn = conn

    def _ctx(self):
        if self._conn:
            from contextlib import nullcontext
            return nullcontext(self._conn)
        return get_connection()

    @staticmethod
    def hash_token(token_value: str) -> str:
        import hashlib

        return hashlib.sha256(token_value.encode("utf-8")).hexdigest()

    def create_draft(self, record) -> None:
        from packages.hitl.queue import ApprovalState

        with self._ctx() as conn:
            conn.execute(
                """
                INSERT INTO approval_records (approval_id, draft_id, state)
                VALUES (gen_random_uuid(), %s, %s)
                ON CONFLICT (draft_id) DO UPDATE SET state = EXCLUDED.state
                """,
                (str(record.draft_id), ApprovalState.AWAITING_APPROVAL.value),
            )
            for role in record.required_roles:
                conn.execute(
                    """
                    INSERT INTO approval_required_roles (draft_id, role, approved)
                    VALUES (%s, %s, FALSE)
                    ON CONFLICT (draft_id, role) DO NOTHING
                    """,
                    (str(record.draft_id), role),
                )
            conn.commit()

    def record_state(self, record) -> None:
        with self._ctx() as conn:
            conn.execute(
                "UPDATE approval_records SET state = %s WHERE draft_id = %s",
                (record.state.value, str(record.draft_id)),
            )
            conn.commit()

    def record_approval(self, record, reviewer_identity, reviewer_role, token) -> None:
        token_hash = self.hash_token(str(token.token_id))
        with self._ctx() as conn:
            conn.execute(
                """
                UPDATE approval_records
                SET state = %s,
                    reviewer_identity = %s,
                    reviewer_role = %s,
                    token_hash = %s
                WHERE draft_id = %s
                """,
                (
                    record.state.value,
                    reviewer_identity,
                    reviewer_role,
                    token_hash,
                    str(record.draft_id),
                ),
            )
            conn.execute(
                """
                UPDATE approval_required_roles
                SET approved = TRUE, approved_by = %s, approved_at = now()
                WHERE draft_id = %s AND role = %s
                """,
                (reviewer_identity, str(record.draft_id), reviewer_role),
            )
            conn.commit()

    def record_edit(self, record, editor) -> None:
        with self._ctx() as conn:
            conn.execute(
                "UPDATE approval_records SET state = %s WHERE draft_id = %s",
                (record.state.value, str(record.draft_id)),
            )
            conn.execute(
                "UPDATE approval_required_roles SET approved = FALSE, approved_by = NULL, "
                "approved_at = NULL WHERE draft_id = %s",
                (str(record.draft_id),),
            )
            conn.commit()

    def get_by_draft(self, draft_id: str) -> ApprovalRecord | None:
        with self._ctx() as conn:
            row = conn.execute(
                """
                SELECT approval_id, draft_id, state,
                       reviewer_identity, reviewer_role, token_hash, created_at
                FROM approval_records WHERE draft_id = %s LIMIT 1
                """,
                (draft_id,),
            ).fetchone()
            if not row:
                return None
            roles_rows = conn.execute(
                "SELECT role FROM approval_required_roles WHERE draft_id = %s",
                (draft_id,),
            ).fetchall()
            required_role = ",".join(sorted(r[0] for r in roles_rows))
            return ApprovalRecord(
                approval_id=str(row[0]),
                draft_id=str(row[1]),
                state=row[2],
                required_role=required_role,
                reviewer_identity=row[3],
                reviewer_role=row[4],
                token_hash=row[5],
                created_at=row[6],
            )
