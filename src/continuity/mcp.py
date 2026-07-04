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

from datetime import datetime, timezone

from continuity.api.models import (
    ActorRef,
    Basis,
    CommitMemoryRequest,
    GetCaseRequest,
    ImportMemoryRequest,
    MemoryKind,
    RepairMemoryRequest,
    MemoryStatus,
    ObserveMemoryRequest,
    PremiseRef,
    QueryMemoryRequest,
    RelianceClass,
    ReliedOnEntry,
    RevokeMemoryRequest,
    SourceRef,
    VerifyRelianceRequest,
    effective_reliance,
)
from continuity.store.sqlite import (
    ContentHashMismatchError,
    InvalidTransitionError,
    IslandWriteRefusedError,
    MemoryNotFoundError,
    PolicyDeniedError,
    SQLiteStore,
)
from continuity.util.dbpath import (
    GLOBAL_DB_PATH,
    resolve_db_path,
    source_to_scope_kind,
)


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
                            "relation": {
                                "type": "string",
                                "enum": [
                                    "depends_on", "supports", "derived_from",
                                    "implements", "supersedes", "invalidates",
                                    "about", "evidence_for", "confirmed_by",
                                    "ruled_out_by",
                                ],
                                "description": (
                                    "How this premise relates to the memory. "
                                    "Default: depends_on."
                                ),
                            },
                            "strength": {"type": "string", "enum": ["hard", "soft"]},
                            "note": {"type": "string"},
                        },
                    },
                    "description": "Premise links to other memories this depends on.",
                },
                "supersedes": {
                    "type": "string",
                    "description": (
                        "Memory ID this new observation will replace when "
                        "committed. Use with memory_query_latest to implement "
                        "the query-then-supersede pattern for project_state "
                        "and other singleton-current kinds."
                    ),
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
                            "relation": {
                                "type": "string",
                                "enum": [
                                    "depends_on", "supports", "derived_from",
                                    "implements", "supersedes", "invalidates",
                                    "about", "evidence_for", "confirmed_by",
                                    "ruled_out_by",
                                ],
                                "description": (
                                    "How this premise relates to the memory. "
                                    "Default: depends_on."
                                ),
                            },
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
        "name": "memory_import",
        "description": (
            "Import a memory from a source store into the local store, "
            "with content-hash verification. The caller supplies the "
            "portable payload (memory_id, scope, kind, content, "
            "reliance_class, supersedes) plus the expected sha256 "
            "content_hash; the store recomputes and refuses on mismatch. "
            "Idempotent at the same content_hash. See "
            "docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_store_id": {
                    "type": "string",
                    "description": "store_id of the source continuity DB.",
                },
                "source_ref": {
                    "type": "string",
                    "description": "Optional human-readable source pointer (e.g., a path).",
                },
                "memory_id": {
                    "type": "string",
                    "description": "memory_id in the source store (also used locally).",
                },
                "scope": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": [
                        "fact", "note", "decision", "hypothesis",
                        "summary", "constraint", "project_state",
                        "next_action", "experiment", "lesson",
                    ],
                },
                "content": {"type": "object"},
                "reliance_class": {
                    "type": "string",
                    "enum": ["none", "retrieve_only", "advisory", "actionable"],
                },
                "supersedes": {"type": "string"},
                "expected_content_hash": {
                    "type": "string",
                    "description": "sha256:... hash the caller asserts.",
                },
                "status": {
                    "type": "string",
                    "enum": ["observed", "committed", "revoked"],
                    "description": "Status to land at locally. Default 'committed'.",
                },
            },
            "required": [
                "source_store_id", "memory_id", "scope", "kind",
                "content", "expected_content_hash",
            ],
        },
    },
    {
        "name": "memory_repair",
        "description": (
            "Repair a recording error in an existing memory. Repair is "
            "intentionally narrow: only `content`, `source_refs`, and "
            "`confidence` may be patched. Fields that affect rely "
            "semantics (scope/kind/basis/status/reliance_class, "
            "expiration, supersession, premises) cannot be repaired — "
            "use the supersede pattern for scope/kind/reliance changes, "
            "or revoke+recommit for status/basis changes. The repair "
            "leaves a memory.repair event and a hash-chained receipt."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "ID of the memory to repair.",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this repair is being applied.",
                },
                "patch": {
                    "type": "object",
                    "description": (
                        "Patch dict. May only contain keys: content, "
                        "source_refs, confidence. Other keys are rejected."
                    ),
                },
                "target_event_id": {
                    "type": "string",
                    "description": (
                        "Optional: the event_id this repair corrects."
                    ),
                },
                "target_receipt_id": {
                    "type": "string",
                    "description": (
                        "Optional: the receipt_id this repair corrects."
                    ),
                },
            },
            "required": ["memory_id", "reason", "patch"],
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
            "before acting on a remembered fact to verify it is still valid. "
            "Optionally takes evaluation_time (ISO-8601) to reconstruct rely_ok "
            "as it would have been computed at that historical moment — useful "
            "for audit replay. Defaults to the current wall clock."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "The memory ID to explain.",
                },
                "evaluation_time": {
                    "type": "string",
                    "description": (
                        "Optional ISO-8601 timestamp. When provided, rely_ok "
                        "and expiration are computed as of that moment, not "
                        "the current wall clock. Reflected back in the "
                        "response's evaluation_time field."
                    ),
                },
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "memory_verify_reliance",
        "description": (
            "Verify a consumer receipt's relied_on array against the "
            "local store. Walks each citation: confirms the memory exists "
            "locally, compares pinned content_hash against current, "
            "checks status (revoked/expired) at the citation's "
            "evaluation_time. Returns per-entry status (match / "
            "content_drift / revoked_after / expired_after / missing / "
            "mode_mismatch) plus an aggregate `verified` bool. Local-only; "
            "does not contact source stores. See "
            "docs/gaps/CROSS_COMPONENT_RELIANCE_GAP.md."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "relied_on": {
                    "type": "array",
                    "description": (
                        "Array of relied_on entries from a consumer "
                        "receipt. Each entry requires memory_id, "
                        "content_hash, and evaluation_time."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "memory_id": {"type": "string"},
                            "content_hash": {"type": "string"},
                            "evaluation_time": {"type": "string"},
                            "scope": {"type": "string"},
                            "reliance_class": {
                                "type": "string",
                                "enum": ["none", "retrieve_only", "advisory", "actionable"],
                            },
                            "verification_mode": {
                                "type": "string",
                                "description": "local_native | local_import | unchecked",
                            },
                            "source_store_id": {"type": "string"},
                        },
                        "required": ["memory_id", "content_hash", "evaluation_time"],
                    },
                },
            },
            "required": ["relied_on"],
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
        "name": "memory_query_latest",
        "description": (
            "Return the most recently updated memory in (scope, kind), "
            "or null. Defaults to filtering by status=committed — the "
            "typical 'what is the current blessed value of this kind in "
            "this scope' query. This is the read side of the supersede "
            "convention: call this before observing a new project_state "
            "or next_action, then pass its memory_id as 'supersedes' on "
            "the new observation. Both old and new remain committed; "
            "lineage is preserved through the supersedes pointer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Scope to search within.",
                },
                "kind": {
                    "type": "string",
                    "enum": [
                        "fact", "note", "decision", "hypothesis",
                        "summary", "constraint", "project_state", "next_action",
                        "experiment", "lesson",
                    ],
                    "description": "Memory kind to filter by.",
                },
                "status": {
                    "type": "string",
                    "enum": ["observed", "committed", "revoked", "any"],
                    "description": "Status filter. Default 'committed'.",
                },
            },
            "required": ["scope", "kind"],
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

