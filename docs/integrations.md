# Integrations

How to talk to continuity. Three modes, one model. The vocabulary and invariants are in [`concepts.md`](concepts.md); this doc is a reference for the surfaces.

## Modes at a glance

| Mode | For | Process shape | Entry point |
|------|-----|---------------|-------------|
| **MCP server** | Claude Code / other MCP clients calling memory tools during a session | stdio subprocess, JSON-RPC | `continuity-mcp` (installed with the package) |
| **CLI (`contctl`)** | Humans, shell scripts, CI jobs, ad-hoc inspection | short-lived invocation | `contctl <command>` |
| **Python library** | In-process integration, custom tooling, test harnesses | direct import | `from continuity.store.sqlite import SQLiteStore` |

All three talk to the same on-disk SQLite stores. They share schema, receipt chains, and explain semantics. Choose the one that fits the process shape — the data is the same.

**Adopter classes.** The MCP path is for Claude Code sessions; the library and CLI paths are adopter-agnostic. Non-Claude adopters (e.g., the WLP persistence adapter at [`gaps/WLP_PERSISTENCE_ADAPTER_GAP.md`](gaps/WLP_PERSISTENCE_ADAPTER_GAP.md)) integrate via the library or CLI without involving MCP. The substrate (verbs, schema, receipts, premise graph, rely check) is the same for all adopter classes. The discipline that holds across adopters: **persistence ≠ transport; receipt store ≠ reliance engine.** Continuity does not route, validate, propagate revocations, or decide reliance — adopters bring those.

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
| `memory_repair` | Narrow patch to content/source_refs/confidence on an existing memory |
| `memory_import` | Cross-DB import with content-hash verification |
| `memory_query` | Query memories by scope/kind/status/basis/reliance_class |
| `memory_query_latest` | Most recently updated memory matching (scope, kind) |
| `memory_get` | Get a single memory by ID |
| `memory_get_case` | Derived case bundle for a scope (investigation view) |
| `memory_explain` | Full lineage, receipt chain, premises, dependents, rely_ok |
| `memory_verify_reliance` | Walk a consumer receipt's `relied_on` array against the local store |
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
contctl explain MEMORY_ID [--evaluation-time ISO8601]   # lineage + rely_ok (replayable)
contctl case SCOPE                              # case bundle for a scope

