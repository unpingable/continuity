# Gap: Island Discipline — declaration, purpose, and bridging across continuity domains

**Status:** proposed
**Depends on:** existing workspace registry (`~/.config/continuity/workspaces/`), workspace manifest shape, `CROSS_SCOPE_REFERENCE_GAP` primitives (content hashing, import receipts, pinned provenance)
**Related:** `ISLANDS_OF_CONTINUITY` (this gap's predecessor — that spec fixes the accidental-island visibility bug; this one specifies what a *declared* island is, how purposes are classified, and what cross-domain exchange looks like). `CROSS_SCOPE_REFERENCE_GAP` is the v1 substrate this gap builds on, not a parallel system.
**Last updated:** 2026-04-24

## The Problem

Continuity currently has one implicit topology: a workspace-resolved DB is "shared," a project-local fallback DB is "isolated," and nothing else is named. That is insufficient because isolation itself is not the bug — *undeclared* isolation is. Some continuity domains are intentionally kept separate:

- **Firewall domains.** Book/paper/manuscript work is deliberately off operational continuity. Exploratory contradiction, mutable fragments, and independent derivation would be damaged by shared scope. This pattern has been operated deliberately for a while; it just lacks a name.
- **Quarantined domains.** Stores whose provenance, schema version, or trust basis is uncertain. Exchanging with them requires explicit ceremony.
- **`local_dev_test` domains.** Throwaway stores for experimental features, destructive testing, schema evolution.
- **Archival domains.** Frozen stores kept as historical record, not live writeable state.

Today the system cannot distinguish these from accidents. A firewall island and a fallback-resolution accident look identical from the outside: one SQLite file in one directory. The `ISLANDS_OF_CONTINUITY` spec addresses the bug case (accidental); this spec addresses the valid cases (declared) and the contract for cross-domain exchange.

## Design Stance

**Declaration is the primitive. Purpose classifies declared domains. Bridges reuse cross-scope-reference machinery.**

A continuity domain is a set of stores that share a declared identity and exchange discipline. Declaration is the act of recording that identity in a location other continuity instances can discover. Undeclared stores are either workspace-resolved (and thus part of their workspace's domain) or accidental islands. The system should never have to guess which.

Cross-domain exchange is not a merge and not a federation. It is **typed, non-transitive, receipted import** — the same shape `CROSS_SCOPE_REFERENCE_GAP` already specifies for cross-DB references within a workspace, with added domain metadata. One hash-pinning system, not two.

## Architectural Invariants

### Declaration

1. **Isolation is valid only when declared.** An isolated store without a domain declaration is a topology fault, not a boundary. The `ISLANDS_OF_CONTINUITY` visibility layer already names this; this gap formalizes the other half — what "declared" means operationally.
2. **Declared domain metadata lives in the workspace manifest (or equivalent).** The existing `~/.config/continuity/workspaces/<name>/manifest.json` is the natural home. It gains a `purpose` field (`firewall` / `bridgeable` / `quarantined` / `local_dev_test` / `archival`) and optional `bridge_policy` metadata. Non-workspace stores declare via a per-store metadata file alongside the DB, or via `store_metadata` rows.
3. **Declaration is discoverable.** A continuity instance (CLI or MCP) can enumerate known domains from the workspace registry and optionally from a per-user domain registry. Undeclared stores found during discovery are reported as warnings, not errors, and never silently treated as declared.

### Scope and domain

4. **Global scope is global only within its declared domain.** A `scope=global` memory in domain A is not automatically global in domain B. This is the load-bearing invariant that prevents `scope=global` from becoming fake empire. Cross-domain global references must be explicit imports, not implicit visibility.
5. **Purpose constrains bridge eligibility.** Firewall domains refuse bridges by default. Bridgeable domains define what artifact classes may be exported and to whom. Quarantined domains may receive imports but do not export until re-classified. `local_dev_test` and `archival` domains are bridge-inert.

### Bridges (cross-domain import)

6. **Bridges reuse `CROSS_SCOPE_REFERENCE_GAP` primitives.** Content hashing, import receipts, pinned provenance, and `memory_id` stability across stores are not reinvented here. A bridge is a cross-scope import with added domain metadata on both ends. One hash-pinning religion, one import-receipt shape.
7. **Imports start as observed. Always.** Even if the source domain considered the memory committed with actionable reliance. Commitment does not travel. Target-domain operator review is the only path from observed to committed after a bridge crossing.
8. **Reliance is non-transitive across domains.** A memory in domain B that imports from domain A carries the pinned source content hash, but domain A's reliance_class does not automatically transfer. Domain B makes its own commitment decision under its own standing.
9. **Bridges are receipted on both sides.** The source domain records an export event; the target records an import event. Both chains stay walkable.

### Accidental islands remain bugs

10. **Declaration does not retroactively validate accidental islands.** Declaring a previously-accidental island as intentional-after-the-fact is a legitimate operator act, but the prior accidental-island writes do not thereby become clean global claims. The declaration receipts the boundary going forward; the orphan history stays as evidence.
11. **Enforcement mode and semantic eligibility are distinct.** V1 may implement policy violations (e.g., firewall export attempts) as loud warnings rather than hard refusals, for operator visibility and scar-tissue accumulation. But the semantic eligibility result must remain precise: every bridge attempt evaluates to `allowed`, `denied`, or `requires_override`. Enforcement mode governs what the system *does* with that evaluation; it does not change what the evaluation *means*.

## Deliberately out of scope (v1)

- Night Shift cross-continuity coordination machinery (scheduler/Night Shift's jurisdiction, separate gap in that repo).
- Automatic discovery of remote continuity hosts over the network.
- Multi-writer bridge authority or federated consensus.
- Purpose change as a governed act (e.g., promoting a quarantined domain to bridgeable) — the declaration can change, but the semantics of that transition are deferred.
- UI for bridge review/approval.
- Enforcing purpose constraints as hard refusals — v1 warns loudly and surfaces eligibility; hard refusal follows later if warnings prove insufficient.

## Data Shape

**Workspace manifest** gains:

```json
{
  "id": "observatory-family",
  "label": "ATProto observatory family",
  "purpose": "bridgeable",
  "bridge_policy": {
    "exports": ["decision", "lesson", "constraint"],
    "imports_from": ["*"],
    "operator_review_required": true
  },
  "projects": [...],
  "created_at": "..."
}
```

**Per-store declaration** (for non-workspace DBs) uses a sibling file `domain.json` alongside the DB, or a row in `store_metadata` with a `domain_declaration` field. Exact placement TBD; workspace manifest is the canonical path.

**Bridge event and receipt** reuse existing primitives from `CROSS_SCOPE_REFERENCE_GAP`: a `memory.imported` event with additional fields `source_domain_id` and `source_domain_purpose`. Import receipts in the target domain carry the full cross-domain provenance.

**No new enums required for v1** beyond the `DomainPurpose` taxonomy (firewall, bridgeable, quarantined, local_dev_test, archival).

## V1 Slice

1. **Extend workspace manifest** with `purpose` and optional `bridge_policy`. Existing unannotated workspaces are treated as `legacy_bridgeable` for compatibility, with a one-time warning until explicitly declared. `legacy_bridgeable` is a migration marker that makes the missing declaration visible — it is *not* a declaration, and it should not masquerade as one.
2. **Add `contctl domain show` / `contctl domain list`** — enumerate declared domains, show purpose, bridge policy, and any warnings from the visibility layer.
3. **Warn on cross-domain writes without declaration.** A bridge import into a target with no declared purpose is flagged. A bridge export from a firewall domain is flagged harder.
4. **Bridge command**: `contctl bridge import --source-domain <name> --memory-id <mid>` pulls a memory via `CROSS_SCOPE_REFERENCE_GAP` machinery with domain metadata attached. Target import status is `observed` / non-binding regardless of source reliance_class; operator review is required before any target-domain commit or stronger reliance class.
5. **Tests**: manifests round-trip, declared vs accidental detection works, firewall export refusal warns, cross-domain import starts as observed, receipt chains are walkable across the bridge.

## Acceptance Criteria

- A domain can be declared with an explicit purpose in the workspace manifest or per-store equivalent.
- `contctl domain show` reports the purpose, bridge policy, and any warnings.
- Cross-domain imports reuse `CROSS_SCOPE_REFERENCE_GAP` content hashing, import events, and receipt chains — no parallel machinery.
- Imported memories always land in target status `observed` regardless of source status.
- `scope=global` writes in a declared domain are global *within that domain*; cross-domain access requires explicit import.
- Firewall-purpose domains refuse (or at minimum loudly warn) on export attempts.
- Accidental islands (no declaration, fallback-resolved) are surfaced by the visibility layer and cannot be silently treated as declared.
- The taxonomy is two-axis: declaration status × declared purpose. Purpose subtypes are not peers with "accidental."
- Given an undeclared fallback island with prior writes, adding a declaration establishes the domain boundary only from the declaration event forward; prior writes remain tagged as pre-declaration / orphan history and are not retroactively treated as clean global claims.

## Open Questions

1. **Where do per-store (non-workspace) declarations live?** Sibling `domain.json` is simple; `store_metadata` is more integrated. Pick at implementation time.
2. **Default purpose for unannotated workspaces.** `bridgeable` preserves current behavior but may be the wrong default for an explicit-declarations regime. A one-time migration prompt may be preferable to a silent default.
3. **Bridge policy granularity.** Allowlists of artifact kinds (decision, lesson, constraint) are a starting point. Per-scope or per-basis policies may be needed later.
4. **Discovery registry.** Should a per-user `~/.config/continuity/domains/` registry catalogue all known domains, or is walking the workspace registry sufficient for v1? Probably sufficient; revisit when multiple workspaces exist.
5. **Domain identity and hashing.** A domain's identity is currently its workspace `id`. Do bridges need a stronger hash of the domain's declaration (to detect drift or impersonation)? Deferred until a real risk case appears.
6. **Warning vs refusal escalation.** v1 warns loudly. Under what conditions should warnings become refusals? The `ISLANDS_OF_CONTINUITY` spec proposed `--allow-island`; this gap's equivalent is probably `--allow-undeclared-bridge`. Decide when the v1 warnings prove insufficient in practice.

## Short Version

Continuity domains can be isolated, but isolation must be declared. Declaration classifies purpose: `firewall`, `bridgeable`, `quarantined`, `local_dev_test`, `archival`. Cross-domain exchange is typed, non-transitive, receipted import — built on `CROSS_SCOPE_REFERENCE_GAP` primitives, not a parallel system. Imports always start as observed. `scope=global` is global only within its declared domain. Accidental islands remain bugs; the visibility layer from `ISLANDS_OF_CONTINUITY` catches them. Night Shift cross-continuity coordination is downstream of this gap and lives in the scheduler repo. One hash-pinning system, one import-receipt shape, one topology that no longer lies.
