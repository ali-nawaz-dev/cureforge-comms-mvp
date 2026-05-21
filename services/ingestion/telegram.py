"""Telegram Bot polling connector.

Polls the Telegram Bot API every POLL_INTERVAL seconds (default 300).
Each new message is wrapped into a RawSignal and fed through IngestionPipeline.

Environment variables required:
  TELEGRAM_BOT_TOKEN  — bot token from BotFather
  TELEGRAM_POLL_INTERVAL — seconds between polls (default 300)

Run standalone:
  python -m services.ingestion.telegram
"""
from __future__ import annotations

import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import json

logger = logging.getLogger(__name__)

_BASE = "https://api.telegram.org/bot{token}/{method}"


def _api_call(token: str, method: str, params: dict | None = None) -> dict:
    url = _BASE.format(token=token, method=method)
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="ignore")
        raise RuntimeError(f"Telegram API error {exc.code}: {body}") from exc


def poll_once(token: str, offset: int = 0) -> tuple[list[dict], int]:
    """Fetch pending updates; return (messages, next_offset)."""
    data = _api_call(token, "getUpdates", {"offset": offset, "timeout": 10, "limit": 100})
    updates = data.get("result", [])
    next_offset = offset
    messages: list[dict] = []
    for update in updates:
        next_offset = update["update_id"] + 1
        msg = update.get("message") or update.get("channel_post")
        if msg and msg.get("text"):
            messages.append(msg)
    return messages, next_offset


def run_polling_loop(pipeline, poll_interval: int | None = None) -> None:
    """
    Long-running loop that feeds Telegram messages into the ingestion pipeline.
    Designed to run in a background thread or as a service entrypoint.
    """
    from services.ingestion.pipeline import RawSignal

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set – Telegram connector disabled")
        return
    interval = poll_interval or int(os.getenv("TELEGRAM_POLL_INTERVAL", "300"))
    offset = 0
    backoff = interval

    logger.info("Telegram polling started (interval=%ds)", interval)
    while True:
        try:
            messages, offset = poll_once(token, offset)
            for msg in messages:
                text = msg.get("text", "")
                chat_id = str(msg.get("chat", {}).get("id", "unknown"))
                signal = RawSignal(
                    source="telegram",
                    source_url=f"https://t.me/c/{chat_id}/{msg.get('message_id', '')}",
                    raw_text=text,
                    topics=["telegram"],
                )
                result = pipeline.ingest(signal)
                if result:
                    logger.info("Telegram signal ingested: %s", result.content_hash)
            backoff = interval  # reset on success
        except Exception as exc:
            logger.warning("Telegram poll error: %s – backing off %ds", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 3600)
            continue
        time.sleep(interval)


if __name__ == "__main__":
    from packages.bus.factory import get_bus
    from packages.common.logging import configure_json_logging
    from packages.llm.factory import build_llm_client
    from packages.taxonomy import load_taxonomy
    from services.ingestion.pipeline import IngestionPipeline

    configure_json_logging()
    bus = get_bus()
    taxonomy = load_taxonomy()
    llm = build_llm_client()
    pipeline = IngestionPipeline(bus=bus, taxonomy=taxonomy, parser_llm=llm)
    run_polling_loop(pipeline)
