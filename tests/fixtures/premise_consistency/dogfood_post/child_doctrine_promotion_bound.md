---
name: doctrine-promotion-bound
description: "Doctrine promotion across projects (post-correction framing)."
metadata:
  node_type: memory
  type: project
---

When a lesson generalizes across projects, the importing project must wire a local stub that instantiates the rule at the entrypoint. Recognition is binding, not advisory: the hook is the mechanism, and the lint check enforces that the wiring exists.

Premises: [[consultation-must-be-load-bearing]]. The premise requires consultation to be load-bearing; this memory inherits that obligation and is bound by it. Each adopting project installs the stub and the hook; the lint surfaces missing wiring as a flag, not a suggestion.
