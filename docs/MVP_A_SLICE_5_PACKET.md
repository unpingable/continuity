# MVP-A Slice 5 Packet — Continuity WLP Persistence Adapter

**Filed:** 2026-05-28 by chat-context Cartographer (cross-repo coordination scope).
**Status:** repo-local spec drop. **No implementation authorized yet.** Build target for whoever takes the slice.
**Origin:** [MVP-A Plan rev1](file:///home/jbeck/git/cartography/audit/2026-05-28-mvp-plan-rev1.md), Slice 5.

## What this packet is

A self-contained build scope for Continuity's role in the MVP-A demo loop:

```
substrate → NQ → NS → Wicket → WLP → Continuity persistence (this slice)
```

Continuity is the **WLP persistence adapter** — custody-preserving storage, not router, not reliance engine, not transport. The candidate doc at `docs/candidates/WLP_PERSISTENCE_ADAPTER.md` is the load-bearing terminology + invariants spec. This packet adds *implementation scope* under MVP-A forcing pressure.

## Forcing case (graduation trigger met)

Per the candidate doc's graduation triggers (lines ~113-117):

- ✓ WLP wire format for `AuthorizationReceipt` reached stability (v0.2 shipped per Cartographer re-audit).
- ✓ A consumer (NS + orchestrator on sushi-k, per `~/git/nightshift/docs/working/decisions/MVP_A_SLICES_2_3_4_PACKET.md`) names Continuity as the persistence surface.
- ✓ First forcing case = MVP-A disk_pressure finding flowing through full pipeline.

Therefore: graduate the candidate to gap-spec, add implementation scope, build the adapter.

Estimated work: ~1 day (Python persistence adapter on existing schema; gap-spec graduation; tests). Docs doctrine work is **already done** in the candidate; preserve verbatim.

## What already exists (Cartographer audit 2026-05-28)

- `docs/candidates/WLP_PERSISTENCE_ADAPTER.md` — full terminology, invariants list (12 items), persistence-vs-transport split, boundary list, keepers. Filed by Continuity-Claude 2026-05-28 (commit `5e190b0`).
- Hash-chained `receipts` table with append-only discipline (`src/continuity/store/schema.sql:77-93`).
- `memory_objects` table for current-state materialization.
- Content-hash / state-hash split.
- `verify_reliance()` for relied-on walks.
- `explain()` for lineage queries.
- 12 callable MCP tools + CLI (`contctl`) + Python library — three integration surfaces, all adopter-agnostic at substrate.
- Receipt format: `format_receipt()` in `src/continuity/receipts/memory_receipts.py` produces WLP-compatible envelope.

## What does NOT exist yet

- WLP `AuthorizationReceipt` write path (no specific adapter; the schema is generic but no documented WLP write path).
- Gap-spec graduation of the candidate (still in `docs/candidates/`).
- Optional new `ReceiptType` enum value for WLP types (or documented reuse of existing `MEMORY_IMPORT`).

## Build target

### Slice 5a — Gap-spec graduation

Move the candidate to `docs/gaps/WLP_PERSISTENCE_ADAPTER_GAP.md`. **Preserve verbatim:**

- The keepers ("WLP preserves the artifact contract. Continuity may preserve the artifact. Consumers decide reliance." + "A receipt store is not a reliance engine.")
- The scope sentence (custody-preserving persistence; store / retrieve / index / preserve)
- The boundary list (10 things the adapter is NOT)
- The 12 invariants
- The persistence-vs-transport split (table form)
- The "open gap surfaced" section
- The "graduation triggers" section (mark as MET; record date and forcing case)
- The "not in scope, even at candidate stage" section

Add an **Implementation Scope** section with the Slice 5b build target below.

### Slice 5b — Persistence adapter implementation

Python module — likely path `src/continuity/wlp_persistence.py` or under `src/continuity/adapters/wlp.py`:

- Input: WLP HandlingReceipt JSON (canonical bytes) + WLP-provided `artifact_hash`.
- Storage strategy (adapter author's call; either is fine):
  - **Option A:** Extend `ReceiptType` enum with `WLP_AUTHORIZATION` (and later, when a separate gap files transport, `WLP_REVOCATION`). Store in existing `receipts` table.
  - **Option B:** Reuse existing `MEMORY_IMPORT` ReceiptType with a kind metadata field marking it as `wlp_authorization`. No enum change.
- Stored fields:
  - `content` = canonical JSON bytes of the HandlingReceipt (byte-identical to write input)
  - `hash` = WLP-provided `artifact_hash` — **NOT recomputed by Continuity** (recomputation implies re-validation, which violates the persistence-not-validation invariant)
  - `prev_hash` = per existing chain discipline
  - `receipt_type` = `WLP_AUTHORIZATION` or `MEMORY_IMPORT` (per chosen option)
  - `created_at` = local timestamp
- Readback path: use existing `contctl get <id>` CLI or library `get_memory()`. No new readback surface.
- Hash-match verification primitive (for the MVP demo's acceptance):
  - `sha256(canonical_readback_bytes) == stored_hash` returns true.

### Slice 5c — Tests

- Write/read round-trip with byte-identical content (canonical JSON serialization).
- Hash-match assertion: `sha256(readback) == wlp_provided_hash`.
- `explain()` shows lineage including WLP `custody.causal_parents` (existing behavior preserved; no new code in `explain`).
- Negative: tampered stored content fails hash-match.

## Invariants (load-bearing; enforce in adapter code)

From the candidate doc; enumerated here for implementation reference. Each is a refusal-shape, not just a comment:

1. **stored ≠ valid** — adapter signature does not include "is this valid?" parameter. Validation is WLP's, not Continuity's.
2. **retrieved ≠ trusted** — `get` returns bytes + custody metadata; does not return "trust this" verdict.
3. **indexed ≠ endorsed** — index queries return matches; don't return policy verdicts.
4. **latest ≠ canonical** — no `get_canonical_for(subject)` API. Canonicity is upstream.
5. **missing ≠ false** — `get` on absent receipt returns "not in custody," not "doesn't exist as testimony."
6. **imported ≠ accepted** — import path records custody, doesn't promote trust.
7. **hash-chained ≠ ratified** — chain proves order + tamper-resistance only.
8. **WLP-valid envelope ≠ authorized action** — Continuity doesn't run WLP's `handle()` on the stored artifact.
9. **revocation encoded ≠ revocation propagated** — adapter does not call any consumer when storing a future RevocationReceipt (out of MVP-A scope; named here as a closed door).
10. **custody preserved ≠ channel secured** — adapter doesn't speak to transport security.
11. **persistence ≠ transport** — no `subscribe`, `notify`, `deliver`, `announce`, `publish` surfaces in the adapter.
12. **receipt store ≠ reliance engine** — `verify_reliance()` is consumer-driven; adapter doesn't make reliance decisions.

Recommended code-side enforcement: comments at each call site naming the relevant invariant; if a function signature would naturally invite violating one, refactor or add a refusal-shaped check.

## Acceptance

Slice 5 closes when:

1. `docs/gaps/WLP_PERSISTENCE_ADAPTER_GAP.md` exists with the candidate's content + Implementation Scope.
2. Adapter accepts a sample WLP HandlingReceipt JSON (e.g., produced by NS Slice 4 packet) and stores it.
3. `contctl get <continuity_receipt_id>` returns content byte-identical to write input.
4. `sha256(readback_canonical) == wlp_provided_hash` returns true.
5. `explain()` walks the lineage including `custody.causal_parents` from WLP layer.
6. Tests pass: write/read round-trip, hash-match, negative tamper-detection.

## Must NOT

- Route the artifact (no "send to X" logic).
- Decide reliance (no "should consumer Y trust this" logic).
- Propagate revocations (no "revocation came in, alert N consumers" logic).
- Re-validate WLP semantics (Continuity does not run `wlp::handle()` or check policy schemes).
- Provide transport surfaces (no subscribe, notify, deliver, replay, publish).
- Touch `~/git/wlp/` or `~/git/nightshift/` code.
- Add transport-side gap-specs adjacent to this work — the candidate doc already names the persistence/transport split; transport remains a separate future gap.
- Recompute the WLP hash on store (preserve provided hash; recomputation implies re-validation).
- Touch Linode-side or lil-nas-x-side concerns (Path B, Path A.5 — separate, later).

## Stop conditions

- Implementation requires WLP semantic interpretation (e.g., "if revoked, X") → stop; that's a different gap.
- Implementation requires consumer notification → stop; that's transport.
- Implementation requires schema migration beyond optional `ReceiptType` enum extension → stop and report.
- Graduating the candidate surfaces a need to revise the invariants → stop and report (invariants are load-bearing; revising deserves operator review).
- Adapter signature would naturally invite violating one of the 12 invariants → stop, refactor or add a refusal-shaped check.

## Composes with

- `docs/candidates/WLP_PERSISTENCE_ADAPTER.md` — load-bearing source for terminology + invariants. **Graduate, don't duplicate.**
- [MVP-A Plan rev1](file:///home/jbeck/git/cartography/audit/2026-05-28-mvp-plan-rev1.md) — full Slice 5 context, path ladder, subject-boundary
- [WLP-as-wire-layer cross-ref](file:///home/jbeck/git/cartography/coordination/wlp-notes-as-wire-layer-for-standing-boundary.md) — the layer picture (adopter slot below WLP)
- [Coordination registration](file:///home/jbeck/git/cartography/coordination/MVP-PATH-A-PLAN.md)
- This repo's existing primitives: `receipts` table, `memory_objects`, hash chain, content/state hash split, `verify_reliance()`, `explain()` — do not duplicate; reuse.

## WLP integration anchors (read-only)

- WLP HandlingReceipt produced by `wlp::handle()`; see `~/git/wlp/src/validate.rs:46-82`.
- WLP Artifact model (model.rs): `Kind::AuthorizationReceipt`.
- WLP canonical JSON via `serde_jcs` + SHA-256; see `~/git/wlp/src/canonical.rs`.
- WLP custody block format including `causal_parents` array.

## Provenance

Filed by Cartographer per operator instruction 2026-05-28 (post §H confirmation, packet placement phase). Cartographer's authority for cross-repo writes is bounded to coordination/docs scope per operator directional 2026-05-28; this packet is a docs-only spec drop, not implementation.
