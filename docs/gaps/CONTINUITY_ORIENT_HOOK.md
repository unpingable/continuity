# Gap: Continuity Orient Hook — make consultation load-bearing at the entrypoint

**Status:** proposed
**Depends on:** existing `contctl` CLI, MCP server query primitives, workspace manifest from `ISLAND_DISCIPLINE`
**Related:** `ISLAND_DISCIPLINE` (declared topology that orient fans across), `ISLANDS_OF_CONTINUITY` (visibility prerequisite for fresh sessions), `CROSS_ISLAND_BRIDGES_GAP` (cross-island reads share orient-shape concerns); operator-side companion `feedback_pointer_section_pattern` (claude-memory write-side discipline this gap operationalizes); continuity `mem_5ba16efa6c514afa874c28cc753da5d3` (meta-orientation diagnosis this gap is the mechanism for)
**Last updated:** 2026-04-28

## The Problem

Continuity substrate is adequate. Consultation is not load-bearing. Sessions reach continuity through `Claude Code → MCP → Continuity`, but the reflex to actually consult is missing — so cross-cutting doctrine at `workspace` or `global` is routinely missed by sessions that query only their project scope, and lessons that should land at `workspace` or `global` first land in local Claude auto-memory and require manual operator promotion.

Three observed seams (forcing cases on 2026-04-28):

- **Write seam.** Cross-constellation lessons land first in local Claude auto-memory and require manual promotion. labelwatch-claude wrote `lesson_operationally_up_epistemically_degraded.md` to local memory; operator promoted it to continuity at scope=workspace (`mem_5a7a4680...`).
- **Read seam.** A session queries narrowly (e.g., `scope="nq"`) and misses relevant `workspace` or `global` entries. NQ-claude wrote at scope=workspace correctly; the receiving session's project-scope-only query missed it.
- **Session-clear seam.** Cleared sessions do not reflexively consult continuity. The substrate has been adequate for some time; the entry-point reflex is what doesn't survive a session clear.

The naive fix is "record more discipline notes inside continuity," which patches the sessions that already consult while doing nothing for the ones that don't. The mechanism has to live where sessions actually start, not inside the room they aren't entering.

## Design Stance

**Make consultation load-bearing on the execution path. Don't conflate policy ownership with mechanism location.**

Policy ownership for "claude must consult continuity" may be Governor-shaped (a hygiene rule). Execution path is `Claude Code → MCP → Continuity`. The reflex has to be installed somewhere on THAT path or the policy is unenforced. Saying "Governor's lane" without naming the adapter layer is itself a governance smell — a very elegant way to leave the broken pipe unfixed.

This gap scopes to the adapter layer continuity controls or co-owns: `contctl`, the MCP server, and the workspace manifest. Claude Code bootloader integration (`.claude/settings.json` hooks, repo CLAUDE.md conventions) is downstream consumer work that builds on this gap's primitives — not in scope here.

**Non-goal:** This gap does not create new continuity doctrine. It makes continuity consultation operationally load-bearing for fresh sessions. The "more memory" reflex is the wrong fix.

**The anti-pattern this gap exists to prevent:** *if the user has to remember to ask for orientation, the hook has failed.*

## Architectural Invariants

### Orient is a fanout, not a search

