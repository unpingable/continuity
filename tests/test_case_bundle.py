"""Tests for the derived case bundle endpoint."""

from continuity.api.models import (
    Basis,
    CommitMemoryRequest,
    GetCaseRequest,
    MemoryKind,
    MemoryStatus,
    ObserveMemoryRequest,
    PremiseRef,
    RelianceClass,
    RevokeMemoryRequest,
)
from continuity.store.sqlite import SQLiteStore


def _observe(
    store: SQLiteStore,
    scope: str,
    kind: MemoryKind,
    content: dict | None = None,
    basis: Basis = Basis.DIRECT_CAPTURE,
) -> str:
    resp = store.observe_memory(ObserveMemoryRequest(
        scope=scope,
        kind=kind,
        basis=basis,
        content=content or {"text": f"{kind} in {scope}"},
    ))
    return resp.memory.memory_id


def test_empty_case_returns_empty_bundle(store: SQLiteStore) -> None:
    bundle = store.get_case(GetCaseRequest(scope="case:nothing"))

    assert bundle.scope == "case:nothing"
    assert bundle.total_memories == 0
    assert bundle.summary is None
    assert bundle.title is None
    assert bundle.last_touch is None
    assert bundle.facts == []
    assert bundle.hypotheses == []
    assert bundle.decisions == []
    assert bundle.constraints == []
    assert bundle.notes == []
    assert bundle.other == []


def test_case_buckets_by_kind(store: SQLiteStore) -> None:
    scope = "case:bucket-test"
    _observe(store, scope, MemoryKind.FACT, {"text": "f1"})
    _observe(store, scope, MemoryKind.FACT, {"text": "f2"})
    _observe(store, scope, MemoryKind.HYPOTHESIS, {"text": "h1"})
    _observe(store, scope, MemoryKind.DECISION, {"text": "d1"})
    _observe(store, scope, MemoryKind.CONSTRAINT, {"text": "lesson"})
    _observe(store, scope, MemoryKind.NOTE, {"text": "experiment"})
    _observe(store, scope, MemoryKind.NEXT_ACTION, {
        "project": "p", "action": "do thing",
    })

    bundle = store.get_case(GetCaseRequest(scope=scope))

    assert bundle.total_memories == 7
    assert len(bundle.facts) == 2
    assert len(bundle.hypotheses) == 1
    assert len(bundle.decisions) == 1
    assert len(bundle.constraints) == 1
    assert len(bundle.notes) == 1
    assert len(bundle.other) == 1
    assert bundle.summary is None


def test_case_summary_provides_title(store: SQLiteStore) -> None:
    scope = "case:titled"
    summary_id = _observe(store, scope, MemoryKind.SUMMARY, {
        "title": "The MCP Stdio Incident",
        "status": "resolved",
    })
    store.commit_memory(CommitMemoryRequest(
        memory_id=summary_id,
        reliance_class=RelianceClass.RETRIEVE_ONLY,
    ))

    bundle = store.get_case(GetCaseRequest(scope=scope))

    assert bundle.summary is not None
    assert bundle.summary.memory.memory_id == summary_id
    assert bundle.title == "The MCP Stdio Incident"


def test_case_prefers_committed_summary_over_observed(store: SQLiteStore) -> None:
    scope = "case:two-summaries"
    obs = _observe(store, scope, MemoryKind.SUMMARY, {"title": "draft"})
    committed = _observe(store, scope, MemoryKind.SUMMARY, {"title": "final"})
    store.commit_memory(CommitMemoryRequest(
        memory_id=committed,
        reliance_class=RelianceClass.RETRIEVE_ONLY,
    ))

    bundle = store.get_case(GetCaseRequest(scope=scope))

    assert bundle.summary is not None
    assert bundle.summary.memory.memory_id == committed
    assert bundle.title == "final"
    # The observed one is still findable as 'unused' — it's not in any bucket
    # because summary is singular. That's intentional; only one summary per case.
    _ = obs


