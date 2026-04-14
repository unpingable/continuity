# Gap: Cross-Scope Reference — identity and import for continuity that crosses DB boundaries

**Status:** proposed
**Depends on:** existing memory / link / receipt primitives; canonical JSON hashing
**Related:** `CONTINUITY_STORAGE_GAP` (orthogonal — that spec is about tiering within a project's store; this one is about identity across project stores)
**Blocks:** durable cross-project reliance on shared doctrine; governor's ability to cite specific versions of continuity-owned standards; any workflow where one project's decision historically depends on another project's doctrine object.
**Last updated:** 2026-04-14

## The Problem

Continuity is per-project-DB by design. Each project has its own SQLite store, its own receipt chain, its own local explain surface. That is correct and load-bearing: it keeps blast radius local and lets each project own its own history.

But some objects want to be referenceable across that boundary. Shared doctrine, standards, vocabularies, and (soon) gap specs like this one are written once and relied on by many. Governor already consults continuity for doctrine; the first cross-system edge has been walked. As more projects gain continuity stores, this pattern will grow.

The naïve shapes all fail:

- **Copy the standard locally in each project.** Silent forks at the same name. Drift is invisible.
- **Reference a mutable shared document by title.** Old receipts silently change meaning when the shared doc is edited. Historical fraud.
- **Keep shared objects only in a global DB and leave local references as URLs.** Old decisions terminate at "some doc we were using at the time."

The gap is not that continuity lacks a model for shared objects. **Global-scope memories, `supersedes` link relations, and premise refs already give us most of what we need.** The gap is that references crossing DB boundaries have no identity verification, no import receipt, and no hash-pinning — so "project A relied on standard X" is a claim continuity cannot yet prove.

## Design Stance

**Parasitize existing primitives. Add only what cross-DB identity actually requires.**

Shared objects are already representable as memory_objects in global scope. Versioning is already representable via `LinkRelation.SUPERSEDES`. Reliance is already representable via `PremiseRef.memory_id`. The only genuinely new concern is:

- How do two DBs agree that they hold the *same* memory at the *same* version?
- How does an import into a local store become a historical act in the local receipt chain?
- How does a stale or drifted cached copy surface as a declared gap rather than silent divergence?

That is a hash-identity + import-receipt layer on top of existing machinery, not a second continuity system.

Shared-object taxonomy, richer reliance vocabularies (normative / informative / cited), and cross-project search are **second-order refinements**. They belong in follow-up gaps after v1 proves cross-scope reference can work at all.

## Architectural Invariants

The following are frozen as doctrine. Downstream decisions depend on them.

### Identity across DBs

1. **`memory_id` is the canonical cross-DB identity.** A memory with id `mem_xyz` in the global-authoritative store is the same object as `mem_xyz` in any project's local store. The UUID is stable by construction; treat it as the primary key across DBs, not just within one.
2. **Content hash pins the version.** Every imported memory carries a content hash over its canonical form (scope, kind, content, status, reliance_class, supersedes pointer if any). Two DBs holding `mem_xyz` at matching content hashes hold the same version; mismatched hashes are drift, surfaced honestly.
3. **Supersession chains span DBs.** When a shared standard evolves via `LinkRelation.SUPERSEDES`, that chain must be walkable from any DB that has imported any node in it. Imports may be partial; the chain's walkability within the imported subset must still hold.

### Import as historical act

4. **Cross-DB import emits a receipt in the local chain.** When project B pulls global `mem_xyz` at hash `H` from store `store_id_A`, project B's receipt chain gets a `memory.imported` (or equivalent) receipt that carries `(memory_id, content_hash, source_store_id, imported_at)`. The local audit trail shows when and from where each cross-scope reference entered.
5. **Import is append-only.** Re-importing a newer version of the same memory produces a new local row bound to a new content hash and a new import receipt. The old imported version remains as history, not overwritten. Continuity's append-only doctrine does not pause at scope boundaries.
6. **An import is a witness copy, not a fork.** Importing `mem_xyz` locally does not give the local project authority to modify it. Local mutations to an imported memory are either disallowed or explicitly promote the memory to a new local-scope object with its own identity. A cache is not a new canonical object.

### Reliance and traversal

7. **Local premises may target imported memories.** A local memory citing a shared standard uses the existing `PremiseRef.memory_id` mechanism. No new edge type. The premise carries the imported memory's content hash at the time of reliance, so the reliance is version-pinned even if the local import is later refreshed.
8. **`explain()` crosses scope boundaries cleanly.** Traversal from a local memory into its imported premise must resolve the shared object's current local state, report its content hash, flag any mismatch against the premise's pinned hash, and walk `supersedes` links within the imported subset.
9. **Mismatch between pinned hash and current import is a declared gap.** If a premise was pinned at hash `H1` but the local import now carries hash `H2`, `explain()` surfaces the drift explicitly. It does not silently resolve to current, nor does it silently fail.

### Authority and availability

10. **Shared-object authority is scope-defined, not store-defined.** A memory in `global` scope is authoritative regardless of which store holds the authoritative write path. Projects rely on the identity-and-hash contract, not on knowing which store is the origin.
11. **A missing import is not a missing reference.** If a local premise points at `mem_xyz` and the local DB has no import record for it, `explain()` declares the gap and can still show the premise edge, content hash (from the pin), and what the reference was supposed to be. Folklore is worse than honest absence.
12. **Revocation crosses scope.** A revoke against an imported memory (in its authoritative store) taints dependents in every importing project's `rely_ok` computation, once the revocation is imported. v1 does not solve push-based propagation; pull-at-explain-time with honest gap declaration is sufficient.

### Deliberately deferred (do NOT freeze in v1)

- Reliance-kind vocabulary beyond what existing `LinkRelation` + `reliance_class` express (normative / informative / cited / pinned_snapshot — valid concerns, but second-order)
- Push-based propagation of shared-object updates or revocations
- Cross-project search UI
- Federated reference resolution across hosts
- Permission/authority model for multi-writer shared stores
- Branch/merge semantics for shared doctrine editing
- Automatic refresh policies for stale imports
- Conflict resolution when multiple imports disagree

## Data Shape

No new tables in v1. The machinery lands on existing ones.

**`memory_objects`:** already carries `scope`, `kind`, content, status, reliance_class, and a stable `memory_id`. Global-scope memories represent shared objects. No schema change.

**`memory_links`:** already carries `LinkRelation.SUPERSEDES` for versioning and premise-style edges for reliance. No schema change.

**`memory_events`:** new event type `memory.imported` carrying `(memory_id, source_store_id, imported_content_hash)`. Existing append-only machinery handles persistence.

**`receipts`:** existing chain. Import events produce receipts like any other state transition. No schema change.

**`PremiseRef` / `MemoryLink`:** gain an optional `pinned_content_hash` field at reliance time, capturing the exact version the reliance was bound to. If absent, reliance is unpinned (discouraged for shared-object references, allowed for local ones).

**Shared-object content hash computation:** reuses `util.jsoncanon.canonical_json()` over a defined subset of the memory_object row. The exact subset is an open question (see below); the candidate is `(memory_id, scope, kind, content, reliance_class, supersedes_memory_id)` — fields whose change constitutes a new version, excluding timestamps and local-only metadata.

## V1 Slice

Keep the first implementation narrow.

1. **Content-hash function** over a defined memory-object subset, deterministic across DBs.
2. **Import path**: a new CLI/API verb (e.g. `contctl import --from STORE --memory-id MID`) that pulls a memory from a source store, writes it locally, emits a `memory.imported` event, and produces a receipt carrying the content hash.
3. **Pinned premises**: `PremiseRef` and `MemoryLink` accept an optional `pinned_content_hash`. When reliance targets an imported memory, pinning is strongly encouraged.
4. **`explain()` cross-scope traversal**: when a premise points at an imported memory, `explain()` resolves it, reports pin-vs-current match/mismatch, and walks local `supersedes` edges within the imported subset.
5. **Gap declaration**: missing imports, hash mismatches, and revoked-then-imported targets all surface as declared gaps in `explain()` output. No silent fallback.
6. **Proving ground**: gap specs themselves. Publish the gap specs in this repo as global-scope memories with well-known `memory_id`s; have one project (governor is a natural candidate) import and reference one of them via a pinned premise; demonstrate the full explain walk end-to-end.

That is enough to prove the feature without inventing scaffolding the real workload has not asked for.

## Explicit Deferrals

Not v1 (listed above in the invariants section, repeated here for readability):

- Richer reliance vocabularies
- Push propagation of shared-object updates
- Cross-project search
- Multi-writer authority and permissioning
- Automatic import refresh
- Conflict resolution across divergent imports
- Federated cross-host resolution

## Open Questions

1. **What exactly goes into the content hash?** Candidate: `(memory_id, scope, kind, content, reliance_class, supersedes_memory_id)`. Does `status` belong? Probably yes for committed/revoked, but a `revoked` state of a shared object is a new version in its own right — needs thought.
2. **How does a project discover the authoritative source for a given memory?** v1 can accept an explicit `--from STORE` and defer discovery. Later: a registry, a naming convention, or a manifest per scope.
3. **Should the `supersedes` link for shared objects be imported eagerly (pull the whole chain) or lazily (walk on demand)?** Probably lazy with explicit prefetch; decide when implementing.
4. **What happens when an imported memory's source store is unavailable at explain time?** Fall back to the local pinned copy, flag the unreachability as a gap, never pretend the pin is "current-verified."
5. **Does pinning belong on `PremiseRef` only, or also on `MemoryLink.src_memory_id` for links that are not premises?** Probably both; verify when implementing.
6. **Should import itself require standing / approval?** Likely yes eventually — pulling an external object into the local audit trail is a standing-relevant act. Defer until Standing integration lands.

## Acceptance Criteria

This gap is closed when:

- A memory in global scope can be imported from one store into another with a verified content hash.
- Each import appears in the importing store's receipt chain as a historical act.
- Premises on imported memories can be version-pinned at reliance time.
- `explain()` traversals cross scope boundaries, report pin-vs-current state, and walk `supersedes` lineage within the imported subset.
- Hash mismatches, missing imports, and unreachable source stores all surface as declared gaps, never silent fallbacks.
- At least one real shared-object class (gap specs, doctrine) is proven end-to-end: authored in one store, imported by another, cited by a local memory, walkable via `explain()`.
- No existing continuity primitive was duplicated; the cross-scope layer is additive, not parallel.

## Short Version

The gap is not "we need a model for shared context."

The gap is that references crossing project DB boundaries have no identity verification, no import receipt, and no hash-pinning — so "project A relied on standard X" is a claim continuity cannot yet prove. Fix it by reusing existing primitives and adding a thin cross-DB identity layer: canonical `memory_id`, content hash over a defined subset, import-as-receipt, pinned premises, and honest gap declaration when things drift. Everything else — richer reliance vocabulary, push propagation, cross-project search — is second-order and deferred.
