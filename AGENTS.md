# AGENTS.md — Working in this repo

This file is a **travel guide**, not a law.
If anything here conflicts with the user's explicit instructions, the user wins.

> Instruction files shape behavior; the user determines direction.

---

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

Always run tests before proposing commits. Never claim tests pass without running them.

---

## Safety and irreversibility

### Do not do these without explicit user confirmation
- Push to remote, create/close PRs or issues
- Delete or rewrite git history
- Modify schema.sql in ways that break existing databases
- Drop or rename SQLite tables

### Preferred workflow
- Make changes in small, reviewable steps
- Run tests locally before proposing commits
- For any operation that affects external state, require explicit user confirmation

---

## Repository layout

```
continuity/
  src/continuity/
    api/models.py        — Pydantic domain models, enums, request/response
    store/schema.sql     — SQLite schema (5 tables)
    store/sqlite.py      — SQLiteStore (observe, commit, revoke, query, explain)
    memory/policy.py     — MemoryPolicy (Governor seam)
    receipts/            — Receipt shapes (WLP-compatible, future)
    ingest/              — Spool import, WLP import (future)
    util/                — clock, hashing, ids, jsoncanon
  tests/                 — pytest suite
  docs/                  — Architecture docs (future)
```

---

## Coding conventions

- Python 3.11+, type hints, Pydantic v2
- pytest for testing, tmp_path for SQLite fixtures
- Canonical JSON for hashing (sorted keys, compact separators)
- Prefixed UUIDs for all IDs (mem_, evt_, rcpt_, lnk_, imp_)
- UTC timestamps everywhere via continuity.util.clock

---

## Invariants

1. Every state mutation produces a hash-chained receipt
2. No silent promotion: observed cannot become relied-on without explicit commit
3. Links preserve history: revocation of a premise taints dependents via explain/rely, does not destroy edges
4. Premises append on commit, never silently replace
5. Schema CHECK constraints enforce valid enum values in SQLite

---

## What this is not

- Not a vector database or semantic search engine
- Not an LLM memory/summarization tool
- Not a distributed system
- Not a truth maintenance system with automatic cascades

---

## When you're unsure

Ask for clarification rather than guessing, especially around:
- Whether a change should modify the SQLite schema
- Whether a new memory kind or reliance class is needed
- Anything that changes a documented invariant

---

## Agent-specific instruction files

| Agent | File | Role |
|-------|------|------|
| Claude Code | `CLAUDE.md` | Full operational context, build details, conventions |
| Codex | `AGENTS.md` (this file) | Operating context + defaults |
| Any future agent | `AGENTS.md` (this file) | Start here |