_DEFAULT_PRINCIPAL_ID = "claude:mcp"
_PRINCIPAL_ENV_VAR = "CONTINUITY_PRINCIPAL_ID"


def _parse_evaluation_time(value: Any) -> datetime | None:
    """Parse an ISO-8601 string into a timezone-aware datetime, or None.

    Accepts None passthrough; rejects empty strings to keep handler args
    honest. The bare 'Z' suffix common in JSON timestamps is normalized to
    +00:00 because fromisoformat in Python <3.11 rejects it.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("evaluation_time must be a non-empty ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _mcp_actor() -> ActorRef:
    """Build the actor that authored the current MCP call.

    Defaults to 'claude:mcp' but can be overridden via the
    CONTINUITY_PRINCIPAL_ID environment variable. Use this when you want
    the audit trail to read 'jbeck via claude:mcp' instead of 'claude:mcp'
    alone — set it in .mcp.json env or in your shell rc.
    """
    principal_id = os.environ.get(_PRINCIPAL_ENV_VAR, _DEFAULT_PRINCIPAL_ID)
    return ActorRef(principal_id=principal_id, auth_method="mcp")


class ContinuityMCPServer:
    def __init__(
        self,
        db_path: Path | None = None,
        *,
        scope_kind: str | None = None,
        scope_label: str | None = None,
        allow_island: bool = False,
    ) -> None:
        if db_path is None:
            db_path, source = resolve_db_path()
            if scope_kind is None:
                scope_kind = source_to_scope_kind(source)
        self.db_path = db_path
        self.scope_kind = scope_kind
        self.scope_label = scope_label
        self.allow_island = allow_island
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._store: SQLiteStore | None = None

    @property
    def store(self) -> SQLiteStore:
        if self._store is None:
            self._store = SQLiteStore(
                self.db_path, allow_island=self.allow_island,
            )
            self._store.initialize(
                scope_kind=self.scope_kind,
                scope_label=self.scope_label,
            )
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
        except PolicyDeniedError as exc:
            # Refusal receipt has already been appended; surface its ID so
            # the caller can fetch the audit artifact.
            return {
                "error": f"policy denied: {exc.reason}",
                "refused": True,
                "refusal_receipt_id": exc.refusal_receipt.receipt_id,
                "refusal_receipt_hash": exc.refusal_receipt.hash,
            }
        except IslandWriteRefusedError as exc:
            return {
                "error": str(exc),
                "refused": True,
                "reason": "island_write_refused",
                "scope": exc.scope,
                "store_scope_kind": exc.store_scope_kind,
            }
        except ContentHashMismatchError as exc:
            return {
                "error": str(exc),
                "refused": True,
                "reason": "content_hash_mismatch",
                "memory_id": exc.memory_id,
                "expected": exc.expected,
                "actual": exc.actual,
            }
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
            supersedes=args.get("supersedes"),
            authoring_tier=args.get("authoring_tier"),
            source_observed_at=_parse_evaluation_time(args.get("source_observed_at")),
            actor=_mcp_actor(),
        )

        resp = self.store.observe_memory(req)
        return {
            "memory_id": resp.memory.memory_id,
            "status": resp.memory.status,
            "authoring_tier": resp.memory.authoring_tier,
            "supersedes": resp.memory.supersedes,
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
            authoring_tier=args.get("authoring_tier"),
            approved_by=_mcp_actor(),
        )

        resp = self.store.commit_memory(req)
        return {
            "memory_id": resp.memory.memory_id,
            "status": resp.memory.status,
            "reliance_class": resp.memory.reliance_class,
            "authoring_tier": resp.memory.authoring_tier,
            "effective_reliance": effective_reliance(
                resp.memory.reliance_class, resp.memory.authoring_tier,
            ),
            "receipt_id": resp.receipt.receipt_id,
            "receipt_hash": resp.receipt.hash,
        }

    def _handle_memory_revoke(self, args: dict[str, Any]) -> dict[str, Any]:
        req = RevokeMemoryRequest(
            memory_id=args["memory_id"],
            reason=args["reason"],
            replacement_memory_id=args.get("replacement_memory_id"),
            revoked_by=_mcp_actor(),
        )

        resp = self.store.revoke_memory(req)
        return {
            "memory_id": resp.memory.memory_id,
            "status": resp.memory.status,
            "receipt_id": resp.receipt.receipt_id,
        }

    def _handle_memory_import(self, args: dict[str, Any]) -> dict[str, Any]:
        source_refs = [
            SourceRef(**s) for s in args.get("source_refs", [])
        ]
        req = ImportMemoryRequest(
            source_store_id=args["source_store_id"],
            source_ref=args.get("source_ref"),
            memory_id=args["memory_id"],
            scope=args["scope"],
            kind=args["kind"],
            basis=args.get("basis", "import"),
            content=args["content"],
            reliance_class=args.get("reliance_class", "none"),
            supersedes=args.get("supersedes"),
            confidence=args.get("confidence", 0.5),
            source_refs=source_refs,
            status=args.get("status", "committed"),
            expected_content_hash=args["expected_content_hash"],
            actor=_mcp_actor(),
        )
        resp = self.store.import_memory(req)
        return {
            "memory_id": resp.memory.memory_id,
            "spool_import_id": resp.spool_import_id,
            "already_imported": resp.already_imported,
            "event_id": resp.event.event_id,
            "receipt_id": resp.receipt.receipt_id,
            "receipt_hash": resp.receipt.hash,
        }

    def _handle_memory_repair(self, args: dict[str, Any]) -> dict[str, Any]:
        req = RepairMemoryRequest(
            memory_id=args["memory_id"],
            reason=args["reason"],
            patch=args.get("patch") or {},
            target_event_id=args.get("target_event_id"),
            target_receipt_id=args.get("target_receipt_id"),
            actor=_mcp_actor(),
        )
        resp = self.store.repair_memory(req)
        return {
            "memory_id": resp.memory.memory_id,
            "event_id": resp.event.event_id,
            "receipt_id": resp.receipt.receipt_id,
            "receipt_hash": resp.receipt.hash,
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
                    "authoring_tier": m.authoring_tier,
                    "effective_reliance": effective_reliance(
                        m.reliance_class, m.authoring_tier,
                    ),
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
        payload = memory.model_dump(mode="json")
        # authoring_tier is already in the dump; surface the effective reliance
        # ceiling explicitly (read at tier, never above — MEMORY_AUTHORING_TIER).
        payload["effective_reliance"] = effective_reliance(
            memory.reliance_class, memory.authoring_tier,
        )
        return payload

    def _handle_memory_explain(self, args: dict[str, Any]) -> dict[str, Any]:
        evaluation_time = _parse_evaluation_time(args.get("evaluation_time"))
        resp = self.store.explain_memory(
            args["memory_id"],
            evaluation_time=evaluation_time,
        )
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
            "rely_state": (
                {
                    "code": resp.rely_state.code,
                    "message": resp.rely_state.message,
                    "details": resp.rely_state.details,
                }
                if resp.rely_state is not None else None
            ),
            "evaluation_time": (
                resp.evaluation_time.isoformat()
                if resp.evaluation_time is not None else None
            ),
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
            "imported_premises": [
                {
                    "link_id": ip.link_id,
                    "src_memory_id": ip.src_memory_id,
                    "pinned_content_hash": ip.pinned_content_hash,
                    "current_content_hash": ip.current_content_hash,
                    "content_status": ip.content_status,
                    "state": ip.state,
                    "source_store_id": ip.source_store_id,
                    "imported_at": (
                        ip.imported_at.isoformat() if ip.imported_at else None
                    ),
                }
                for ip in resp.imported_premises
            ],
        }

    def _handle_memory_query_latest(self, args: dict[str, Any]) -> dict[str, Any]:
        status_arg = args.get("status", "committed")
        status = None if status_arg == "any" else status_arg
        memory = self.store.latest_memory(
            scope=args["scope"],
            kind=args["kind"],
            status=status,
        )
        if memory is None:
            return {"memory": None}
        return {
            "memory": {
                "memory_id": memory.memory_id,
                "scope": memory.scope,
                "kind": memory.kind,
                "status": memory.status,
                "reliance_class": memory.reliance_class,
                "supersedes": memory.supersedes,
                "content": memory.content,
                "created_at": str(memory.created_at),
                "updated_at": str(memory.updated_at),
            },
        }

    def _handle_memory_get_case(self, args: dict[str, Any]) -> dict[str, Any]:
        req = GetCaseRequest(
            scope=args["scope"],
            include_expired=args.get("include_expired", False),
        )
        bundle = self.store.get_case(req)
        return bundle.model_dump(mode="json")

    def _handle_memory_verify_reliance(
        self, args: dict[str, Any],
    ) -> dict[str, Any]:
        raw_entries = args.get("relied_on", []) or []
        if not isinstance(raw_entries, list):
            return {"error": "`relied_on` must be an array"}
        entries = [ReliedOnEntry.model_validate(e) for e in raw_entries]
        resp = self.store.verify_reliance(VerifyRelianceRequest(entries=entries))
        return {
            "verified": resp.verified,
            "summary": resp.summary,
            "entries": [
                {
                    "memory_id": v.entry.memory_id,
                    "status": v.status,
                    "current_content_hash": v.current_content_hash,
                    "current_status": v.current_status,
                    "detail": v.detail,
                }
                for v in resp.entries
            ],
        }

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


def create_server(
    db_path: Path | None = None,
    *,
    scope_kind: str | None = None,
    scope_label: str | None = None,
    allow_island: bool = False,
) -> ContinuityMCPServer:
    return ContinuityMCPServer(
        db_path,
        scope_kind=scope_kind,
        scope_label=scope_label,
        allow_island=allow_island,
    )


def run_mcp_server(
    db_path: Path | None = None,
    *,
    scope_kind: str | None = None,
    scope_label: str | None = None,
    allow_island: bool = False,
) -> None:
    """Run the continuity MCP server over JSON-RPC/stdio."""
    log.info("SERVER STARTING db_path=%s pid=%d", db_path, os.getpid())
    log.info("  python=%s", sys.executable)
    log.info("  argv=%s", sys.argv)
    log.info(
        "  scope_kind=%s scope_label=%s allow_island=%s",
        scope_kind, scope_label, allow_island,
    )
    server = create_server(
        db_path,
        scope_kind=scope_kind,
        scope_label=scope_label,
        allow_island=allow_island,
    )
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
            "--workspace/$CONTINUITY_WORKSPACE, "
            f"<git-root>/.continuity/db.sqlite, {GLOBAL_DB_PATH}"
        ),
    )
    parser.add_argument(
        "--workspace", default=None, metavar="ID",
        help=(
            "select a named workspace store. "
            "Equivalent to setting $CONTINUITY_WORKSPACE."
        ),
    )
    args = parser.parse_args()

    explicit = Path(args.db) if args.db else None
    db_path, source = resolve_db_path(explicit, workspace=args.workspace)
    scope_kind = source_to_scope_kind(source)
    scope_label = (
        (args.workspace or os.environ.get("CONTINUITY_WORKSPACE"))
        if source == "workspace"
        else None
    )
    allow_island = os.environ.get("CONTINUITY_ALLOW_ISLAND", "").lower() in (
        "1", "true", "yes",
    )
    log.info(
        "DB resolved: %s (source=%s, scope_kind=%s, label=%s, allow_island=%s)",
        db_path, source, scope_kind, scope_label, allow_island,
    )
    # If the resolver landed in fallback territory, log it loudly so the
    # operator can see the topology in the debug log without having to run
    # `contctl where` afterward (docs/gaps/ISLANDS_OF_CONTINUITY.md inv. 4).
    if source in ("git-root", "global-fallback"):
        log.warning(
            "TOPOLOGY: server resolved DB by '%s' fallback. "
            "Cross-project-shaped writes (scope=global / scope=workspace*) "
            "will refuse without allow_island. Set CONTINUITY_WORKSPACE or "
            "use --workspace to point at a shared store.",
            source,
        )
    run_mcp_server(
        db_path,
        scope_kind=scope_kind,
        scope_label=scope_label,
        allow_island=allow_island,
    )


if __name__ == "__main__":
    main()