def test_case_includes_revoked_items(store: SQLiteStore) -> None:
    """Ruled-out hypotheses must remain in the bundle as evidence."""
    scope = "case:ruled-out"
    h1 = _observe(store, scope, MemoryKind.HYPOTHESIS, {"claim": "h1"})
    h2 = _observe(store, scope, MemoryKind.HYPOTHESIS, {"claim": "h2"})
    store.revoke_memory(RevokeMemoryRequest(
        memory_id=h1,
        reason="ruled out by experiment",
    ))

    bundle = store.get_case(GetCaseRequest(scope=scope))

    assert len(bundle.hypotheses) == 2
    statuses = {item.memory.status for item in bundle.hypotheses}
    assert MemoryStatus.REVOKED in statuses
    assert MemoryStatus.OBSERVED in statuses
    _ = h2


def test_case_items_carry_rely_state(store: SQLiteStore) -> None:
    scope = "case:rely-state"
    fact_id = _observe(store, scope, MemoryKind.FACT, {"text": "actionable fact"})
    store.commit_memory(CommitMemoryRequest(
        memory_id=fact_id,
        reliance_class=RelianceClass.ACTIONABLE,
    ))

    observed_id = _observe(store, scope, MemoryKind.FACT, {"text": "still observed"})

    bundle = store.get_case(GetCaseRequest(scope=scope))

    by_id = {item.memory.memory_id: item for item in bundle.facts}
    assert by_id[fact_id].rely_ok is True
    assert "actionable" in by_id[fact_id].rely_reason
    assert by_id[observed_id].rely_ok is False
    assert "not committed" in by_id[observed_id].rely_reason


def test_case_summary_remains_non_actionable(store: SQLiteStore) -> None:
    """The bundle is a navigation aid; the summary cannot be relied on."""
    scope = "case:summary-not-rely"
    summary_id = _observe(store, scope, MemoryKind.SUMMARY, {
        "title": "case",
        "story": "what happened",
    })
    store.commit_memory(CommitMemoryRequest(
        memory_id=summary_id,
        reliance_class=RelianceClass.ADVISORY,
    ))

    bundle = store.get_case(GetCaseRequest(scope=scope))

    assert bundle.summary is not None
    # advisory is allowed for summary; actionable is not
    assert bundle.summary.rely_ok is True

    # Now try to make it actionable — should be blocked
    summary_id2 = _observe(store, scope, MemoryKind.SUMMARY, {"title": "v2"})
    store.commit_memory(CommitMemoryRequest(
        memory_id=summary_id2,
        reliance_class=RelianceClass.ACTIONABLE,
    ))
    bundle2 = store.get_case(GetCaseRequest(scope=scope))
    assert bundle2.summary is not None
    assert bundle2.summary.rely_ok is False
    assert "summary" in bundle2.summary.rely_reason


def test_case_chronological_order(store: SQLiteStore) -> None:
    scope = "case:chrono"
    f1 = _observe(store, scope, MemoryKind.FACT, {"n": 1})
    f2 = _observe(store, scope, MemoryKind.FACT, {"n": 2})
    f3 = _observe(store, scope, MemoryKind.FACT, {"n": 3})

    bundle = store.get_case(GetCaseRequest(scope=scope))

    ids = [item.memory.memory_id for item in bundle.facts]
    assert ids == [f1, f2, f3]


def test_case_last_touch_is_max_updated(store: SQLiteStore) -> None:
    scope = "case:touch"
    fact_id = _observe(store, scope, MemoryKind.FACT, {"text": "t"})
    _observe(store, scope, MemoryKind.NOTE, {"text": "n"})

    bundle_before = store.get_case(GetCaseRequest(scope=scope))
    touch_before = bundle_before.last_touch
    assert touch_before is not None

    # Commit one — that updates the row
    store.commit_memory(CommitMemoryRequest(
        memory_id=fact_id,
        reliance_class=RelianceClass.RETRIEVE_ONLY,
    ))

    bundle_after = store.get_case(GetCaseRequest(scope=scope))
    assert bundle_after.last_touch is not None
    assert bundle_after.last_touch >= touch_before


def test_case_scope_isolation(store: SQLiteStore) -> None:
    _observe(store, "case:a", MemoryKind.FACT)
    _observe(store, "case:b", MemoryKind.FACT)
    _observe(store, "case:b", MemoryKind.HYPOTHESIS)

    bundle_a = store.get_case(GetCaseRequest(scope="case:a"))
    bundle_b = store.get_case(GetCaseRequest(scope="case:b"))

    assert bundle_a.total_memories == 1
    assert bundle_b.total_memories == 2
    assert len(bundle_a.facts) == 1
    assert len(bundle_b.hypotheses) == 1
