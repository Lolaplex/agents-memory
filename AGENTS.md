# Agent install (this repo)

You are installing **local agent memory** for the human. Do every step yourself. Do not dump a command list for them to run.

Never commit `memory/USER.md`, `PROJECTS.md`, `facts.md`, `scan.json`, `projects/*.md`, or `memory-bootstrap/`.

## Procedure

1. Install deps with the same interpreter you will keep using:
   - `python -m pip install -r requirements.txt`
   - Windows: `py -3` is fine if that is what Cursor uses. macOS/Linux: `python3` if `python` is missing.
2. If `memory/USER.md` or `memory/scan.json` do not exist, they appear on first `sync.py` from the `*.example.*` files. You may copy them yourself first.
3. **Ask the human once** (one short question batch):
   - name / work
   - how agents should talk
   - stack defaults
   - which folders hold their repos (absolute paths or `~/...`)
   - any monorepo parents whose *child* repos should also be tracked → `expand_children`
4. Write `memory/USER.md` (real identity, not empty `Name:`) and `memory/scan.json` (`roots` must exist on disk). `cursor_rule_name` default `user-rules.mdc` is fine.
5. Run `python sync.py --init` from this repo root.
   - Copies examples only if live files are missing (never overwrites filled `USER.md`).
   - Writes Cursor user rule + `~/.gemini/config/AGENTS.md` + `~/.cursor/skills/memory-sync`.
   - Merges `agent-memory` into `~/.cursor/mcp.json` using **this** Python (`sys.executable`). Other MCP servers stay.
   - If merge fails (invalid JSON), fix or insert the printed snippet; do not overwrite the whole file blindly.
6. Run `python inventory.py`. For each **unknown** folder: register (slug, path, role, stack) or `--ignore`. For **missing**: ask before deleting.
7. If you edited `USER.md` / `scan.json` *after* `--init`, run `python sync.py` again.
8. Tell the human **one** thing: reload Cursor (MCP). You cannot do that for them.

## Done when

- `~/.cursor/mcp.json` has `mcpServers.agent-memory` pointing at this clone's `mcp_server.py`
- `~/.cursor/rules/<cursor_rule_name>` exists
- `inventory.py` is clean or leftovers were explicitly ignored
- `USER.md` is not the blank example
