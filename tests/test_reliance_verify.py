"""Test the cross-component reliance verification surface.

Per docs/gaps/CROSS_COMPONENT_RELIANCE_GAP.md: consumer-tool receipts
carry a `relied_on` array of citations against continuity memory.
`verify_reliance` walks each entry against the local store and labels
status by name. Local-only — no source-store network calls.

Terminal statuses tested:
    match / content_drift / revoked_after / expired_after / missing /
    mode_mismatch
"""

from datetime import datetime, timedelta, timezone
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
    ReliedOnEntry,
    RepairMemoryRequest,
    RevokeMemoryRequest,
    VerifyRelianceRequest,
)
from continuity.store.sqlite import SQLiteStore
from continuity.util.hashing import content_hash


def _operator() -> ActorRef:
    return ActorRef(principal_id="operator:test", auth_method="local")


def _committed_local(
    store: SQLiteStore,
    *,
    scope: str = "case:test",
    expires_at: datetime | None = None,
) -> str:
    obs = store.observe_memory(ObserveMemoryRequest(
        scope=scope,
        kind=MemoryKind.FACT,
        basis=Basis.DIRECT_CAPTURE,
        content={"fact": "x"},
        expires_at=expires_at,
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
        expires_at=expires_at,
    ))
    return obs.memory.memory_id


def _imported_into(
    target: SQLiteStore, tmp_path: Path,
) -> tuple[str, str, str]:
    """Author + commit in source, import into target. (mem_id, hash, store_id)."""
    src = SQLiteStore(tmp_path / "src.db")
    src.initialize(scope_kind="workspace", scope_label="src")
    obs = src.observe_memory(ObserveMemoryRequest(
        scope="global", kind=MemoryKind.LESSON,
        basis=Basis.OPERATOR_ASSERTION,
        content={"lesson": "imported"},
    ))
    src.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=_operator(),
    ))
    src_mem = src.get_memory(obs.memory.memory_id)
    src_meta = src.get_store_metadata()
    src_hash = content_hash(src_mem)
    target.import_memory(ImportMemoryRequest(
        source_store_id=src_meta["store_id"],
        memory_id=src_mem.memory_id,
        scope=src_mem.scope,
        kind=src_mem.kind,
        basis=src_mem.basis,
        content=src_mem.content,
        reliance_class=src_mem.reliance_class,
        supersedes=src_mem.supersedes,
        status=src_mem.status,
        expected_content_hash=src_hash,
    ))
    return src_mem.memory_id, src_hash, src_meta["store_id"]


# -- terminal statuses ----------------------------------------------------


