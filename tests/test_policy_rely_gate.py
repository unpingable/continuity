"""Test the rely gate: premise-aware reliance checking.

This is the test that proves the thesis:
  - A committed next_action with valid premises is rely_ok=True
  - Revoking a hard premise flips it to rely_ok=False
  - The link still exists in explain (history is preserved)
"""

from continuity.api.models import (
    ActorRef,
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

    store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ACTIONABLE,
    ))

    memory = store.get_memory(obs.memory.memory_id)
    policy = MemoryPolicy()
    result = policy.allow_rely(memory)
    assert not result.allowed
    assert "inference" in result.reason
