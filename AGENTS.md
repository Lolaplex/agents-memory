# Agent install (this repo)

You are installing **local agent memory** for the human. Do every step yourself. Do not dump a command list for them to run.

`CLAUDE.md` at this repo root is a **git symlink** to this file — edit `AGENTS.md` only. Sync does not rewrite engine-root `CLAUDE.md` (installed always-on lives in `~/.agents/`). On Windows without symlink privilege the checkout may be a short stub; enable Developer Mode or recreate the symlink from git. Installed always-on: `~/.agents/AGENTS.md`; Gemini, Zed, and `~/.claude/` bind to it. Foreign `~/.claude/CLAUDE.md` is replaced on sync — back it up first. See `abi/PLATFORM.md`.

Live store is **`~/.agents/memory`** (user) plus **`<repo>/.agents/memory`** (project). Never commit those live files. This clone's `examples/*.example.*` are scaffolding only. Run `python -m agents_memory consolidate` if live markdown leaked into `memory/` or `examples/`.

Python is a package: `src/agents_memory/`. After `pip install -e .`, use `python -m agents_memory` (or `agents-memory` on PATH).

## Procedure

1. Install with the same interpreter you will keep using:
   - `python -m pip install -e .`
   - Windows: `py -3` is fine if that is what your Agent uses. macOS/Linux: `python3` if `python` is missing.
2. First `python -m agents_memory sync --init` copies examples into `~/.agents/memory` if missing, and runs `consolidate_repo_leaks()` so nothing live stays in this clone.
3. **Ask the human once** (one short question batch):
   - name / work
   - how agents should talk
   - stack defaults
   - which folders hold their repos (absolute paths or `~/...`)
   - any monorepo parents whose *child* repos should also be tracked → `expand_children`
4. Write `~/.agents/memory/USER.md` (real identity, not empty `Name:`) and `scan.json` (`roots` must exist on disk). `agent_rule_name` default `user-rules.mdc` is fine.
5. Run `python -m agents_memory sync --init` from this repo root.
   - Copies examples only if live files are missing (never overwrites filled `USER.md`).
   - Writes your Agent always-on inject + canonical `~/.agents/AGENTS.md` with `CLAUDE.md` bound to it (Gemini, `~/.claude/AGENTS.md`). Does **not** create `.agents/` or `.cursor/` inside this engine clone.
   - Ensures each registered repo has `.agents/memory/` **files only** (`README.md`, `staging/captured.md`) and `projects/<slug>/README.md` as a link. No empty subfolders. No `.cursor/` in repos (scan skips `.cursor`).
   - Merges `agents-memory` into host MCP config (`~/.cursor/mcp.json` when your Agent uses it) using **this** Python (`sys.executable -m agents_memory.mcp_server`). Other MCP servers stay.
   - Merges host MCP servers into Zed `context_servers` and mirrors user skills into `~/.agents/skills`.
6. Run `python -m agents_memory inventory`. For each **unknown** folder: register (slug, path, role, stack) or `--ignore`. For **missing**: ask before deleting.
7. Run `python -m agents_memory ingest catalog` to (re)build `~/.agents/memory/chats-index.md` from local chat stores (Open AI GDPR export, Cursor, VS Code, Antigravity, Pi, …). Titles + paths only. Optional: `python -m agents_memory ingest extract` (Python filters → staging). Distill with MCP `distill_batch` / skill `memory-distill`.
8. If you edited `USER.md` / `scan.json` *after* `--init`, run `python -m agents_memory sync` again.
9. Tell the human **one** thing: reload your Agent (MCP). You cannot do that for them.

## Done when

- Host MCP config has `mcpServers.agents-memory` with `args: ["-m", "agents_memory.mcp_server"]`
- `~/.agents/memory/USER.md` is not the blank example
- `~/.agents/memory/chats-index.md` exists
- `python -m agents_memory inventory` is clean or leftovers were explicitly ignored
