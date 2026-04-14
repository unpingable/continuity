# Gap: Continuity Storage — tiered history that stays chain-walkable

**Status:** proposed
**Depends on:** none
**Related:** NQ's `HISTORY_COMPACTION_GAP` (dense numeric compaction — orthogonal; this spec is about audit-chain tiering, not value compression)
**Blocks:** nothing yet. Becomes load-bearing when the first busy project (likely NQ) reaches a size where "all history stays in the live SQLite DB forever" stops being a serious answer.
**Last updated:** 2026-04-14

## The Problem

Continuity's tables are append-dominated by construction: `memory_events` and `receipts` grow monotonically; `memory_objects` grows with every new memory and never shrinks (revoked objects stay as tombstones); `memory_links` grows with every premise written. Per-project DBs already localize blast radius — one noisy project does not bloat another — but within a single busy project the growth is real.

The projects most likely to surface this pressure first are operational/monitoring ones (NQ, observatory-family watchers), where investigations produce dense receipt chains and event streams faster than narrative projects do.

The gap is **not** that continuity needs compression for its own sake. The gap is that continuity has no formal tiering doctrine. When the first firehose project hits uncomfortable size, the system will improvise under pressure — which is how audit trails become folklore.

"Cold storage" in the naïve sense (tarball, offline, restore-to-query) is not an option here. Historical material in continuity is not disposable telemetry. It is:

- the receipt hash chain,
- the event lineage behind every memory transition,
- the premise/dependent graph `explain()` walks,
- the basis for `rely_ok` taint computation.

A receipt that cannot be walked from its successor is not cold, it is **severed**. That breaks the core invariant: *historical structure is never destroyed*.

## Design Stance

**Historical continuity is tierable. Auditability is not.**

Cold is allowed to be slower, more compact, segment-based, and manifest-addressed. It is not allowed to be opaque, unverifiable, non-walkable, or restore-before-query.

The right framing is not "how do we compress continuity" but **"which continuity objects need which latency class, and how do tier transitions preserve chain integrity?"** Different tables want different treatment, and one universal retention policy across every project is wrong from the start.

Per-project DBs remain the model. This gap adds tiers *within* a project's store, not a shared global substrate.

## Architectural Invariants

The following are frozen as doctrine. Downstream decisions depend on them. Revisiting any of these means revisiting the whole section, not cherry-picking.

### Chain preservation

1. **A chain that was walkable while hot must remain walkable after tiering.** Receipt predecessor/successor links, premise/dependent graph traversal, event-to-receipt relation, and `rely_ok` taint propagation all cross tier boundaries without ceremony. Latency may change; answerability may not.
2. **Hash chain bridges are first-class objects.** When a segment of receipts or events is tiered out, the tiering operation emits an explicit bridge record: last in-prior-tier hash, first in-moved-segment hash, segment manifest hash, operation receipt. "We moved it" is a historical act; treat it that way.
3. **Tier transitions produce receipts.** Moving history between tiers is a state change against the store's own metadata. It gets a receipt in the same chain as everything else. Tiering is not a meta-operation outside the audit surface.
4. **Cold data is immutable.** Once a segment is written and its bridge is verified, the segment is append-only by replacement, never in-place edit. Fix by emitting a new segment covering the range.

### Identity and discovery

5. **Manifest metadata lives outside the compressed payload.** Segment id, project id, class, generation/time range, first/last receipt hashes, first/last event ids, encoding, content hash, object counts — all queryable without decompression. The payload holds the dense body; the manifest holds enough identity to find, verify, and bridge.
6. **Cold segments are addressable without full restore.** A query that needs one incident's chain decompresses only the relevant segment(s). "Restore the whole cold tier and then ask" is not a supported access pattern.
7. **Cold is not exile from the logical surface.** Callers of `query`, `explain`, and `rely_ok` do not know which tier served the answer. They see one continuity surface. Tiering is a storage concern, not a reasoning burden.

### Audit preservation

