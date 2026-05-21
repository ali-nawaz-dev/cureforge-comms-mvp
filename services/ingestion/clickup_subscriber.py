"""ClickUp subscriber – creates tasks in the signal_intake staging list.

Subscribes to external_signal.* bus events and creates a ClickUp task in the
configured staging list. Never writes to the main roadmap board.

Environment variables:
  CLICKUP_API_TOKEN          — required
  CLICKUP_SIGNAL_INTAKE_LIST_ID — required (staging list only)

Usage (standalone):
  python -m services.ingestion.clickup_subscriber
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_CLICKUP_API = "https://api.clickup.com/api/v2"


def create_task(list_id: str, api_token: str, name: str, description: str) -> dict | None:
    """Create a ClickUp task in the given list. Returns response dict or None on failure."""
    url = f"{_CLICKUP_API}/list/{list_id}/task"
    payload = json.dumps({"name": name, "description": description}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": api_token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            logger.info("ClickUp task created: %s", data.get("id"))
            return data
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="ignore")
        logger.warning("ClickUp API error %d: %s", exc.code, body)
        return None
    except Exception as exc:
        logger.warning("ClickUp request failed: %s", exc)
        return None


def wire_clickup_subscriber(bus) -> bool:
    """Subscribe to ``external_signal.*`` and create ClickUp tasks.

    Returns ``True`` if the subscriber was wired, ``False`` if credentials
    are missing. The handler dedups by ``event_id`` so a Redis redelivery
    cannot create the same task twice.
    """
    from packages.bus.idempotency import IdempotencyCache

    api_token = os.getenv("CLICKUP_API_TOKEN", "")
    list_id = os.getenv("CLICKUP_SIGNAL_INTAKE_LIST_ID", "")
    if not api_token or not list_id:
        logger.info("ClickUp subscriber not wired (CLICKUP_API_TOKEN or LIST_ID not set)")
        return False

    idempotency = IdempotencyCache()

    def _handler(envelope) -> None:
        if not idempotency.claim(str(envelope.event_id)):
            return
        payload = envelope.payload
        name = (
            f"Signal: {payload.get('source', 'unknown')} – "
            f"{payload.get('content_hash', '')[:12]}"
        )
        description = (
            f"Topic: {envelope.topic}\n"
            f"Summary: {payload.get('parsed_summary', 'N/A')}\n"
            f"Source URL: {payload.get('source_url', 'N/A')}\n"
            f"Event ID: {envelope.event_id}"
        )
        create_task(list_id, api_token, name, description)

    bus.subscribe("external_signal.*", _handler)
    logger.info("ClickUp subscriber wired to external_signal.* (list %s)", list_id)
    return True


if __name__ == "__main__":
    from packages.bus.factory import get_bus
    from packages.common.logging import configure_json_logging

    configure_json_logging()
    bus = get_bus()
    wired = wire_clickup_subscriber(bus)
    if not wired:
        print("ClickUp subscriber not started: CLICKUP_API_TOKEN or CLICKUP_SIGNAL_INTAKE_LIST_ID not set")
    else:
        import time
        print("ClickUp subscriber running. Waiting for bus events…")
        while True:
            time.sleep(60)