contctl repair MEMORY_ID --reason "..." --content '{...}'  # narrow content fix
contctl import --from PATH --memory-id MID               # cross-DB pinned import
contctl reliance verify RECEIPT.json                     # verify relied_on array
```

`--allow-island` is a global flag that opts into cross-project-shaped writes (scope=global / scope=workspace*) against a project-local store. Without it, such writes refuse — see [`gaps/ISLANDS_OF_CONTINUITY.md`](gaps/ISLANDS_OF_CONTINUITY.md).

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

## Cross-component reliance

When consumer tools (Wicket, Nightshift, Standing, NQ) act on continuity-recorded state, their own receipts should carry **which memories they relied on**. This makes the action replayable later: an auditor can walk back from a receipt to the cited memory, see whether the citation has drifted, and label the drift by name.

Three keepers anchor the design (preserved verbatim in [`gaps/CROSS_COMPONENT_RELIANCE_GAP.md`](gaps/CROSS_COMPONENT_RELIANCE_GAP.md)):

> **Continuity records what may be relied on; it does not decide who may speak.**

> **Continuity can distribute reliance records. It should not distribute the rely path.**

> **Cross-host reliance cannot be stronger than local reliance replay.**

### `relied_on` receipt convention

A consumer receipt that cited continuity memory carries a field like:

```json
{
  "relied_on": [
    {
      "memory_id": "mem_xyz...",
      "content_hash": "sha256:abc...",
      "evaluation_time": "2026-05-28T12:34:56+00:00",
      "scope": "global",
      "reliance_class": "advisory",
      "verification_mode": "local_import",
      "source_store_id": "store_..."
    }
  ]
}
```

Required: `memory_id`, `content_hash`, `evaluation_time`. Recommended optional: `scope`, `reliance_class`, `verification_mode` ∈ `{local_native, local_import, unchecked}`, `source_store_id`. The `verification_mode` field is what keeps local/imported/live/unchecked reliance from collapsing into a single category in audit.

### Verifying a receipt

Given a receipt JSON, verify locally — no source-store network calls:

```bash
contctl reliance verify path/to/receipt.json
# or
cat receipt.json | contctl reliance verify -
```

Exit code 0 if every entry is `match`, exit 2 otherwise. Per-entry status:

| Status | Meaning |
|--------|---------|
| `match` | Pinned hash matches current local content_hash; memory is committed; not expired at the cited evaluation_time |
| `content_drift` | Pinned hash differs from current local content_hash |
| `revoked_after` | Hash matches but the local memory was revoked after the citation |
| `expired_after` | Hash matches but the memory was past `expires_at` at evaluation_time |
| `missing` | The cited memory_id is not in the local store |
| `mode_mismatch` | Receipt claimed `local_import` but no `memory.import` event exists locally for this memory_id |

The same verification is available as the `memory_verify_reliance` MCP tool. Both share the same per-entry vocabulary; consumers can drive verification either via CLI for batch / out-of-band audit, or via MCP for in-session checks.

### StandingRef — worked example

**Anchoring caveat (preserve verbatim wherever this example is reproduced):**

> *Importing a Standing grant into Continuity does not make the grant valid, current, or binding. It records the relied-on artifact and lets rely/explain assess whether that artifact is still safe to cite. Standing decides standing. Continuity records relied-on state. The two stay separate.*

Worked flow:

1. **Standing produces a grant receipt.** A standing grant decision in `~/git/standing` emits a content-addressed receipt (sha256, RFC 8785 JCS). Its `digest` is the canonical artifact identity.

2. **Operator imports the grant as a continuity memory** (in workspace scope, since standing grants cross project boundaries):

   ```bash
   contctl --workspace observatory-family observe \
       --scope workspace \
       --kind constraint \
       --basis import \
       --content '{
           "grant_id": "grant_...",
           "subject_id": "claude:research",
           "action": "read",
           "target": "operator-notes",
           "state": "Activated",
           "standing_digest": "sha256:..."
       }' \
       --actor operator:jbeck
   contctl --workspace observatory-family commit MEMORY_ID \
       --reliance-class advisory \
       --actor operator:jbeck
   ```

   The reliance class is **advisory**, not actionable. Continuity is recording that the grant *was cited*, not promoting it to an enforcement gate. (Standing's own validity check is the authority surface.)

3. **A consumer tool cites the constraint memory in its own receipt.** When Wicket or any other gate processes an action that depended on this grant, its receipt's `relied_on` array carries the continuity memory_id + content_hash:

   ```json
   {
     "receipt_id": "wicket.action.xyz",
     "obligation": "ActionReceipt",
     "relied_on": [
       {
         "memory_id": "mem_grant_...",
         "content_hash": "sha256:...",
         "evaluation_time": "2026-05-28T12:00:00Z",
         "scope": "workspace",
         "reliance_class": "advisory",
         "verification_mode": "local_import",
         "source_store_id": "store_..."
       }
     ]
   }
   ```

4. **Future audit walks the citation locally:**

   ```bash
   contctl reliance verify wicket-receipt.json
   ```

   The walk confirms the constraint memory still exists locally, the content hash hasn't drifted, and the local row isn't revoked or expired. It does **not** re-evaluate the standing grant's validity — that is a separate `standing verify` against the standing CLI/store.

Continuity proves the citation; standing proves the authorization. The split is the keeper: keep church and state as two haunted buildings, not one haunted mall.

### Per-consumer integration shape

Code in each consumer repo is that repo's work — these are the recommended shapes for the cross-component-reliance convention.

| Consumer | What to cite | Where the citation lives | Verification timing |
|----------|--------------|---------------------------|---------------------|
| **Wicket** | Policy / config memories the verdict cooked against | New optional `relied_on` field on `Receipt` (alongside existing `evidence_ref_hashes`) | Operator runs `contctl reliance verify` post-hoc on the receipt; in-session checks via `memory_verify_reliance` MCP if needed |
| **Nightshift** | Gate policy / advisory closeout memories at run-horizon closure | New `relied_on` field on `RunHorizonOutcome.receipt_references` | Either at NS's own closure check or post-hoc via CLI |
| **Standing** | Optionally cite continuity memory for policy/grant provenance in receipts | New optional field on `standing-receipt` Receipt struct | Out-of-band audit; Standing itself does not consume continuity in V1 |
| **NQ** | Peer policy + query-target definition memories at remote-testimony acceptance | New `relied_on` block on `nq.receipt.v1` (when remote testimony is wired) | At ingest time via `memory_verify_reliance` MCP, or post-hoc |

Notes:
- Nightshift's live concurrent-activity-coordination wants are **out of scope** for this convention (per the keeper: continuity does not distribute the rely path). If that need surfaces as a real forcing case, file as a separate substrate gap.
- NQ's `REMOTE_SURFACE_AUTH_AND_STANDING_GAP` and `QUERY_TARGET_PRIMITIVE_GAP` are the upstream blockers for the NQ side of this convention. The continuity verification surface ships independently; NQ adopts when those land.

### Dogfooding the substrate end-to-end

The proving-ground script demonstrates the full pinned-import + citation + drift-detection loop without touching real workspace stores:

```bash
python -m scripts.dogfood_phase2 --demo-drift
```

Against real stores (operator-driven; the lesson is `basis=operator_assertion` so the principal should be you):

```bash
python -m scripts.dogfood_phase2 \
    --source-db ~/.config/continuity/workspaces/observatory-family/db.sqlite \
    --target-db /some/project/.continuity/db.sqlite \
    --actor operator:jbeck
```

The script's source is the worked example for "how a consumer would call continuity's library directly to import and cite doctrine."

## Related reading

- [`concepts.md`](concepts.md) — the mental model all three surfaces share
- [`gaps/CROSS_SCOPE_REFERENCE_GAP.md`](gaps/CROSS_SCOPE_REFERENCE_GAP.md) — substrate: cross-DB identity, content/state hash split, pinned imports
- [`gaps/CROSS_COMPONENT_RELIANCE_GAP.md`](gaps/CROSS_COMPONENT_RELIANCE_GAP.md) — doctrine: what continuity is *for* in the cross-host world
- [`gaps/ISLANDS_OF_CONTINUITY.md`](gaps/ISLANDS_OF_CONTINUITY.md) — why scope=global writes to project DBs refuse without `--allow-island`
- [`gaps/CONTINUITY_TIME_DISCIPLINE.md`](gaps/CONTINUITY_TIME_DISCIPLINE.md) — why explain/verify accept an explicit `evaluation_time`
- [`../README.md`](../README.md) — narrative onboarding
