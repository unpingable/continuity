# Gap: Cross-Island Bridges — transfer intent, disposition, and admissibility

**Status:** proposed
**Depends on:** `ISLAND_DISCIPLINE` (declared domains, bridge primitive, imports start as observed), `CROSS_SCOPE_REFERENCE_GAP` (content hashing, import receipts, cross-DB identity)
**Related:** `ISLANDS_OF_CONTINUITY` (the visibility prerequisite — bridges presuppose declared topology)
**Last updated:** 2026-04-26

## The Problem

`ISLAND_DISCIPLINE` establishes that bridges between declared continuity domains are typed, non-transitive, receipted imports — and that imports always land as `observed` regardless of source reliance. That is the right substrate, but it stops one layer short of where actual operator decisions live.

Today a bridge import event records *that* a crossing happened. It does not record:

- **why** the thing was crossing (a doctrine candidate? a citation in support of a paper claim? a stale-claim revocation? a public-language proposal? the creation of a scope fence?)
- **what happened after inspection** (verified against the target island's source of truth and promoted? quarantined as observed-but-non-reliant? blocked by an existing fence? superseded by a local commit? rejected outright?)
- **how scope fences interact with point-in-time bridge events** — the existing schema can record that a fence was created or that a transfer was blocked, but cannot answer "what fences am I subject to right now" without event-log scanning, which is exactly what the materialization layer exists to avoid.

The result is a class of failure where the receipt chain is intact but the semantics are mush. A vivid book sentence and a load-bearing engineering requirement and a tentative LLM synthesis all look like the same generic `memory.import` event from outside. The operator has to reconstruct intent and disposition from prose, which is the failure mode islands were declared in order to prevent. This bit on 2026-04-25 in the book/paper/implementation island design conversation: a stale book-claude memory ("Ch 11 is the primary Administrative Queue target") was the thing the bridge machinery exists to surface and revoke, but without admissibility classification on import, the system would record only that "something crossed" — no way to query "what classes of claim are pending verification" or "what was just superseded."

This gap formalizes the layer above `ISLAND_DISCIPLINE`: how cross-island transfers carry intent, how their dispositions are recorded, where scope fences live, and what Governor may and may not adjudicate at the crossing.

## Design Stance

**Capture intent at the crossing, classify disposition at admissibility, and never collapse the two into a single state machine.**

A bridge transfer has three orthogonal axes:

- `transfer_type` — *why* the claim is crossing (intent, declared at event time)
- `reliance_class` — *how much* the target island is permitted to trust it (existing primitive, governs downstream rely_ok)
- `disposition` — *what happened* after the target island inspected it (outcome, recorded on the event that produced the current status)

These three must never collapse into each other. Mixing intent with outcome rots the model; mixing trust ceiling with intent rots the rely gate; mixing outcome with status creates a parallel state machine the schema does not need.

The corollary is the capture-vs-index distinction: structured capture of `transfer_type` and `disposition` is mandatory from the first bridge event, with provisional enums and an `unknown/freeform` escape valve. Indexing, enum closure, and required verification flows are promotion decisions that wait for observed usage to justify them. Capture is correctness; indexing is performance. Conflating them is the enterprise observability sin: "we'll instrument it after we see what happens." By then the data is prose mush.

Scope fences are dual: they are *events* (creation, application) and they are *standing constraint memories* (the materialized current set of fences this island is subject to). Without the standing representation, "what am I allowed to import?" requires event-log archaeology, which defeats the materialization layer. Without the event representation, the receipt chain loses the moment of fence creation and the moment of fence application.

Governor's role at the crossing is narrow: it adjudicates bridge admissibility (does this transfer have standing, evidence, an owner, and the verification its `transfer_type` requires?) and procedural consequence (may it acquire reliance or consequence in the target?). Governor does not confer epistemic standing inside any domain island. Local domain authority remains local. Otherwise Governor accidentally becomes Pope of Book Claude, Ops Claude, and the vibes district — operationally cursed, even if thematically funny.

## Architectural Invariants

### The three orthogonal axes

1. **`transfer_type` captures *intent at crossing*.** It is a structured payload field on the bridge event, with a provisional enum and an `unknown/freeform` escape valve. Every cross-island import classifies its intent. No event of this class lacks one.
2. **`reliance_class` captures *how much the target may trust*.** This is the existing primitive (`none` / `retrieve_only` / `advisory` / `actionable`). It is not extended by this gap. Bridge imports default to `none` regardless of source `reliance_class` — commitment does not travel.
3. **`disposition` captures *what happened to the transfer after inspection*.** It is a structured payload field on the event that produces the current memory_object status. A `pending` import has no disposition yet; a verified import has `disposition=verified` with `verified_against=<reference>`; a fence-blocked import has `disposition=scope_fenced` with `fence_id=<constraint memory_id>`; and so on.
4. **The three axes do not collapse.** `transfer_type` is not a relation, `reliance_class` is not an outcome, `disposition` is not a trust ceiling. Tooling and queries treat them independently. Mixing them is a category error and should be rejected at code review.

### Capture before index

5. **Capture is mandatory from event one.** `transfer_type` and `disposition` are required structured fields on cross-island bridge events, with `unknown` + freeform `detail` permitted as escape valves. There is no "park it and add later" option — by definition, deferred capture loses the data the system was built to preserve.
6. **Indexing, enum closure, and required verification flows are promotion decisions.** They wait for observed bridge usage. Promotion criteria are: a meaningful number of real cross-island events (~10+) with a diverse spread of `transfer_type` and `disposition` values; observed query patterns that justify indexes; observed misuse patterns that justify closing the enum or requiring verification chains for specific `transfer_type` values.
7. **Provisional enums are explicitly provisional.** Both enums are versioned and may grow without ceremony in v1. Promotion to "closed" is a later, deliberate act — not a side effect of someone removing the freeform escape.

### Lifecycle without a new state machine

8. **No new lifecycle column.** The apparent lifecycle states (`pending` / `verified` / `promoted` / `rejected` / `revised` / `scope_fenced` / `revoked` / `superseded`) are derived from the combination of `memory_object.status` (`observed` / `committed` / `revoked`) and the `disposition` recorded on the event that produced the current status. No parallel state machine.
9. **The bridge sequence shape:**
   - **import event:** creates `memory_object` with `status=observed`, `basis=import`; payload carries `transfer_type=<X>`, `target_status=pending`, optional `verification_required=true`.
   - **verification event (commit-shaped):** transitions `status=observed → status=committed`; payload carries `disposition=verified`, `verified_against=<reference>`. Optional concurrent reliance_class promotion under target standing.
   - **fence-blocked event (revoke-shaped):** transitions `status=observed → status=revoked`; payload carries `disposition=scope_fenced`, `fence_id=<constraint memory_id>`, `reason=<text>`.
   - **rejection event (revoke-shaped):** payload carries `disposition=rejected`, `reason=<text>`.
   - **revision event (commit-shaped, on a new memory_object):** the new object's `supersedes` points to the import; payload on the supersession event carries `disposition=revised`.
10. **The existing schema carries this.** No new tables, no new columns on memory_objects or memory_events. The `payload_json` field on events is the home for `transfer_type` and `disposition`.

### Scope fences: dual representation

11. **`transfer_type=scope_fence` means the thing crossing IS itself the creation of a fence.** The bridge event payload carries the fence's predicate (what class of claim it blocks) and the resulting standing constraint memory_id.
12. **`disposition=scope_fenced` means a different transfer was blocked by an existing fence.** The event payload carries `fence_id=<the constraint memory_id whose predicate matched>`. This event sits on the *blocked* transfer's memory_object, not on the fence itself.
13. **Standing fences are materialized as `kind=constraint` memories in the target island.** Their `content_json` carries the fence predicate and creation provenance. They are queryable as "what fences bind this island right now" without scanning the event log. This is the materialization invariant from the rest of continuity, applied consistently to fences.
14. **The fence creation event references the constraint memory_id.** The constraint memory's creation provenance points back to the import event. Bidirectional walkability, same shape as existing memory_links provenance.
15. **Fence revocation is a normal revoke event on the constraint memory.** A revoked fence does not retroactively un-block prior transfers it blocked — those `disposition=scope_fenced` events stay as evidence. Going forward, the fence no longer applies.

### Governor's narrow role

16. **Governor adjudicates bridge admissibility — not domain truth.** It can rule that a cross-island transfer lacks standing, evidence, an owner, or the verification its `transfer_type` requires. It cannot rule on whether a claim is the correct reading of Chapter 12, the correct formalization strategy, or the correct chapter placement. Local island authority remains local.
17. **Governor adjudicates procedural consequence at the crossing.** Whether a transfer may *acquire* reliance or consequence in the target is a procedural question (does it meet the rules of admissibility?). Whether the reliance is then *correct* is a substantive question (is the claim true under the target's standards?) — that stays inside the target island.
18. **Governor does not own bridge state.** Bridge events and constraint memories live in the relevant continuity domains. Governor reads them to adjudicate; it does not mutate them. This preserves the existing rule that Governor mediates action across tools but never owns shared substrate.

### Legacy migration: graduated quarantine as default

19. **Legacy memory loads into a new island as `observed`/non-reliant by default.** This is "graduated quarantine": existing claims are visible and queryable but cannot ground reliance until explicit triage produces a commit, revocation, scope_fence, or supersession.
20. **Bridges may light up during graduated quarantine.** Letting external claims arrive while triage is in progress preserves signal — an external "I think Ch 12 is the target" can be the prompt that triggers revocation of a stale local "Ch 11 is the target." Forbidding bridges until triage clears would lose that loop.
21. **Strict quarantine remains an option per source or per scope.** Legacy regions with compromised provenance, schema drift, or known untrustworthy origins can be flagged for strict quarantine — no imports accepted until the region is cleared or fenced. Strict is opt-in, not default.
22. **Triage produces the seeding revocation events.** The Ch 11 / Ch 12 correction is the canonical first scar: a real revocation with a real cause and a real correction, embarrassing in exactly the useful way. Synthetic seeds do not exercise the revocation machinery the way real corrections do.

### The bridge operations are a typed surface, not a CLI shorthand

23. **Bridge import, disposition, fence creation/application, and triage are typed library/MCP operations.** The CLI is one face; programmatic callers use the same underlying primitives without the CLI in the loop. Both surfaces produce identical events, payloads, receipts, and constraint memories. The typed shape is load-bearing because downstream consumers (programmatic basis inspectors, automated triage assistants, doctrine linters) need to invoke the operations directly — without parsing CLI output or shelling through a process boundary that strips type information.
24. **No business logic lives in the CLI layer.** The CLI is a thin wrapper over the typed ops. This is a precondition for downstream consumers to be substitutable for human invocation; if the CLI carried logic, the underlying ops would be a leaky surface and consumers would re-implement business logic in their own callers — exactly the rot pattern the bridge primitives exist to prevent.

## Data Shape

No schema changes. This gap lives entirely in the event payload and in the discipline around how `kind=constraint` memories are used for fences.

**Bridge import event payload (extends `ISLAND_DISCIPLINE`'s `memory.imported` event):**

```json
{
  "source_domain_id": "chatty",
  "source_domain_purpose": "bridgeable",
  "source_memory_ref": { "...content-hash pinned, per CROSS_SCOPE_REFERENCE_GAP..." },
  "target_scope": "book",
  "transfer_type": "doctrine_candidate",
  "transfer_detail": "Ch 12 §Administrative Queue is primary Latent Leviathan controlled-burn target",
  "target_status": "pending",
  "verification_required": true,
  "verified_against": null
}
```

**Verification event payload (commit-shaped, on the imported memory_object):**

```json
{
  "disposition": "verified",
  "verified_against": "manuscript/ch12",
  "promoted_reliance_class": "advisory"
}
```

**Fence creation event payload (`transfer_type=scope_fence`, creates a `kind=constraint` memory in target):**

```json
{
  "transfer_type": "scope_fence",
  "fence_predicate": {
    "claim_class": "metaphysics",
    "rationale": "Paper 22 scope: no metaphysics admitted as implementation doctrine"
  },
  "constraint_memory_id": "mem_abc123..."
}
```

**Fence application event payload (revoke-shaped, on a blocked transfer):**

```json
{
  "disposition": "scope_fenced",
  "fence_id": "mem_abc123...",
  "reason": "Claim class matches Paper 22 metaphysics fence; not admissible to implementation island."
}
```

**Provisional `transfer_type` enum (v1):**

`analogy` · `doctrine_candidate` · `implementation_requirement` · `citation_support` · `chapter_placement` · `public_language` · `stale_claim_revocation` · `scope_fence` · `unknown` (with required `transfer_detail` freeform field)

**Provisional `disposition` enum (v1):**

`pending` · `verified` · `promoted` · `rejected` · `revised` · `scope_fenced` · `revoked` · `superseded` · `unknown` (with required `disposition_detail` freeform field)

## V1 Slice

1. **Extend the `memory.imported` event payload schema** with required `transfer_type` and optional `target_status` / `verification_required` / `verified_against` fields. Provisional enum + `unknown`+freeform.
2. **Add `disposition` to the payload schema** for events that resolve a pending bridge import (commit, revoke, supersession produced by triage). Provisional enum + `unknown`+freeform.
3. **Implement scope_fence dual:** a bridge event with `transfer_type=scope_fence` creates a `kind=constraint` memory in the target island carrying the fence predicate. The constraint memory_id is recorded in the event payload. Subsequent transfers that are evaluated against the fence record `disposition=scope_fenced` with `fence_id`.
4. **Implement graduated quarantine for legacy migration:** a `contctl bridge migrate-legacy --from <legacy-store> --to <new-island>` command imports existing memories with `target_status=pending`, `reliance_class=none`, and a generated triage queue. Strict quarantine is the `--strict` flag.
5. **Triage commands:** `contctl bridge triage list <scope>` shows pending; `contctl bridge triage promote <memory_id> --verified-against <ref>` produces the verification event; `contctl bridge triage revoke <memory_id> --reason <text>` produces the revocation; `contctl bridge triage scope-fence <memory_id> --fence-id <fid>` records the fence application.
6. **Ch 11 / Ch 12 seeding:** the migration of book-claude's existing memory should produce the Ch 11 → Ch 12 revocation as its first concrete triage outcome. This becomes the canonical example in tests and documentation.
7. **Tests:** every `transfer_type` × `disposition` combination round-trips; constraint memories materialize from fence creation events; legacy loads default to graduated quarantine; bridges that arrive during quarantine land as `observed` and inform triage; receipt chains stay walkable across import → verification → optional supersession.

## Deliberately out of scope (v1)

- **Indexing on `transfer_type` or `disposition`.** Wait for observed query patterns. The capture is the load-bearing decision; indexing is a later promotion.
- **Closing the `transfer_type` or `disposition` enums.** Both stay open with `unknown`+freeform escapes until usage justifies closure.
- **Required verification flows per `transfer_type`.** E.g., should `implementation_requirement` require a verification chain pointing to a named authority? Defer until at least 10 real bridges show whether this is necessary.
- **Strict quarantine as default.** Graduated is the default. Strict remains opt-in per source or per scope.
- **Governor-side automation of bridge admissibility.** v1 surfaces admissibility metadata; Governor's automated adjudication policies live in Governor's repo and use this gap's primitives. This gap does not encode adjudication rules.
- **UI for triage workflow.** CLI is sufficient for v1. TUI sequencing follows `HITL_entrypoint_scoping` discipline (polish CLI first, TUI after demonstrated need).
- **Multi-source bridge transactions** (a single triage decision that resolves against multiple incoming claims). Each bridge event is independent in v1.
- **Fence inheritance across domains.** A fence in island A does not automatically install in island B even if B imports from A. Fences are local policy. Cross-island fence sharing, if needed, is a future gap.

## Acceptance Criteria

- Every cross-island bridge event carries a `transfer_type` value (or `unknown`+freeform) — no events without intent classification.
- Every disposition event records `disposition` (or `unknown`+freeform) with the appropriate references (`fence_id`, `verified_against`, etc.).
- A bridge import lands as `status=observed`, `reliance_class=none` regardless of source `reliance_class`. Verification events are the only path to `committed`.
- "What fences am I subject to in island X" is answerable by querying `kind=constraint` memories in X — no event-log scan required.
- A `transfer_type=scope_fence` event creates a corresponding constraint memory; revoking the constraint memory does not retroactively un-block prior `disposition=scope_fenced` events.
- Legacy migration via `contctl bridge migrate-legacy` defaults to graduated quarantine; the `--strict` flag flips to strict per scope.
- Ch 11 / Ch 12 revocation is the first triage example exercised in book-island tests.
- Governor can read bridge admissibility metadata (`transfer_type`, `target_status`, `disposition`, fence applicability) but cannot mutate domain-internal commitment status. The schema does not provide a Governor-only mutation path.
- The three axes (`transfer_type` / `reliance_class` / `disposition`) are independently queryable and never collapsed into a single state machine in any code path.

## Open Questions

1. **Strict vs graduated quarantine — per island or per source?** Graduated is the default; strict is opt-in. The opt-in granularity (per island, per source, per scope, per transfer_type) is unsettled. Pick when a real strict-quarantine case appears.
2. **Constraint memory scope for fences.** Does a fence live in the target island's local scope, in a `cross_island_policy` scope, or both? The querying side cares; the writing side may not. Defer to implementation-time when the first real cross-island fence is being created.
3. **Promotion criteria for indexing `transfer_type` / `disposition`.** Probably 10+ diverse cross-island events plus observed query patterns. Concrete threshold deferred until the data exists to make the call.
4. **Required verification flows per transfer_type.** Should `implementation_requirement` require a verification chain pointing to a named authority? Should `chapter_placement` require a manuscript-source pin? Defer; let observed misuse drive the rule, not anticipated misuse.
5. **Governor's adjudication contract.** Does Governor *block* an inadmissible crossing entirely, or *annotate* it with low standing and let the target island decide? Probably annotate-then-let-target-decide for v1, with hard block as a later policy decision once Governor's authority surface is more settled.
6. **Cross-island fence sharing.** If island A declares "no metaphysics admitted as implementation doctrine," should island B (a different implementation island) inherit that fence by default? v1 says no — fences are local policy. A future gap may revisit if the constellation grows multiple implementation islands with shared scope.
7. **Reliance promotion under verification.** When a verification event flips `status=observed → committed`, can it concurrently set `reliance_class` higher than `none`? v1 allows it under target standing. Whether Governor's bridge-admissibility role also gates reliance promotion (vs only gating commit) is open.
8. **Programmatic consumers of this surface.** A motivating downstream consumer is a cross-island basis inspector ("Basis Walker") that would call bridge ops programmatically to assemble cross-island evidence packets for validator consumption — bounded by declared topology, with typed operations only, emitting validator-shaped basis records rather than authority claims. This gap does not specify Basis Walker; it does ensure the bridge surface is callable by such a consumer. The detailed shape, depth caps, typed-op vocabulary, and admissibility constraints of any such consumer live in its own design artifact, not here.

## Revision trigger

Revise this gap when implementation pressure proves it underspecified — not when downstream events merely happen.

The likely revelation moments: the first typed bridge-op surface lands and exposes a missing invariant; the first attempt to promote an observed bridge to committed reliance hits a state combination this gap doesn't decide; an early `scope_fence` creation surfaces a fence-predicate shape the data model can't carry; a triage operation needs a disposition the provisional enum doesn't cover and `unknown`+freeform turns out to be insufficient. The trigger in each case is *"I tried to use this and it didn't tell me what to do"* — not "X happened, time to revisit."

Calendar-driven review is explicitly avoided, and event-driven review without evidence of underspecification is too. Revision is bound to demonstrated friction. The gap-spec stays as written until something actually breaks against it.

## Short Version

A bridge isn't just an import event. It carries intent (`transfer_type`), trust ceiling (`reliance_class`), and outcome (`disposition`) on three orthogonal axes that must never collapse. Capture all three at event time with provisional enums and `unknown`+freeform escapes; defer indexing, enum closure, and required verification flows until observed usage justifies them. Scope fences live twice — as creation and application events on the bridge, and as standing `kind=constraint` memories that make "what fences am I subject to" queryable without log archaeology. Lifecycle is derived from existing `memory_object.status` plus event payload `disposition` — no new state machine. Governor adjudicates bridge admissibility (does the crossing have standing, evidence, an owner, and the verification its transfer_type requires?) and procedural consequence; it does not confer epistemic standing inside any domain island. Legacy memory loads as graduated quarantine — observed-but-non-reliant during triage — letting external claims help inform local correction without granting them authority. The Ch 11 / Ch 12 revocation is the canonical first scar. Concepts can cross islands. Authority cannot cross without a receipt.