8. **Receipt chain anchors stay hot indefinitely.** Even when receipt payloads tier cold, the minimal chain index (receipt_id, prev_hash, this_hash, covering-segment pointer) remains in hot local storage. Small hot indexes for cold bodies are cheaper than breaking chain walkability.
9. **Revocation must still taint tiered dependents.** A revoke event fires against a memory; any dependent in any tier whose `rely_ok` reads that memory's status must compute correctly. Taint does not stop at tier boundaries.
10. **Provenance and admissibility survive tiering intact.** Basis, reliance class, source refs, approval actors — all preserved in manifests or segment bodies, never elided for compression. Otherwise tiered history is narratively available but evidentially flat, which is not good enough.

### Policy and per-project doctrine

11. **Retention policy is per-project and per-class.** NQ, labelwatch, governor, and future projects do not produce the same volume or deserve the same hot window. Events may tier earlier than receipts; receipts may tier earlier than link anchors; high-firehose projects shrink hot windows sooner than quiet ones.
12. **A hot raw window is always retained.** Every project keeps some recent window fully hot, no matter what retention policy says. Debugging, codec rollout, and forensic edge cases require it.
13. **Tiering is opportunistic, not constitutional.** Some projects will never warrant tiering. The invariant is correctness and bounded operational cost, not "every store gets colder over time."
14. **Tier transitions are restart-safe and transactional.** A segment exists only if its manifest row, payload, bridge record, and tiering receipt all commit together. Process death mid-tiering leaves either intact hot data or a completed segment with a verified bridge. Never "history vanished into a half-written idea."

### Gap visibility

15. **Gaps are declared, not faked.** If a segment is unavailable, partial, or intentionally excluded from a tier, queries surface that as a declared gap rather than pretending completeness. Cold is allowed to be slow. It is not allowed to silently lie.

### Deliberately deferred (do NOT freeze in v1)

The following are explicitly not decided now. Revisit after v1 ships:

- Cross-project unified history search
- Remote object store integration (S3, etc.)
- Distributed continuity fabric
- Automatic relevance scoring over cold history
- Full-text archival search
- Cross-project dedup
- Tiering policy that auto-tunes per access frequency

## Data Classes

Continuity's tables do not all want the same treatment.

### Receipts

The audit spine. Hash-chained, append-only, queried during `explain()` and lineage walks. Volume grows with every observe/commit/revoke/tier event, but the per-row payload is small.

**v1 posture: stay hot.** Receipt tiering is the riskiest tier transition in the system and its volume is not the first pressure point. Defer until events are proven to tier cleanly.

### Events (`memory_events`)

The mutation log. Every state change writes one. Highest-volume table in busy projects. Queried by subject or time range; less commonly joined across the whole table.

**v1 posture: primary tier candidate.** Events are the most obvious size-pressure source and the least risky to segment. This is where the first hot→warm→cold path should be proven.

### Memory objects (`memory_objects`)

Materialized current state. One row per memory, including revoked tombstones. Grows with memory count, not with activity. Queried by id, scope, kind, status.

**v1 posture: stay hot.** Per-row cost is low and current-state lookups must stay fast. Revisit only if a project accumulates millions of tombstones.

### Links (`memory_links`)

Premise/dependent graph. Read during `explain()`. Active links colocate with their memory objects; revoked links stay as evidence.

**v1 posture: follow memory objects.** If memory objects stay hot in v1, so do links.

### Spool imports (`spool_imports`)

Async ingest tracking. Terminal states are fire-and-forget after reconciliation.

**v1 posture: lowest-sanctity tier candidate.** After a spool import reaches a terminal state older than some threshold, it can move warm or cold with minimal ceremony. A useful proving ground for the segment/manifest machinery.

## Tier Model

```
Tier 1: hot       — active SQLite tables, normal query path, recent window
          ↓ (background tierer, per-project policy)
Tier 2: warm      — compacted but still directly queryable locally
          ↓
Tier 3: cold      — immutable segments, manifest-addressed, bridge-linked
```

### Hot

The current SQLite store as it exists today. All normal reads and writes. Every project starts here and most projects never leave.

### Warm

Local, still queryable without manifest indirection, but with a compacted row layout or consolidated segment format. Optimized for range scans and reconstruction rather than frequent writes.

Warm is the cheapest win: no new storage tier, no remote dependencies, no decompression roundtrip for common queries. Most projects that ever need tiering will only need hot + warm.

### Cold

