# Gap: Memory Authoring Tier — provenance distinct from reliance

**Status:** V1 implemented 2026-07-04 (`tests/test_authoring_tier.py`) — see Implementation Notes below
**Depends on:** None at the substrate layer (orthogonal to `CROSS_SCOPE_REFERENCE_GAP`).
**Related:** Composes with `CROSS_COMPONENT_RELIANCE_GAP` (reliance shape at the cross-host layer — receipts gain a `tier_drift` status), `CONTINUITY_TIME_DISCIPLINE` (rely is replayable, so tier-cap must be re-checkable at replay), `PREMISE_CONSISTENCY_DOCTOR` (doctor seam for tier-violation detection follows the same shape). Doctrine source: the constellation map of 2026-06-03 (nine roles × four refusal kinds × mutation discipline per tier) and the keystone invariant *"no actor is authoritative over what it authors — including what it authors into its own past."*
**Blocks:** any downstream consumer that needs to distinguish *can remind* from *can bind*. Today no such distinction exists in continuity. Wicket, Nightshift, Standing, and a future Governor cannot tell which memory entries carry binding force vs advisory force.
**Last updated:** 2026-06-03

## The Problem

Continuity carries two enums today: `reliance_class` (`none`, `retrieve_only`, `advisory`, `actionable`) and `basis` (`direct_capture`, `operator_assertion`, `inference`, `import`, `synthesis`). It also carries `created_by: ActorRef` and `approved_by: ActorRef` as informational fields. None of these answer the load-bearing question:

> *Who authored this memory, and what force is it allowed to have later?*

The dangerous failure mode is not memory forgetting. Omission is survivable: a forgotten obligation eventually surfaces as an incident. The dangerous mode is memory *remembering wrong* — commission:

> The agent writes a "lesson" at t0: *we established that staging deploys do not need tickets*.
> At t1 the entry is read back as standing policy.
> Provenance has blurred. The entry arrives wearing the authority of the past — the one witness that cannot be cross-examined.

This is the prime laundering channel in the whole constellation: **agent-authored content acquiring binding force through persistence**. Continuity is the only role where the laundering channel runs *through time* — every other role (Standing, Wicket, NQ, Verifier, Agent Governor, Linear Accountant, Execution, Nightshift) polices synchronous moves. Time blurs provenance, and the blur is the attack.

Existing fields gesture at the problem but do not enforce it. An agent-authored entry can be written today at `reliance_class=actionable`. There is no read-back rule that distinguishes *can remind* from *can bind*. There is no machinery that surfaces tier on query results. There is no audit trail when stored reliance exceeds what the authoring tier should permit.

## Design Stance

Three operator keepers anchor the design. They are preserved verbatim in any consumer documentation that cites this gap:

> **Memory preserves provenance or memory launders authority. There is no third setting.**

> **No actor is authoritative over what it authors — including what it authors into its own past.**

> **Continuity remembering something wrong can mint a constitution while everyone is looking at the floor.**

A complementary keeper for the read seam:

> **Read at authoring tier, never above it.**

Together they rule out three failure modes the alternative shapes would invite. The first treats provenance as cosmetic metadata — `created_by` populated but not consulted by rely. The first keeper rules this out: provenance either binds reliance or it is laundering by default. The second conflates capture method with authority — collapsing `basis` and tier into one field, letting `operator_assertion` quietly become an actionable claim. The second keeper rules this out: an agent transcribing an operator's words is not the operator. The third pretends the agent is a stable authority over its own prior writes. The keystone rules this out: a remembered conclusion is a minted policy unless something else certified it.

## Non-goals

Continuity is **not**:

- An identity service. Tier names *roles* (agent, runtime, custodian-signed, revoked); it does not authenticate principals. Standing decides who is in each role.
- An automatic invalidation cascade. When an author later loses standing, prior entries enter a *contested* state for explicit adjudication, not automatic discharge or automatic survival.
- A retroactive sanitizer. Existing rows are not relabeled to claim authoring tiers their writes never carried. Pre-doctrine rows are honestly labeled `provenance_unknown`.
- An external witness substrate. The "NQ witnesses continuity writes" edge is named here for future composition; V1 does not build it.
- A policy engine over `basis`. `basis` and `authoring_tier` stay orthogonal — see invariant 4.

