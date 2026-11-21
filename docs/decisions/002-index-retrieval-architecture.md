---
title: "Decision 002: Index and Retrieval Architecture — FTS5 + TF-IDF RRF"
date: "2026-08-24"
status: "implemented"
refs:
  - user/concepts/cache-law
  - .agents/memory/decisions/001-semantic-capability-platform
---

# Decision 002: Index and Retrieval Architecture — FTS5 + TF-IDF RRF

## Context & Bench Findings

Findings from `agents-bench` L2 probe evaluations demonstrated critical retrieval characteristics:
1. **Phrase-only FTS collapse**: Pure exact-phrase matching collapsed to a 0.007 hit-rate on natural-keyword probes.
2. **Keyword & Porter Stemming superiority**: Term-level FTS with unicode61 porter tokenization scored far above phrase-only matching.
3. **TF-IDF ≈ dense without a model**: Ranked TF-IDF cosine hit ~0.627 MRR-competitive with local embedding stores on LoCoMo probes; on MSC organic dialogue 0.780 / 0.664 while phrase-FTS was blind.
4. **Cache Invariance**: Embedding DBs as primary state introduce sync drift. Indexes must be disposable.

## Decision

1. **One disposable SQLite cache** at `~/.agents/memory/.index/fts.sqlite` (gitignored):
   - FTS5 virtual table (BM25 / `rank`, porter unicode61).
   - Sparse TF-IDF IDF + L2-normalized postings for the same documents.
   - Rebuilt together by `rebuild_index()` from markdown. Delete the file, rebuild, same results.
2. **`search_memory` is the product entry**:
   - Exact substring first (precision).
   - If empty, call the ranked index path automatically.
   - Agents do not pick a second store or a second tool for the same query.
3. **Ranked path = FTS5 list ∪ TF-IDF cosine list → Reciprocal Rank Fusion** (`k=60`).
   - Fuse ranks, not raw scores (BM25 and cosine are not commensurate).
   - Internal function remains `search_hybrid` for ranks/snippets / viewer; MCP keeps it secondary.
4. **No `semantic=` flag, no embedding model on this path.**
   - The old stub defaulted to `False` and never ran. Dense optional caches (`embeddings.sqlite` + model disclosure) stay a future, separate disclosure if ever needed — not required for correctness.
5. **Explicit typed relations still win** in `get_related` / `suggest_links` (`refs`, `supersedes`, `same_as`, `at_project`) before content overlap.

## Consequences

- Zero risk of index corruption breaking memory integrity.
- Recall without LMS or an embedder; RRF usually beats either list alone.
- `search_hybrid(semantic=…)` is gone — callers that passed it must drop the kwarg.
