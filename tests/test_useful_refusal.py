"""Structured rely refusal — RelyReasonCode + details + rendered message.

V1 of docs/gaps/USEFUL_REFUSAL_EXPLAIN.md. Each discrete rely check now returns
a typed code and structured details alongside the human string. These tests pin:

- every code is produced by the case that should produce it, with the right details;
- the flat ``rely_reason`` string is unchanged (backward compat / the AG pin);
- ``rely_state`` threads additively through explain and case bundles;
- ``contctl why`` renders the decision operator-forward and exits non-zero on refusal.
"""

from __future__ import annotations

import io
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from continuity.api.models import (
    ActorRef,
    AdjudicateMemoryRequest,
    AdjudicationMotion,
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
    RevokeMemoryRequest,
)
from continuity.cli import main
from continuity.store.sqlite import SQLiteStore
from continuity.util.clock import utcnow


def _operator() -> ActorRef:
    return ActorRef(principal_id="operator:jbeck", auth_method="local")


def _observe(store: SQLiteStore, scope, kind, content, *, basis=Basis.DIRECT_CAPTURE):
    return store.observe_memory(ObserveMemoryRequest(
        scope=scope, kind=kind, basis=basis, content=content,
    )).memory


def _commit(store, memory_id, reliance=RelianceClass.ADVISORY):
    return store.commit_memory(CommitMemoryRequest(
        memory_id=memory_id, reliance_class=reliance, approved_by=_operator(),
    )).memory


# --- one code per check, with its structured details ------------------------- #


def test_eligible_carries_class(store: SQLiteStore) -> None:
    mem = _observe(store, "why:ok", MemoryKind.FACT, {"x": 1})
    _commit(store, mem.memory_id, RelianceClass.ADVISORY)
    st = store.explain_memory(mem.memory_id).rely_state
    assert st.rely_ok is True
    assert st.code == RelyReasonCode.ELIGIBLE
    assert st.details["reliance_class"] == "advisory"


def test_status_not_committed_code(store: SQLiteStore) -> None:
    mem = _observe(store, "why:obs", MemoryKind.FACT, {"x": 1})
    st = store.explain_memory(mem.memory_id).rely_state
    assert st.rely_ok is False
    assert st.code == RelyReasonCode.STATUS_NOT_COMMITTED
    assert st.details["status"] == "observed"
    assert "not committed" in st.message  # string unchanged


def test_expired_code_carries_timestamps(store: SQLiteStore) -> None:
    past = utcnow() - timedelta(days=1)
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="why:exp", kind=MemoryKind.FACT, basis=Basis.DIRECT_CAPTURE,
        content={"x": 1}, expires_at=past,
    )).memory
    _commit(store, obs.memory_id, RelianceClass.ADVISORY)
    st = store.explain_memory(obs.memory_id).rely_state
    assert st.rely_ok is False
    assert st.code == RelyReasonCode.EXPIRED
    assert "expires_at" in st.details and "evaluation_time" in st.details
    assert "expired" in st.message


def test_reliance_none_code(store: SQLiteStore) -> None:
    mem = _observe(store, "why:none", MemoryKind.FACT, {"x": 1})
    _commit(store, mem.memory_id, RelianceClass.NONE)
    st = store.explain_memory(mem.memory_id).rely_state
    assert st.rely_ok is False
    assert st.code == RelyReasonCode.RELIANCE_NONE
    assert st.details["reliance_class"] == "none"


def _promote_actionable(store, memory_id):
    """Custody-promote to custodian_signed + actionable — the only path to an
    actionable committed memory. Returns the successor's id."""
    _commit(store, memory_id, RelianceClass.ADVISORY)
    resp = store.adjudicate_memory(AdjudicateMemoryRequest(
        memory_id=memory_id,
        motion=AdjudicationMotion.REAFFIRM,
        custody_record={"custodian": "operator:jbeck", "sig": "test"},
        reliance_class=RelianceClass.ACTIONABLE,
        actor=_operator(),
    ))
    return resp.memory.memory_id


def test_kind_policy_code(store: SQLiteStore) -> None:
    mem = _observe(store, "why:kind", MemoryKind.SUMMARY, {"title": "t", "story": "s"})
    promoted_id = _promote_actionable(store, mem.memory_id)
    st = store.explain_memory(promoted_id).rely_state
    assert st.rely_ok is False
    assert st.code == RelyReasonCode.KIND_BASIS_POLICY
    assert st.details["kind"] == "summary"
    assert st.details["requested_class"] == "actionable"
    assert "summary" in st.message


def test_basis_policy_code(store: SQLiteStore) -> None:
    mem = _observe(store, "why:basis", MemoryKind.FACT, {"x": 1}, basis=Basis.INFERENCE)
    promoted_id = _promote_actionable(store, mem.memory_id)
    st = store.explain_memory(promoted_id).rely_state
    assert st.rely_ok is False
    assert st.code == RelyReasonCode.KIND_BASIS_POLICY
    assert st.details["basis"] == "inference"
    assert "actionable" in st.message


