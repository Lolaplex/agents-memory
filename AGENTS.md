# Agent install (this repo)

You are installing **local agent memory** for the human. Do every step yourself. Do not dump a command list for them to run.

`CLAUDE.md` at this repo root **git-symlinks** this file (DeepSeek pattern). Edit `AGENTS.md` only. On Windows without symlink privilege the checkout is a 9-byte stub; `python sync.py` binds `CLAUDE.md` (hardlink or symlink with Developer Mode). Installed always-on: `~/.agents/AGENTS.md`; Gemini, Zed, and `~/.claude/` bind to it. Foreign `~/.claude/CLAUDE.md` is replaced on sync — back it up first. See `memory/PLATFORM.md`.

Live store is **`~/.agents/memory`** (user) plus **`<repo>/.agents/memory`** (project). Never commit those live files. This clone's `memory/*.example.*` are templates only.

## Procedure

1. Install deps with the same interpreter you will keep using:
   - `python -m pip install -r requirements.txt`
   - Windows: `py -3` is fine if that is what Cursor uses. macOS/Linux: `python3` if `python` is missing.
2. First `sync.py` copies examples into `~/.agents/memory` if missing, and migrates any leftover clone `memory/USER.md` etc.
3. **Ask the human once** (one short question batch):
   - name / work
   - how agents should talk
   - stack defaults
   - which folders hold their repos (absolute paths or `~/...`)
   - any monorepo parents whose *child* repos should also be tracked → `expand_children`
4. Write `~/.agents/memory/USER.md` (real identity, not empty `Name:`) and `scan.json` (`roots` must exist on disk). `cursor_rule_name` default `user-rules.mdc` is fine.
5. Run `python sync.py --init` from this repo root.
   - Copies examples only if live files are missing (never overwrites filled `USER.md`).
   - Writes Cursor user rule + canonical `~/.agents/AGENTS.md` with `CLAUDE.md` bound to it (Gemini, `~/.claude/AGENTS.md`, this clone `.agents/`) + `memory-sync` skill.
   - Ensures each registered repo has `.agents/memory/` (staging, research, sequential plans/tasks/waves/roadmap/decisions, lifecycle notes) and `projects/<slug>/README.md` as a link.
   - Merges `agent-memory` into `~/.cursor/mcp.json` using **this** Python (`sys.executable`). Other MCP servers stay.
   - Copies Cursor + Antigravity MCP servers into Zed `context_servers` and mirrors user skills into `~/.agents/skills`.
6. Run `python inventory.py`. For each **unknown** folder: register (slug, path, role, stack) or `--ignore`. For **missing**: ask before deleting.
7. Run `python ingest_chats.py` to (re)build `~/.agents/memory/chats-index.md` from ChatGPT export, Cursor, VS Code, Antigravity, and Pi. Titles + paths only. Optional: `python extract_openai.py` unzip+filter the ChatGPT zip (staging in `%TEMP%`, not always-on). Distill with MCP `add_memory(kind=..., name=...)`.
8. If you edited `USER.md` / `scan.json` *after* `--init`, run `python sync.py` again.
9. Tell the human **one** thing: reload Cursor and Zed (MCP). You cannot do that for them.

## Done when

- `~/.cursor/mcp.json` has `mcpServers.agent-memory` pointing at this clone's `mcp_server.py`
- `~/.agents/memory/USER.md` is not the blank example
- `~/.agents/memory/chats-index.md` exists
- `inventory.py` is clean or leftovers were explicitly ignored
