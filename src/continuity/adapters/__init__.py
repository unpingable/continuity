"""Adopter-side integration modules.

Adapters wire continuity's library primitives into adopter-specific
ingest paths. They are library-only — no CLI, no MCP, no transport
surface. Each adapter's gap-spec carries the load-bearing invariants
the adapter enforces.

See:
  - docs/gaps/WLP_PERSISTENCE_ADAPTER_GAP.md — WLP persistence adapter
"""
