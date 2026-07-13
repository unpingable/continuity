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

- **(A) migrate-on-open.** The store open/read path invokes the idempotent
  column migration (`_add_missing_columns`, or a thin `ensure_columns()`), so
  any store is brought current before a query that references post-original
  columns. **Single choke point; self-heals the live broken store on next open
  — no separate manual migration of the operator's `~/.config/continuity` store
  needed.**
- **(B) defensive query.** Each query that references a post-original column
  first checks `PRAGMA table_info` / column presence and degrades (omit the
  column, treat as NULL). Localized, but whack-a-mole across every current and
  future column-referencing query; a missed query reintroduces the break.

**Recommendation: (A).** It matches the doctrine already in the code comments,
collapses the failure class at one seam, and makes the operator's live store
self-heal (removing what would otherwise be a separate operational act against a
real store). Ratify or override before build.

## Acceptance criteria (behavioral — mechanism-agnostic)

1. Against a store fixture created **without** the `authoring_tier` column
   (schema as of pre-252c11d), `memory_query_latest` and `memory_get_case`
   return results (possibly with `authoring_tier` reported as its default /
   absent) instead of raising `OperationalError: no such column`.
2. The fix covers the **SQL-level** reference, not only the row-dict read — a
   regression test issues the actual failing query shape against the
   un-migrated fixture and asserts no raise.
3. Under fork (A): opening the store is sufficient to heal it — a second call
   succeeds with no manual migration step; the migration is idempotent (running
   it on an already-current store is a no-op, asserted).
4. No behavior change for already-migrated stores (existing 231-test suite green
   — run **bare**, exit code is the verdict; never judged through a piped tail).
5. The live operator store that produced the 2026-07-13 error
   (`~/.config/continuity/workspaces/observatory-family`) returns instead of
   raising after the fix is in place (verified once, out-of-band from the unit
   fixture — this is the operational confirmation, and it needs no destructive
   step if (A) is chosen).

## Non-goals

- Not a schema change — the column already exists in `schema.sql`.
- Not a redesign of the authoring_tier feature or the migration framework.
- Not a general "migrate everything on every open" performance commitment —
  scope is the column-presence class that currently raises.

## Validation provenance

_(escape-count pass to be recorded here before this spec admits a build_slice:
run a cold flat-prompt validator over this artifact, count "what I'd build
wrong" items that escape the pins above; zero escapes = ratifiable.)_
