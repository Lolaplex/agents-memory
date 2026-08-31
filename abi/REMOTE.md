# Remote & mirror sync (ABI)

When `~/.agents/memory/remote_config.json` exists, devices keep **local files as the working copy** and sync a **mirror bundle** to the cloud server. All MCP tools run locally; push/pull handles multi-device truth.

Version: see [`VERSION`](VERSION).

## Mirror bundle (sync payload)

| Prefix / path | Source on device | On server | On pull to device |
|---------------|------------------|-----------|-------------------|
| `USER.md`, `concepts/`, `staging/`, … | `~/.agents/memory/` | same tree | merge into `~/.agents/memory/` |
| `rules/*.mdc` | `~/.agents/rules/` | stored in bundle | merge into `~/.agents/rules/` |
| `mirror/projects/<slug>/…` | `<repo>/.agents/memory/…` | `~/.agents/memory/mirror/projects/<slug>/…` | merge into local repo if registered |

Chat graves, FTS index (`.index/`), and `remote_config.json` are **never** synced.

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

## Non-goals
- Syncing chat transcript bodies to cloud.
- Syncing disposable SQLite caches.
