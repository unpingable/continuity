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
| [`CROSS_SCOPE_REFERENCE_GAP.md`](CROSS_SCOPE_REFERENCE_GAP.md) | proposed | Identity and import for references that cross project-DB boundaries. Content-hash pinning, import receipts, honest gap declaration. Parasitic on existing primitives — no new tables in v1. |
| [`PREMISE_CONSISTENCY_DOCTOR.md`](PREMISE_CONSISTENCY_DOCTOR.md) | proposed | `continuity doctor --check premise-consistency` — premise links function as review surfaces, not just provenance. Flag memory entries whose wording weakens or contradicts the obligation of any cited premise. Dogfood fixture is a real corrected memory pair from 2026-05-13. |
| [`CONTINUITY_TIME_DISCIPLINE.md`](CONTINUITY_TIME_DISCIPLINE.md) | proposed | Continuity may reason about time but must not hide which clock it used. V1: explicit `evaluation_time` parameter on rely/explain (no ambient `now()` in the kernel) and drop the SQLite `updated_at` trigger (one clock surface, not two). V2 captures `source_observed_at`, `last_confirmed_at`, and a staleness gradient — named, deferred. |
| [`CROSS_COMPONENT_RELIANCE_GAP.md`](CROSS_COMPONENT_RELIANCE_GAP.md) | proposed | Doctrine layer over `CROSS_SCOPE_REFERENCE_GAP`. Names what continuity is *for* in the cross-host world: records what may be relied on, never decides who may speak; distributes reliance records, never the rely path. V1 ships a `relied_on` receipt convention plus a local-only `contctl reliance verify` + `memory_verify_reliance` MCP tool. Three operator keepers preserved verbatim. |
