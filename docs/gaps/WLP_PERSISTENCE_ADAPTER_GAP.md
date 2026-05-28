# Gap: WLP Persistence Adapter — continuity as a custody-preserving persistence substrate for WLP artifacts

**Status:** graduated from candidate 2026-05-28 (all four graduation triggers MET — see "Graduation triggers" section); V1 implementation in progress per `docs/MVP_A_SLICE_5_PACKET.md`.
**Originated:** 2026-05-28 (candidate)
**Last updated:** 2026-05-28 — graduated from `docs/candidates/` to `docs/gaps/` under MVP-A forcing pressure (NS live demo loop on sushi-k). Doctrine layer (keepers, scope, boundary, persistence-vs-transport split, twelve invariants, not-in-scope) is preserved verbatim from the candidate; implementation scope is appended as a new section. Original reframe note retained: WLP's artifact wire grammar carries a load-bearing `custody` block, which made "custody adapter" a namespace collision; "router" over-named continuity's plausible role. Continuity's role is **persistence / custody preservation**, not routing or transport. The seam is a **WLP persistence adapter** — equivalently a **custody-preserving persistence adapter**.
**Depends on:** WLP wire format reaching stability for `AuthorizationReceipt` and `RevocationReceipt`; an explicit adapter/gap before any integration is implemented
**Related:** `~/git/cartography/coordination/wlp-notes-as-wire-layer-for-standing-boundary.md` (the layer picture that names "adopter — storage, discovery, UX, audit aggregation"); `~/git/cartography/coordination/nq-REMOTE_STANDING_BOUNDARY.md` (the doctrine whose receipts WLP serializes); `~/git/wlp/WLP_STANDING_BOUNDARY_CROSSREF.md` (authoritative WLP-side statement); gaps `CROSS_SCOPE_REFERENCE_GAP.md` (substrate for cross-store identity) and `CROSS_COMPONENT_RELIANCE_GAP.md` (consumer doctrine on top)

## The Idea

WLP defines the **artifact contract** — `AuthorizationReceipt`, `RevocationReceipt`, the `custody` block, the causal-parents graph, the validation rules an artifact must satisfy. WLP's layer picture names an `adopter` slot below WLP — *storage, discovery, UX, audit aggregation* — without naming an adopter.

Continuity already runs the only hash-chained receipts substrate in the constellation. Its existing primitives are shape-compatible with a custody-preserving persistence role:

- Hash-chained receipts table with append-only discipline.
- Memory-objects layer materializing the current state of any identifiable artifact.
- Import-as-receipt for cross-store identity (`CROSS_SCOPE_REFERENCE_GAP`).
- Content-hash and state-hash split for distinguishing content drift from status drift.
- Reliance vocabulary (`relied_on` receipt convention, `verification_mode`) for what kind of citation was performed (`CROSS_COMPONENT_RELIANCE_GAP`).

Continuity may therefore plausibly serve as a **WLP-compatible persistence substrate**, accessed through an explicit **WLP persistence adapter**: an adapter that writes WLP artifacts into continuity and reads WLP artifacts out of continuity, preserving the artifact's hash, custody chain, provenance, and context pointers.

This note marks the slot. It does not authorize the integration.

> **Continuity may become a WLP-compatible persistence substrate through an explicit WLP persistence adapter. This does not make continuity a WLP router, transport, registry, discovery service, event stream, revocation propagator, or authority source.**

> **Any future continuity transport/eventing role for WLP artifacts is a separate gap and must compose with remote-standing-boundary, component-reliance, subscription standing, absence semantics, replay semantics, and revocation propagation.**

## Scope — what the adapter would do

If continuity ever serves as a WLP persistence substrate, the scope is bounded:

> A **WLP persistence adapter** may write WLP artifacts into continuity and read WLP artifacts out of continuity. Continuity storage preserves the artifact's hash, custody chain, provenance, and context pointers.

That is custody-preserving persistence. It is **store, retrieve, index, preserve**. It is not anything else.

## Boundary — what the adapter is not

