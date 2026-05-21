"""Contact import CLI.

Reads contacts from a CSV or JSON file and upserts them into Postgres via the
ContactRepository. Falls back to printing a dry-run summary when DATABASE_URL
is not set.

Usage:
  python -m services.matching.cli_import --file contacts.csv
  python -m services.matching.cli_import --file contacts.json --dry-run
"""
from __future__ import annotations

import csv
import json
import logging
import os
import uuid
from pathlib import Path

from packages.common.logging import configure_json_logging

configure_json_logging()
logger = logging.getLogger(__name__)


def _parse_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def _parse_json(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = list(data.values())
    return data


def _normalize(raw: dict) -> dict:
    """Normalize a raw row into a ContactRecord-compatible dict."""
    def _list_field(value) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            return [v.strip() for v in value.split(",") if v.strip()]
        return []

    return {
        "contact_id": raw.get("contact_id") or str(uuid.uuid4()),
        "contact_type": raw.get("contact_type", raw.get("type", "PARTNER")).upper(),
        "name": raw.get("name", "Unknown"),
        "organization": raw.get("organization", raw.get("org")),
        "role": raw.get("role"),
        "focus_areas": _list_field(raw.get("focus_areas", raw.get("focus", []))),
        "stated_thesis_tags": _list_field(raw.get("stated_thesis_tags", raw.get("tags", []))),
        "under_nda": str(raw.get("under_nda", "false")).lower() in ("true", "1", "yes"),
        "disinterest_flag": str(raw.get("disinterest_flag", "false")).lower() in ("true", "1", "yes"),
        "active_conversation_token": raw.get("active_conversation_token"),
        "last_contact_from_us_date": raw.get("last_contact_from_us_date") or None,
        "warm_signal_score": int(raw.get("warm_signal_score", 0)),
        "source_provenance": {"import": "cli"},
    }


def import_contacts(path: Path, dry_run: bool = False) -> list[dict]:
    """Parse and optionally upsert contacts. Returns list of normalized records."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = _parse_csv(path)
    elif suffix in (".json", ".jsonl"):
        rows = _parse_json(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    normalized = [_normalize(row) for row in rows]
    logger.info("Parsed %d contacts from %s", len(normalized), path)

    if dry_run:
        for rec in normalized:
            print(f"  DRY-RUN: {rec['contact_id']} | {rec['name']} | {rec['contact_type']}")
        return normalized

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.warning("DATABASE_URL not set – printing dry-run summary instead")
        for rec in normalized:
            print(f"  {rec['contact_id']} | {rec['name']} | {rec['contact_type']}")
        return normalized

    from packages.db.repositories import ContactRecord, ContactRepository
    repo = ContactRepository()
    imported = 0
    for rec in normalized:
        try:
            from datetime import date as dt_date
            last_date = None
            if rec["last_contact_from_us_date"]:
                last_date = dt_date.fromisoformat(rec["last_contact_from_us_date"])
            repo.upsert(ContactRecord(
                contact_id=rec["contact_id"],
                contact_type=rec["contact_type"],
                name=rec["name"],
                organization=rec["organization"],
                role=rec["role"],
                focus_areas=rec["focus_areas"],
                stated_thesis_tags=rec["stated_thesis_tags"],
                under_nda=rec["under_nda"],
                disinterest_flag=rec["disinterest_flag"],
                active_conversation_token=rec["active_conversation_token"],
                last_contact_from_us_date=last_date,
                warm_signal_score=rec["warm_signal_score"],
                source_provenance=rec["source_provenance"],
            ))
            imported += 1
        except Exception as exc:
            logger.warning("Failed to upsert %s: %s", rec["name"], exc)
    logger.info("Upserted %d/%d contacts", imported, len(normalized))
    return normalized


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Import contacts from CSV or JSON into Postgres.")
    parser.add_argument("--file", required=True, help="Path to contacts CSV or JSON file")
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse and print without writing to DB"
    )
    args = parser.parse_args()
    import_contacts(Path(args.file), dry_run=args.dry_run)


if __name__ == "__main__":
    _cli()
