# Scoping — when to write to Continuity, and at what weight

A workflow discipline doc. For *what* the fields mean, see [`concepts.md`](concepts.md); for *how* to call the surfaces, see [`integrations.md`](integrations.md). This doc is about *choosing*: when continuity is the right home at all, which scope, which kind, which basis, which reliance class.

## The Rule

**Continuity is for durable orientation across agents and runs, not a transcript archive.**

The filter, every time:

> **Would a future agent make a worse decision if this were absent?**

If yes, consider continuity. If no, leave it in the conversation, in Claude memory, or in a repo doc. Writing everything interesting is how the substrate stops being usable for orientation.

## Where Should It Live — Continuity, Repo Docs, or Claude Memory?

Three durable homes, three different jobs:

| Home | Purpose | Example |
|------|---------|---------|
| **Repo docs** (`docs/`, `CLAUDE.md`, gap specs) | Canonical project-local doctrine, invariants, implementation contracts | `concepts.md`, `ISLAND_DISCIPLINE.md` |
| **Claude memory** (`~/.claude/.../memory/`) | Assistant working-style calibration, session persistence for *one* Claude | "jbeck prefers X", "don't lose state" |
| **Continuity** | Cross-agent orientation, durable project state, supersession-worthy doctrine | Constellation thesis, Island Discipline doctrine, project status snapshots |

Rule of thumb:

- If the note says *"how this Claude should behave,"* use Claude memory.
- If the note says *"how this project works / is implemented,"* use repo docs.
- If the note says *"how future agents should orient to this project or constellation,"* use continuity.

The same fact sometimes has a pointer in two homes (e.g., memory pointing at a continuity mem_id). That's fine. Duplicating the *content* across homes is not — pick a canonical home and point at it from the others.

## Scope Selection

Scope is a free-form string, with four conventions (see `concepts.md`):

- **`project:<name>`** — local to one project's work. Default for most commits. Use when the memory is only useful inside one repo/project.
- **`workspace`** — shared across a multi-project working set. Use when multiple projects in a workspace need to see it.
- **`global`** — cross-project doctrine. Use for constellation-wide orientation, shared constraints, or doctrine that other domains' agents might query.
- **`explicit`** (any other string) — caller-defined scope for cases the built-ins don't cover.

**Load-bearing:** `scope=global` is global only *within its declared continuity domain*. It is not universal across all domains. See [`ISLAND_DISCIPLINE.md`](gaps/ISLAND_DISCIPLINE.md). A global memory in an undeclared island is a local memory wearing a fake mustache.

Default to the narrowest scope that reaches the intended audience. Inflating scope "because this feels important" is the fastest way to pollute global doctrine with project-local noise.

Going broader is valid when the intended audience is broader. Do not broaden scope to make a memory feel more important; broaden only when another project or domain would predictably make a worse decision without seeing it.

## Kind Selection

Actual `MemoryKind` enum: `fact`, `note`, `decision`, `hypothesis`, `summary`, `constraint`, `project_state`, `next_action`, `experiment`, `lesson`.

When non-obvious:

- **`summary`** — orientation snapshots, thesis statements, doctrine digests. Supersedable. What you pick when "this is the current best articulation" and expect to refine.
- **`decision`** — something was *decided*, future work treats it as settled unless superseded. Stronger weight than `summary`.
- **`constraint`** — a durable restriction on future action ("no X before Y", "never do Z in scope A").
- **`lesson`** — postmortem-shaped findings; "do not repeat this rake."
- **`project_state`** / **`next_action`** — status buckets with the query-then-supersede pattern (see `feedback_supersede_pattern` if curious about local convention).
- **`fact`** / **`note`** / **`hypothesis`** / **`experiment`** — lower-weight, observation-shaped. Usually `status=observed` with `reliance_class=none`.

If several fit, pick the lower-weight one. A low-weight memory can be superseded or re-expressed at stronger weight later; a premature `decision` is harder to unwind cleanly.

## Basis Selection

Actual `Basis` enum: `direct_capture`, `operator_assertion`, `inference`, `import`, `synthesis`.

- **`operator_assertion`** — the operator/principal explicitly said so. Use for doctrine commits jbeck articulated.
- **`direct_capture`** — observed firsthand (tool output, file read, command run). Use for system-state captures.
- **`inference`** — derived from other memories. Cannot be `actionable` reliance_class (policy check in code).
- **`synthesis`** — combined from multiple sources. Same actionable restriction as inference.
- **`import`** — pulled from another system or continuity store. See `CROSS_SCOPE_REFERENCE_GAP`.

