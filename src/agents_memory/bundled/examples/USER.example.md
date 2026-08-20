# Agent profile

Live store: `~/.agents/memory` (user) and `<repo>/.agents/memory` (project).
Projects: `PROJECTS.md`. Links: `projects/<slug>/`. In-tree: `.agents/memory/` (staging inbox, sequential work, decisions, lifecycle notes).
MCP: `agents-memory`. Skill: `memory-sync`.

## Who
- Name:
- Work:

## Talk & run
- Dense, direct. Agent runs everything it can (terminal, installs, edits, verify).
- Never ask the user to run a command the agent can run. If a manual step is unavoidable: one short copy-paste command.

## Stack defaults
- OS, shell, package managers, languages, UI defaults — fill in.

## Memory (local, not cloud)
- Identity + project map live in `~/.agents/memory`. Synced into Cursor rules, Antigravity `AGENTS.md`, and Zed `%APPDATA%/Zed/AGENTS.md`.
- **Proactive capture:** ALWAYS call `add_memory` (MCP) immediately when user reveals durable preferences, project standards, architecture decisions (ADRs), or global rules. Do not wait for explicit user prompt to save.
- **Context retrieval:** Call `search_memory` or `get_project_memories` before guessing project architecture, past decisions, or user preferences.
- Project-local research/plans/tasks/waves/roadmap/decisions live in `<repo>/.agents/memory/`. Staging is inbox only.
- Chat titles: `python -m agents_memory ingest catalog` → `chats-index.md`. Bodies stay in product folders.
- New repo under `scan.json` roots → skill `memory-sync` or MCP `register_project`. Unlisted projects make this map useless.
- Periodic audit: skill `memory-sync` / `python -m agents_memory inventory`.

## ALWAYS / NEVER
- NEVER overengineer. Simplest, cleanest, fastest solution wins.
- NEVER comment out failing tests to go green.
- ALWAYS inspect existing files/types before generating code.
- ALWAYS register new projects in this memory, then sync.

