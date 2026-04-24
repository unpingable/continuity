# Gap: Useful Refusal — structured rely_reason for machine-consumable refusal

**Status:** proposed
**Depends on:** existing `_compute_rely_state` machinery
**Related:** none yet; downstream consumers (Governor refusal surfaces, CLI `why` command, future TUI) will benefit
**Last updated:** 2026-04-24

## The Problem

`rely_ok=false` today carries a free-form `rely_reason` string. The strings are already operationally decent — they name IDs, statuses, and specific check failures (`"hard premises unavailable: mem_xyz:missing, mem_abc:revoked"`, `"memory is expired"`). Textually useful.

The gap is that downstream consumers cannot filter, route, or act on the refusal category without string parsing. A Governor surface that wants to show "all rely failures due to expired horizons" has to regex. A TUI `why` view that wants to render "Blocking conditions" as a structured checklist has to parse a sentence. Operators who have been burned want surgical refusals, and surgical refusals require typed reasons.

Two risks compound:

1. **Drift.** New rely conditions added later may produce strings that don't match existing patterns, silently degrading parseability.
2. **Policy fog.** A free-form string field is where vague language like "alignment concerns detected" or "this memory is not currently relyable" sneaks in. Today's strings are good; there is no structural guard keeping them good.

This gap is about making refusal machine-consumable and drift-resistant, not about rewriting the strings.

## Design Stance

**Promote `rely_reason` to a structured shape alongside a rendered human string.** Callers that want text still get text; callers that want to branch on category get typed fields.

The existing checks in `_compute_rely_state` already map to discrete categories (status, expiry, reliance_class, kind/basis policy, hard premise). The codes already exist — they just aren't named.

No new checks in v1. The scope is: structure what's already there.

## Architectural Invariants

1. **Refusal carries a category code.** Every `rely_ok=false` return names a specific, enumerable reason category (e.g. `STATUS_NOT_COMMITTED`, `EXPIRED`, `RELIANCE_NONE`, `KIND_BASIS_POLICY`, `HARD_PREMISE_UNAVAILABLE`). Free-text-only refusal is a defect.
2. **Refusal names specifics by ID.** When the reason involves other memories (premises, supersession targets), the offending `memory_id`s are surfaced as structured fields, not embedded in prose.
3. **Timestamps are structured where relevant.** Expiry refusals include the `expires_at` value as a field, not just "memory is expired."
4. **Success also carries a code.** `rely_ok=true` returns an `ELIGIBLE` code plus the reliance class; callers that log or audit outcomes get uniform shape across success and failure.
5. **Rendered string remains.** `rely_reason` as a human-readable string stays on the response, derived from the structured form. Existing CLI/text consumers do not break.
6. **Codes are additive.** New categories can be added. Existing codes do not change meaning or get renamed. Consumers can switch on known codes and fall through on unknown.

## Deliberately out of scope (v1)

- New rely conditions (horizon-of-commitment, conditioned_on, reliance-class decay, standing gates). The gap spec for temporal admissibility doctrine is separate.
- Multi-reason refusal. If multiple conditions fail, v1 may return the first one encountered, as today. Aggregating all failing conditions into one response is v2.
- Internationalization of the human string.
- Distinguishing "cannot rely" vs "may rely with caveat" vs "insufficient evidence" as separate outcomes. Today `rely_ok` is boolean; a richer ternary belongs in a later spec if ever.

## Data Shape

New enum `RelyReasonCode` (or similar), with at least these v1 values mirroring existing checks:

- `ELIGIBLE` — success; paired with the reliance class in the detail
- `STATUS_NOT_COMMITTED` — current status (observed/revoked) fails the committed precondition
- `EXPIRED` — past `expires_at`
- `RELIANCE_NONE` — committed but reliance_class=none
- `KIND_BASIS_POLICY` — kind/basis combination forbids the requested reliance class (summary/hypothesis cannot be actionable; inference/synthesis cannot be actionable)
- `HARD_PREMISE_UNAVAILABLE` — one or more hard premises are missing or revoked

New response shape on `ExplainMemoryResponse`, `CaseItem`, and anywhere else `rely_ok` + `rely_reason` ship together:

```python
class RelyState(JsonModel):
    rely_ok: bool
    code: RelyReasonCode
    message: str  # the rendered human string, kept for compatibility
    details: dict  # structured: e.g. {"expires_at": "...", "bad_premises": ["mem_x:revoked", ...], "required_class": "actionable", "actual_class": "advisory"}
```

Exact field names are open. Load-bearing: code + details + derived message.

`rely_reason: str` may stay as a flat field for backward compatibility, populated from `message`; or the structured form replaces it with a clean migration. Decide at implementation time.

## V1 Slice

1. Define `RelyReasonCode` enum covering existing checks.
2. Refactor `_compute_rely_state` to return `(code, details)` alongside (or in place of) the current string. Render the message from code+details so the strings look the same as today by default.
3. Thread the structured form through `ExplainMemoryResponse`, `CaseItem`, and MCP response payloads.
4. Add a CLI helper (`contctl why` or `contctl explain --brief`) that renders the structured form operator-forward: code + specifics first, supporting detail second. (This is the HITL polish pass landing on top.)
5. Tests: each code has a case that produces it with the right details; unknown codes round-trip cleanly (forward compatibility).

## Acceptance Criteria

- `rely_ok=false` responses carry a machine-readable category code.
- Structured details (offending IDs, expiry timestamps, class mismatches) are typed fields, not embedded prose.
- Existing human-readable `rely_reason` strings continue to be available and visually match today's output by default.
- A downstream consumer can switch on the code to route handling (log, surface, retry, escalate) without string parsing.
- Adding a new rely condition later requires adding an enum value, not altering existing ones.
- No existing rely-check behavior changes; v1 is purely a shape upgrade.

## Short Version

Refusal today is operationally decent but unparseable. Promote `rely_reason` from free-form string to structured code + details + rendered message. No new checks, no new outcomes — just give downstream consumers (Governor refusal surfaces, CLI `why`, future TUI) a typed shape to branch on so refusal stays useful as the system grows and doesn't silently drift into policy fog.
