---
type: belief
id: frag-search-is-fanout-over-named-stores
provenance: 2026-11-21 — the .agents mechanic retired across the fleet; agents-bench stores/ adapters measured the shape
ts: 2026-11-21
---

agents-memory is a **retrieval engine over named stores**, not a memory
format. What backs a store is config (`stores.json`), not code: the
markdown corpus is one store, a repo's `docs/decisions`+`concepts/` is
another, agents-store can be a third — the engine only sees the
`Store` protocol and merges ranked lists by RRF (k=60, the same constant
the FTS/TF-IDF fusion already used).

This retires the idea that memory lives in a blessed directory shape.
The per-repo `.agents/memory` mechanic is dead — durable rulings now live
as versioned docs in-repo (decisions, frags), and `repo-docs` stores make
them reachable through the same query surface as the markdown corpus.
A store that can't answer is a **named refusal row**, never a silent skip.

Open questions: whether `search_memory` becomes the fan-out facade or
`search_stores` stays the separate entry; where write-paths (add_memory)
belong when writes are per-store-shaped; whether bench's hybrid manifest
index becomes a store kind for large corpora.
