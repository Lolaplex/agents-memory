# MCP surface (reference contract)

The Python server in this repository (`python -m agents_memory.mcp_server`, FastMCP) is the **reference implementation** of the agents-memory MCP contract. Other stacks may implement the same tools against the same on-disk layout ([`LAYOUT.md`](LAYOUT.md)).

Version: see [`VERSION`](VERSION).

## Tools

### `search_memory(query, project="")`

Search all local markdown: user store plus each registered project's `<repo>/.agents/memory/`.
Exact substring first (stable line ids for `delete_memory`), then ranked FTS5 fill so one weak exact hit does not hide other files.
Known project slug → `get_project_memories`. Does **not** search product chat/jsonl graves — use `chats-index.md` for paths to bodies on disk.
Appends staging overflow notice if staging depth >= threshold.

### `add_memory(fact_or_message, kind="", name="", project="", collection="")`

File a durable fact. See [`KINDS.md`](KINDS.md). Returns the relative path written and auto-syncs across all IDEs/CLIs.

### `read_memory_file(file_id)`

Read the raw text of any memory or rule file by id (e.g. `user/USER.md`, `rules/user-rules.mdc`, `user/notes/...`, `project/<slug>/...`).

### `write_memory_file(file_id, content)`

Write/overwrite any memory or rule file and automatically trigger sync to all IDEs/CLIs.

### `get_staging_inbox(project="", limit=20)`

Return un-distilled staging bullets **grouped by source file** (ingest id, project staging, or user inbox).
JSON shape: `{ "total", "shown", "groups": [{ "source", "file", "ingest_id", "project", "bullets": [...] }] }`.
Each bullet includes `source_path` for `distill_batch`.

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

### `get_related(memory_id, limit=5)`

Follow explicit frontmatter relations (`refs`, `supersedes`, `same_as`, `at_project`) from a `search_memory` hit id.

## Related surfaces (not this MCP)

- **Ingest** (`catalog` / `extract` / `status`): CLI `python -m agents_memory ingest`. Chat graves stay on the workstation.
- **Index rebuild**: CLI `python -m agents_memory rebuild-index` (MCP start already rebuilds).
- **Session reads** (`session_snap` / `session_grep` / `session_tail`): [agents-traces](https://github.com/Lolaplex/agents-traces).
- **Cloud mirror**: CLI `remote serve` / `connect` / `disconnect`. MCP tools still read and write **local** markdown; the bundle is push/pull only. See [`REMOTE.md`](REMOTE.md).

## Non-goals

- No embedding database as source of truth, no LLM on write (no auto-promote without `kind` + `name`).
- Optional search indexes must be rebuildable from markdown; markdown wins.
- This MCP does not scrape product jsonl and does not own conversation bodies.
