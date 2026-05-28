"""Test cross-scope import: pinned-hash federation between local stores.

Per docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md:
  - import_memory verifies content_hash against the supplied payload
  - idempotent at the same (memory_id, content_hash)
  - refuses re-import at a different content_hash (V1; no silent overwrite)
  - emits a memory.imported event + memory.import receipt
  - populates spool_imports as 'applied'

These tests use two SQLite stores side-by-side to simulate cross-DB
federation. No network involved; the federation is by payload + hash.
"""

import sqlite3
from pathlib import Path

import pytest

from continuity.api.models import (
    ActorRef,
    Basis,
    CommitMemoryRequest,
    ImportMemoryRequest,
    MemoryKind,
    ObserveMemoryRequest,
    RelianceClass,
    RevokeMemoryRequest,
)
from continuity.store.sqlite import (
    ContentHashMismatchError,
    SQLiteStore,
)
from continuity.util.hashing import content_hash


def _operator() -> ActorRef:
    return ActorRef(principal_id="operator:test", auth_method="local")


def _build_source(tmp_path: Path) -> tuple[SQLiteStore, str, str, str]:
    """Author a committed global-scope lesson in a workspace store.

    Returns (source_store, memory_id, store_id, content_hash).
    """
    src_path = tmp_path / "source.db"
    src = SQLiteStore(src_path)
    src.initialize(scope_kind="workspace", scope_label="source-workspace")

    obs = src.observe_memory(ObserveMemoryRequest(
        scope="global",
        kind=MemoryKind.LESSON,
        basis=Basis.OPERATOR_ASSERTION,
        content={"lesson": "the constellation thesis", "version": 1},
    ))
    src.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))
    src_mem = src.get_memory(obs.memory.memory_id)
    src_metadata = src.get_store_metadata()
    return src, src_mem.memory_id, src_metadata["store_id"], content_hash(src_mem)


def _import_into(
    target: SQLiteStore,
    src: SQLiteStore,
    memory_id: str,
    source_store_id: str,
    expected_hash: str,
    **overrides,
) -> "ImportMemoryRequest":
    src_mem = src.get_memory(memory_id)
    req_kwargs = dict(
        source_store_id=source_store_id,
        memory_id=src_mem.memory_id,
        scope=src_mem.scope,
        kind=src_mem.kind,
        basis=src_mem.basis,
        content=src_mem.content,
        reliance_class=src_mem.reliance_class,
        supersedes=src_mem.supersedes,
        status=src_mem.status,
        expected_content_hash=expected_hash,
    )
    req_kwargs.update(overrides)
    return ImportMemoryRequest(**req_kwargs)


# -- happy path ------------------------------------------------------------


def test_import_creates_local_row_and_receipt(tmp_path: Path) -> None:
    src, mem_id, store_id, src_hash = _build_source(tmp_path)
    tgt = SQLiteStore(tmp_path / "target.db")
    tgt.initialize(scope_kind="workspace", scope_label="target-workspace")

    resp = tgt.import_memory(_import_into(tgt, src, mem_id, store_id, src_hash))

    assert not resp.already_imported
    assert resp.memory.memory_id == mem_id
    assert resp.memory.scope == "global"
    # Local copy carries basis=import even if source was different
    assert resp.memory.basis == "import"
    assert resp.receipt.receipt_type == "memory.import"
    assert resp.event.event_type == "import"
    # Receipt content carries the audit trail
    assert resp.receipt.content["source_store_id"] == store_id
    assert resp.receipt.content["imported_content_hash"] == src_hash
    # Spool import row recorded
    assert resp.spool_import_id


def test_imported_memory_content_hash_matches_source(tmp_path: Path) -> None:
    src, mem_id, store_id, src_hash = _build_source(tmp_path)
    tgt = SQLiteStore(tmp_path / "target.db")
    tgt.initialize(scope_kind="workspace", scope_label="target")

    tgt.import_memory(_import_into(tgt, src, mem_id, store_id, src_hash))
    tgt_mem = tgt.get_memory(mem_id)
    assert content_hash(tgt_mem) == src_hash