Basis is set at observe time and does not change. It is part of how `explain()` answers "why should I believe this." Mislabeling basis now creates fake provenance later.

## Reliance Class Selection

Actual `RelianceClass` enum: `none`, `retrieve_only`, `advisory`, `actionable`.

- **`none`** — default for observations. Visible in queries, not safe to rely on.
- **`retrieve_only`** — surfacable in queries, not used to drive action.
- **`advisory`** — may inform decisions, not authoritative. Right default for doctrine snapshots, thesis statements, orientation digests.
- **`actionable`** — may drive action subject to `rely_ok`. Rarely the right choice for new commits; promote deliberately when the memory is proven.

Note: `observed` is a *status*, not a reliance class. A memory with `status=observed` always has `reliance_class=none`. Promotion to a reliance class happens via `commit`.

## Anti-Patterns

Real failure modes, all observed:

- **Transcript hoarding** — writing every insight to continuity because it felt important. Bloats the substrate; makes orientation harder, not easier.
- **Scope inflation** — using `scope=global` because something seems philosophically important. Global is for cross-domain doctrine, not for emotional weight.
- **Authority laundering** — turning an agent's summary into committed project state without operator review. Use `operator_assertion` basis only when the operator actually asserted it.
- **Repo duplication** — copying whole specs into continuity instead of storing a compact orientation + pointer. The gap spec is canonical; continuity stores the doctrine, not the full text.
- **Fake closure** — writing "resolved" because no one has touched it recently. Use `supersedes` or `revoke` with a real reason.
- **Island blindness** — writing `global` memories from an undeclared local store. See [`ISLANDS_OF_CONTINUITY.md`](gaps/ISLANDS_OF_CONTINUITY.md).

## New Repo Bootstrap Checklist

When enrolling a new repo into a continuity workspace:

1. Decide whether the repo joins an existing continuity domain, gets a declared island, or explicitly opts out (firewall). See [`ISLAND_DISCIPLINE.md`](gaps/ISLAND_DISCIPLINE.md).
2. Configure `.mcp.json` with the shared workspace pattern: `continuity-mcp` binary, `CONTINUITY_WORKSPACE` and `CONTINUITY_PRINCIPAL_ID` env vars. (Match the 10-repo pattern; don't use `python -m continuity.mcp` with no env — that's the Islands-of-Continuity bug.)
3. Run `contctl where` to confirm resolution lands in the workspace DB, not the project-local fallback.
4. Register the project in the workspace manifest if applicable (`contctl workspace add-project`).
5. Write *at most one initial* orientation summary if the project needs it — `scope=project:<name>`, `kind=summary`, `basis=operator_assertion`, `reliance_class=advisory`. Body: what this project is, what domain it belongs to, what it must not be confused with, key repo docs to read first, known open gaps.
6. Do not import historical chat. Repo docs and git history are canonical for implementation; continuity stores orientation, not transcripts.

## Deferred: Tooling

The above is human/agent discipline. If these are applied consistently and the boring parts start asking to be automated, candidates include (not implemented yet):

- `contctl template new-repo` — generate `.mcp.json` + orientation stub
- `contctl observe --template orientation` — prefilled scaffold for project orientation summaries
- `contctl lint-memory` — detect scope inflation, authority laundering, island-blind writes
- `contctl doctor --scoping` — audit existing memories against the rule-of-thumb filter

Do not build these speculatively. Write the guide, apply the discipline, let the friction reveal which tools are worth building.

## Rule of Thumb

> Continuity should remember enough that the next agent can start in the right room, facing the right wall, without inheriting the whole argument.

## Related Reading

- [`concepts.md`](concepts.md) — canonical definitions of scope, kind, basis, reliance class, status, premise, rely_ok
- [`integrations.md`](integrations.md) — how to talk to continuity (MCP, CLI, library)
- [`gaps/ISLAND_DISCIPLINE.md`](gaps/ISLAND_DISCIPLINE.md) — domain topology, cross-domain bridges, why "global within declared domain" is the anti-empire bolt
- [`gaps/ISLANDS_OF_CONTINUITY.md`](gaps/ISLANDS_OF_CONTINUITY.md) — accidental-island visibility bug and fix
