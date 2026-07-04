"""Test the rely gate: premise-aware reliance checking.

This is the test that proves the thesis:
  - A committed next_action with valid premises is rely_ok=True
  - Revoking a hard premise flips it to rely_ok=False
  - The link still exists in explain (history is preserved)
"""

from continuity.api.models import (
    ActorRef,
    AdjudicateMemoryRequest,
    AdjudicationMotion,
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    ObserveMemoryRequest,
    PremiseRef,
    RelianceClass,
    RevokeMemoryRequest,
)
from continuity.store.sqlite import SQLiteStore


def _operator() -> ActorRef:
    return ActorRef(principal_id="operator:jbeck", auth_method="local")


def test_rely_ok_with_valid_premises(store: SQLiteStore) -> None:
    """Committed next_action depending on committed hypothesis = rely_ok."""
    # Create and commit the hypothesis
    hyp = store.observe_memory(ObserveMemoryRequest(
        scope="rely-test",
        kind=MemoryKind.HYPOTHESIS,
        basis=Basis.INFERENCE,
        content={"hypothesis": "connection pool is leaking"},
        confidence=0.7,
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=hyp.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))

    # Create next_action that depends on the hypothesis
    action = store.observe_memory(ObserveMemoryRequest(
        scope="rely-test",
        kind=MemoryKind.NEXT_ACTION,
        basis=Basis.INFERENCE,
        content={"action": "restart pool hourly"},
        premises=[
            PremiseRef(
                memory_id=hyp.memory.memory_id,
                relation="depends_on",
                strength="hard",
            ),
        ],
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=action.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))

    # Check: should be rely_ok because hypothesis is still committed
    explain = store.explain_memory(action.memory.memory_id)
    assert explain.rely_ok is True
    assert len(explain.premises) == 1
    assert explain.premises[0].src_memory_id == hyp.memory.memory_id


def test_revoked_premise_taints_dependent(store: SQLiteStore) -> None:
    """Revoking a hard premise makes the dependent not rely_ok."""
    # Hypothesis
    hyp = store.observe_memory(ObserveMemoryRequest(
        scope="taint-test",
        kind=MemoryKind.HYPOTHESIS,
        basis=Basis.INFERENCE,
        content={"hypothesis": "it's a DNS problem"},
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=hyp.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))

    # Action depending on hypothesis
    action = store.observe_memory(ObserveMemoryRequest(
        scope="taint-test",
        kind=MemoryKind.NEXT_ACTION,
        basis=Basis.INFERENCE,
        content={"action": "flush DNS cache"},
        premises=[
            PremiseRef(
                memory_id=hyp.memory.memory_id,
                relation="depends_on",
                strength="hard",
            ),
        ],
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=action.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))

    # Revoke the hypothesis
    store.revoke_memory(RevokeMemoryRequest(
        memory_id=hyp.memory.memory_id,
        reason="turned out to be a firewall rule",
        revoked_by=_operator(),
    ))

    # Action should now be tainted
    explain = store.explain_memory(action.memory.memory_id)
    assert explain.rely_ok is False
    assert "revoked" in explain.rely_reason

    # But the link still exists — history preserved
    assert len(explain.premises) == 1
    assert explain.premises[0].status == "active"  # link itself not revoked
    assert explain.premises[0].src_memory_id == hyp.memory.memory_id


def test_soft_premise_does_not_taint(store: SQLiteStore) -> None:
    """Revoking a soft premise does not affect rely_ok."""
    hyp = store.observe_memory(ObserveMemoryRequest(
        scope="soft-test",
        kind=MemoryKind.HYPOTHESIS,
        basis=Basis.INFERENCE,
        content={"hypothesis": "maybe related to GC pressure"},
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=hyp.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))

    action = store.observe_memory(ObserveMemoryRequest(
        scope="soft-test",
        kind=MemoryKind.NEXT_ACTION,
        basis=Basis.OPERATOR_ASSERTION,
        content={"action": "increase heap size"},
        premises=[
            PremiseRef(
                memory_id=hyp.memory.memory_id,
                relation="supports",
                strength="soft",
                note="informational, not load-bearing",
            ),
        ],
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=action.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))

    # Revoke the soft premise
    store.revoke_memory(RevokeMemoryRequest(
        memory_id=hyp.memory.memory_id,
        reason="GC pressure was normal",
        revoked_by=_operator(),
    ))

    # Action should still be rely_ok — soft premise doesn't taint
    explain = store.explain_memory(action.memory.memory_id)
    assert explain.rely_ok is True


def test_explain_shows_dependents(store: SQLiteStore) -> None:
    """Explain on a premise should show what depends on it."""
    fact = store.observe_memory(ObserveMemoryRequest(
        scope="dep-test",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "database is PostgreSQL"},
    ))

    note = store.observe_memory(ObserveMemoryRequest(
        scope="dep-test",
        kind=MemoryKind.NOTE,
        basis=Basis.INFERENCE,
        content={"note": "use pg_stat_statements for profiling"},
        premises=[
            PremiseRef(
                memory_id=fact.memory.memory_id,
                relation="derived_from",
            ),
        ],
    ))

    explain = store.explain_memory(fact.memory.memory_id)
    assert len(explain.dependents) == 1
    assert explain.dependents[0].dst_memory_id == note.memory.memory_id


