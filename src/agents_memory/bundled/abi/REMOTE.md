# Remote & mirror sync (ABI)

When `~/.agents/memory/remote_config.json` exists, devices keep **local files as the working copy** and sync a **mirror bundle** to the cloud server. All MCP tools run locally; push/pull handles multi-device truth.

Version: see [`VERSION`](VERSION).

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
- Existing slug row edited on another device: **incoming wins** (local path kept when the incoming path is not on this host).
- A slug removed on one device stays removed. The union drops tombstoned rows.
- Conflicts logged to `staging/sync-conflicts.md` for agent review.

### Deletion tombstones

Merge unions files and table rows, so a missing path is not a deletion. A deletion is an explicit tombstone. The file is `~/.agents/memory/.tombstones.json` (a dotfile, never part of the bundle). Push and pull carry the same document on `/api/v1/merge` and `/api/v1/snapshot` as `tombstones`, plus the legacy `deleted` path list.

```json
{
  "version": 1,
  "files": {"notes/old.md": "2026-10-05T12:00:00Z"},
  "prefixes": {"mirror/projects/old-slug/": "2026-10-05T12:00:00Z"},
  "rows": {"PROJECTS.md": {"old-slug": "2026-10-05T12:00:00Z"}},
  "bullets": {"concepts/x.md": {"normalized bullet": "2026-10-05T12:00:00Z"}}
}
```

Rules, in order:

1. Later deletion stamp wins when two devices tombstone the same key.
2. A whole-file tombstone blocks that path. A prefix tombstone blocks everything under it (`mirror/projects/<slug>/` and `projects/<slug>/` when a slug is removed).
3. After the table union, tombstoned `PROJECTS.md` slugs are removed. After a bullet union, tombstoned bullets are removed.
4. A **re-add wins only when it is strictly newer** than the tombstone. File mtime counts for a single file. It does not punch through a prefix (a touched project tree must not undo a project removal). Putting the slug back (`register_project`, editing the row) records an explicit row and prefix write. `write_memory_file` / `PUT /api/v1/file` records an explicit file write.
5. Tombstones older than **90 days** are dropped on merge and snapshot. After that, a stale push can create the path again.
6. An old 1.1 client sends files and no tombstones. The server still applies its tombstones and does not resurrect blocked paths or rows. Those clients do not strip rows on pull; upgrade them. `deleted` path lists are still unlinked.

Writers: `delete_memory` (whole file, a `PROJECTS.md` row, or a bullet line), `delete_memory_file`, `ignore_project` / `inventory --ignore` when the slug is in `PROJECTS.md` (the row and that slug's mirror prefix are tombstoned; the repo checkout is not deleted), and `write_projects` / a `PROJECTS.md` rewrite that drops a slug. A baseline (`.sync-baseline.json`, local only) also tombstones paths this device had after the last sync and has since removed, so a background pull does not union them back.

`remote push` (the CLI, not the background push) with **no baseline yet** also tombstones project rows and `mirror/projects/` / `projects/` paths that the remote still has and this store does not. An empty local `PROJECTS.md` does not wipe a populated remote. Pull once on any other machine before its first `remote push` after upgrade, so it does not publish absences it has merely not seen.

### Replace pull

`agents-memory remote pull --replace` (and `remote connect <url> --replace`) makes this machine's **synced** files match the snapshot exactly:

1. Copy the store to `~/.agents/memory.bak-<UTC>` (sibling of the store directory). Registered repo memory trees are copied under that backup as `repo-memory-snapshot/<slug>/` before they are rewritten.
2. Leave machine-local files in place: `remote_config.json`, `host_paths.json`, `board_attach.json`, `.index/`, and any other dotfile the bundle already skips.
3. Delete synced files that are not in the snapshot. Write snapshot bytes verbatim (no table union).
4. For each slug **still in the snapshot's `PROJECTS.md`** whose repo exists here, make `<repo>/.agents/memory/` match `mirror/projects/<slug>/`. Slugs that were removed are not registered anymore, so their checkouts are left on disk and are not pushed.

The command takes the same cross-process lock as MCP pull/push (`.sync.lock`). It is safe while `sync_mcp` is running: the background pull waits, then merges a store that already matches the server. If the lock stays busy for 15 seconds, the command refuses and tells you to retry.

## Index (FTS)
- Rebuilt locally after each pull/push (`~/.agents/memory/.index/`).
- Never synced; markdown is source of truth.

## Board attach (extra root)

`connect` is single-tenant: one personal `USER_MEMORY` mirrored across your devices.

`agents-memory remote attach <board-url> --slug <agent>` pulls a **shared project** snapshot. It shells out to `python -m agents_keys did|sign` (secret stays in that process). `--token lpb_…` is a spare door. If that project is **registered**, dest is the clone's `<repo>/.agents/memory/` (LAYOUT). Otherwise dest is `~/.agents/shared/by-url/<id>/` — an opaque id of the remote URL, never a guessed project name. `--project <slug>` selects the local clone when the board path name differs. It does **not** write `remote_config.json`, does **not** switch MCP to `sync_mcp`, and never copies `USER.md` / `PROJECTS.md`. Dest must not sit inside `~/.agents/memory/`. `<repo>/.agents/` is gitignored so another clone does not receive those files.

Only markdown under `decisions/`, `plans/`, `tasks/`, `waves/`, `roadmap/`, `staging/`, `notes/`, `research/` is written.

## Non-goals
- Syncing chat transcript bodies to cloud.
- Syncing disposable SQLite caches.
- Folding a board project into `connect` (that would replace the personal store).
