# Cross-platform notes (agent-memory)

Read this before installing on a new OS or sharing the tool.

## Instruction files (`AGENTS.md` / `CLAUDE.md`)

| Platform | Git clone of agent-memory | Installed homes after `sync.py` |
|----------|---------------------------|----------------------------------|
| **macOS / Linux** | `CLAUDE.md` git-symlink works | symlink → hardlink → copy |
| **Windows + Developer Mode** | symlink works after clone | same |
| **Windows without symlink privilege** | `CLAUDE.md` may be a **9-byte stub** (`AGENTS.md`) — run `sync.py` | hardlink to `~/.agents/AGENTS.md` (no drift) |
| **exFAT / network drives** | stub risk as above | may fall back to **copy** — sync prints `WARN`; edits to AGENTS.md alone |

Binding order: **symlink → hardlink → copy**. Copy is last resort and can drift if you edit only one file.

`~/.claude/AGENTS.md` and `~/.claude/CLAUDE.md` are bound to `~/.agents/AGENTS.md` on sync. A foreign `~/.claude/CLAUDE.md` (another tool) is **replaced** — back it up first if you still need it.

## Paths (not Windows-only)

- Live store: `~/.agents/memory` via `Path.home()` — works everywhere.
- Zed config: `%APPDATA%/Zed` on Windows, `$XDG_CONFIG_HOME/zed` or `~/.config/zed` elsewhere.
- VS Code Copilot chats: `%APPDATA%/Code/...` on Windows, `~/.config/Code/...` on Linux.
- `scan.json` roots: use paths that exist on **that** machine (absolute or `~/...`).

## Chat ingest (`ingest_chats.py`)

Machine-specific paths (Cursor, VS Code, Antigravity, OpenAI export zip) are hardcoded for Fabian's layout. On another machine, edit `ingest_chats.py` / export path or rely on MCP `add_memory` after manual distill.

## Memory mutability (all platforms)

| Kind | How it changes |
|------|----------------|
| `staging/`, `scratch/` | Append inbox bullets → distill → delete |
| `plans/` `tasks/` `waves/` `roadmap/` | New `001-` file per tranche; edit current plan/tasks in place; archive old plan |
| `research/` | Revise topical file when input changes |
| `notes/implemented/` | **Revise in place** when shipped code changes |
| `notes/rejected/` | Frozen |
| `decisions/` | Revise contract in place; new number when superseding |
| `concepts/` `entities/` `workflows/` | One home per idea; edit or append deliberately |

`add_memory` appends. For revise-in-place kinds, edit the markdown file when updating facts — do not only stack bullets.
