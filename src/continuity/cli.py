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
import os
import sys
from pathlib import Path
from typing import Any

from continuity.api.models import (
    ActorRef,
    Basis,
    CommitMemoryRequest,
    GetCaseRequest,
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
from continuity.util.dbpath import (
    GLOBAL_DB_PATH,
    resolve_db_path,
    source_to_scope_kind,
)
from continuity.workspace import (
    WorkspaceExistsError,
    WorkspaceNotFoundError,
    add_project_to_workspace,
    create_workspace,
    list_workspace_summaries,
    remove_project_from_workspace,
    workspace_info,
)


def _resolve(args: argparse.Namespace) -> tuple[Path, str]:
    explicit = Path(args.db) if args.db else None
    workspace = getattr(args, "workspace", None)
    return resolve_db_path(explicit, workspace=workspace)


def _scope_label(args: argparse.Namespace, source: str) -> str | None:
    """Pick a human label for store metadata based on resolution source."""
    if source == "workspace":
        return getattr(args, "workspace", None) or os.environ.get("CONTINUITY_WORKSPACE")
    return None


def _get_store(args: argparse.Namespace) -> SQLiteStore:
    db_path, source = _resolve(args)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path)
    store.initialize(
        scope_kind=source_to_scope_kind(source),
        scope_label=_scope_label(args, source),
    )
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
    db_path, source = _resolve(args)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path)
    store.initialize(
        scope_kind=source_to_scope_kind(source),
        scope_label=_scope_label(args, source),
    )
    print(f"initialized: {db_path} (source={source})")


def cmd_where(args: argparse.Namespace) -> None:
    """Show the active database path, how it was resolved, and its identity."""
    db_path, source = _resolve(args)
    info: dict[str, Any] = {
        "db_path": str(db_path),
        "source": source,
        "exists": db_path.exists(),
        "scope_kind_resolved": source_to_scope_kind(source),
    }
    if db_path.exists():
        # Initialize is idempotent and will create the store_metadata table
        # (and add scope_kind column) for DBs created before they existed.
        store = SQLiteStore(db_path)
        store.initialize()
        info["metadata"] = store.get_store_metadata()

    if args.json:
        _out(info)
        return

    print(f"db_path:      {info['db_path']}")
    print(f"source:       {info['source']}")
    print(f"scope_kind:   {info['scope_kind_resolved']}")
    print(f"exists:       {info['exists']}")
    if info.get("metadata"):
        m = info["metadata"]
        print(f"store_id:     {m.get('store_id')}")
        print(f"project_hint: {m.get('project_hint')}")
        print(f"stored_kind:  {m.get('scope_kind') or '(none)'}")
        print(f"git_root:     {m.get('git_root') or '(none)'}")
        print(f"created_at:   {m.get('created_at')}")


# ---------------------------------------------------------------------------
# Workspace commands
# ---------------------------------------------------------------------------

def cmd_workspace_create(args: argparse.Namespace) -> None:
    try:
        manifest = create_workspace(
            args.workspace_id,
            label=args.label,
        )
    except WorkspaceExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"created workspace: {manifest['id']}")
    print(f"  manifest: {Path('~/.config/continuity/workspaces') / args.workspace_id / 'manifest.json'}")
    print(f"  db:       {Path('~/.config/continuity/workspaces') / args.workspace_id / 'db.sqlite'}")
    print()
    print("To use it:")
    print(f"  export CONTINUITY_WORKSPACE={manifest['id']}")
    print(f"  contctl --workspace {manifest['id']} init")


def cmd_workspace_list(args: argparse.Namespace) -> None:
    summaries = list_workspace_summaries()
    if args.json:
        _out(summaries)
        return
    if not summaries:
        print("(no workspaces)")
        return
    for s in summaries:
        marker = "*" if s["db_exists"] else " "
        print(f"{marker} {s['id']:30s}  {s['label']}  ({s['project_count']} project(s))")


def cmd_workspace_show(args: argparse.Namespace) -> None:
    try:
        info = workspace_info(args.workspace_id)
    except WorkspaceNotFoundError as exc:
        print(f"error: workspace not found: {exc}", file=sys.stderr)
        sys.exit(1)
    _out(info)


