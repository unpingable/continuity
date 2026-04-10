# continuity

Claude forgot what you decided last week. Again.

You told it the auth migration was blocked on legal review. You told it the config format changed. You told it not to touch the billing module until after the freeze. It nodded, it complied, and then the session ended. Next session, it had no idea. So you told it again. And again. And you started to wonder whether "memory" means anything if nothing stops stale memory from driving action.

## What you'd normally think

"It needs better memory." Longer context windows. Bigger memory files. Smarter summarization. RAG over everything. The assumption is that the problem is retrieval — the system can't find what it knew before. So you build a better search engine for past conversations and call it solved.

## What's actually happening

The retrieval works fine. The problem is that retrieval has no authority model. When Claude "remembers" something, there's no distinction between a passing observation from three weeks ago, a decision you explicitly committed to yesterday, and a stale note that was superseded but never cleaned up. They're all just text in a file. There's no way to ask "is this still safe to act on?" because nothing tracks whether the premises underneath a memory are still valid.

This is what silent promotion looks like: an observation quietly hardens into something downstream actions rely on, with no explicit transition and no receipts. Your offhand comment becomes canon. A hypothesis becomes a constraint. A revoked decision keeps driving behavior because nothing recorded the revocation.

## Why the obvious framing is insufficient

Memory systems assume the hard problem is storage and retrieval. It isn't. The hard problem is *governance* — what may persist, what may be relied on, and what happens when the premises underneath a committed memory go bad.

This isn't a search problem. It's an authority problem. Retrieval is not authority. Recall is not truth. Having seen something is not the same as having committed to it.

## What continuity actually is

A governed state persistence layer. Three verbs:

- **observe** — cheap, noisy, not binding. "Claude noticed this." No downstream system should rely on it without promotion.
- **commit** — durable, receipted, scoped. "This was explicitly promoted with a reliance class." Something downstream may now depend on it, within bounds.
- **rely** — the check before action. "Are the premises under this memory still valid, or has something been revoked?" If a hard premise was revoked, rely fails. The system tells you why.

Every state change produces a hash-chained receipt. Revoked memories stay as evidence — tombstones over disappearance. Premise links are explicit, written deliberately, never inferred from content. History is never destroyed.

The storage is boring local SQLite. Three layers: objects (current state), events (append-only mutation log), receipts (hash-chained attestations). Plus a dependency graph and an async ingest tracker. No vector search. No LLM summarization. No distributed anything.

## What to check next

**Install and run the tests:**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

**Try the MCP server** (if you use Claude Code):

The MCP server exposes continuity as tools Claude can call directly — `memory_observe`, `memory_commit`, `memory_query`, `memory_explain`, and more. Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "continuity": {
      "command": "/path/to/your/.venv/bin/continuity-mcp",
      "args": []
    }
  }
}
```

**Try the CLI:**

```bash
contctl observe --scope myproject --kind decision --basis operator_assertion \
  --content '{"text": "auth migration blocked on legal review"}'

contctl query --scope myproject --status committed
```

**Read the code:**

| Path | What's there |
|------|-------------|
| `src/continuity/store/sqlite.py` | The store — observe, commit, revoke, query, explain |
| `src/continuity/api/models.py` | Domain models, enums, request/response types |
| `src/continuity/store/schema.sql` | SQLite schema (5 tables) |
| `src/continuity/mcp.py` | MCP server (7 tools over JSON-RPC/stdio) |
| `src/continuity/memory/policy.py` | Governor policy seam |
| `tests/` | Lifecycle, idempotency, query, receipts, rely gate |

## Design principles

Emit locally. Ingest idempotently. Never silently harden. Revoke by event. Derive by view.

Built on patterns the internet already learned: append-only logs, maildir-style durable objects, outbox/inbox, idempotent ingestion, tombstones over deletion, capability-scoped writers. Boring ancestors, healthy descendants.

## License

Apache-2.0
