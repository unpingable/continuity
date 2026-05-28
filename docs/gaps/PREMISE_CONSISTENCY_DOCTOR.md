# Gap: Premise Consistency Doctor — premise links as self-check surfaces, not just provenance

**Status:** proposed
**Depends on:** existing memory entries with `[[premise]]`-style links (currently informal in `~/.claude/projects/*/memory/`), planned `continuity doctor` audit harness
**Related:** `CROSS_ISLAND_BRIDGES_GAP.md` (audited memories may cross island boundaries — bridges deferred), `ISLAND_DISCIPLINE.md`, `~/git/cartography/coordination/SELF-SUBJECT-COLLAPSE.md` (cross-component pattern — the discipline below is continuity's local manifestation)
**Last updated:** 2026-05-28

## The Problem

Memory entries cite premises with `[[link]]` references. Today those links function as provenance — *where this came from* — but nothing verifies that a child memory's operational requirements remain consistent with the premises it cites.

On 2026-05-13, AG Claude caught a globally-scoped memory whose framing made project uptake optional, despite linking to a premise that made consultation load-bearing. The contradiction was invisible because child and premise lived in different layers — each read alone looked fine. The shape: a child cites a premise that imposes an obligation, but the child's wording weakens, omits or contradicts that obligation. This bit on a real memory. The same shape will recur because there is no audit surface.

## Failure Mode

A `[[premise]]` link is currently decorative — its presence does not constrain the child memory's wording, scope, or operational claims. Premises and children drift apart layer-by-layer:

- advisory memory accidentally encoding an obligation its premise rejects
- coordination memory leaving the coordination path optional despite a premise demanding it bind
- local stub that fails to instantiate the global rule it claims to carry
- "recognition rule" with no recognition mechanism, citing a premise that required one
- global doctrine whose origin breadcrumb points to a project rule that has since been narrowed or retired

All five share one structure: child contradicts premise across layers, invisible from either side alone.

## Concrete Trigger

`mem_deb2f0af6cab40788dec5f5b9fe0023f` — the doctrine-promotion memory AG Claude rewrote 2026-05-13. Earlier framing left project uptake optional; the linked premise required consultation be load-bearing. AG Claude's correction made the recognition obligation explicit and added the local-stub mechanism that instantiates the premise. The pre-correction / post-correction pair is the dogfood fixture.

## Design Stance

**Premise links should function as review surfaces, not just provenance trails.** A linked premise constrains the child memory; if a memory cites a premise, it inherits a consistency obligation. `continuity doctor --check premise-consistency` walks memory entries, follows premise links, and flags entries whose wording weakens or contradicts the operational requirement of any cited premise.

The doctor is audit, not gate. It reports; operators resolve.

## Self-Subject Collapse discipline

The doctor's subject is continuity. The doctor's actor is also continuity. That makes premise-consistency a standing-prohibition instance of the cross-component pattern named in `~/git/cartography/coordination/SELF-SUBJECT-COLLAPSE.md`: a finding whose subject is the producing component may be reported by that component, but it may not be resolved by it. The continuity-local manifestation:

- **Continuity-as-doctor may report findings about continuity's own substrate or state.** That is the doctor's job.
- **Continuity-as-doctor may not self-resolve those findings.** No code path inside the doctor produces a verdict that closes, clears, ratifies, or absolves a flag it raised.
- **Every finding where continuity is both actor and subject routes to an external reconciler.** The operator is the natural reconciler today; a deliberately-architected external actor may take that role later. The routing target is named on the finding; the absence of a target is itself a flag, not an implicit clearance.
- **Doctor output is testimony / finding, not authority.** A FLAG is a claim about the substrate; it is not a `reliance_class` change, not a status mutation, not a receipt that closes a prior receipt.
- **Premise-consistency findings do not mutate, suppress, rewrite, or auto-ratify memory records.** The substrate is read-only to the doctor at this seam. Any write that resolves a finding is an operator act with its own receipt, not a doctor effect.

> **A continuity doctor may diagnose continuity. It may not absolve continuity.**

This belongs in the spec before implementation because the self-resolution bug, once written, gets refactored into "maintenance" and stops looking like a category error. Naming it as a discipline up front prevents the doctor from growing a `--fix` flag that quietly cures whatever it just flagged.

## V1 Slice

1. `continuity doctor --check premise-consistency [<path>]` scans a memory directory (default: workspace-resolved memory store).
2. For each memory file with `[[premise-name]]` links, locate the premise and emit:
   - **OK** — no contradiction detected by current heuristics
   - **FLAG** — obligation/wording mismatch; surface premise, child, and the conflicting phrase pair
   - **MISSING** — premise link points nowhere
3. Heuristics for v1: keyword pairs marking obligation vs optionality (`must`/`optional`, `load-bearing`/`ambient`, `binding`/`advisory`, `required`/`may`) cross-checked between premise and child. Plus structural: a premise that ships a mechanism (stub, hook, lint) flags children that drop the mechanism.
4. Dogfood fixture committed under `tests/fixtures/premise_consistency/` — the `mem_deb2f0af...` pre/post pair, plus 3–5 hand-built positive/negative pairs covering each failure-mode shape above.
5. Output is operator-readable: cites premise file, child file, the wording pair that triggered the flag. JSON variant for downstream `contctl` integration.

## Deliberately out of scope (v1)

- No ontology expansion or theorem prover.
- No generalized contradiction engine across arbitrary memory pairs — only premise→child, single hop.
- No automatic resolution or rewrite suggestions; flagging is the deliverable.
- No write-blocking — doctor is audit, not gate.
- Multi-hop premise chains (premise-of-premise). V1 is single-hop.
- Cross-island premise resolution — deferred to `CROSS_ISLAND_BRIDGES_GAP.md` consequences.
- Embedding-similarity scoring. Keyword pairs only for v1; revisit if false-positive rate is unworkable.

## Acceptance Criteria

- `continuity doctor --check premise-consistency` runs against a memory directory and emits OK / FLAG / MISSING per entry.
- The dogfood fixture (today's `mem_deb2f0af...` corrected pair) flags in its pre-correction form and clears in its post-correction form.
- Output cites premise file, child file, and the wording pair that triggered the flag.
- The doctor's own outputs are themselves auditable by it — self-validation: the doctor cites premises and must not contradict them.
- False-positive rate on the existing memory corpus is workable (informal threshold; tune from real runs).

## Open Questions

1. **Where premise links live.** Currently `[[name]]` in markdown body. Should the doctor also recognize structured frontmatter premise lists? Probably yes — same heuristic, easier parsing.
2. **Severity grading.** Should FLAG distinguish weak-vs-strong contradictions? V1 probably treats all flags equal; revisit if operators report noise.
3. **Receipt emission.** Should the doctor emit a continuity event (`doctor.flagged_premise_inconsistency`) for receipt-chain traceability? Aligns with the templates-as-product thesis that recognition events should be receipted, not just logged.
4. **Heuristic graduation path.** When keyword-pair coverage runs out, the next step is small structured premise annotations (`obligation: must consult`) rather than embeddings. Defer until v1 noise floor demands it.

## Short Version

Premise links are currently decorative. Today they caught a real layer-crossing contradiction — but only because a human read both layers. `continuity doctor --check premise-consistency` makes the catch reproducible. V1 is narrow: walk memory directory, follow premise links, flag wording-vs-obligation mismatches, ship the corrected `mem_deb2f0af...` pair as the dogfood fixture. No theorem prover, no contradiction engine, no write-blocking. Premise links bind, or they should be removed.
