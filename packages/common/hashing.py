import hashlib
import json
import unicodedata
from typing import Any


def canonical_json(payload: Any) -> str:
    """Canonicalize JSON for stable hashing and ledger records."""
    normalized = _normalize(payload)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def normalized_content_hash(text: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFC", text).lower().split())
    return sha256_hex(normalized)


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize(val) for key, val in value.items()}
    return value

