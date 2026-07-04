"""SQLite-backed continuity store.

Three responsibilities:
  1. Materialize memory object state
  2. Append memory events with hash-chained receipts
  3. Maintain provenance graph (memory_links)
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# Bump this when the schema.sql shape changes (new tables, columns,
# CHECK constraint expansions). It is the store/schema substrate version,
# not the package version. Stored in store_metadata so receipts and
# cross-system consumers can pin which schema shape produced an answer.
SCHEMA_VERSION = 2

from continuity.api.models import (
    ActorRef,
    Basis,
    CaseBundle,
    CaseItem,
    CommitMemoryRequest,
    CommitMemoryResponse,
    EventType,
    ExplainMemoryResponse,
    GetCaseRequest,
    ImportMemoryRequest,
    ImportMemoryResponse,
    ImportedPremiseStatus,
    ReliedOnEntry,
    ReliedOnVerification,
    VerifyRelianceRequest,
    VerifyRelianceResponse,
    LinkStatus,
    MemoryEvent,
    MemoryKind,
    MemoryLink,
    MemoryObject,
    MemoryStatus,
    ObserveMemoryRequest,
    ObserveMemoryResponse,
    PremiseRef,
    QueryMemoryRequest,
    QueryMemoryResponse,
    ReceiptRecord,
    ReceiptType,
    RelianceClass,
    RelyReasonCode,
    RelyState,
    RepairMemoryRequest,
    RepairMemoryResponse,
    RevokeMemoryRequest,
    RevokeMemoryResponse,
    SourceRef,
    StandingRef,
)
from continuity.util.clock import isoformat_now, to_isoformat, utcnow
from datetime import datetime
from continuity.memory.policy import Decision, MemoryPolicy, PolicyResult
from continuity.util.dbpath import find_git_root
from continuity.util.hashing import content_hash, receipt_hash, request_hash
from continuity.util.ids import new_id
from continuity.util.jsoncanon import canonical_json, from_json


def _to_json(value: Any) -> str:
    return canonical_json(value)


def _extract_create_table(schema_sql: str, table: str) -> str | None:
    """Extract a single CREATE TABLE statement from a multi-statement schema.

    Returns the statement without trailing semicolon, suitable for substituting
    into sqlite_master.sql via PRAGMA writable_schema. Returns None if not found.
    """
    marker = f"CREATE TABLE IF NOT EXISTS {table} ("
    start = schema_sql.find(marker)
    if start == -1:
        return None
    # Walk forward tracking parenthesis depth until we hit the closing ');'
    depth = 0
    i = start
    while i < len(schema_sql):
        ch = schema_sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                # Found the closing paren of the CREATE TABLE
                end = i + 1
                stmt = schema_sql[start:end]
                # Strip "IF NOT EXISTS" — sqlite_master stores the canonical form
                stmt = stmt.replace("CREATE TABLE IF NOT EXISTS ", "CREATE TABLE ")
                return stmt
        i += 1
    return None


def _summary_priority(item: "CaseItem") -> tuple[int, Any]:
    """Sort key for picking the bundle's summary memory.

    Prefer committed summaries, then by most recent updated_at. Returning
    a tuple lets us compare across two candidates without writing branches.
    """
    status_rank = {
        MemoryStatus.COMMITTED: 2,
        MemoryStatus.OBSERVED: 1,
        MemoryStatus.REVOKED: 0,
    }.get(item.memory.status, 0)
    return (status_rank, item.memory.updated_at)


class MemoryNotFoundError(KeyError):
    pass


class IdempotencyConflictError(RuntimeError):
    pass


class InvalidTransitionError(RuntimeError):
    pass


class PolicyDeniedError(RuntimeError):
    """Raised when MemoryPolicy denies a write. A refusal receipt has
    already been appended to the receipt chain before this is raised, so
    the denial is audit-visible even though no memory row was created.
    """

    def __init__(self, reason: str, refusal_receipt: ReceiptRecord) -> None:
        super().__init__(reason)
        self.reason = reason
        self.refusal_receipt = refusal_receipt


class ContentHashMismatchError(RuntimeError):
    """Raised when import sees an unexpected content_hash.

    Two cases trigger this:
      1. The caller's `expected_content_hash` does not match the hash
         computed over the payload they supplied — defends against bad
         payloads or stale pin metadata.
      2. The memory already exists locally at a different content_hash
         (the source has drifted since the local import). Per
         docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md, V1 refuses this case
         rather than silently overwrite or fork — the operator handles
         drift explicitly via revoke + re-import, or by importing a
         supersede successor as a new memory_id.
    """

    def __init__(
        self,
        *,
        memory_id: str,
        expected: str,
        actual: str,
        reason: str,
    ) -> None:
        super().__init__(
            f"content_hash mismatch for {memory_id}: expected {expected}, "
            f"got {actual} ({reason})"
        )
        self.memory_id = memory_id
        self.expected = expected
        self.actual = actual
        self.reason = reason


class IslandWriteRefusedError(RuntimeError):
    """Raised when a cross-project-shaped write would land in an isolated
    project-local (or fallback-global) DB without explicit opt-in.

    A `scope=global` memory in a project-local DB is "a local memory wearing
    a fake mustache" (per docs/gaps/ISLANDS_OF_CONTINUITY.md). The store
    refuses such writes by default; pass `allow_island=True` to the store
    constructor (CLI `--allow-island`) to override after seeing the warning.
    """

    def __init__(self, scope: str, store_scope_kind: str, db_path: Path) -> None:
        msg = (
            f"refusing to write scope={scope!r} to a {store_scope_kind!r} "
            f"store at {db_path} — this would create an island "
            f"(a cross-project memory in a project-local DB). "
            f"Set CONTINUITY_WORKSPACE/--workspace to point at a shared "
            f"store, or pass --allow-island / allow_island=True to confirm."
        )
        super().__init__(msg)
        self.scope = scope
        self.store_scope_kind = store_scope_kind
        self.db_path = db_path


# Scope prefixes/values that signal cross-project intent. A write at these
# scopes against a project-local store is the islands bug.
_CROSS_PROJECT_SCOPE_EXACT = frozenset({"global", "workspace"})
_CROSS_PROJECT_SCOPE_PREFIXES = ("workspace:",)


def _is_cross_project_scope(scope: str) -> bool:
    if scope in _CROSS_PROJECT_SCOPE_EXACT:
        return True
    return any(scope.startswith(p) for p in _CROSS_PROJECT_SCOPE_PREFIXES)


class SQLiteStore:
    def __init__(
        self,
        db_path: str | Path,
        *,
        policy: MemoryPolicy | None = None,
        allow_island: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        # Default policy is intentionally light — Governor or a downstream
        # caller plugs in a stricter policy by passing one in.
        self.policy = policy if policy is not None else MemoryPolicy()
        # When True, cross-project-shaped scopes (global / workspace*) may
        # be written even to a project-local DB. Operators set this after
        # seeing the topology warning. Default False per
        # docs/gaps/ISLANDS_OF_CONTINUITY.md invariant 3.
        self.allow_island = allow_island

    def initialize(
        self,
        *,
        scope_kind: str | None = None,
        scope_label: str | None = None,
    ) -> None:
        """Initialize the database and (optionally) stamp scope identity.

        scope_kind and scope_label are only used on first-init: they
        describe what kind of store this is ('project', 'workspace',
        'global', 'explicit') and a human label. Subsequent calls
        do not overwrite existing metadata.
        """
        schema_path = Path(__file__).with_name("schema.sql")
        schema_sql = schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema_sql)
            self._add_missing_columns(conn)
            self._ensure_store_metadata(
                conn,
                scope_kind=scope_kind,
                scope_label=scope_label,
            )

    def _add_missing_columns(self, conn: sqlite3.Connection) -> None:
        """ALTER TABLE for columns added after the original schema was shipped.

        SQLite ALTER TABLE ADD COLUMN is cheap and fully supported. We
        check existence via PRAGMA table_info first to stay idempotent.
        """
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(store_metadata)").fetchall()
        }
        if "scope_kind" not in existing:
            conn.execute("ALTER TABLE store_metadata ADD COLUMN scope_kind TEXT NULL")
        if "schema_version" not in existing:
            conn.execute(
                "ALTER TABLE store_metadata ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1"
            )

        links_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(memory_links)").fetchall()
        }
        if "pinned_content_hash" not in links_cols:
            conn.execute(
                "ALTER TABLE memory_links ADD COLUMN pinned_content_hash TEXT NULL"
            )

    def _ensure_store_metadata(
        self,
        conn: sqlite3.Connection,
        *,
        scope_kind: str | None = None,
        scope_label: str | None = None,
    ) -> None:
        """Populate store_metadata on first init.

        The metadata is a singleton — one row per database — that records
        store identity, the git root the DB lived next to at creation
        time, the scope kind, and a project hint. It is never updated
        after creation; it describes origin, not current state.

        scope_label, when provided, overrides the auto-derived hint.
        """
        row = conn.execute(
            "SELECT store_id FROM store_metadata WHERE id = 1"
        ).fetchone()
        if row is not None:
            return

        db_dir = self.db_path.parent.resolve()
        git_root = find_git_root(db_dir)

        if scope_label is not None:
            project_hint = scope_label
        elif git_root is not None:
            project_hint = git_root.name
        else:
            project_hint = db_dir.name

        conn.execute(
            "INSERT INTO store_metadata "
            "(id, store_id, project_hint, git_root, scope_kind, schema_version, created_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?)",
            (
                new_id("store"),
                project_hint,
                str(git_root) if git_root is not None else None,
                scope_kind,
                SCHEMA_VERSION,
                isoformat_now(),
            ),
        )

    def get_store_metadata(self) -> dict[str, Any] | None:
        """Return the singleton store metadata row, or None if not set."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT store_id, project_hint, git_root, scope_kind, "
                "schema_version, created_at "
                "FROM store_metadata WHERE id = 1"
            ).fetchone()
            if row is None:
                return None
            return {
                "store_id": row["store_id"],
                "project_hint": row["project_hint"],
                "git_root": row["git_root"],
                "scope_kind": row["scope_kind"],
                "schema_version": row["schema_version"],
                "created_at": row["created_at"],
            }

    def migrate_schema(self) -> dict[str, Any]:
        """Update CHECK constraints on existing tables to match current schema.

        SQLite's CREATE TABLE IF NOT EXISTS does not update CHECK constraints
        on tables that already exist. When new enum values are added (new
        memory kinds, link relations, etc.), existing databases need their
        sqlite_master entries patched in place. This is the documented
        SQLite pattern for altering constraints without rebuilding tables.

        Returns a dict describing what was changed.
        """
        schema_path = Path(__file__).with_name("schema.sql")
        schema_sql = schema_path.read_text(encoding="utf-8")

        # Parse out the CREATE TABLE statements we want to patch.
        # We only patch tables whose CHECK constraints we extend over time.
        targets = ("memory_objects", "memory_links", "receipts")
        new_defs: dict[str, str] = {}
        for table in targets:
            stmt = _extract_create_table(schema_sql, table)
            if stmt is None:
                raise RuntimeError(
                    f"could not find CREATE TABLE {table} in schema.sql"
                )
            new_defs[table] = stmt

        # Triggers that the current schema no longer creates but older
        # databases may still carry. Dropping is idempotent.
        triggers_to_drop = ("trg_memory_objects_updated_at",)

        changed: list[str] = []
        dropped_triggers: list[str] = []
        with self._connect() as conn:
            for table, new_sql in new_defs.items():
                row = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE name = ? AND type = 'table'",
                    (table,),
                ).fetchone()
                if row is None:
                    continue
                old_sql = row["sql"]
                if old_sql.strip() == new_sql.strip():
                    continue
                # Use writable_schema to patch the constraint definition.
                conn.execute("PRAGMA writable_schema = ON")
                conn.execute(
                    "UPDATE sqlite_master SET sql = ? WHERE name = ? AND type = 'table'",
                    (new_sql, table),
                )
                conn.execute("PRAGMA writable_schema = OFF")
                changed.append(table)

            for trig in triggers_to_drop:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                    (trig,),
                ).fetchone()
                if row is not None:
                    conn.execute(f"DROP TRIGGER IF EXISTS {trig}")
                    dropped_triggers.append(trig)

            # Verify integrity after patching.
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

        return {
            "changed_tables": changed,
            "dropped_triggers": dropped_triggers,
            "integrity_check": integrity,
        }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def get_memory(self, memory_id: str) -> MemoryObject:
        with self._connect() as conn:
            return self._get_memory(conn, memory_id)

    def latest_memory(
        self,
        scope: str,
        kind: MemoryKind | str,
        *,
        status: MemoryStatus | str | None = MemoryStatus.COMMITTED,
    ) -> MemoryObject | None:
        """Return the most recently updated memory in (scope, kind), if any.

        Default filters to committed only — the typical "what is the
        current blessed value of this kind in this scope" query. Pass
        status=None to consider any status. Returns None if no match.

        This is the read side of the supersede convention: when you want
        to write a new project_state, you call latest_memory first to get
        the prior, then observe the new one with supersedes=prior.id, then
        commit. Both old and new remain committed; lineage is preserved
        through the supersedes pointer; the latest_memory call surfaces
        the chain head.
        """
        sql = (
            "SELECT * FROM memory_objects "
            "WHERE scope = ? AND kind = ? "
        )
        params: list[Any] = [scope, str(kind)]
        if status is not None:
            sql += "AND status = ? "
            params.append(str(status))
        sql += "ORDER BY updated_at DESC, created_at DESC LIMIT 1"

        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
            if row is None:
                return None
            return self._row_to_memory_object(row)

    def query_memory(
        self,
        req: QueryMemoryRequest,
        *,
        evaluation_time: datetime | None = None,
    ) -> QueryMemoryResponse:
        # Boundary default: resolve evaluation_time once at the entry; flow
        # explicitly into the expiration filter. The kernel does not call
        # the clock (see docs/gaps/CONTINUITY_TIME_DISCIPLINE.md).
        if evaluation_time is None:
            evaluation_time = utcnow()
        where: list[str] = []
        params: list[Any] = []

        if req.scope is not None:
            where.append("scope = ?")
            params.append(req.scope)
        if req.kind is not None:
            where.append("kind = ?")
            params.append(str(req.kind))
        if req.status is not None:
            where.append("status = ?")
            params.append(str(req.status))
        if req.basis is not None:
            where.append("basis = ?")
            params.append(str(req.basis))
        if req.reliance_class is not None:
            where.append("reliance_class = ?")
            params.append(str(req.reliance_class))
        if not req.include_expired:
            where.append(
                "(expires_at IS NULL OR expires_at > ?)"
            )
            params.append(to_isoformat(evaluation_time))

        where_sql = ""
        if where:
            where_sql = "WHERE " + " AND ".join(where)

        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS count FROM memory_objects {where_sql}",
                params,
            ).fetchone()["count"]

            rows = conn.execute(
                f"""
                SELECT * FROM memory_objects {where_sql}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                [*params, req.limit, req.offset],
            ).fetchall()

        return QueryMemoryResponse(
            items=[self._row_to_memory_object(r) for r in rows],
            total=total,
        )

    def get_case(
        self,
        req: GetCaseRequest,
        *,
        evaluation_time: datetime | None = None,
    ) -> CaseBundle:
        """Return a derived case bundle for a scope.

        Cases are not persisted; they are computed on demand by bucketing
        all memories in the scope by kind and pairing each with its rely
        state. Revoked items are included so the case preserves the
        ruled-out branches that were part of the investigation.
        """
        if evaluation_time is None:
            evaluation_time = utcnow()
        with self._connect() as conn:
            params: list[Any] = [req.scope]
            sql = "SELECT * FROM memory_objects WHERE scope = ?"
            if not req.include_expired:
                sql += " AND (expires_at IS NULL OR expires_at > ?)"
                params.append(to_isoformat(evaluation_time))
            sql += " ORDER BY created_at ASC, memory_id ASC"

            rows = conn.execute(sql, params).fetchall()
            memories = [self._row_to_memory_object(r) for r in rows]

            items: list[CaseItem] = []
            for m in memories:
                rs = self._compute_rely_state(conn, m, evaluation_time)
                items.append(CaseItem(
                    memory=m,
                    rely_ok=rs.rely_ok,
                    rely_reason=rs.message,
                    rely_state=rs,
                ))

        bundle = CaseBundle(scope=req.scope, total_memories=len(items))

        for item in items:
            kind = item.memory.kind
            if kind == MemoryKind.SUMMARY:
                # Pick the most recently updated committed summary as the
                # bundle summary; fall back to the most recent of any status.
                if (
                    bundle.summary is None
                    or _summary_priority(item) > _summary_priority(bundle.summary)
                ):
                    bundle.summary = item
            elif kind == MemoryKind.FACT:
                bundle.facts.append(item)
            elif kind == MemoryKind.HYPOTHESIS:
                bundle.hypotheses.append(item)
            elif kind == MemoryKind.EXPERIMENT:
                bundle.experiments.append(item)
            elif kind == MemoryKind.LESSON:
                bundle.lessons.append(item)
            elif kind == MemoryKind.DECISION:
                bundle.decisions.append(item)
            elif kind == MemoryKind.CONSTRAINT:
                bundle.constraints.append(item)
            elif kind == MemoryKind.NOTE:
                bundle.notes.append(item)
            elif kind == MemoryKind.PROJECT_STATE:
                bundle.project_states.append(item)
            elif kind == MemoryKind.NEXT_ACTION:
                bundle.next_actions.append(item)
            else:
                bundle.other.append(item)

        if bundle.summary is not None:
            title = bundle.summary.memory.content.get("title")
            if isinstance(title, str):
                bundle.title = title

        if items:
            bundle.last_touch = max(m.memory.updated_at for m in items)

        return bundle

    def verify_reliance(
        self, req: VerifyRelianceRequest,
    ) -> VerifyRelianceResponse:
        """Walk each relied_on entry against the local store and label drift.

        Local-only by design (per docs/gaps/CROSS_COMPONENT_RELIANCE_GAP.md
        keeper: explain may describe imported reliance locally; refresh may
        test source reachability; do not merge them). No network call to
        source stores. Each entry receives one terminal status.

        Aggregate `verified` is True only if every entry is `match`.
        """
        out: list[ReliedOnVerification] = []
        summary: dict[str, int] = {}
        with self._connect() as conn:
            for entry in req.entries:
                verification = self._verify_one(conn, entry)
                out.append(verification)
                summary[verification.status] = summary.get(verification.status, 0) + 1
        verified = all(v.status == "match" for v in out) and len(out) > 0
        return VerifyRelianceResponse(
            verified=verified, entries=out, summary=summary,
        )

    def _verify_one(
        self,
        conn: sqlite3.Connection,
        entry: ReliedOnEntry,
    ) -> ReliedOnVerification:
        memory = self._maybe_get_memory(conn, entry.memory_id)
        if memory is None:
            return ReliedOnVerification(
                entry=entry,
                status="missing",
                detail=(
                    f"no memory with id {entry.memory_id} in local store"
                ),
            )

        current_hash = content_hash(memory)

        # mode_mismatch — claimed local_import but no import receipt exists.
        # We check this before content_drift so the operator sees the
        # provenance error first; a forged "imported" claim is more
        # actionable than the content question that follows.
        if entry.verification_mode == "local_import":
            import_event = self._latest_event_for_memory(
                conn, entry.memory_id, EventType.IMPORT,
            )
            if import_event is None:
                return ReliedOnVerification(
                    entry=entry,
                    status="mode_mismatch",
                    current_content_hash=current_hash,
                    current_status=str(memory.status),
                    detail=(
                        "receipt claims verification_mode=local_import but "
                        "no memory.import event exists locally for this "
                        "memory_id"
                    ),
                )

        if entry.content_hash != current_hash:
            return ReliedOnVerification(
                entry=entry,
                status="content_drift",
                current_content_hash=current_hash,
                current_status=str(memory.status),
                detail=(
                    f"pinned content_hash differs from current local hash"
                ),
            )

        # Hash matches; check state.
        if str(memory.status) == "revoked":
            return ReliedOnVerification(
                entry=entry,
                status="revoked_after",
                current_content_hash=current_hash,
                current_status="revoked",
                detail="memory was revoked after this citation was recorded",
            )

        if memory.expires_at is not None:
            eval_iso = to_isoformat(entry.evaluation_time)
            exp_iso = to_isoformat(memory.expires_at)
            if exp_iso and eval_iso and eval_iso >= exp_iso:
                return ReliedOnVerification(
                    entry=entry,
                    status="expired_after",
                    current_content_hash=current_hash,
                    current_status=str(memory.status),
                    detail=(
                        f"memory expired at {exp_iso}; "
                        f"evaluation_time was {eval_iso}"
                    ),
                )

        return ReliedOnVerification(
            entry=entry,
            status="match",
            current_content_hash=current_hash,
            current_status=str(memory.status),
        )

    def explain_memory(
        self,
        memory_id: str,
        *,
        evaluation_time: datetime | None = None,
    ) -> ExplainMemoryResponse:
        if evaluation_time is None:
            evaluation_time = utcnow()
        with self._connect() as conn:
            memory = self._get_memory(conn, memory_id)

            event_rows = conn.execute(
                """
                SELECT * FROM memory_events
                WHERE memory_id = ?
                ORDER BY created_at ASC, event_id ASC
                """,
                (memory_id,),
            ).fetchall()

            receipt_ids = [r["receipt_id"] for r in event_rows]
            receipt_rows: list[sqlite3.Row] = []
            if receipt_ids:
                ph = ",".join("?" for _ in receipt_ids)
                receipt_rows = conn.execute(
                    f"""
                    SELECT * FROM receipts
                    WHERE receipt_id IN ({ph})
                    ORDER BY created_at ASC, receipt_id ASC
                    """,
                    receipt_ids,
                ).fetchall()

            premises = self._load_premises(conn, memory_id)
            dependents = self._load_dependents(conn, memory_id)
            rs = self._compute_rely_state(conn, memory, evaluation_time)
            imported = self._imported_premise_statuses(
                conn, premises, evaluation_time,
            )

        return ExplainMemoryResponse(
            memory=memory,
            events=[self._row_to_memory_event(r) for r in event_rows],
            receipts=[self._row_to_receipt(r) for r in receipt_rows],
            premises=premises,
            dependents=dependents,
            rely_ok=rs.rely_ok,
            rely_reason=rs.message,
            rely_state=rs,
            evaluation_time=evaluation_time,
            imported_premises=imported,
        )

    def _imported_premise_statuses(
        self,
        conn: sqlite3.Connection,
        premises: list[MemoryLink],
        evaluation_time: datetime,
    ) -> list[ImportedPremiseStatus]:
        """Compute per-premise drift for premises targeting imported memories.

        Local-only: no network call to source store. Drift surfaces against
        the pin recorded at reliance time vs. the current local content_hash.
        State reflects the local imported memory's current status (and
        expiration at evaluation_time).
        """
        out: list[ImportedPremiseStatus] = []
        for link in premises:
            if link.src_memory_id is None:
                continue
            src = self._maybe_get_memory(conn, link.src_memory_id)
            if src is None:
                # FK should prevent this; defensive skip if it happens.
                continue
            # Only annotate premises whose target is an imported memory
            # OR whose link carries a pin (operator opted into pinning).
            if str(src.basis) != "import" and link.pinned_content_hash is None:
                continue

            current_hash = content_hash(src)
            if link.pinned_content_hash is None:
                content_status = "unpinned"
            elif link.pinned_content_hash == current_hash:
                content_status = "match"
            else:
                content_status = "drift"

            # State: committed/observed/revoked, plus expired if past
            # evaluation_time. Expired takes precedence over committed.
            state = str(src.status)
            if (
                state == "committed"
                and src.expires_at is not None
            ):
                eval_iso = to_isoformat(evaluation_time)
                exp_iso = to_isoformat(src.expires_at)
                if exp_iso and eval_iso and eval_iso >= exp_iso:
                    state = "expired"

            # Provenance: the import receipt for this memory (most recent
            # import event). Best-effort — passthrough only.
            import_event = self._latest_event_for_memory(
                conn, src.memory_id, EventType.IMPORT,
            )
            source_store_id: str | None = None
            imported_at: datetime | None = None
            if import_event is not None:
                try:
                    receipt = self._get_receipt(conn, import_event.receipt_id)
                    source_store_id = receipt.content.get("source_store_id")
                    imported_at = receipt.created_at
                except RuntimeError:
                    pass

            out.append(ImportedPremiseStatus(
                link_id=link.link_id,
                src_memory_id=src.memory_id,
                pinned_content_hash=link.pinned_content_hash,
                current_content_hash=current_hash,
                content_status=content_status,
                state=state,
                source_store_id=source_store_id,
                imported_at=imported_at,
            ))
        return out

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    def observe_memory(self, req: ObserveMemoryRequest) -> ObserveMemoryResponse:
        with self._tx() as conn:
            if req.idempotency_key:
                existing = self._load_idempotent_response(
                    conn, req.idempotency_key, EventType.OBSERVE,
                )
                if existing is not None:
                    mem, evt, rcpt = existing
                    links = self._load_premises(conn, mem.memory_id, include_revoked=False)
                    return ObserveMemoryResponse(
                        memory=mem, event=evt, receipt=rcpt, links=links,
                    )

            self._check_island_safety(conn, req.scope)

            decision = self.policy.allow_observe(req)
            if not decision.allowed:
                self._emit_refusal_and_raise(
                    conn,
                    intended_event=EventType.OBSERVE,
                    decision=decision,
                    request_payload=req.model_dump(mode="json"),
                    actor=req.actor,
                    standing=req.standing,
                )

            memory = MemoryObject(
                scope=req.scope,
                kind=req.kind,
                basis=req.basis,
                status=MemoryStatus.OBSERVED,
                reliance_class=RelianceClass.NONE,
                confidence=req.confidence,
                content=req.content,
                source_refs=req.source_refs,
                expires_at=req.expires_at,
                supersedes=req.supersedes,
                created_by=req.actor,
            )

            receipt_content = self._observe_receipt_content(memory, req)
            receipt = self._build_receipt(
                conn, ReceiptType.MEMORY_OBSERVE, receipt_content,
            )

            event = MemoryEvent(
                memory_id=memory.memory_id,
                event_type=EventType.OBSERVE,
                actor=req.actor,
                standing=req.standing,
                receipt_id=receipt.receipt_id,
                payload={
                    "status": memory.status,
                    "content": memory.content,
                    "source_refs": [s.model_dump(mode="json") for s in memory.source_refs],
                    "confidence": memory.confidence,
                },
                idempotency_key=req.idempotency_key,
            )

            self._insert_memory_object(conn, memory)
            self._insert_receipt(conn, receipt)
            self._insert_memory_event(conn, event)

            links = self._insert_memory_links(
                conn,
                dst_memory_id=memory.memory_id,
                premises=req.premises,
                created_by_event_id=event.event_id,
            )

            return ObserveMemoryResponse(
                memory=memory, event=event, receipt=receipt, links=links,
            )

    def commit_memory(self, req: CommitMemoryRequest) -> CommitMemoryResponse:
        with self._tx() as conn:
            if req.idempotency_key:
                existing = self._load_idempotent_response(
                    conn, req.idempotency_key, EventType.COMMIT,
                )
                if existing is not None:
                    mem, evt, rcpt = existing
                    links = self._load_premises(conn, mem.memory_id, include_revoked=False)
                    return CommitMemoryResponse(
                        memory=mem, event=evt, receipt=rcpt, links=links,
                    )

            decision = self.policy.allow_commit(req)
            if not decision.allowed:
                self._emit_refusal_and_raise(
                    conn,
                    intended_event=EventType.COMMIT,
                    decision=decision,
                    request_payload=req.model_dump(mode="json"),
                    actor=req.approved_by,
                    standing=req.standing,
                )

            memory = self._get_memory(conn, req.memory_id)

            if memory.status == MemoryStatus.REVOKED:
                raise InvalidTransitionError(
                    f"cannot commit revoked memory {memory.memory_id}"
                )

            prior_status = memory.status
            memory.status = MemoryStatus.COMMITTED
            memory.reliance_class = req.reliance_class
            memory.approved_by = req.approved_by
            if req.supersedes is not None:
                memory.supersedes = req.supersedes
            if req.expires_at is not None:
                memory.expires_at = req.expires_at

            receipt_content = {
                "memory_id": memory.memory_id,
                "prior_status": prior_status,
                "new_status": memory.status,
                "reliance_class": memory.reliance_class,
                "approved_by": (
                    memory.approved_by.model_dump(mode="json")
                    if memory.approved_by else None
                ),
                "standing": (
                    req.standing.model_dump(mode="json")
                    if req.standing else None
                ),
                "supersedes": memory.supersedes,
                "expires_at": to_isoformat(memory.expires_at),
                "note": req.note,
                "premises": [
                    p.model_dump(mode="json") for p in req.premises
                ],
            }

            receipt = self._build_receipt(
                conn, ReceiptType.MEMORY_COMMIT, receipt_content,
            )

            event = MemoryEvent(
                memory_id=memory.memory_id,
                event_type=EventType.COMMIT,
                actor=req.approved_by,
                standing=req.standing,
                receipt_id=receipt.receipt_id,
                payload={
                    "prior_status": prior_status,
                    "new_status": memory.status,
                    "reliance_class": memory.reliance_class,
                    "supersedes": memory.supersedes,
                    "expires_at": to_isoformat(memory.expires_at),
                    "note": req.note,
                },
                idempotency_key=req.idempotency_key,
            )

            self._update_memory_object(conn, memory)
            self._insert_receipt(conn, receipt)
            self._insert_memory_event(conn, event)

            # Append — does not replace observe-time premises
            links = self._insert_memory_links(
                conn,
                dst_memory_id=memory.memory_id,
                premises=req.premises,
                created_by_event_id=event.event_id,
            )

            return CommitMemoryResponse(
                memory=memory, event=event, receipt=receipt, links=links,
            )

    def repair_memory(self, req: RepairMemoryRequest) -> RepairMemoryResponse:
        """Apply a narrow patch to a memory's recorded content/metadata.

        Repair is intentionally restricted (see RepairMemoryRequest doc):
        only `content`, `source_refs`, and `confidence` may be patched.
        Fields that affect rely semantics use observe/commit/revoke/supersede.

        The repair leaves a memory.repair event and a hash-chained receipt
        carrying the patch payload, the prior values of patched fields, and
        the operator's reason. Status, reliance_class, expiration, and
        premises are untouched — downstream rely_ok is preserved.
        """
        with self._tx() as conn:
            if req.idempotency_key:
                existing = self._load_idempotent_response(
                    conn, req.idempotency_key, EventType.REPAIR,
                )
                if existing is not None:
                    mem, evt, rcpt = existing
                    return RepairMemoryResponse(
                        memory=mem, event=evt, receipt=rcpt,
                    )

            decision = self.policy.allow_repair(req)
            if not decision.allowed:
                self._emit_refusal_and_raise(
                    conn,
                    intended_event=EventType.REPAIR,
                    decision=decision,
                    request_payload=req.model_dump(mode="json"),
                    actor=req.actor,
                    standing=req.standing,
                )

            memory = self._get_memory(conn, req.memory_id)

            if memory.status == MemoryStatus.REVOKED:
                raise InvalidTransitionError(
                    f"cannot repair revoked memory {memory.memory_id}"
                )

            # Capture prior values for the patched fields so the receipt
            # records what changed, not just what was newly set.
            prior: dict[str, Any] = {}
            if "content" in req.patch:
                prior["content"] = memory.content
                memory.content = req.patch["content"]
            if "source_refs" in req.patch:
                prior["source_refs"] = [
                    s.model_dump(mode="json") for s in memory.source_refs
                ]
                memory.source_refs = [
                    SourceRef.model_validate(s) for s in req.patch["source_refs"]
                ]
            if "confidence" in req.patch:
                prior["confidence"] = memory.confidence
                memory.confidence = float(req.patch["confidence"])

            receipt_content = {
                "memory_id": memory.memory_id,
                "reason": req.reason,
                "patch": req.patch,
                "prior": prior,
                "target_event_id": req.target_event_id,
                "target_receipt_id": req.target_receipt_id,
                "actor": (
                    req.actor.model_dump(mode="json") if req.actor else None
                ),
                "standing": (
                    req.standing.model_dump(mode="json")
                    if req.standing else None
                ),
            }

            receipt = self._build_receipt(
                conn, ReceiptType.MEMORY_REPAIR, receipt_content,
            )

            event = MemoryEvent(
                memory_id=memory.memory_id,
                event_type=EventType.REPAIR,
                actor=req.actor,
                standing=req.standing,
                receipt_id=receipt.receipt_id,
                payload={
                    "reason": req.reason,
                    "patch": req.patch,
                    "prior": prior,
                },
                idempotency_key=req.idempotency_key,
            )

            self._update_memory_object(conn, memory)
            self._insert_receipt(conn, receipt)
            self._insert_memory_event(conn, event)

            return RepairMemoryResponse(
                memory=memory, event=event, receipt=receipt,
            )

    def revoke_memory(self, req: RevokeMemoryRequest) -> RevokeMemoryResponse:
        with self._tx() as conn:
            if req.idempotency_key:
                existing = self._load_idempotent_response(
                    conn, req.idempotency_key, EventType.REVOKE,
                )
                if existing is not None:
                    mem, evt, rcpt = existing
                    return RevokeMemoryResponse(
                        memory=mem, event=evt, receipt=rcpt,
                    )

            memory = self._get_memory(conn, req.memory_id)

            if memory.status == MemoryStatus.REVOKED:
                raise InvalidTransitionError(
                    f"memory {memory.memory_id} is already revoked"
                )

            prior_status = memory.status
            memory.status = MemoryStatus.REVOKED
            memory.revoked_by = req.replacement_memory_id

            receipt_content = {
                "memory_id": memory.memory_id,
                "prior_status": prior_status,
                "reason": req.reason,
                "revoked_by": (
                    req.revoked_by.model_dump(mode="json")
                    if req.revoked_by else None
                ),
                "standing": (
                    req.standing.model_dump(mode="json")
                    if req.standing else None
                ),
                "replacement_memory_id": req.replacement_memory_id,
            }

            receipt = self._build_receipt(
                conn, ReceiptType.MEMORY_REVOKE, receipt_content,
            )

            event = MemoryEvent(
                memory_id=memory.memory_id,
                event_type=EventType.REVOKE,
                actor=req.revoked_by,
                standing=req.standing,
                receipt_id=receipt.receipt_id,
                payload={
                    "prior_status": prior_status,
                    "reason": req.reason,
                    "replacement_memory_id": req.replacement_memory_id,
                },
                idempotency_key=req.idempotency_key,
            )

            self._update_memory_object(conn, memory)
            self._insert_receipt(conn, receipt)
            self._insert_memory_event(conn, event)

            # Links stay active — explain/rely reads the taint from source status

            return RevokeMemoryResponse(
                memory=memory, event=event, receipt=receipt,
            )

    def import_memory(self, req: ImportMemoryRequest) -> ImportMemoryResponse:
        """Pull a memory from a source store into the local store.

        Verifies `expected_content_hash` against the recomputed hash over
        the supplied portable payload (`memory_id`, scope, kind, content,
        reliance_class, supersedes). Refuses on mismatch.

        Idempotency: if the memory already exists locally at the same
        content_hash, returns the existing row + the original import
        receipt and event; no new audit artifact is emitted (already_imported=True).
        If the memory exists at a *different* content_hash, raises
        ContentHashMismatchError — V1 does not silently overwrite or fork.
        See docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md invariants 4-6 and
        explicit deferrals.

        Writes:
          - memory_objects row (if first-time import)
          - memory_events row of type 'import'
          - receipts row of type 'memory.import'
          - spool_imports row marking the import as 'applied'
        """
        # Build the candidate memory object from the portable payload.
        # basis is forced to IMPORT for imported memories — the basis on
        # the source store may differ, but locally this is an import.
        candidate = MemoryObject(
            memory_id=req.memory_id,
            scope=req.scope,
            kind=req.kind,
            basis=Basis.IMPORT,
            status=req.status,
            reliance_class=req.reliance_class,
            confidence=req.confidence,
            content=req.content,
            source_refs=req.source_refs,
            expires_at=req.expires_at,
            supersedes=req.supersedes,
            created_by=req.actor,
        )
        # IMPORTANT: content_hash is computed over the portable subset
        # which uses memory.basis only implicitly (it's not in the hash).
        # We use a temporary copy with the source's reliance/scope/etc to
        # produce the canonical hash, then verify against expected.
        actual_hash = content_hash(candidate)
        if actual_hash != req.expected_content_hash:
            raise ContentHashMismatchError(
                memory_id=req.memory_id,
                expected=req.expected_content_hash,
                actual=actual_hash,
                reason="payload hash differs from expected_content_hash",
            )

        with self._tx() as conn:
            # Idempotency by explicit key — short-circuit identical replays.
            if req.idempotency_key:
                existing = self._load_idempotent_response(
                    conn, req.idempotency_key, EventType.IMPORT,
                )
                if existing is not None:
                    mem, evt, rcpt = existing
                    spool_id = self._latest_spool_id_for_memory(
                        conn, mem.memory_id, req.source_store_id,
                    )
                    return ImportMemoryResponse(
                        memory=mem, event=evt, receipt=rcpt,
                        spool_import_id=spool_id or "",
                        already_imported=True,
                    )

            # Idempotency by (memory_id, content_hash) — second import of
            # the same memory at the same version is a no-op.
            existing_local = self._maybe_get_memory(conn, req.memory_id)
            if existing_local is not None:
                existing_hash = content_hash(existing_local)
                if existing_hash != actual_hash:
                    raise ContentHashMismatchError(
                        memory_id=req.memory_id,
                        expected=actual_hash,
                        actual=existing_hash,
                        reason=(
                            "memory already exists locally at a different "
                            "content_hash; V1 refuses silent overwrite. "
                            "Revoke + re-import, or import a supersede "
                            "successor under a new memory_id."
                        ),
                    )
                # Same content — return the prior import event/receipt as
                # the idempotent response.
                prior_event = self._latest_event_for_memory(
                    conn, req.memory_id, EventType.IMPORT,
                )
                if prior_event is not None:
                    prior_receipt = self._get_receipt(conn, prior_event.receipt_id)
                    spool_id = self._latest_spool_id_for_memory(
                        conn, req.memory_id, req.source_store_id,
                    )
                    return ImportMemoryResponse(
                        memory=existing_local,
                        event=prior_event,
                        receipt=prior_receipt,
                        spool_import_id=spool_id or "",
                        already_imported=True,
                    )
                # Exists but never imported (locally-authored row at the
                # same memory_id — defensive refusal: don't smuggle it
                # into the import audit trail).
                raise ContentHashMismatchError(
                    memory_id=req.memory_id,
                    expected=actual_hash,
                    actual=existing_hash,
                    reason=(
                        "memory_id already exists locally but was not "
                        "imported; refusing to retroactively label a "
                        "locally-authored memory as imported."
                    ),
                )

            # Island check: imports of cross-project-shaped scopes follow
            # the same topology rules as observe.
            self._check_island_safety(conn, req.scope)

            # Build the import receipt and event, then insert atomically.
            spool_id = new_id("imp")
            receipt_content = {
                "memory_id": candidate.memory_id,
                "source_store_id": req.source_store_id,
                "source_ref": req.source_ref,
                "imported_content_hash": actual_hash,
                "scope": candidate.scope,
                "kind": str(candidate.kind),
                "actor": (
                    req.actor.model_dump(mode="json") if req.actor else None
                ),
                "standing": (
                    req.standing.model_dump(mode="json")
                    if req.standing else None
                ),
            }
            receipt = self._build_receipt(
                conn, ReceiptType.MEMORY_IMPORT, receipt_content,
            )

            event = MemoryEvent(
                memory_id=candidate.memory_id,
                event_type=EventType.IMPORT,
                actor=req.actor,
                standing=req.standing,
                receipt_id=receipt.receipt_id,
                payload={
                    "source_store_id": req.source_store_id,
                    "source_ref": req.source_ref,
                    "imported_content_hash": actual_hash,
                    "spool_import_id": spool_id,
                },
                idempotency_key=req.idempotency_key,
            )

            self._insert_memory_object(conn, candidate)
            self._insert_receipt(conn, receipt)
            self._insert_memory_event(conn, event)
            self._insert_spool_import(
                conn,
                spool_id=spool_id,
                source=req.source_store_id,
                external_ref=req.source_ref or candidate.memory_id,
                status="applied",
            )

            return ImportMemoryResponse(
                memory=candidate,
                event=event,
                receipt=receipt,
                spool_import_id=spool_id,
                already_imported=False,
            )

    # ------------------------------------------------------------------
    # Memory links
    # ------------------------------------------------------------------

    def _insert_memory_links(
        self,
        conn: sqlite3.Connection,
        *,
        dst_memory_id: str,
        premises: list[PremiseRef],
        created_by_event_id: str,
    ) -> list[MemoryLink]:
        links: list[MemoryLink] = []
        for premise in premises:
            link = MemoryLink(
                dst_memory_id=dst_memory_id,
                src_memory_id=premise.memory_id,
                src_receipt_id=premise.receipt_id,
                src_ref=premise.source_ref,
                relation=premise.relation,
                strength=premise.strength,
                status=LinkStatus.ACTIVE,
                note=premise.note,
                pinned_content_hash=premise.pinned_content_hash,
                created_by_event_id=created_by_event_id,
            )
            conn.execute(
                """
                INSERT INTO memory_links (
                    link_id, dst_memory_id,
                    src_memory_id, src_receipt_id, src_ref_json,
                    relation, strength, status, note,
                    created_at, created_by_event_id,
                    revoked_at, revoked_by_event_id,
                    pinned_content_hash
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    link.link_id,
                    link.dst_memory_id,
                    link.src_memory_id,
                    link.src_receipt_id,
                    _to_json(link.src_ref.model_dump(mode="json")) if link.src_ref else None,
                    str(link.relation),
                    str(link.strength),
                    str(link.status),
                    link.note,
                    to_isoformat(link.created_at),
                    link.created_by_event_id,
                    to_isoformat(link.revoked_at),
                    link.revoked_by_event_id,
                    link.pinned_content_hash,
                ),
            )
            links.append(link)
        return links

    def _load_premises(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        *,
        include_revoked: bool = True,
    ) -> list[MemoryLink]:
        sql = "SELECT * FROM memory_links WHERE dst_memory_id = ?"
        params: list[Any] = [memory_id]
        if not include_revoked:
            sql += " AND status = 'active'"
        sql += " ORDER BY created_at ASC, link_id ASC"
        return [self._row_to_memory_link(r) for r in conn.execute(sql, params).fetchall()]

    def _load_dependents(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        *,
        include_revoked: bool = True,
    ) -> list[MemoryLink]:
        sql = "SELECT * FROM memory_links WHERE src_memory_id = ?"
        params: list[Any] = [memory_id]
        if not include_revoked:
            sql += " AND status = 'active'"
        sql += " ORDER BY created_at ASC, link_id ASC"
        return [self._row_to_memory_link(r) for r in conn.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------
    # Rely computation
    # ------------------------------------------------------------------

    def _compute_rely_state(
        self,
        conn: sqlite3.Connection,
        memory: MemoryObject,
        evaluation_time: datetime,
    ) -> RelyState:
        # evaluation_time is required — the kernel never reads the wall clock.
        # The boundary (explain/query/case) resolves the default via utcnow()
        # exactly once and flows it down explicitly so historical rely is
        # reconstructible (per docs/gaps/CONTINUITY_TIME_DISCIPLINE.md).
        #
        # Each branch returns a RelyState: a machine code, typed details, and a
        # rendered message. The message strings are held identical to their
        # pre-structuring form on purpose — flat rely_reason consumers must see
        # the same text (per USEFUL_REFUSAL_EXPLAIN invariant 5).
        if memory.status != MemoryStatus.COMMITTED:
            return RelyState(
                rely_ok=False,
                code=RelyReasonCode.STATUS_NOT_COMMITTED,
                message=f"memory status is {memory.status}, not committed",
                details={"status": str(memory.status)},
            )

        if memory.expires_at is not None:
            eval_iso = to_isoformat(evaluation_time)
            exp_iso = to_isoformat(memory.expires_at)
            if exp_iso and eval_iso and eval_iso >= exp_iso:
                return RelyState(
                    rely_ok=False,
                    code=RelyReasonCode.EXPIRED,
                    message="memory is expired",
                    details={"expires_at": exp_iso, "evaluation_time": eval_iso},
                )

        if memory.reliance_class == RelianceClass.NONE:
            return RelyState(
                rely_ok=False,
                code=RelyReasonCode.RELIANCE_NONE,
                message="reliance_class=none",
                details={"reliance_class": str(memory.reliance_class)},
            )

        if (
            memory.kind in {MemoryKind.SUMMARY, MemoryKind.HYPOTHESIS}
            and memory.reliance_class == RelianceClass.ACTIONABLE
        ):
            return RelyState(
                rely_ok=False,
                code=RelyReasonCode.KIND_BASIS_POLICY,
                message=f"{memory.kind} cannot be actionable by default",
                details={
                    "kind": str(memory.kind),
                    "requested_class": str(memory.reliance_class),
                },
            )

        if (
            memory.basis in {Basis.INFERENCE, Basis.SYNTHESIS}
            and memory.reliance_class == RelianceClass.ACTIONABLE
        ):
            return RelyState(
                rely_ok=False,
                code=RelyReasonCode.KIND_BASIS_POLICY,
                message=f"basis={memory.basis} cannot be actionable by default",
                details={
                    "basis": str(memory.basis),
                    "requested_class": str(memory.reliance_class),
                },
            )

        # Check hard premises
        hard_rows = conn.execute(
            """
            SELECT ml.src_memory_id, mo.status AS src_status
            FROM memory_links AS ml
            LEFT JOIN memory_objects AS mo ON mo.memory_id = ml.src_memory_id
            WHERE ml.dst_memory_id = ?
              AND ml.status = 'active'
              AND ml.strength = 'hard'
              AND ml.src_memory_id IS NOT NULL
            """,
            (memory.memory_id,),
        ).fetchall()

        bad: list[str] = []
        for row in hard_rows:
            src_id = row["src_memory_id"]
            src_status = row["src_status"]
            if src_status is None:
                bad.append(f"{src_id}:missing")
            elif src_status == MemoryStatus.REVOKED:
                bad.append(f"{src_id}:revoked")

        if bad:
            return RelyState(
                rely_ok=False,
                code=RelyReasonCode.HARD_PREMISE_UNAVAILABLE,
                message=f"hard premises unavailable: {', '.join(bad)}",
                details={"bad_premises": bad},
            )

        return RelyState(
            rely_ok=True,
            code=RelyReasonCode.ELIGIBLE,
            message=f"eligible for reliance at class {memory.reliance_class}",
            details={"reliance_class": str(memory.reliance_class)},
        )

    # ------------------------------------------------------------------
    # Internal DB helpers
    # ------------------------------------------------------------------

    def _get_memory(self, conn: sqlite3.Connection, memory_id: str) -> MemoryObject:
        row = conn.execute(
            "SELECT * FROM memory_objects WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            raise MemoryNotFoundError(memory_id)
        return self._row_to_memory_object(row)

    def _maybe_get_memory(
        self, conn: sqlite3.Connection, memory_id: str,
    ) -> MemoryObject | None:
        row = conn.execute(
            "SELECT * FROM memory_objects WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_memory_object(row)

    def _latest_event_for_memory(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        event_type: EventType,
    ) -> MemoryEvent | None:
        row = conn.execute(
            "SELECT * FROM memory_events "
            "WHERE memory_id = ? AND event_type = ? "
            "ORDER BY created_at DESC, event_id DESC LIMIT 1",
            (memory_id, str(event_type)),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_memory_event(row)

    def _get_receipt(
        self, conn: sqlite3.Connection, receipt_id: str,
    ) -> ReceiptRecord:
        row = conn.execute(
            "SELECT * FROM receipts WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"receipt {receipt_id} not found")
        return self._row_to_receipt(row)

    def _latest_spool_id_for_memory(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        source_store_id: str,
    ) -> str | None:
        """Find the most recent spool_import row for (source, memory_id)."""
        row = conn.execute(
            "SELECT import_id FROM spool_imports "
            "WHERE source = ? AND external_ref = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (source_store_id, memory_id),
        ).fetchone()
        return row["import_id"] if row else None

    def _insert_spool_import(
        self,
        conn: sqlite3.Connection,
        *,
        spool_id: str,
        source: str,
        external_ref: str,
        status: str,
    ) -> None:
        conn.execute(
            "INSERT INTO spool_imports "
            "(import_id, source, external_ref, status, reason, "
            " created_at, applied_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                spool_id,
                source,
                external_ref,
                status,
                None,
                isoformat_now(),
                isoformat_now() if status == "applied" else None,
            ),
        )

    def _insert_memory_object(self, conn: sqlite3.Connection, m: MemoryObject) -> None:
        conn.execute(
            """
            INSERT INTO memory_objects (
                memory_id, scope, kind, basis, status, reliance_class,
                confidence, content_json, source_refs_json,
                created_at, updated_at, expires_at,
                supersedes, revoked_by,
                created_by_json, approved_by_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                m.memory_id, m.scope, str(m.kind), str(m.basis),
                str(m.status), str(m.reliance_class), m.confidence,
                _to_json(m.content),
                _to_json([s.model_dump(mode="json") for s in m.source_refs]),
                to_isoformat(m.created_at), to_isoformat(m.updated_at),
                to_isoformat(m.expires_at),
                m.supersedes, m.revoked_by,
                _to_json(m.created_by.model_dump(mode="json")) if m.created_by else None,
                _to_json(m.approved_by.model_dump(mode="json")) if m.approved_by else None,
            ),
        )

    def _update_memory_object(self, conn: sqlite3.Connection, m: MemoryObject) -> None:
        conn.execute(
            """
            UPDATE memory_objects SET
                scope=?, kind=?, basis=?, status=?, reliance_class=?,
                confidence=?, content_json=?, source_refs_json=?,
                expires_at=?, supersedes=?, revoked_by=?,
                created_by_json=?, approved_by_json=?,
                updated_at=?
            WHERE memory_id=?
            """,
            (
                m.scope, str(m.kind), str(m.basis), str(m.status),
                str(m.reliance_class), m.confidence,
                _to_json(m.content),
                _to_json([s.model_dump(mode="json") for s in m.source_refs]),
                to_isoformat(m.expires_at), m.supersedes, m.revoked_by,
                _to_json(m.created_by.model_dump(mode="json")) if m.created_by else None,
                _to_json(m.approved_by.model_dump(mode="json")) if m.approved_by else None,
                isoformat_now(),
                m.memory_id,
            ),
        )

    def _insert_receipt(self, conn: sqlite3.Connection, r: ReceiptRecord) -> None:
        conn.execute(
            """
            INSERT INTO receipts (
                receipt_id, receipt_type, hash, prev_hash,
                content_json, created_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                r.receipt_id, str(r.receipt_type), r.hash, r.prev_hash,
                _to_json(r.content), to_isoformat(r.created_at),
            ),
        )

    def _insert_memory_event(self, conn: sqlite3.Connection, e: MemoryEvent) -> None:
        try:
            conn.execute(
                """
                INSERT INTO memory_events (
                    event_id, memory_id, event_type,
                    actor_json, standing_json,
                    receipt_id, payload_json,
                    created_at, idempotency_key
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    e.event_id, e.memory_id, str(e.event_type),
                    _to_json(e.actor.model_dump(mode="json")) if e.actor else None,
                    _to_json(e.standing.model_dump(mode="json")) if e.standing else None,
                    e.receipt_id, _to_json(e.payload),
                    to_isoformat(e.created_at), e.idempotency_key,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if e.idempotency_key:
                raise IdempotencyConflictError(
                    f"idempotency conflict for key {e.idempotency_key}"
                ) from exc
            raise

    def _check_island_safety(
        self,
        conn: sqlite3.Connection,
        scope: str,
    ) -> None:
        """Refuse cross-project-shaped writes against project-local stores.

        Implements docs/gaps/ISLANDS_OF_CONTINUITY.md invariant 3: a
        scope=global / scope=workspace[:*] memory in a project-local DB is
        "a local memory wearing a fake mustache" — the storage topology
        contradicts the advertised scope. Refuse unless the operator passes
        allow_island=True (CLI --allow-island).

        Stores stamped scope_kind="workspace" / "global" / "explicit" are
        operator-chosen and not silent fallback, so they are allowed.
        """
        if self.allow_island:
            return
        if not _is_cross_project_scope(scope):
            return
        row = conn.execute(
            "SELECT scope_kind FROM store_metadata WHERE id = 1"
        ).fetchone()
        store_kind = row["scope_kind"] if row else None
        if store_kind == "project":
            raise IslandWriteRefusedError(scope, store_kind, self.db_path)

    def _emit_refusal_and_raise(
        self,
        conn: sqlite3.Connection,
        *,
        intended_event: EventType,
        decision: PolicyResult,
        request_payload: dict[str, Any],
        actor: ActorRef | None,
        standing: StandingRef | None,
    ) -> None:
        """Append a hash-chained memory.refused receipt and raise.

        No memory_objects row is created, no memory_events row is written.
        The receipt is the only audit artifact of the denied write — it
        chains off the latest receipt so denied writes are visible in the
        chain (per docs/gaps/CROSS_COMPONENT_RELIANCE_GAP.md, plan 0.3).
        """
        evaluation_time = utcnow()
        content = {
            "intended_event": str(intended_event),
            "policy_reason": decision.reason,
            "request_hash": request_hash(request_payload),
            "evaluation_time": to_isoformat(evaluation_time),
            "actor": actor.model_dump(mode="json") if actor else None,
            "standing": standing.model_dump(mode="json") if standing else None,
        }
        refusal = self._build_receipt(
            conn, ReceiptType.MEMORY_REFUSED, content,
        )
        self._insert_receipt(conn, refusal)
        # Persist the refusal before raising — otherwise the _tx() context
        # manager would roll it back with the exception. This is the whole
        # point of the receipt: denied writes are auditable.
        conn.commit()
        raise PolicyDeniedError(decision.reason, refusal)

    def _build_receipt(
        self,
        conn: sqlite3.Connection,
        rtype: ReceiptType,
        content: dict[str, Any],
    ) -> ReceiptRecord:
        prev_hash = self._latest_receipt_hash(conn)
        h = receipt_hash(
            receipt_type=str(rtype), prev_hash=prev_hash, content=content,
        )
        return ReceiptRecord(
            receipt_type=rtype, hash=h, prev_hash=prev_hash, content=content,
        )

    def _latest_receipt_hash(self, conn: sqlite3.Connection) -> str | None:
        row = conn.execute(
            "SELECT hash FROM receipts ORDER BY created_at DESC, receipt_id DESC LIMIT 1"
        ).fetchone()
        return str(row["hash"]) if row else None

    def _observe_receipt_content(
        self, memory: MemoryObject, req: ObserveMemoryRequest,
    ) -> dict[str, Any]:
        return {
            "memory_id": memory.memory_id,
            "scope": memory.scope,
            "kind": memory.kind,
            "basis": memory.basis,
            "status": memory.status,
            "reliance_class": memory.reliance_class,
            "confidence": memory.confidence,
            "content": memory.content,
            "source_refs": [s.model_dump(mode="json") for s in memory.source_refs],
            "expires_at": to_isoformat(memory.expires_at),
            "supersedes": memory.supersedes,
            "actor": memory.created_by.model_dump(mode="json") if memory.created_by else None,
            "standing": req.standing.model_dump(mode="json") if req.standing else None,
            "premises": [p.model_dump(mode="json") for p in req.premises],
        }

    def _load_idempotent_response(
        self,
        conn: sqlite3.Connection,
        idempotency_key: str,
        expected: EventType,
    ) -> tuple[MemoryObject, MemoryEvent, ReceiptRecord] | None:
        event_row = conn.execute(
            "SELECT * FROM memory_events WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if event_row is None:
            return None

        event = self._row_to_memory_event(event_row)
        if event.event_type != expected:
            raise IdempotencyConflictError(
                f"idempotency key {idempotency_key} already used for {event.event_type}"
            )

        memory = self._get_memory(conn, event.memory_id)
        receipt_row = conn.execute(
            "SELECT * FROM receipts WHERE receipt_id = ?",
            (event.receipt_id,),
        ).fetchone()
        if receipt_row is None:
            raise RuntimeError(f"receipt {event.receipt_id} missing for event {event.event_id}")
        return memory, event, self._row_to_receipt(receipt_row)

    # ------------------------------------------------------------------
    # Row conversion
    # ------------------------------------------------------------------

    def _row_to_memory_object(self, row: sqlite3.Row) -> MemoryObject:
        created_by_raw = from_json(row["created_by_json"])
        approved_by_raw = from_json(row["approved_by_json"])
        return MemoryObject(
            memory_id=row["memory_id"],
            scope=row["scope"],
            kind=row["kind"],
            basis=row["basis"],
            status=row["status"],
            reliance_class=row["reliance_class"],
            confidence=row["confidence"],
            content=from_json(row["content_json"]),
            source_refs=[
                SourceRef.model_validate(s)
                for s in from_json(row["source_refs_json"])
            ],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            supersedes=row["supersedes"],
            revoked_by=row["revoked_by"],
            created_by=ActorRef.model_validate(created_by_raw) if created_by_raw else None,
            approved_by=ActorRef.model_validate(approved_by_raw) if approved_by_raw else None,
        )

    def _row_to_memory_event(self, row: sqlite3.Row) -> MemoryEvent:
        actor_raw = from_json(row["actor_json"])
        standing_raw = from_json(row["standing_json"])
        return MemoryEvent(
            event_id=row["event_id"],
            memory_id=row["memory_id"],
            event_type=row["event_type"],
            actor=ActorRef.model_validate(actor_raw) if actor_raw else None,
            standing=StandingRef.model_validate(standing_raw) if standing_raw else None,
            receipt_id=row["receipt_id"],
            payload=from_json(row["payload_json"]),
            created_at=row["created_at"],
            idempotency_key=row["idempotency_key"],
        )

    def _row_to_receipt(self, row: sqlite3.Row) -> ReceiptRecord:
        return ReceiptRecord(
            receipt_id=row["receipt_id"],
            receipt_type=row["receipt_type"],
            hash=row["hash"],
            prev_hash=row["prev_hash"],
            content=from_json(row["content_json"]),
            created_at=row["created_at"],
        )

    def _row_to_memory_link(self, row: sqlite3.Row) -> MemoryLink:
        src_ref_raw = from_json(row["src_ref_json"])
        # pinned_content_hash may be absent on rows pre-dating the column;
        # PRAGMA table_info-driven migration adds it, but Row.keys() guards
        # against pre-migration reads.
        pinned = row["pinned_content_hash"] if "pinned_content_hash" in row.keys() else None
        return MemoryLink(
            link_id=row["link_id"],
            dst_memory_id=row["dst_memory_id"],
            src_memory_id=row["src_memory_id"],
            src_receipt_id=row["src_receipt_id"],
            src_ref=SourceRef.model_validate(src_ref_raw) if src_ref_raw else None,
            relation=row["relation"],
            strength=row["strength"],
            status=row["status"],
            note=row["note"],
            created_at=row["created_at"],
            created_by_event_id=row["created_by_event_id"],
            revoked_at=row["revoked_at"],
            revoked_by_event_id=row["revoked_by_event_id"],
            pinned_content_hash=pinned,
        )