## Architectural Invariants

### Authoring tier and reliance

1. **Every memory entry carries an `authoring_tier`.** Five values:

   | Tier | Meaning |
   | --- | --- |
   | `agent_authored` | Written by the running agent / LLM / model session. |
   | `runtime_authored` | Written by a tool, runtime, or operational sensor — deterministic source under no semantic discretion. |
   | `custodian_signed` | Written under an explicit custody event with an attached signature record. |
   | `revoked` | Author's standing has ended; entry retained as history, not as live authority. |
   | `provenance_unknown` | Honest backfill label for pre-doctrine rows. See invariant 3. |

2. **Authoring tier upper-bounds reliance class.** The cap is enforced at write time and re-applied at read/rely time:

   | Tier | Maximum reliance_class |
   | --- | --- |
   | `provenance_unknown` | `retrieve_only` |
   | `agent_authored` | `advisory` |
   | `runtime_authored` | `advisory` |
   | `custodian_signed` | `actionable` |
   | `revoked` | `none` (history only) |

   Writes whose requested reliance exceeds the cap are refused with a useful refusal (the cap rule, the tier, the requested reliance). Rows whose cap is later tightened (e.g. tier downgrade after standing loss) keep their stored reliance_class but `rely_ok` returns the capped value.

3. **Pre-doctrine rows are backfilled as `provenance_unknown`, not as `agent_authored`.** "Agent-authored" is a *claim* the schema would be falsely attesting to. "Provenance unknown" is the honest state. The migration ratchets the cap; it never mints new authority. This is the same discipline as treating an imported memory as a witness copy, not a fork.

### Basis vs tier

4. **`basis` and `authoring_tier` are orthogonal.** `basis` answers *how the claim was formed* (capture, assertion, inference, import, synthesis). `authoring_tier` answers *who is allowed to make it binding later*. They share no enum values and no enforcement paths. An `operator_assertion` can be `agent_authored` (the agent transcribed the operator without custody machinery) or `custodian_signed` (a signing custody event is attached). Same basis, different tier, different reliance ceiling. Collapsing them into one field is how the gremlin gets tenure.

### Read discipline

5. **Read at authoring tier, never above it.** `query`, `query_latest`, and `get` results carry `authoring_tier` and `effective_reliance` in the response payload. `effective_reliance = min(stored_reliance_class, tier_cap)`. Consumers receive the gap explicitly rather than silently inheriting a stale reliance label.

6. **Useful refusal at the query surface, not silence.** A query result whose `effective_reliance` falls below an action threshold returns the result *and* a refusal-to-bind reason that names the cap rule. The same shape as the existing `USEFUL_REFUSAL_EXPLAIN` discipline — refusals are evidence, not omission.

7. **`explain` surfaces tier weakness in the premise walk.** When `explain` traverses a memory and its premises, it surfaces any premise whose `effective_reliance` is weaker than what the dependent is using it for. Named separately from content drift; same shape (drift is a known status, tier weakness is a known status).

### Custody events

8. **Tier promotion requires a custody event.** Moving an entry from `agent_authored` to `custodian_signed` is not an edit. It is a new event that names the custodian, attaches a custody record, and writes a receipt. The substrate stores a `custody_event_id` reference and treats the signing mechanism as opaque — the cryptographic shape (HSM, GPG, ed25519, ceremony manifest) is decided per-deployment. Until a real custody mechanism exists, custodian-signed entries can be produced only via an explicit admin path, not via routine API calls.

9. **Promotion creates a new memory object; the original is preserved.** Tier promotion produces a new `memory_objects` row whose `supersedes` points at the original. The original is marked revoked-by-promotion (not destroyed). History stays walkable. This composes with the existing supersede pattern; it does not invent a new one.

### Standing-loss policy

