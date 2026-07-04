# Roadmap

Continuity's internal roadmap. The constellation hub (`agent_gov/docs/roadmaps/README.md`)
coordinates across repos and keeps its own view of continuity
(`agent_gov/docs/roadmaps/tools/continuity.md`, slices R-CONT-1/R-CONT-2); this file is
the view from inside. It points at gap specs rather than restating them — a slice's
invariants live in its spec, its position in the queue lives here.

Written 2026-07-03 after a constellation survey (continuity, agent_gov, lean, spine,
standing, nq, linearaccountant). Revise when a slice lands or a consumer's forcing case
changes the order — not on a calendar.

## Where continuity stands

Shipped and green (231 tests): the observe/commit/revoke/repair/import lifecycle with
hash-chained receipts; `contctl` (init, bootstrap, workspace, observe/commit/revoke/
repair, query/latest/get/explain, import, `reliance verify`, case, export, stats,
`doctor --check premise-consistency`); 12 MCP tools; per-project/workspace/global store
resolution with island-topology warnings; cross-scope import with pinned premises;
time-discipline V1 (explicit `evaluation_time`, no ambient clock in the kernel); the
WLP persistence adapter (library-only); and `continuity.declaration_export.v0`
(`docs/DECLARATION_EXPORT_V0.md`).

Who consumes it today:

- **agent_gov** — `src/governor/doctrine.py`, a read-only Governor→Continuity edge
  (latest committed doctrine + `rely_ok` captured at consultation time, emitted into an
  observational gate receipt). This is the constellation's first wired cross-system
  edge and it pins a library surface — see `gaps/PINNED_CONSUMER_SURFACE_GAP.md`.
- **Claude sessions** — the MCP server, across the observatory-family workspace
  (agent_gov and standing both carry `.mcp.json` wiring).
- **WLP** — via the persistence adapter (`src/continuity/adapters/wlp.py`).

