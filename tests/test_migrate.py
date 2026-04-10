"""Test schema migration: patching CHECK constraints on existing databases."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from continuity.api.models import (
    Basis,
    MemoryKind,
    ObserveMemoryRequest,
    PremiseRef,
)
from continuity.store.sqlite import SQLiteStore


def _create_old_schema_db(db_path: Path) -> None:
    """Create a DB with the old (pre-experiment/lesson) CHECK constraints."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE memory_objects (
            memory_id       TEXT PRIMARY KEY,
            scope           TEXT NOT NULL,
            kind            TEXT NOT NULL CHECK (
                kind IN (
                    'fact', 'note', 'decision', 'hypothesis',
                    'summary', 'constraint', 'project_state', 'next_action'
                )
            ),
            basis           TEXT NOT NULL CHECK (
                basis IN (
                    'direct_capture', 'operator_assertion',
                    'inference', 'import', 'synthesis'
                )
            ),
            status          TEXT NOT NULL CHECK (
                status IN ('observed', 'committed', 'revoked')
            ),
            reliance_class  TEXT NOT NULL CHECK (
                reliance_class IN (
                    'none', 'retrieve_only', 'advisory', 'actionable'
                )
            ),
            confidence      REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
            content_json      TEXT NOT NULL,
            source_refs_json  TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            expires_at  TEXT NULL,
            supersedes    TEXT NULL,
            revoked_by    TEXT NULL,
            created_by_json   TEXT NULL,
            approved_by_json  TEXT NULL
        );
        CREATE TABLE memory_links (
            link_id         TEXT PRIMARY KEY,
            dst_memory_id   TEXT NOT NULL,
            src_memory_id   TEXT NULL,
            src_receipt_id  TEXT NULL,
            src_ref_json    TEXT NULL,
            relation  TEXT NOT NULL CHECK (
                relation IN (
                    'depends_on', 'supports', 'derived_from',
                    'implements', 'supersedes', 'invalidates', 'about'
                )
            ),
            strength  TEXT NOT NULL CHECK (strength IN ('hard', 'soft')),
            status  TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
            note  TEXT NULL,
            created_at TEXT NOT NULL,
            created_by_event_id TEXT NULL,
            revoked_at TEXT NULL,
            revoked_by_event_id TEXT NULL
        );
    """)
    conn.commit()
    conn.close()


def test_old_schema_rejects_new_kind(tmp_path: Path) -> None:
    """Sanity check: an old-schema DB rejects 'experiment' kind."""
    db = tmp_path / "old.db"
    _create_old_schema_db(db)

    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO memory_objects (memory_id, scope, kind, basis, status, "
            "reliance_class, confidence, content_json, source_refs_json, "
            "created_at, updated_at) VALUES "
            "('mem_test', 's', 'experiment', 'direct_capture', 'observed', "
            "'none', 0.5, '{}', '[]', '2026-01-01', '2026-01-01')"
        )
    conn.close()


def test_migrate_adds_new_kinds_and_relations(tmp_path: Path) -> None:
    """After migrate, an old-schema DB accepts the new enum values."""
    db = tmp_path / "to-migrate.db"
    _create_old_schema_db(db)

    store = SQLiteStore(db)
    result = store.migrate_schema()

    assert "memory_objects" in result["changed_tables"]
    assert "memory_links" in result["changed_tables"]
    assert result["integrity_check"] == "ok"

    # Now the new kinds should work end-to-end via the normal API
    store.initialize()  # creates other tables (events, receipts, links indexes)
    resp = store.observe_memory(ObserveMemoryRequest(
        scope="case:after-migrate",
        kind=MemoryKind.EXPERIMENT,
        basis=Basis.DIRECT_CAPTURE,
        content={"action": "test post-migration"},
    ))
    assert resp.memory.kind == MemoryKind.EXPERIMENT


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    """Running migrate on an already-current DB is a no-op."""
    db = tmp_path / "fresh.db"
    store = SQLiteStore(db)
    store.initialize()

    result = store.migrate_schema()
    assert result["changed_tables"] == []
    assert result["integrity_check"] == "ok"

    # Run it again — still no-op
    result2 = store.migrate_schema()
    assert result2["changed_tables"] == []
