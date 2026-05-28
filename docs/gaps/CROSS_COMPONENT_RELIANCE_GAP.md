# Gap: Cross-Component Reliance — what continuity is *for* in the cross-host world

**Status:** proposed
**Depends on:** `CROSS_SCOPE_REFERENCE_GAP` (substrate — content/state hash split, import-as-receipt, pinned premises, local-only cross-scope explain). `CONTINUITY_TIME_DISCIPLINE` (rely path is replayable). `ISLANDS_OF_CONTINUITY` (writes refuse silent islands).
**Related:** sibling-repo gaps that name where consumers will hook in — NQ `REMOTE_SURFACE_AUTH_AND_STANDING_GAP`, NQ `QUERY_TARGET_PRIMITIVE_GAP`, Nightshift `GAP-parallel-ops.md`. Standing has no current continuity references in code; the integration shape is documented here on the continuity side.
**Blocks:** any cross-host workflow whose receipt is supposed to be auditable later — Wicket preflight against cited policy, Nightshift closure against cited gate doctrine, Standing grant import as a relied-on artifact in consumer receipts, NQ remote testimony acceptance against cited peer/policy memory.
**Last updated:** 2026-05-28

## The Problem

NQ, Nightshift, Wicket, and Standing are about to stop living on one host. Some of them will reach across host boundaries. When they do, their actions will rely on committed state that originated elsewhere: peer identity, standing grants, query-target definitions, advisory closeouts, deployment exceptions, revocation history. Today, continuity has no story for this:

- Shared doctrine has no cross-DB identity. "Project A relied on standard X" is a claim continuity cannot prove.
- Receipts in consumer tools cite ad-hoc references — file paths, free-text labels, hash digests with no provenance. Future `explain` cannot walk them.
- There is no shared vocabulary for *what kind of reliance was performed* — was the citation a local memory, an imported copy, a live network read, or unchecked?

`CROSS_SCOPE_REFERENCE_GAP` builds the substrate: pinned-import federation. Two stores can now agree on the same memory at the same version via content_hash; the import lands as a receipted historical act. But the substrate is silent on what consumers should *do* with it — which scopes deserve cross-host reliance, which receipts should carry citations, what counts as legitimate use vs. abuse.

This gap names the doctrine layer. It is not a separate substrate. It is the rule for how the existing substrate is consumed.

## Design Stance

Three operator keepers anchor the design. They are preserved verbatim throughout the spec body and in any consumer documentation that cites this gap:

> **Continuity records what may be relied on; it does not decide who may speak.**

> **Continuity can distribute reliance records. It should not distribute the rely path.**

> **Cross-host reliance cannot be stronger than local reliance replay.**

Together they rule out three failure modes the alternative shapes would invite. The first keeps continuity out of authorization. Authority lives in Standing; continuity records the *artifact* a Standing decision produced and lets future audit assess whether that artifact is still safe to cite. The second rules out continuity-as-network-service. Each host runs its own local store; shared doctrine arrives via content-hash-pinned imports; consumers cite local imported memory IDs in their receipts; the rely computation stays local and replayable. The third keeps the work honest: if the local rely path is mushy (ambient clocks in the kernel, silent islands, unaudited refusals), the cross-host story is a fiction. Phase 0 of the implementation plan is prerequisite hardening for exactly this reason.

A complementary keeper carried over from the substrate gap:

> **Content drift and status drift are different failures.**

And a separation-of-concerns keeper for the explain side:

> **Explain may describe imported reliance locally. Refresh may test source reachability. Do not merge them.**

## Non-goals

Continuity is **not**:

