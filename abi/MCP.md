# MCP surface (reference contract)

The Python server in this repository (`python -m agent_memory.mcp_server`, FastMCP) is the **reference implementation** of the agent-memory MCP contract. Other stacks may implement the same tools against the same on-disk layout ([`LAYOUT.md`](LAYOUT.md)).

Version: see [`VERSION`](VERSION).

## Tools

### `search_memory(query, project="")`

Search all local markdown: user store plus each registered project's `<repo>/.agents/memory/`.
Returns hit lines with stable ids (`user/...` or `project/<slug>/...`) suitable for `delete_memory`.

### `add_memory(fact_or_message, kind="", name="", project="", collection="")`

File a durable fact. See [`KINDS.md`](KINDS.md). Returns the relative path written.

### `get_project_memories(project)`

Return the project link README plus in-tree `.agents/memory` markdown for one slug.

### `delete_memory(memory_id)`

Delete one bullet line by id from a prior `search_memory` result
(e.g. `user/notes/programming/chat-stores.md:3`).

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

Rebuild `chats-index.md` and `entities/chat-source-*.md` from `ingest.json`. Catalog phase only — bodies stay on disk. See [`INGEST.md`](INGEST.md).

### `ingest_extract(source_id="")`

Filter durable user lines into `staging/ingest/<id>/captured.md` for one source or all enabled sources. Extract phase — distill with `add_memory` afterward.

### `ingest_status()`

JSON summary from `ingest/state.json` (last catalog/extract per source).

## Non-goals

- No cloud sync, no embedding database as source of truth, no LLM on write.
- Optional search indexes must be rebuildable from markdown; markdown wins.
