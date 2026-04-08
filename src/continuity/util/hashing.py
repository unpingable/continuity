"""Content hashing for receipts."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from continuity.util.jsoncanon import canonical_json


def receipt_hash(
    *,
    receipt_type: str,
    prev_hash: str | None,
    content: dict[str, Any],
) -> str:
    """Compute SHA-256 hash for a receipt, chaining from prev_hash."""
    material = {
        "receipt_type": receipt_type,
        "prev_hash": prev_hash,
        "content": content,
    }
    return sha256(canonical_json(material).encode("utf-8")).hexdigest()
