# Candidate: ProjectionReceipt — a read is a witnessed claim, not a resurrection of stored truth

**Status:** candidate / non-binding (not gap-spec, not implementation). No implementation authorized by this record; no schema admitted. A handle for review.
**Originated:** 2026-06-18.
**Authorized by:** agent_gov, as constellation-governor / cross-repo custody root. AG authorizes the *filing*; continuity owns the *doctrine*. AG did not admit any architecture here. See AG `docs/cross-tool/managed-repo-candidate-filing-note.md`.
**Provenance:** lifted from agent_gov's receipt-kernel arch (`libs/receipt_kernel/`, `docs/RECEIPT_KERNEL_CONTRACT.md`) as a per-office choke-point steal — *"steal the choke point, not the throne"* (the pattern NQ used in `nq/docs/working/decisions/PREFLIGHT_CORE_CANDIDATE.md`). This is the continuity-grammar version of one kernel mechanism, not a port of the kernel.
**Related:** AG `working/GOV_GAP_QUERIED_RECEIPT_SUBSTRATE_001.md` (substrate + inheritance → Continuity; the read-end-is-open observation this sharpens); `candidates/MAP_SKEW.md` (orthogonal — skew is *staleness direction* of a record; this is *semantic conversion* at the read boundary).

## The monster lives in the decoder, not the ledger

Continuity stores sealed records well. Hash-chaining, content addressing, and supersession-as-event are the *storage*-side disciplines, and they hold: a stored record cannot be silently mutated.

That is not where the failure is. The failure is at the **read**:

```text
record v3 is stored correctly (hash-valid, sealed, "verified")
decoder v4 reads it
projection emits something plausible
consumer treats that projection as inherited truth
```

The storage layer did not lie. **The read layer laundered.** A v3 record decoded through a v4 schema can silently reshape meaning while every integrity check stays green — *signed is not witnessed, one layer up; stored is not true.*

So the choke point continuity wants is not another ledger invariant. It is a typed object at the **read/projection boundary** that forces a read to confess what it actually is.

## The candidate object

```text
ProjectionReceipt {
  source_record_hash       # the sealed fact, content-addressed
  source_schema_version    # the schema the record was sealed under
  decoder_version          # what is doing the reading
  decoder_hash             # ...content-addressed, so a decoder change is visible
  projection_kind          # what kind of read this is
  projection_hash          # content hash of the emitted projection
  projected_fields         # what was actually surfaced
  read_clock               # a witnessed read time (typed clock basis, not a bare number)
  refusals_losses_unknowns # what could NOT be projected — present-as-claim, never silently dropped
}
```

With it, continuity stops saying *"I retrieved the fact"* and starts saying:

> I projected sealed record X through decoder Y under schema Z and got projection P, surfacing these fields, losing/refusing these others.

## Central invariant

> **A read is a new witnessed claim, not a resurrection of stored truth.**
> Every semantic read across a schema / version / projection boundary must be witnessed by a ProjectionReceipt. No silent schema/version conversion. Supersession is an event, never an overwrite.

## The one universal, in continuity's dialect

The cross-office rule (every constellation office inherits it) is: **UNKNOWN poisons PASS** — *no office may convert unknown, unavailable, incompatible, or unverified evidence into a clean affirmative result merely because the local path lacks a refusal branch.*

Continuity's chalice for that poison:

```text
DecodeUnknown        # the decoder could not read the record
SchemaIncompatible   # record schema and decoder schema do not commute; refuse, do not coerce
ProjectionUnknown    # a requested field could not be projected
```

A projection that hits any of these is not a clean read with a footnote. It is a typed non-result that the consumer must handle as such — it may remain *observable* but it is not *inherited truth*.

## Graduation triggers

Promote to a gap-spec when any of these lands:

- A real decode-skew incident: a record sealed under schema vN is read through a vN+1 decoder and a consumer inherits a silently-reshaped projection as truth.
- A second reader of continuity records appears (beyond the authoring session), making the read boundary a genuine cross-consumer surface rather than a single-process convenience.
- AG's `working/GOV_GAP_QUERIED_RECEIPT_SUBSTRATE_001.md` graduates and assigns continuity the substrate+inheritance office — at which point projection receipts become a named obligation, not a candidate.

## Non-goals (explicit)

- No implementation authorized. This is a name, not a build ticket.
- Not a verdict/authority surface. Continuity remains the **medium**, not a witness office and not consequence — a ProjectionReceipt testifies to *what a read was*, it does not authorize anything.
- No transition-kernel import. Continuity does not adopt admission/authorization machinery.
- Storage-side ledger shape is *not* the prize here; if it ever helps, it is a separate record.

## Doctrine lines

- Continuity stores sealed records; it does not make future decoders honest.
- Stored is not true. Signed is not witnessed. A read is a claim.
- Every semantic read across a schema/version/projection boundary must be witnessed.

---

*Candidate. Name early, ratify lazily. No implementation authorized by this record.*
