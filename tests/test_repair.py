"""Test repair_memory: narrow patch semantics + receipt chain integrity.

Repair fixes recording errors (content/source_refs/confidence). It must NOT
permit scope/kind/basis/status/reliance_class/supersedes/expires_at/premises/
revoked_by changes — those go through observe/commit/revoke/supersede.
"""

import pytest

from continuity.api.models import (
    ActorRef,
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    MemoryStatus,
    ObserveMemoryRequest,
    RelianceClass,
    RepairMemoryRequest,
    RevokeMemoryRequest,
    SourceRef,
)
from continuity.store.sqlite import (
    InvalidTransitionError,
    SQLiteStore,
)


def _operator() -> ActorRef:
    return ActorRef(principal_id="operator:jbeck", auth_method="local")


def _committed_fact(store: SQLiteStore) -> str:
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="repair-test",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "typo here"},
        confidence=0.6,
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))
    return obs.memory.memory_id


def test_repair_content_patch_updates_memory_and_emits_receipt(
    store: SQLiteStore,
) -> None:
    mem_id = _committed_fact(store)

    resp = store.repair_memory(RepairMemoryRequest(
        memory_id=mem_id,
        reason="fix typo in fact text",
        patch={"content": {"fact": "no typo here"}},
        actor=_operator(),
    ))

    assert resp.memory.content == {"fact": "no typo here"}
    assert resp.event.event_type == "repair"
    assert resp.receipt.receipt_type == "memory.repair"
    # Prior content is preserved in the event payload — repair is auditable
    assert resp.event.payload["prior"]["content"] == {"fact": "typo here"}
    assert resp.event.payload["patch"] == {"content": {"fact": "no typo here"}}


def test_repair_preserves_status_and_reliance_class(store: SQLiteStore) -> None:
    """Repair must not change rely semantics — status and reliance unchanged."""
    mem_id = _committed_fact(store)
    before = store.get_memory(mem_id)

    store.repair_memory(RepairMemoryRequest(
        memory_id=mem_id,
        reason="rebalance confidence",
        patch={"confidence": 0.9},
        actor=_operator(),
    ))

    after = store.get_memory(mem_id)
    assert after.status == before.status == MemoryStatus.COMMITTED
    assert after.reliance_class == before.reliance_class
    assert after.confidence == 0.9


def test_repair_rejects_scope_change(store: SQLiteStore) -> None:
    mem_id = _committed_fact(store)
    with pytest.raises(ValueError, match="repair patch may only set"):
        RepairMemoryRequest(
            memory_id=mem_id,
            reason="move to different scope",
            patch={"scope": "elsewhere"},
            actor=_operator(),
        )


def test_repair_rejects_reliance_class_change(store: SQLiteStore) -> None:
    mem_id = _committed_fact(store)
    with pytest.raises(ValueError, match="repair patch may only set"):
        RepairMemoryRequest(
            memory_id=mem_id,
            reason="bump reliance class",
            patch={"reliance_class": "actionable"},
            actor=_operator(),
        )


def test_repair_rejects_status_and_premises(store: SQLiteStore) -> None:
    mem_id = _committed_fact(store)
    with pytest.raises(ValueError, match="repair patch may only set"):
        RepairMemoryRequest(
            memory_id=mem_id,
            reason="revoke through repair",
            patch={"status": "revoked"},
            actor=_operator(),
        )
    with pytest.raises(ValueError, match="repair patch may only set"):
        RepairMemoryRequest(
            memory_id=mem_id,
            reason="add a premise sneakily",
            patch={"premises": [{"memory_id": "mem_other"}]},
            actor=_operator(),
        )


def test_repair_rejects_supersedes_and_expires(store: SQLiteStore) -> None:
    mem_id = _committed_fact(store)
    with pytest.raises(ValueError, match="repair patch may only set"):
        RepairMemoryRequest(
            memory_id=mem_id,
            reason="point at a successor through repair",
            patch={"supersedes": "mem_someone"},
            actor=_operator(),
        )
    with pytest.raises(ValueError, match="repair patch may only set"):
        RepairMemoryRequest(
            memory_id=mem_id,
            reason="quietly expire it",
            patch={"expires_at": "2026-01-01T00:00:00Z"},
            actor=_operator(),
        )


def test_repair_idempotent_via_key(store: SQLiteStore) -> None:
    mem_id = _committed_fact(store)
    key = "repair-idem-1"

    first = store.repair_memory(RepairMemoryRequest(
        memory_id=mem_id,
        reason="fix",
        patch={"content": {"fact": "v2"}},
        actor=_operator(),
        idempotency_key=key,
    ))
    second = store.repair_memory(RepairMemoryRequest(
        memory_id=mem_id,
        reason="fix",
        patch={"content": {"fact": "v2"}},
        actor=_operator(),
        idempotency_key=key,
    ))

    assert first.event.event_id == second.event.event_id
    assert first.receipt.receipt_id == second.receipt.receipt_id


def test_repair_chains_to_prior_receipt(store: SQLiteStore) -> None:
    """Repair receipt's prev_hash points at the last receipt before it."""
    mem_id = _committed_fact(store)
    # Snapshot the latest receipt hash before the repair.
    import sqlite3
    conn = sqlite3.connect(str(store.db_path))
    try:
        prior_hash = conn.execute(
            "SELECT hash FROM receipts ORDER BY created_at DESC, receipt_id DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()

    resp = store.repair_memory(RepairMemoryRequest(
        memory_id=mem_id,
        reason="confidence rebalance",
        patch={"confidence": 0.8},
        actor=_operator(),
    ))

    assert resp.receipt.prev_hash == prior_hash


def test_repair_refused_on_revoked_memory(store: SQLiteStore) -> None:
    mem_id = _committed_fact(store)
    store.revoke_memory(RevokeMemoryRequest(
        memory_id=mem_id, reason="wrong", revoked_by=_operator(),
    ))
    with pytest.raises(InvalidTransitionError, match="revoked"):
        store.repair_memory(RepairMemoryRequest(
            memory_id=mem_id,
            reason="fix it anyway",
            patch={"content": {"fact": "still wrong"}},
            actor=_operator(),
        ))


def test_repair_replaces_source_refs(store: SQLiteStore) -> None:
    mem_id = _committed_fact(store)
    new_refs = [
        {"kind": "url", "ref": "https://example.com/correct"},
        {"kind": "doc", "ref": "spec.md", "note": "section 3"},
    ]
    resp = store.repair_memory(RepairMemoryRequest(
        memory_id=mem_id,
        reason="point at the right source",
        patch={"source_refs": new_refs},
        actor=_operator(),
    ))
    assert len(resp.memory.source_refs) == 2
    assert resp.memory.source_refs[0].ref == "https://example.com/correct"
