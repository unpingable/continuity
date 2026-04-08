"""Test idempotency: same key returns same result, different type raises."""

import pytest

from continuity.api.models import (
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    ObserveMemoryRequest,
    RelianceClass,
)
from continuity.store.sqlite import IdempotencyConflictError, SQLiteStore


def test_observe_idempotent(store: SQLiteStore) -> None:
    req = ObserveMemoryRequest(
        scope="idem-test",
        kind=MemoryKind.NOTE,
        basis=Basis.DIRECT_CAPTURE,
        content={"note": "same note twice"},
        idempotency_key="idem-observe-1",
    )

    first = store.observe_memory(req)
    second = store.observe_memory(req)

    assert first.memory.memory_id == second.memory.memory_id
    assert first.event.event_id == second.event.event_id
    assert first.receipt.receipt_id == second.receipt.receipt_id


def test_commit_idempotent(store: SQLiteStore) -> None:
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="idem-test",
        kind=MemoryKind.DECISION,
        basis=Basis.OPERATOR_ASSERTION,
        content={"decision": "keep it boring"},
    ))

    req = CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.RETRIEVE_ONLY,
        idempotency_key="idem-commit-1",
    )

    first = store.commit_memory(req)
    second = store.commit_memory(req)

    assert first.memory.memory_id == second.memory.memory_id
    assert first.receipt.receipt_id == second.receipt.receipt_id


def test_idempotency_key_type_conflict(store: SQLiteStore) -> None:
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="idem-test",
        kind=MemoryKind.NOTE,
        basis=Basis.DIRECT_CAPTURE,
        content={"note": "conflict test"},
        idempotency_key="shared-key",
    ))

    with pytest.raises(IdempotencyConflictError):
        store.commit_memory(CommitMemoryRequest(
            memory_id=obs.memory.memory_id,
            reliance_class=RelianceClass.RETRIEVE_ONLY,
            idempotency_key="shared-key",  # same key, different op type
        ))
