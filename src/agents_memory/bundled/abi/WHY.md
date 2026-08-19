# Why agents-memory exists

Version: see [`VERSION`](VERSION).

## The problem

Coding agents leave session archives everywhere: Cursor transcripts, Open AI (GDPR export, Codex rollouts, ChatGPT app), Copilot logs, IDE brain folders, Pi sessions. **Without a shared layout, each vendor owns a graveyard** — session archives that never become durable identity unless you manually re-teach every new agent.

Those graves are searchable only inside the product that created them. Switch hosts and you lose operational continuity — not because the facts changed, but because nothing was ever filed where another tool could read it.

## What this is (and is not)

agents-memory is **operational memory for coding agents**: identity, project map, typed facts, decisions, staging inboxes. It is local markdown with a path-shaped contract (`abi/`), optional MCP as a clerk — not a cloud product, not a second brain app.

It is **not**:

| Approach | What it optimizes | Why it is different |
|----------|-------------------|---------------------|
| **RAG / vector retrieval** | “What passages support this answer?” | Chunks and embeddings are usually a **derived cache**. Ranking is similarity-based. **Similarity ≠ importance.** |
| **Obsidian / vault / second-brain** | “Where did I put this thought, and how does it relate to my life?” | Links, graph layout, and folder placement are **part of your reasoning**. The map is the thought. |
| **Vendor “memory” features** | “Remember this chat in our product.” | Siloed, opaque, not portable across IDEs and agents. |

The ABI says it plainly: **no embedding database as source of truth, no LLM on write, markdown wins**; optional indexes must be rebuildable from files ([`MCP.md`](MCP.md)). That is the opposite of most RAG stacks and the opposite of “AI organize my vault.”

RAG and full-text search **compose** with this layout: retrieval over `~/.agents/memory` is a **vehicle through the MCP door** — enrichment for delivery, not ownership of truth. The files on disk remain authoritative; the index is disposable.

## The pipeline is the opposite of a warehouse

Chat and brain stores stay in product folders. Ingest does **not** copy bodies wholesale into memory ([`INGEST.md`](INGEST.md)):

1. **Catalog** — pointers only (`chats-index.md`, entity cards). Like project links: where bodies live, not the bodies themselves.
2. **Extract** — filtered user lines into **staging** (revertible inbox). Aggressive filters: PII, how-tos, code dumps, length.
3. **Distill** — intentional `add_memory(kind=, name=)` into typed paths. Then delete the staging bullet.

Memory is what you distill. Archives are evidence.

Wholesale ingest or symlink-all-histories would flood search with one-shots, duplicate product stores, and noise that ranks high by similarity but low by durability. We do not want to remember everything ever said.

## Always-on stays short; the rest is retrieved

Always-on injection is **USER.md + PROJECTS.md** (generated into `~/.agents/AGENTS.md` and host rules) — not transcripts, not the full text of every project README, not extracted chat bullets.

Project entries in the map should trend toward **small link cards** (`projects/<slug>/README.md` points at the real tree; per-repo `.agents/AGENTS.md` is a slice, not a copy of global identity). Details live in typed files and in repos; agents **search** for the rest.

## Personal notes vs agent memory

Second-brain tools get abused as agent memory because they are already markdown on disk and agents can read them. That merges two jobs and guarantees entropy.

When you file a note under one area vs another, or link it to specific neighbors, **you performed classification that is itself reasoning**. If an LLM “cleans up” by moving notes, merging duplicates, and proposing a prettier tree, you may get a cleaner filesystem — and lose why something mattered, even if it looks organized now. An LLM shuffling your cards is contrary to organizing your thoughts when **that organization is the thought**.

agents-memory’s `notes/` collections hold **agent-addressable facts**, not a replacement for a personal vault. Separate surfaces, separate write rules: agents append to staging and distill with explicit `kind`; they do not silently reorganize your inner map.

## Portability

What travels across machines is **typed markdown** (identity, project map, concepts, decisions) — sync via git, Syncthing, or whatever you already use. Catalog paths in `ingest.json` are per-machine (globs to local transcript folders). JSONL graves stay where the product put them; only pointers and distilled facts need to move.

The layout is implementation-agnostic: any agent that reads folders and optional MCP can conform. Python in this repo is the reference implementation, not the lock-in.

## What to protect

**Markdown with a path is the memory. Chats are evidence. MCP is a clerk.**

If an improvement makes the clerk the store — embeddings as SoT, auto-promotion from staging, LLM rewrite on write, wholesale chat import — it is a regression even if it feels smarter.

Planned improvements for the reference implementation: [`../ROADMAP.md`](../ROADMAP.md).
