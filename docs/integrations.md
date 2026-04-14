# Integrations

How to talk to continuity. Three modes, one model. The vocabulary and invariants are in [`concepts.md`](concepts.md); this doc is a reference for the surfaces.

## Modes at a glance

| Mode | For | Process shape | Entry point |
|------|-----|---------------|-------------|
| **MCP server** | Claude Code / other MCP clients calling memory tools during a session | stdio subprocess, JSON-RPC | `continuity-mcp` (installed with the package) |
| **CLI (`contctl`)** | Humans, shell scripts, CI jobs, ad-hoc inspection | short-lived invocation | `contctl <command>` |
| **Python library** | In-process integration, custom tooling, test harnesses | direct import | `from continuity.store.sqlite import SQLiteStore` |

All three talk to the same on-disk SQLite stores. They share schema, receipt chains, and explain semantics. Choose the one that fits the process shape — the data is the same.

## Store location

Continuity resolves a store path in this order (first match wins):

1. `--db PATH` on the CLI, or explicit path passed to `SQLiteStore(path)`
2. `CONTINUITY_DB` environment variable
3. Per-project default (derived from `cwd` / git root)
4. Workspace default (if the working dir is in a registered workspace)
5. Global default (`~/.local/share/continuity/global.db` or platform equivalent)

`contctl where` prints which path and source resolver would be used from the current directory. Start there when unsure.

## MCP server

The MCP server exposes continuity as tools a Claude Code session can call directly. It runs as a stdio subprocess over JSON-RPC; nothing network-facing.

### Installation

```json
// .claude/settings.json or the project/user equivalent
{
  "mcpServers": {
    "continuity": {
      "command": "/absolute/path/to/.venv/bin/continuity-mcp",
      "args": []
    }
  }
}
```

For faster bootstrap, `contctl bootstrap` writes a minimal `.mcp.json` in the current project pointing at the local venv.

### Tools exposed

| Tool | Purpose |
|------|---------|
| `memory_observe` | Create a memory (status=observed) |
| `memory_commit` | Promote observed → committed with a reliance class |
| `memory_revoke` | Retire a memory (status=revoked, stays as evidence) |
| `memory_query` | Query memories by scope/kind/status/basis/reliance_class |
| `memory_query_latest` | Most recently updated memory matching (scope, kind) |
| `memory_get` | Get a single memory by ID |
| `memory_get_case` | Derived case bundle for a scope (investigation view) |
| `memory_explain` | Full lineage, receipt chain, premises, dependents, rely_ok |
| `memory_stats` | Store-level counts and summary |

Tool schemas (including the `LinkRelation` enum on premise `relation` fields) are defined in [`src/continuity/mcp.py`](../src/continuity/mcp.py).

### When to use MCP

When a Claude session wants to record, query, or verify memory during the work itself. The MCP path is for *live* integration: observations captured as they happen, rely checks performed before acting.

## CLI (`contctl`)

The CLI is for humans, shell scripts, and out-of-band inspection. Every MCP tool has a CLI equivalent, plus store-management commands MCP does not expose.

### Lifecycle commands

```bash
contctl init                       # initialize a store in the resolved path
contctl migrate                    # patch schema on an existing store
contctl where                      # print resolved path and resolver source
contctl bootstrap                  # write .mcp.json for Claude Code
contctl stats                      # show store counts
```

### Memory commands

```bash
contctl observe --scope SCOPE --kind KIND --basis BASIS \
    --content '{"text": "..."}' [--premise MID[:relation[:strength]]]

contctl commit MEMORY_ID --reliance-class retrieve_only [--note "..."]
contctl revoke MEMORY_ID --reason "..." [--replacement NEW_MID]

contctl get MEMORY_ID
contctl query --scope SCOPE [--kind KIND] [--status STATUS] [--limit N]
contctl latest --scope SCOPE --kind KIND        # most recent
contctl explain MEMORY_ID                       # lineage + rely_ok
contctl case SCOPE                              # case bundle for a scope
```

### Workspace commands

```bash
contctl workspace create NAME
contctl workspace list
contctl workspace show NAME
contctl workspace add-project NAME PROJECT_PATH
contctl workspace remove-project NAME PROJECT_PATH
```

Full flag reference lives in `contctl <command> --help`.

### When to use the CLI

Setup (`init`, `migrate`, `bootstrap`), inspection (`where`, `stats`, `explain`, `query`), scripted ingest, and CI jobs. Not for high-frequency writes from a long-running process — use the library for that.

## Python library

For in-process integration: custom tools, test harnesses, anything that needs to read or write without spawning a subprocess.

### Entry points

```python
from continuity.store.sqlite import SQLiteStore
from continuity.api.models import (
    ObserveMemoryRequest, CommitMemoryRequest, RevokeMemoryRequest,
    MemoryKind, Basis, RelianceClass, LinkRelation,
)

store = SQLiteStore("/path/to/store.db")
store.initialize(scope_kind="project", scope_label="myproj")

req = ObserveMemoryRequest(
    scope="myproj",
    kind=MemoryKind.DECISION,
    basis=Basis.OPERATOR_ASSERTION,
    content={"text": "auth migration blocked on legal review"},
)
resp = store.observe_memory(req)
# resp.memory.memory_id, resp.receipt, etc.
```

### Key surfaces

| Module | What's there |
|--------|--------------|
| [`continuity.store.sqlite`](../src/continuity/store/sqlite.py) | `SQLiteStore` — observe, commit, revoke, query, explain, case bundle |
| [`continuity.api.models`](../src/continuity/api/models.py) | Pydantic request/response types, enums, `PremiseRef`, `MemoryLink` |
| [`continuity.memory.policy`](../src/continuity/memory/policy.py) | `MemoryPolicy` — the Governor seam for reliance-class gating |
| [`continuity.util`](../src/continuity/util/) | `clock.utcnow()`, `jsoncanon.canonical_json()`, `ids.new_id()`, hashing |

### When to use the library

Anything long-running, anything that needs custom integration points (e.g. a daemon that observes events and promotes selected ones), anything under test. Also the right path for building a higher-level tool on top of continuity — the CLI and MCP server are themselves library consumers.

## Choosing between the three

- **Claude session wants to record or check?** MCP.
- **Human typing commands, or a shell script?** CLI.
- **Your own code wants to integrate directly?** Library.

When a workflow crosses modes — e.g. a CLI `init` followed by MCP tool calls in the same project — the store is shared and the receipt chain is continuous. Nothing depends on which surface a given transition came through; the audit trail treats them uniformly.

## Related reading

- [`concepts.md`](concepts.md) — the mental model all three surfaces share
- [`gaps/CROSS_SCOPE_REFERENCE_GAP.md`](gaps/CROSS_SCOPE_REFERENCE_GAP.md) — proposed doctrine for references that cross store boundaries
- [`../README.md`](../README.md) — narrative onboarding
