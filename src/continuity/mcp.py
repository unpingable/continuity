"""continuity MCP server — JSON-RPC over stdio.

Exposes continuity as MCP tools for Claude Code and other MCP clients.
No external SDK dependency. Follows the same custom JSON-RPC pattern
as agent_gov.

Tools:
  memory_observe   — observe a new memory
  memory_commit    — commit an observed memory
  memory_revoke    — revoke a memory
  memory_query     — query memories by scope/kind/status
  memory_get       — get a single memory by ID
  memory_explain   — explain a memory (lineage, premises, rely_ok)
  memory_stats     — database statistics
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

_LOG_PATH = Path.home() / ".local" / "share" / "continuity" / "mcp-debug.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(_LOG_PATH),
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("continuity.mcp")

from continuity.api.models import (
    ActorRef,
    CommitMemoryRequest,
    GetCaseRequest,
    ObserveMemoryRequest,
    PremiseRef,
    QueryMemoryRequest,
    RelianceClass,
    RevokeMemoryRequest,
    SourceRef,
)
from continuity.store.sqlite import (
    InvalidTransitionError,
    MemoryNotFoundError,
    SQLiteStore,
)
from continuity.util.dbpath import GLOBAL_DB_PATH, resolve_db_path


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "memory_observe",
        "description": (
            "Observe a new memory. Creates a memory object with status=observed "
            "and reliance_class=none. This is cheap and non-binding — observations "
            "must be explicitly committed before they can be relied on."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Scope for the memory (e.g., project name, domain).",
                },
                "kind": {
                    "type": "string",
                    "enum": [
                        "fact", "note", "decision", "hypothesis",
                        "summary", "constraint", "project_state", "next_action",
                        "experiment", "lesson",
                    ],
                    "description": "Kind of memory object.",
                },
                "basis": {
                    "type": "string",
                    "enum": [
                        "direct_capture", "operator_assertion",
                        "inference", "import", "synthesis",
                    ],
                    "description": "How this memory was derived.",
                },
                "content": {
                    "type": "object",
                    "description": "The memory content as a JSON object.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence level 0.0-1.0. Default 0.5.",
                },
                "source_refs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ref": {"type": "string"},
                            "kind": {"type": "string"},
                            "note": {"type": "string"},
                        },
                        "required": ["ref", "kind"],
                    },
                    "description": "References to source material.",
                },
                "premises": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "memory_id": {"type": "string"},
                            "relation": {"type": "string"},
                            "strength": {"type": "string", "enum": ["hard", "soft"]},
                            "note": {"type": "string"},
                        },
                    },
                    "description": "Premise links to other memories this depends on.",
                },
            },
            "required": ["scope", "kind", "basis", "content"],
        },
    },
    {
        "name": "memory_commit",
        "description": (
            "Commit an observed memory, promoting it to committed status with "
            "an explicit reliance class. This is the transition from 'noticed' to "
            "'may be relied on'. Requires the memory to be in observed status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "ID of the memory to commit.",
                },
                "reliance_class": {
                    "type": "string",
                    "enum": ["none", "retrieve_only", "advisory", "actionable"],
                    "description": "What downstream use is permitted. Default: retrieve_only.",
                },
                "note": {
                    "type": "string",
                    "description": "Optional note about why this was committed.",
                },
                "supersedes": {
                    "type": "string",
                    "description": "Memory ID this supersedes, if any.",
                },
                "premises": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "memory_id": {"type": "string"},
                            "relation": {"type": "string"},
                            "strength": {"type": "string", "enum": ["hard", "soft"]},
                            "note": {"type": "string"},
                        },
                    },
                    "description": "Additional premise links to add at commit time (appends, does not replace).",
                },
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "memory_revoke",
        "description": (
            "Revoke a memory. The memory stays in the database as history but "
            "is marked revoked. Any memory with a hard premise on this one will "
            "have its rely_ok tainted. Provide a reason."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "ID of the memory to revoke.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this memory is being revoked.",
                },
                "replacement_memory_id": {
                    "type": "string",
                    "description": "ID of a replacement memory, if any.",
                },
            },
            "required": ["memory_id", "reason"],
        },
    },
    {
        "name": "memory_query",
        "description": (
            "Query memories by scope, kind, status, basis, or reliance class. "
            "Returns matching memories ordered by most recently updated. "
            "Use this to check what the system already knows about a topic."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Filter by scope.",
                },
                "kind": {
                    "type": "string",
                    "enum": [
                        "fact", "note", "decision", "hypothesis",
                        "summary", "constraint", "project_state", "next_action",
                        "experiment", "lesson",
                    ],
                    "description": "Filter by kind.",
                },
                "status": {
                    "type": "string",
                    "enum": ["observed", "committed", "revoked"],
                    "description": "Filter by status.",
                },
                "basis": {
                    "type": "string",
                    "enum": [
                        "direct_capture", "operator_assertion",
                        "inference", "import", "synthesis",
                    ],
                    "description": "Filter by basis.",
                },
                "reliance_class": {
                    "type": "string",
                    "enum": ["none", "retrieve_only", "advisory", "actionable"],
                    "description": "Filter by reliance class.",
                },
                "include_expired": {
                    "type": "boolean",
                    "description": "Include expired memories. Default false.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results. Default 100.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "memory_get",
        "description": "Get a single memory object by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "The memory ID to retrieve.",
                },
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "memory_explain",
        "description": (
            "Explain a memory: its full event lineage, receipt chain, premises, "
            "dependents, and whether it is safe to rely on (rely_ok). Use this "
            "before acting on a remembered fact to verify it is still valid."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "The memory ID to explain.",
                },
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "memory_stats",
        "description": "Get database statistics: counts by status, kind, scope.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "memory_get_case",
        "description": (
            "Get a derived case bundle for a scope. A case is computed on "
            "demand from all memories in the scope, bucketed by kind "
            "(facts, hypotheses, decisions, constraints, notes, other) "
            "and paired with rely state. Use this to retrieve an "
            "investigation, debugging session, or other multi-memory case "
            "as a single structured view. The bundle itself is a navigation "
            "aid — code that wants to act on a finding should rely on the "
            "underlying fact, not the bundle."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Scope identifying the case (e.g., 'case:mcp-stdio-2026-04-09').",
                },
                "include_expired": {
                    "type": "boolean",
                    "description": "Include expired memories. Default false.",
                },
            },
            "required": ["scope"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

class ContinuityMCPServer:
    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path, _source = resolve_db_path()
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._store: SQLiteStore | None = None

    @property
    def store(self) -> SQLiteStore:
        if self._store is None:
            self._store = SQLiteStore(self.db_path)
            self._store.initialize()
        return self._store

    def list_tools(self) -> list[dict[str, Any]]:
        return TOOLS

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_handle_{name}", None)
        if handler is None:
            return {"error": f"unknown tool: {name}"}
        try:
            return handler(arguments)
        except MemoryNotFoundError as exc:
            return {"error": f"memory not found: {exc}"}
        except InvalidTransitionError as exc:
            return {"error": f"invalid transition: {exc}"}
        except Exception as exc:
            return {"error": str(exc)}

    def _handle_memory_observe(self, args: dict[str, Any]) -> dict[str, Any]:
        source_refs = [
            SourceRef(**s) for s in args.get("source_refs", [])
        ]
        premises = [
            PremiseRef(
                memory_id=p.get("memory_id"),
                relation=p.get("relation", "depends_on"),
                strength=p.get("strength", "hard"),
                note=p.get("note"),
            )
            for p in args.get("premises", [])
        ]

        req = ObserveMemoryRequest(
            scope=args["scope"],
            kind=args["kind"],
            basis=args["basis"],
            content=args["content"],
            confidence=args.get("confidence", 0.5),
            source_refs=source_refs,
            premises=premises,
            actor=ActorRef(principal_id="claude:mcp", auth_method="mcp"),
        )

        resp = self.store.observe_memory(req)
        return {
            "memory_id": resp.memory.memory_id,
            "status": resp.memory.status,
            "receipt_id": resp.receipt.receipt_id,
            "receipt_hash": resp.receipt.hash,
        }

    def _handle_memory_commit(self, args: dict[str, Any]) -> dict[str, Any]:
        premises = [
            PremiseRef(
                memory_id=p.get("memory_id"),
                relation=p.get("relation", "depends_on"),
                strength=p.get("strength", "hard"),
                note=p.get("note"),
            )
            for p in args.get("premises", [])
        ]

        req = CommitMemoryRequest(
            memory_id=args["memory_id"],
            reliance_class=args.get("reliance_class", "retrieve_only"),
            note=args.get("note"),
            supersedes=args.get("supersedes"),
            premises=premises,
            approved_by=ActorRef(principal_id="claude:mcp", auth_method="mcp"),
        )

        resp = self.store.commit_memory(req)
        return {
            "memory_id": resp.memory.memory_id,
            "status": resp.memory.status,
            "reliance_class": resp.memory.reliance_class,
            "receipt_id": resp.receipt.receipt_id,
            "receipt_hash": resp.receipt.hash,
        }

    def _handle_memory_revoke(self, args: dict[str, Any]) -> dict[str, Any]:
        req = RevokeMemoryRequest(
            memory_id=args["memory_id"],
            reason=args["reason"],
            replacement_memory_id=args.get("replacement_memory_id"),
            revoked_by=ActorRef(principal_id="claude:mcp", auth_method="mcp"),
        )

        resp = self.store.revoke_memory(req)
        return {
            "memory_id": resp.memory.memory_id,
            "status": resp.memory.status,
            "receipt_id": resp.receipt.receipt_id,
        }

    def _handle_memory_query(self, args: dict[str, Any]) -> dict[str, Any]:
        req = QueryMemoryRequest(
            scope=args.get("scope"),
            kind=args.get("kind"),
            status=args.get("status"),
            basis=args.get("basis"),
            reliance_class=args.get("reliance_class"),
            include_expired=args.get("include_expired", False),
            limit=args.get("limit", 100),
        )

        resp = self.store.query_memory(req)
        return {
            "total": resp.total,
            "items": [
                {
                    "memory_id": m.memory_id,
                    "scope": m.scope,
                    "kind": m.kind,
                    "basis": m.basis,
                    "status": m.status,
                    "reliance_class": m.reliance_class,
                    "confidence": m.confidence,
                    "content": m.content,
                    "created_at": str(m.created_at),
                    "updated_at": str(m.updated_at),
                }
                for m in resp.items
            ],
        }

    def _handle_memory_get(self, args: dict[str, Any]) -> dict[str, Any]:
        memory = self.store.get_memory(args["memory_id"])
        return memory.model_dump(mode="json")

    def _handle_memory_explain(self, args: dict[str, Any]) -> dict[str, Any]:
        resp = self.store.explain_memory(args["memory_id"])
        return {
            "memory": {
                "memory_id": resp.memory.memory_id,
                "scope": resp.memory.scope,
                "kind": resp.memory.kind,
                "status": resp.memory.status,
                "reliance_class": resp.memory.reliance_class,
                "content": resp.memory.content,
            },
            "rely_ok": resp.rely_ok,
            "rely_reason": resp.rely_reason,
            "event_count": len(resp.events),
            "premises": [
                {
                    "link_id": p.link_id,
                    "src_memory_id": p.src_memory_id,
                    "src_receipt_id": p.src_receipt_id,
                    "relation": p.relation,
                    "strength": p.strength,
                    "status": p.status,
                    "note": p.note,
                }
                for p in resp.premises
            ],
            "dependents": [
                {
                    "link_id": d.link_id,
                    "dst_memory_id": d.dst_memory_id,
                    "relation": d.relation,
                    "strength": d.strength,
                    "status": d.status,
                }
                for d in resp.dependents
            ],
        }

    def _handle_memory_get_case(self, args: dict[str, Any]) -> dict[str, Any]:
        req = GetCaseRequest(
            scope=args["scope"],
            include_expired=args.get("include_expired", False),
        )
        bundle = self.store.get_case(req)
        return bundle.model_dump(mode="json")

    def _handle_memory_stats(self, args: dict[str, Any]) -> dict[str, Any]:
        with self.store._connect() as conn:
            memories = conn.execute("SELECT COUNT(*) AS c FROM memory_objects").fetchone()["c"]
            events = conn.execute("SELECT COUNT(*) AS c FROM memory_events").fetchone()["c"]
            receipts = conn.execute("SELECT COUNT(*) AS c FROM receipts").fetchone()["c"]
            links = conn.execute("SELECT COUNT(*) AS c FROM memory_links").fetchone()["c"]

            by_status = conn.execute(
                "SELECT status, COUNT(*) AS c FROM memory_objects GROUP BY status"
            ).fetchall()
            by_kind = conn.execute(
                "SELECT kind, COUNT(*) AS c FROM memory_objects GROUP BY kind"
            ).fetchall()
            by_scope = conn.execute(
                "SELECT scope, COUNT(*) AS c FROM memory_objects GROUP BY scope"
            ).fetchall()

        return {
            "memories": memories,
            "events": events,
            "receipts": receipts,
            "links": links,
            "by_status": {r["status"]: r["c"] for r in by_status},
            "by_kind": {r["kind"]: r["c"] for r in by_kind},
            "by_scope": {r["scope"]: r["c"] for r in by_scope},
        }


# ---------------------------------------------------------------------------
# JSON-RPC over stdio transport
# ---------------------------------------------------------------------------

def _send_response(response: dict[str, Any]) -> None:
    """Send a JSON-RPC response as NDJSON (one JSON object per line).

    Claude Code expects newline-delimited JSON, not Content-Length framing.
    """
    body = json.dumps(response, separators=(",", ":"))
    log.debug("SEND id=%s method=%s len=%d", response.get("id"), response.get("method"), len(body))
    sys.stdout.buffer.write(body.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def _read_request() -> dict[str, Any] | None:
    """Read a JSON-RPC request as NDJSON (one JSON object per line).

    Claude Code sends newline-delimited JSON, not Content-Length framing.
    """
    log.debug("RECV waiting for line...")
    line = sys.stdin.buffer.readline()
    if not line:
        log.debug("RECV stdin EOF")
        return None
    line = line.strip()
    if not line:
        log.debug("RECV empty line, skipping")
        return _read_request()
    parsed = json.loads(line.decode("utf-8"))
    log.debug("RECV id=%s method=%s", parsed.get("id"), parsed.get("method"))
    return parsed


def create_server(db_path: Path | None = None) -> ContinuityMCPServer:
    return ContinuityMCPServer(db_path)


def run_mcp_server(db_path: Path | None = None) -> None:
    """Run the continuity MCP server over JSON-RPC/stdio."""
    log.info("SERVER STARTING db_path=%s pid=%d", db_path, os.getpid())
    log.info("  python=%s", sys.executable)
    log.info("  argv=%s", sys.argv)
    server = create_server(db_path)
    log.info("SERVER READY, entering read loop")

    while True:
        request = _read_request()
        if request is None:
            log.info("SERVER EXITING (null request)")
            break

        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")

        if method == "initialize":
            log.info("INIT params: %s", json.dumps(params, default=str))
            client_version = params.get("protocolVersion", "unknown")
            log.info("INIT client requests protocolVersion=%s", client_version)
            # Negotiate: echo back the client's version if we can work with it,
            # otherwise offer our preferred version and hope for the best.
            SUPPORTED_VERSIONS = ["2025-03-26", "2024-11-05"]
            negotiated = client_version if client_version in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
            log.info("INIT negotiated protocolVersion=%s", negotiated)
            _send_response({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": negotiated,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "continuity",
                        "version": "0.1.0",
                    },
                },
            })
        elif method == "notifications/initialized":
            # Client notification, no response needed
            pass
        elif method == "tools/list":
            _send_response({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": server.list_tools()},
            })
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = server.call_tool(tool_name, arguments)

            _send_response({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2, default=str),
                        }
                    ],
                },
            })
        else:
            _send_response({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"method not found: {method}",
                },
            })


def main() -> None:
    """Entry point for continuity-mcp console script."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="continuity-mcp",
        description="continuity MCP server — governed memory tools for Claude",
    )
    parser.add_argument(
        "--db", default=None,
        help=(
            "path to SQLite database. "
            "Resolution order: --db, $CONTINUITY_DB_PATH, "
            f"<git-root>/.continuity/db.sqlite, {GLOBAL_DB_PATH}"
        ),
    )
    args = parser.parse_args()

    explicit = Path(args.db) if args.db else None
    db_path, source = resolve_db_path(explicit)
    log.info("DB resolved: %s (source=%s)", db_path, source)
    run_mcp_server(db_path)


if __name__ == "__main__":
    main()
