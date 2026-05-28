---
name: rule-with-hook
description: "Rule that ships an enforcement hook."
metadata:
  node_type: memory
  type: project
---

The rule is binding and must be enforced by the project. Each project shall install the lint hook that instantiates the rule on its entrypoint. The wiring is what gives the rule force; without the hook the rule is decoration.
