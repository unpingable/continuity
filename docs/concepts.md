# Concepts

The canonical mental model for continuity. Other docs, gap specs, and external integrators should cite this rather than redefining terms.

## What continuity is

A governed state persistence layer. Three verbs — **observe**, **commit**, **rely** — plus a hash-chained receipt trail that makes every transition auditable.

In the broader tool constellation (this is the positioning, not the guts), three planes divide labor:

- **Continuity** carries **standing, witness, and reference** — what is known, what was decided, what standards apply, what prior work exists.
- **Governor** carries **consequence and arbitration** — what may be done, by whom, under what policy.
- **Signals** (where present) carry **liveness and observation** — diagnostic state, windowed telemetry, "something changed, go look."

Each tool should be usable on its own. Continuity should be *optional but valuable*: a tool gains durable memory, shared doctrine, and cross-scope explainability when it integrates, but must not become structurally fused. Mutable shared state across scopes is empire, just deferred. Hash-pinned, versioned references keep the constellation from collapsing into a soft monolith.

## The Core Model

### observe

Cheap, noisy, not binding. "Claude noticed this." "The CLI emitted that." "A spool file arrived."

An observation creates a memory object with `status=observed` and `reliance_class=none`. It appears in queries and can be read, but **no downstream system should rely on it without promotion**. This is the discipline that prevents silent promotion.

### commit

Durable, receipted, scoped. "This was explicitly promoted, with a reliance class, by a principal."

Commit transitions a memory from `observed` to `committed` and assigns a `reliance_class` — the contract for what downstream computation may do with the memory. Commit emits an event and a hash-chained receipt. After commit, `rely` checks become meaningful.

### rely

The check before action. "Given this memory, is it still safe to act on, given its premises and their status?"

`rely` is not a state; it is a *computation* performed at read time via `explain()`. It walks the premise graph, inspects statuses (including revocations), and returns a boolean `rely_ok` plus the reasoning. A single revoked hard premise taints the dependent. Nothing is automatically invalidated; the taint is derived freshly every time it is queried.

### premise

An explicit support edge from one memory (the dependent) to another memory, receipt, or external source (the source). Premises are written deliberately at observe/commit time. Continuity does not infer premises from content.

Premises carry a `LinkRelation` (`depends_on`, `supports`, `derived_from`, `implements`, `supersedes`, `invalidates`, `about`, plus case-record vocabulary `evidence_for`, `confirmed_by`, `ruled_out_by`) and a `LinkStrength` (`hard` or `soft`). Hard premises taint `rely_ok` when revoked; soft premises are informational.

### basis

Where a memory came from, epistemically. One of:

- `direct_capture` — observed firsthand (tool output, file read, command run)
- `operator_assertion` — the user/principal explicitly said so
- `inference` — derived from other memories or context
- `import` — pulled from another system or another continuity store
- `synthesis` — combined from multiple sources

Basis is recorded at observe time and does not change. It is part of how `explain()` answers "why should I believe this."

### receipt chain

Every state-mutating operation (observe, commit, revoke, import, tier-transition) produces a receipt. Receipts are hash-chained: each receipt carries `prev_hash` binding it to the previous one. The chain is append-only and tamper-evident.

The chain is the audit spine. Anything that breaks chain walkability breaks the system's core invariant.

### explain and rely_ok

`explain(memory_id)` returns:

- the memory's full event lineage,
- its receipt chain,
- its premises (upstream) and dependents (downstream),
- a freshly computed `rely_ok` boolean plus the reasoning.

`rely_ok` is the single question downstream systems should ask before depending on a memory. It reads taint from premise status at query time — not from a cached flag. This is deliberate: truth maintenance by *current query* rather than by *stored cascade* avoids invalidation races and keeps the system's state one layer deep.

## Scope and Identity

### scope

A memory's scope defines its sharing boundary. Values:

- `project` — local to one project's work
- `workspace` — shared across a multi-project working set
- `global` — shared across all projects (doctrine, standards, shared vocabularies)
- `explicit` — caller-provided string for cases the built-in scopes don't cover

Per-project SQLite DBs are the default. A project's store holds its own memories and may hold imported copies of memories from wider scopes (see `CROSS_SCOPE_REFERENCE_GAP`).

### memory_id

The canonical cross-DB identity for a memory. A UUID with a `mem_` prefix, assigned at creation, stable for the life of the memory. When a memory is imported from one store into another, `memory_id` is preserved — that is the whole point. Two stores holding rows with the same `memory_id` hold the same object (with content-hash verification to prove the version matches).

### supersession

Versioning via `LinkRelation.SUPERSEDES`. A new memory with a `supersedes` edge to an older memory becomes the preferred current version; the older memory remains as history. The supersede pattern is a convention (not enforcement): query the latest version via `memory_query_latest`, write new versions with explicit `supersedes` pointers.

Supersession is **additive, not retroactive**. A new version does not rewrite earlier reliance edges; anything that relied on version N still relies on version N. Later analysis may observe that the decision would classify differently under version N+1, but that is a new interpretive statement, not a historical rewrite.

### status

The lifecycle of a memory:

- `observed` — created via `observe`, not yet committed. May be queried but should not be relied on.
- `committed` — promoted via `commit` with a `reliance_class`. Appears in rely computations per its class.
- `revoked` — retired via `revoke`. Stays in the database as evidence (tombstone); taints dependents with hard premises at `rely` time.

Status transitions are one-way: observed → committed → revoked, or observed → revoked. No demotion, no silent reset.

