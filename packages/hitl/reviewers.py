"""Load reviewers from data/seeds/reviewers.json and seed them into the HITL context.

The reviewers file maps email addresses to roles. These identities are used
by the ApprovalQueue to validate role-based approvals.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Roles the HITL queue knows how to dispatch. Loading any other role is a
# typo in the seed file; we log and skip rather than silently accepting it.
KNOWN_ROLES = frozenset(
    {
        "principal_investigator",
        "grants_administrator",
        "patent_counsel",
        "regulatory_advisor",
        "institutional_legal",
    }
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Reviewer:
    email: str
    role: str


class ReviewerSchemaError(ValueError):
    """Raised when the reviewers seed file is malformed."""


def load_reviewers(path: str | None = None, *, strict: bool = False) -> list[Reviewer]:
    """Load reviewers from a JSON seed file.

    ``strict=True`` raises ``ReviewerSchemaError`` on any issue; otherwise
    bad rows are logged and skipped so the dashboard can still start with
    partial data during development.
    """
    if path is None:
        base = os.path.dirname(__file__)
        path = os.path.normpath(os.path.join(base, "..", "..", "data", "seeds", "reviewers.json"))
    if not os.path.exists(path):
        logger.warning("Reviewers file not found at %s", path)
        return []
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception as exc:
        msg = f"Failed to read reviewers file: {exc}"
        if strict:
            raise ReviewerSchemaError(msg) from exc
        logger.warning(msg)
        return []

    if not isinstance(data, list):
        msg = "Reviewers file must be a JSON array"
        if strict:
            raise ReviewerSchemaError(msg)
        logger.warning(msg)
        return []

    reviewers: list[Reviewer] = []
    for idx, item in enumerate(data):
        try:
            email = item["email"]
            role = item["role"]
        except (KeyError, TypeError) as exc:
            msg = f"Reviewer row {idx} missing required keys: {exc}"
            if strict:
                raise ReviewerSchemaError(msg) from exc
            logger.warning(msg)
            continue
        if not isinstance(email, str) or not _EMAIL_RE.match(email):
            msg = f"Reviewer row {idx} has invalid email: {email!r}"
            if strict:
                raise ReviewerSchemaError(msg)
            logger.warning(msg)
            continue
        if role not in KNOWN_ROLES:
            msg = f"Reviewer row {idx} uses unknown role {role!r}"
            if strict:
                raise ReviewerSchemaError(msg)
            logger.warning(msg)
            continue
        reviewers.append(Reviewer(email=email, role=role))
    logger.info("Loaded %d reviewers from %s", len(reviewers), path)
    return reviewers


def reviewers_by_role(reviewers: list[Reviewer]) -> dict[str, list[Reviewer]]:
    """Group reviewers by role for quick lookup."""
    result: dict[str, list[Reviewer]] = {}
    for reviewer in reviewers:
        result.setdefault(reviewer.role, []).append(reviewer)
    return result