10. **Standing loss places prior obligations into `standing_contested`, not automatic survive or automatic discharge.** When an actor whose entries carry binding force loses standing, their `custodian_signed` entries flip to a contested marker (substrate detail: an event of type `standing_contested`, not a tier mutation in place — events are append-only). Contested entries return `effective_reliance = retrieve_only` until a custodian adjudicates them via *re-affirm* (new custody event, restored binding) or *retire* (explicit revocation, becomes history).

    Default for unattended contested entries is *do not bind*. Survive-by-default leaves booby traps; discharge-by-default lets revocation erase history; contested-by-default preserves evidence without granting it automatic control. This is the third-option-by-construction shape: the substrate does not pretend the question has a quiet answer.

### External witness (named, deferred)

11. **NQ will eventually witness continuity writes.** The substrate-side hook is reserved: each write event carries an `external_witness_ref` field that V1 does not populate. When the NQ cross-system edge lands, that field carries the NQ receipt ID. Naming the hook now means the schema does not require retrofit when the edge ships.

## V1 Slice

V1 ships the doctrine, the smallest substrate surface that proves it, and an honest migration. No external witness work.

1. **Schema** — `authoring_tier` column added to `memory_objects` and `memory_events`. Enum check constraint on the five values. Index on `(scope, authoring_tier)` for the doctor query. Reserved `external_witness_ref TEXT NULL` column on `memory_events` (invariant 11).
2. **Models** — `AuthoringTier` enum. `MemoryObject`, `MemoryEvent`, `ObserveRequest`, `CommitRequest`, and the corresponding response payloads gain the field. No implicit default at the substrate; callers declare tier explicitly.
3. **Cap enforcement** — `MemoryPolicy.tier_cap(tier) -> RelianceClass` defines the cap table from invariant 2. Write paths refuse if `requested_reliance > tier_cap(tier)` with a useful refusal. `rely_ok` re-applies the cap and returns `effective_reliance = min(stored, cap)`.
4. **Migration** — schema bump. All existing `memory_objects` and `memory_events` rows backfilled with `authoring_tier = provenance_unknown`. Stored `reliance_class` is left at its previously-stored value; `rely_ok` returns the capped value going forward.
5. **Query surface** — `query`, `query_latest`, `get` return `authoring_tier` and `effective_reliance`. `explain` surfaces tier weakness on premises.
6. **MCP surface** — `memory_observe` and `memory_commit` accept an `authoring_tier` argument. `memory_query`, `memory_query_latest`, `memory_get`, `memory_explain` return tier and effective reliance.
7. **CLI** — `contctl memory observe / commit / query / get / explain` accept and surface `--authoring-tier`.
8. **Doctor** — `contctl doctor --check authoring-tier` flags entries whose stored `reliance_class` exceeds their `tier_cap` (legacy rows are fine; the cap takes over), surfaces `standing_contested` entries awaiting adjudication, and flags `revoked`-tier entries that are still cited as active premises.
9. **Adjudication path** — `contctl memory adjudicate <memory_id> --reaffirm --custody-record=<path>` and `--retire`. Reaffirm produces a new custody event; retire produces a revocation event. UI for richer review is deferred.
10. **Test corpus** — happy paths for each tier; refusal at cap exceedance with the rule named in the refusal; standing-loss → contested transition with adjudication both ways; explain surfacing tier weakness; doctor detection of each violation class; migration backfill correctness.

## Explicit Deferrals

Named so retrofit is bounded.

