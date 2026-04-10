"""Tests for the supersede convention: latest_memory + supersedes pointer.

This is the read+write side of the "what is the current project_state"
problem. project_state and next_action have singleton-current semantics:
later observations replace earlier ones, but the lineage stays auditable
through the supersedes pointer. Both old and new remain committed.
"""

from __future__ import annotations

import pytest

from continuity.api.models import (
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    MemoryStatus,
    ObserveMemoryRequest,
    RelianceClass,
)
from continuity.store.sqlite import SQLiteStore


def _observe(
    store: SQLiteStore,
    scope: str,
    kind: MemoryKind,
    content: dict | None = None,
    *,
    supersedes: str | None = None,
) -> str:
    resp = store.observe_memory(ObserveMemoryRequest(
        scope=scope,
        kind=kind,
        basis=Basis.DIRECT_CAPTURE,
        content=content or {"text": "x"},
        supersedes=supersedes,
    ))
    return resp.memory.memory_id


def _commit(store: SQLiteStore, memory_id: str) -> None:
    store.commit_memory(CommitMemoryRequest(
        memory_id=memory_id,
        reliance_class=RelianceClass.RETRIEVE_ONLY,
    ))


def test_observe_accepts_supersedes(store: SQLiteStore) -> None:
    first = _observe(store, "driftwatch", MemoryKind.PROJECT_STATE, {"phase": "v1"})
    _commit(store, first)

    second = _observe(
        store, "driftwatch", MemoryKind.PROJECT_STATE, {"phase": "v2"},
        supersedes=first,
    )
    mem = store.get_memory(second)
    assert mem.supersedes == first


def test_supersedes_does_not_revoke_prior(store: SQLiteStore) -> None:
    """The prior memory stays committed; supersede is a pointer, not a revoke."""
    first = _observe(store, "drift", MemoryKind.PROJECT_STATE, {"phase": "a"})
    _commit(store, first)

    second = _observe(
        store, "drift", MemoryKind.PROJECT_STATE, {"phase": "b"},
        supersedes=first,
    )
    _commit(store, second)

    prior = store.get_memory(first)
    new = store.get_memory(second)
    assert prior.status == MemoryStatus.COMMITTED  # not auto-revoked
    assert new.status == MemoryStatus.COMMITTED
    assert new.supersedes == first


def test_latest_memory_returns_most_recent_committed(store: SQLiteStore) -> None:
    first = _observe(store, "drift", MemoryKind.PROJECT_STATE, {"phase": "1"})
    _commit(store, first)
    second = _observe(store, "drift", MemoryKind.PROJECT_STATE, {"phase": "2"})
    _commit(store, second)
    third = _observe(store, "drift", MemoryKind.PROJECT_STATE, {"phase": "3"})
    _commit(store, third)

    latest = store.latest_memory("drift", MemoryKind.PROJECT_STATE)
    assert latest is not None
    assert latest.memory_id == third


def test_latest_memory_returns_none_when_empty(store: SQLiteStore) -> None:
    latest = store.latest_memory("nothing-here", MemoryKind.PROJECT_STATE)
    assert latest is None


def test_latest_memory_filters_by_status(store: SQLiteStore) -> None:
    """Default status=committed; observed memories don't count."""
    obs_only = _observe(store, "drift", MemoryKind.PROJECT_STATE, {"phase": "draft"})

    # No committed yet
    latest = store.latest_memory("drift", MemoryKind.PROJECT_STATE)
    assert latest is None

    # Now commit one
    committed = _observe(store, "drift", MemoryKind.PROJECT_STATE, {"phase": "live"})
    _commit(store, committed)

    latest = store.latest_memory("drift", MemoryKind.PROJECT_STATE)
    assert latest is not None
    assert latest.memory_id == committed

    # status=None considers any
    latest_any = store.latest_memory(
        "drift", MemoryKind.PROJECT_STATE, status=None,
    )
    assert latest_any is not None
    # The most recently updated of any status — committed updates row, so it wins
    assert latest_any.memory_id == committed
    _ = obs_only


def test_latest_memory_kind_isolated(store: SQLiteStore) -> None:
    p_id = _observe(store, "s", MemoryKind.PROJECT_STATE, {"phase": "a"})
    _commit(store, p_id)
    n_id = _observe(store, "s", MemoryKind.NEXT_ACTION, {
        "project": "s", "action": "b",
    })
    _commit(store, n_id)

    latest_p = store.latest_memory("s", MemoryKind.PROJECT_STATE)
    latest_n = store.latest_memory("s", MemoryKind.NEXT_ACTION)
    assert latest_p is not None and latest_p.memory_id == p_id
    assert latest_n is not None and latest_n.memory_id == n_id


def test_supersede_chain_walkable(store: SQLiteStore) -> None:
    """Following supersedes pointers should reconstruct the lineage."""
    a = _observe(store, "drift", MemoryKind.PROJECT_STATE, {"v": 1})
    _commit(store, a)
    b = _observe(store, "drift", MemoryKind.PROJECT_STATE, {"v": 2}, supersedes=a)
    _commit(store, b)
    c = _observe(store, "drift", MemoryKind.PROJECT_STATE, {"v": 3}, supersedes=b)
    _commit(store, c)

    # Walk from latest backwards
    chain = []
    cur_id = c
    while cur_id is not None:
        mem = store.get_memory(cur_id)
        chain.append(mem.memory_id)
        cur_id = mem.supersedes

    assert chain == [c, b, a]


def test_observe_supersedes_in_receipt(store: SQLiteStore) -> None:
    """The supersedes pointer is captured in the observe receipt."""
    a = _observe(store, "drift", MemoryKind.PROJECT_STATE, {"v": 1})
    _commit(store, a)

    resp = store.observe_memory(ObserveMemoryRequest(
        scope="drift",
        kind=MemoryKind.PROJECT_STATE,
        basis=Basis.DIRECT_CAPTURE,
        content={"v": 2},
        supersedes=a,
    ))
    assert resp.receipt.content["supersedes"] == a
