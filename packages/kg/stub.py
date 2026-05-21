"""Knowledge Graph stub.

Persists to SQLite when ``KG_SQLITE_PATH`` is set; otherwise runs in-memory.

Both nodes and edges are now reloaded on init so an in-memory edge index
stays consistent with what is on disk. ``add_edge`` validates endpoints
before insert so dangling edges cannot enter the graph.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS kg_nodes (
    node_id    TEXT PRIMARY KEY,
    node_type  TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS kg_edges (
    edge_id    TEXT PRIMARY KEY,
    src_id     TEXT NOT NULL REFERENCES kg_nodes(node_id),
    dst_id     TEXT NOT NULL REFERENCES kg_nodes(node_id),
    label      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass
class KnowledgeGraphStub:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: dict[str, dict[str, str]] = field(default_factory=dict)
    _db_path: str | None = field(default=None, repr=False, compare=False)
    _conn: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        db_path = self._db_path or os.getenv("KG_SQLITE_PATH")
        if db_path:
            try:
                self._conn = sqlite3.connect(db_path, check_same_thread=False)
                self._conn.executescript(_DDL)
                self._conn.commit()
                self._load_existing()
                logger.info("KG SQLite opened at %s", db_path)
            except Exception as exc:
                logger.warning("KG SQLite open failed: %s – running in-memory", exc)
                self._conn = None

    def _load_existing(self) -> None:
        if not self._conn:
            return
        for row in self._conn.execute(
            "SELECT node_id, node_type, payload FROM kg_nodes"
        ).fetchall():
            self.nodes[row[0]] = {"node_type": row[1], "payload": json.loads(row[2])}
        for row in self._conn.execute(
            "SELECT edge_id, src_id, dst_id, label FROM kg_edges"
        ).fetchall():
            self.edges[row[0]] = {
                "src_id": row[1],
                "dst_id": row[2],
                "label": row[3],
            }

    def add_node(self, node_type: str, payload: dict[str, Any]) -> str:
        node_id = str(uuid4())
        self.nodes[node_id] = {"node_type": node_type, "payload": payload}
        if self._conn:
            try:
                self._conn.execute(
                    "INSERT OR IGNORE INTO kg_nodes (node_id, node_type, payload) VALUES (?,?,?)",
                    (node_id, node_type, json.dumps(payload)),
                )
                self._conn.commit()
            except Exception as exc:
                logger.warning("KG node persist failed: %s", exc)
        return node_id

    def add_edge(self, src_id: str, dst_id: str, label: str) -> str:
        if src_id not in self.nodes or dst_id not in self.nodes:
            raise ValueError(
                f"KG edge endpoints must reference existing nodes (src={src_id}, dst={dst_id})"
            )
        edge_id = str(uuid4())
        self.edges[edge_id] = {"src_id": src_id, "dst_id": dst_id, "label": label}
        if self._conn:
            try:
                self._conn.execute(
                    "INSERT OR IGNORE INTO kg_edges (edge_id, src_id, dst_id, label) "
                    "VALUES (?,?,?,?)",
                    (edge_id, src_id, dst_id, label),
                )
                self._conn.commit()
            except Exception as exc:
                logger.warning("KG edge persist failed: %s", exc)
        return edge_id
