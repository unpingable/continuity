# continuity — docs

A map of this directory. Start from the top if you're new.

## Read this first

1. [`../README.md`](../README.md) — narrative onboarding: why this exists and what it does
2. [`concepts.md`](concepts.md) — canonical mental model and vocabulary; the constitution
3. [`integrations.md`](integrations.md) — how to talk to continuity (MCP, CLI, library)
4. [`gaps/`](gaps/) — proposed doctrine for architectural shifts

## Contents

| Path | What's there |
|------|--------------|
| [`concepts.md`](concepts.md) | Core model (observe/commit/rely), scope and identity, cross-cutting invariants, what continuity is *not* |
| [`integrations.md`](integrations.md) | MCP server, `contctl` CLI, and Python library — each as a reference, with minimal examples and entry points |
| [`gaps/`](gaps/) | Gap specs: proposed doctrine for load-bearing architectural or storage shifts, before implementation |

## Agent instruction files (not in this directory)

| File | Audience | Role |
|------|----------|------|
| [`../CLAUDE.md`](../CLAUDE.md) | Claude Code | Full operational context, build details, conventions |
| [`../AGENTS.md`](../AGENTS.md) | Codex and future agents | Travel guide: quick start, safety, invariants |

These are short operational briefings. The canonical *model* lives in [`concepts.md`](concepts.md); the instruction files can point at it rather than redefining terms.