Who is about to: **Spine Slice 2c** consumes `continuity.declaration_export.v0` through
a `DeclarationSource`. Spine's 2b fixture predates the export contract; the
reconciliation is recorded in `docs/DECLARATION_EXPORT_V0.md` ("Consumer
reconciliation") and is bounded. Continuity is the prerequisite; the adapter work is
Spine's.

## Near-term slices, in order

1. **Consumer-surface contract tests** — **landed 2026-07-03.** V1 of
   [`gaps/PINNED_CONSUMER_SURFACE_GAP.md`](gaps/PINNED_CONSUMER_SURFACE_GAP.md):
   `tests/test_consumer_surface_ag.py` locks the exact surface agent_gov's
   `doctrine.py` stands on (five imports, six signatures, ten fields, plus the
   consumer's `str`/`float`/`dict`/`bool` coercions), so a breaking refactor fails in
   this repo before it silently kills the edge (the consumer deliberately degrades
   instead of failing). First because it is small, and because every later slice below
   touches code inside that surface.

2. **Spine 2c support** — golden fixture **landed 2026-07-03**
   (`tests/fixtures/declaration_export_v0_golden.json`, byte-locked by
   `tests/test_declaration_export_golden.py`); it also freezes the `ref = "<repo>:<path>"`
   split seam 2c maps on. Remaining: availability for questions while Spine writes the
   `DeclarationSource` in its own repo, and retiring the reconciliation note in
   `DECLARATION_EXPORT_V0.md` once 2c lands. The Spine-side adapter and `build_edition`
   refactor are Spine's work, not continuity's.

3. **USEFUL_REFUSAL_EXPLAIN V1** — **landed 2026-07-03.**
   [`gaps/USEFUL_REFUSAL_EXPLAIN.md`](gaps/USEFUL_REFUSAL_EXPLAIN.md): `RelyReasonCode`
   enum + `RelyState` (code + details + message), threaded additively through
   `explain`, case bundles, and the MCP explain payload, plus `contctl why` (verdict +
   code + specifics, non-zero exit on refusal). The flat `rely_ok`/`rely_reason` fields
   are derived from `rely_state` and unchanged, honoring the pinned-surface constraint
   (`rely_reason` stays str-renderable; agent_gov does `str(explained.rely_reason)`).
   Sequenced before the authoring-tier slice so tier-cap refusals land structured from
   day one. `tests/test_useful_refusal.py`.

4. **MEMORY_AUTHORING_TIER V1** — **landed 2026-07-04.**
   [`gaps/MEMORY_AUTHORING_TIER_GAP.md`](gaps/MEMORY_AUTHORING_TIER_GAP.md) (see its
   Implementation Notes for the deviations): the doctrinal centerpiece.
   `authoring_tier` upper-bounds `reliance_class`, enforced at write (over-cap commits
   refused) and re-applied at rely (`effective_reliance = min(stored, cap)`); the
   schema migration backfills existing rows honestly as `provenance_unknown` (never a
   false claim of agent authorship); custodian_signed is reachable only via
   `contctl adjudicate --reaffirm` (the custody path); `contctl doctor --check
   authoring-tier` flags cap violations and revoked-tier premises;
   `external_witness_ref` reserved (unpopulated) for the future NQ edge. Additive
   against the pinned surface — the flat `rely_ok`/`rely_reason` are unchanged, tier +
   effective reliance ride alongside. `tests/test_authoring_tier.py` (+ MCP coverage).
   `standing_contested` and automatic standing-loss detection remain deferred.

## Decide when triggered

**ProjectionReceipt graduation** (`candidates/PROJECTION_RECEIPT.md`). agent_gov
watches the candidate and will not adopt until continuity *ratifies* it. Its stated
graduation trigger is a real decode-skew incident or a second reader. Observation from
the survey: agent_gov's `doctrine.py` already implements the pattern's core discipline
— `rely_ok`/`rely_reason` captured at consultation time, never stored — which is
arguably the second reader arriving. Whether that satisfies the trigger is an operator
ratification call, flagged here, not made here.

## Named, not scheduled

Each has a spec; none has a forcing case at the front of the queue. Order here is not
a commitment.

- **Time-discipline V2** (`gaps/CONTINUITY_TIME_DISCIPLINE.md`) — `source_observed_at`
  **landed 2026-07-04** (the one pure-capture field; it was MapSkew's named substrate
  dependency). `last_confirmed_at` (needs a `confirm` producer) and the staleness
  gradient (taxonomy — do not invent preemptively) stay deferred. MapSkew
  (`candidates/MAP_SKEW.md`) advanced but does **not** graduate the comparator — see
  its Graduation Assessment.
- **Artifact Observer V0** (`gaps/MAPSKEW_OBSERVATION_SIDE_V0.md`) — **landed
  2026-07-04.** MapSkew's missing input surface: a read-only observer (`src/artifact_observer/`,
  its own package, zero continuity coupling) that emits one bounded artifact-state claim.
  Builds the light source, not the comparator — Continuity remembers, the observer
  observes, MapSkew (later) compares. Next toward MapSkew: a second dogfood in a
  different domain, and promoting the specimen into an identified permanent
  observation owner — neither manufacturable on demand.
- **Islands: declared domains and typed bridges** (`gaps/ISLAND_DISCIPLINE.md`,
  `gaps/CROSS_ISLAND_BRIDGES_GAP.md`) — manifest `purpose`/`bridge_policy`,
  `contctl domain`, receipted `bridge import`. Visibility V1
  (`gaps/ISLANDS_OF_CONTINUITY.md`) is partially landed (`where` warnings,
  `--allow-island`, MCP startup topology log).
- **Orient hook** (`gaps/CONTINUITY_ORIENT_HOOK.md`) — `contctl orient`,
  `lint-promotion`, read-side advisory.
- **Storage tiering** (`gaps/CONTINUITY_STORAGE_GAP.md`) — hot/warm/cold that stays
  chain-walkable.
- **WLP RevocationReceipt persistence + any transport surface** — explicitly deferred
  out of the shipped adapter (`gaps/WLP_PERSISTENCE_ADAPTER_GAP.md`).
- **`contctl refresh` / `memory_refresh`** — source-reachability checks, deferred from
  `gaps/CROSS_COMPONENT_RELIANCE_GAP.md`.
- **NQ witness wiring** — `external_witness_ref` stays a reserved column until the NQ
  cross-system edge is real (per the authoring-tier spec's deferrals).

Deliberately absent, reaffirmed: vector search, LLM summarization, distributed
anything, automatic invalidation cascades, inferred links (see `../CLAUDE.md` and
`concepts.md`, "What Continuity Is Not").

## Standing constraints on everything above

- Retrieval is not authority; `reliance_class` governs what may be relied on.
- `rely_ok` advises, never authorizes. The constraint agent_gov states from its side,
  binding here too: *a linked memory never upgrades a verdict.*
- The declaration export is the envelope, never the verdict; no authority-shaped field
  crosses it.
- Formal citations go to lean's `AdmissibilityKernels` (`Admissibility.Kernels`) —
  never the deprecated `CalculusOne` shim (removed in lean 2.0), never annex or
  scratch modules. Lean names continuity a consumer of `ConsolidationDenial`
  (fluency ≠ settlement) and of the `WitnessInvariance` check-construction primitive.
