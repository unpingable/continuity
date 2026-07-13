# Gap: authoring_tier query against an un-migrated store raises `no such column`

**Status:** spec_slice — filed 2026-07-13, awaiting escape-count nod before build.
**Kind:** substrate defect (live break, not new surface).
**Depends on:** `MEMORY_AUTHORING_TIER_GAP` (shipped the column, commit 252c11d).
**Related:** `PINNED_CONSUMER_SURFACE_GAP` (agent_gov is the live consumer whose
read path trips this); the AG-side census defect **D6**
(`agent_gov/working/constellation-census-2026-07-13.md`).
**Blocks:** the governed-memory recovery path — `memory_query_latest` /
`memory_get_case` from an AG session currently raise instead of returning.
**Cross-repo note:** filed by agent_gov's loop under the naturalization/standing
convention (AG crosses into continuity in continuity's idiom). If a continuity
session picks it up, the spec is already in-idiom — hand off cleanly.

## The Problem (reproduced 2026-07-13)

An AG session calling the continuity MCP `memory_query_latest(scope=agent_gov,
kind=project_state)` gets:

```
error: no such column: authoring_tier
```

The column exists in `schema.sql` (line 80) and `initialize()` adds it to
existing DBs via `_add_missing_columns` (`store/sqlite.py:296`,
`ALTER TABLE memory_objects ADD COLUMN authoring_tier ...`). The migration is
present and idempotent. **The defect is that a read/query path can open a store
created before that column and issue SQL that references `authoring_tier`
without the migration ever having run against that store.** The author already
documented the shape at `store/sqlite.py:2149`:

> `authoring_tier` may be absent on rows in a DB not yet migrated (AG opens
> stores without initialize()).

The existing guard is a `Row.keys()` check on **row-dict reads** (2219–2220).
It does not cover a query that names the column at the **SQL level** (SELECT /
WHERE / ORDER BY), which fails at execute time before any Python-side guard.

Reduction is deferred to the build worker on purpose: the exact failing open
path (which query, opened by the MCP handler vs. AG's library edge in
`governor/doctrine.py`, against which store file) must be reproduced against the
real broken store, not assumed. This spec pins the *behavior* to restore, not
the line to edit.

## Design fork (the one decision this spec must resolve)

- **(A) migrate-on-open.** A **writable** store open invokes the idempotent
  column migration (`_add_missing_columns`, or a thin `ensure_columns()`), so a
  store is brought current before a query references post-original columns.
  Single choke point. **Self-heal of the operator's `~/.config/continuity` store
  is CONTINGENT, not promised:** it happens only if a *writable* consumer opens
  that store. Whether one does — vs. the live store being reached only by
  read-only query paths — is an unreduced empirical fact (see the deferred
  reduction below). If no writable open reaches it, a one-time migration of the
  live store is required and is an **operational act** (owner confirmation).
- **(B) defensive query.** Each query that references a post-original column
  first checks `PRAGMA table_info` / column presence and degrades (omit the
  column, treat as NULL). Localized, but whack-a-mole across every current and
  future column-referencing query; a missed query reintroduces the break.

**Recommendation: (A) and (B) are complementary, not exclusive — build both**
(revised after escape-count pass 3, which found the writability precondition
below). (A) heals durably but its `ALTER` needs a **writable** connection, so it
can only fire on writable opens; (B) costs nothing and covers the window before
any writable consumer has healed the store, and any genuinely read-only
consumer. The hybrid: **heal on writable opens (A); degrade defensively on
column-referencing reads (B)** so no path raises regardless of migration state
or connection mode. See Pin E-write. Ratify the hybrid or override before build.

## Acceptance criteria (behavioral — mechanism-agnostic)

1. Against a store fixture created **without** the `authoring_tier` column
   (schema as of pre-252c11d), `memory_query_latest` and `memory_get_case`
   return the **correct latest / correct case** records (non-empty when the
   store has matching data — see Pin E6) instead of raising
   `OperationalError: no such column`.
2. The fix covers the **SQL-level** reference, not only the row-dict read — a
   regression test issues the actual failing query shape against the
   un-migrated fixture and asserts no raise **and** correct content.
3. Under fork (A): opening the store is sufficient to heal it — a second call
   succeeds with no manual migration step; the migration is idempotent (running
   it on an already-current store is a no-op, asserted).
4. No behavior change for already-migrated stores (existing 231-test suite green
   — run **bare**, exit code is the verdict; never judged through a piped tail).
5. The live operator store that produced the 2026-07-13 error
   (`~/.config/continuity/workspaces/observatory-family`): after the fix,
   `memory_query_latest` **returns** (B guarantees this regardless of migration
   state) AND — verified separately — the store is **durably healed**: re-open
   and assert `authoring_tier` now exists in `memory_objects`. If it does NOT
   (no writable consumer reached it), the build ran a one-time migration as an
   explicit operational step, receipted — NOT silently left un-migrated. "Just
   returns" is insufficient; durability is asserted, not assumed. (This is what
   pass 4 caught: B can make reads succeed while the store stays broken forever.)

