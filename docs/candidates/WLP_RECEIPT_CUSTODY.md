# Candidate: WLP Receipt Custody — continuity as storage substrate for WLP-serialized receipts

**Status:** candidate (not gap-spec, not implementation, not a build plan)
**Originated:** 2026-05-28
**Depends on:** WLP wire format reaching stability for `AuthorizationReceipt` and `RevocationReceipt`; an explicit adapter/gap before any integration is implemented
**Related:** `~/git/cartography/coordination/wlp-notes-as-wire-layer-for-standing-boundary.md` (the layer picture that names "adopter — storage, discovery, UX, audit aggregation"); `~/git/cartography/coordination/nq-REMOTE_STANDING_BOUNDARY.md` (the doctrine whose receipts WLP serializes); `~/git/wlp/WLP_STANDING_BOUNDARY_CROSSREF.md` (authoritative WLP-side statement); gaps `CROSS_SCOPE_REFERENCE_GAP.md` (substrate for cross-store identity) and `CROSS_COMPONENT_RELIANCE_GAP.md` (consumer doctrine on top)

## The Idea

WLP serializes constellation-wide standing decisions (Authorization, Revocation, custody chain) into receipt-shaped artifacts. The WLP layer picture names an `adopter` slot below WLP — *storage, discovery, UX, audit aggregation* — but does not name an adopter. Continuity already runs the only hash-chained receipts substrate in the constellation. Its existing receipt-keeping primitives are shape-compatible with what an adopter would need:

- Hash-chained receipts table with append-only discipline.
- Memory-objects layer materializing the current state of any identifiable artifact.
- Import-as-receipt for cross-store identity (`CROSS_SCOPE_REFERENCE_GAP`).
- Content-hash and state-hash split for distinguishing content drift from status drift.
- Reliance vocabulary (`relied_on` receipt convention, `verification_mode`) for what kind of citation was performed (`CROSS_COMPONENT_RELIANCE_GAP`).

Continuity may therefore be a natural storage / custody substrate for WLP-serialized `AuthorizationReceipt`, `RevocationReceipt`, and related receipt bundles. The slot exists; continuity occupies a shape that fits it.

This note marks the slot. It does not authorize the integration.

## Scope of what custody would mean

If continuity ever serves as a WLP receipt store, the scope is bounded:

> Continuity can **store, index, retrieve, import, export, and preserve** WLP-serialized AuthorizationReceipts, RevocationReceipts, and related receipt bundles.

That is custody. It is not anything else.

## Boundary — what custody is not

Continuity storage is **custody / discovery**. It is not:

- **Routing** — continuity does not decide where a receipt should be sent or who should hear about it.
- **Validation** — continuity does not adjudicate whether a receipt was correctly issued.
- **Authorization** — continuity does not grant, withhold, or re-issue standing on the basis of a receipt it holds.
- **Reconciliation** — continuity does not resolve disputes between conflicting receipts.
- **Truth arbitration** — continuity does not become the authority the receipt claims to record.

The boundary is structural, not procedural. The custody surface should not contain a code path that could become any of the five.

## Required invariants

If integration is ever specified, these invariants gate the design:

- **stored ≠ valid** — a receipt in custody is bytes on disk; validity is what WLP and the issuing standing-authority decided.
- **indexed ≠ endorsed** — making a receipt discoverable does not vouch for its claims.
- **retrievable ≠ authoritative** — handing back a receipt is a custody act, not a standing claim.
- **missing ≠ false** — absence of a receipt in custody is not testimony against the underlying authorization; it is testimony about custody scope.
- **latest ≠ canonical** — the most recently stored receipt is not automatically the live one; the issuing authority decides canonicity.
- **imported ≠ trusted** — pulling a receipt across a store boundary creates a custody record; it does not promote trust.
- **deduplicated ≠ reconciled** — collapsing identical receipt bytes is a storage optimization, not a resolution of substantive duplicates.
- **hash-chained ≠ ratified** — continuity's hash chain proves order and tamper-resistance, not external acceptance.
- **custody metadata must preserve** emitter, subject, receipt hash, source, import path, and reliance class — losing any of these turns custody into laundering.