- **Custody event signature mechanism.** V1 stores a `custody_event_id` reference; the cryptographic shape is a future gap once a real custody mechanism is chosen.
- **NQ external witness wiring.** V1 reserves `external_witness_ref`; integration is a future cross-system gap.
- **Automatic standing-loss detection.** V1 requires explicit revocation of the actor (a separate admin operation); push-based standing-loss notifications and Standing-side propagation are out of scope.
- **Rich adjudication UI.** V1 ships the CLI adjudication path; a TUI/web review surface follows the existing HITL-entrypoint sequencing.
- **Tier downgrade by voluntary author action.** V1 supports tier *upgrade* (via custody event) and tier *retirement* (revoked, standing_contested). A custodian voluntarily lowering their own entries' binding force is a real motion but not yet specified.
- **Cross-host tier sync.** When a tier-bearing memory is imported across stores via `CROSS_SCOPE_REFERENCE_GAP`, V1 carries the tier in the import record. Cross-host *re-adjudication* (propagating contest/reaffirm decisions) is out of scope; receiving stores re-check the cap locally.
- **Receipt-side `tier_drift` status.** A natural composition with `CROSS_COMPONENT_RELIANCE_GAP`'s `relied_on` verification (a receipt cites an entry at a reliance the entry's current cap no longer permits). Named here so the sibling gap inherits it; not implemented in this V1.

## Open Questions

1. **Is `provenance_unknown`'s cap (`retrieve_only`) too strict for genuinely useful pre-doctrine rows?** V1 says no — unknown is honestly weaker than agent-authored. Open: whether some deployments need a one-time grace window or a manual ratchet path to lift specific legacy entries to `agent_authored` after operator review.
2. **Does `runtime_authored` deserve a ceiling above `advisory`?** V1 says no — both `agent_authored` and `runtime_authored` cap at `advisory`. Runtime testimony is more reliable than agent assertion for the witness role, but binding force still requires custody. Open: whether specific runtime classes (signed CI output, attested measurement) earn a higher cap without full custody ceremony.
3. **How does `authoring_tier=revoked` interact with the existing `status=revoked`?** They are not the same axis. `status=revoked` is per-memory event-driven revocation; `authoring_tier=revoked` is author-level standing loss. An entry can have `status=committed, authoring_tier=revoked` (committed once, author later lost standing). V1 keeps both axes; the doctor surfaces the intersection. Open: whether any consumer needs the cross-product explicitly modeled.
4. **Does the `effective_reliance` cap apply retroactively to existing receipts?** A receipt minted before the cap was enforced may cite an entry at a higher reliance than the cap now permits. V1: receipts are append-only history; the receipt records what was relied on at the time. `contctl reliance verify` (per `CROSS_COMPONENT_RELIANCE_GAP`) gains a `tier_drift` status that flags the discrepancy without invalidating the receipt.
5. **Is `provenance_unknown` allowed as a *new* write?** Strict: no — writes must declare a tier honestly. Lenient: allowed for migration tooling and for import paths where the source tier cannot be determined. V1: allowed only via the import path; new writes from `observe`/`commit` must declare a tier explicitly.
6. **Should the wrapper layer (MCP server, CLI default) supply an implicit `agent_authored` default?** V1 substrate refuses unset. Wrapper-side ergonomics may default to `agent_authored` since that is honest for most LLM-driven calls. Open: whether the default leaks the same laundering risk the gap exists to prevent. Probably safe iff the default is visible in the response and the receipt records it explicitly.

## Acceptance Criteria

This gap is closed when:

- `docs/gaps/MEMORY_AUTHORING_TIER_GAP.md` is written, indexed in `docs/gaps/README.md`, and preserves all four operator keepers verbatim.
- The decision tree is unambiguous from the spec: `agent_authored` cannot mint policy; `provenance_unknown` is the honest backfill (not a false claim of agent authorship); standing-loss flips entries to `standing_contested`, not survive/discharge.
- A worked migration plan is included (this document, V1 Slice §4) that names the schema version bump, the backfill statement, and the cap-recheck path.
- Sibling-repo touchpoints are listed: NQ witness-edge as a future composition (`external_witness_ref` reserved), Standing as the principal-roster source for tier transitions, `CROSS_COMPONENT_RELIANCE_GAP` for `tier_drift` in receipt verify.
- A workspace-scope doctrine memory is committed citing this gap as a pinned premise; the dogfood pattern from earlier gaps holds.

## Implementation Notes (V1, 2026-07-04)

What shipped, and where it deviated from the spec above — recorded so the next
reader doesn't mistake a deliberate choice for an oversight.

