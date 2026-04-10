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
    RevokeMemoryRequest,
    RevokeMemoryResponse,
    SourceRef,
    StandingRef,
)
from continuity.util.clock import isoformat_now, to_isoformat
from continuity.util.dbpath import find_git_root
from continuity.util.hashing import receipt_hash
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


class SQLiteStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        schema_sql = schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema_sql)
            self._ensure_store_metadata(conn)

    def _ensure_store_metadata(self, conn: sqlite3.Connection) -> None:
        """Populate store_metadata on first init.

        The metadata is a singleton — one row per database — that records
        store identity, the git root the DB lived next to at creation
        time, and a project hint derived from the surrounding directory
        names. It is never updated after creation; it describes origin,
        not current state.
        """
        row = conn.execute(
            "SELECT store_id FROM store_metadata WHERE id = 1"
        ).fetchone()
        if row is not None:
            return

        db_dir = self.db_path.parent.resolve()
        git_root = find_git_root(db_dir)
        if git_root is not None:
            project_hint = git_root.name
        else:
            project_hint = db_dir.name

        conn.execute(
            "INSERT INTO store_metadata "
            "(id, store_id, project_hint, git_root, created_at) "
            "VALUES (1, ?, ?, ?, ?)",
            (
                new_id("store"),
                project_hint,
                str(git_root) if git_root is not None else None,
                isoformat_now(),
            ),
        )

    def get_store_metadata(self) -> dict[str, Any] | None:
        """Return the singleton store metadata row, or None if not set."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT store_id, project_hint, git_root, created_at "
                "FROM store_metadata WHERE id = 1"
            ).fetchone()
            if row is None:
                return None
            return {
                "store_id": row["store_id"],
                "project_hint": row["project_hint"],
                "git_root": row["git_root"],
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
        targets = ("memory_objects", "memory_links")
        new_defs: dict[str, str] = {}
        for table in targets:
            stmt = _extract_create_table(schema_sql, table)
            if stmt is None:
                raise RuntimeError(
                    f"could not find CREATE TABLE {table} in schema.sql"
                )
            new_defs[table] = stmt

        changed: list[str] = []
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

            # Verify integrity after patching.
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

        return {"changed_tables": changed, "integrity_check": integrity}

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

    def query_memory(self, req: QueryMemoryRequest) -> QueryMemoryResponse:
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
            params.append(isoformat_now())

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

    def get_case(self, req: GetCaseRequest) -> CaseBundle:
        """Return a derived case bundle for a scope.

        Cases are not persisted; they are computed on demand by bucketing
        all memories in the scope by kind and pairing each with its rely
        state. Revoked items are included so the case preserves the
        ruled-out branches that were part of the investigation.
        """
        with self._connect() as conn:
            params: list[Any] = [req.scope]
            sql = "SELECT * FROM memory_objects WHERE scope = ?"
            if not req.include_expired:
                sql += " AND (expires_at IS NULL OR expires_at > ?)"
                params.append(isoformat_now())
            sql += " ORDER BY created_at ASC, memory_id ASC"

            rows = conn.execute(sql, params).fetchall()
            memories = [self._row_to_memory_object(r) for r in rows]

            items: list[CaseItem] = []
            for m in memories:
                rely_ok, rely_reason = self._compute_rely_state(conn, m)
                items.append(CaseItem(
                    memory=m, rely_ok=rely_ok, rely_reason=rely_reason,
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
            else:
                bundle.other.append(item)

        if bundle.summary is not None:
            title = bundle.summary.memory.content.get("title")
            if isinstance(title, str):
                bundle.title = title

        if items:
            bundle.last_touch = max(m.memory.updated_at for m in items)

        return bundle

    def explain_memory(self, memory_id: str) -> ExplainMemoryResponse:
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
            rely_ok, rely_reason = self._compute_rely_state(conn, memory)

        return ExplainMemoryResponse(
            memory=memory,
            events=[self._row_to_memory_event(r) for r in event_rows],
            receipts=[self._row_to_receipt(r) for r in receipt_rows],
            premises=premises,
            dependents=dependents,
            rely_ok=rely_ok,
            rely_reason=rely_reason,
        )

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
                created_by_event_id=created_by_event_id,
            )
            conn.execute(
                """
                INSERT INTO memory_links (
                    link_id, dst_memory_id,
                    src_memory_id, src_receipt_id, src_ref_json,
                    relation, strength, status, note,
                    created_at, created_by_event_id,
                    revoked_at, revoked_by_event_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
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
    ) -> tuple[bool, str]:
        if memory.status != MemoryStatus.COMMITTED:
            return False, f"memory status is {memory.status}, not committed"

        if memory.expires_at is not None:
            now = isoformat_now()
            exp = to_isoformat(memory.expires_at)
            if exp and now >= exp:
                return False, "memory is expired"

        if memory.reliance_class == RelianceClass.NONE:
            return False, "reliance_class=none"

        if (
            memory.kind in {MemoryKind.SUMMARY, MemoryKind.HYPOTHESIS}
            and memory.reliance_class == RelianceClass.ACTIONABLE
        ):
            return False, f"{memory.kind} cannot be actionable by default"

        if (
            memory.basis in {Basis.INFERENCE, Basis.SYNTHESIS}
            and memory.reliance_class == RelianceClass.ACTIONABLE
        ):
            return False, f"basis={memory.basis} cannot be actionable by default"

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
            return False, f"hard premises unavailable: {', '.join(bad)}"

        return True, f"eligible for reliance at class {memory.reliance_class}"

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
        )
