"""Hash-chain provenance ledger.

Each record links to the previous one via a SHA-256 chain hash. The ledger
persists to SQLite when ``LEDGER_SQLITE_PATH`` is set; otherwise it runs in
memory. Both modes expose the same API so callers are unaffected.

Naming note: earlier drafts called this a Merkle-anchored ledger. The current
implementation is a linear hash chain. A future ``MerkleAnchor`` can batch
``chain_hash`` values and publish a root to an external store if/when needed.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from packages.common.hashing import canonical_json, sha256_hex
from packages.common.time import utc_now_iso

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS ledger (
    record_id    INTEGER PRIMARY KEY,
    record_type  TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    chain_hash   TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    payload_json TEXT
);
"""


@dataclass(frozen=True)
class LedgerRecord:
    record_id: int
    record_type: str
    payload_hash: str
    prev_record_hash: str
    chain_hash: str
    timestamp: str


class Ledger:
    """Append-only hash-chain ledger.

    Concurrency: appends are guarded by an instance-level lock so the
    ``record_id`` sequence and the chain link cannot race. SQLite is opened
    in WAL mode so concurrent readers do not block writers.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.records: list[LedgerRecord] = []
        self._db_path = db_path or os.getenv("LEDGER_SQLITE_PATH")
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        if self._db_path:
            self._open_db()
            self._load_existing()
        if not self.records:
            self.append("GENESIS", {"genesis": True})

    def _open_db(self) -> None:
        try:
            self._conn = sqlite3.connect(
                self._db_path,  # type: ignore[arg-type]
                check_same_thread=False,
                isolation_level=None,  # explicit transactions via BEGIN IMMEDIATE
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(_DDL)
            logger.info("Ledger SQLite opened at %s", self._db_path)
        except Exception as exc:
            logger.warning("Ledger SQLite open failed: %s – running in-memory", exc)
            self._conn = None

    def _load_existing(self) -> None:
        if not self._conn:
            return
        rows = self._conn.execute(
            "SELECT record_id, record_type, payload_hash, prev_hash, chain_hash, timestamp "
            "FROM ledger ORDER BY record_id"
        ).fetchall()
        for row in rows:
            self.records.append(
                LedgerRecord(
                    record_id=row[0],
                    record_type=row[1],
                    payload_hash=row[2],
                    prev_record_hash=row[3],
                    chain_hash=row[4],
                    timestamp=row[5],
                )
            )

    def _next_record_id(self) -> int:
        if self._conn:
            row = self._conn.execute("SELECT COALESCE(MAX(record_id), 0) FROM ledger").fetchone()
            return int(row[0]) + 1
        return len(self.records) + 1

    def append(self, record_type: str, payload: dict[str, Any]) -> LedgerRecord:
        with self._lock:
            record_id = self._next_record_id()
            prev_hash = self.records[-1].chain_hash if self.records else "0" * 64
            timestamp = utc_now_iso()
            payload_hash = sha256_hex(canonical_json(payload))
            chain_hash = sha256_hex(
                f"{record_id}{record_type}{payload_hash}{prev_hash}{timestamp}"
            )
            record = LedgerRecord(
                record_id, record_type, payload_hash, prev_hash, chain_hash, timestamp
            )

            if self._conn:
                try:
                    self._conn.execute("BEGIN IMMEDIATE")
                    self._conn.execute(
                        "INSERT INTO ledger (record_id, record_type, payload_hash, "
                        "prev_hash, chain_hash, timestamp, payload_json) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (
                            record_id,
                            record_type,
                            payload_hash,
                            prev_hash,
                            chain_hash,
                            timestamp,
                            json.dumps(payload),
                        ),
                    )
                    self._conn.execute("COMMIT")
                except Exception as exc:
                    try:
                        self._conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    logger.error("Ledger persist failed: %s – not appending in-memory", exc)
                    raise

            self.records.append(record)
            return record

    def verify_chain(self) -> bool:
        previous = "0" * 64
        for record in self.records:
            expected = sha256_hex(
                f"{record.record_id}{record.record_type}{record.payload_hash}"
                f"{previous}{record.timestamp}"
            )
            if expected != record.chain_hash or record.prev_record_hash != previous:
                return False
            previous = record.chain_hash
        return True

    def last_n(self, n: int = 10) -> list[LedgerRecord]:
        return self.records[-n:]
