"""Test query filtering by scope, kind, status."""

from continuity.api.models import (
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    MemoryStatus,
    ObserveMemoryRequest,
    QueryMemoryRequest,
    RelianceClass,
)
from continuity.store.sqlite import SQLiteStore


def _observe(store: SQLiteStore, scope: str, kind: MemoryKind) -> str:
    resp = store.observe_memory(ObserveMemoryRequest(
        scope=scope,
        kind=kind,
        basis=Basis.DIRECT_CAPTURE,
        content={"test": f"{scope}/{kind}"},
    ))
    return resp.memory.memory_id


def test_query_by_scope(store: SQLiteStore) -> None:
    _observe(store, "project-a", MemoryKind.FACT)
    _observe(store, "project-a", MemoryKind.NOTE)
    _observe(store, "project-b", MemoryKind.FACT)

    resp = store.query_memory(QueryMemoryRequest(scope="project-a"))
    assert resp.total == 2
    assert all(m.scope == "project-a" for m in resp.items)


def test_query_by_kind(store: SQLiteStore) -> None:
    _observe(store, "proj", MemoryKind.FACT)
    _observe(store, "proj", MemoryKind.HYPOTHESIS)
    _observe(store, "proj", MemoryKind.FACT)

    resp = store.query_memory(QueryMemoryRequest(kind=MemoryKind.FACT))
    assert resp.total == 2


def test_query_by_status(store: SQLiteStore) -> None:
    mid = _observe(store, "proj", MemoryKind.DECISION)
    _observe(store, "proj", MemoryKind.NOTE)

    store.commit_memory(CommitMemoryRequest(
        memory_id=mid,
        reliance_class=RelianceClass.ADVISORY,
    ))

    resp = store.query_memory(QueryMemoryRequest(
        status=MemoryStatus.COMMITTED,
    ))
    assert resp.total == 1
    assert resp.items[0].memory_id == mid


def test_query_pagination(store: SQLiteStore) -> None:
    for i in range(5):
        _observe(store, "proj", MemoryKind.NOTE)

    page1 = store.query_memory(QueryMemoryRequest(scope="proj", limit=2, offset=0))
    page2 = store.query_memory(QueryMemoryRequest(scope="proj", limit=2, offset=2))

    assert page1.total == 5
    assert len(page1.items) == 2
    assert len(page2.items) == 2
    assert page1.items[0].memory_id != page2.items[0].memory_id