**Landed as specified:** the `AuthoringTier` enum and cap table (`tier_cap`,
`effective_reliance` in `api/models.py`); the `authoring_tier` column on
`memory_objects` and `memory_events` plus reserved `external_witness_ref`
(schema + `_add_missing_columns` migration, `SCHEMA_VERSION` 2→3); honest
backfill as `provenance_unknown`; write-time cap enforcement (refuse
over-cap commits) and rely-time re-application (`effective_reliance = min(stored,
cap)`); the read surfaces (`explain`/`get`/`query` carry tier + effective
reliance, on the MCP and CLI too); `contctl doctor --check authoring-tier`; and
the custody path. 21 tests.

**Deviations, each deliberate:**

1. **Substrate defaults tier to `agent_authored`, it does not refuse unset**
   (resolves Open Question 6). Making the field strictly required would break
   every existing caller and the pinned agent_gov surface. The default is honest
   for LLM-driven writes and *safe because it caps at advisory* — the laundering
   the gap prevents is agent content reaching **actionable**, which the cap still
   blocks. `custodian_signed`, `revoked`, and `provenance_unknown` remain
   non-self-declarable (refused at observe/commit).

2. **Custody promotion reuses `commit`/`revoke` events, not a new event type.**
   `adjudicate --reaffirm` mints a `custodian_signed` successor via a normal
   commit event whose receipt carries the `custody_record`; the original is
   revoked-by-promotion. This avoids a schema enum change to `event_type` /
   `receipt_type` (which would ripple through the CHECK constraints and
   `migrate_schema`) while still satisfying invariants 8–9: custodian_signed is
   reachable *only* here, a custody record is attached, history stays walkable.
   The `custody_event_id` reference (invariant 8) is the commit event's own id.

3. **CLI verb is `contctl adjudicate`, not `contctl memory adjudicate`.** The
   existing CLI is flat (observe/commit/revoke/…); a nested `memory` group for
   one verb would be inconsistent. Same behavior, flatter path.

4. **`standing_contested` is deferred, not built.** V1 has no producer for it —
   automatic standing-loss detection is an explicit deferral, and no manual
   contest command is in the V1 slice. The doctor is forward-compatible (it would
   surface contested entries) but none exist yet. The revoked-tier→cap-none path
   *is* built and tested (via a direct tier set standing in for the future
   standing-loss edge).

5. **`rely_ok` stays a coarse boolean; the ceiling rides in `effective_reliance`.**
   A `provenance_unknown` row stored at advisory reads `rely_ok=true` with
   `effective_reliance=retrieve_only` — relyable *for retrieval*, not at advisory.
   Only a cap of `none` (revoked tier) flips `rely_ok` to false, with the new
   `AUTHORING_TIER_CAPPED` reason code. Consumers that need the ceiling read
   `effective_reliance`, not the boolean.

Still deferred per the spec's own list: the custody signature mechanism, NQ
witness wiring (`external_witness_ref` reserved, unpopulated), cross-host tier
sync/re-adjudication, receipt-side `tier_drift`, and the rich adjudication UI.

## Short Version

Continuity's dangerous failure is not forgetting — it is remembering something wrong as policy. Existing `reliance_class` and `basis` cover *what may be relied on* and *how the claim was formed*; neither covers *who is allowed to make it binding later*. This gap adds `authoring_tier` (`agent_authored`, `runtime_authored`, `custodian_signed`, `revoked`, plus the honest backfill label `provenance_unknown`) and the rule that tier upper-bounds reliance class — enforced at write, re-applied at rely. Three keepers anchor the design: *memory preserves provenance or memory launders authority*; *no actor is authoritative over what it authors, including its own past*; *continuity remembering something wrong can mint a constitution while everyone is looking at the floor*. Standing-loss places prior obligations into `standing_contested` (custodian adjudicates), neither automatic survive nor automatic discharge — the substrate refuses to pretend the question has a quiet answer. NQ witnesses-writes is named for future composition (`external_witness_ref` reserved on events), not built in V1. The substrate ships the tier column, the cap table, the read-side surface, the migration as `provenance_unknown` (never as a false claim of `agent_authored`), and a doctor check for cap violations.
