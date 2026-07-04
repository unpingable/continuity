"""CONTINUITY_TIME_DISCIPLINE V2 — source_observed_at capture.

The one V2 capture field that is pure (no taxonomy invention): when the
underlying fact was OBSERVED, distinct from when the memory was RECORDED
(created_at). No backfill; capture begins when a caller supplies it. No
timestamp impersonates another.

The staleness posture gradient (invariant 10) and last_confirmed_at (invariant
9) remain deliberately unbuilt — they would require inventing a taxonomy ahead
of pressure, which the gap forbids.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from continuity.api.models import (
    ActorRef,
    AdjudicateMemoryRequest,
    AdjudicationMotion,
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    ObserveMemoryRequest,
    RelianceClass,
)
from continuity.store.sqlite import SQLiteStore


def _seen() -> datetime:
    return datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_source_observed_at_is_captured_distinct_from_created_at(store: SQLiteStore) -> None:
    resp = store.observe_memory(ObserveMemoryRequest(
        scope="t", kind=MemoryKind.FACT, basis=Basis.DIRECT_CAPTURE,
        content={"a": 1}, source_observed_at=_seen(),
    ))
    m = store.get_memory(resp.memory.memory_id)
    assert m.source_observed_at == _seen()
    # created_at is record time — the lag is preserved, not laundered.
    assert m.created_at != m.source_observed_at


def test_source_observed_at_defaults_none(store: SQLiteStore) -> None:
    resp = store.observe_memory(ObserveMemoryRequest(
        scope="t", kind=MemoryKind.FACT, basis=Basis.DIRECT_CAPTURE,
        content={"a": 1},
    ))
    assert store.get_memory(resp.memory.memory_id).source_observed_at is None


def test_observe_receipt_records_source_observed_at(store: SQLiteStore) -> None:
    resp = store.observe_memory(ObserveMemoryRequest(
        scope="t", kind=MemoryKind.FACT, basis=Basis.DIRECT_CAPTURE,
        content={"a": 1}, source_observed_at=_seen(),
    ))
    assert resp.receipt.content["source_observed_at"] == "2026-03-01T12:00:00.000000+00:00"


def test_source_observed_at_survives_commit(store: SQLiteStore) -> None:
    resp = store.observe_memory(ObserveMemoryRequest(
        scope="t", kind=MemoryKind.FACT, basis=Basis.DIRECT_CAPTURE,
        content={"a": 1}, source_observed_at=_seen(),
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=resp.memory.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    assert store.get_memory(resp.memory.memory_id).source_observed_at == _seen()


def test_source_observed_at_carries_through_custody_promotion(store: SQLiteStore) -> None:
    resp = store.observe_memory(ObserveMemoryRequest(
        scope="t", kind=MemoryKind.FACT, basis=Basis.DIRECT_CAPTURE,
        content={"a": 1}, source_observed_at=_seen(),
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=resp.memory.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    adj = store.adjudicate_memory(AdjudicateMemoryRequest(
        memory_id=resp.memory.memory_id,
        motion=AdjudicationMotion.REAFFIRM,
        custody_record={"sig": "x"},
        actor=ActorRef(principal_id="cust", auth_method="local"),
    ))
    assert store.get_memory(adj.memory.memory_id).source_observed_at == _seen()


def test_unmigrated_db_reads_source_observed_at_as_none(tmp_path: Path) -> None:
    """A row from a DB that predates the column reads as None, not an error
    (AG opens stores without initialize)."""
    db = tmp_path / "t.db"
    store = SQLiteStore(db)
    store.initialize()
    resp = store.observe_memory(ObserveMemoryRequest(
        scope="t", kind=MemoryKind.FACT, basis=Basis.DIRECT_CAPTURE, content={"a": 1},
    ))
    # Drop the value to simulate a pre-column row, then re-read.
    conn = sqlite3.connect(str(db))
    conn.execute(
        "UPDATE memory_objects SET source_observed_at=NULL WHERE memory_id=?",
        (resp.memory.memory_id,),
    )
    conn.commit()
    conn.close()
    assert SQLiteStore(db).get_memory(resp.memory.memory_id).source_observed_at is None
