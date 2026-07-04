"""MEMORY_AUTHORING_TIER V1 — provenance distinct from reliance.

Covers the anti-laundering core: tier caps reliance (enforced at write,
re-applied at read), custodian_signed is never self-declarable via a routine
write, the custody path (adjudicate) is the only way there, the honest
migration backfill, the read-surface effective_reliance, and the doctor check.
"""

from __future__ import annotations

import sqlite3

import pytest

from continuity.api.models import (
    ActorRef,
    AdjudicateMemoryRequest,
    AdjudicationMotion,
    AuthoringTier,
    Basis,
    CommitMemoryRequest,
    GetCaseRequest,
    LinkRelation,
    LinkStrength,
    MemoryKind,
    MemoryStatus,
    ObserveMemoryRequest,
    PremiseRef,
    RelianceClass,
    RelyReasonCode,
    effective_reliance,
    reliance_exceeds,
    tier_cap,
)
from continuity.doctor import TierFindingStatus, check_authoring_tier
from continuity.memory.policy import MemoryPolicy
from continuity.store.sqlite import PolicyDeniedError, SQLiteStore


def _operator() -> ActorRef:
    return ActorRef(principal_id="operator:jbeck", auth_method="local")


def _obs(store, scope="t", kind=MemoryKind.FACT, basis=Basis.DIRECT_CAPTURE,
         content=None, tier=None):
    return store.observe_memory(ObserveMemoryRequest(
        scope=scope, kind=kind, basis=basis,
        content=content or {"x": 1}, authoring_tier=tier,
    )).memory


# --- the cap table (definitional) ------------------------------------------- #


def test_tier_cap_table() -> None:
    assert tier_cap(AuthoringTier.PROVENANCE_UNKNOWN) == RelianceClass.RETRIEVE_ONLY
    assert tier_cap(AuthoringTier.AGENT_AUTHORED) == RelianceClass.ADVISORY
    assert tier_cap(AuthoringTier.RUNTIME_AUTHORED) == RelianceClass.ADVISORY
    assert tier_cap(AuthoringTier.CUSTODIAN_SIGNED) == RelianceClass.ACTIONABLE
    assert tier_cap(AuthoringTier.REVOKED) == RelianceClass.NONE


def test_effective_reliance_is_min_of_stored_and_cap() -> None:
    # agent_authored (cap advisory) stored at retrieve_only -> retrieve_only
    assert effective_reliance("retrieve_only", "agent_authored") == RelianceClass.RETRIEVE_ONLY
    # provenance_unknown (cap retrieve_only) stored at advisory -> capped down
    assert effective_reliance("advisory", "provenance_unknown") == RelianceClass.RETRIEVE_ONLY
    # custodian_signed (cap actionable) stored at actionable -> actionable
    assert effective_reliance("actionable", "custodian_signed") == RelianceClass.ACTIONABLE


# --- write-time tier gate --------------------------------------------------- #


def test_observe_defaults_to_agent_authored(store: SQLiteStore) -> None:
    m = _obs(store)
    assert m.authoring_tier == AuthoringTier.AGENT_AUTHORED


def test_observe_accepts_runtime_authored(store: SQLiteStore) -> None:
    m = _obs(store, tier=AuthoringTier.RUNTIME_AUTHORED)
    assert m.authoring_tier == AuthoringTier.RUNTIME_AUTHORED


@pytest.mark.parametrize("tier", [
    AuthoringTier.CUSTODIAN_SIGNED,
    AuthoringTier.REVOKED,
    AuthoringTier.PROVENANCE_UNKNOWN,
])
def test_observe_refuses_non_self_declarable_tier(store: SQLiteStore, tier) -> None:
    with pytest.raises(PolicyDeniedError) as exc:
        store.observe_memory(ObserveMemoryRequest(
            scope="t", kind=MemoryKind.FACT, basis=Basis.DIRECT_CAPTURE,
            content={"x": 1}, authoring_tier=tier,
        ))
    assert "not self-declarable" in str(exc.value)


# --- commit cap enforcement ------------------------------------------------- #


