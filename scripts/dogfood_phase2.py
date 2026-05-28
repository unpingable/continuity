"""Dogfood the cross-component-reliance substrate end-to-end.

Implements the Phase 1.5 + Phase 2.2 proving ground described in
docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md and
docs/gaps/CROSS_COMPONENT_RELIANCE_GAP.md.

The script:
  1. Authors the doctrine memory (operator-drafted lesson) in a source
     workspace store.
  2. Imports it into a target workspace store with content-hash pinning.
  3. Authors a "second-order observation" in the target store citing the
     imported doctrine via a pinned premise.
  4. Runs explain on the citing memory to demonstrate drift detection
     surfaces cleanly when the source is later mutated.

Usage:
    # Ephemeral demo against temp dirs:
    python -m scripts.dogfood_phase2

    # Against real workspace stores:
    python -m scripts.dogfood_phase2 \\
        --source-db ~/.config/continuity/workspaces/observatory-family/db.sqlite \\
        --target-db /some/project/.continuity/db.sqlite \\
        --actor operator:jbeck

The doctrine memory itself is operator_assertion-basis; if you want it to
appear under your own actor, pass --actor. Default is
'operator:dogfood-demo' so an accidental run is obvious in the audit
trail.

For-real workspace commits should be done deliberately by the operator,
not by a Claude session — this script makes that easy, but the decision
of whether/when to point it at production stores is yours.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

# Repo-local imports (run via `python -m scripts.dogfood_phase2`).
from continuity.api.models import (
    ActorRef,
    Basis,
    CommitMemoryRequest,
    ImportMemoryRequest,
    LinkRelation,
    LinkStrength,
    MemoryKind,
    ObserveMemoryRequest,
    PremiseRef,
    RelianceClass,
    RepairMemoryRequest,
)
from continuity.store.sqlite import SQLiteStore
from continuity.util.hashing import content_hash


DOCTRINE_CONTENT = {
    "title": "Remote auth/standing is cross-constellation, not NQ-local",
    "lesson": (
        "Standing gates speaker/request standing. "
        "Continuity preserves relied-on state — advisory closeouts, "
        "revocations, deployment exceptions. "
        "Remote mutation surfaces require explicit auth/standing before "
        "exposure. "
        "Local/homelab plaintext read-only exposure is an exception, "
        "not doctrine."
    ),
    "keepers": [
        "Continuity records what may be relied on; it does not decide who may speak.",
        "Continuity can distribute reliance records. It should not distribute the rely path.",
        "Cross-host reliance cannot be stronger than local reliance replay.",
    ],
    "gap_ref": "docs/gaps/CROSS_COMPONENT_RELIANCE_GAP.md",
}


def _step(label: str) -> None:
    print(f"\n=== {label} ===")


def _author_doctrine(
    store: SQLiteStore,
    actor: ActorRef,
    *,
    allow_island: bool = False,
) -> str:
    """Observe + commit the doctrine lesson at workspace scope."""
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="workspace",
        kind=MemoryKind.LESSON,
        basis=Basis.OPERATOR_ASSERTION,
        content=DOCTRINE_CONTENT,
        confidence=0.95,
        actor=actor,
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=actor,
        note="constellation-wide cross-component reliance doctrine",
    ))
    return obs.memory.memory_id


def _import_doctrine(
    target: SQLiteStore,
    source: SQLiteStore,
    memory_id: str,
    actor: ActorRef,
) -> str:
    src_mem = source.get_memory(memory_id)
    src_meta = source.get_store_metadata()
    expected_hash = content_hash(src_mem)
    resp = target.import_memory(ImportMemoryRequest(
        source_store_id=src_meta["store_id"] if src_meta else "unknown-source",
        source_ref=str(source.db_path),
        memory_id=src_mem.memory_id,
        scope=src_mem.scope,
        kind=src_mem.kind,
        basis=src_mem.basis,
        content=src_mem.content,
        reliance_class=src_mem.reliance_class,
        supersedes=src_mem.supersedes,
        confidence=src_mem.confidence,
        status=src_mem.status,
        expected_content_hash=expected_hash,
        actor=actor,
    ))
    return expected_hash if not resp.already_imported else expected_hash


def _cite_doctrine_with_pin(
    store: SQLiteStore,
    doctrine_mem_id: str,
    pinned_hash: str,
    actor: ActorRef,
) -> str:
    """Author a second-order observation citing the imported doctrine."""
    obs = store.observe_memory(ObserveMemoryRequest(
        scope="case:dogfood-cross-component-reliance",
        kind=MemoryKind.DECISION,
        basis=Basis.OPERATOR_ASSERTION,
        content={
            "decision": (
                "this project adopts the cross-component reliance "
                "convention: receipts cite continuity memory_id + "
                "content_hash, rely is local against pinned imports"
            ),
            "follows": DOCTRINE_CONTENT["gap_ref"],
        },
        confidence=0.9,
        actor=actor,
        premises=[PremiseRef(
            memory_id=doctrine_mem_id,
            relation=LinkRelation.DEPENDS_ON,
            strength=LinkStrength.HARD,
            pinned_content_hash=pinned_hash,
            note="pinned at citation time",
        )],
    ))
    store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
        approved_by=actor,
    ))
    return obs.memory.memory_id


def _format_explain(
    store: SQLiteStore, citing_mem_id: str,
) -> dict:
    explain = store.explain_memory(citing_mem_id)
    return {
        "memory_id": explain.memory.memory_id,
        "rely_ok": explain.rely_ok,
        "rely_reason": explain.rely_reason,
        "imported_premises": [
            {
                "src_memory_id": ip.src_memory_id,
                "pinned_content_hash": ip.pinned_content_hash[:24] + "..." if ip.pinned_content_hash else None,
                "current_content_hash": ip.current_content_hash[:24] + "...",
                "content_status": ip.content_status,
                "state": ip.state,
                "source_store_id": ip.source_store_id,
            }
            for ip in explain.imported_premises
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dogfood the cross-component-reliance proving ground."
        ),
    )
    parser.add_argument("--source-db", default=None,
                        help="path to source workspace DB (default: temp)")
    parser.add_argument("--target-db", default=None,
                        help="path to target workspace DB (default: temp)")
    parser.add_argument("--actor", default="operator:dogfood-demo",
                        help="principal_id for actor on all writes")
    parser.add_argument("--demo-drift", action="store_true",
                        help="repair the source memory after citation to "
                             "demonstrate explain surfaces content drift")
    parser.add_argument("--keep-temp", action="store_true",
                        help="don't clean up temp DBs after running")
    args = parser.parse_args(argv)

    actor = ActorRef(principal_id=args.actor, auth_method="cli")

    if args.source_db and args.target_db:
        source_path = Path(args.source_db).expanduser().resolve()
        target_path = Path(args.target_db).expanduser().resolve()
        tmpdir_ctx = None
    else:
        tmpdir_ctx = tempfile.TemporaryDirectory(prefix="continuity-dogfood-")
        tmpdir = Path(tmpdir_ctx.__enter__())
        source_path = tmpdir / "source.db"
        target_path = tmpdir / "target.db"

    try:
        _step("set up source workspace store")
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source = SQLiteStore(source_path)
        source.initialize(scope_kind="workspace", scope_label="dogfood-source")
        print(f"  source: {source_path}")

        _step("author doctrine memory in source")
        doctrine_id = _author_doctrine(source, actor)
        src_mem = source.get_memory(doctrine_id)
        src_hash = content_hash(src_mem)
        print(f"  memory_id:    {doctrine_id}")
        print(f"  content_hash: {src_hash}")

        _step("set up target workspace store")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target = SQLiteStore(target_path)
        target.initialize(scope_kind="workspace", scope_label="dogfood-target")
        print(f"  target: {target_path}")

        _step("import doctrine memory into target with content-hash verification")
        pinned_hash = _import_doctrine(target, source, doctrine_id, actor)
        print(f"  imported at: {pinned_hash}")

        _step("cite imported doctrine from a local decision (pinned premise)")
        citing_id = _cite_doctrine_with_pin(target, doctrine_id, pinned_hash, actor)
        print(f"  citing memory_id: {citing_id}")

        _step("explain the citing memory — pin should match, state committed")
        result = _format_explain(target, citing_id)
        print(json.dumps(result, indent=2))
        assert result["rely_ok"] is True, "citing memory should rely_ok"
        ip = result["imported_premises"][0]
        assert ip["content_status"] == "match", f"expected match, got {ip['content_status']}"
        assert ip["state"] == "committed"

        if args.demo_drift:
            _step("repair the source memory to demonstrate drift detection")
            # Repair only the local imported copy (in the target store) —
            # this simulates upstream content changing and the local mirror
            # being repaired to follow.
            target.repair_memory(RepairMemoryRequest(
                memory_id=doctrine_id,
                reason="simulate upstream content change",
                patch={"content": {**DOCTRINE_CONTENT, "rev": "drift-demo"}},
                actor=actor,
            ))
            result_after = _format_explain(target, citing_id)
            print(json.dumps(result_after, indent=2))
            ip_after = result_after["imported_premises"][0]
            assert ip_after["content_status"] == "drift", (
                f"expected drift, got {ip_after['content_status']}"
            )

        print("\nOK")
        return 0
    finally:
        if tmpdir_ctx is not None and not args.keep_temp:
            tmpdir_ctx.__exit__(None, None, None)
        elif tmpdir_ctx is not None:
            print(f"\n(keeping temp dir: {tmpdir_ctx.name})")


if __name__ == "__main__":
    sys.exit(main())
