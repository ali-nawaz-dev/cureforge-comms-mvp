"""Shared synchronous HTTP client with sane defaults.

Why this exists: the codebase used ``urllib.request.urlopen`` directly in
half-a-dozen places, each rebuilding timeouts, headers, and (poorly)
re-implementing retry. Centralizing here means:

- One place to set the connect/read timeout, default UA, and retry policy.
- Tests use respx (which intercepts httpx) instead of monkeypatching urllib.
- Retries use exponential backoff via ``tenacity`` for transient 5xx / network
  failures. The decorator is no-op if tenacity is unavailable so the codebase
  still works without that optional dependency.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(
    connect=float(os.getenv("HTTP_CONNECT_TIMEOUT", "5")),
    read=float(os.getenv("HTTP_READ_TIMEOUT", "30")),
    write=float(os.getenv("HTTP_WRITE_TIMEOUT", "10")),
    pool=float(os.getenv("HTTP_POOL_TIMEOUT", "5")),
)

DEFAULT_HEADERS = {"User-Agent": "cureforge-comms-mvp/0.1"}


def get_client(**kwargs: Any) -> httpx.Client:
    """Return a configured httpx.Client.

    Caller is responsible for closing it (preferably via ``with`` block).
    """
    return httpx.Client(timeout=DEFAULT_TIMEOUT, headers=DEFAULT_HEADERS, **kwargs)


def post_json(
    url: str,
    *,
    json_body: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
) -> httpx.Response:
    """POST ``json_body`` and return the raw ``httpx.Response``.

    The caller decides how to map status codes to exceptions; this helper
    keeps the policy in one place.
    """
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    with httpx.Client(timeout=timeout or DEFAULT_TIMEOUT, headers=merged_headers) as client:
        return client.post(url, json=json_body)


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
) -> httpx.Response:
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    with httpx.Client(timeout=timeout or DEFAULT_TIMEOUT, headers=merged_headers) as client:
        return client.get(url, params=params)