- An authority gate. Standing decides standing. A continuity memory is an *artifact* of a decision, not the decision.
- A service discovery mechanism. Hosts find each other through whatever the constellation already uses; continuity does not coordinate liveness.
- A live coordination substrate. If a consumer needs to know "what other agents are operating in this scope *right now*" (Nightshift's parallel-ops concern), that is not a continuity question — file the live-coordination problem as a separate substrate gap.
- A distributed consensus system. No quorum, no leader election, no automatic invalidation cascades.
- A remote control plane. There is no `continuity-server` daemon listening on the network. The MCP surface is local stdio; sharing happens via pinned-import receipts.
- A truth maintenance system. Revocation is per-store; downstream consumers pull-at-explain-time and surface drift honestly rather than chase fan-out.

## Architectural Invariants

### Reliance shape

1. **Consumer receipts carry continuity memory IDs as a first-class field.** When a consumer tool (Wicket, Nightshift, Standing, NQ) cooks its receipt against committed continuity state, the receipt names the memories cited, by local memory_id and content_hash. The future `explain` walk depends on this; nothing else replaces it.

2. **Rely-checks evaluate locally against pinned imports.** A consumer that imports a doctrine memory and pins its content_hash at reliance time later verifies *against the local imported copy*. No network call to the source store is part of the rely path. (Refresh is a separate operation — see `CROSS_SCOPE_REFERENCE_GAP` invariant 8 and the keeper above.)

3. **Reliance is annotated, not silent.** A receipt that cites continuity memory carries enough structure to distinguish how the citation was verified — local-native (memory authored in this store), local-import (imported from another store and pinned), unchecked (the consumer cited without computing rely_ok before acting). The taxonomy is intentionally short; expanding it requires a forcing case.

### Doctrine custody

4. **Standing decides standing; continuity records the artifact.** Importing a Standing grant receipt as a continuity memory does not make the grant valid, current, or binding. It records the relied-on artifact and lets rely/explain assess whether the artifact is still safe to cite. A consumer that needs the grant's *authorization* asks Standing; a consumer that needs to know whether the grant *was cited and whether the citation has drifted* asks continuity.

5. **Cross-host doctrine lives at workspace or global scope, not project.** A project-local memory imported into another project is incoherent — the importing project gets a copy of something the source project never offered cross-host. Cross-host citations must target memories whose source scope is `workspace`, `workspace:*`, or `global`. The substrate enforces this via the islands check on import.

6. **Pinning is the default for cross-host citation.** Unpinned premises against imported memories are allowed by the substrate but are a smell at the doctrine layer. Consumer tools should pin by default; the `verification_mode: "unchecked"` flag on a receipt's `relied_on` entry is the in-band signal that the consumer skipped pinning deliberately.

### Audit

7. **A receipt that cites memory MUST be replayable.** Given a receipt with `relied_on: [...]`, an auditor must be able to walk each cited memory, see its current local state (with the time-discipline `evaluation_time`), compare against the pin recorded in the receipt, and label any drift by name (`content_drift`, `state_revoked_after`, `state_expired_after`, `missing_local_import`, `unchecked`). The verification surface ships with this gap.

8. **Verification is local and offline-capable.** `contctl reliance verify` reads a receipt JSON and walks each entry against the local store. It does not contact source stores. (When live source-reachability is needed, that is `contctl refresh` — separate operation, separate failure-mode taxonomy.)

### Distribution

9. **Each host runs its own continuity store.** No host depends on another being reachable for the rely path. Shared doctrine arrives via the `import_memory` substrate path; consumers cite locally.

10. **Receipts cross-link by memory_id + content_hash, not by URL or path.** A receipt that cites `mem_xyz @ sha256:abc...` is interpretable by any store that has imported that memory at that version. File paths, http URLs, and other transport-coupled references are anti-patterns.

## Data Shape

No schema changes in continuity. The wire convention sits on top of the existing substrate. Consumer-tool receipt formats are each repo's own concern; this gap names the shape they should converge on.

**Receipt-side `relied_on` entry (consumer-authored, continuity-verified):**

```json
{
  "memory_id": "mem_xyz...",
  "content_hash": "sha256:abc...",
  "evaluation_time": "2026-05-28T12:34:56+00:00",
  "scope": "global",
  "reliance_class": "advisory",
  "verification_mode": "local_import",
  "source_store_id": "store_..."
}
```

Required fields: `memory_id`, `content_hash`, `evaluation_time`. Recommended optional fields: `scope`, `reliance_class`, `verification_mode` ∈ `{local_native, local_import, unchecked}`, `source_store_id`.

**Verification response shape:**

```json
{
  "verified": false,
  "entries": [
    {"memory_id": "...", "status": "match"},
    {"memory_id": "...", "status": "content_drift", "current_hash": "..."},
    {"memory_id": "...", "status": "revoked_after"},
    {"memory_id": "...", "status": "missing_local_import"}
  ]
}
```

Per-entry status: `match`, `content_drift`, `revoked_after`, `expired_after`, `missing_local_import`, `mode_mismatch` (the receipt claimed `local_import` but no import receipt is present locally).

## V1 Slice

Keep narrow.

1. **`contctl reliance verify <receipt.json>`** — reads receipt-shaped JSON from a file or stdin, extracts `relied_on`, walks each entry locally, prints per-entry status and an aggregate `verified: bool`. Exit code 0 on `verified: true`, 2 on any non-match.
2. **`memory_verify_reliance` MCP tool** — same shape over JSON-RPC. Accepts the receipt's `relied_on` array (or the whole receipt envelope; extracts the field). Returns the response shape above.
3. **Doctrine memory (proving ground)** — commit the cross-constellation lesson the operator drafted as a workspace-scope memory with premise links to this gap spec and to `CROSS_SCOPE_REFERENCE_GAP`. Dogfoods the citation pattern.
4. **`docs/integrations.md` updates** — name the per-consumer integration shape (NQ remote import, Nightshift closure, Wicket preflight, Standing import). Code in those consumers is each repo's work, not this gap's.
5. **StandingRef worked example** — runnable fixture in `docs/integrations.md` showing: standing grant receipt → import as `kind=constraint` continuity memory → consumer cites in `relied_on` → `contctl reliance verify` walks back through standing → continuity → consumer. Includes the anchoring caveat verbatim (invariant 4).

## Explicit Deferrals

Named so retrofit cost is bounded.

- **`contctl refresh` / `memory_refresh`** — active source-reachability probe. Separate from explain per the keeper. Not part of this gap; file when a consumer actually needs to drive a refresh against a remote store.
- **Live coordination state** (Nightshift parallel-ops concurrent-activity). Not a continuity question. If it surfaces as a constellation need, file as its own substrate gap.
- **Receipt-format changes inside consumer tools** — each repo adopts the `relied_on` convention on its own cadence. This gap ships the verification side; consumer code lands on each repo's clock.
- **Verification of standing-grant validity through continuity.** Continuity verifies *the citation* (was the artifact cited, has the artifact drifted). Standing's own validity check is a separate call. The two stay separate.
- **Cross-store search / federated discovery.** Substrate gap `CROSS_SCOPE_REFERENCE_GAP` already defers these.
- **Push-based propagation of upstream revocations.** Pull-at-explain-time with honest drift declaration is sufficient for V1 (substrate invariant 12).
- **Receipt-chain bridging across consumer tools and continuity.** Wicket / Standing receipts chain within their own systems. Continuity's chain stays local. Cross-system audit walks the citation graph by content_hash, not by chaining the receipt hashes themselves.

## Open Questions

1. **Default `verification_mode` when the field is absent?** Strict reading: `unchecked`. Lenient: infer from the memory's local basis (`local_import` if basis=import, `local_native` otherwise). V1 defaults to `unchecked` and emits a soft warning — surfaces the smell without breaking older receipts.
2. **Should `contctl reliance verify` accept inline JSON via `--receipt-json`?** Probably yes for ergonomics; V1 implements file path and stdin, follow-up adds the inline form if it earns its keep.
3. **Aggregate exit-code semantics.** V1: 0 if all entries `match`, 2 if any non-match. Open: should `unpinned` or `unchecked` entries count as failures, warnings, or info? V1 treats them as info (do not flip the aggregate).
4. **MCP-side actor for verification.** The MCP tool runs as the configured principal but the verification is read-only; should the actor be recorded anywhere? V1 says no — verification is read-only with no audit artifact. If a verification needs to leave an audit trail, the consumer's own receipt is the right home.
5. **Operator UX for "I need to import this and cite it" in one shot.** V1 keeps import and citation as two separate operations; a future ergonomic wrapper may chain them. Out of scope until friction is demonstrated.

## Acceptance Criteria

This gap is closed when:

- `docs/gaps/CROSS_COMPONENT_RELIANCE_GAP.md` is written, indexed in `docs/gaps/README.md`, and preserves all three operator keepers verbatim.
- A workspace-scope doctrine memory is committed with a pinned premise link to this gap (the gap itself imported as a continuity memory per the proving-ground pattern in `CROSS_SCOPE_REFERENCE_GAP`).
- `contctl reliance verify` and `memory_verify_reliance` ship with per-entry status taxonomy and tests covering each terminal status (`match`, `content_drift`, `revoked_after`, `expired_after`, `missing_local_import`, `mode_mismatch`).
- A worked StandingRef example in `docs/integrations.md` is runnable and includes the anchoring caveat (invariant 4) verbatim.
- Per-consumer integration sketches are present in `docs/integrations.md` for NQ, Nightshift, Wicket, Standing.
- No sibling-repo code changes are required to land this gap — the substrate ships; consumers adopt on their own cadence.

## Short Version

Continuity does not become a network oracle. It does not decide who may speak. It records what was relied on, surfaces drift honestly, and stays out of the rely path. Cross-host reliance is shaped by three keepers — *records what may be relied on, does not decide who may speak; distributes reliance records, does not distribute the rely path; cross-host reliance cannot be stronger than local reliance replay*. V1 ships a `relied_on` receipt convention (memory_id + content_hash + evaluation_time + optional `verification_mode`/scope/reliance_class/source_store_id), a local-only `contctl reliance verify` walker with the same logic exposed via `memory_verify_reliance` MCP tool, a worked StandingRef example, and a workspace-scope doctrine memory committed as the first dogfood. The substrate from `CROSS_SCOPE_REFERENCE_GAP` does the heavy lifting; this gap names the consumer doctrine on top of it.