def test_uncommitted_memory_not_rely_ok(store: SQLiteStore) -> None:
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="uncommitted-test",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "just observed, not committed"},
    ))

    explain = store.explain_memory(obs.memory.memory_id)
    assert explain.rely_ok is False
    assert "observed" in explain.rely_reason


def test_policy_blocks_inference_actionable(store: SQLiteStore) -> None:
    """Inference basis + actionable reliance = deny by default."""
    from continuity.memory.policy import MemoryPolicy

    obs = store.observe_memory(ObserveMemoryRequest(
        scope="policy-test",
        kind=MemoryKind.FACT,
        basis=Basis.INFERENCE,
        content={"fact": "inferred from logs"},
    ))

    # Agent-authored inference caps at advisory, so commit it there first, then
    # custody-promote to custodian_signed + actionable (the only tier whose cap
    # permits actionable). Even then, the rely-time basis check blocks
    # inference+actionable — the gate this test pins.
    store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
    ))
    promoted = store.adjudicate_memory(AdjudicateMemoryRequest(
        memory_id=obs.memory.memory_id,
        motion=AdjudicationMotion.REAFFIRM,
        custody_record={"custodian": "operator:test", "sig": "x"},
        reliance_class=RelianceClass.ACTIONABLE,
        actor=_operator(),
    ))

    memory = store.get_memory(promoted.memory.memory_id)
    policy = MemoryPolicy()
    result = policy.allow_rely(memory)
    assert not result.allowed
    assert "inference" in result.reason


# ---------------------------------------------------------------------------
# Time discipline V1: explicit evaluation_time on the rely path
# (docs/gaps/CONTINUITY_TIME_DISCIPLINE.md)
# ---------------------------------------------------------------------------


def _committed_expiring_memory(store: SQLiteStore, expires_at):
    """Helper: observe + commit a fact with an expires_at; return memory_id."""
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="expiry-test",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "will expire"},
        expires_at=expires_at,
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
        expires_at=expires_at,
    ))
    return obs.memory.memory_id


def test_historical_evaluation_time_returns_not_expired(store: SQLiteStore) -> None:
    """A memory now-expired was not yet expired at a past evaluation_time."""
    from datetime import datetime, timedelta, timezone

    expires = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mem_id = _committed_expiring_memory(store, expires)

    # Past evaluation: before expiry -> rely_ok.
    past = expires - timedelta(days=30)
    past_explain = store.explain_memory(mem_id, evaluation_time=past)
    assert past_explain.rely_ok is True, past_explain.rely_reason

    # Default (now) evaluation: well past expiry -> not rely_ok.
    current = store.explain_memory(mem_id)
    assert current.rely_ok is False
    assert "expired" in current.rely_reason


def test_future_evaluation_time_returns_expired(store: SQLiteStore) -> None:
    """An explicit future evaluation_time past expires_at returns expired."""
    from datetime import datetime, timedelta, timezone

    expires = datetime(2099, 1, 1, tzinfo=timezone.utc)  # not yet expired wall-clock
    mem_id = _committed_expiring_memory(store, expires)

    # Default evaluation: not expired (wall-clock is well before 2099).
    current = store.explain_memory(mem_id)
    assert current.rely_ok is True

    # Future evaluation: past the expires_at -> expired.
    future = expires + timedelta(days=1)
    future_explain = store.explain_memory(mem_id, evaluation_time=future)
    assert future_explain.rely_ok is False
    assert "expired" in future_explain.rely_reason


def test_explain_response_surfaces_evaluation_time(store: SQLiteStore) -> None:
    """ExplainMemoryResponse.evaluation_time reflects the time actually used."""
    from datetime import datetime, timezone

    obs = store.observe_memory(ObserveMemoryRequest(
        scope="eval-time-test",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "audit me"},
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))

    # Explicit evaluation_time round-trips.
    t = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    resp = store.explain_memory(obs.memory.memory_id, evaluation_time=t)
    assert resp.evaluation_time == t

    # Default boundary resolves to a real datetime (never None).
    default_resp = store.explain_memory(obs.memory.memory_id)
    assert default_resp.evaluation_time is not None


def test_trigger_dropped_app_owns_updated_at(store: SQLiteStore) -> None:
    """After init the legacy updated_at trigger must not exist; app owns the clock."""
    import sqlite3
    conn = sqlite3.connect(str(store.db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'trigger' AND name = 'trg_memory_objects_updated_at'"
        ).fetchone()
    finally:
        conn.close()
    assert row is None, "legacy updated_at trigger should not exist on a fresh store"