def cmd_workspace_add_project(args: argparse.Namespace) -> None:
    try:
        manifest = add_project_to_workspace(
            args.workspace_id, str(Path(args.project_path).expanduser().resolve()),
        )
    except WorkspaceNotFoundError as exc:
        print(f"error: workspace not found: {exc}", file=sys.stderr)
        sys.exit(1)
    _out(manifest)


def cmd_workspace_remove_project(args: argparse.Namespace) -> None:
    try:
        manifest = remove_project_from_workspace(
            args.workspace_id, str(Path(args.project_path).expanduser().resolve()),
        )
    except WorkspaceNotFoundError as exc:
        print(f"error: workspace not found: {exc}", file=sys.stderr)
        sys.exit(1)
    _out(manifest)


def cmd_migrate(args: argparse.Namespace) -> None:
    store = _get_store(args)
    result = store.migrate_schema()
    _out(result)


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
        supersedes=args.supersedes,
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


def cmd_latest(args: argparse.Namespace) -> None:
    """Find the most recently updated memory in (scope, kind)."""
    store = _get_store(args)
    status = None if args.status == "any" else args.status
    memory = store.latest_memory(
        scope=args.scope,
        kind=args.kind,
        status=status,
    )
    if memory is None:
        if args.quiet:
            sys.exit(1)
        print("(no match)", file=sys.stderr)
        sys.exit(1)
    if args.quiet:
        print(memory.memory_id)
    else:
        _out(memory)