def test_match(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.db")
    store.initialize(scope_kind="workspace", scope_label="s")
    mem_id = _committed_local(store)
    h = content_hash(store.get_memory(mem_id))

    resp = store.verify_reliance(VerifyRelianceRequest(entries=[
        ReliedOnEntry(
            memory_id=mem_id, content_hash=h,
            evaluation_time=datetime.now(timezone.utc),
        ),
    ]))
    assert resp.verified is True
    assert resp.entries[0].status == "match"
    assert resp.summary == {"match": 1}


def test_content_drift(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.db")
    store.initialize(scope_kind="workspace", scope_label="s")
    mem_id = _committed_local(store)
    old_hash = content_hash(store.get_memory(mem_id))

    # Repair to change content -> current hash differs from old hash.
    store.repair_memory(RepairMemoryRequest(
        memory_id=mem_id, reason="content fix",
        patch={"content": {"fact": "rewritten"}},
        actor=_operator(),
    ))

    resp = store.verify_reliance(VerifyRelianceRequest(entries=[
        ReliedOnEntry(
            memory_id=mem_id, content_hash=old_hash,
            evaluation_time=datetime.now(timezone.utc),
        ),
    ]))
    assert resp.verified is False
    assert resp.entries[0].status == "content_drift"
    assert resp.entries[0].current_content_hash != old_hash


def test_revoked_after(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.db")
    store.initialize(scope_kind="workspace", scope_label="s")
    mem_id = _committed_local(store)
    h = content_hash(store.get_memory(mem_id))
    store.revoke_memory(RevokeMemoryRequest(
        memory_id=mem_id, reason="superseded", revoked_by=_operator(),
    ))

    resp = store.verify_reliance(VerifyRelianceRequest(entries=[
        ReliedOnEntry(
            memory_id=mem_id, content_hash=h,
            evaluation_time=datetime.now(timezone.utc),
        ),
    ]))
    assert resp.entries[0].status == "revoked_after"
    assert resp.verified is False


def test_expired_after(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.db")
    store.initialize(scope_kind="workspace", scope_label="s")
    expires = datetime(2026, 6, 1, tzinfo=timezone.utc)
    mem_id = _committed_local(store, expires_at=expires)
    h = content_hash(store.get_memory(mem_id))

    # evaluation_time past the expiry
    eval_time = expires + timedelta(days=1)
    resp = store.verify_reliance(VerifyRelianceRequest(entries=[
        ReliedOnEntry(
            memory_id=mem_id, content_hash=h, evaluation_time=eval_time,
        ),
    ]))
    assert resp.entries[0].status == "expired_after"
    assert resp.verified is False


def test_expired_not_yet_at_past_evaluation_time(tmp_path: Path) -> None:
    """Citation against a past evaluation_time before expiry still matches."""
    store = SQLiteStore(tmp_path / "s.db")
    store.initialize(scope_kind="workspace", scope_label="s")
    expires = datetime(2026, 6, 1, tzinfo=timezone.utc)
    mem_id = _committed_local(store, expires_at=expires)
    h = content_hash(store.get_memory(mem_id))

    # evaluation_time well before expiry — historical replay
    eval_time = expires - timedelta(days=30)
    resp = store.verify_reliance(VerifyRelianceRequest(entries=[
        ReliedOnEntry(
            memory_id=mem_id, content_hash=h, evaluation_time=eval_time,
        ),
    ]))
    assert resp.entries[0].status == "match"
    assert resp.verified is True


def test_missing(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.db")
    store.initialize(scope_kind="workspace", scope_label="s")
    resp = store.verify_reliance(VerifyRelianceRequest(entries=[
        ReliedOnEntry(
            memory_id="mem_doesnotexist_aaaaaaaaaaaaa",
            content_hash="sha256:" + "0" * 64,
            evaluation_time=datetime.now(timezone.utc),
        ),
    ]))
    assert resp.entries[0].status == "missing"
    assert resp.verified is False


def test_mode_mismatch_when_no_import_event(tmp_path: Path) -> None:
    """Receipt claims local_import but the memory was authored locally."""
    store = SQLiteStore(tmp_path / "s.db")
    store.initialize(scope_kind="workspace", scope_label="s")
    mem_id = _committed_local(store)
    h = content_hash(store.get_memory(mem_id))

    resp = store.verify_reliance(VerifyRelianceRequest(entries=[
        ReliedOnEntry(
            memory_id=mem_id, content_hash=h,
            evaluation_time=datetime.now(timezone.utc),
            verification_mode="local_import",
        ),
    ]))
    assert resp.entries[0].status == "mode_mismatch"
    assert resp.verified is False


def test_mode_local_import_with_actual_import(tmp_path: Path) -> None:
    """If the memory actually was imported, local_import claim verifies."""
    tgt = SQLiteStore(tmp_path / "tgt.db")
    tgt.initialize(scope_kind="workspace", scope_label="tgt")
    mem_id, h, _ = _imported_into(tgt, tmp_path)

    resp = tgt.verify_reliance(VerifyRelianceRequest(entries=[
        ReliedOnEntry(
            memory_id=mem_id, content_hash=h,
            evaluation_time=datetime.now(timezone.utc),
            verification_mode="local_import",
        ),
    ]))
    assert resp.entries[0].status == "match"


# -- aggregate behavior ---------------------------------------------------


def test_aggregate_verified_only_when_all_match(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "s.db")
    store.initialize(scope_kind="workspace", scope_label="s")
    a_id = _committed_local(store, scope="case:a")
    b_id = _committed_local(store, scope="case:b")
    a_hash = content_hash(store.get_memory(a_id))
    b_hash = content_hash(store.get_memory(b_id))
    now = datetime.now(timezone.utc)

    # Revoke one to mix statuses
    store.revoke_memory(RevokeMemoryRequest(
        memory_id=b_id, reason="x", revoked_by=_operator(),
    ))

    resp = store.verify_reliance(VerifyRelianceRequest(entries=[
        ReliedOnEntry(memory_id=a_id, content_hash=a_hash, evaluation_time=now),
        ReliedOnEntry(memory_id=b_id, content_hash=b_hash, evaluation_time=now),
    ]))
    statuses = [e.status for e in resp.entries]
    assert statuses == ["match", "revoked_after"]
    assert resp.verified is False
    assert resp.summary == {"match": 1, "revoked_after": 1}


def test_empty_entries_yields_unverified(tmp_path: Path) -> None:
    """An empty relied_on array does not count as verified."""
    store = SQLiteStore(tmp_path / "s.db")
    store.initialize(scope_kind="workspace", scope_label="s")
    resp = store.verify_reliance(VerifyRelianceRequest(entries=[]))
    assert resp.verified is False
    assert resp.summary == {}


# -- CLI surface ----------------------------------------------------------


def test_cli_verify_match(tmp_path: Path, capsys) -> None:
    """`contctl reliance verify` exits 0 on all-match."""
    import json
    from continuity.cli import main as cli_main

    db = tmp_path / "store.db"
    cli_main(["--db", str(db), "init"])
    capsys.readouterr()

    # Observe + commit
    obs_argv = [
        "--db", str(db), "observe",
        "--scope", "case:cli-verify", "--kind", "fact",
        "--basis", "direct_capture",
        "--content", '{"fact":"x"}', "-q",
    ]
    cli_main(obs_argv)
    mem_id = capsys.readouterr().out.strip()

    cli_main([
        "--db", str(db), "commit", mem_id,
        "--reliance-class", "advisory", "--actor", "operator:test", "-q",
    ])
    capsys.readouterr()

    # Compute hash directly
    store = SQLiteStore(db)
    store.initialize()
    h = content_hash(store.get_memory(mem_id))

    # Build the receipt JSON
    receipt = {
        "relied_on": [
            {
                "memory_id": mem_id,
                "content_hash": h,
                "evaluation_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))

    # Success path: cmd_reliance_verify prints the response and returns
    # without calling sys.exit. main() also returns normally on success.
    cli_main(["--db", str(db), "reliance", "verify", str(receipt_path)])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["verified"] is True
    assert parsed["entries"][0]["status"] == "match"


def test_cli_verify_drift_exits_2(tmp_path: Path, capsys) -> None:
    """Verification failure causes exit code 2."""
    import json
    from continuity.cli import main as cli_main

    db = tmp_path / "store.db"
    cli_main(["--db", str(db), "init"])
    capsys.readouterr()

    receipt = {
        "relied_on": [
            {
                "memory_id": "mem_doesnotexist_aaaaaaaaaaaaa",
                "content_hash": "sha256:" + "0" * 64,
                "evaluation_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    receipt_path = tmp_path / "bad_receipt.json"
    receipt_path.write_text(json.dumps(receipt))

    with pytest.raises(SystemExit) as excinfo:
        cli_main(["--db", str(db), "reliance", "verify", str(receipt_path)])
    assert excinfo.value.code == 2