A WLP persistence adapter is **persistence and custody preservation**. It is not:

- **Routing** — continuity does not decide where an artifact should be sent or who should hear about it.
- **Validation** — continuity does not adjudicate whether an artifact was correctly issued. A WLP-valid envelope does not become an authorized action by being stored.
- **Authorization** — continuity does not grant, withhold, or re-issue standing on the basis of an artifact it holds.
- **Reconciliation** — continuity does not resolve disputes between conflicting artifacts.
- **Transport** — continuity does not deliver, announce, propagate, or notify on artifact arrival.
- **Subscription / eventing** — continuity exposes no subscribe-and-be-notified surface for WLP artifacts. A consumer that wants events must build its own subscription layer.
- **Revocation propagation** — encoding a `RevocationReceipt` in storage does not propagate revocation to the consumers that previously relied on the now-revoked artifact.
- **Ranking / canonicalization** — continuity does not decide which of several stored artifacts is the live one. WLP and the issuing authority do.
- **Discovery service** — continuity may be queried; queryability is not announcement. A consumer that does not know to look will not be told to.
- **Reliance arbitration** — *a receipt store is not a reliance engine.* Consumers decide reliance; continuity records what was stored.

The boundary is structural, not procedural. The persistence surface should not contain a code path that could become any of the above.

## Required distinction — persistence is not transport

| Persistence (in scope) | Transport (out of scope) |
|---|---|
| **store** — accept artifact bytes, preserve hash and envelope | **deliver** — push artifact to a named consumer |
| **retrieve** — return stored artifact by identifier | **announce** — emit "new artifact at id X" |
| **index** — make stored artifacts queryable | **subscribe** — let consumers register interest |
| **preserve hash / custody / provenance / context pointers** | **replay** — re-deliver historical artifacts on demand |
| | **propagate revocations** — push state changes downstream |
| | **notify consumers** — cause consumer state updates |

Continuity-as-WLP-persistence is plausible. Continuity-as-WLP-transport is **not implied** by adopting the persistence role and would require a **separate gap** that explicitly composes with remote-standing-boundary, component-reliance, subscription standing, absence semantics, replay semantics, and revocation propagation.

## Required invariants

If integration is ever specified, these invariants gate the design:

- **stored ≠ valid** — a stored artifact is bytes in custody; validity is what WLP and the issuing authority decided.
- **retrieved ≠ trusted** — handing back an artifact is a custody act, not a trust signal.
- **indexed ≠ endorsed** — making an artifact discoverable does not vouch for its claims.
- **latest ≠ canonical** — the most recently stored artifact is not automatically the live one; the issuing authority decides canonicity.
- **missing ≠ false** — absence of an artifact in custody is not testimony against the underlying authorization; it is testimony about custody scope.
- **imported ≠ accepted** — pulling an artifact across a store boundary creates a custody record; it does not promote acceptance.
- **hash-chained ≠ ratified** — continuity's hash chain proves order and tamper-resistance, not external acceptance.
- **WLP-valid envelope ≠ authorized action** — passing the WLP wire grammar's validation is not the same as having standing to act on the artifact.
- **revocation encoded ≠ revocation propagated** — storing a `RevocationReceipt` does not deliver the revocation to consumers that relied on the prior artifact.
- **custody preserved ≠ channel secured** — preserving custody/provenance does not address transport-layer security; those are different concerns at different layers.
- **persistence ≠ transport** — the storage surface does not imply or perform any delivery, announcement, or notification.
- **receipt store ≠ reliance engine** — continuity records what was relied on; consumers decide what to rely on.

These compose with the existing continuity invariants (no silent promotion; retrieval is not authority; revoked links stay as evidence) and the cross-component keepers (records what may be relied on, never decides who may speak).

> **WLP preserves the artifact contract. Continuity may preserve the artifact. Consumers decide reliance.**

Sharper:

> **A receipt store is not a reliance engine.**

## Why this is a candidate, not a gap-spec