1. **`contctl orient` is the canonical entrypoint.** A single command produces an orientation packet for a named project (or the current working directory's resolved project). The packet covers the operationally relevant scopes a fresh session would otherwise have to know to query individually.

2. **Default fanout: `{global, workspace, workspace:<own>, project:<own>}`.** These four are non-negotiable — every fresh session needs cross-cutting doctrine, workspace-level shared state, the workspace-name-prefixed scope (which exists in current data and is otherwise easy to miss), and the project's own scope.

3. **Related-organ scopes are declared, not inferred.** A workspace manifest may declare additional scopes the orient should fan across (e.g., NQ orient surfaces relevant `agent_gov`, `nightshift`, `continuity` entries). Declaration lives in the workspace manifest per `ISLAND_DISCIPLINE`'s precedent for workspace-level config; per-project override is allowed via the manifest's `per_project` map. No hardcoding of related-organ relationships in Claude behavior or in MCP code.

4. **Orient output is a packet, not a dump.** Compact summary: recent decisions, active lessons, open gaps, "read this before acting" pointers, and explicit declared-gaps where source stores were unreachable. Volume-control via `--since`, `--kind`, `--limit` filters is required; the default packet must fit in a session's working attention.

### Read-side advisory warns at the seam

5. **Project-scope-only queries with parent-scope content trigger an advisory.** When `memory_query(scope="<project>")` runs and the workspace manifest declares parent scopes (`workspace`, `workspace:<name>`, `global`) that have committed memories newer than the caller's last orient, the response surface includes a one-line advisory: "Project-scope query only; N memories at parent scopes may be missed. Run `contctl orient --project <name>` to fan across."

6. **The advisory is advisory, never blocking.** It does not refuse the narrow query, does not modify results, does not auto-fan. Its job is to make the reader aware that the scope they chose is narrower than where cross-cutting doctrine actually lives. Operators decide whether to fan.

### Write-side lint suggests promotion at the seam

7. **`contctl lint-promotion <file>` is the write-side primitive.** It scans a file (typically a claude-memory write) for heuristic flags that suggest cross-constellation material: explicit mentions of *future agents*, *cross-constellation*, *workspace*, AG / NQ / NS / continuity / governor relationships, *doctrine*, *scope*, *admissibility*, *boundary*, "this should live in continuity," constellation roles. When the heuristic fires, the lint surfaces: *"This looks like continuity material, not local Claude memory. Promote to continuity? Defer? Mark local-only?"*

8. **Write-side lint is operationally useful only with a hook.** Continuity does not own the hook surface; Claude Code's `PostToolUse` (on Write tool, path-matched to claude-memory directories) or equivalent is the integration point. V1 ships `contctl lint-promotion` as a callable subcommand; the hook wiring is downstream work. Without the hook, the lint exists but operators forget to run it — same problem this gap is trying to solve.

### Pointer-section pattern is the declarative companion

9. **Repo `CLAUDE.md` / `MEMORY.md` may declare related scopes / organs in a parseable block.** A standard "Continuity Orientation" section format that names the project, its workspace, its declared related-organ scopes, and any explicit "always orient against these" pointers. The block is machine-readable enough that `contctl orient` can consume it as a per-project config supplement to the workspace manifest.

10. **Declaration is opt-in but discoverable.** Repos without the section get default fanout based on workspace manifest. Repos with the section get the declared related-organ scopes added. `contctl orient --project <name> --explain` reports which sources contributed to the fanout (workspace manifest, per-project block, defaults) so operators can audit.

### Advisory until enforced; no silent escalation

11. **The orient hook never auto-promotes anything.** It does not turn observed memories into committed; it does not raise reliance class; it does not author bridges. It is a read-side fanout plus a write-side suggestion. Promotion remains an explicit operator act.

12. **Mandatory orient-on-session-start is downstream consumer work.** This gap exposes the primitive; whether `.claude/settings.json` hooks call it on every session, or per project entry, or on demand, is for the bootloader to decide. V1 ships everything advisory; mandatory enforcement is V2 territory and lives in Claude Code's settings, not in continuity.

## Data Shape

**Workspace manifest gains:**

```json
{
  "id": "observatory-family",
  "purpose": "bridgeable",
  "orient": {
    "default_related_scopes": ["agent_gov", "nightshift", "continuity"],
    "per_project": {
      "nq": { "related_scopes": ["agent_gov", "nightshift"] },
      "nightshift": { "related_scopes": ["nq", "agent_gov", "continuity"] }
    }
  }
}
```

**Repo `CLAUDE.md` Continuity Orientation block (proposed convention):**

```markdown
## Continuity Orientation

Project: nq
Workspace: observatory-family
Declared related scopes: agent_gov, nightshift, continuity, workspace
Always orient before: making project-state claims, citing doctrine, declaring closure
```

**`contctl orient` output (skeleton):**

```
Orientation packet for project=nq, workspace=observatory-family
  Fanout: global, workspace, workspace:observatory-family, project:nq, agent_gov, nightshift, continuity
  Recent decisions (3):
    mem_02ab085f...  agent_gov   Admissibility Pattern Language Boundary  (2026-04-28)
    mem_5a7a4680...  workspace   Operationally up vs epistemically degraded  (2026-04-28)
    mem_5ba16efa...  global      Consultation must be load-bearing  (2026-04-28)
  Active lessons: 2  | Open gaps: 1  | Read-before-acting pointers: 2
  Declared gaps (unreachable sources): 0
```

**`contctl lint-promotion <file>` output:**

```
File: ~/.claude/projects/-home-jbeck-git-labelwatch/memory/some_lesson.md
Heuristic flags: [cross-constellation, future agents, doctrine, scope]
Suggestion: Looks like continuity material. Consider:
  - contctl observe --scope workspace --kind lesson --basis synthesis ...
  - or add `local-only: true` frontmatter to suppress this lint
```

## V1 Slice

1. **`contctl orient`** — fan across `{global, workspace, workspace:<current>, project:<current>}` plus workspace-manifest-declared related-organ scopes. Compact packet output. `--since`, `--kind`, `--limit` filters. `--explain` mode shows fanout source.
2. **Read-side advisory in MCP `memory_query`** — when scope=<single project> is used and parent scopes have content the caller hasn't seen recently, append a one-line advisory. `--no-orient-advisory` disables.
3. **Workspace manifest `orient` block** — schema additions for `default_related_scopes` and `per_project` overrides.
4. **Repo CLAUDE.md Continuity Orientation parser** — `contctl orient` consumes the block when present in CWD's CLAUDE.md.
5. **`contctl lint-promotion <file>`** — heuristic-based promotion suggestion subcommand. Standalone, no hook wiring.
6. **Tests:** orient packet round-trips; advisory fires only when narrow query has parent-scope content; manifest declarations apply correctly; per-project overrides work; lint-promotion catches the labelwatch forcing case.

## Deliberately out of scope (v1)

- **Claude Code bootloader integration.** `.claude/settings.json` hooks calling `contctl orient` at session start are downstream consumer work. This gap exposes the primitive; the bootloader integration follows.
- **Hook-wiring for `lint-promotion`.** Same reason — Claude Code `PostToolUse` integration is downstream. Subcommand ships in V1; hook integration in V2 when settings.json conventions are stable enough to depend on.
- **Automatic orient-on-every-query.** Aggressive read-side fanout that always returns parent-scope content alongside narrow queries — too much volume, undermines the operator's narrowing-on-purpose signal.
- **Mandatory orient before commit.** The substrate already has discipline at write time (basis, scope, reliance class). Adding orient-must-have-been-called as a precondition is over-fitting.
- **Cross-workspace orient.** Fan-across-domains is `CROSS_ISLAND_BRIDGES_GAP` territory. Orient stays within one workspace's declared topology.
- **Per-Claude-instance "you've already oriented today" state.** Stateful orient memory is a session-management feature, not a continuity primitive. Sessions have no durable identity to track.

## Acceptance Criteria

- A single command (`contctl orient --project <name>`) fans across `{global, workspace, workspace:<current>, project:<current>}` plus declared related scopes. Output is a compact packet.
- A `memory_query` with a single project scope, when parent scopes contain committed memories the caller hasn't seen, returns an advisory line pointing at orient.
- A repo's `CLAUDE.md` Continuity Orientation block declares related scopes/organs without hardcoding them in Claude behavior. `contctl orient` consumes the block.
- `contctl lint-promotion <file>` flags claude-memory writes whose content matches the heuristic (cross-constellation, future agents, doctrine, scope, admissibility, etc.) and suggests continuity promotion or local-only marking.
- The mechanism remains advisory in V1: no silent promotion, no auto-fan, no automatic authority escalation. Operator invocation drives every action.
- The keeper line is preserved: *queryable memory is not operational memory unless the tools fresh sessions actually use are forced to query it.*
- The anti-pattern is explicitly named in the spec: *if the user has to remember to ask for orientation, the hook has failed.*

## Open Questions

1. **Where does the per-project related-scopes block actually live?** Workspace manifest is the canonical home for workspace-level config; per-project overrides could live in the manifest's `per_project` map, in `store_metadata`, or in CLAUDE.md. The querying side cares; the writing side may not. Pick at implementation when first concrete per-project case lands.
2. **Read-side advisory threshold.** Always fire when parent scope has committed memories? Only fire when parent scope has memories newer than X? Only fire on first query of session? Wait for usage to settle.
3. **Write-side lint vocabulary.** The starting heuristic (cross-constellation / future agents / doctrine / scope / admissibility / boundary / etc.) is provisional. False positives will tune it. Open until ~10 real lint fires demonstrate the right shape.
4. **Orient packet format.** Compact-by-default vs operator-customizable? V1 ships one shape; format flexibility waits for downstream consumer needs.
5. **Hook surface for Claude Code integration.** `PreToolUse` vs `PostToolUse` vs `SessionStart` — depends on Claude Code's settings.json conventions and what survives version drift. Defer until stable enough to depend on.
6. **Multi-consumer neutrality.** Fanout/lint shape is built around Claude Code now. If Codex / Gemini / others integrate via different MCP-equivalents, the orient primitives should remain neutral to consumer. V1 stays Claude-Code-shaped because that's the live consumer; expand when a second consumer materializes.

## Revision trigger

Revise this gap when implementation pressure proves it underspecified — not when downstream events merely happen.

The likely revelation moments: the first `contctl orient` call lands and exposes a missing fanout case; the read-side advisory fires too often or too rarely against real usage; the write-side lint heuristic produces unacceptable false positives; per-project block declarations turn out to need a structured grammar the V1 parser doesn't carry. The trigger in each case is *"I tried to use this and it didn't tell me what to do"* — not "X happened, time to revisit."

## Short Version

Continuity substrate is adequate; consultation is not load-bearing. Sessions reach continuity via `Claude Code → MCP → Continuity`, so the fix has to live on that path — not at policy ownership (which may be Governor-shaped) and not by recording more memory inside the substrate that's already being missed. This gap exposes three primitives at the entrypoint adapter layer: `contctl orient` to fan a session's read across `{global, workspace, workspace:<own>, project:<own>}` plus declared related-organ scopes; a read-side advisory when project-scope-only queries miss parent-scope content; and `contctl lint-promotion` for write-side material that looks like continuity doctrine. Repo CLAUDE.md declares related scopes/organs without hardcoding them in Claude behavior. Claude Code bootloader integration is downstream consumer work this gap does not own. The mechanism stays advisory in V1 — no silent promotion, no automatic enforcement. Keeper line: *queryable memory is not operational memory unless the tools fresh sessions actually use are forced to query it.* Anti-pattern: *if the user has to remember to ask for orientation, the hook has failed.*
