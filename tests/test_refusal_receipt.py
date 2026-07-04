"""Test MemoryPolicy wire-up: refusal receipts on denied writes.

Per the cross-component-reliance plan (Phase 0.3 amendment):
a policy-denied write produces no memory row and no memory event,
but DOES append a hash-chained `memory.refused` receipt carrying:
  - intended_event
  - policy_reason
  - request_hash  (sha256 over canonical(request) — no requester trust)
  - evaluation_time
  - actor / standing

So denied writes are not invisible; they are auditable via the receipt chain.
"""

import sqlite3

import pytest

from continuity.api.models import (
    ActorRef,
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    ObserveMemoryRequest,
    RelianceClass,
    RepairMemoryRequest,
)
from continuity.memory.policy import Decision, MemoryPolicy, PolicyResult
from continuity.store.sqlite import (
    PolicyDeniedError,
    SQLiteStore,
)


def _operator() -> ActorRef:
    return ActorRef(principal_id="operator:test", auth_method="local")


class _DenyAllObserve(MemoryPolicy):
    def allow_observe(self, req):  # type: ignore[override]
        return PolicyResult(Decision.DENY, "observe denied for test")


class _DenyAllCommit(MemoryPolicy):
    def allow_commit(self, req):  # type: ignore[override]
        return PolicyResult(Decision.DENY, "commit denied for test")


class _DenyAllRepair(MemoryPolicy):
    def allow_repair(self, req):  # type: ignore[override]
        return PolicyResult(Decision.DENY, "repair denied for test")


# -- helpers ---------------------------------------------------------------


def _count_rows(db_path: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            "memory_objects": conn.execute(
                "SELECT COUNT(*) FROM memory_objects"
            ).fetchone()[0],
            "memory_events": conn.execute(
                "SELECT COUNT(*) FROM memory_events"
            ).fetchone()[0],
            "receipts": conn.execute(
                "SELECT COUNT(*) FROM receipts"
            ).fetchone()[0],
            "refusals": conn.execute(
                "SELECT COUNT(*) FROM receipts WHERE receipt_type = 'memory.refused'"
            ).fetchone()[0],
        }
    finally:
        conn.close()


# -- tests -----------------------------------------------------------------


def test_denied_observe_writes_only_refusal_receipt(tmp_path) -> None:
    db = tmp_path / "deny-obs.db"
    store = SQLiteStore(db, policy=_DenyAllObserve())
    store.initialize()

    req = ObserveMemoryRequest(
        scope="refusal-test",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "should never land"},
        actor=_operator(),
    )

    with pytest.raises(PolicyDeniedError) as excinfo:
        store.observe_memory(req)

    assert "observe denied" in excinfo.value.reason
    counts = _count_rows(str(db))
    assert counts["memory_objects"] == 0
    assert counts["memory_events"] == 0
    assert counts["receipts"] == 1
    assert counts["refusals"] == 1

    # The receipt's content carries the auditable fields.
    receipt = excinfo.value.refusal_receipt
    assert receipt.receipt_type == "memory.refused"
    assert receipt.content["intended_event"] == "observe"
    assert receipt.content["policy_reason"] == "observe denied for test"
    assert receipt.content["request_hash"].startswith("sha256:")
    assert receipt.content["evaluation_time"] is not None
    assert receipt.content["actor"]["principal_id"] == "operator:test"


def test_denied_commit_leaves_no_row_no_event(tmp_path) -> None:
    db = tmp_path / "deny-cmt.db"
    # Use permissive observe + denying commit so we exercise the commit path
    # against an already-observed memory.
    class _Allow_Obs_Deny_Cmt(MemoryPolicy):
        def allow_commit(self, req):  # type: ignore[override]
            return PolicyResult(Decision.DENY, "no commits allowed")

    store = SQLiteStore(db, policy=_Allow_Obs_Deny_Cmt())
    store.initialize()

    obs = store.observe_memory(ObserveMemoryRequest(
        scope="refusal-test",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "observed but commit blocked"},
    ))

    counts_before = _count_rows(str(db))

    with pytest.raises(PolicyDeniedError):
        store.commit_memory(CommitMemoryRequest(
            memory_id=obs.memory.memory_id,
            reliance_class=RelianceClass.ADVISORY,
            approved_by=_operator(),
        ))

    counts_after = _count_rows(str(db))
    # No new memory row, no new event; one new refusal receipt.
    assert counts_after["memory_objects"] == counts_before["memory_objects"]
    assert counts_after["memory_events"] == counts_before["memory_events"]
    assert counts_after["receipts"] == counts_before["receipts"] + 1
    assert counts_after["refusals"] == counts_before["refusals"] + 1


