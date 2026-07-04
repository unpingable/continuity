"""Contract tests pinning the library surface agent_gov relies on.

V1 of docs/gaps/PINNED_CONSUMER_SURFACE_GAP.md.

The consumer is agent_gov's ``src/governor/doctrine.py`` — the constellation's
only wired Governor->Continuity edge. It reaches into continuity's *library*
API (not the CLI, not MCP) and deliberately degrades to a shaped
``quality="store_error"`` result instead of raising when the store misbehaves.
That graceful degradation means a breaking rename or re-signature here would
ship green from *both* repos and silently kill the edge.

So the pin lives in continuity's own suite: these tests restate exactly what
``doctrine.py`` imports, calls, and reads — including the ``str(...)`` /
``float(...)`` / ``dict(...)`` / ``bool(...)`` coercions the consumer applies —
so any break fails *here first*.

Do not "simplify" these by importing agent_gov's ``doctrine.py`` directly; that
would invert the dependency (continuity's suite must not need a sibling
checkout). Restating ~20 lines is the intended cost. See the gap spec, Open
Question 1.

If a pinned member below genuinely needs to change, that is a *coordinated*
change, not a forbidden one: update the consumer and this pin together, name
both in the commit, and the suite goes green again. It is red in the meantime
on purpose.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from continuity.api.models import (
    Basis,
    CommitMemoryRequest,
    MemoryKind,
    MemoryStatus,
    ObserveMemoryRequest,
    RelianceClass,
)
from continuity.store.sqlite import SQLiteStore

# The doctrine kinds the consumer queries, passed as PLAIN STRINGS (not enum
# members). doctrine.py's DEFAULT_DOCTRINE_KINDS is ("constraint", "decision").
CONSUMER_DOCTRINE_KINDS: tuple[str, ...] = ("constraint", "decision")


# ---------------------------------------------------------------------------
# Invariant 1 — importable names
# ---------------------------------------------------------------------------


def test_pinned_importable_names() -> None:
    """Every name doctrine.py imports must resolve at these exact paths."""
    continuity = importlib.import_module("continuity")
    assert isinstance(continuity.__version__, str)

    models = importlib.import_module("continuity.api.models")
    assert hasattr(models, "MemoryKind")
    assert hasattr(models, "MemoryStatus")
    # The consumer references MemoryStatus.COMMITTED explicitly.
    assert hasattr(models.MemoryStatus, "COMMITTED")

    sqlite_mod = importlib.import_module("continuity.store.sqlite")
    assert hasattr(sqlite_mod, "SQLiteStore")

    dbpath = importlib.import_module("continuity.util.dbpath")
    assert hasattr(dbpath, "resolve_db_path")
    assert hasattr(dbpath, "source_to_scope_kind")


# ---------------------------------------------------------------------------
# Invariant 2 — call signatures
# ---------------------------------------------------------------------------


def test_resolve_db_path_shape(tmp_path: Path) -> None:
    """resolve_db_path(explicit, workspace=, cwd=) -> (Path-ish, source-label).

    doctrine.py calls it positionally with keyword workspace/cwd and unpacks a
    two-tuple, then feeds ``source`` to source_to_scope_kind.
    """
    from continuity.util.dbpath import resolve_db_path, source_to_scope_kind

    explicit = tmp_path / "explicit.db"
    db_path, source = resolve_db_path(explicit, workspace=None, cwd=tmp_path)
    assert Path(db_path) == explicit
    assert source == "explicit"

    # source_to_scope_kind maps every documented label to a scope_kind string.
    for label in ("explicit", "env", "workspace", "git-root", "global-fallback"):
        assert isinstance(source_to_scope_kind(label), str)


def test_store_construction_and_metadata(tmp_path: Path) -> None:
    """SQLiteStore(db_path); store.get_store_metadata() -> dict|None.

    doctrine.py constructs the store from a resolved path and reads metadata
    into its evidence bundle. Metadata may be None (tolerated by the consumer);
    when present it must carry the pinned keys.
    """
    db = tmp_path / "meta.db"
    store = SQLiteStore(db)
    store.initialize(scope_kind="project", scope_label="pin-test")

    meta = store.get_store_metadata()
    assert meta is None or isinstance(meta, dict)
    if isinstance(meta, dict):
        for key in ("store_id", "project_hint", "git_root", "scope_kind", "schema_version"):
            assert key in meta


def test_latest_memory_accepts_string_kind_and_status(store: SQLiteStore) -> None:
    """latest_memory(scope=, kind=<str>, status=MemoryStatus.COMMITTED).

    The consumer passes ``kind`` as a plain string and filters to committed.
    Missing (scope, kind) must return None, not raise — doctrine.py treats
    None as "no current doctrine for that scope/kind".
    """
    # No memory yet: None for every doctrine kind.
    for kind in CONSUMER_DOCTRINE_KINDS:
        assert store.latest_memory(
            scope="doctrine:pin", kind=kind, status=MemoryStatus.COMMITTED,
        ) is None

    _commit_doctrine(store, scope="doctrine:pin", kind="constraint")

    hit = store.latest_memory(
        scope="doctrine:pin", kind="constraint", status=MemoryStatus.COMMITTED,
    )
    assert hit is not None
    assert hit.scope == "doctrine:pin"


def test_explain_memory_yields_rely_fields(store: SQLiteStore) -> None:
    """explain_memory(memory_id) -> object with rely_ok, rely_reason."""
    mem = _commit_doctrine(store, scope="doctrine:pin", kind="decision")
    explained = store.explain_memory(mem.memory_id)
    assert hasattr(explained, "rely_ok")
    assert hasattr(explained, "rely_reason")


# ---------------------------------------------------------------------------
# Invariant 3 — read fields (with the consumer's exact coercions)
# ---------------------------------------------------------------------------


def test_read_fields_survive_consumer_coercions(store: SQLiteStore) -> None:
    """Reproduce doctrine.py's DoctrineEntry construction exactly.

    If any pinned field disappears or stops coercing, this fails here before
    it reaches a gate receipt as repr-soup.
    """
    mem = _commit_doctrine(store, scope="doctrine:pin", kind="constraint")
    explained = store.explain_memory(mem.memory_id)

    # This mirrors DoctrineEntry(...) in agent_gov/src/governor/doctrine.py.
    entry = {
        "memory_id": mem.memory_id,
        "scope": mem.scope,
        "kind": str(mem.kind),
        "status": str(mem.status),
        "reliance_class": str(mem.reliance_class),
        "confidence": float(mem.confidence),
        "content": dict(mem.content),
        "updated_at": str(mem.updated_at),
        "rely_ok": bool(explained.rely_ok),
        "rely_reason": str(explained.rely_reason),
    }

    assert isinstance(entry["memory_id"], str) and entry["memory_id"]
    assert entry["scope"] == "doctrine:pin"
    assert isinstance(entry["kind"], str) and entry["kind"]
    assert isinstance(entry["status"], str) and entry["status"]
    assert isinstance(entry["reliance_class"], str) and entry["reliance_class"]
    assert isinstance(entry["confidence"], float)
    assert isinstance(entry["content"], dict) and entry["content"]
    assert isinstance(entry["updated_at"], str) and entry["updated_at"]
    assert isinstance(entry["rely_ok"], bool)
    assert isinstance(entry["rely_reason"], str)


def test_rely_reason_is_str_renderable(store: SQLiteStore) -> None:
    """Invariant 4: rely_reason must remain str-renderable.

    doctrine.py does ``str(explained.rely_reason)`` straight into a gate
    receipt. USEFUL_REFUSAL_EXPLAIN will make refusals structured; when it
    lands, either rely_reason stays a string with structure alongside, or the
    structured object's __str__ renders the human message. A bare repr() of a
    dataclass/dict in a receipt is a silent break even though nothing raises.
    """
    mem = _commit_doctrine(store, scope="doctrine:pin", kind="decision")
    explained = store.explain_memory(mem.memory_id)
    rendered = str(explained.rely_reason)
    assert isinstance(rendered, str)
    # A structured refusal that fell through to the default object repr would
    # look like "<... object at 0x...>". That is exactly the break we pin against.
    assert "object at 0x" not in rendered


# ---------------------------------------------------------------------------
# Helper — build a committed doctrine memory the way a real store would hold one
# ---------------------------------------------------------------------------


def _commit_doctrine(store: SQLiteStore, *, scope: str, kind: str):
    """Observe + commit a memory at (scope, kind), return the committed object.

    Uses the real request models so the pinned read fields come from a genuine
    committed row, not a hand-built object.
    """
    obs = store.observe_memory(ObserveMemoryRequest(
        scope=scope,
        kind=MemoryKind(kind),
        basis=Basis.OPERATOR_ASSERTION,
        content={"rule": f"pinned doctrine for {scope}/{kind}"},
        confidence=0.7,
    ))
    cmt = store.commit_memory(CommitMemoryRequest(
        memory_id=obs.memory.memory_id,
        reliance_class=RelianceClass.ADVISORY,
    ))
    return cmt.memory
