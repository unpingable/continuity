# Gaps

Proposed doctrine for architectural, storage, or substrate shifts — written **before** implementation, so the invariants are chosen deliberately rather than improvised under pressure.

The format matches sibling projects (agent_gov, nq): each gap spec is a single markdown file that freezes the shape of a problem, the invariants the solution must hold, and the smallest slice that proves the feature works.

## What a gap spec is for

Gap specs exist for decisions you don't want future-you to have to reconstruct under pressure. They are not design documents for every feature. They are for changes that would lock in invariants or reshape a load-bearing surface — tiering, cross-boundary identity, new tables, authority models, anything that affects how chains or scopes behave.

Small polish items, bugfixes, CLI ergonomics, and schema additions that don't change invariants do not need one.

## Format

Every gap spec should have:

- **Header block**: Status, Depends on, Related, Blocks, Last updated
- **The Problem**: what the gap actually is, framed so the naïve fixes are visible as wrong
- **Design Stance**: the framing that rules out bad solutions early
- **Architectural Invariants**: frozen doctrine, numbered, organized into small blocks. If one turns out wrong, revisit the block, not individual items.
- **V1 Slice**: the smallest thing that proves the feature works
- **Explicit Deferrals**: what is *not* decided now, listed by name so it is not accidentally frozen
- **Open Questions**: honest uncertainty, numbered for later resolution
- **Acceptance Criteria**: how we know the gap is closed
- **Short Version**: one paragraph that survives being quoted out of context

Prose first. Bullets only for the numbered invariants and enumerated lists where they earn their place.

## Current specs

