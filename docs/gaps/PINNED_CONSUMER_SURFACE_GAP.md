# Gap: Pinned Consumer Surface — the API another repo already stands on

**Status:** proposed
**Depends on:** None (records existing facts; adds tests, no behavior).
**Related:** `CROSS_COMPONENT_RELIANCE_GAP` (the doctrine layer for *what* may be relied on; this gap is about *which code shapes* a consumer relies on), `USEFUL_REFUSAL_EXPLAIN` (will change the type of `rely_reason`, which is inside the pinned surface — see invariant 4), `MEMORY_AUTHORING_TIER_GAP` (adds fields to read payloads; must stay additive against this surface). Consumer-side counterpart: `agent_gov/docs/roadmaps/tools/continuity.md` (R-CONT-1/R-CONT-2).
**Blocks:** any refactor of `store/sqlite.py`, `util/dbpath.py`, or `api/models.py` that renames or re-signatures the pinned members below without a coordinated consumer migration.
**Last updated:** 2026-07-03

## The Problem

Continuity has consumers on three declared surfaces — MCP, CLI, library — and
`docs/integrations.md` describes them. What it does not record is that one consumer has
already **wired the library surface into production code**: agent_gov's
`src/governor/doctrine.py`, the only live Governor→Continuity edge in the constellation.
That module imports specific names, calls specific signatures, and reads specific
response fields. Nothing in this repo names that surface, and nothing in this repo's
test suite would fail if a refactor broke it. The failure mode is quiet: continuity's
231 tests stay green, agent_gov's graceful degradation converts the breakage into
`quality="store_error"` receipts, and the constellation's first cross-system edge dies
without a red light anywhere.

The naïve fixes are both wrong. "Freeze the whole library API" over-pins — continuity
is pre-1.0 and most of its internals have exactly one caller (itself). "Let the
consumer's tests catch it" under-pins — agent_gov *deliberately* degrades instead of
failing (traffic cop, not city), so its tests assert graceful degradation, not
continuity's stability. The right shape is narrow and explicit: enumerate exactly what
the consumer touches, and make *this* repo's suite fail when that enumeration breaks.

## Design Stance

A pinned surface is a fact, not a promise ceremony. The consumer already depends on
these names; recording them changes retrofit cost, not authority. This is the
allowlist shape: the pinned set is small and enumerable, so the guarantee is
conjunctive — every member holds or the edge is broken. Additions to responses are
free; removals and re-signatures of pinned members are coordinated changes.

This gap does not create a compatibility regime, a semver policy, or a deprecation
process. One consumer, one file, one contract-test module. When a second consumer pins
a second surface (Spine's is the export contract, already frozen in
`docs/DECLARATION_EXPORT_V0.md` with its own tests), it gets its own section here or
its own spec — pinning stays per-consumer and evidence-backed, never speculative.

## Architectural Invariants

### What is pinned (observed from `agent_gov/src/governor/doctrine.py` @ `3d08a48`)

1. **Importable names.** `continuity.__version__`;
   `continuity.api.models.MemoryKind`, `MemoryStatus` (with member `COMMITTED`);
   `continuity.store.sqlite.SQLiteStore`;
   `continuity.util.dbpath.resolve_db_path`, `source_to_scope_kind`.

2. **Call signatures.**
   `resolve_db_path(explicit_db, workspace=..., cwd=...)` returning a
   `(db_path, source)` pair; `source_to_scope_kind(source)` returning a string;
   `SQLiteStore(db_path)`; `store.get_store_metadata()`;
   `store.latest_memory(scope=..., kind=..., status=MemoryStatus.COMMITTED)` returning
   a memory object or `None`, accepting `kind` as a plain string (the consumer passes
   `"constraint"` and `"decision"`, not enum members);
   `store.explain_memory(memory_id)`.