These compose with the existing local invariants (no silent promotion; retrieval is not authority; revoked links stay as evidence) and the cross-component keepers (records what may be relied on, never decides who may speak).

> **Continuity may store the receipt. It may not become the authority the receipt claims.**

## Why this is a candidate, not a gap-spec

1. **WLP wire shape is not yet frozen.** `AuthorizationReceipt` and `RevocationReceipt` have v0.2-ish drafts; the wire schema for the receipts continuity would store does not yet have the stability a gap-spec depends on.
2. **No consumer is yet asking continuity to store WLP receipts.** Custody slots without consumers invent vocabulary in the absence of forcing cases.
3. **The component-reliance surface is itself an open gap.** If continuity hosts WLP receipts, downstream tools relying on continuity to find them creates a new component-reliance surface, which then composes with `CROSS_COMPONENT_RELIANCE_GAP` and the remote-standing-boundary doctrine. That composition has not been specified.
4. **Storage adapter shape is undecided.** Whether WLP receipts land in the existing `receipts` table, in a sibling table, in `memory_objects` with a specialized kind, or in a separate WLP-receipts substrate is exactly the kind of decision that should land in a real gap-spec when the forcing case arrives.

The candidate stage holds the keeper, the scope sentence, the boundary list, the invariants list, and the open gap. Specification waits for pressure.

## Open gap surfaced by this candidate

If continuity becomes a WLP receipt store, it exposes a **component-reliance surface** to whichever tools query that store. Two further trigger conditions:

- If receipt storage or import ever crosses host or trust boundaries (federation, remote import, network reads), the remote-standing-boundary doctrine composes here. The composition vocabulary then includes `exposure_profile`, standing resolver, action class, receipt-recorded standing basis, and reliance class — same vocabulary that `CROSS_SCOPE_REFERENCE_GAP` and `CROSS_COMPONENT_RELIANCE_GAP` already carry breadcrumbs for.
- If continuity's WLP-receipt custody surface is queried by tools that treat its returns as authority (rather than as custody handoff), the boundary above has already been violated. Recognition of this failure shape is what the invariants list defends against.

Both conditions are *named*, not *answered*. The candidate's job is to make them visible so a future gap-spec inherits them rather than rediscovering them.

## Graduation triggers

This candidate becomes a gap-spec when:

- WLP wire format for `AuthorizationReceipt` and `RevocationReceipt` reaches a stability point where a continuity-side schema mapping is meaningful.
- A consumer (Wicket / Nightshift / Standing-the-tool / NQ / AG) names continuity as the storage / discovery surface it wants to rely on for WLP receipts.
- The first forcing case demonstrates a concrete custody flow continuity would have to support — write path, index path, retrieve path, or import path.
- A federated or cross-host custody requirement makes the remote-standing-boundary composition non-deferrable.

Per the candidates discipline: graduate when implementation pressure proves the framing underspecified, not when downstream events merely happen.

## Not in scope, even at candidate stage

- **Naming continuity as the canonical WLP receipt store by assertion.** Custody fit is one option among several; the candidate does not pre-empt the architectural decision.
- **Schema design.** Whether WLP receipts share the `receipts` table, get a sibling table, or live elsewhere is a gap-spec question.
- **Wire-level integration with WLP.** Even at candidate stage, no integration code is authorized.
- **Cross-host or federated receipt import.** Cited as a trigger, not designed here.
- **Adopter responsibilities WLP punts (workflow, UX, audit aggregation).** Adoption shape is downstream of custody scope; designing it before the custody scope is real is calendar theology with a schema migration.
- **Anything that turns "continuity stores it" into "continuity vouches for it."** That is the failure mode the invariants list and the keeper exist to refuse.

## One-line summary

Continuity has the shape of an adopter for WLP-serialized receipts (hash-chained receipts, import-as-receipt, content/state-hash split, reliance vocabulary). The slot exists; whether continuity occupies it is a future gap-spec decision. Until then, the candidate holds the scope sentence (custody and discovery only), the boundary (not routing, validation, authorization, reconciliation, or truth arbitration), the invariants list (stored ≠ valid, …, hash-chained ≠ ratified), and the keeper: *continuity may store the receipt; it may not become the authority the receipt claims.*
