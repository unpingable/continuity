"""Test the core observe -> commit -> revoke lifecycle."""

import pytest

from continuity.api.models import (
    ActorRef,
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    MemoryStatus,
    ObserveMemoryRequest,
    RelianceClass,
    RevokeMemoryRequest,
    SourceRef,
)
from continuity.store.sqlite import (
    InvalidTransitionError,
    MemoryNotFoundError,
    SQLiteStore,
)


def _operator() -> ActorRef:
    return ActorRef(principal_id="operator:jbeck", auth_method="local")


def test_observe_creates_memory(store: SQLiteStore) -> None:
    resp = store.observe_memory(ObserveMemoryRequest(
        scope="test-project",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"claim": "the sky is blue"},
        source_refs=[SourceRef(ref="observation:1", kind="test")],
        confidence=0.9,
    ))

    assert resp.memory.status == MemoryStatus.OBSERVED
    assert resp.memory.reliance_class == RelianceClass.NONE
    assert resp.memory.scope == "test-project"
    assert resp.event.event_type == "observe"
    assert resp.receipt.receipt_type == "memory.observe"
    assert resp.receipt.hash
    assert resp.receipt.prev_hash is None  # first receipt


def test_commit_promotes_memory(store: SQLiteStore) -> None:
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="test-project",
        kind=MemoryKind.DECISION,
        basis=Basis.OPERATOR_ASSERTION,
        content={"decision": "use SQLite"},
    ))

    resp = store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
        note="reviewed and approved",
    ))

    assert resp.memory.status == MemoryStatus.COMMITTED
    assert resp.memory.reliance_class == RelianceClass.ADVISORY
    assert resp.receipt.prev_hash == obs.receipt.hash  # chain


def test_revoke_marks_memory(store: SQLiteStore) -> None:
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="test-project",
        kind=MemoryKind.HYPOTHESIS,
        basis=Basis.INFERENCE,
        content={"hypothesis": "connection pool leaking"},
    ))

    resp = store.revoke_memory(RevokeMemoryRequest(
        memory_id=obs.memory.memory_id,
        reason="turned out to be a DNS issue",
        revoked_by=_operator(),
    ))

    assert resp.memory.status == MemoryStatus.REVOKED
    assert resp.receipt.receipt_type == "memory.revoke"


def test_cannot_commit_revoked(store: SQLiteStore) -> None:
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="test-project",
        kind=MemoryKind.NOTE,
        basis=Basis.DIRECT_CAPTURE,
        content={"note": "ephemeral"},
    ))

    store.revoke_memory(RevokeMemoryRequest(
        memory_id=obs.memory.memory_id,
        reason="no longer relevant",
    ))

    with pytest.raises(InvalidTransitionError):
        store.commit_memory(CommitMemoryRequest(
            memory_id=obs.memory.memory_id,
            reliance_class=RelianceClass.RETRIEVE_ONLY,
        ))


def test_cannot_revoke_twice(store: SQLiteStore) -> None:
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="test-project",
        kind=MemoryKind.NOTE,
        basis=Basis.DIRECT_CAPTURE,
        content={"note": "once is enough"},
    ))

    store.revoke_memory(RevokeMemoryRequest(
        memory_id=obs.memory.memory_id,
        reason="first revocation",
    ))

    with pytest.raises(InvalidTransitionError):
        store.revoke_memory(RevokeMemoryRequest(
            memory_id=obs.memory.memory_id,
            reason="second revocation",
        ))


def test_get_nonexistent_raises(store: SQLiteStore) -> None:
    with pytest.raises(MemoryNotFoundError):
        store.get_memory("mem_does_not_exist_at_all_nope")


def test_full_lifecycle_receipt_chain(store: SQLiteStore) -> None:
    """observe -> commit -> revoke should produce a valid receipt chain."""
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="chain-test",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "receipt chains work"},
    ))

    cmt = store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
    ))

    rev = store.revoke_memory(RevokeMemoryRequest(
        memory_id=obs.memory.memory_id,
        reason="testing chain",
    ))

    assert obs.receipt.prev_hash is None
    assert cmt.receipt.prev_hash == obs.receipt.hash
    assert rev.receipt.prev_hash == cmt.receipt.hash