def cmd_case(args: argparse.Namespace) -> None:
    store = _get_store(args)
    bundle = store.get_case(GetCaseRequest(
        scope=args.scope,
        include_expired=args.include_expired,
    ))

    if args.json:
        _out(bundle)
        return

    # Human-readable rendering
    print(f"# {bundle.title or bundle.scope}")
    print(f"scope: {bundle.scope}")
    print(f"total memories: {bundle.total_memories}")
    if bundle.last_touch:
        print(f"last touch: {bundle.last_touch}")
    print()

    if bundle.summary:
        s = bundle.summary
        rely_marker = "✓" if s.rely_ok else "·"
        print(f"## summary [{s.memory.status}] {rely_marker}")
        for k, v in s.memory.content.items():
            if k == "title":
                continue
            print(f"  {k}: {v}")
        print()

    def _render_bucket(label: str, items: list) -> None:
        if not items:
            return
        print(f"## {label} ({len(items)})")
        for item in items:
            rely_marker = "✓" if item.rely_ok else "·"
            status = item.memory.status
            content = item.memory.content
            primary = (
                content.get("text")
                or content.get("claim")
                or content.get("action")
                or content.get("title")
                or content.get("decision")
                or next(iter(content.values()), "")
            )
            primary_str = str(primary)[:120]
            print(f"  {rely_marker} [{status}] {item.memory.memory_id[:16]}  {primary_str}")
        print()

    _render_bucket("project_states", bundle.project_states)
    _render_bucket("next_actions", bundle.next_actions)
    _render_bucket("facts", bundle.facts)
    _render_bucket("hypotheses", bundle.hypotheses)
    _render_bucket("experiments", bundle.experiments)
    _render_bucket("lessons", bundle.lessons)
    _render_bucket("decisions", bundle.decisions)
    _render_bucket("constraints", bundle.constraints)
    _render_bucket("notes", bundle.notes)
    _render_bucket("other", bundle.other)


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
        help=(
            "path to SQLite database. "
            "Resolution order: --db, $CONTINUITY_DB_PATH, "
            "--workspace/$CONTINUITY_WORKSPACE, "
            "<git-root>/.continuity/db.sqlite, "
            f"{GLOBAL_DB_PATH}"
        ),
    )
    parser.add_argument(
        "--workspace", default=None, metavar="ID",
        help=(
            "select a named workspace store at "
            "~/.config/continuity/workspaces/<ID>/db.sqlite. "
            "Wins over git-root resolution. Equivalent to setting "
            "$CONTINUITY_WORKSPACE."
        ),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # init
    sub.add_parser("init", help="initialize the database")

    # where
    p_where = sub.add_parser(
        "where",
        help="show the active DB path, how it was resolved, and its identity",
    )
    p_where.add_argument("--json", action="store_true", help="output as JSON")

    # workspace
    p_ws = sub.add_parser(
        "workspace",
        help="manage cross-project workspace stores",
    )
    ws_sub = p_ws.add_subparsers(dest="workspace_command", required=True)

    p_ws_create = ws_sub.add_parser("create", help="create a new workspace")
    p_ws_create.add_argument("workspace_id", help="workspace identifier (no slashes)")
    p_ws_create.add_argument("--label", default=None, help="human label")

    p_ws_list = ws_sub.add_parser("list", help="list known workspaces")
    p_ws_list.add_argument("--json", action="store_true")

    p_ws_show = ws_sub.add_parser("show", help="show a workspace manifest and paths")
    p_ws_show.add_argument("workspace_id")

    p_ws_add = ws_sub.add_parser(
        "add-project", help="add a project path to a workspace manifest",
    )
    p_ws_add.add_argument("workspace_id")
    p_ws_add.add_argument("project_path")

    p_ws_rm = ws_sub.add_parser(
        "remove-project", help="remove a project path from a workspace manifest",
    )
    p_ws_rm.add_argument("workspace_id")
    p_ws_rm.add_argument("project_path")

    # migrate
    sub.add_parser(
        "migrate",
        help="patch CHECK constraints on existing tables to match current schema",
    )

    # observe
    p_obs = sub.add_parser("observe", help="observe a new memory")
    p_obs.add_argument("--scope", required=True)
    p_obs.add_argument("--kind", required=True, choices=[k.value for k in MemoryKind])
    p_obs.add_argument("--basis", required=True, choices=[b.value for b in Basis])
    p_obs.add_argument("--content", required=True, help="JSON or key=value,key=value")
    p_obs.add_argument("--confidence", type=float, default=0.5)
    p_obs.add_argument("--source-ref", action="append", help="kind:ref[:note]")
    p_obs.add_argument("--premise", action="append", help="memory_id[:relation[:strength]]")
    p_obs.add_argument(
        "--supersedes", default=None,
        help="memory_id this observation will replace when committed",
    )
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

    # latest
    p_latest = sub.add_parser(
        "latest",
        help="find the most recently updated memory in (scope, kind)",
    )
    p_latest.add_argument("--scope", required=True)
    p_latest.add_argument(
        "--kind", required=True, choices=[k.value for k in MemoryKind],
    )
    p_latest.add_argument(
        "--status", default="committed",
        choices=["observed", "committed", "revoked", "any"],
        help="status filter (default: committed; pass 'any' to skip filter)",
    )
    p_latest.add_argument(
        "-q", "--quiet", action="store_true",
        help="output only the memory_id; exit nonzero if no match",
    )

    # case
    p_case = sub.add_parser(
        "case",
        help="show a derived case bundle for a scope",
    )
    p_case.add_argument("scope", help="scope identifying the case")
    p_case.add_argument(
        "--json", action="store_true",
        help="output the bundle as JSON instead of human-readable form",
    )
    p_case.add_argument(
        "--include-expired", action="store_true",
        help="include expired memories",
    )

    # stats
    sub.add_parser("stats", help="show database statistics")

    return parser


WORKSPACE_COMMANDS = {
    "create": cmd_workspace_create,
    "list": cmd_workspace_list,
    "show": cmd_workspace_show,
    "add-project": cmd_workspace_add_project,
    "remove-project": cmd_workspace_remove_project,
}


def cmd_workspace(args: argparse.Namespace) -> None:
    handler = WORKSPACE_COMMANDS[args.workspace_command]
    handler(args)


COMMANDS = {
    "init": cmd_init,
    "migrate": cmd_migrate,
    "where": cmd_where,
    "workspace": cmd_workspace,
    "observe": cmd_observe,
    "commit": cmd_commit,
    "revoke": cmd_revoke,
    "get": cmd_get,
    "query": cmd_query,
    "explain": cmd_explain,
    "latest": cmd_latest,
    "case": cmd_case,
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