3. **Read fields.** On the memory object: `memory_id`, `scope`, `kind`, `status`,
   `reliance_class`, `confidence` (float-coercible), `content` (dict-coercible),
   `updated_at`. On the explain result: `rely_ok` (bool-coercible), `rely_reason`.

4. **`rely_reason` stays str-renderable.** The consumer does
   `str(explained.rely_reason)`. When `USEFUL_REFUSAL_EXPLAIN` promotes refusals to a
   structured `RelyReasonCode` shape, either the field remains a string with structure
   alongside, or the structured object's `__str__` renders the human message. Silent
   `repr()` soup in a gate receipt is a break even though no exception is raised.

### How the pin binds

5. **The pin lives in continuity's own test suite.** A contract-test module exercises
   every member of invariants 1–3 against a real tmp store, so any breaking rename or
   re-signature fails *here first*, before it ships to the consumer. The consumer's
   graceful degradation is an argument for this placement, not against it.

6. **Additive changes are free; the pinned set only grows by evidence.** New fields on
   responses, new parameters with defaults, new methods — all fine without ceremony.
   Adding a member to the pinned set requires an actual consumer call site, named with
   repo and path. No speculative pinning.

7. **Breaking a pinned member is a coordinated change, not a forbidden one.** The rule
   is not "never change"; it is "this repo's suite goes red until the change is either
   reverted or explicitly coordinated" (consumer migrated, pin updated, both named in
   the commit).

## V1 Slice

1. This spec, indexed in `docs/gaps/README.md`.
2. `tests/test_consumer_surface_ag.py` — one test per invariant block: imports resolve;
   `resolve_db_path`/`source_to_scope_kind` shapes hold; `latest_memory` accepts
   string `kind` and returns `None` on miss; a committed memory round-trips all eight
   pinned fields; `explain_memory` yields `rely_ok`/`rely_reason` with `rely_reason`
   str-renderable. Header comment points at this spec and the consumer file.
3. A cross-reference note in `docs/integrations.md`'s library-surface section.

## Explicit Deferrals

- **A general compatibility/semver policy.** One consumer does not justify a regime.
- **Pinning the MCP tool schemas.** Session tooling breaks loudly (tools fail at call
  time in front of an operator), unlike the library edge; pin when a consumer script
  depends on them unattended.
- **Spine's consumer surface.** Already contract-frozen in `DECLARATION_EXPORT_V0.md`
  with its own tests; a conformance *fixture* for Spine 2c is tracked in the roadmap,
  not here.
- **Mechanical detection of new consumers** (grepping sibling repos for `import
  continuity`). Cheap to run by hand when a roadmap crossing suggests it.

## Open Questions

1. Should the contract tests import agent_gov's `doctrine.py` directly (true
   end-to-end) instead of restating the calls? V1 says no — that inverts the
   dependency and makes continuity's suite depend on a sibling checkout. Restating the
   calls duplicates ~20 lines; acceptable.
2. When `MEMORY_AUTHORING_TIER` V1 makes callers declare a tier explicitly, does any
   pinned *write* path appear? Today the consumer is read-only, so no. If Governor
   ever writes doctrine back, that is a new pin — and a new authority conversation.

## Acceptance Criteria

This gap is closed when the contract-test module exists and passes, a deliberate
rename of any pinned member makes it fail, and `docs/integrations.md` points here.

## Short Version

agent_gov's `src/governor/doctrine.py` — the constellation's only wired
Governor→Continuity edge — imports five continuity names, calls six signatures, and
reads ten fields. Nothing in continuity records or tests that surface, and the
consumer deliberately degrades instead of failing, so a breaking refactor would ship
green from both repos and kill the edge silently. This gap pins exactly that observed
surface (never more), puts the contract tests in continuity's own suite so breakage
fails here first, keeps additions free, and defines "breaking a pin" as a coordinated
change rather than a forbidden one. One consumer, one file, one test module — pinning
grows only by evidence of an actual call site.
