"""contctl — CLI for continuity.

Usage:
    contctl observe --scope SCOPE --kind KIND --basis BASIS --content JSON [options]
    contctl commit MEMORY_ID --reliance-class CLASS [options]
    contctl revoke MEMORY_ID --reason REASON [options]
    contctl get MEMORY_ID [--receipt]
    contctl query [--scope SCOPE] [--kind KIND] [--status STATUS] [options]
    contctl explain MEMORY_ID
    contctl stats
    contctl init
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from continuity.api.models import (
    ActorRef,
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    MemoryStatus,
    ObserveMemoryRequest,
    QueryMemoryRequest,
    RelianceClass,
    RevokeMemoryRequest,
    SourceRef,
    PremiseRef,
)
from continuity.receipts.memory_receipts import format_receipt
from continuity.store.sqlite import (
    InvalidTransitionError,
    MemoryNotFoundError,
    SQLiteStore,
)


DEFAULT_DB_DIR = Path.home() / ".local" / "share" / "continuity"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "continuity.db"


def _get_store(args: argparse.Namespace) -> SQLiteStore:
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path)
    store.initialize()
    return store


def _out(data: Any) -> None:
    """Print JSON to stdout."""
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    print(json.dumps(data, indent=2, default=str))


def _parse_content(raw: str) -> dict[str, Any]:
    """Parse content from CLI arg. Accepts JSON string or key=value pairs."""
    raw = raw.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    # key=value shorthand: "claim=the sky is blue" -> {"claim": "the sky is blue"}
    parts: dict[str, Any] = {}
    for segment in raw.split(","):
        if "=" not in segment:
            raise ValueError(f"content must be JSON or key=value pairs, got: {segment!r}")
        k, v = segment.split("=", 1)
        parts[k.strip()] = v.strip()
    return parts


def _parse_source_ref(raw: str) -> SourceRef:
    """Parse 'kind:ref' or 'kind:ref:note'."""
    parts = raw.split(":", 2)
    if len(parts) < 2:
        raise ValueError(f"source-ref must be kind:ref[:note], got: {raw!r}")
    return SourceRef(
        kind=parts[0].strip(),
        ref=parts[1].strip(),
        note=parts[2].strip() if len(parts) > 2 else None,
    )


def _parse_premise(raw: str) -> PremiseRef:
    """Parse 'mem_xxx' or 'mem_xxx:relation:strength'."""
    parts = raw.split(":", 2)
    memory_id = parts[0].strip()
    relation = parts[1].strip() if len(parts) > 1 else "depends_on"
    strength = parts[2].strip() if len(parts) > 2 else "hard"
    return PremiseRef(
        memory_id=memory_id,
        relation=relation,
        strength=strength,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    store = _get_store(args)
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    print(f"initialized: {db_path}")


def cmd_observe(args: argparse.Namespace) -> None:
    store = _get_store(args)

    content = _parse_content(args.content)
    source_refs = [_parse_source_ref(s) for s in (args.source_ref or [])]
    premises = [_parse_premise(p) for p in (args.premise or [])]

    actor = None
    if args.actor:
        actor = ActorRef(principal_id=args.actor, auth_method="cli")

    req = ObserveMemoryRequest(
        scope=args.scope,
        kind=args.kind,
        basis=args.basis,
        content=content,
        source_refs=source_refs,
        premises=premises,
        confidence=args.confidence,
        actor=actor,
        idempotency_key=args.idempotency_key,
    )

    resp = store.observe_memory(req)

    if args.receipt:
        _out(format_receipt(resp.receipt))
    elif args.quiet:
        print(resp.memory.memory_id)
    else:
        _out({
            "memory_id": resp.memory.memory_id,
            "status": resp.memory.status,
            "receipt_id": resp.receipt.receipt_id,
            "receipt_hash": resp.receipt.hash,
        })


def cmd_commit(args: argparse.Namespace) -> None:
    store = _get_store(args)

    actor = None
    if args.actor:
        actor = ActorRef(principal_id=args.actor, auth_method="cli")

    premises = [_parse_premise(p) for p in (args.premise or [])]

    req = CommitMemoryRequest(
        memory_id=args.memory_id,
        reliance_class=args.reliance_class,
        approved_by=actor,
        note=args.note,
        supersedes=args.supersedes,
        premises=premises,
        idempotency_key=args.idempotency_key,
    )

    resp = store.commit_memory(req)

    if args.receipt:
        _out(format_receipt(resp.receipt))
    elif args.quiet:
        print(resp.memory.memory_id)
    else:
        _out({
            "memory_id": resp.memory.memory_id,
            "status": resp.memory.status,
            "reliance_class": resp.memory.reliance_class,
            "receipt_id": resp.receipt.receipt_id,
            "receipt_hash": resp.receipt.hash,
        })


def cmd_revoke(args: argparse.Namespace) -> None:
    store = _get_store(args)

    actor = None
    if args.actor:
        actor = ActorRef(principal_id=args.actor, auth_method="cli")

    req = RevokeMemoryRequest(
        memory_id=args.memory_id,
        reason=args.reason,
        revoked_by=actor,
        replacement_memory_id=args.replacement,
        idempotency_key=args.idempotency_key,
    )

    resp = store.revoke_memory(req)

    if args.receipt:
        _out(format_receipt(resp.receipt))
    elif args.quiet:
        print(resp.memory.memory_id)
    else:
        _out({
            "memory_id": resp.memory.memory_id,
            "status": resp.memory.status,
            "receipt_id": resp.receipt.receipt_id,
        })


def cmd_get(args: argparse.Namespace) -> None:
    store = _get_store(args)
    memory = store.get_memory(args.memory_id)
    _out(memory)


def cmd_query(args: argparse.Namespace) -> None:
    store = _get_store(args)

    req = QueryMemoryRequest(
        scope=args.scope,
        kind=args.kind,
        status=args.status,
        basis=args.basis,
        reliance_class=args.reliance_class,
        include_expired=args.include_expired,
        limit=args.limit,
        offset=args.offset,
    )

    resp = store.query_memory(req)

    if args.ids_only:
        for item in resp.items:
            print(item.memory_id)
    else:
        _out({
            "total": resp.total,
            "items": [item.model_dump(mode="json") for item in resp.items],
        })


def cmd_explain(args: argparse.Namespace) -> None:
    store = _get_store(args)
    resp = store.explain_memory(args.memory_id)
    _out(resp)


def cmd_stats(args: argparse.Namespace) -> None:
    store = _get_store(args)
    with store._connect() as conn:
        memories = conn.execute("SELECT COUNT(*) AS c FROM memory_objects").fetchone()["c"]
        events = conn.execute("SELECT COUNT(*) AS c FROM memory_events").fetchone()["c"]
        receipts = conn.execute("SELECT COUNT(*) AS c FROM receipts").fetchone()["c"]
        links = conn.execute("SELECT COUNT(*) AS c FROM memory_links").fetchone()["c"]
        imports = conn.execute("SELECT COUNT(*) AS c FROM spool_imports").fetchone()["c"]

        by_status = conn.execute(
            "SELECT status, COUNT(*) AS c FROM memory_objects GROUP BY status ORDER BY status"
        ).fetchall()
        by_kind = conn.execute(
            "SELECT kind, COUNT(*) AS c FROM memory_objects GROUP BY kind ORDER BY kind"
        ).fetchall()
        by_scope = conn.execute(
            "SELECT scope, COUNT(*) AS c FROM memory_objects GROUP BY scope ORDER BY scope"
        ).fetchall()

    _out({
        "memories": memories,
        "events": events,
        "receipts": receipts,
        "links": links,
        "imports": imports,
        "by_status": {r["status"]: r["c"] for r in by_status},
        "by_kind": {r["kind"]: r["c"] for r in by_kind},
        "by_scope": {r["scope"]: r["c"] for r in by_scope},
    })


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contctl",
        description="continuity — governed state persistence",
    )
    parser.add_argument(
        "--db", default=None,
        help=f"path to SQLite database (default: {DEFAULT_DB_PATH})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # init
    sub.add_parser("init", help="initialize the database")

    # observe
    p_obs = sub.add_parser("observe", help="observe a new memory")
    p_obs.add_argument("--scope", required=True)
    p_obs.add_argument("--kind", required=True, choices=[k.value for k in MemoryKind])
    p_obs.add_argument("--basis", required=True, choices=[b.value for b in Basis])
    p_obs.add_argument("--content", required=True, help="JSON or key=value,key=value")
    p_obs.add_argument("--confidence", type=float, default=0.5)
    p_obs.add_argument("--source-ref", action="append", help="kind:ref[:note]")
    p_obs.add_argument("--premise", action="append", help="memory_id[:relation[:strength]]")
    p_obs.add_argument("--actor", help="principal_id for the actor")
    p_obs.add_argument("--idempotency-key", default=None)
    p_obs.add_argument("--receipt", action="store_true", help="output full receipt")
    p_obs.add_argument("-q", "--quiet", action="store_true", help="output only memory_id")

    # commit
    p_cmt = sub.add_parser("commit", help="commit an observed memory")
    p_cmt.add_argument("memory_id")
    p_cmt.add_argument(
        "--reliance-class", default="retrieve_only",
        choices=[r.value for r in RelianceClass],
    )
    p_cmt.add_argument("--note", default=None)
    p_cmt.add_argument("--supersedes", default=None)
    p_cmt.add_argument("--premise", action="append", help="memory_id[:relation[:strength]]")
    p_cmt.add_argument("--actor", help="principal_id for approver")
    p_cmt.add_argument("--idempotency-key", default=None)
    p_cmt.add_argument("--receipt", action="store_true", help="output full receipt")
    p_cmt.add_argument("-q", "--quiet", action="store_true", help="output only memory_id")

    # revoke
    p_rev = sub.add_parser("revoke", help="revoke a memory")
    p_rev.add_argument("memory_id")
    p_rev.add_argument("--reason", required=True)
    p_rev.add_argument("--replacement", default=None, help="replacement memory_id")
    p_rev.add_argument("--actor", help="principal_id for revoker")
    p_rev.add_argument("--idempotency-key", default=None)
    p_rev.add_argument("--receipt", action="store_true", help="output full receipt")
    p_rev.add_argument("-q", "--quiet", action="store_true", help="output only memory_id")

    # get
    p_get = sub.add_parser("get", help="get a memory by ID")
    p_get.add_argument("memory_id")

    # query
    p_qry = sub.add_parser("query", help="query memories")
    p_qry.add_argument("--scope", default=None)
    p_qry.add_argument("--kind", default=None, choices=[k.value for k in MemoryKind])
    p_qry.add_argument("--status", default=None, choices=[s.value for s in MemoryStatus])
    p_qry.add_argument("--basis", default=None, choices=[b.value for b in Basis])
    p_qry.add_argument("--reliance-class", default=None, choices=[r.value for r in RelianceClass])
    p_qry.add_argument("--include-expired", action="store_true")
    p_qry.add_argument("--limit", type=int, default=100)
    p_qry.add_argument("--offset", type=int, default=0)
    p_qry.add_argument("--ids-only", action="store_true", help="output only memory IDs")

    # explain
    p_exp = sub.add_parser("explain", help="explain a memory (lineage, premises, rely_ok)")
    p_exp.add_argument("memory_id")

    # stats
    sub.add_parser("stats", help="show database statistics")

    return parser


COMMANDS = {
    "init": cmd_init,
    "observe": cmd_observe,
    "commit": cmd_commit,
    "revoke": cmd_revoke,
    "get": cmd_get,
    "query": cmd_query,
    "explain": cmd_explain,
    "stats": cmd_stats,
}


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        COMMANDS[args.command](args)
    except MemoryNotFoundError as exc:
        print(f"error: memory not found: {exc}", file=sys.stderr)
        sys.exit(1)
    except InvalidTransitionError as exc:
        print(f"error: invalid transition: {exc}", file=sys.stderr)
        sys.exit(1)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
