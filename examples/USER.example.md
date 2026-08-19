# Agent profile

Live store: `~/.agents/memory` (user) and `<repo>/.agents/memory` (project).
Projects: `PROJECTS.md`. Links: `projects/<slug>/`. In-tree: `.agents/memory/` (staging inbox, sequential work, decisions, lifecycle notes).
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
- Identity + project map live in `~/.agents/memory`. They are synced into your Agent always-on inject and `~/.gemini/config/AGENTS.md`.
- Capture with `add_memory` (kind + name + collection). No `facts.md`.
- Project-local research/plans/tasks/waves/roadmap/decisions live in `<repo>/.agents/memory/`. Staging is inbox only.
- `AGENTS.md` is the real instruction file; `CLAUDE.md` is bound to it.
- Chat titles: `python -m agent_memory ingest catalog` → `chats-index.md`. Bodies stay in product folders.
- New repo under `scan.json` roots → skill `memory-sync` or MCP `register_project`. Unlisted projects make this map useless.
- Periodic audit: skill `memory-sync` / `python -m agent_memory inventory`.

## ALWAYS / NEVER
- ALWAYS inspect existing files/types before generating code.
- ALWAYS register new projects in this memory, then sync.
- NEVER comment out failing tests to go green.
