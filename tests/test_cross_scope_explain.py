"""Test cross-scope explain: local-only drift surfacing for imported premises.

Per docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md invariant 8 + the plan's
Phase 1.4 amendment: explain walks scope boundaries by reading the local
imported copy, computes pin-vs-current drift, and surfaces state
(committed / revoked / expired) — no network call to source store.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from continuity.api.models import (
    ActorRef,
    Basis,
    CommitMemoryRequest,
    ImportMemoryRequest,
    LinkRelation,
    LinkStrength,
    MemoryKind,
    MemoryStatus,
    ObserveMemoryRequest,
    PremiseRef,
    RelianceClass,
    RepairMemoryRequest,
    RevokeMemoryRequest,
)
from continuity.store.sqlite import SQLiteStore
from continuity.util.hashing import content_hash


def _operator() -> ActorRef:
    return ActorRef(principal_id="operator:test", auth_method="local")


def _setup_imported_doctrine(
    tmp_path: Path,
    *,
    content: dict | None = None,
) -> tuple[SQLiteStore, SQLiteStore, str, str]:
    """Author + commit in src, import into tgt. Return (src, tgt, mem_id, hash)."""
    src = SQLiteStore(tmp_path / "src.db")
    src.initialize(scope_kind="workspace", scope_label="src")
    obs = src.observe_memory(ObserveMemoryRequest(
        scope="global", kind=MemoryKind.LESSON,
        basis=Basis.OPERATOR_ASSERTION,
        content=content or {"lesson": "v1"},
    ))
    src.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))
    src_mem = src.get_memory(obs.memory.memory_id)
    src_metadata = src.get_store_metadata()
    expected_hash = content_hash(src_mem)

    tgt = SQLiteStore(tmp_path / "tgt.db")
    tgt.initialize(scope_kind="workspace", scope_label="tgt")
    tgt.import_memory(ImportMemoryRequest(
        source_store_id=src_metadata["store_id"],
        memory_id=src_mem.memory_id,
        scope=src_mem.scope,
        kind=src_mem.kind,
        basis=src_mem.basis,
        content=src_mem.content,
        reliance_class=src_mem.reliance_class,
        supersedes=src_mem.supersedes,
        status=src_mem.status,
        expected_content_hash=expected_hash,
    ))
    return src, tgt, src_mem.memory_id, expected_hash


def _cite_pinned(
    tgt: SQLiteStore, premise_mem_id: str, pinned_hash: str | None,
) -> str:
    """Local decision citing the imported memory; return citing memory_id."""
    obs = tgt.observe_memory(ObserveMemoryRequest(
        scope="case:citing", kind=MemoryKind.DECISION,
        basis=Basis.OPERATOR_ASSERTION,
        content={"decision": "x"},
        premises=[PremiseRef(
            memory_id=premise_mem_id,
            relation=LinkRelation.DEPENDS_ON,
            strength=LinkStrength.HARD,
            pinned_content_hash=pinned_hash,
        )],
    ))
    return obs.memory.memory_id


# -- happy path: pin matches current ---------------------------------------


def test_imported_premise_content_match(tmp_path: Path) -> None:
    _src, tgt, mem_id, h = _setup_imported_doctrine(tmp_path)
    citing = _cite_pinned(tgt, mem_id, h)

    explain = tgt.explain_memory(citing)
    assert len(explain.imported_premises) == 1
    ip = explain.imported_premises[0]
    assert ip.src_memory_id == mem_id
    assert ip.content_status == "match"
    assert ip.state == "committed"
    assert ip.pinned_content_hash == h
    assert ip.current_content_hash == h
    assert ip.source_store_id is not None  # passthrough from import receipt


# -- content drift: local copy was repaired or otherwise changed -----------


def test_imported_premise_content_drift_after_local_repair(tmp_path: Path) -> None:
    """If the local imported copy changes (via repair), pin no longer matches."""
    _src, tgt, mem_id, h_at_pin = _setup_imported_doctrine(tmp_path)
    citing = _cite_pinned(tgt, mem_id, h_at_pin)

    # Repair the local imported copy to change the content.
    tgt.repair_memory(RepairMemoryRequest(
        memory_id=mem_id,
        reason="local re-author of imported doctrine",
        patch={"content": {"lesson": "v1+local-edits"}},
        actor=_operator(),
    ))

    explain = tgt.explain_memory(citing)
    ip = explain.imported_premises[0]
    assert ip.content_status == "drift"
    assert ip.pinned_content_hash == h_at_pin
    assert ip.current_content_hash != h_at_pin


# -- state drift: revoked / expired ---------------------------------------


def test_imported_premise_state_revoked(tmp_path: Path) -> None:
    """Content hash unchanged, but local copy revoked -> state='revoked'."""
    _src, tgt, mem_id, h = _setup_imported_doctrine(tmp_path)
    citing = _cite_pinned(tgt, mem_id, h)

    tgt.revoke_memory(RevokeMemoryRequest(
        memory_id=mem_id, reason="superseded", revoked_by=_operator(),
    ))

    explain = tgt.explain_memory(citing)
    ip = explain.imported_premises[0]
    # content_hash doesn't include status, so it still matches
    assert ip.content_status == "match"
    assert ip.state == "revoked"


def test_imported_premise_state_expired_at_evaluation_time(tmp_path: Path) -> None:
    """Expiration is computed against the explicit evaluation_time."""
    # Source/import a memory with expires_at set.
    src = SQLiteStore(tmp_path / "src.db")
    src.initialize(scope_kind="workspace", scope_label="src")
    expires = datetime(2026, 6, 1, tzinfo=timezone.utc)
    obs = src.observe_memory(ObserveMemoryRequest(
        scope="global", kind=MemoryKind.CONSTRAINT,
        basis=Basis.OPERATOR_ASSERTION,
        content={"rule": "valid through June"},
        expires_at=expires,
    ))
    src.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
        expires_at=expires,
    ))
    src_mem = src.get_memory(obs.memory.memory_id)
    src_meta = src.get_store_metadata()
    h = content_hash(src_mem)

    tgt = SQLiteStore(tmp_path / "tgt.db")
    tgt.initialize(scope_kind="workspace", scope_label="tgt")
    tgt.import_memory(ImportMemoryRequest(
        source_store_id=src_meta["store_id"],
        memory_id=src_mem.memory_id,
        scope=src_mem.scope, kind=src_mem.kind, basis=src_mem.basis,
        content=src_mem.content, reliance_class=src_mem.reliance_class,
        supersedes=src_mem.supersedes, status=src_mem.status,
        expires_at=src_mem.expires_at,
        expected_content_hash=h,
    ))
    citing = _cite_pinned(tgt, src_mem.memory_id, h)

    # Past evaluation: not yet expired
    past = expires - timedelta(days=30)
    e_past = tgt.explain_memory(citing, evaluation_time=past)
    assert e_past.imported_premises[0].state == "committed"

    # Future evaluation: expired
    future = expires + timedelta(days=1)
    e_future = tgt.explain_memory(citing, evaluation_time=future)
    assert e_future.imported_premises[0].state == "expired"


# -- unpinned premises and non-imported premises --------------------------


def test_imported_premise_unpinned_still_surfaces(tmp_path: Path) -> None:
    """An unpinned premise on an imported memory is reported with content_status='unpinned'."""
    _src, tgt, mem_id, h = _setup_imported_doctrine(tmp_path)
    citing = _cite_pinned(tgt, mem_id, None)

    explain = tgt.explain_memory(citing)
    assert len(explain.imported_premises) == 1
    ip = explain.imported_premises[0]
    assert ip.content_status == "unpinned"
    assert ip.pinned_content_hash is None
    assert ip.current_content_hash == h


def test_local_premise_omitted_from_imported_premises(tmp_path: Path) -> None:
    """Premises on locally-authored (non-imported) memories are not in imported_premises."""
    store = SQLiteStore(tmp_path / "local.db")
    store.initialize(scope_kind="workspace", scope_label="local")

    a = store.observe_memory(ObserveMemoryRequest(
        scope="local-case", kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE, content={"fact": "x"},
    ))
    b = store.observe_memory(ObserveMemoryRequest(
        scope="local-case", kind=MemoryKind.DECISION,
        basis=Basis.OPERATOR_ASSERTION, content={"decision": "y"},
        premises=[PremiseRef(memory_id=a.memory.memory_id)],
    ))
    explain = store.explain_memory(b.memory.memory_id)
    assert explain.imported_premises == []  # nothing imported here


def test_imported_premises_empty_when_no_premises(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "empty.db")
    store.initialize(scope_kind="workspace", scope_label="empty")
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="case:lonely", kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE, content={"fact": "no premises"},
    ))
    explain = store.explain_memory(obs.memory.memory_id)
    assert explain.imported_premises == []
