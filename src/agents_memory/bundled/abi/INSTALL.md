# Install and injection

What `python -m agents_memory sync` and `python -m agents_memory inventory` write, merge, and bind. For CLI flags use **`--help-json`** (derived from argparse, cannot drift):

```bash
python -m agents_memory --help-json
python -m agents_memory sync --help-json
python -m agents_memory inventory --help-json
```

MCP tools: [`MCP.md`](MCP.md).

## Inventory scan skips `.agents` and `.cursor`

`scan.json` `ignore_dir_names` includes **`.agents`** and **`.cursor`**. Inventory walks repo roots but does not treat those folders as projects. Sync does **not** create `.cursor/` inside registered repos — only **files** under `<repo>/.agents/` (README + bound AGENTS/CLAUDE). No empty folder trees.

## Shipped vs generated

| Artifact | Where | How it changes |
|----------|-------|----------------|
| `abi/*.md` | Engine repo | Edit in git; version in `abi/VERSION` |
| `~/.agents/memory/LAYOUT.md` | Live user store | **Copied** from `abi/LAYOUT.md` on sync |
| `~/.agents/AGENTS.md` | User home | **Generated** from `USER.md` + `PROJECTS.md` |
| Always-on rule | `~/.agents/rules/<name>.mdc` | **Generated** from USER + PROJECTS; hosts bind here |
| Per-repo `.agents/AGENTS.md` | Registered repos | **Generated** project slice + README only |
| `memory-sync` skill | host skill dirs + `~/.agents/skills` | **Generated** from template + machine path block |
| Host MCP config | e.g. `~/.cursor/mcp.json` | **Merged** on `python -m agents_memory sync --init` |

No roff man page. Use `--help-json` instead of scraping `--help` or README.

## First install

```bash
python -m pip install -e .
# fill ~/.agents/memory/USER.md and scan.json (from examples/*.example.*)
python -m agents_memory consolidate
python -m agents_memory sync --init
python -m agents_memory inventory
```

`--init` runs layout ensure, global + per-repo `.agents` inject, skill install, MCP merge. Reload your Agent after.

## `python -m agents_memory sync`

| Flag | Effect |
|------|--------|
| *(default)* | `ensure_memory_layout()` + rewrite injection (global + registered repos) |
| `--init` | above + merge host MCP config + Zed `context_servers` |
| `--no-repos` | skip per-repo `.agents/` inject |

Re-run after editing `USER.md`, `PROJECTS.md`, or `scan.json`.

## `python -m agents_memory inventory`

| Flag | Effect |
|------|--------|
| *(default)* | Print unknown / missing folders vs `PROJECTS.md` |
| `--json` | Machine-readable report |
| `--register SLUG PATH ROLE STACK` | Add project, bootstrap `.agents/memory/` **files only**, sync inject |
| `--ignore SLUG` | Add to `scan.json` ignore_slugs |
| `--sync` | Rewrite injection after audit |
| `--no-repos` | With `--sync`, global inject only |

## Injection targets (sync)

**Always-on (user):**

- `~/.agents/AGENTS.md` ← `USER.md` + `PROJECTS.md`
- `~/.agents/CLAUDE.md` bound to AGENTS
- `~/.agents/rules/<agent_rule_name>.mdc` ← USER + PROJECTS (canonical)
- Host rule slots (e.g. `~/.cursor/rules/`) **bound** to the canonical rule on sync
- Gemini / Zed / `~/.claude/` — AGENTS/CLAUDE bound to canonical

**Per registered repo** (path must exist):

- `projects/<slug>/README.md` in user store (link)
- `<repo>/.agents/memory/README.md` + `staging/captured.md` only (no empty subfolders)
- `<repo>/.agents/AGENTS.md` + bound `CLAUDE.md` (if not foreign)

**Skills:**

- Installs `memory-sync` to your Agent skill dirs and `~/.agents/skills`
- Mirrors other user skills into `~/.agents/skills` (copy if missing)

**MCP merge (`--init` only):**

- Host MCP JSON → `mcpServers.agents-memory` = this Python + `-m agents_memory.mcp_server`
- Zed `settings.json` → union of host MCP configs as `context_servers`

## Marker and foreign files

Generated files include `<!-- agents-memory-sync -->`.

- Repo-root `AGENTS.md` **without** the marker is never overwritten.
- Foreign `~/.claude/CLAUDE.md` is replaced on sync — back up first if another tool wrote it.

## `scan.json`

| Key | Purpose |
|-----|---------|
| `roots` | Folders to scan for unknown repos (must exist on this machine) |
| `agent_rule_name` | Always-on rule filename under `~/.agents/rules/` (default `user-rules.mdc`). Legacy key: `cursor_rule_name`. |
| `ignore_dir_names` | Skipped when scanning — includes `.agents`, `.cursor`, `.git`, `node_modules`, … |
| `ignore_slugs` | Slugs never reported as unknown |
| `expand_children` | Monorepo parents whose child repos are also tracked |
| `compact_always_on` | Default `true`. One-line project table in inject; paths in `projects/<slug>/README.md`. Set `false` for full `PROJECTS.md` body in always-on. |

## Optional commands

| Command | Role |
|---------|------|
| `python -m agents_memory ingest catalog` | Rebuild `chats-index.md` (titles + paths only — link for search) |
| `python -m agents_memory ingest extract` | Filter durable user lines into staging (not typed memory) |
| `python -m agents_memory distill` | Show grouped staging inbox (inspect before distill) |
| `python -m agents_memory extract-openai` | Open AI GDPR export wrapper (`--out` = legacy JSON) |
| `python -m agents_memory mcp` | stdio MCP — see [`MCP.md`](MCP.md) |

Ingest contract (all providers): catalog → pointers, extract → filtered staging, distill → explicit promote. See [`INGEST.md`](INGEST.md).

## Correct usage (agents)

1. Durable facts → MCP `add_memory(kind=, name=)` or edit typed markdown in place.
2. Identity / project map → edit `USER.md` / `PROJECTS.md`, then `python -m agents_memory sync`.
3. New repo under a scan root → `python -m agents_memory inventory --register` or MCP `register_project`.
4. Do not commit live `~/.agents/memory` or `<repo>/.agents/memory` (gitignored in registered repos).
5. Prefer `python -m agents_memory --help-json` over README for flags and injection paths.