Immutable compressed segments with explicit manifests and bridge records. Queryable through manifest indirection: find relevant segment → load manifest → verify bridge → decompress only what's needed → reconstruct.

Cold is real continuity, not an archive dump. The segment format must preserve enough structure outside the compressed body to walk chains and verify integrity without decompression.

## Continuity Bridge

When data moves between tiers, the transition emits a **bridge record**:

- source tier, destination tier
- project id, store id
- covered time range and/or event id range
- last predecessor hash in prior tier
- first hash in moved segment
- segment manifest hash
- object count
- operation timestamp
- operation receipt id

The bridge is what lets a reader prove the chain did not break at the transition. Without bridges, tiering is chain amputation with better manners.

Bridges themselves live in a hot table (`tier_bridges` or similar) indefinitely. They are small and sacred.

## Manifest

Cold segments carry a manifest with enough identity to find, verify, and walk without decompression:

- segment id, project id, store id
- object class (receipts | events | spool_imports | ...)
- start/end time, start/end event id or receipt id
- first/last chain anchor hash (for receipts)
- encoding, compression type
- content hash
- object count
- optional sparse summaries for query pruning

Manifests live in a hot table (`cold_segments` or similar), scanned cheaply during query planning. The payload blob is only read when a query demands its contents.

## Query Semantics Across Tiers

A query arrives at the logical continuity surface. The planner:

1. Searches hot tables first.
2. Consults warm layout if the range or subject extends beyond hot.
3. Consults cold manifests if warm doesn't cover it.
4. Loads and decompresses only the cold segments whose manifests overlap the query.
5. Merges results, preserving tier provenance on the response.

Callers asking "why did this happen," "what did this rely on," "what preceded this receipt" never need to know which tier answered.

## V1 Slice

Keep the first implementation narrow. Doctrine is cheap; implementation is not.

1. **Tier vocabulary** in code and docs: hot, warm, cold.
2. **Bridge record table** and shape, even if only one transition class uses it in v1.
3. **Manifest table** and shape.
4. **One tierable class end-to-end**: events. Hot → warm is the minimum; hot → cold if the segment/compression path is straightforward.
5. **Tiering operation emits a receipt** on the same chain as observe/commit/revoke.
6. **Per-project retention policy surface**, even if initially hand-edited config.
7. **Query path** that walks at least one tier boundary for `query` and `explain`.

Receipts, memory objects, and links stay fully hot in v1. Spool imports may be the second tiered class if events go smoothly.

## Explicit Deferrals

Not v1:

- Receipt tiering (too sacred, not the first pressure point)
- Memory object tiering
- Link tiering
- Cross-project history search
- Remote/cloud cold storage
- Auto-tuning retention
- Full-text search over cold
- Delta sync between hosts

## Open Questions

1. **What's the minimum hot receipt-chain index when receipts eventually tier?** Probably (receipt_id, prev_hash, this_hash, segment_pointer). Freeze the shape before tiering receipts.
2. **Should events and spool imports share segment format?** Probably similar manifest shape, different payload encoding. Decide at v1.
3. **What's the warm layout?** Consolidated wide rows, or segment-in-hot-DB, or a separate local DB file? Decide when implementing.
4. **Does tiering itself get a `reliance_class`?** Probably `retrieve_only` at minimum — these receipts exist to be walked, not to be acted on.
5. **What's the minimum viable cold index granularity?** Per-segment manifest is probably enough for v1. Per-object sparse indexes can come later.

## Acceptance Criteria

This gap is closed when:

- The system has a named, documented tier model for continuity storage.
- At least one historical class can move hot → colder through an explicit, verified transition.
- Continuity bridges preserve chain walkability across tiers.
- Manifests make cold data discoverable and verifiable without decompression.
- `explain` and `query` can cross at least one tier boundary.
- Per-project retention policy is expressible.
- Compressed/segmented history remains queryable without full restore.
- Provenance and admissibility metadata survive tier transitions intact.
- Tier transitions themselves appear in the receipt chain.

## Short Version

The gap is not "we need compression."

The gap is that we need a storage doctrine for historical continuity that lets history get colder without becoming dead, opaque, or non-auditable. The scary part is not bytes. It's breaking the walkability invariant.
