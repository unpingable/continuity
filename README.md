# continuity

Governed state persistence — durable, receipted, scoped memory with observe/commit/rely semantics.

## What it does

- Persists cross-session memory objects with explicit lifecycle: observe, commit, revoke
- Hash-chains every mutation as a receipt (WLP-compatible envelope)
- Tracks provenance via first-class dependency links between memories
- Computes `rely_ok` by checking premise validity — retrieval is not authority
- Stores everything in boring local SQLite

## What this is not

- Not a vector database or semantic search engine
- Not an LLM summarization tool — persists structure, not vibes
- Not a distributed system — local-first, single-file substrate
- Not a truth maintenance system — no automatic invalidation cascades

## Invariants

1. **No silent promotion.** An observation must not quietly harden into something downstream actions rely on without explicit transition and receipts.
2. **Every mutation receipted.** Hash-chained, append-only.
3. **History preserved.** Revoked links stay as evidence; `explain` reads taint from source status.
4. **Retrieval is not authority.** `reliance_class` governs what may be relied on.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Architecture

Three-layer storage design:

```
memory_objects   — materialized current state
memory_events    — append-only mutation log
receipts         — hash-chained attestations
memory_links     — provenance/dependency graph
spool_imports    — async ingest tracking
```

Core verb split:

| Verb | Meaning |
|------|---------|
| **observe** | Cheap, noisy, not binding. Creates a memory with `status=observed`, `reliance_class=none`. |
| **commit** | Durable, receipted, scoped. Promotes to `status=committed` with an explicit `reliance_class`. |
| **rely** | Downstream computation checks `explain`/`rely_ok` before depending on a memory. |

Design mantra: **Emit locally. Ingest idempotently. Never silently harden. Revoke by event. Derive by view.**

## License

Licensed under Apache-2.0.
