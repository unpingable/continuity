"""Canonical JSON serialization for hashing and storage."""

from __future__ import annotations

import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators, no ASCII escaping."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def from_json(value: str | None) -> Any:
    """Parse JSON string, or return None for None input."""
    if value is None:
        return None
    return json.loads(value)
