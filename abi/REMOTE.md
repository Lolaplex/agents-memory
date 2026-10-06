# Remote & mirror sync (ABI)

When `~/.agents/memory/remote_config.json` exists, devices keep **local files as the working copy** and sync a **mirror bundle** to the cloud server. All MCP tools run locally; push/pull handles multi-device truth.

Version: see [`VERSION`](VERSION).

## Three planes (do not conflate)

| Plane | Entry | What it is | What it is not |
|-------|--------|------------|----------------|
| **CLI** | `python -m agents_memory …` | Human/shell commands: `sync`, `search`, `remote connect`, `remote attach`, … | MCP tools; Cordis schedule names |
| **MCP** | `python -m agents_memory.mcp_server` (or `remote.sync_mcp` when connected) | IDE tool surface: `search_memory`, `add_memory`, `session_snap`, … | `connect` / `attach` / `push` / `pull` — those are CLI only |
| **Harness** | `runner/modules/*.json`, `runner/schedules/*.json` | Cordis verbs that shell out to CLI (`python -m agents_memory search`, `rebuild-index`, `inventory`, …) | A second MCP server; not board attach |

**Rule:** one capability, one primary plane. Duplicating `remote attach` as an MCP tool was wrong — it blurred CLI vs MCP and invited shadow copies.

### `connect` vs `attach` (CLI only)

| Command | Alias | Writes `remote_config.json` | MCP mode | Purpose |
|---------|-------|----------------------------|----------|---------|
| `connect` | top-level `agents-memory connect` **or** `remote connect` | yes | switches host to `sync_mcp` | Personal mirror across devices |
| `disconnect` | top-level **or** `remote disconnect` | removes | back to local `mcp_server` | Stop mirroring identity |
| `attach` | **`remote attach` only** (no top-level shortcut) | no | stays local `mcp_server` | Pull shared board project into registered clone |

`connect` and `attach` may both exist on one machine; they are different roots ([`REMOTE.md`](#board-attach-extra-root), skill [`memory-remote`](../skills/memory-remote/SKILL.md)).

### MCP session tools vs markdown search

`session_snap`, `session_grep`, `session_tail` read **agents-traces** (`~/.agents/traces`). They do not search markdown memory. For architecture, ADRs, and facts use `search_memory` / `get_project_memories`. See [`HYGIENE.md`](HYGIENE.md).

### CLI discovery

Fixed command list — not free-form scraping of `--help`:

```bash
python -m agents_memory --help-json          # scripts + scripts_no_flags + injection
python -m agents_memory sync --help-json     # argparse-derived flags for sync
python -m agents_memory inventory --help-json
```

`search` is CLI + harness verb (`mcp.memory.search` → `python -m agents_memory search QUERY`); default memory lookup in the IDE is MCP `search_memory`.

## Mirror bundle (sync payload)

| Prefix / path | Source on device | On server | On pull to device |
|---------------|------------------|-----------|-------------------|
| `USER.md`, `concepts/`, `staging/`, … | `~/.agents/memory/` | same tree | merge into `~/.agents/memory/` |
| `rules/*.mdc` | `~/.agents/rules/` | stored in bundle | merge into `~/.agents/rules/` |
| `mirror/projects/<slug>/…` | `<repo>/.agents/memory/…` | `~/.agents/memory/mirror/projects/<slug>/…` | merge into local repo if registered |

Chat graves, FTS index (`.index/`), `remote_config.json`, and `board_attach.json` are **never** synced.

## MCP entry

| Mode | Process |
|------|---------|
| Local only | `python -m agents_memory.mcp_server` |
| Connected | `python -m agents_memory.remote.sync_mcp` (pull on start, push after writes, periodic pull) |

## Pipelines

### Ingest
1. **Catalog + extract** on workstation (reads local chat folders).
2. **Push** mirror bundle → server.
3. Bodies stay in product folders; typed memory lands in store via distill.

### Distill / CRUD
1. All MCP tools write **local files** (user store + repo `.agents/memory/`).
2. `_finish_store_write()` → injection + **push** mirror bundle.
3. Other devices **pull** → local files + repo trees updated.

### PROJECTS.md merge
- New slugs: appended.
- Existing slug row edited on another device: **incoming wins**.
- Conflicts logged to `staging/sync-conflicts.md` for agent review.

## Index (FTS)
- Rebuilt locally after each pull/push (`~/.agents/memory/.index/`).
- Never synced; markdown is source of truth.

## Board attach (extra root)

`connect` is single-tenant: one personal `USER_MEMORY` mirrored across your devices.

`agents-memory remote attach <board-url> --slug <agent>` pulls a **shared project** snapshot. It shells out to `python -m agents_keys did|sign` (secret stays in that process). `--token lpb_…` is a spare door. Dest is **only** the registered clone's `<repo>/.agents/memory/` (LAYOUT). If the project is not registered locally, attach fails — there is no `~/.agents/shared/` shadow tree and no copy into `~/.agents/memory/`. `--project <slug>` selects the local clone when the board path name differs. It does **not** write `remote_config.json`, does **not** switch MCP to `sync_mcp`, and never copies `USER.md` / `PROJECTS.md`. `<repo>/.agents/` is gitignored so another clone does not receive those files.

Only markdown under `decisions/`, `plans/`, `tasks/`, `waves/`, `roadmap/`, `staging/`, `notes/`, `research/` is written. CLI procedure: skill [`memory-remote`](../skills/memory-remote/SKILL.md).

## Non-goals
- Syncing chat transcript bodies to cloud.
- Syncing disposable SQLite caches.
- Folding a board project into `connect` (that would replace the personal store).