def test_refusal_chains_to_prior_receipt(tmp_path) -> None:
    """The refusal receipt's prev_hash points at the last receipt before it."""
    db = tmp_path / "chain.db"
    # Observe succeeds (default policy), then a denying commit policy
    # produces a refusal that chains off the observe receipt.
    class _Allow_Obs_Deny_Cmt(MemoryPolicy):
        def allow_commit(self, req):  # type: ignore[override]
            return PolicyResult(Decision.DENY, "no commits")

    store = SQLiteStore(db, policy=_Allow_Obs_Deny_Cmt())
    store.initialize()

    obs = store.observe_memory(ObserveMemoryRequest(
        scope="chain-test",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "x"},
    ))
    prior_hash = obs.receipt.hash

    with pytest.raises(PolicyDeniedError) as excinfo:
        store.commit_memory(CommitMemoryRequest(
            memory_id=obs.memory.memory_id,
            reliance_class=RelianceClass.ADVISORY,
            approved_by=_operator(),
        ))

    assert excinfo.value.refusal_receipt.prev_hash == prior_hash


def test_request_hash_deterministic(tmp_path) -> None:
    """Same canonical request payload -> same request_hash in the receipt."""
    db1 = tmp_path / "a.db"
    db2 = tmp_path / "b.db"
    store_a = SQLiteStore(db1, policy=_DenyAllObserve())
    store_b = SQLiteStore(db2, policy=_DenyAllObserve())
    store_a.initialize()
    store_b.initialize()

    req = ObserveMemoryRequest(
        scope="hash-test",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "deterministic"},
    )

    with pytest.raises(PolicyDeniedError) as exc_a:
        store_a.observe_memory(req)
    with pytest.raises(PolicyDeniedError) as exc_b:
        store_b.observe_memory(req)

    assert (
        exc_a.value.refusal_receipt.content["request_hash"]
        == exc_b.value.refusal_receipt.content["request_hash"]
    )


def test_default_policy_denies_actionable_without_approver(tmp_path) -> None:
    """Default policy: ACTIONABLE without approved_by is refused at commit."""
    db = tmp_path / "default.db"
    store = SQLiteStore(db)  # default policy
    store.initialize()

    obs = store.observe_memory(ObserveMemoryRequest(
        scope="default-policy-test",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "actionable but unsigned"},
    ))

    with pytest.raises(PolicyDeniedError) as excinfo:
        store.commit_memory(CommitMemoryRequest(
            memory_id=obs.memory.memory_id,
            reliance_class=RelianceClass.ACTIONABLE,
            # no approved_by — that's the violation
        ))

    assert "operator approval" in excinfo.value.reason
    assert excinfo.value.refusal_receipt.content["intended_event"] == "commit"


def test_default_policy_allows_advisory_with_approver(tmp_path) -> None:
    """Default policy: an agent_authored memory commits at advisory (its cap)."""
    db = tmp_path / "default-ok.db"
    store = SQLiteStore(db)
    store.initialize()

    obs = store.observe_memory(ObserveMemoryRequest(
        scope="default-policy-ok",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "advisory and signed"},
    ))

    resp = store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))
    assert resp.memory.reliance_class == "advisory"


def test_agent_authored_actionable_is_refused_by_cap(tmp_path) -> None:
    """Actionable now requires custodian_signed: operator approval alone no
    longer buys it. An agent_authored memory (the default) caps at advisory, so
    an actionable commit is refused with a receipt (MEMORY_AUTHORING_TIER)."""
    db = tmp_path / "cap-refuse.db"
    store = SQLiteStore(db)
    store.initialize()

    obs = store.observe_memory(ObserveMemoryRequest(
        scope="cap-refuse",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "wants to be actionable"},
    ))

    with pytest.raises(PolicyDeniedError) as exc:
        store.commit_memory(CommitMemoryRequest(
            memory_id=obs.memory.memory_id,
            reliance_class=RelianceClass.ACTIONABLE,
            approved_by=_operator(),
        ))
    assert "exceeds the cap" in str(exc.value)
    assert exc.value.refusal_receipt is not None


def test_denied_repair_leaves_refusal(tmp_path) -> None:
    db = tmp_path / "deny-rep.db"
    store = SQLiteStore(db, policy=_DenyAllRepair())
    store.initialize()

    obs = store.observe_memory(ObserveMemoryRequest(
        scope="refuse-repair",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "x"},
    ))
    counts_before = _count_rows(str(db))

    with pytest.raises(PolicyDeniedError):
        store.repair_memory(RepairMemoryRequest(
            memory_id=obs.memory.memory_id,
            reason="typo fix",
            patch={"content": {"fact": "y"}},
            actor=_operator(),
        ))

    counts_after = _count_rows(str(db))
    assert counts_after["memory_objects"] == counts_before["memory_objects"]
    assert counts_after["memory_events"] == counts_before["memory_events"]
    assert counts_after["refusals"] == counts_before["refusals"] + 1