### reliance_class

The contract for what downstream computation may do with a committed memory:

- `none` — not to be relied on (the default for observations)
- `retrieve_only` — may be surfaced in queries, not used to drive action
- `advisory` — may inform decisions but is not authoritative
- `actionable` — may be relied on to drive action, subject to `rely_ok` being true

Reliance class is assigned at commit time and can be raised by re-committing (within policy). The class is independent of `LinkRelation` — it answers "how may this memory be used," not "how does this memory relate to another."

### expires_at

A horizon on admissibility. Set at observe or commit time; carried on the memory object; honored by `rely_ok`.

Use `expires_at` whenever a committed memory represents a tolerance, exception, temporary allowance, windowed operational judgment, or any other claim that is only admissible under a bounded horizon. Expiry is part of the object's admissibility, not optional metadata.

After the horizon passes, the memory remains as historical evidence — queryable, explainable, auditable — but `rely_ok` returns false and queries filter it out by default (`include_expired=False`). This is the mechanism by which "acceptable for now" does not decay into "acceptable in general."

## Storage Layers

Three tables carry the core state:

1. `memory_objects` — materialized current state (one row per memory, reflects latest status)
2. `memory_events` — append-only mutation log (one row per transition)
3. `receipts` — hash-chained attestations (one row per mutation, bound to event)

Plus:

- `memory_links` — the provenance/dependency graph (premises and dependents, active and revoked)
- `spool_imports` — async ingest tracking for deferred imports
- `store_metadata` — singleton row identifying the store (store_id, scope_kind, schema_version)

## Cross-Cutting Invariants

These are the rules that make continuity *continuity*. They are invariant across all other choices.

### Historical structure is never destroyed

Revocation is by event, not by deletion. Revoked memories, revoked links, superseded versions — all remain as evidence. `explain()` reads taint from source status at query time. Tombstones over disappearance.

### Temporal admissibility must not decay into durable legitimacy

When a memory is only admissible under a bounded horizon, that horizon must be carried explicitly via `expires_at`. Once the horizon passes, the memory may remain as historical evidence, but it must not remain rely-able as current authority or standing permission. Tolerances, exceptions, and windowed operational judgments are admissible *for a time*, and that time is part of the commitment, not a footnote.

Remember the leash, not just the dog.

### Retrieval is not authority

Being queryable does not mean being safe to act on. `reliance_class` governs what may be relied on; `rely_ok` governs whether the premises still hold. An observation sitting in the database is not a permission slip.

### No silent promotion

An observation must not quietly harden into something downstream actions rely on without explicit transition and receipts. Every promotion is a state change. Every state change is receipted.

### Premises append, never silently replace

Additional premises can be added to a committed memory; existing premises are not silently overwritten. The dependency graph grows deliberately.

### Declared gaps over silent healing

Missing imports, hash mismatches, unreachable source stores, revoked-then-referenced memories — all surface as declared gaps in `explain()` output. The system never invents completeness to paper over absence.

### Supersession is additive, not retroactive

A new version of a shared standard does not rewrite earlier reliance. Historical meaning is pinned to the version that was relied on at the time.

### Rely/explain must remain walkable across boundaries

Scope boundaries, tier boundaries, import boundaries — the chain remains walkable. Latency may change at a boundary. Answerability may not.

## What Continuity Is Not

- **Not a coordination substrate.** Live locks, leader election, claim enforcement, "who has the baton right now" — these are Governor's job, or a dedicated liveness mechanism's. Continuity may *record* advisory state ("scope X is in progress, claimed by agent A"), but advisory state in continuity **has no action force until promoted through Governor**. Reading the record to inform yourself is fine; reading it to yield authority is the soft monolith forming.
- **Not a truth maintenance system.** No automatic invalidation cascades. `rely_ok` is computed fresh at query time from source status; it is not maintained across writes.
- **Not a vector database or semantic search engine.** Retrieval is by explicit scope/kind/status, not by similarity.
- **Not an LLM summarization tool.** The daemon persists structure, not vibes.
- **Not a distributed system.** Local SQLite per project. Cross-scope reference is by import with hash pinning, not by federated consensus.

## Operator Cadence

Continuity does not page you. Nothing in the substrate decides when an agent should consult it, and nothing prompts an agent to write back. That is deliberate — the alternative (instrumenting every conversational turn) would drown the signal in noise.

The honest split:

- **Interactive / exploratory work** — the operator's cadence. A human nudge ("go check continuity," "write that down before we lose it") is the right mechanism. Scope is moving, judgment about what matters is human-shaped, and the cost of forgetting is usually a re-derivation, not a corruption.
- **Repo, debug/production, cross-session handoff, supersession of prior decisions** — worth structural hooks eventually. The cost of forgetting is ugly (silent supersession, rely-like claims with no basis, durable state lost on session close). Hygiene receipts and passive preflight belong here, not in the chat path. Whether and when those hooks get built is a Governor question, not a continuity one (continuity exposes the surfaces; Governor decides when their use is expected).

A useful starting heuristic: if the work is repo-shaped or production-shaped, assume continuity is in scope and consult before acting. Otherwise, trust the operator to nudge.

## Related Reading

- `docs/integrations.md` — how to talk to continuity (MCP, CLI, library)
- `docs/gaps/` — proposed doctrine for architectural shifts
- `docs/gaps/CONTINUITY_STORAGE_GAP.md` — tiering within a store
- `docs/gaps/CROSS_SCOPE_REFERENCE_GAP.md` — identity across stores
