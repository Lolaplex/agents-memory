# Agent profile

Live store: `~/.agents/memory` (user) and `<repo>/.agents/memory` (project).
Projects: `PROJECTS.md`. Details: `<repo>/.agents/memory/facts.md`.
MCP: `agent-memory`. Skill: `memory-sync`.

## Who
- Name:
- Work:

## Talk & run
- Dense, direct. Agent runs everything it can (terminal, installs, edits, verify).
- Never ask the user to run a command the agent can run. If a manual step is unavoidable: one short copy-paste command.

## Stack defaults
- OS, shell, package managers, languages, UI defaults — fill in.

## Memory (local, not cloud)
- Identity + project map live in `~/.agents/memory`. They are synced into Cursor rules and `~/.gemini/config/AGENTS.md`.
- Capture durable facts with `add_memory` (MCP). Project facts go to `<repo>/.agents/memory/facts.md`.
- Chat titles: `ingest_chats.py` → `chats-index.md`. Bodies stay in product folders.
- New repo under `scan.json` roots → skill `memory-sync` or MCP `register_project`. Unlisted projects make this map useless.
- Periodic audit: skill `memory-sync` / `inventory.py`.

## ALWAYS / NEVER
- ALWAYS inspect existing files/types before generating code.
- ALWAYS register new projects in this memory, then sync.
- NEVER comment out failing tests to go green.