def test_hard_premise_unavailable_code(store: SQLiteStore) -> None:
    # A committed dependent whose hard premise is revoked.
    premise = _observe(store, "why:prem", MemoryKind.FACT, {"x": "premise"})
    _commit(store, premise.memory_id, RelianceClass.ADVISORY)

    dependent = store.observe_memory(ObserveMemoryRequest(
        scope="why:prem", kind=MemoryKind.DECISION, basis=Basis.DIRECT_CAPTURE,
        content={"d": "depends"},
        premises=[PremiseRef(
            memory_id=premise.memory_id,
            relation=LinkRelation.DERIVED_FROM,
            strength=LinkStrength.HARD,
        )],
    )).memory
    _commit(store, dependent.memory_id, RelianceClass.ADVISORY)

    store.revoke_memory(RevokeMemoryRequest(
        memory_id=premise.memory_id, reason="premise pulled",
    ))

    st = store.explain_memory(dependent.memory_id).rely_state
    assert st.rely_ok is False
    assert st.code == RelyReasonCode.HARD_PREMISE_UNAVAILABLE
    assert st.details["bad_premises"] == [f"{premise.memory_id}:revoked"]
    assert "revoked" in st.message


# --- additive threading: flat fields still derive from rely_state ------------ #


def test_explain_flat_fields_match_rely_state(store: SQLiteStore) -> None:
    mem = _observe(store, "why:derive", MemoryKind.FACT, {"x": 1})
    resp = store.explain_memory(mem.memory_id)
    assert resp.rely_state is not None
    assert resp.rely_ok == resp.rely_state.rely_ok
    assert resp.rely_reason == resp.rely_state.message


def test_case_items_carry_rely_state_code(store: SQLiteStore) -> None:
    scope = "why:case"
    obs = _observe(store, scope, MemoryKind.FACT, {"x": 1})
    bundle = store.get_case(GetCaseRequest(scope=scope))
    item = {i.memory.memory_id: i for i in bundle.facts}[obs.memory_id]
    assert item.rely_state is not None
    assert item.rely_state.code == RelyReasonCode.STATUS_NOT_COMMITTED
    assert item.rely_reason == item.rely_state.message  # flat derives from structured


# --- forward compatibility: unknown codes round-trip ------------------------- #


def test_unknown_code_round_trips_as_string() -> None:
    """A consumer on an older enum must not choke on a code it doesn't know.

    RelyReasonCode is a StrEnum, so serialized payloads are plain strings; an
    unknown value deserializes as text and a switch falls through cleanly.
    """
    from continuity.api.models import RelyState

    payload = {"rely_ok": False, "code": "some_future_code",
               "message": "m", "details": {}}
    # StrEnum-typed field accepts the raw string form on the wire.
    st = RelyState.model_validate({**payload, "code": RelyReasonCode.EXPIRED})
    assert st.code == RelyReasonCode.EXPIRED
    # and the raw string form of a known code compares equal to the member
    assert RelyReasonCode.EXPIRED == "expired"


# --- CLI: contctl why -------------------------------------------------------- #


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "why.db")


def _run(db_path: str, argv: list[str]) -> tuple[str, int]:
    buf = io.StringIO()
    code = 0
    with patch("sys.stdout", buf):
        try:
            main(["--db", db_path] + argv)
        except SystemExit as exc:
            code = exc.code or 0
    return buf.getvalue(), code


def test_cli_why_refusal_exits_nonzero(db_path: str) -> None:
    _run(db_path, ["init"])
    observed = json.loads(_run(db_path, [
        "observe", "--scope", "why", "--kind", "fact",
        "--basis", "direct_capture", "--content", '{"x": 1}',
    ])[0])
    mem_id = observed["memory_id"]

    # observed, not committed -> REFUSED, exit 1, code shown
    out, code = _run(db_path, ["why", mem_id])
    assert code == 1
    assert "REFUSED" in out
    assert "status_not_committed" in out

    # commit it -> RELY OK, exit 0
    _run(db_path, ["commit", mem_id, "--reliance-class", "advisory"])
    out, code = _run(db_path, ["why", mem_id])
    assert code == 0
    assert "RELY OK" in out
    assert "eligible" in out


def test_cli_why_json_emits_rely_state(db_path: str) -> None:
    _run(db_path, ["init"])
    observed = json.loads(_run(db_path, [
        "observe", "--scope", "why", "--kind", "fact",
        "--basis", "direct_capture", "--content", '{"x": 1}',
    ])[0])
    out, _ = _run(db_path, ["why", observed["memory_id"], "--json"])
    state = json.loads(out)
    assert state["code"] == "status_not_committed"
    assert state["rely_ok"] is False
    assert "status" in state["details"]
