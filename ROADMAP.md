# Roadmap (reference implementation)

Not part of the ABI — this is **future work for this repo's Python package**, not normative contract changes. The ABI lives in [`abi/`](abi/). Rationale: [`abi/WHY.md`](abi/WHY.md).

Constraints for any item here: **markdown as source of truth**, **MCP as clerk not store**.

## Highest leverage (in order)

### 1. Make distill cheaper, not automatic

Staging with hundreds of extract bullets is the real failure mode (inbox, not memory). Do **not** auto-write `concepts/` or promote staging without explicit `kind` + `name`.

Improvements to consider:

- Cluster extract bullets by title / source before display
- Cap bullets per source on extract
- MCP tool: **promote bullet** — requires `kind`, `name`, optional `project`; moves one line from staging to typed path; deletes source bullet
- Periodic `ingest status` summary (nag when staging grows)

### 2. Keep always-on short — **priority**

`USER.md` + full `PROJECTS.md` in every inject already grows with registry size.

**Target:** one-line-per-project in always-on inject (slug, path, role — not full README bodies). Agents use `search_memory` / `get_project_memories` for detail.

Related:

- **Small link cards** everywhere: `projects/<slug>/README.md` and repo `.agents/AGENTS.md` stay pointers + minimal metadata, not essays
- Per-repo inject remains a **slice** only; one global profile in `~/.agents/`

This will matter **before embeddings do**.

### 3. Extract quality as the contract

Per-source parsers (`agent-jsonl`, `openai-export`, …) are extension points; **filters** are the product (PII, how-to, length, dedupe).

Add fixture transcripts per kind so format drift does not silently admit junk. Tests assert keep/drop behavior, not just parser smoke.

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
