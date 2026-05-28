# Candidate: WLP Persistence Adapter — continuity as a custody-preserving persistence substrate for WLP artifacts

**Status:** candidate (not gap-spec, not implementation, not a build plan)
**Originated:** 2026-05-28
**Last updated:** 2026-05-28 — reframed from "WLP Receipt Custody / custody adapter / WLP router" wording. WLP's artifact wire grammar carries a load-bearing `custody` block, which made "custody adapter" a namespace collision; "router" over-named continuity's plausible role. Continuity's role is **persistence / custody preservation**, not routing or transport. The seam is a **WLP persistence adapter** — equivalently a **custody-preserving persistence adapter**.
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

This candidate becomes a gap-spec when:

- WLP wire format for `AuthorizationReceipt` and `RevocationReceipt` reaches a stability point where a continuity-side persistence mapping is meaningful.
- A consumer (Wicket / Nightshift / Standing-the-tool / NQ / AG) names continuity as the persistence surface it wants WLP artifacts to live in.
- The first forcing case demonstrates a concrete custody flow continuity would have to support — write path, index path, retrieve path, or import path.
- A federated or cross-host custody requirement makes the remote-standing-boundary composition non-deferrable.

A *separate* gap is filed (not this one graduating) when a consumer demands transport / eventing / subscription / revocation propagation behavior on top of continuity's WLP persistence. That gap composes against the persistence-vs-transport split named here.

Per the candidates discipline: graduate when implementation pressure proves the framing underspecified, not when downstream events merely happen.

## Not in scope, even at candidate stage

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
