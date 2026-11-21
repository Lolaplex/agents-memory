# Hooks provenance

Template hook set. Lineage:

1. `commit-msg.cjs` from `korulang/koru` (World Model + Membrane).
2. Universal `## Gates`, git wall, and signal ledger from `Lolaplex/klanker` /
   `Lolaplex/agents-board` @ dev (`695d12c`).

This repo is the **upstream owner** (D2). Consumers pin `hooks/` through
`origins.lock` and run drift CI.

Install: `bash hooks/install.sh` — sets `git config core.hooksPath hooks`.