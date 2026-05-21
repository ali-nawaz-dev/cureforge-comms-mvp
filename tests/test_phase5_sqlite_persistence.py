"""Phase 5: Ledger + KG SQLite persistence tests."""
from __future__ import annotations

import os
from pathlib import Path

from packages.kg.stub import KnowledgeGraphStub
from packages.ledger.chain import Ledger


def test_ledger_persists_and_reloads(tmp_path: Path) -> None:
    db = tmp_path / "ledger.sqlite"
    first = Ledger(db_path=str(db))
    a = first.append("signal", {"k": 1})
    b = first.append("signal", {"k": 2})
    assert first.verify_chain() is True

    second = Ledger(db_path=str(db))
    assert [r.record_id for r in second.records] == [r.record_id for r in first.records]
    assert second.records[-1].chain_hash == b.chain_hash
    # Genesis row from first instance must not be duplicated by reload.
    assert second.records[0].record_type == "GENESIS"
    assert second.records[1].record_id == a.record_id


def test_ledger_uses_max_id_when_partial_writes_left_gap(tmp_path: Path) -> None:
    db = tmp_path / "gap.sqlite"
    Ledger(db_path=str(db))  # creates genesis row 1

    import sqlite3

    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO ledger (record_id, record_type, payload_hash, prev_hash, "
            "chain_hash, timestamp, payload_json) VALUES (?,?,?,?,?,?,?)",
            (5, "synthetic", "hash5", "0" * 64, "chain5", "2025-01-01T00:00:00Z", "{}"),
        )
        conn.commit()

    ledger = Ledger(db_path=str(db))
    new_record = ledger.append("signal", {"k": 1})
    assert new_record.record_id == 6


def test_kg_reloads_nodes_and_edges(tmp_path: Path) -> None:
    db = tmp_path / "kg.sqlite"
    os.environ.pop("KG_SQLITE_PATH", None)

    first = KnowledgeGraphStub(_db_path=str(db))
    a = first.add_node("signal", {"label": "a"})
    b = first.add_node("contact", {"label": "b"})
    first.add_edge(a, b, "REL")

    second = KnowledgeGraphStub(_db_path=str(db))
    assert a in second.nodes
    assert b in second.nodes
    assert any(e["src_id"] == a and e["dst_id"] == b for e in second.edges.values())
