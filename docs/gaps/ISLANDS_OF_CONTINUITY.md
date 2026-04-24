# Gap: Islands of Continuity — storage topology must be visible before writes

**Status:** proposed
**Depends on:** existing store resolver (`contctl where`), workspace registration machinery
**Related:** `CROSS_SCOPE_REFERENCE_GAP` (orthogonal — that fixes after-the-fact identity across DBs; this one prevents writes from silently landing in unreachable islands in the first place). A follow-on "Island Discipline" gap (TBD) will cover declared islands, firewall boundaries, and cross-continuity bridge semantics — this spec is scoped to the bug class (accidental islands) only.
**Last updated:** 2026-04-24

## The Problem

Continuity's store resolver falls back through a priority list (`--db` → `CONTINUITY_DB` env → per-project default → workspace default → global default). The fallback is silent: if no workspace or explicit path is set, resolution lands in `<git-root>/.continuity/db.sqlite` with no indication that this may not be the DB other constellation agents are reading.

A `global`-scoped memory written to an *undeclared* isolated project-local DB is **not** global. It is a local memory wearing a fake mustache. The scope field on the memory object advertises cross-project intent; the storage topology contradicts it. Nothing in the system makes that contradiction visible.

**Isolation is not the bug. *Undeclared* isolation is the bug.** Some continuity domains are isolated on purpose — firewalls between operational continuity and book/manuscript work, quarantines around uncertain-provenance stores, deliberately-local scratch domains. Those are valid. This gap is about the bug class where isolation was created by fallback config drift with no operator intent, and the system continued to accept writes as if the topology were normal.

This bit for real on 2026-04-24. The constellation thesis (scope=global, kind=summary, advisory class) was committed from a Claude Code session inside the continuity repo. Continuity's own `.mcp.json` was on the outlier pattern (`python -m continuity.mcp`, no workspace env) while 10 other repos in the constellation pointed at the shared observatory-family workspace. The thesis landed in `/home/jbeck/git/continuity/.continuity/db.sqlite` — an island — with no warning. The authoritative workspace DB had no record of it. The dogfood moment of "continuity carries doctrine about the constellation it's part of" was, for about 90 minutes, carried by a DB that only continuity itself could see.

The bug is obvious in hindsight and invisible until exactly the wrong moment. Classic silent-fallback failure.

## Design Stance

**Make topology visible at every surface that can write cross-project.** Silence is the enemy. Refusal is fine. Warnings are fine. Silent landing in an island is not.

The resolver itself is not broken — fallback is useful for local dev, tests, and first-run bootstrap. The bug is that the resolver's choice is hidden from callers who have reason to believe they're writing to shared state.

This gap adds visibility, not new resolution logic.

## Architectural Invariants

1. **Resolution source is always surfaced.** Every command that resolves a store path must be able to report *how* it resolved it: explicit path, env var, per-project default, workspace registration, global default, git-root fallback. `contctl where` already does this; extend the discipline to all write verbs.
2. **Fallback resolution is a warning, not a silence.** When the resolver lands on `<git-root>/.continuity/db.sqlite` via fallback (not via explicit workspace or explicit path), every mutation must emit a topology warning at least once per process. The warning names the resolved DB, the fallback source, and what a cross-constellation write would need to reach the shared workspace.
3. **Global-scope writes against fallback-resolved DBs must be loud.** Writing a `scope=global` (or `scope=workspace`) memory to a DB whose resolution source is project-local fallback is a contradiction. The system must warn prominently or refuse without `--allow-island` (or equivalent opt-in). A local memory wearing a fake mustache is the specific defect this gap closes.
4. **MCP startup emits topology as an environment note.** When the MCP server starts, its first emission to the agent includes the resolved workspace, DB path, resolution source, and principal. Agents operating against fallback DBs should know they are on an island before they write.
5. **`contctl doctor` exists and is the canonical place operators go to see this.** The command should show workspace, DB, principal, resolution source, and any warnings. It is the operator-legibility version of `where --explain`.
6. **Existing islands are evidence, not embarrassment.** Orphaned project-local DBs are not deleted as part of this fix. They are preserved as history. `contctl doctor` may optionally list known islands adjacent to the current resolution.

## Deliberately out of scope (v1)

- Automatic migration of island data into the workspace. (Import machinery lives in `CROSS_SCOPE_REFERENCE_GAP`; that's its job.)
- Cross-DB identity verification. (Same.)
- Network-facing discovery of workspace hosts.
- Enforcement of principal identity — this gap is about storage topology, not who is writing.
- Forbidding project-local fallback entirely. Dev work and bootstrapping still need it. The fix is visibility, not prohibition.

## Data Shape

No schema changes. This is a resolver / reporting / warning layer over existing primitives.

New fields/emissions:

- `contctl where` gains an optional `--explain` (or default-verbose mode) that surfaces resolution source more prominently, plus a `warnings` list when fallback is in play.
- `contctl doctor` — new command. Emits topology, workspace, principal, warnings, and optional island listing.
- MCP server `initialize` handshake (or equivalent first emission) includes a `continuity_topology` block with the same fields.
- Every mutation verb (`observe`, `commit`, `revoke`, `import`) checks resolution source at call time; if source is fallback *and* the request scope is `global` or `workspace`, emit a warning (or refuse, per policy).

## V1 Slice

1. Extend `contctl where` output to include an explicit warning when resolution source is fallback.
2. Add `contctl doctor` with topology + warnings.
3. Gate global/workspace-scope writes against fallback DBs with a warning; add `--allow-island` to explicitly opt in.
4. Add MCP startup topology emission (log or handshake message) so agents know their surface before writing.
5. Tests: resolution-source detection, warning emission on global writes against fallback, `doctor` output shape.

## Acceptance Criteria

- `contctl where` (and/or `doctor`) names the resolution source explicitly and warns on fallback.
- A `scope=global` commit against a fallback-resolved DB either refuses or warns loudly with actionable remediation text.
- MCP startup makes topology visible to the agent before the first write.
- A repo misconfigured like continuity was on 2026-04-24 produces a visible warning the moment an agent opens it, not 90 minutes later when someone notices the thesis is missing from the workspace.
- No existing resolver behavior changes; the layer is additive.

## Open Questions

1. **Warn vs refuse on global-scope fallback writes.** v1 probably warns, but the bug this gap addresses is exactly the case where warnings get ignored. Refusal-by-default with explicit opt-in may be warranted.
2. **Where does the MCP startup topology emission go?** JSON-RPC does not have a natural "banner" slot. Options: log line, diagnostic tool response, a first-response metadata field. Probably log + tool-accessible.
3. **Should `contctl doctor` scan for known islands?** Walking `~/git/*/.continuity/db.sqlite` to list potentially-stale project-local DBs has value for the exact bug this gap addresses, but crosses into filesystem-inspection territory that continuity otherwise avoids.
4. **Principal identity visibility.** This gap stops at topology. Whether `contctl doctor` should also surface principal resolution — and whether fallback principal is its own defect — is adjacent and may want its own gap.

## Short Version

Silent fallback resolution lets `global`-scope writes land in isolated project-local DBs that nobody else reads. Continuity's own thesis commit hit this bug on 2026-04-24. Fix: make storage topology visible at every surface that can write cross-project. `contctl where` names resolution source, `contctl doctor` surfaces warnings, MCP startup tells the agent where it is, and global-scope writes against fallback DBs either warn loudly or refuse without explicit opt-in. A global memory in an island DB is a local memory wearing a fake mustache.
