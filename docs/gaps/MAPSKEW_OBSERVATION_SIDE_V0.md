# Gap: MapSkew Observation Side V0 — the light source, not the comparator

**Status:** V1 specimen implemented 2026-07-04 (`src/artifact_observer/`, `tests/test_artifact_observer.py`)
**Depends on:** nothing in continuity's store (deliberately — see the boundary). Composes with `CONTINUITY_TIME_DISCIPLINE` V2 `source_observed_at` (an observation carries an `observed_at` that becomes a memory's `source_observed_at` when one is later formed).
**Related:** `candidates/MAP_SKEW.md` (this builds MapSkew's missing *input*, not MapSkew). Doctrine source: the 2026-07-04 ruling — *"build the light source, then let the map be wrong in public."*
**Blocks:** MapSkew graduation. MapSkew is a comparator between a remembered claim and an observed artifact-state claim; without a surface that emits the observed side, the comparator has no inputs and cannot honestly exist.

## The Problem

MapSkew stalled on a real wall: nothing produces artifact-state claims commensurable
with continuity's memory claims. The wrong response is to wait for an abstract
"observation owner" decision (deadlock), and the equally wrong response is to graduate
MapSkew anyway (blueshift — shipping the candidate as more mature than reality, the
exact failure MapSkew exists to detect).

The right response is narrower than either: build the **narrowest honest light source** —
a read-only observer that emits *one* bounded artifact-state claim shape. Not the
comparator. Not the skew taxonomy. Just the witness that gives MapSkew a second input.

## Design Stance — the ownership boundary is the whole point

Three organs, strictly separated, no self-certifying closure:

- **Continuity** owns *remembered* claims. It must NOT observe artifact reality — a
  memory-keeper that also produces the reality it is checked against is self-licking-map
  ice cream.
- **Artifact Observer** owns *observed* artifact-state claims. Read-only. It never
  imports the continuity store, never mutates memory, never compares against memory,
  never decides skew. It only testifies: *here is what the artifact currently says.*
- **MapSkew** (later, still a candidate) compares the two. It is the comparator, not
  the witness.
- **NQ-ish doctrine** (later) supplies admissibility / freshness / cannot-testify
  discipline over both sides.

This gap builds only the Artifact Observer, and only a V0 specimen of it.

**Placement.** The observer lives in its own top-level package (`src/artifact_observer/`,
namespace `artifact_observer`) — *not* under `continuity`. It is colocated in this repo
for now as a specimen; if it grows past a specimen it moves to its own repo. Colocation
is not ownership: the package has zero import of `continuity.*`.

## The claim shape

One bounded observation, deliberately different from a `MemoryObject` (an observation is
not a memory; commensurability is resolved at the MapSkew comparison layer, not by
sharing a schema):

```
subject         — what was observed (file / symbol / doc_section / route)
subject_kind    — bounded enum; V0 implements `file`, reserves the rest
claim_kind      — exists / contains / declares / omits
claim_value     — the bounded observed value (e.g. a matched token) or None
observed_at     — when the scan happened (becomes source_observed_at downstream)
source_ref      — repo / path / content digest (+ commit if resolvable): line-of-sight
can_testify     — false when the observer refuses to make a claim (out of bounds, unreadable)
cannot_testify_reason — the refusal reason when can_testify is false
observer_version
```

`can_testify=false` is a first-class, honest outcome — refusal is evidence, not silence.
Observing *absence* (a missing file for an `exists` claim) is still testimony
(`claim_value=false`), distinct from *unable to observe* (`can_testify=false`).

## Architectural Invariants

1. **Read-only.** The observer never writes anything, anywhere. It opens files and
   reports.
2. **No continuity coupling.** No import of `continuity.*`. The observer has its own
   claim model and its own boundary clock. (Enforced by a test.)
3. **No comparison, no skew, no memory.** The observer emits an observation and stops.
   Diffing it against a remembered claim is MapSkew's job, in a later gap.
4. **Bounded claims only.** `claim_value` is a matched token or a digest, never an
   unbounded file dump. Large/binary/out-of-bounds artifacts yield `can_testify=false`.
5. **Line-of-sight source_ref.** Every observation cites repo + path + content digest
   (and commit when a git worktree resolves), so a reader can reproduce the scan.
6. **Boundary clock.** `observed_at` is resolved once at the `observe()` boundary
   (injectable for tests), never by an ambient read inside the claim logic — the same
   time discipline continuity holds.

## V0 Slice

1. `src/artifact_observer/models.py` — `ArtifactObservation`, `SubjectKind`,
   `ClaimKind`, `SourceRef` (observer's own; not continuity's).
2. `src/artifact_observer/observer.py` — `ArtifactObserver(repo_root)` with
   `observe(subject, claim_kind, needle=None, observed_at=None) -> ArtifactObservation`.
   V0 handles `subject_kind=file` and the four claim kinds against a repo working tree.
3. `tests/test_artifact_observer.py` — including a concrete dogfood fixture: observe
   continuity's *own* repo (e.g. that `declaration_export.py` contains the schema tag),
   an absence case, a `cannot_testify` case (path escaping the repo root), the
   no-continuity-import invariant, and digest reproducibility.

## Explicit Deferrals

- **The MapSkew comparator.** Still a candidate. This gap gives it an input, nothing more.
- **The axes taxonomy** (recency / completeness / authority / capability / integration).
  Un-invented until a second dogfood earns it.
- **Subject kinds beyond `file`** (symbol, doc_section, route) — reserved in the enum,
  not implemented. Each earns its way in with a forcing case.
- **A general repo-scanner framework.** V0 observes one subject per call. It does not
  crawl, index, or watch. It becomes a framework only if forced.
- **Git blame / history / cross-commit observation.** V0 records the current commit if a
  worktree resolves; it does not walk history.
- **Relocation to its own repo.** Colocated specimen for now; moves out if it graduates.

## Acceptance Criteria

- A read-only observer emits one commensurable claim shape carrying `observed_at` and a
  reproducible `source_ref` (repo/path/digest).
- It can say `cannot_testify` and distinguishes that from observed absence.
- It does not import continuity and does not mutate anything (both asserted by tests).
- MapSkew's candidate is updated: observation-side trigger now has a **V0 specimen, not a
  general solution**; a second dogfood is still required before graduation.

## Short Version

MapSkew stalled because nothing emits the observed half of its comparison. Don't
deadlock waiting for an abstract observation owner, and don't blueshift MapSkew into
maturity. Build the narrowest honest light source: a read-only `ArtifactObserver` (its
own package, zero continuity coupling) that emits one bounded artifact-state claim —
subject / claim_kind / claim_value / observed_at / source_ref / can_testify — and
nothing more. No comparison, no skew, no memory. Continuity remembers; the observer
observes; MapSkew (later) compares. Build the light source, then let the map be wrong in
public.
