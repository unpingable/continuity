# Gap: Continuity Time Discipline — be time-aware without hiding which clock you used

**Status:** proposed
**Depends on:** existing `util/clock.py`, `MemoryPolicy.allow_rely`, `_compute_rely_state` in `sqlite.py`, the `trg_memory_objects_updated_at` SQL trigger
**Related:** `CONTINUITY_ORIENT_HOOK.md` (read-side staleness gradient is upstream of any future "orient-only past T" posture); constellation-wide time audit (NQ / NS / Wicket / WLP / RPP / AG carry their own time-shaped gaps in their respective repos)
**Last updated:** 2026-05-18

## The Problem

Continuity's foundation is decent: `utcnow()` is centralized, table-level `created_at`s are separated (receipt time ≠ event time ≠ memory time), `expires_at` is honored in rely and query, revoked memories are blocked from rely, and receipts are hash-chained. The 2026-05-18 audit against chatty's constellation-wide time-discipline pass surfaced five leaks where wall-clock and field semantics drift into ambient territory exactly where memory systems become spooky:

1. **`_compute_rely_state` silently consults wall-clock.** `sqlite.py:825` calls `isoformat_now()` directly with no evaluation-time parameter. Replay or audit cannot ask "would this have relied successfully at time T?" without mocking the clock.
2. **Two clock surfaces, not one.** The trigger `trg_memory_objects_updated_at` (`schema.sql:268-276`) uses SQLite's `'now'` — invisible from Python, bypassing `utcnow()`. Tests cannot mock it; replays cannot reproduce it.
3. **`created_at` conflates *recording time* with *source observation time*.** A memory written 2026-04-01 summarizing a fact observed 2025-12-15 has no way to expose the four-month lag. The field for source-observation doesn't exist.
4. **`updated_at` conflates "anything mutated" with "fact reconfirmed."** The trigger bumps on link revocation, supersession by other memories, repair events — any state change. It reads as freshness but isn't.
5. **No middle state between hard `expires_at` and forever-binding.** "Orient-only past T" / "advisory-only past T" has no representation in the data model.

Leaks 1 and 2 are demonstrated by the current code. Leaks 3-5 are named holes whose retrofit cost rises with usage spread, but whose taxonomy is dangerous to invent ahead of pressure.

## Design Stance

**Continuity may reason about time, but it must not hide which clock it used.**

This is narrower than the atemporal-kernel rule that applies to Wicket. Continuity is allowed to be time-aware — memory decays, that is its job. The rule is about *transparency*, not abstinence: any clock read that affects whether memory binds must be either an explicit parameter or recorded alongside the decision. Ambient `now()` reads are acceptable at the API boundary; they are not acceptable inside the rely computation, inside the storage trigger, or anywhere a future reviewer cannot reconstruct what time was used.

The shared constellation invariant — **No timestamp may impersonate another timestamp** — applies. Generation time, observation time, recording time, evaluation time, confirmation time, supersession time are each their own concept; collapsing two into one field is an explicit design choice with a documented reason or it is a leak.

V1 closes the two leaks the current code carries (items 1 and 2). V2 captures the field separations that do not yet exist (items 3-5) — but only when implementation pressure demonstrates the gap. Inventing the staleness taxonomy preemptively is *calendar theology with a schema migration*; nobody needs that before dinner.

## Architectural Invariants

### Clock transparency

1. **No ambient `now()` inside rely computation.** `_compute_rely_state` and any function it delegates expiry/freshness decisions to takes `evaluation_time: datetime` as a parameter. The API edge — `MemoryStore.explain`, query-with-expiry-filter, MCP tool surfaces — defaults `evaluation_time` to `utcnow()` *once* at the boundary if the caller did not supply one. From the boundary inward, the resolved time flows down explicitly. The kernel never calls the clock.

2. **One clock surface, not two.** The SQLite trigger `trg_memory_objects_updated_at` is removed. `updated_at` is set by the application layer through `utcnow()`. Storage no longer carries an independent clock read.

3. **`evaluation_time` is visible in rely outputs.** When `rely_ok` is computed, the evaluation time used is captured in `ExplainMemoryResponse` so a future audit can reconstruct the decision context. The hash chain on receipts remains keyed to receipt-issue time, not evaluation time — these are distinct clocks and any receipt content that audits rely must carry both.

### Field semantics

