"""Test the islands-of-continuity defect: cross-project writes against a
project-local DB.

Per docs/gaps/ISLANDS_OF_CONTINUITY.md invariant 3, a scope=global or
scope=workspace* memory in a DB stamped scope_kind='project' is "a local
memory wearing a fake mustache" — refuse without explicit operator opt-in
(allow_island=True / CLI --allow-island).
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
)
from continuity.store.sqlite import (
    IslandWriteRefusedError,
    SQLiteStore,
)


def _operator() -> ActorRef:
    return ActorRef(principal_id="operator:test", auth_method="local")


def _project_store(tmp_path, *, allow_island: bool = False) -> SQLiteStore:
    """A store stamped as project-local — the islands defect target."""
    db = tmp_path / "proj.db"
    store = SQLiteStore(db, allow_island=allow_island)
    store.initialize(scope_kind="project", scope_label="proj-test")
    return store


def _workspace_store(tmp_path) -> SQLiteStore:
    """A store stamped as workspace — cross-project writes are legitimate."""
    db = tmp_path / "ws.db"
    store = SQLiteStore(db)
    store.initialize(scope_kind="workspace", scope_label="ws-test")
    return store


def test_global_scope_against_project_store_refuses(tmp_path) -> None:
    store = _project_store(tmp_path)
    with pytest.raises(IslandWriteRefusedError) as excinfo:
        store.observe_memory(ObserveMemoryRequest(
            scope="global",
            kind=MemoryKind.LESSON,
            basis=Basis.OPERATOR_ASSERTION,
            content={"lesson": "would be an island"},
        ))
    assert excinfo.value.scope == "global"
    assert excinfo.value.store_scope_kind == "project"

    # No row was written
    conn = sqlite3.connect(str(store.db_path))
    try:
        n = conn.execute("SELECT COUNT(*) FROM memory_objects").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_workspace_prefix_scope_against_project_store_refuses(tmp_path) -> None:
    store = _project_store(tmp_path)
    with pytest.raises(IslandWriteRefusedError):
        store.observe_memory(ObserveMemoryRequest(
            scope="workspace:observatory-family",
            kind=MemoryKind.CONSTRAINT,
            basis=Basis.OPERATOR_ASSERTION,
            content={"rule": "x"},
        ))


def test_project_scope_against_project_store_allowed(tmp_path) -> None:
    """Project-local scopes are exactly what a project store is for."""
    store = _project_store(tmp_path)
    resp = store.observe_memory(ObserveMemoryRequest(
        scope="case:debugging-x",
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "perfectly local"},
    ))
    assert resp.memory.scope == "case:debugging-x"


def test_allow_island_overrides_refusal(tmp_path) -> None:
    store = _project_store(tmp_path, allow_island=True)
    resp = store.observe_memory(ObserveMemoryRequest(
        scope="global",
        kind=MemoryKind.LESSON,
        basis=Basis.OPERATOR_ASSERTION,
        content={"lesson": "explicit opt-in"},
    ))
    assert resp.memory.scope == "global"


def test_workspace_store_accepts_global_scope(tmp_path) -> None:
    """A workspace store is the right home for cross-project memories."""
    store = _workspace_store(tmp_path)
    resp = store.observe_memory(ObserveMemoryRequest(
        scope="global",
        kind=MemoryKind.LESSON,
        basis=Basis.OPERATOR_ASSERTION,
        content={"lesson": "legitimately global"},
    ))
    assert resp.memory.scope == "global"


def test_island_refusal_does_not_emit_refusal_receipt(tmp_path) -> None:
    """Island refusal is a topology error caught before policy/receipts.

    Unlike PolicyDeniedError (which emits a memory.refused receipt for
    audit), an island refusal happens before any state mutation runs and
    leaves no receipt — the operator's flag fixes the call, no audit
    artifact needed.
    """
    store = _project_store(tmp_path)
    with pytest.raises(IslandWriteRefusedError):
        store.observe_memory(ObserveMemoryRequest(
            scope="global",
            kind=MemoryKind.FACT,
            basis=Basis.DIRECT_CAPTURE,
            content={"fact": "x"},
        ))
    conn = sqlite3.connect(str(store.db_path))
    try:
        n = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_cli_where_surfaces_warning_for_git_root_fallback(tmp_path, capsys) -> None:
    """`contctl where` emits a topology warning when source is git-root."""
    from continuity.cli import _island_warnings

    warnings = _island_warnings(
        source="git-root",
        resolved_kind="project",
        stored_kind=None,
        db_path=tmp_path / "x.db",
    )
    assert warnings
    assert any("git-root fallback" in w for w in warnings)


def test_cli_where_warnings_empty_for_workspace(tmp_path) -> None:
    from continuity.cli import _island_warnings

    warnings = _island_warnings(
        source="workspace",
        resolved_kind="workspace",
        stored_kind="workspace",
        db_path=tmp_path / "x.db",
    )
    assert warnings == []
