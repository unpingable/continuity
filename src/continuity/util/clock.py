"""UTC timestamp helpers."""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time, timezone-aware."""
    return datetime.now(timezone.utc)


def to_isoformat(dt: datetime | None) -> str | None:
    """Convert datetime to ISO-8601 UTC string, or None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="microseconds")


def isoformat_now() -> str:
    """Current UTC time as ISO-8601 string."""
    return to_isoformat(utcnow())  # type: ignore[return-value]