| Spec | Status | Summary |
|------|--------|---------|
| [`CONTINUITY_STORAGE_GAP.md`](CONTINUITY_STORAGE_GAP.md) | proposed | Tiered history (hot/warm/cold) that preserves chain walkability. Events and spool imports as first tier candidates; receipts stay hot in v1. |
| [`ISLANDS_OF_CONTINUITY.md`](ISLANDS_OF_CONTINUITY.md) | proposed; visibility V1 partially landed | Silent fallback resolution lets `global`-scope writes land in isolated project-local DBs nobody else reads. Make topology visible at every surface that can write cross-project: `contctl where` names the resolution source, MCP startup announces topology, global-scope writes to fallback DBs warn or refuse (`--allow-island`). A global memory in an island DB is a local memory wearing a fake mustache. |
| [`ISLAND_DISCIPLINE.md`](ISLAND_DISCIPLINE.md) | proposed | Isolation is fine; *undeclared* isolation is the bug. Domains declare purpose (`firewall`, `bridgeable`, `quarantined`, `local_dev_test`, `archival`); cross-domain exchange is typed, non-transitive, receipted import on `CROSS_SCOPE_REFERENCE_GAP` primitives; imports always start observed; `scope=global` is global only within its declared domain. |
| [`CROSS_ISLAND_BRIDGES_GAP.md`](CROSS_ISLAND_BRIDGES_GAP.md) | proposed | A bridge carries intent (`transfer_type`), trust ceiling (`reliance_class`), and outcome (`disposition`) on three orthogonal axes that must never collapse. Scope fences as dual event + constraint-memory; legacy loads as graduated quarantine; Governor adjudicates crossing admissibility but confers no epistemic standing inside any island. Concepts can cross islands; authority cannot cross without a receipt. |
| [`USEFUL_REFUSAL_EXPLAIN.md`](USEFUL_REFUSAL_EXPLAIN.md) | V1 implemented (`RelyReasonCode` + `RelyState`, `contctl why`) | Refusal today is operationally decent but unparseable. Promote `rely_reason` from free-form string to structured code + details + rendered message, plus `contctl why`. No new checks, no new outcomes — a typed shape for downstream consumers so refusal doesn't drift into policy fog. |
| [`CONTINUITY_ORIENT_HOOK.md`](CONTINUITY_ORIENT_HOOK.md) | proposed | Substrate is adequate; consultation is not load-bearing. Entrypoint-adapter primitives: `contctl orient` (fan a session's read across parent scopes + declared related organs), read-side advisory on narrow queries, `contctl lint-promotion` for write-side doctrine-shaped material. Advisory in V1. Keeper: *queryable memory is not operational memory unless the tools fresh sessions actually use are forced to query it.* |
| [`CROSS_SCOPE_REFERENCE_GAP.md`](CROSS_SCOPE_REFERENCE_GAP.md) | proposed | Identity and import for references that cross project-DB boundaries. Content-hash pinning, import receipts, honest gap declaration. Parasitic on existing primitives — no new tables in v1. |
| [`PREMISE_CONSISTENCY_DOCTOR.md`](PREMISE_CONSISTENCY_DOCTOR.md) | proposed | `continuity doctor --check premise-consistency` — premise links function as review surfaces, not just provenance. Flag memory entries whose wording weakens or contradicts the obligation of any cited premise. Dogfood fixture is a real corrected memory pair from 2026-05-13. |
| [`CONTINUITY_TIME_DISCIPLINE.md`](CONTINUITY_TIME_DISCIPLINE.md) | V1 implemented (`1d01b91`); V2 proposed | Continuity may reason about time but must not hide which clock it used. V1 (landed): explicit `evaluation_time` parameter on rely/explain (no ambient `now()` in the kernel) and dropped the SQLite `updated_at` trigger (one clock surface, not two). V2 captures `source_observed_at`, `last_confirmed_at`, and a staleness gradient — named, deferred. |
| [`CROSS_COMPONENT_RELIANCE_GAP.md`](CROSS_COMPONENT_RELIANCE_GAP.md) | proposed | Doctrine layer over `CROSS_SCOPE_REFERENCE_GAP`. Names what continuity is *for* in the cross-host world: records what may be relied on, never decides who may speak; distributes reliance records, never the rely path. V1 ships a `relied_on` receipt convention plus a local-only `contctl reliance verify` + `memory_verify_reliance` MCP tool. Three operator keepers preserved verbatim. |
| [`WLP_PERSISTENCE_ADAPTER_GAP.md`](WLP_PERSISTENCE_ADAPTER_GAP.md) | graduated from candidate 2026-05-28; V1 in progress | Continuity as a custody-preserving persistence substrate for WLP artifacts (HandlingReceipt, AuthorizationReceipt). Library-only adapter, no transport surface. Twelve invariants enumerated. Persistence ≠ transport; receipt store ≠ reliance engine. Keepers: *WLP preserves the artifact contract; continuity may preserve the artifact; consumers decide reliance.* |
| [`PINNED_CONSUMER_SURFACE_GAP.md`](PINNED_CONSUMER_SURFACE_GAP.md) | V1 implemented (contract tests); doctrine proposed | agent_gov's `src/governor/doctrine.py` (the only wired Governor→Continuity edge) imports, calls, and reads a specific library surface that nothing in this repo records or tests — and the consumer degrades gracefully, so breakage ships green from both repos. Pins exactly the observed surface; V1 is a contract-test module in continuity's own suite so a breaking rename fails here first. Additions free; pins grow only by evidence of a real call site. |
| [`MEMORY_AUTHORING_TIER_GAP.md`](MEMORY_AUTHORING_TIER_GAP.md) | V1 implemented (`authoring_tier`, cap enforcement, `adjudicate`, doctor check) | Provenance distinct from reliance: every entry carries an `authoring_tier` (`agent_authored`, `runtime_authored`, `custodian_signed`, `revoked`, `provenance_unknown`) that upper-bounds `reliance_class`. Standing-loss flips to `standing_contested`, not survive/discharge. Backfill is honest (`provenance_unknown`), not a false claim of `agent_authored`. NQ witness-edge reserved. Keepers: *memory preserves provenance or memory launders authority*; *no actor is authoritative over what it authors, including its own past*; *continuity remembering something wrong can mint a constitution while everyone is looking at the floor*. |
