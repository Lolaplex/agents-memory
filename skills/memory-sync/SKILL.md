---
name: memory-sync
description: Audits and updates local agent memory. Scans configured coding folders, registers or ignores new projects, writes PROJECTS.md, syncs Cursor/Antigravity/Zed injection. Use when the user says Bestandaufnahme, memory sync, neues Projekt, inventory, Projekte updaten, register project, or wants agents to know a new repo path.
---

# memory-sync

Local markdown memory. Not cloud.

## Paths

<!-- agent-memory-paths -->
User memory: `~/.agents/memory`. Project memory: `<repo>/.agents/memory`.
<!-- /agent-memory-paths -->

| File | What |
|------|------|
| `~/.agents/memory/USER.md` | Identity, talk style, stack, ALWAYS/NEVER |
| `~/.agents/memory/PROJECTS.md` | slug / path / role / stack / status |
| `~/.agents/memory/concepts/` | Ideas |
| `~/.agents/memory/entities/` | Named things |
| `~/.agents/memory/workflows/` | Procedures |
| `~/.agents/memory/projects/<slug>/` | Link to a real tree (not a second copy) |
| `~/.agents/memory/notes/<collection>/` | Personal notes. Guide: projects, interests, education, finance, family, preferences, programming, work, certifications, scratch — **not a closed set** |
| `<repo>/.agents/memory/staging/` | Inbox only (`captured.md`, `from-chats.md`). Distill, then empty. |
| `<repo>/.agents/memory/` | research (input); `plans/` `tasks/` `waves/` `roadmap/` `decisions/` as `001-topic.md`; `notes/proposed\|implemented\|rejected/<class>/` |
| `~/.agents/AGENTS.md` | Canonical always-on (USER + PROJECTS). `CLAUDE.md` is bound to it. |
| `~/.agents/memory/chats-index.md` | Chat title catalog |
| `~/.agents/memory/scan.json` | Roots, ignore list, Cursor rule name |

MCP server `agent-memory`: `inventory_projects`, `register_project`, `ignore_project`, `add_memory` (kind+name, collection=, or project=), `search_memory`, `get_project_memories`, `sync_local_agents_md`, `list_projects`.

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
4. Register adds write `PROJECTS.md`, `projects/<slug>/README.md` (link), and `<repo>/.agents/memory/` folders, then sync injection (`AGENTS.md` with `CLAUDE.md` bound to it).
5. For **missing**: confirm delete from `PROJECTS.md` or fix the path. Do not guess a new path.
6. Run `sync.py` if you edited markdown by hand.
7. Tell the user: Cursor / Antigravity / Zed pick up MCP + rules after reload if the server name changed.

## New project while coding (no full audit)

If you scaffold a repo under a scan root:

1. `register_project` immediately (slug, absolute path, role, stack).
2. Do not wait for the user to remember. If role is unclear, register as `unclassified` and ask one question.
3. Never leave a new repo off `PROJECTS.md`. The always-on map is useless if it is stale.

## Edit rules

- Durable identity → `~/.agents/memory/USER.md` then `sync.py`
- Idea → MCP `add_memory(kind="concept"|"entity", name="stem")`
- Procedure → `add_memory(kind="workflow", name="stem")`
- Project **link** → `add_memory(kind="project", name="slug")` writes `projects/<slug>/README.md` pointing at the real tree
- Ordered work → `kind="plans"|"tasks"|"waves"|"roadmap"` with `project=` → `001-topic.md`
- ADR / claimed contract → `kind="decision"|"adr"` → `decisions/001-title.md`
- In-flight design note → `kind="proposed"|"implemented"|"rejected"`, `collection=` class (`architecture` default). **implemented** and **decisions** = revise the file in place when shipped reality changes; **rejected** = frozen.
- Research (input) → `kind="research"` — revise topical file when input changes
- Inbox → `project=` alone or `kind="staging"` → `staging/captured.md`. Distill, then delete the bullet.
- Personal note → `add_memory(kind="note", name="stem", collection="interests"|…)` or `project="slug"` for `notes/projects/<slug>/`
- Throw-away → `kind="scratch"`
- No `facts.md`. Path encodes the home.
- Chat titles → `python ingest_chats.py`. ChatGPT bodies → `python extract_openai.py` then distill out of staging
- `AGENTS.md` is the real file. `CLAUDE.md` is bound to it (symlink → hardlink → copy). Edit `AGENTS.md`. See `memory/PLATFORM.md` for Windows vs macOS/Linux.
- `sync.py` replaces foreign `~/.claude/CLAUDE.md` — back up first if another tool wrote it.
- Do not copy secrets, tokens, SSH keys, emails, phones, or `.env` values into memory
- Do not overwrite a repo root `AGENTS.md` unless it contains `<!-- agent-memory-sync -->`

## Off / parked

Empty or spec-only folders stay in the table with `status: parked` so inventory does not nag. Ignore only if the folder should never be a project.
