"""Postgres connection factory.

Reads ``DATABASE_URL`` from environment. Falls back gracefully to None so
the rest of the codebase can import this module even without a live DB
(tests, local dev without Docker).

Key changes vs. the previous version:

- The pool is opened lazily and *retained* under a module global. The new
  ``reset_pool()`` makes it explicit how to recycle it (e.g. tests).
- ``health_check()`` runs a cheap ``SELECT 1`` against the pool – used by
  the FastAPI ``/readyz`` route.
- ``run_migrations()`` no longer swallows ``Exception`` silently. It logs
  and re-raises so a Docker init container actually fails the start-up.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)

_pool: object | None = None


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Copy .env.example → .env and fill in the Postgres credentials."
        )
    return url


def get_pool():
    """Return (and lazily create) a psycopg connection pool."""
    global _pool
    if _pool is None:
        try:
            from psycopg_pool import ConnectionPool  # type: ignore

            _pool = ConnectionPool(_database_url(), min_size=1, max_size=10, open=False)
            _pool.open(wait=True)  # type: ignore[attr-defined]
            logger.info("Postgres connection pool opened")
        except Exception as exc:
            logger.warning("Could not open Postgres pool: %s – running without DB", exc)
            _pool = None
    return _pool


def reset_pool() -> None:
    """Close and discard the pool. Tests use this between fixtures."""
    global _pool
    if _pool is not None:
        try:
            _pool.close()  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug("Pool close error: %s", exc)
    _pool = None


def health_check() -> bool:
    """Run ``SELECT 1`` against the pool. Returns ``True`` if it succeeds."""
    pool = get_pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:  # type: ignore[attr-defined]
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception as exc:
        logger.warning("Pool health check failed: %s", exc)
        return False


@contextmanager
def get_connection() -> Generator:
    """Context manager that yields a psycopg connection from the pool."""
    pool = get_pool()
    if pool is None:
        raise RuntimeError("No Postgres connection available.")
    with pool.connection() as conn:  # type: ignore[attr-defined]
        yield conn


def run_migrations() -> None:
    """Apply the core schema DDL.

    Raises on any failure so a startup script / init container can detect a
    bad schema rather than silently running on an outdated DB.
    """
    migrations_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "migrations", "001_core_schema.sql"
    )
    migrations_path = os.path.normpath(migrations_path)
    if not os.path.exists(migrations_path):
        raise RuntimeError(f"Migration file not found at {migrations_path}")
    with open(migrations_path) as fh:
        sql = fh.read()
    with get_connection() as conn:
        conn.execute(sql)
        conn.commit()
        logger.info("Migrations applied from %s", migrations_path)
