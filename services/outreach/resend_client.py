"""Resend API client.

Sends emails via the Resend API using urllib (no extra dependencies).
Only activates in sandbox mode (OUTREACH_SEND_MODE=sandbox) and only
sends to the configured test inbox.

Environment variables:
  RESEND_API_KEY        — required for real sends
  RESEND_FROM_EMAIL     — sender address (default outreach@contact.longevityintime.org)
  RESEND_REPLY_TO       — reply-to address
  OUTREACH_SEND_MODE    — "sandbox" (default) or "live"
  RESEND_SANDBOX_TO     — test inbox address (required in sandbox mode)
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_RESEND_API_URL = "https://api.resend.com/emails"


@dataclass
class ResendSendResult:
    email_id: str | None
    to: str
    subject: str
    mode: str
    success: bool
    error: str | None = None


class ResendClient:
    def __init__(
        self,
        api_key: str | None = None,
        from_email: str | None = None,
        reply_to: str | None = None,
        mode: str | None = None,
        sandbox_to: str | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("RESEND_API_KEY", "")
        self._from_email = from_email or os.getenv(
            "RESEND_FROM_EMAIL", "outreach@contact.longevityintime.org"
        )
        self._reply_to = reply_to or os.getenv("RESEND_REPLY_TO")
        self._mode = mode or os.getenv("OUTREACH_SEND_MODE", "sandbox")
        self._sandbox_to = sandbox_to or os.getenv("RESEND_SANDBOX_TO", "")

    def send(self, to: str, subject: str, html_body: str) -> ResendSendResult:
        """Send an email. In sandbox mode, redirects to RESEND_SANDBOX_TO."""
        if not self._api_key:
            logger.warning("RESEND_API_KEY not set – skipping real send")
            return ResendSendResult(
                email_id=None,
                to=to,
                subject=subject,
                mode="skipped",
                success=False,
                error="RESEND_API_KEY not configured",
            )

        effective_to = to
        if self._mode == "sandbox":
            if not self._sandbox_to:
                logger.warning("RESEND_SANDBOX_TO not set – cannot send in sandbox mode")
                return ResendSendResult(
                    email_id=None,
                    to=to,
                    subject=subject,
                    mode="sandbox",
                    success=False,
                    error="RESEND_SANDBOX_TO not configured",
                )
            effective_to = self._sandbox_to
            subject = f"[SANDBOX → {to}] {subject}"

        payload: dict = {
            "from": self._from_email,
            "to": [effective_to],
            "subject": subject,
            "html": html_body,
        }
        if self._reply_to:
            payload["reply_to"] = self._reply_to

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            _RESEND_API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read())
                email_id = body.get("id")
                logger.info(
                    "Resend send OK",
                    extra={"email_id": email_id, "mode": self._mode, "to": effective_to},
                )
                return ResendSendResult(
                    email_id=email_id,
                    to=effective_to,
                    subject=subject,
                    mode=self._mode,
                    success=True,
                )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode(errors="ignore")
            logger.error("Resend HTTP error %d: %s", exc.code, error_body)
            return ResendSendResult(
                email_id=None,
                to=effective_to,
                subject=subject,
                mode=self._mode,
                success=False,
                error=f"HTTP {exc.code}: {error_body}",
            )
        except Exception as exc:
            logger.error("Resend send failed: %s", exc)
            return ResendSendResult(
                email_id=None,
                to=effective_to,
                subject=subject,
                mode=self._mode,
                success=False,
                error=str(exc),
            )
