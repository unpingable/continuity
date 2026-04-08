"""Test that the schema loads and tables exist."""

from continuity.store.sqlite import SQLiteStore


def test_schema_loads(store: SQLiteStore) -> None:
    with store._connect() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r["name"] for r in tables}

    assert "memory_objects" in names
    assert "memory_events" in names
    assert "receipts" in names
    assert "spool_imports" in names
    assert "memory_links" in names


def test_schema_idempotent(store: SQLiteStore) -> None:
    """Calling initialize() twice should not fail."""
    store.initialize()
    with store._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table'"
        ).fetchone()["c"]
    assert count >= 5
