# agent-memory

Local markdown memory for coding agents. MCP server + Cursor/Antigravity injection. No cloud.

Live identity (`memory/USER.md`, `PROJECTS.md`, `facts.md`, `scan.json`, `projects/*.md`) is **gitignored**. This repo ships the engine and empty examples.

**Coding agents:** follow [`AGENTS.md`](AGENTS.md). That file is the install spec. This README is the map.

## Setup

Same interpreter for pip and MCP:

```bash
python -m pip install -r requirements.txt
```

Fill `memory/USER.md` and `memory/scan.json` (copy from `*.example.*` if missing), then:

```bash
python sync.py --init
python inventory.py
```

`--init` does not overwrite an existing `USER.md`. It does:

- copy examples → live files **only if missing**
- write Cursor + Gemini injection and the `memory-sync` skill
- merge `agent-memory` into `~/.cursor/mcp.json` (other servers untouched; command = this Python)

If you edit `USER.md` after `--init`, run `python sync.py` again. Reload Cursor.

`scan.json` `roots` must be folders that exist (`~/Coding` is expanded; change it if that path is empty). `expand_children` = monorepo parents whose nested repos should also be tracked. `cursor_rule_name` defaults to `user-rules.mdc`.

Manual MCP fallback: `mcp.json.example`. Prefer `--init`.

## Layout

| Path | What |
|------|------|
| `AGENTS.md` | Install spec for coding agents |
| `memory/USER.md` | Always-on identity (gitignored) |
| `memory/PROJECTS.md` | slug / path / role / stack / status |
| `memory/projects/<slug>.md` | Per-project facts |
| `memory/facts.md` | Global captured facts |
| `memory/scan.json` | Scan roots, ignore list, Cursor rule filename |
| `mcp_server.py` | MCP: search / add / register / inventory / sync |
| `inventory.py` | Disk vs `PROJECTS.md` |
| `sync.py` | Rewrite Cursor rules + Gemini `AGENTS.md` |

## Scripts

From this repo root (installed skill uses absolute paths):

```bash
python inventory.py
python inventory.py --json
python inventory.py --register SLUG "/path/to/repo" "role" "stack"
python inventory.py --ignore SLUG
python sync.py
```

## Existing install

If `memory/USER.md` already exists, `--init` does not overwrite it. Sync still refreshes injection, the user-level skill, and the MCP entry.
