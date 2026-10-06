# MCP surface (reference contract)

The Python server in this repository (`python -m agents_memory.mcp_server`, FastMCP) is the **reference implementation** of the agents-memory MCP contract. Other stacks may implement the same tools against the same on-disk layout ([`LAYOUT.md`](LAYOUT.md)).

Version: see [`VERSION`](VERSION).

## Tools

### `search_memory(query, project="")`

**Default search.** Search local markdown. **Default (`project` omitted) is the user store only** (`~/.agents/memory`). An unqualified search must not leak every registered clone.

- `project=<slug>` — that clone's `<repo>/.agents/memory/` plus the user store.
- `project=*` (or `all`) — every registered clone plus the user store.

Exact substring first (at most two hits per file) with stable hash-anchored IDs (`<rel_path>:<line>#<hash8>`, e.g. `user/notes/programming/chat-stores.md:3#a1b2c3d4`), then ranked index fallback is automatic (FTS5 BM25 + sparse TF-IDF fused by RRF in the same disposable `fts.sqlite`) so one noisy exact file does not hide another. Repo architecture: `get_project_memories(slug)` or pass `project=`. Does **not** search product chat/jsonl graves — use `chats-index.md` for paths to bodies on disk.
Known project slug → `get_project_memories`. Does **not** search product chat/jsonl graves — use `session_*` or `chats-index.md` for paths to bodies on disk.
Appends staging overflow notice if staging depth >= threshold.

### `add_memory(fact_or_message, kind="", name="", project="", collection="")`

File a durable fact. See [`KINDS.md`](KINDS.md). Returns the relative path written and auto-syncs across all IDEs/CLIs. For revise-in-place kinds (`research`, `decision`, `adr`, `implemented`), `add_memory` initializes a new file, but rejects appending to an already existing file (`write_memory_file` must be used).

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

Delete one bullet line by id from a prior `search_memory` result.
Supports stable hash-anchored IDs (`user/notes/foo.md:3#a1b2c3d4`), pure hash IDs (`user/notes/foo.md#a1b2c3d4`), uniform prefix (`memory:...`), and legacy line IDs (`...:3`).
Uses shift-tolerant content-hash matching if prior deletions moved line positions, and raises clean errors without silent line corruption. Auto-syncs.

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

### `get_baton(project="", cwd="")`

Read the session handoff baton marker text for a project (`<repo>/.agents/memory/rituals/baton.md`) or global user store fallback (`~/.agents/memory/rituals/baton.md`).

### `set_baton(text, project="", cwd="")`

Write or update the session handoff baton marker text. Mutable ritual; triggers auto-sync.

### `append_chronicle(beat, project="", emoji="📝", refs=[])`

Append an observation beat to `~/.agents/memory/events/chronicle/<slug>.md`. Includes timestamp and optional relation `refs:`.

### `session_snap(limit=20, project="", cwd="")`

Recent user lines from **agents-traces** (`~/.agents/traces`) plus baton header if present. Does not scrape product jsonl. Run `python -m agents_traces ingest` (harness `traces_ingest`) so vendor chats exist as traces first. Catalog pointers stay in `chats-index.md`.

### `session_grep(pattern, since="", project="")`

Search session messages in agents-traces (case-insensitive regex). Conversation bodies are never markdown memory.

### `session_tail(session_id="", limit=10)`

Tail recent session messages from agents-traces for one session id (or latest lines).

### `rebuild_index()`

Rebuild disposable SQLite cache (FTS5 + TF-IDF postings in one `fts.sqlite`). Maintenance — `search_memory` auto-rebuilds when the index is missing.

### `search_hybrid(query, project="", limit=20)`

**Secondary** ranked search over the same cache: FTS5 BM25 and sparse TF-IDF cosine fused with Reciprocal Rank Fusion. Use for explicit ranks/snippets; default agents use `search_memory`. Not for graph traversal — use `get_related`. No embedding model; the old `semantic=` stub is gone.

### `get_related(memory_id, limit=5)`

Graph neighbors for a **known id** from search results — Follow explicit frontmatter relations (`refs`, `supersedes`, `same_as`, `at_project`) from a `search_memory` hit id.

### `suggest_links(from_id, limit=5)`

Propose new relation candidates for human review. Does not write memory.

## Related surfaces (not this MCP)

- **CLI vault CRUD**: `search` / `add` / `read` / `write` / `delete` / `related` mirror these tools for humans and scripts.
- **Ingest** (`catalog` / `extract` / `status`): CLI `python -m agents_memory ingest`. Chat graves stay on the workstation.
- **Index rebuild**: CLI `python -m agents_memory rebuild-index` (MCP start already rebuilds).
- **Session reads** (`session_snap` / `session_grep` / `session_tail`): [agents-traces](https://github.com/Lolaplex/agents-traces).
- **Cloud mirror**: CLI `remote serve` / `connect` / `disconnect`. MCP tools still read and write **local** markdown; the bundle is push/pull only. See [`REMOTE.md`](REMOTE.md).

## Non-goals

- No embedding database as source of truth, no LLM on write (no auto-promote without `kind` + `name`).
- Optional search indexes must be rebuildable from markdown; markdown wins.
- This MCP does not scrape product jsonl and does not own conversation bodies.
- `distill_batch` stays MCP/skill-shaped (JSON batch); CLI only peeks (`distill`) or runs `distill --auto`.