4. **`updated_at` means mutation time, not confirmation time.** It is bumped by any state change on the memory row. It is not a freshness signal. Code that wants freshness must consult `last_confirmed_at` (deferred to V2) or walk the event log explicitly.

5. **`created_at` means recording time.** When `source_observed_at` lands in V2, `created_at` continues to mean "when this memory was recorded in the substrate." The two are usually close but not identical, and the asymmetry is named — not laundered.

### Boundary discipline

6. **Ambient `now()` at the API boundary is acceptable.** A CLI invocation, an MCP tool dispatch, or a library call that does not specify `evaluation_time` falls through to `utcnow()` *once* at the entry point. The resolved time then flows explicitly into the kernel.

7. **Receipt-issue time stays at receipt-creation site.** `ReceiptRecord.created_at` is the wall-clock moment the receipt was issued. Receipts are issued at action time by definition — that clock read is at the boundary and is not affected by this gap.

### Deferred but named (V2)

8. **`source_observed_at` is a named field on `MemoryObject` and `ObserveMemoryRequest`.** Optional. When set, it carries the time the underlying fact was observed — distinct from the memory's `created_at`. Backfill is impossible; capture begins when the field lands. V1 does not add the field; V2 does, when an audit or capture surface routinely loses the source-observation signal.

9. **`last_confirmed_at` is bumped by explicit re-confirmation only.** A V2 event class (`confirm`) — or an event-shape under `observe` that names the prior memory it confirms — updates this column. Until V2, freshness must be inferred from the event log. The `confirm`-as-event-type-vs-sub-shape question stays open.

10. **Staleness posture has no v1 representation.** A gradient between hard `expires_at` and forever-binding — `orient_after`, `advisory_after`, `bind_until`, or some other naming — is reserved here so the V2 schema migration arrives honest. *Do not invent the taxonomy preemptively.*

## Data Shape

**No schema changes for V1.** The trigger is dropped. No new columns.

**V1 code-level changes:**
- `_compute_rely_state` signature gains `evaluation_time: datetime` parameter.
- `ExplainMemoryResponse` gains optional `evaluation_time: datetime` carrying the time used.
- Public `MemoryStore.explain` and any sibling rely-touching surface accept optional `evaluation_time` (default behavior unchanged for callers that omit it).
- Query path that filters `expires_at` uses the same parameter flow.
- SQL migration: `DROP TRIGGER IF EXISTS trg_memory_objects_updated_at;`.
- Application write paths push `updated_at` from Python through `utcnow()`.

**V2 schema additions (named, not built):**
```sql
-- V2 only — DO NOT add in this gap
ALTER TABLE memory_objects ADD COLUMN source_observed_at TEXT NULL;
ALTER TABLE memory_objects ADD COLUMN last_confirmed_at  TEXT NULL;
-- staleness posture: enum + posture-specific cutoff timestamp; shape TBD
```

## V1 Slice

1. Add `evaluation_time: datetime | None` to `MemoryStore.explain` and the query path that filters expired memories. Default at the boundary to `utcnow()` when `None`; from there it flows down explicitly.
2. Refactor `_compute_rely_state` to take `evaluation_time` as a required parameter. Internal callers pass the resolved boundary value through.
3. Drop the `trg_memory_objects_updated_at` trigger via migration. Update every write path that mutates `memory_objects` to set `updated_at = utcnow()` in Python.
4. Add `evaluation_time: datetime | None` to `ExplainMemoryResponse`.
5. Tests:
   - rely with an explicit past `evaluation_time` on a memory that hadn't yet expired at T returns the historical answer (not expired);
   - rely with an explicit future `evaluation_time` past `expires_at` returns expired;
   - default behavior unchanged for callers that don't pass `evaluation_time`;
   - dropped trigger: `updated_at` continues to bump correctly through the application path; concurrent writes from multiple connections still get monotonic-enough updates for the test suite;
   - `ExplainMemoryResponse.evaluation_time` reflects the time actually used (including the boundary default).

## Deliberately out of scope (v1)

