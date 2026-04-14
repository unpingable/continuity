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
