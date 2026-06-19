# Candidates

Architectural notes that have earned a name but not implementation.

A candidate is below the gap-spec threshold. It marks a slot for a design idea the project may want to reference later — keeper lines, vocabulary, the structural question to resolve before specification — without authorizing build. The convention is *name early, ratify lazily*: file the smallest useful record if forgetting would create retrofit cost; mark it candidate / non-binding until pressure justifies graduation.

## When to file a candidate

- A design idea has a load-bearing keeper line worth preserving for recognition use.
- An architectural slot is identified but a structural blocker prevents specification (missing dependency, unidentified owner, no schema substrate).
- A vocabulary or typed taxonomy is sketched but not earned by forcing cases.
- A cross-organ primitive is proposed but the cross-organ owners aren't lined up.

A candidate is *not* a gap-spec under another name. Gap-specs lock invariants; candidates hold ideas in a known location until they're ready.

## When a candidate graduates

A candidate becomes a gap-spec when implementation pressure proves the candidate framing underspecified — not when downstream events merely happen, and not on a calendar. Each candidate names its own graduation triggers in a `## Graduation triggers` section.

If a candidate stops paying rent — the idea was wrong, or the slot turned out not to exist, or the work happened differently elsewhere — retire it. Candidates are not durable doctrine; they are bookmarks.

## Format

Loose. A candidate note should at minimum carry:

- **Status:** candidate (not gap-spec, not implementation)
- **Depends on:** structural dependencies that block graduation
- **Related:** existing gap-specs or memories the candidate intersects
- **The idea**, briefly
- **Why it's a candidate, not a gap-spec** — the structural blockers, named
- **Graduation triggers** — what would earn promotion
- **Not in scope, even at candidate stage** — guardrails against premature ratification

Keep them short. A candidate that needs the full gap-spec structure is probably ready to be a gap-spec.

## Current candidates

| Note | Originated | One-line |
|------|------------|----------|
| [`MAP_SKEW.md`](MAP_SKEW.md) | 2026-05-20 | Directional belief-state error detection — memory has direction, not just age. Cross-organ; waiting on observation-side owner and time-discipline V2 substrate. |
| [`PROJECTION_RECEIPT.md`](PROJECTION_RECEIPT.md) | 2026-06-18 | Stored-is-not-true. A semantic read across schema/version/projection boundaries is a witnessed claim, not a resurrection of stored truth. AG-authorized port of one receipt-kernel choke point into continuity grammar. |

## Graduated

| Note | Graduated | Now at |
|------|-----------|--------|
| WLP Persistence Adapter | 2026-05-28 | [`../gaps/WLP_PERSISTENCE_ADAPTER_GAP.md`](../gaps/WLP_PERSISTENCE_ADAPTER_GAP.md) — graduated under MVP-A forcing pressure; all four graduation triggers MET. |
