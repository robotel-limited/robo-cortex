---
name: Feature request
about: Propose a new capability for robo-cortex
title: ''
labels: enhancement
assignees: ''
---

**What problem does this solve?**

Describe the concrete situation where robo-cortex's current behavior falls short — not just the feature itself.

**Proposed behavior**

**Have you checked ROADMAP.md?**

Several candidates (an instruction-file auto-importer, AST-level staleness anchoring, a `prune` command, a code decorator, a CI-gate subcommand) have already been evaluated there, with reasons for or against. If your idea overlaps, link the relevant section and say what's changed.

**Does this need a new dependency?**

robo-cortex is deliberately stdlib + SQLite only (the `mcp` extra is the one exception). A feature that requires a new third-party dependency needs a stronger justification than one that doesn't.
