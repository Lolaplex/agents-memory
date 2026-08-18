---
name: memory-sync
description: Audits and updates local agent memory. Scans configured coding folders, registers or ignores new projects, writes PROJECTS.md, syncs Cursor rules and Antigravity AGENTS.md. Use when the user says Bestandaufnahme, memory sync, neues Projekt, inventory, Projekte updaten, register project, or wants agents to know a new repo path.
---

# memory-sync

Local markdown memory. Not cloud.

## Paths

<!-- agent-memory-paths -->
This clone. Live store: `memory/`. Scripts from the agent-memory repo root:

```powershell
python inventory.py
python inventory.py --json
python sync.py
```

Register:

```powershell
python inventory.py --register SLUG "C:\path\to\repo" "role here" "stack here"
```

New folders: whatever `memory/scan.json` lists under `roots`. Cursor rule filename: `cursor_rule_name` in that file (default `user-rules.mdc`).
<!-- /agent-memory-paths -->

| File | What |
|------|------|
| `USER.md` | Identity, talk style, stack, ALWAYS/NEVER |
| `PROJECTS.md` | slug / path / role / stack / status |
| `projects/<slug>.md` | Project facts |
| `facts.md` | Global captured facts |
| `scan.json` | Roots, ignore list, Cursor rule name |

MCP server `agent-memory`: `inventory_projects`, `register_project`, `ignore_project`, `add_memory`, `search_memory`, `get_project_memories`, `sync_local_agents_md`, `list_projects`.

## When this skill fires

- User asks for Bestandaufnahme / inventory / memory sync / Projekte updaten
- User (or you) created a **new folder** under a `scan.json` root
- A path in `PROJECTS.md` is wrong or missing
- After editing `USER.md` or `PROJECTS.md` by hand → always `sync.py`

## Bestandaufnahme workflow

1. Run `inventory.py` (or MCP `inventory_projects`).
2. Show the user a tight list:
   - **unknown**: on disk, not in memory
   - **missing**: in memory, path gone
3. For each **unknown**, ask (or infer if obvious):
   - **add** → role + stack (one line each)
   - **ignore** → never list again (`ignore_project` / `--ignore SLUG`)
   - **skip** → leave for later
4. Register adds write `PROJECTS.md`, `projects/SLUG.md`, then sync injection files.
5. For **missing**: confirm delete from `PROJECTS.md` or fix the path. Do not guess a new path.
6. Run `sync.py` if you edited markdown by hand.
7. Tell the user: Cursor/Antigravity pick up MCP + rules after reload if the server name changed.

## New project while coding (no full audit)

If you scaffold a repo under a scan root:

1. `register_project` immediately (slug, absolute path, role, stack).
2. Do not wait for the user to remember. If role is unclear, register as `unclassified` and ask one question.
3. Never leave a new repo off `PROJECTS.md`. The always-on map is useless if it is stale.

## Edit rules

- Durable identity → `USER.md` then `sync.py`
- Durable project fact → `add_memory(fact, project="slug")` or edit `projects/<slug>.md`
- Do not copy secrets, tokens, SSH keys, or `.env` values into memory
- Do not overwrite a repo root `AGENTS.md` unless it contains `<!-- agent-memory-sync -->`
- Per-repo always-on file is `.cursor/rules/<cursor_rule_name>` (generated)

## Off / parked

Empty or spec-only folders stay in the table with `status: parked` so inventory does not nag. Ignore only if the folder should never be a project.