## Deferred reduction (the build_slice's FIRST task — not a spec ambiguity)

The exact failing open-path AND whether any writable consumer reaches the live
operator store are facts about the running deployment, unresolvable on paper.
The build worker reduces them against the real store before writing the fix:
which query/handler raised (MCP `memory_query_latest` vs AG's library edge), and
whether that store is ever opened writable. **Escalation trigger:** if the live
store is reached only read-only, the one-time migration of it (criterion 5) is
an operational touch on the operator's real memory — surface to the continuity
owner, do not perform unilaterally. Criterion 5 makes skipping this impossible.

## Pins (added 2026-07-13 after escape-count pass 1 — 4 escapes closed)

A cold flat-prompt validator (no project context) found four ways to build this
wrong. Each is pinned here so the spec teaches its own boundaries:

- **Pin E2 — a pre-migration row reads as lowest authority, never as `None`.**
  When `authoring_tier` is absent, the read MUST present the same reliance
  semantics an explicit `provenance_unknown` row gets (capped at
  `retrieve_only`) — NOT `None`, which would bypass the cap and let an
  un-migrated row read as unconstrained. Match existing lowest-authority
  behavior; do not invent a new absence value. (Falsification: an impl returning
  `authoring_tier=None` with no cap satisfies "does not raise" but is a reliance
  regression — refuse it.)
- **Pin E3 + E4 — fork (A) calls the EXISTING idempotent `_add_missing_columns`
  on the open/read path that currently bypasses `initialize()`.** Two parts:
  - **Where it fires:** on the store-open/read path itself — the one the defect
    names ("AG opens stores without `initialize()`", `sqlite.py:2149`). It must
    NOT be added only inside `initialize()`: that path is exactly the one the
    broken consumer skips, so an initialize-only fix reproduces the bug. Fork
    (A) heals the store because opening it runs the ensure step (criterion 3 is
    the hard behavioral gate; an initialize-only build fails it).
  - **Coverage + cost:** call `_add_missing_columns` as-is — it already covers
    the whole post-original class (`pinned_content_hash`, `source_observed_at`,
    `external_witness_ref`, `authoring_tier`), not one column, because a
    one-column patch just re-raises on the next post-original reference. Its
    idempotency is the EXISTING per-column `PRAGMA table_info` guard
    (`sqlite.py:266-317`): the `ALTER` fires only for a genuinely-absent column,
    so on an already-current store it is a few cheap PRAGMA reads and zero
    writes. That is the reconciliation with non-goal 3 — cheap presence checks
    that no-op once columns exist, NOT a "rebuild everything on every open"
    commitment. **Do NOT gate on `schema_version`:** that marker is `DEFAULT 1`
    and nothing in the code advances it, so a version gate would either never
    fire or skip the broken store. Idempotency lives in the per-column PRAGMA
    check, not a version marker. (Escape found + closed in pass 2.)
- **Pin E6 — "return" means return the correct record, not swallow-to-empty.**
  Acceptance forbids an impl that catches `OperationalError` and returns `[]`.
  The regression asserts the query returns the actual latest/matching record
  (positive content) for a populated un-migrated store, closing the recovery
  path the `Blocks:` line names.

- **Pin E-write — the heal is a WRITE; reads must not trigger it on a read-only
  connection.** `_add_missing_columns` issues `ALTER TABLE ADD COLUMN`, which
  requires a writable connection. Therefore: (A) fires ONLY on writable opens
  (MCP init, CLI, any RW consumer) — wiring the `ALTER` into a read-only-opened
  query connection raises `OperationalError: attempt to write a readonly
  database`, a *worse* failure than the original. A column-referencing query
  that may run on a read-only / not-yet-healed store MUST instead degrade
  defensively (B): treat the absent column as `provenance_unknown` →
  `retrieve_only` per Pin E2, never assume it in SQL. Net: writes heal durably,
  reads never write and never raise. (Escape found + closed in pass 3.)
  Acceptance addendum: a regression opens the fixture **read-only**, runs the
  failing query, and asserts it returns correct content WITHOUT raising either
  `no such column` OR `readonly database`.

**Not escaping (validator-confirmed pinned):** the fork decision (now the hybrid
above); which entry points + store file the regression uses (criteria 1/5);
whether continuity owns the open path (criterion 5); migration coverage +
idempotency mechanism (Pin E3+E4 verified against code in pass 3).

## Non-goals

- Not a schema change — the column already exists in `schema.sql`.
- Not a redesign of the authoring_tier feature or the migration framework.
- Not a general "migrate everything on every open" performance commitment —
  scope is the column-presence class that currently raises.

## Validation provenance

- **Pass 1 (2026-07-13):** cold flat-prompt validator (fresh no-context agent;
  codex substitute — codex-exec sandbox dead on this host). Artifact + cited
  code only, no doctrine preamble. Found **4 escapes** (E2 absence-value
  semantics, E3 coverage set, E4 migration trigger point, E6 swallow-to-empty),
  3 items confirmed already-pinned. All 4 patched into Pins above.
- **Pass 2 (2026-07-13):** re-run after pins. Confirmed E2/E3/E6 closed and E4
  closed-by-test. Found **1 NEW escape** the patch introduced: Pin E3+E4 invoked
  a `schema_version` gate that does not exist in the code (marker never advances
  past `DEFAULT 1`) — a literal build would skip the broken store. Pin rewritten
  to the real mechanism (per-column `PRAGMA table_info` idempotency; fire on the
  open/read path, not `initialize()`-only).
- **Pass 3 (2026-07-13):** confirmed E3+E4 matches code, E2/E6/fork clean. Found
  **1 residual precondition:** the heal is a `write`, but the spec never required
  a writable connection — a read-only-opened heal raises `readonly database`.
  Resolved by Pin E-write (hybrid: heal on writable opens, degrade defensively
  on reads) + a read-only regression.
- **Pass 4 (2026-07-13):** confirmed the hybrid + Pin E-write close the
  read-only-write ambiguity (both regressions jointly force A and B). Found **1
  residual:** the self-heal headline was a promise no criterion falsified — B
  could make reads succeed while the store stayed un-migrated forever. **Not a
  spec ambiguity but an unreduced empirical fact** (does a writable open reach
  the live store?). Closed at the spec level by: demoting self-heal to
  contingent, strengthening criterion 5 to assert *durable* heal (re-open +
  column present) or a receipted one-time migration, and naming the reduction +
  owner-escalation trigger explicitly (Deferred reduction section).

**Ratification verdict (loop PLAN phase, 2026-07-13):** RATIFIABLE for a
build_slice. Passes converged 4 → 1 → 1 → 1, walking from structural holes to a
deferred empirical reduction that *cannot* be settled on paper and now lives,
named and escalation-gated, in the build_slice's first task. Per the stop
condition above, the validation loop halts here rather than chase a paper zero
against a runtime fact. No pass 5.
