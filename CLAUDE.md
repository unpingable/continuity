# CLAUDE.md — Instructions for Claude Code

## What This Is

continuity: Governed state persistence with observe/commit/rely semantics. Durable, receipted, scoped memory for cross-session state that later computation can depend on.

## What This Is Not

- Not a vector database or semantic search engine
- Not an LLM summarization tool — the daemon persists structure, not vibes
- Not a distributed system — local SQLite, boring and correct
- Not a truth maintenance system — no automatic invalidation cascades

## Invariants

1. No silent promotion: an observation must not quietly harden into something downstream actions rely on without explicit transition and receipts
2. Every state mutation produces a hash-chained receipt
3. Historical structure is never destroyed: revoked links stay as evidence, `explain` reads taint from source status
4. Retrieval is not authority: `reliance_class` governs what may be relied on, not just what can be queried
5. Premises append, never silently replace

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Project Structure

- `src/continuity/api/models.py` — Pydantic domain models, enums, request/response types
- `src/continuity/store/schema.sql` — SQLite schema (5 tables: memory_objects, memory_events, receipts, memory_links, spool_imports)
- `src/continuity/store/sqlite.py` — SQLiteStore (observe, commit, revoke, query, explain)
- `src/continuity/memory/policy.py` — MemoryPolicy (Governor seam)
- `src/continuity/util/` — clock, hashing, ids, jsoncanon
- `tests/` — pytest suite covering lifecycle, idempotency, query, receipts, rely gate

## Conventions

- License: Apache-2.0
- Python 3.11+, type hints everywhere, Pydantic v2
- Testing: pytest, all tests use tmp_path SQLite databases
- No datetime.utcnow() — use continuity.util.clock.utcnow() (timezone-aware)
- JSON storage: canonical_json() for deterministic hashing
- IDs: prefixed UUIDs (mem_, evt_, rcpt_, lnk_, imp_)

## Architecture

Three-layer storage:
1. `memory_objects` — materialized current state
2. `memory_events` — append-only mutation log
3. `receipts` — hash-chained attestations

Plus:
- `memory_links` — provenance/dependency graph (premises and dependents)
- `spool_imports` — async ingest tracking

Core verb split:
- **observe**: cheap, noisy, not binding (status=observed, reliance_class=none)
- **commit**: durable, receipted, scoped (status=committed, reliance_class set)
- **rely**: downstream computation checks explain/rely_ok before depending on memory

## Don't

- Don't build automatic invalidation cascades — rely_ok computes taint from premise status
- Don't collapse identity and persistence — standing says who can act, continuity says what may persist
- Don't infer links from content — premises are explicit, written deliberately
- Don't add vector search, LLM summarization, or distributed anything yet
- Don't delete receipts or events — append-only, tombstones over disappearance
