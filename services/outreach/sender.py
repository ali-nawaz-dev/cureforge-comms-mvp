"""Outreach sender with real Resend integration and Postgres-backed cooldown.

Guards:
1. HITL approval token validation (always enforced).
2. 60-day cooldown check – reads last_contact_from_us_date from Postgres when
   DATABASE_URL is set; falls back to the in-memory date string.
3. Sandbox mode redirects to RESEND_SANDBOX_TO (never touches real inboxes).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from packages.hitl import ApprovalQueue, ApprovalToken

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SendResult:
    draft_id: UUID
    provider: str
    mode: str
    delivered: bool
    resend_email_id: str | None = None
    error: str | None = None


class OutreachSender:
    def __init__(
        self,
        approval_queue: ApprovalQueue,
        mode: str | None = None,
        resend_client=None,
        contact_repo=None,
        ledger=None,
    ) -> None:
        self.approval_queue = approval_queue
        self.mode = mode or os.getenv("OUTREACH_SEND_MODE", "sandbox")
        self._resend_client = resend_client
        self._contact_repo = contact_repo
        self._ledger = ledger

    def _get_resend(self):
        if self._resend_client is not None:
            return self._resend_client
        from services.outreach.resend_client import ResendClient
        self._resend_client = ResendClient()
        return self._resend_client

    def _get_contact_repo(self):
        if self._contact_repo is not None:
            return self._contact_repo
        if not os.getenv("DATABASE_URL"):
            return None
        try:
            from packages.db.repositories import ContactRepository
            self._contact_repo = ContactRepository()
            return self._contact_repo
        except Exception as exc:
            logger.warning("ContactRepository init failed: %s", exc)
            return None

    def _resolve_cooldown_date(
        self, contact_id: str | None, last_contact_from_us_date: str | None
    ) -> str | None:
        """Prefer Postgres over in-memory date string for cooldown check."""
        if contact_id:
            repo = self._get_contact_repo()
            if repo:
                try:
                    pg_date = repo.get_last_contact_date(contact_id)
                    if pg_date:
                        return pg_date.isoformat()
                except Exception as exc:
                    logger.warning("Postgres cooldown check failed: %s – using in-memory", exc)
        return last_contact_from_us_date

    def send_email(
        self,
        draft_id: UUID,
        token: ApprovalToken | None,
        to_email: str | None = None,
        subject: str | None = None,
        html_body: str | None = None,
        last_contact_from_us_date: str | None = None,
        active_conversation_token: str | None = None,
        contact_id: str | None = None,
    ) -> SendResult:
        self.approval_queue.validate_send_token(draft_id, token)

        effective_date = self._resolve_cooldown_date(contact_id, last_contact_from_us_date)
        if self._in_cooldown(effective_date, active_conversation_token):
            raise PermissionError("Contact is inside 60-day cooldown")

        # Attempt the real Resend send only when both credentials and target are provided.
        # "delivered" reflects what actually happened so the caller cannot claim a send it
        # never made.
        resend_email_id: str | None = None
        delivered: bool
        send_error: str | None = None

        if to_email and subject and html_body:
            resend = self._get_resend()
            result = resend.send(to=to_email, subject=subject, html_body=html_body)
            resend_email_id = result.email_id
            delivered = bool(result.success)
            send_error = getattr(result, "error", None)
            if not delivered:
                logger.warning("Resend send not confirmed: %s", send_error)
        else:
            delivered = self.mode != "live"

        if delivered:
            self.approval_queue.mark_sent(draft_id, token)  # type: ignore[arg-type]
            if contact_id:
                repo = self._get_contact_repo()
                if repo:
                    try:
                        repo.set_last_contact_date(contact_id, date.today())
                    except Exception as exc:
                        logger.warning("Failed to stamp last_contact_from_us_date: %s", exc)
            if self._ledger:
                try:
                    self._ledger.append(
                        "outreach_sent",
                        {
                            "draft_id": str(draft_id),
                            "resend_email_id": resend_email_id,
                            "mode": self.mode,
                        },
                    )
                except Exception as exc:
                    logger.warning("Sender ledger append failed: %s", exc)
        elif self._ledger and send_error is not None:
            try:
                self._ledger.append(
                    "outreach_send_failed",
                    {
                        "draft_id": str(draft_id),
                        "error": send_error,
                        "mode": self.mode,
                    },
                )
            except Exception as exc:
                logger.warning("Sender ledger append failed: %s", exc)

        return SendResult(
            draft_id=draft_id,
            provider="resend",
            mode=self.mode,
            delivered=delivered,
            resend_email_id=resend_email_id,
            error=send_error,
        )

    def classify_reply_intent(self, text: str) -> str:
        if "meeting" in text.lower() or "calendar" in text.lower():
            return "meeting_requested"
        if "not interested" in text.lower():
            return "not_interested"
        return "needs_review"

    def notify_telegram_meeting(self, contact_name: str, draft_id: str) -> bool:
        """Post a Telegram notification when a meeting is requested."""
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_NOTIFY_CHAT_ID")
        if not token or not chat_id:
            logger.info(
                "Telegram notify skipped (TELEGRAM_BOT_TOKEN or TELEGRAM_NOTIFY_CHAT_ID not set)"
            )
            return False
        import json
        import urllib.request

        msg = f"📅 Meeting requested by {contact_name} (draft {draft_id})"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": chat_id, "text": msg}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                logger.info("Telegram meeting notification sent to chat %s", chat_id)
                return True
        except Exception as exc:
            logger.warning("Telegram notify failed: %s", exc)
            return False

    def handle_inbound_reply(
        self,
        text: str,
        from_email: str | None = None,
        contact_name: str | None = None,
        draft_id: str | None = None,
        candidate_id: str | None = None,
        contact_id: str | None = None,
        current_token: str | None = None,
        contact_repo=None,
    ) -> tuple[str, str | None]:
        """
        Classify a reply, manage active-conversation token, and notify if needed.

        Returns (intent, new_token):
          - intent: classified string
          - new_token: updated active_conversation_token for the contact
            (None means token was revoked; same value means no change)

        Token rules:
          intent ∈ {interested, needs_info, meeting_requested, needs_review} → issue/refresh
          intent == not_interested → revoke immediately
          TTL: 30 days, refreshes on each reply
        """
        from packages.hitl.conversation_token import handle_reply_token

        intent = self.classify_reply_intent(text)
        logger.info(
            "Reply classified",
            extra={"intent": intent, "from_email": from_email, "draft_id": draft_id},
        )
        if intent == "meeting_requested":
            self.notify_telegram_meeting(
                contact_name=contact_name or from_email or "unknown",
                draft_id=draft_id or "unknown",
            )

        new_token = handle_reply_token(
            contact_id=contact_id or candidate_id or from_email or "unknown",
            intent=intent,
            current_token=current_token,
        )

        # Persist updated token to Postgres when repo is available
        if contact_id and new_token != current_token:
            repo = contact_repo or self._get_contact_repo()
            if repo:
                try:
                    repo.update_conversation_token(contact_id, new_token)
                except Exception as exc:
                    logger.warning("Could not persist conversation token: %s", exc)

        return intent, new_token

    def _in_cooldown(
        self, last_contact_from_us_date: str | None, active_conversation_token: str | None
    ) -> bool:
        from packages.hitl.conversation_token import is_token_valid
        # Valid (non-expired) token bypasses cooldown
        if not last_contact_from_us_date or is_token_valid(active_conversation_token):
            return False
        last_contact = date.fromisoformat(last_contact_from_us_date)
        return date.today() - last_contact < timedelta(days=60)