1. **WLP wire shape is not yet frozen.** `AuthorizationReceipt` and `RevocationReceipt` have v0.2-ish drafts; the wire schema continuity would persist does not yet have the stability a gap-spec depends on.
2. **No consumer is yet asking continuity to persist WLP artifacts.** Persistence slots without consumers invent vocabulary in the absence of forcing cases.
3. **The component-reliance surface is itself an open gap.** If continuity persists WLP artifacts, downstream tools relying on continuity for them creates a new component-reliance surface, which then composes with `CROSS_COMPONENT_RELIANCE_GAP` and the remote-standing-boundary doctrine. That composition has not been specified.
4. **Storage layout is undecided.** Whether WLP artifacts share the existing `receipts` table, land in a sibling table, in `memory_objects` with a specialized kind, or in a separate WLP-artifacts substrate is exactly the kind of decision that should land in a real gap-spec when the forcing case arrives.

The candidate stage holds the keepers, the scope sentence, the boundary list, the persistence/transport split, the invariants list, and the open gap. Specification waits for pressure.

## Open gap surfaced by this candidate

If continuity becomes a WLP persistence substrate, it exposes a **component-reliance surface** to whichever tools query that store. Three further conditions are named, not answered:

- If persistence or import ever crosses host or trust boundaries (federation, remote import, network reads), the remote-standing-boundary doctrine composes here. The composition vocabulary then includes `exposure_profile`, standing resolver, action class, receipt-recorded standing basis, and reliance class — same vocabulary that `CROSS_SCOPE_REFERENCE_GAP` and `CROSS_COMPONENT_RELIANCE_GAP` already carry breadcrumbs for.
- If continuity's WLP persistence surface is queried by tools that treat its returns as authority (rather than as custody handoff), the boundary above has already been violated. Recognition of this failure shape is what the invariants list defends against.
- **Any transport / eventing role** (delivery, subscription, replay, revocation propagation, consumer notification) is a *separate gap*. The required composition surface is named in the persistence-vs-transport section; the gap itself is not filed here, and adoption of the persistence role does not imply or authorize it.

The candidate's job is to make all three visible so a future gap-spec inherits them rather than rediscovering them.

## Graduation triggers

All four triggers below were MET on 2026-05-28. The candidate is graduated to a gap-spec on that date.

- ✅ **WLP wire format stability** — `AuthorizationReceipt` reached v0.2 per Cartographer's 2026-05-28 re-audit; `RevocationReceipt` remains future work and stays out of this V1.
- ✅ **A consumer names continuity as the persistence surface** — NS + orchestrator on `sushi-k` (per `~/git/nightshift/docs/working/decisions/MVP_A_SLICES_2_3_4_PACKET.md`).
- ✅ **First forcing case** — MVP-A `disk_pressure` finding flowing through the full pipeline; HandlingReceipt sample at `/tmp/mvp-a-demo/ns-wlp-handling-run_eccbc954b4fc4119b2c4cf332bea2956.json` with `artifact_hash = sha256:86126707b3974f5c160deabca6df9e968da17baab4c48cadaffb221b1ff47b19`.
- ✅ **Cross-host composition pressure** — the demo loop runs from NS on `sushi-k` into continuity locally; federation/cross-host receipts are imminent per cartographer's Path B planning. The remote-standing-boundary composition is named in `CROSS_SCOPE_REFERENCE_GAP` and `CROSS_COMPONENT_RELIANCE_GAP` (trigger notes added 2026-05-28).

A *separate* gap is filed (not this one graduating) when a consumer demands transport / eventing / subscription / revocation propagation behavior on top of continuity's WLP persistence. That gap composes against the persistence-vs-transport split named here.

Per the gap-spec discipline: this V1 ships the smallest slice that proves the persistence shape (Slice 5 in `docs/MVP_A_SLICE_5_PACKET.md`); transport, federation, multi-host import, and the broader receipt-type taxonomy are explicitly deferred.

## Implementation scope (V1, per docs/MVP_A_SLICE_5_PACKET.md)