- **`source_observed_at`** — named in invariant 8, not built. V2 begins when an audit surface or capture path demonstrates the source-vs-record gap is costing real information.
- **`last_confirmed_at`** — named in invariant 9, not built. V2 begins when re-confirmation becomes a distinct enough event class that walking the event log is friction.
- **Staleness posture / orient-vs-bind gradient** — invariant 10 reserves the slot. Designing the taxonomy ahead of usage is the "calendar theology" trap.
- **Import-time vs source-authored-time separation.** Imported memories currently set `created_at` to import-landing time. Source-authoring time may be recoverable from the import payload but is not promoted. Deferred until `CROSS_ISLAND_BRIDGES_GAP.md` exercises the gap.
- **Constellation-wide time discipline.** Other organs (NQ / NS / Wicket / WLP / RPP / AG) carry parallel time-shaped gaps. Cross-repo coordination is bridging work, not this gap's concern.
- **Scheduled-job clock handling.** Night Shift territory.

## Acceptance Criteria

- `rely_ok` cannot be computed without either an explicit `evaluation_time` or a boundary default that resolved from exactly one `utcnow()` read. The internal computation never calls the clock.
- A test supplies a past `evaluation_time` and demonstrates that a now-expired memory was not yet expired at T — rely is reconstructible against historical evaluation times.
- The `trg_memory_objects_updated_at` trigger is dropped; `updated_at` is set entirely through `utcnow()` at the application layer.
- `ExplainMemoryResponse` surfaces the `evaluation_time` used to compute `rely_ok`.
- No new schema columns land. V2 capture-side fields remain named-but-unbuilt.
- The keeper lines and design stance are preserved verbatim in the spec body: *Memory time is not source time. Old continuity can orient. It must not silently bind. No timestamp may impersonate another timestamp. Continuity may reason about time, but it must not hide which clock it used.*

## Open Questions

1. **MCP surface exposure.** Should `memory_explain` / `memory_query` accept `evaluation_time` as an external argument, or always default it on the server side? External exposure unlocks replay tooling; server-side defaulting reduces footgun surface. Probably external; revisit if security/audit concerns surface.
2. **Concurrency under dropped trigger.** Two writers updating the same `memory_id` from different connections need to produce a deterministic-enough `updated_at`. SQLite connection locking probably suffices but warrants a focused test.
3. **Receipt payload shape for `evaluation_time`.** Top-level optional field vs. nested under a `rely_audit` sub-object. Probably top-level for parseability; revisit if explain receipts grow.
4. **Multi-hop evaluation time.** A rely decision depends on premise states; premises themselves have rely decisions. Does `evaluation_time` propagate across hops as a single value, or can a multi-hop audit specify per-premise evaluation times? V1 single value; multi-hop is V2+ if it earns implementation pressure.
5. **`confirm` as a fifth event type or a sub-shape of `observe`.** V2 question; named here so it isn't relitigated when the work lands.

## Revision trigger

Revise this gap when implementation pressure proves it underspecified — not when downstream events merely happen.

Likely revelation moments: V1 lands and a caller wants to drive a historical rely computation through MCP (exposing whether `evaluation_time` belongs on the external surface); a concurrent-write test exposes that application-layer `updated_at` is insufficient without an explicit ordering primitive; an audit caller finds that capturing `evaluation_time` in the response isn't enough because *premises'* evaluation times also matter (multi-hop); the V2 staleness gradient gets sketched and the v1 invariants don't constrain it enough. The trigger in each case is *"I tried to use this and it didn't tell me what to do"* — not "X happened, time to revisit."

**V2 promotion trigger:** any named-deferred field (`source_observed_at`, `last_confirmed_at`, staleness posture) accumulates demonstrated implementation pressure — an audit cannot answer a question that the field would have made answerable, or a capture surface routinely loses information the field would have carried.

## Short Version

Continuity is allowed to reason about time; it must not hide which clock it used. V1 closes two leaks the current code carries: `_compute_rely_state` calling ambient `isoformat_now()` (becomes an explicit `evaluation_time` parameter that flows in from the API boundary) and the SQLite `'now'` trigger on `updated_at` (dropped; application owns the bump). V2 captures field separations that don't exist yet — `source_observed_at`, `last_confirmed_at`, staleness posture, import-vs-source time — but only when implementation pressure demonstrates the gap. The narrowed rule for continuity: *transparency over abstinence*. Any clock read that affects whether memory binds must be explicit or surfaced in the response; ambient clock reads are allowed at the boundary, not inside the kernel that decides whether memory still binds. Companion invariant across the constellation: *no timestamp may impersonate another timestamp.*