def test_commit_agent_authored_advisory_ok(store: SQLiteStore) -> None:
    m = _obs(store)
    resp = store.commit_memory(CommitMemoryRequest(
        memory_id=m.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    assert resp.memory.reliance_class == RelianceClass.ADVISORY


def test_commit_agent_authored_actionable_refused(store: SQLiteStore) -> None:
    m = _obs(store)
    with pytest.raises(PolicyDeniedError) as exc:
        store.commit_memory(CommitMemoryRequest(
            memory_id=m.memory_id, reliance_class=RelianceClass.ACTIONABLE,
            approved_by=_operator(),
        ))
    assert "exceeds the cap" in str(exc.value)
    assert exc.value.refusal_receipt is not None


# --- read surface: effective_reliance --------------------------------------- #


def test_get_and_explain_surface_effective_reliance(store: SQLiteStore) -> None:
    m = _obs(store)
    store.commit_memory(CommitMemoryRequest(
        memory_id=m.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    ex = store.explain_memory(m.memory_id)
    assert ex.rely_state.details["authoring_tier"] == "agent_authored"
    assert ex.rely_state.details["effective_reliance"] == "advisory"


# --- custody path: adjudicate reaffirm -------------------------------------- #


def test_reaffirm_mints_custodian_signed_successor(store: SQLiteStore) -> None:
    m = _obs(store)
    store.commit_memory(CommitMemoryRequest(
        memory_id=m.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    resp = store.adjudicate_memory(AdjudicateMemoryRequest(
        memory_id=m.memory_id,
        motion=AdjudicationMotion.REAFFIRM,
        custody_record={"custodian": "operator:jbeck", "sig": "x"},
        reliance_class=RelianceClass.ACTIONABLE,
        actor=_operator(),
    ))
    # Successor is custodian_signed + actionable and relyable.
    assert resp.memory.authoring_tier == AuthoringTier.CUSTODIAN_SIGNED
    assert resp.memory.reliance_class == RelianceClass.ACTIONABLE
    assert resp.superseded_memory_id == m.memory_id
    ex = store.explain_memory(resp.memory.memory_id)
    assert ex.rely_ok is True
    # Original is revoked-by-promotion, preserved as history.
    original = store.get_memory(m.memory_id)
    assert original.status == MemoryStatus.REVOKED
    assert original.revoked_by == resp.memory.memory_id


def test_reaffirm_requires_custody_record() -> None:
    with pytest.raises(ValueError):
        AdjudicateMemoryRequest(
            memory_id="mem_needs_a_record", motion=AdjudicationMotion.REAFFIRM,
        )


def test_retire_revokes(store: SQLiteStore) -> None:
    m = _obs(store)
    store.commit_memory(CommitMemoryRequest(
        memory_id=m.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    resp = store.adjudicate_memory(AdjudicateMemoryRequest(
        memory_id=m.memory_id, motion=AdjudicationMotion.RETIRE,
        reason="author standing retired", actor=_operator(),
    ))
    assert resp.memory.status == MemoryStatus.REVOKED


# --- revoked authoring tier caps reliance to none --------------------------- #


def _force_tier(store: SQLiteStore, memory_id: str, tier: str) -> None:
    """Directly set a row's authoring_tier — stands in for the future
    standing-loss edge, which V1 does not build (deferred). Used only to reach
    states no V1 command produces."""
    conn = sqlite3.connect(str(store.db_path))
    conn.execute(
        "UPDATE memory_objects SET authoring_tier=? WHERE memory_id=?",
        (tier, memory_id),
    )
    conn.commit()
    conn.close()


def test_revoked_tier_caps_rely_to_none(store: SQLiteStore) -> None:
    m = _obs(store)
    store.commit_memory(CommitMemoryRequest(
        memory_id=m.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    _force_tier(store, m.memory_id, "revoked")
    ex = store.explain_memory(m.memory_id)
    assert ex.rely_ok is False
    assert ex.rely_state.code == RelyReasonCode.AUTHORING_TIER_CAPPED
    assert ex.rely_state.details["effective_reliance"] == "none"


# --- migration backfill ----------------------------------------------------- #


def test_migration_backfills_provenance_unknown(tmp_path) -> None:
    """A row present before the column existed reads as provenance_unknown — the
    honest label, not a false claim of agent authorship."""
    db = tmp_path / "legacy.db"
    store = SQLiteStore(db)
    store.initialize()
    m = _obs(store)
    store.commit_memory(CommitMemoryRequest(
        memory_id=m.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    # Simulate a migrated legacy row (backfill sets provenance_unknown; stored
    # reliance is left untouched, so it now exceeds the cap).
    _force_tier(store, m.memory_id, "provenance_unknown")
    ex = store.explain_memory(m.memory_id)
    assert ex.rely_state.details["effective_reliance"] == "retrieve_only"


# --- doctor check ----------------------------------------------------------- #


def test_doctor_flags_cap_exceeded(store: SQLiteStore) -> None:
    m = _obs(store)
    store.commit_memory(CommitMemoryRequest(
        memory_id=m.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    _force_tier(store, m.memory_id, "provenance_unknown")  # cap retrieve_only < advisory
    findings = check_authoring_tier(store)
    flags = [f for f in findings if f.status == TierFindingStatus.FLAG]
    assert any(f.memory_id == m.memory_id and "exceeds the cap" in f.reason for f in flags)


def test_doctor_flags_revoked_tier_cited_as_premise(store: SQLiteStore) -> None:
    premise = _obs(store, content={"x": "premise"})
    store.commit_memory(CommitMemoryRequest(
        memory_id=premise.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    dependent = store.observe_memory(ObserveMemoryRequest(
        scope="t", kind=MemoryKind.DECISION, basis=Basis.DIRECT_CAPTURE,
        content={"d": 1},
        premises=[PremiseRef(
            memory_id=premise.memory_id,
            relation=LinkRelation.DERIVED_FROM,
            strength=LinkStrength.HARD,
        )],
    )).memory
    store.commit_memory(CommitMemoryRequest(
        memory_id=dependent.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    _force_tier(store, premise.memory_id, "revoked")

    findings = check_authoring_tier(store)
    assert any(
        f.status == TierFindingStatus.FLAG
        and f.memory_id == premise.memory_id
        and "active premise" in f.reason
        for f in findings
    )


def test_doctor_clean_store_reports_ok(store: SQLiteStore) -> None:
    m = _obs(store)
    store.commit_memory(CommitMemoryRequest(
        memory_id=m.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    findings = check_authoring_tier(store)
    assert all(f.status == TierFindingStatus.OK for f in findings)


# --- event / receipt record the tier ---------------------------------------- #


def test_commit_event_and_receipt_record_tier(store: SQLiteStore) -> None:
    m = _obs(store)
    resp = store.commit_memory(CommitMemoryRequest(
        memory_id=m.memory_id, reliance_class=RelianceClass.ADVISORY,
    ))
    assert resp.event.authoring_tier == AuthoringTier.AGENT_AUTHORED
    assert resp.receipt.content["authoring_tier"] == "agent_authored"
