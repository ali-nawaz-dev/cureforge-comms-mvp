import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4


class ApprovalState(str, Enum):
    DRAFTED = "DRAFTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"
    SENT = "SENT"


class DraftNotFound(KeyError):
    """Raised when an operation references a draft_id that does not exist."""


@dataclass(frozen=True)
class ApprovalToken:
    token_id: UUID
    draft_id: UUID
    reviewer_identity: str
    reviewer_role: str


@dataclass
class DraftRecord:
    draft_id: UUID
    content: str
    required_roles: set[str]
    state: ApprovalState = ApprovalState.DRAFTED
    token: ApprovalToken | None = None
    approvals: set[str] = field(default_factory=set)
    edit_history: list[tuple[datetime, str]] = field(default_factory=list)


class ApprovalQueue:
    """Thread-safe in-memory HITL queue.

    State transitions on a single draft are serialized so concurrent
    ``approve`` / ``edit`` / ``mark_sent`` calls cannot race past the state
    guard. Durable storage (Postgres) is plugged via the ``repository`` arg.
    """

    def __init__(self, repository=None) -> None:
        self.records: dict[UUID, DraftRecord] = {}
        self._repo = repository
        self._lock = threading.RLock()

    def _get(self, draft_id: UUID) -> DraftRecord:
        record = self.records.get(draft_id)
        if record is None:
            raise DraftNotFound(f"Unknown draft_id: {draft_id}")
        return record

    def draft(self, content: str, required_roles: set[str]) -> DraftRecord:
        with self._lock:
            record = DraftRecord(
                draft_id=uuid4(), content=content, required_roles=set(required_roles)
            )
            record.state = ApprovalState.AWAITING_APPROVAL
            self.records[record.draft_id] = record
            if self._repo:
                self._repo.create_draft(record)
            return record

    def approve(
        self, draft_id: UUID, reviewer_identity: str, reviewer_role: str
    ) -> ApprovalToken:
        with self._lock:
            record = self._get(draft_id)
            if record.state != ApprovalState.AWAITING_APPROVAL:
                raise ValueError("Only awaiting approval records can be approved")
            if reviewer_role not in record.required_roles:
                raise PermissionError("Reviewer role is not authorized for this draft")
            record.approvals.add(reviewer_role)
            if not record.required_roles.issubset(record.approvals):
                # Multi-role drafts: do not transition state until every role
                # has approved. Return an intermediate token for audit only.
                return ApprovalToken(
                    token_id=uuid4(),
                    draft_id=draft_id,
                    reviewer_identity=reviewer_identity,
                    reviewer_role=reviewer_role,
                )
            token = ApprovalToken(
                token_id=uuid4(),
                draft_id=draft_id,
                reviewer_identity=reviewer_identity,
                reviewer_role=reviewer_role,
            )
            record.token = token
            record.state = ApprovalState.APPROVED
            if self._repo:
                self._repo.record_approval(record, reviewer_identity, reviewer_role, token)
            return token

    def reject(self, draft_id: UUID) -> None:
        with self._lock:
            record = self._get(draft_id)
            if record.state != ApprovalState.AWAITING_APPROVAL:
                raise ValueError("Only awaiting approval records can be rejected")
            record.state = ApprovalState.REJECTED
            if self._repo:
                self._repo.record_state(record)

    def edit(self, draft_id: UUID, content: str, editor: str | None = None) -> None:
        with self._lock:
            record = self._get(draft_id)
            if record.state != ApprovalState.AWAITING_APPROVAL:
                raise ValueError("Only awaiting approval records can be edited")
            record.edit_history.append((datetime.utcnow(), editor or "unknown"))
            record.content = content
            record.approvals.clear()
            # Stays in AWAITING_APPROVAL so the gate re-runs.
            if self._repo:
                self._repo.record_edit(record, editor)

    def validate_send_token(self, draft_id: UUID, token: ApprovalToken | None) -> None:
        with self._lock:
            record = self._get(draft_id)
            if record.state != ApprovalState.APPROVED:
                raise PermissionError("Draft is not approved")
            if token is None or record.token != token or token.draft_id != draft_id:
                raise PermissionError("Valid approval token is required")

    def mark_sent(self, draft_id: UUID, token: ApprovalToken) -> None:
        with self._lock:
            self.validate_send_token(draft_id, token)
            record = self._get(draft_id)
            record.state = ApprovalState.SENT
            if self._repo:
                self._repo.record_state(record)
