---
slug: lolaplex-board
status: implemented
---

# Attach writes the registered clone only

Board memory attach pulls into `<repo>/.agents/memory/` for a **registered** project. There is no `~/.agents/shared/` or `memory/shared/` shadow tree. Unregistered slugs fail until `register_project`.

`.agents/` is gitignored. Do not `connect` the personal store to the board.
