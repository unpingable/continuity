# Declaration Export v0 (`continuity.declaration_export.v0`)

A read-only projection of what Continuity holds, shaped for a downstream consumer
(initially the Spine read plane) to **locate and package**. Continuity owns this
contract; the consumer never reaches into Continuity's internals.

> Continuity exports declarations. The consumer locates and packages them.
> Neither act creates standing.

## What it says — and only says

```
here are declared refs;
here is how Continuity holds them (a *quoted* status + *quoted* metadata);
here is export provenance;
here is an export digest over the declarations.
```

It deliberately does **not** say: these are authoritative / current / canonical /
ratified / doctrine, or that one declaration supersedes another *as truth*. Continuity
knows richer things internally (`reliance_class`, `supersedes` pointers, commit
status); this surface is intentionally humiliating. A status is emitted as a **quoted
source status**, never a universal fact — every status carries the tag
`quoted_continuity_status_not_spine_standing` so no reader can mistake it for their own
standing. (Invariant 4: retrieval is not authority.)

## Shape

```json
{
  "schema": "continuity.declaration_export.v0",
  "export_id": "sha256:...",
  "exported_at": "2026-06-28T...Z",
  "source": { "tool": "continuity", "version": "...", "repo": null, "commit": null },
  "declarations": [
    {
      "ref": "spine:DOCTRINE.md",
      "path": "DOCTRINE.md",
      "declared_at": "2026-06-...",
      "source_status": { "value": "committed", "standing": "quoted_continuity_status_not_spine_standing" },
      "source_metadata": { "kind": "decision", "reliance_class": "advisory", "scope": "spine", "confidence": "0.5" }
    }
  ]
}
```

A memory contributes a declaration **iff** its `content` carries a non-empty `ref`
(optionally a `path`). Memories without a locatable ref are excluded with a reason —
no silent drops.

## Guarantees (mechanical, not aspirational)

- **Deterministic, content-addressed digest.** `export_id` is a sha256 over the
  schema tag + declarations only; `exported_at` and `source` provenance are excluded.
  The same held declarations always produce the same `export_id`. The clock is resolved
  at the boundary (the CLI), never inside the builder (Continuity time discipline).
- **Allowlisted metadata.** `source_metadata` quotes a fixed allowlist of fields
  (`kind`, `reliance_class`, `scope`, `confidence`, `supersedes`) — free-form `content`
  cannot inject an authority-shaped field through the export.
- **No authority/recency field.** The builder self-checks and refuses to emit an export
  carrying any of: `latest`, `current`, `canonical`, `authoritative`, `authority`,
  `ratified`, `supersedes_as_truth`, `doctrine`. (`supersedes` as a *quoted pointer* is
  fine; supersession-*as-truth* is not.)

## CLI

```bash
contctl export --scope SCOPE [--status committed|observed|revoked|any] \
    [--include-expired] [--repo REPO] [--commit SHA]
```

Defaults to `--status committed` (the durable declarations). `--repo`/`--commit` are
optional, operator-attested provenance (excluded from `export_id`, so they never affect
content identity).

## Consumer (separate custody)

The Spine read plane consumes `continuity.declaration_export.v0` in its own repo
(`unpingable/spine`, Slice 2c) via a `DeclarationSource` that maps each declaration to
a located/rendered entry — and refuses to map any quoted Continuity status into Spine
standing. The export is the envelope; the verdict stays out of it.

Implementation: `src/continuity/declaration_export.py`; tests:
`tests/test_declaration_export.py`.

## Consumer reconciliation (Spine, recorded 2026-07-03)

Spine's Slice 2b fixture (`spine/src/spine/continuity_fixture.py`,
`tests/fixtures/continuity_export_shape_v0.json`) **predates this contract**. It was
modeled on Continuity `@ aab46ec` — before `contctl export` existed — and consumes a
raw JSON list of `continuity.receipt.v0` envelopes, locating each ref via
`payload.content.repo` + `payload.content.path`. This contract instead emits a single
envelope with `declarations[]`, each carrying `ref` + `path` and a quoted
`source_status`.

The mismatch is bounded and known, not a defect in either repo: 2b's job was to prove
Spine could consume a Continuity-*shaped* export with zero dependency on this package,
and it did. Spine Slice 2c (not started) writes the real `DeclarationSource` against
*this* schema and retires the fixture assumption. Continuity's side of that work is
**shipped**: a golden conformance fixture at
[`tests/fixtures/declaration_export_v0_golden.json`](../tests/fixtures/declaration_export_v0_golden.json),
byte-locked by [`tests/test_declaration_export_golden.py`](../tests/test_declaration_export_golden.py).
Spine vendors that file the same way it vendored its 2b fixture. The golden also freezes
the mapping seam 2c depends on: every `ref` is `"<repo>:<path>"`, so a consumer splits
on the first `:` to fill its own `(repo, path)` — the recovered path equals the
declaration's `path` field. If the byte-lock test ever fails, the wire format changed:
regenerate the golden **and** notify Spine, because a vendored copy just went stale.

Spine additionally needs its own `build_edition` refactor (bytes-from-source instead of
manifest-file path) — their named forcing case for 2c, no Continuity change implied.

Retire this section when 2c lands.
