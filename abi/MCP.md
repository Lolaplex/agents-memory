# MCP surface (reference contract)

The Python server in this repository (`python -m agents_memory.mcp_server`, FastMCP) is the **reference implementation** of the agents-memory MCP contract. Other stacks may implement the same tools against the same on-disk layout ([`LAYOUT.md`](LAYOUT.md)).

Version: see [`VERSION`](VERSION).

## Tools

### `search_memory(query, project="")`

Search all local markdown: user store plus each registered project's `<repo>/.agents/memory/`.
Returns hit lines with stable ids (`user/...` or `project/<slug>/...`) suitable for `delete_memory`.
Does **not** search product chat/jsonl graves — use `chats-index.md` (catalog) for paths to bodies on disk.
Appends staging overflow notice if staging depth >= threshold.

### `add_memory(fact_or_message, kind="", name="", project="", collection="")`

File a durable fact. See [`KINDS.md`](KINDS.md). Returns the relative path written and auto-syncs across all IDEs/CLIs.

### `read_memory_file(file_id)`

Read the raw text of any memory or rule file by id (e.g. `user/USER.md`, `rules/user-rules.mdc`, `user/notes/...`, `project/<slug>/...`).

### `write_memory_file(file_id, content)`

Write/overwrite any memory or rule file and automatically trigger sync to all IDEs/CLIs.

### `promote_bullet(bullet, kind, name, project="", collection="", source_path="")`

Promote one staging bullet into typed memory (`kind` + `name` required) and remove it from staging. Auto-syncs.
Use `source_path` (from `get_staging_inbox`) when multiple staging files may contain similar text.

### `get_staging_inbox(project="", limit=20)`

Return un-distilled staging bullets **grouped by source file** (ingest id, project staging, or user inbox).
JSON shape: `{ "total", "shown", "groups": [{ "source", "file", "ingest_id", "project", "bullets": [...] }] }`.
Each bullet includes `source_path` for `distill_batch` / `promote_bullet`.

### `distill_batch(items_json)`

Batch promote or discard staging bullets. JSON array of objects:

- Promote: `{ "bullet", "kind", "name", "project?", "collection?", "source_path?" }`
- Discard: `{ "bullet", "discard": true, "source_path?" }`

Returns `{ promoted, discarded, remaining_staging_count, errors }`. Auto-syncs after batch.

### `auto_distill(limit=50, discard_noise=true)`

Automatically triage staging inbox: discards obvious chat chatter/questions/noise and categorizes standard preferences/facts. Auto-syncs.

### `get_project_memories(project)`

Return the project link README plus in-tree `.agents/memory` markdown for one slug.

### `delete_memory(memory_id)`

Delete one bullet line by id from a prior `search_memory` result
(e.g. `user/notes/programming/chat-stores.md:3`). Auto-syncs.

### `list_projects()`

List rows from `PROJECTS.md` (slug, path, role, stack, status).

### `inventory_projects()`

Compare `scan.json` roots to `PROJECTS.md`. JSON: unknown folders, missing paths, etc.

### `register_project(slug, path, role="", stack="", status="")`

Add or update `PROJECTS.md`, create `<repo>/.agents/memory/` tree, write project link, inject AGENTS/CLAUDE, sync.

### `ignore_project(slug)`

Add slug to `scan.json` `ignore_slugs` so inventory skips it.

### `sync_local_agents_md(project_folder_path="", project_slug="")`

Rewrite always-on injection (your Agent hosts, `~/.agents/`, registered repo `.agents/`). Optional single-repo inject by path or slug.

### `ingest_catalog()`

Rebuild `chats-index.md` and `entities/chat-source-*.md` from `ingest.json`. **Catalog phase only** — pointers (titles + paths), bodies stay in product folders. Same contract for every source. See [`INGEST.md`](INGEST.md).

### `ingest_extract(source_id="")`

Filter durable user lines into `staging/ingest/<id>/captured.md` for one source or all enabled sources. **Extract phase only** — staging inbox, not typed memory; distill with `promote_bullet` / `distill_batch` / `auto_distill` afterward. Per-source caps and shared filters apply (see [`INGEST.md`](INGEST.md)).

### `ingest_status()`

JSON summary from `ingest/state.json` plus `staging` block: `bullet_count`, `group_count`, `threshold`, `nag` (when inbox exceeds threshold).

## Non-goals

- No cloud sync, no embedding database as source of truth, no LLM on write.
- Optional search indexes must be rebuildable from markdown; markdown wins.
