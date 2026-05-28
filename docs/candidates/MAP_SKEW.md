# Candidate: MapSkew — directional belief-state error detection

**Status:** candidate (not gap-spec, not implementation)
**Originated:** 2026-05-20
**Depends on:** `gaps/CONTINUITY_TIME_DISCIPLINE.md` V2 named fields (`source_observed_at`, `last_confirmed_at`, eventual staleness gradient) as schema substrate; a not-yet-owned observation-side surface that produces structured artifact-state claims commensurable with memory claims
**Related:** `gaps/PREMISE_CONSISTENCY_DOCTOR.md` (orthogonal failure shape — child-vs-premise consistency); the operator-side recognition rule [`feedback_memory_is_evidence_not_completion`](../../../.claude/projects/-home-jbeck-git-continuity/memory/feedback_memory_is_evidence_not_completion.md) (the failure mode this would detect mechanically)

## The Idea

Memory failure has direction, not just age. Comparing remembered state to observable artifact state can yield:

- **Calibrated** — memory matches observation
- **Redshifted** — memory is behind reality (underclaims maturity / completeness / capability)
- **Blueshifted** — memory is ahead of reality (overclaims; ships ghosts; launders projection as completion)
- **Incoherent** — conflicting observations, no stable direction
- **Unobserved** — no commensurable observation surface available

Operator labels are the human handle. The machine-layer primitive is signed skew on typed axes:

- recency
- completeness
- authority
- capability
- integration

with skew values along each axis:

- Lagging
- Leading
- Matched
- Conflicted
- Unknown

Aggregate axis skews → derived operator label. In code, the type stays boring (`MapSkew` or similar). `redshift`/`blueshift` is operator-layer vocabulary, not source-code identifiers.

## Why direction, not just staleness

Stale-and-underclaiming and stale-and-overclaiming have asymmetric consequences. Redshift makes you miss capability you already have. Blueshift makes you ship ghosts — fake completion, projection laundered as state. Different failures need different responses: correct upward and cite evidence for redshift; clamp promotion language and require verification for blueshift; refuse synthesis for incoherent; seek observation for unobserved.

Staleness gradient (named-and-deferred in `CONTINUITY_TIME_DISCIPLINE.md` invariant 10) is the *magnitude* question. MapSkew is the *direction* question. Both are needed; both are V2-ish; neither is the other.

## Placement in the stack

Cross-organ primitive, not purely a continuity concern. Continuity owns the remembered-model half. Computing a delta requires a *commensurable* artifact-state observation, which continuity does not have an active surface for (only `source_refs` pointer metadata). The comparator sits between memory and `rely_ok`:

```
memory (continuity)  +  observation (NQ-shaped or repo-scanner adapter)
        ↓
    comparator (MapSkew)
        ↓
    rely_ok / claim emission
```

Open ownership question: **who owns the observation side?** Until that resolves, the comparator has no inputs to compare against. This is the structural blocker on graduation from candidate to gap-spec.

## Why this is a candidate, not a gap-spec

1. **Observation-side owner is unidentified.** Specifying a comparator without inputs would invent a taxonomy in the absence of forcing cases — calendar theology in spectroscopy clothing.
2. **Schema substrate is not yet built.** Skew detection needs at minimum `source_observed_at` and a comparable claim shape — those are V2 work in `CONTINUITY_TIME_DISCIPLINE.md` with their own implementation-pressure trigger.
3. **The axes taxonomy is sketched, not earned.** Real forcing cases should refine which of recency / completeness / authority / capability / integration survive intact, which collapse, which split.

The candidate stage is for: marking the slot, holding the keeper line, preserving the typed-axes vocabulary so it can be lifted when the dependencies land. Per the project's own discipline: name early, ratify lazily; a record is not authorization to build.

## Recognition value today

The keeper does work in conversation even with no detector:

> **Memory is not wrong only by age. It is wrong by direction.**

Dogfood instance: 2026-05-13, the operator caught me committing blueshift — saving "the V1 doctor command is the natural dogfood" to memory as if the spec had been written. The failure mode was real, demonstrated, and named; the corrective was a gap-spec (`PREMISE_CONSISTENCY_DOCTOR.md`), not more memory. That same recognition would benefit from machine-side support once dependencies exist. Until then, the keeper is recognition-only and operates at the agent layer.

## Graduation triggers

This candidate becomes a gap-spec when:

- The observation-side owner is identified (NQ-shaped surface, a repo-scanner adapter, or a new organ explicitly chartered for artifact-state observation).
- `CONTINUITY_TIME_DISCIPLINE.md` V2 work earns implementation pressure — specifically `source_observed_at` plus a comparable claim shape on memory.
- A second concrete dogfood instance demonstrates the failure mode in a different domain than projection-laundering — proving the axes generalize beyond the case that originated them.

Per `gaps/CONTINUITY_TIME_DISCIPLINE.md`'s revision discipline: graduate this candidate when implementation pressure proves the framing underspecified, not when downstream events merely happen. Until then, the framing stays as written and the keeper stays available for recognition.

## Not in scope, even at candidate stage

- Implementation. The schema substrate isn't there.
- Full axes taxonomy beyond the five sketched. Forcing cases earn axes.
- Operator-label-to-axes derivation rules in detail. The aggregation function will be obvious once real cases pressure it; inventing rules now is premature.
- Anything called `redshift` or `blueshift` in source code. Operator-layer metaphor only; internal primitive stays `MapSkew` or equivalent boring name.

## One-line summary

Memory has direction, not just age. Signed skew on typed axes (recency / completeness / authority / capability / integration) yields derived operator labels (calibrated / redshifted / blueshifted / incoherent / unobserved). Cross-organ; waiting on observation-side owner and time-discipline V2 substrate. Recognition rule available today: *memory is not wrong only by age — it is wrong by direction.*