def test_spool_imports_table_marked_applied(tmp_path: Path) -> None:
    src, mem_id, store_id, src_hash = _build_source(tmp_path)
    tgt_path = tmp_path / "target.db"
    tgt = SQLiteStore(tgt_path)
    tgt.initialize(scope_kind="workspace", scope_label="target")

    tgt.import_memory(_import_into(tgt, src, mem_id, store_id, src_hash))

    conn = sqlite3.connect(str(tgt_path))
    try:
        row = conn.execute(
            "SELECT source, external_ref, status, applied_at FROM spool_imports"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == store_id
    assert row[1] == mem_id
    assert row[2] == "applied"
    assert row[3] is not None


# -- idempotency -----------------------------------------------------------


def test_reimport_same_hash_is_idempotent(tmp_path: Path) -> None:
    src, mem_id, store_id, src_hash = _build_source(tmp_path)
    tgt = SQLiteStore(tmp_path / "target.db")
    tgt.initialize(scope_kind="workspace", scope_label="target")

    first = tgt.import_memory(_import_into(tgt, src, mem_id, store_id, src_hash))
    second = tgt.import_memory(_import_into(tgt, src, mem_id, store_id, src_hash))

    assert not first.already_imported
    assert second.already_imported
    # Returns the original receipt/event — no new audit artifacts.
    assert second.receipt.receipt_id == first.receipt.receipt_id
    assert second.event.event_id == first.event.event_id


def test_reimport_via_idempotency_key(tmp_path: Path) -> None:
    src, mem_id, store_id, src_hash = _build_source(tmp_path)
    tgt = SQLiteStore(tmp_path / "target.db")
    tgt.initialize(scope_kind="workspace", scope_label="target")

    a = tgt.import_memory(_import_into(
        tgt, src, mem_id, store_id, src_hash,
        idempotency_key="import-test-1",
    ))
    b = tgt.import_memory(_import_into(
        tgt, src, mem_id, store_id, src_hash,
        idempotency_key="import-test-1",
    ))
    assert b.already_imported
    assert b.receipt.receipt_id == a.receipt.receipt_id


# -- refusals --------------------------------------------------------------


def test_import_refuses_on_bad_expected_hash(tmp_path: Path) -> None:
    src, mem_id, store_id, src_hash = _build_source(tmp_path)
    tgt = SQLiteStore(tmp_path / "target.db")
    tgt.initialize(scope_kind="workspace", scope_label="target")

    with pytest.raises(ContentHashMismatchError) as exc:
        tgt.import_memory(_import_into(
            tgt, src, mem_id, store_id,
            "sha256:" + "0" * 64,
        ))
    assert exc.value.memory_id == mem_id


def test_import_refuses_drifted_reimport(tmp_path: Path) -> None:
    """If the source memory drifts (e.g. content changed), re-import refuses."""
    src, mem_id, store_id, src_hash_v1 = _build_source(tmp_path)
    tgt = SQLiteStore(tmp_path / "target.db")
    tgt.initialize(scope_kind="workspace", scope_label="target")
    tgt.import_memory(_import_into(tgt, src, mem_id, store_id, src_hash_v1))

    # Drift the local mirror: simulate the source having rewritten content.
    # We build a new request with a different content payload + matching
    # new hash. The store will compute the new hash, see the local memory
    # already exists at a different hash, and refuse.
    drifted_content = {"lesson": "the constellation thesis", "version": 2}
    # Build a candidate to get the new hash
    from continuity.api.models import MemoryObject, MemoryStatus
    candidate = MemoryObject(
        memory_id=mem_id,
        scope="global",
        kind=MemoryKind.LESSON,
        basis=Basis.IMPORT,
        status=MemoryStatus.COMMITTED,
        reliance_class=RelianceClass.ADVISORY,
        content=drifted_content,
    )
    drifted_hash = content_hash(candidate)

    with pytest.raises(ContentHashMismatchError) as exc:
        tgt.import_memory(ImportMemoryRequest(
            source_store_id=store_id,
            memory_id=mem_id,
            scope="global",
            kind=MemoryKind.LESSON,
            basis=Basis.IMPORT,
            content=drifted_content,
            reliance_class=RelianceClass.ADVISORY,
            status=MemoryStatus.COMMITTED,
            expected_content_hash=drifted_hash,
        ))
    assert "different content_hash" in exc.value.reason


def test_import_does_not_collide_with_locally_authored_memory(tmp_path: Path) -> None:
    """A forged import that re-labels a locally-authored memory is refused.

    The defense fires either at the expected_content_hash check (the forged
    payload doesn't hash to the expected value) or at the local-collision
    check (existing local row has a different content_hash). Both are
    legitimate refusals; this test asserts the import does not silently
    succeed regardless of which check fires first.
    """
    src, mem_id, store_id, src_hash = _build_source(tmp_path)

    # Target authors a memory at the same memory_id by coincidence.
    tgt = SQLiteStore(tmp_path / "target.db")
    tgt.initialize(scope_kind="workspace", scope_label="target")
    local = tgt.observe_memory(ObserveMemoryRequest(
        scope="global",
        kind=MemoryKind.NOTE,
        basis=Basis.DIRECT_CAPTURE,
        content={"note": "local note"},
    ))
    # Construct the would-be-imported payload using the local memory_id.
    # Compute the correct hash for THIS forged payload so the first check
    # passes. The second check (local-collision) must then catch it.
    from continuity.api.models import MemoryObject, MemoryStatus
    src_mem = src.get_memory(mem_id)
    forged = MemoryObject(
        memory_id=local.memory.memory_id,
        scope=src_mem.scope,
        kind=src_mem.kind,
        basis=Basis.IMPORT,
        status=src_mem.status,
        reliance_class=src_mem.reliance_class,
        content=src_mem.content,
        supersedes=src_mem.supersedes,
    )
    forged_hash = content_hash(forged)

    with pytest.raises(ContentHashMismatchError):
        tgt.import_memory(ImportMemoryRequest(
            source_store_id=store_id,
            memory_id=local.memory.memory_id,
            scope=src_mem.scope,
            kind=src_mem.kind,
            basis=Basis.IMPORT,
            content=src_mem.content,
            reliance_class=src_mem.reliance_class,
            status=src_mem.status,
            expected_content_hash=forged_hash,
        ))
    # Local row is unchanged — the locally-authored note is intact.
    local_after = tgt.get_memory(local.memory.memory_id)
    assert local_after.content == {"note": "local note"}
    assert local_after.basis != "import"


def test_import_refuses_island_topology(tmp_path: Path) -> None:
    """Importing scope=global into a project store refuses without --allow-island."""
    from continuity.store.sqlite import IslandWriteRefusedError

    src, mem_id, store_id, src_hash = _build_source(tmp_path)
    tgt = SQLiteStore(tmp_path / "project-target.db")
    tgt.initialize(scope_kind="project", scope_label="proj")

    with pytest.raises(IslandWriteRefusedError):
        tgt.import_memory(_import_into(tgt, src, mem_id, store_id, src_hash))


def test_import_allowed_island_with_opt_in(tmp_path: Path) -> None:
    src, mem_id, store_id, src_hash = _build_source(tmp_path)
    tgt = SQLiteStore(tmp_path / "project-target.db", allow_island=True)
    tgt.initialize(scope_kind="project", scope_label="proj")

    resp = tgt.import_memory(_import_into(tgt, src, mem_id, store_id, src_hash))
    assert resp.memory.scope == "global"


# -- receipt chain integrity ----------------------------------------------


def test_import_receipt_chains_to_prior(tmp_path: Path) -> None:
    src, mem_id, store_id, src_hash = _build_source(tmp_path)
    tgt = SQLiteStore(tmp_path / "target.db")
    tgt.initialize(scope_kind="workspace", scope_label="target")

    # Pre-seed a local memory so there's a prior receipt to chain off.
    local = tgt.observe_memory(ObserveMemoryRequest(
        scope="case:bootstrap", kind=MemoryKind.NOTE,
        basis=Basis.DIRECT_CAPTURE, content={"note": "x"},
    ))

    resp = tgt.import_memory(_import_into(tgt, src, mem_id, store_id, src_hash))
    assert resp.receipt.prev_hash == local.receipt.hash


def test_revoke_at_source_does_not_taint_local_import_until_resynced(tmp_path: Path) -> None:
    """Revocation in the source doesn't auto-propagate; the local import
    remains committed. This is the pull-at-explain-time model (per gap
    invariant 12). A follow-up refresh would surface the drift."""
    src, mem_id, store_id, src_hash = _build_source(tmp_path)
    tgt = SQLiteStore(tmp_path / "target.db")
    tgt.initialize(scope_kind="workspace", scope_label="target")
    tgt.import_memory(_import_into(tgt, src, mem_id, store_id, src_hash))

    src.revoke_memory(RevokeMemoryRequest(
        memory_id=mem_id, reason="superseded upstream", revoked_by=_operator(),
    ))

    tgt_mem = tgt.get_memory(mem_id)
    assert tgt_mem.status == "committed"  # local copy is still committed
