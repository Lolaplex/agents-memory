# Agent profile

Live store: `memory/` in this clone (`USER.md`, `PROJECTS.md`, `projects/`).
Projects: `PROJECTS.md`. Details: `projects/<slug>.md`.
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
- Identity + project map live in this folder. They are synced into Cursor rules and `~/.gemini/config/AGENTS.md`.
- Capture durable facts with `add_memory` (MCP) or by editing the markdown.
- New repo under `scan.json` roots → skill `memory-sync` or MCP `register_project`. Unlisted projects make this map useless.
- Periodic audit: skill `memory-sync` / `inventory.py`.

## ALWAYS / NEVER
- ALWAYS inspect existing files/types before generating code.
- ALWAYS register new projects in this memory, then sync.
- NEVER comment out failing tests to go green.
