# Roadmap (reference implementation)

Not part of the ABI — this is **future work for this repo's Python package**, not normative contract changes. The ABI lives in [`abi/`](abi/). Rationale: [`abi/WHY.md`](abi/WHY.md).

Constraints for any item here: **markdown as source of truth**, **MCP as clerk not store**.

## Highest leverage (in order)

### 1. Make distill cheaper, not automatic

Staging with hundreds of extract bullets is the real failure mode (inbox, not memory). Do **not** auto-write `concepts/` or promote staging without explicit `kind` + `name`.

Improvements to consider:

- ~~Cluster extract bullets by title / source before display~~ — `get_staging_inbox` groups by source file
- ~~Cap bullets per source on extract~~ — `extract_max_bullets` in `ingest.json` (global + per-source; `0` = unlimited)
- ~~MCP tool: **promote bullet**~~ — shipped; use `distill_batch` for batch promote/discard
- ~~Periodic `ingest status` summary (nag when staging grows)~~ — `ingest_status` / CLI `ingest status` include `staging.nag`

### 2. Keep always-on short — **priority**

`USER.md` + full `PROJECTS.md` in every inject already grows with registry size.

**Target:** one-line-per-project in always-on inject (slug, path, role — not full README bodies). Agents use `search_memory` / `get_project_memories` for detail.

Shipped: `compact_always_on` defaults **on** (`scan.json` may set `false` for full table). Project link cards and per-repo `.agents/AGENTS.md` are pointer slices — detail via MCP.

This will matter **before embeddings do**.

### 3. Extract quality as the contract

Per-source parsers (`agent-jsonl`, `openai-export`, …) are extension points; **filters** are the product (PII, how-to, length, dedupe).

Add fixture transcripts per kind so format drift does not silently admit junk. Tests assert keep/drop behavior, not just parser smoke.

Shipped: `tests/fixtures/agent-jsonl` and `tests/fixtures/copilot-jsonl` + `tests/test_extract_filters.py`.

### 4. Search later, if ever

Optional **rebuildable** index (e.g. SQLite FTS over markdown paths) fits the ABI. Embedding DB as source of truth does **not**. Index is disposable; files win.

RAG/FTS over the store remains a **delivery vehicle** through MCP, not the store itself.

### 5. More sources as extractors, not as memory

New `kind` in `ingest.json` → catalog + extract handlers. Bodies stay in product folders.

Do not add heavy research/evolve/chronicle pipelines until **distill is a loop you actually run**.

### 6. Engine clone honesty

The agent-memory **engine repo** gets install docs at repo-root `AGENTS.md` only — no in-tree `.agents/` project memory, no copy of global USER inject. Same rule everywhere: **one global profile, per-repo slices only.**

### 7. Cross-machine portability

- **Sync:** typed markdown under `~/.agents/memory` (and chosen project notes) — portable
- **Local:** `ingest.json` globs, transcript paths, catalog counts — machine-specific
- Do not sync or symlink jsonl/chat graves as memory; catalog references are enough

## Explicit non-goals

- Embedding database as source of truth
- LLM on write (auto-merge, auto-reorganize vault-like trees)
- Wholesale chat/brain import into always-on or typed memory
- Second-brain graph UI or force-directed “cleanup” as part of this project
- Treating the Python package as the only valid implementation (the ABI is paths + optional MCP)
