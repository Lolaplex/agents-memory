# agent-memory

Local markdown memory for coding agents. MCP server + Cursor / Antigravity / Zed injection. No cloud.

Live files live under **`~/.agents/memory`** (user) and **`<repo>/.agents/memory`** (project). This repo ships the engine and `memory/*.example.*` templates.

**Coding agents:** follow [`AGENTS.md`](AGENTS.md). That file is the install spec. This README is the map.

## Layout

Same split as skills: one user folder, one folder per repo, one search across both.

| Path | What |
|------|------|
| `~/.agents/memory/USER.md` | Always-on identity |
| `~/.agents/memory/PROJECTS.md` | slug / path / role / stack / status |
| `~/.agents/memory/concepts/` | Reusable ideas |
| `~/.agents/memory/entities/` | Named people, orgs, products, machines |
| `~/.agents/memory/workflows/` | Procedures |
| `~/.agents/memory/projects/<slug>/` | Link to a real tree (README has `path`) |
| `~/.agents/memory/notes/<collection>/` | Personal notes (projects, interests, education, finance, family, preferences, programming, work, certifications, scratch) |
| `~/.agents/memory/chats-index.md` | Chat titles + paths (not bodies) |
| `<repo>/.agents/memory/` | `staging/` (inbox); research; `plans/` `tasks/` `waves/` `roadmap/` `decisions/` as `001-topic.md`; `notes/proposed\|implemented\|rejected/<class>/` |
| `~/.agents/AGENTS.md` | Canonical always-on. `CLAUDE.md` is bound to it. |
| `mcp_server.py` | MCP: search / add (kind+name+collection) / register / inventory / sync |
| `ingest_chats.py` | Rebuild the chat title index |
| `extract_openai.py` | Unzip ChatGPT export; keep durable user lines only |
| `inventory.py` | Disk vs `PROJECTS.md` |
| `sync.py` | Canonical `~/.agents/AGENTS.md`, bound `CLAUDE.md` siblings, Cursor rules, Zed MCP |

Retrieval is overarching: `search_memory` unions the user store and every registered project's `.agents/memory`. Always-on injection stays short (USER + PROJECTS only). `projects/<slug>/` is a **link** to the real tree, not a second copy. Note collections under `notes/` are a guide, not a closed set.

`AGENTS.md` is the real instruction file. `CLAUDE.md` is bound to it (git symlink in this repo; installed: symlink, else hardlink, else copy). Staging files are an inbox, not memory.

Chat *bodies* stay in Cursor / VS Code / Antigravity / Pi / ChatGPT export folders.

## Setup

Same interpreter for pip and MCP:

```bash
python -m pip install -r requirements.txt
```

Fill `~/.agents/memory/USER.md` and `scan.json` (copied from `memory/*.example.*` on first run), then:

```bash
python sync.py --init
python inventory.py
python ingest_chats.py
python extract_openai.py
```

`--init` does not overwrite an existing `USER.md`. It does:

- copy examples → `~/.agents/memory` **only if missing**
- migrate a leftover clone `memory/` live store into `~/.agents/memory` once
- write Cursor + Gemini + Zed injection and the `memory-sync` skill
- merge `agent-memory` into `~/.cursor/mcp.json` (other servers untouched; command = this Python)
- merge Cursor + Antigravity MCP servers into Zed `context_servers`

If you edit `USER.md` after `--init`, run `python sync.py` again. Reload Cursor / Zed.

In-tree project memory is gitignored (`.agents/memory/.gitignore`) so it stays local unless you force-add it.

## Cross-platform

See [`memory/PLATFORM.md`](memory/PLATFORM.md). Summary:

- **Windows:** enable Developer Mode if you want real symlinks; otherwise `sync.py` uses hardlinks (same inode, no drift). A git clone without either may show a 9-byte `CLAUDE.md` stub — run `sync.py`.
- **All OS:** binding order is symlink → hardlink → copy. Copy warns because it can drift.
- **`~/.claude/CLAUDE.md`:** replaced on sync if it is not ours — back up foreign files first.
- **`scan.json` / ingest paths** are per-machine; edit for your layout.

## Scripts

From this repo root (installed skill uses absolute paths):

```bash
python inventory.py
python inventory.py --json
python inventory.py --register SLUG "/path/to/repo" "role" "stack"
python inventory.py --ignore SLUG
python ingest_chats.py
python extract_openai.py
python sync.py
```