V1 covers persistence of WLP HandlingReceipts and AuthorizationReceipts. Revocation is named-and-deferred until WLP wire format for `RevocationReceipt` stabilizes and a consumer demands it.

### Storage strategy

V1 reuses the existing `ReceiptType.MEMORY_IMPORT` audit-receipt type — Option B per the packet. No `ReceiptType` enum extension, no schema migration.

A WLP artifact is persisted as a continuity `memory_object` with:

- `basis = IMPORT` (forced by the import path; matches "we received this from elsewhere")
- `kind = NOTE` (least-semantic existing kind; the actual WLP semantic is in the envelope content, not the continuity kind)
- `status = OBSERVED` (the WLP envelope is in custody; continuity does not promote it to COMMITTED on store — invariant 6: imported ≠ accepted)
- `reliance_class = NONE` (continuity does not decide reliance — invariant 12)
- `confidence = 0.5` (neutral; continuity does not vouch for the envelope's claim)
- `content` = the WLP envelope as a JSON object, byte-identical to the canonical input (after `json.loads`/`json.dumps(sort_keys=True, separators=(',',':'))` round-trip — verified inertness of the round-trip is part of acceptance)
- `source_refs` = at minimum a `SourceRef(kind='wlp_artifact_hash', ref=<sha256:...>, note=<wlp_kind>)`; optionally a `file` source_ref pointing at the on-disk artifact path
- `memory_id` = `mem_wlp_<sha256_hex>` (content-addressed from the WLP `artifact_hash`; same envelope → same memory_id → natural idempotency via `import_memory`'s existing (memory_id, content_hash) check)

A `memory.import` receipt records the import act. The receipt's content (already shaped by the existing import path) records continuity's own content_hash; the WLP `artifact_hash` is preserved verbatim in `source_ref` (top-level `ImportMemoryRequest.source_ref`) and in the `memory_object.source_refs` list. Continuity's chain hash for that receipt is computed by `_build_receipt` per existing discipline; the WLP-provided hash is metadata, never the chain hash.

### Adapter surface (library only — invariant 11: persistence ≠ transport)

Module path: `src/continuity/adapters/wlp.py`. No CLI subcommand and no MCP tool in V1 — the adapter is library-only. Callers wire it into their own ingest pipeline.

```python
from continuity.adapters.wlp import (
    WLPArtifactStored,
    WLPNonCanonicalInputError,
    store_wlp_artifact,
    readback_wlp_artifact,
    verify_wlp_artifact_hash,
)

result: WLPArtifactStored = store_wlp_artifact(
    store=sqlite_store,
    envelope_bytes=<canonical-JSON bytes of HandlingReceipt or AuthorizationReceipt>,
    wlp_artifact_hash="sha256:...",        # WLP-provided, preserved verbatim
    scope="wlp",                            # caller's choice of continuity scope
    source_store_id="ns:nightshiftd",       # WLP issuer, recorded in import receipt
    source_path="/tmp/.../ns-wlp-handling-*.json",  # optional on-disk provenance
)
# result.memory_id, result.receipt_id, result.wlp_artifact_hash, result.wlp_kind,
# result.causal_parents

# Readback through existing path:
readback_bytes: bytes = readback_wlp_artifact(store, result.memory_id)
assert readback_bytes == envelope_bytes  # byte-identical canonical bytes

# Hash-match verification (storage-integrity check; not WLP semantic validation):
assert verify_wlp_artifact_hash(readback_bytes, result.wlp_artifact_hash)
```

### Refusal-shaped checks

The adapter signature must refuse to violate the twelve invariants. V1 enforces explicitly:

- **`WLPNonCanonicalInputError`** is raised if the input bytes are not in canonical JSON form (no whitespace, sorted keys, compact). The adapter does not silently re-canonicalize input — the caller is expected to deliver canonical bytes. The check is `json.dumps(json.loads(bytes), sort_keys=True, separators=(",",":")).encode() == bytes`. (Storage hygiene; not WLP semantic validation.)
- **No "is this valid?" parameter** on `store_wlp_artifact`. Validation belongs to WLP and to the issuing authority; continuity does not own it (invariant 1).
- **No `get_canonical_for(subject)` API.** Canonicity is upstream (invariant 4).
- **No `subscribe`, `notify`, `deliver`, `announce`, `publish`** on the adapter or on any module it touches. Transport is a separate gap (invariant 11).
- **No call to `wlp::handle()` or any WLP policy check** at any point in the persistence path (invariant 8).
- **No recompute of `wlp_artifact_hash` on store.** The WLP-provided hash is recorded verbatim in `source_refs` and `source_ref`. Recomputation is permitted only at verify-time on readback, and that recomputation is integrity-verification, not validation (invariant 7).

### Hash-verification primitive (readback only)

`verify_wlp_artifact_hash(envelope_bytes, expected_artifact_hash)` recomputes the WLP-compatible canonicalization (zero `custody.{artifact_hash, receipt_hash, signature}`, then JCS-style `sort_keys=True, separators=(",",":")`, then SHA-256) and compares to the expected hash. The check is storage-integrity (did the bytes come back unchanged?), not semantic validation (is the artifact's claim true?). Per invariant 1: a passing verify result does NOT make the artifact valid — only preserved.

### Acceptance criteria (closes Slice 5 per packet)

1. ✅ `docs/gaps/WLP_PERSISTENCE_ADAPTER_GAP.md` exists with the candidate's content + Implementation Scope (this section).
2. Adapter accepts the MVP-A sample HandlingReceipt JSON at `/tmp/mvp-a-demo/ns-wlp-handling-run_eccbc954b4fc4119b2c4cf332bea2956.json` and stores it without error.
3. Readback via continuity's existing memory-get path returns bytes that re-canonicalize to byte-identical canonical JSON (`readback_canonical == envelope_bytes`).
4. `verify_wlp_artifact_hash(readback, "sha256:86126707...")` returns `True`.
5. `explain(memory_id)` walks the lineage; the import receipt's content surfaces the WLP `artifact_hash`; the envelope's `custody.causal_parents` survives in the memory's content unchanged.
6. Tests cover: round-trip identity, hash-match positive, hash-match negative on tampered bytes, idempotency (same envelope twice → same memory_id, single receipt).

## Not in scope, even at gap stage

- **Naming continuity as the canonical WLP persistence store by assertion.** Persistence fit is one option among several; the candidate does not pre-empt the architectural decision.
- **Calling continuity a WLP router, transport, registry, discovery service, event stream, revocation propagator, or authority source.** The boundary list and the persistence/transport split exist to refuse these framings.
- **Schema design.** Whether WLP artifacts share the `receipts` table, get a sibling table, or live elsewhere is a gap-spec question.
- **Wire-level integration with WLP.** Even at candidate stage, no integration code is authorized.
- **Cross-host or federated artifact import.** Cited as a trigger, not designed here.
- **Adopter responsibilities WLP punts (workflow, UX, audit aggregation).** Adoption shape is downstream of persistence scope; designing it before the persistence scope is real is calendar theology with a schema migration.
- **Anything that turns "continuity persists it" into "continuity vouches for it."** That is the failure mode the invariants list and the keepers exist to refuse.
- **Anything that turns "continuity persists it" into "continuity delivers it."** That is the persistence-vs-transport collapse the dedicated section exists to refuse.

## One-line summary

WLP defines the artifact contract; continuity may serve as a **WLP-compatible persistence substrate** via an explicit **WLP persistence adapter** (equivalently a *custody-preserving persistence adapter*). The adapter writes WLP artifacts into continuity and reads them out, preserving hash, custody, provenance, and context pointers — nothing else. Continuity is not a router, transport, registry, discovery service, event stream, revocation propagator, or authority source; any transport/eventing role is a *separate gap*. Persistence ≠ transport; receipt store ≠ reliance engine. *WLP preserves the artifact contract. Continuity may preserve the artifact. Consumers decide reliance.*
