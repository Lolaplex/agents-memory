# Hygiene

Version: see [`VERSION`](VERSION).

Data arrives from many surfaces (chat graves, agent transcripts, user capture, MCP calls).
Not everything that enters the system deserves to stay. Hygiene is the gate between raw material and durable memory.

## Three lifetimes

Every piece of information lives in exactly one lifetime. Promote deliberately; never skip a stage.

| Lifetime | Where | Mutability | Exits by |
|----------|-------|------------|----------|
| **Evidence** | Product folders (chat jsonl, brain transcripts, export zips, GDPR shards) | Immutable archive — never rewritten by agents-memory | Catalog pointer → `chats-index.md`; filtered extract → staging |
| **Inbox** | `staging/` (project), `staging/ingest/<id>/` (user), `notes/scratch/` | Append, then distill or delete. Inbox is not memory. | `promote_bullet` / `distill_batch` → typed path; or delete |
| **Memory** | Typed paths (`concepts/`, `decisions/`, `notes/<collection>/`, etc.) | Revise in place (implemented, decisions, entities) or frozen (rejected) | Human or agent edits; `delete_memory` |

### Evidence stays where the product put it

Chat bodies, transcripts, brain folders, and export archives remain in their product directories.
Ingest catalog creates **pointers** (`chats-index.md`). Ingest extract creates **filtered bullets** in staging.
Neither phase copies bodies into `~/.agents/memory`.
The derived execution log — tools, messages, live MCP and ingested vendor chats — is **agents-traces** (`~/.agents/traces`). Memory `session_snap` / `session_grep` / `session_tail` read that store. They do not open product jsonl.

Wholesale import — symlink-all-histories, dump-entire-exports — floods search with one-shots and duplicates product stores. We do not want to remember everything ever said.

### Inbox is transient

Staging is a loading dock, not a warehouse. Bullets accumulate from ingest extract, MCP `add_memory(project=)`, and manual capture. They must be distilled into typed memory or discarded.

The `staging_nag_threshold` in `ingest.json` exists because an inbox that only grows is a second graveyard.

### Memory has a home

A durable fact lives at one typed path. Path encodes kind ([`KINDS.md`](KINDS.md)). No dump files, no monolithic `MEMORY.md`, no `facts.md`.

If a fact cannot be filed under an existing kind, the layout is missing a kind — not the fact.

## Write boundaries

Who may write what. Violations are bugs, not edge cases.

| Surface | Writer | Write rule |
|---------|--------|------------|
| Evidence (product folders) | Product only | agents-memory never writes to chat/brain/export archives |
| `chats-index.md`, `entities/chat-source-*.md` | Ingest catalog | Pointers and titles. Rebuild from `ingest.json` at any time |
| `~/.agents/traces` | agents-traces ingest + live interceptor | Conversation/tool log. Memory reads it; memory never writes it |
| `staging/` | Ingest extract, `add_memory(project=)`, manual | Append bullets. Distill gate before typed memory |
| Typed memory (`concepts/`, `decisions/`, `notes/`, …) | `promote_bullet`, `distill_batch`, `add_memory(kind=, name=)`, direct file edit | Explicit kind + name required. No auto-promotion from staging |
| `~/.agents/AGENTS.md`, host rules, per-repo `.agents/` inject | `sync` (generated) | Short identity + project map. Not transcripts, not extracted bullets |

### No LLM on write

`add_memory`, `promote_bullet`, and `distill_batch` file text as given. They do not summarize, rephrase, merge, or "clean up" the input. The agent or human provides the final wording; the tool provides the path.

Auto-distill (`auto_distill`) may **discard** obvious noise and **categorize** standard facts, but it does not rewrite bullet text or invent facts not present in staging.

A deterministic **noise pass** (`auto_distill_noise_pass`) may run **after ingest extract** when the inbox is at or above `auto_distill_noise_threshold` (defaults to `staging_nag_threshold`). Optional on MCP start via `auto_distill_on_start` (default `false`). That pass only discards obvious noise and files heuristic matches (`always`/`never`/`prefer`). It is not auto-promotion of leftover bullets.

### No auto-promotion

Staging → typed memory requires an explicit distill call with `kind` and `name`. No background LLM, no timer, no "smart inbox" that silently graduates remaining bullets.

If the inbox is too large, the nag fires. The response is distill or delete — not auto-file the rest.

## Filter rules (extract phase)

Extract pulls **user-durable lines** from evidence and drops everything else. Shared across all source kinds ([`INGEST.md`](INGEST.md)):

| Drop | Why |
|------|-----|
| Assistant / model turns | Not user memory; product-specific; often huge |
| Tool calls and tool results | Execution artifacts, not durable facts |
| System prompts | Boilerplate per product |
| Code dumps > threshold | Belong in repos, not memory |
| PII patterns (emails, phones, tokens) | Safety; never land in memory |
| How-to / tutorial prompts | One-shot instructions, not identity or decisions |
| Duplicate bullets (within run) | Dedupe before staging |

Per-source `extract_max_bullets` caps volume per run. The cap exists because uncapped extract from a large archive will overwhelm any distill session.

## Index-as-cache law

Any index, embedding store, or search acceleration structure is a **disposable cache** derived from the markdown files on disk.

| Rule | Consequence |
|------|-------------|
| Markdown is source of truth | Delete the index; rebuild from files; same results |
| Index never auto-writes memory | A search hit does not become a fact. `suggest_links` proposes; human accepts via explicit `add_memory` with refs |
| Embedding vectors are optional | FTS is the baseline. Embeddings improve ranking but are not required for correctness |
| Index location: `~/.agents/memory/.index/` | Gitignored. Not shipped, not synced, not versioned |
| Rebuild command: `rebuild_index` | Deterministic from current markdown tree. No incremental-only state that can't be reconstructed |

An index that cannot be deleted and rebuilt is a second store. That is a regression.

### Embedding cache config disclosure convention

When an embedding vector cache (`embeddings.sqlite`) is generated, it must record a configuration header containing:
- `model_id`: Canonical identifier of the embedding model
- `dimension`: Vector dimensionality (e.g. 768, 1536)
- `instruct_prefix`: Query/document prefix string used (e.g. `"passage: "` or `"query: "`)
- `created_at`: Unix timestamp of the index run

Embedding caches missing configuration metadata or generated with mismatched instruct prefixes must be invalidated and rebuilt.

## Relation frontmatter

Memory files may carry explicit relations in YAML frontmatter. Files with no
`---` fence are valid. A file that opens a fence MUST close it and MUST only
use keys from the schema below (`python -m agents_memory check` /
`frontmatter-schema` + `dangling-refs`). Unknown keys fail: that keeps
UMP-shaped envelopes (DID, integrity, consent blobs) out of the vault.

```yaml
---
refs:
  - project/demo/decisions/001-architecture-baseline
  - user/concepts/data-joins
supersedes: user/notes/programming/old-approach
at_project: demo
same_as: external:resource:abc123
provenance: human
checked_at: 2026-08-29
pin_kind: correction
---
```

### Frontmatter schema (closed)

| Key | Type | Role |
|-----|------|------|
| `slug` `path` `role` `stack` `status` | string | Project card (`stub_project_md`) |
| `title` `kind` `name` `collection` `date` `id` | string | Optional identity (`id` on chat-source entities) |
| `refs` | YAML list | Directional references (memory ids or `survey:` / `record:` / `external:` / `entity:` / `urn:` / `http(s):` / `did:`) |
| `supersedes` `same_as` `at_project` `at_landmark` `part_of` `next` `near` `survey_ref` `on_trail` | string or list | Relation vocabulary |
| `provenance` | `human` \| `agent` \| `import` | Pin / assertion source |
| `checked_at` | date string | When an external claim was last verified |
| `pin_kind` | `correction` \| `addition` \| `deletion` | Human pin that must survive recompile |

`status` on a project card is `active` \| `sandbox` \| `paused` \| `archived`.
Lifecycle notes also use `proposed` \| `implemented` \| `rejected` \| `accepted`.
`planned` is reserved for ingest placeholders (slug reservation).

Machine copy: `agents_memory.frontmatter.SCHEMA_KEYS`. Do not add keys in prose
without adding them there.

| Key | Semantics |
|-----|-----------|
| `refs` | This file references those ids (directional) |
| `supersedes` | This file replaces that file (old file kept, marked superseded) |
| `at_project` | Scoped to a project slug |
| `same_as` | Identity assertion: this memory and that external id refer to the same concept |
| `at_landmark` | Located at a specific landmark |
| `part_of` | Containment relation |
| `next` | Sequence ordering |
| `near` | Proximity relation (symmetric) |
| `survey_ref` | Survey pointer from catalog/index to external body |
| `on_trail` | Sequential progression step |

Named check ids for the harness: `staging-leftovers`, `duplicate-notes`,
`near-duplicate-slugs`, `stub-notes`, `index-stale`, `frontmatter-schema`,
`dangling-refs`.

Explicit typed edges take precedence over similarity ranking. The index may surface related files, but the frontmatter is the ground truth.

### Survey pointer convention

1. `chats-index.md` contains shallow survey pointers (title, date, path) rather than full chat transcripts.
2. Chronicle beats reference external entity IDs via `refs: ["survey:...", "record:..."]`.
3. Reading raw full bodies is strictly on-demand (via ingestion filters or reader tools), never dumped wholesale into active memory.

### Relation vocabulary appendix

| RelationKind | Description | Symmetric |
|---|---|---|
| `refs` | Directional reference | No |
| `supersedes` | Replaces target entity | No |
| `same_as` | Identity equivalence | Yes |
| `at_project` | Project membership | No |
| `at_landmark` | Landmark spatial/topic anchor | No |
| `near` | Proximity association | Yes |
| `on_trail` | Sequential progression step | No |
| `survey_ref` | Catalog pointer to external body | No |
| `part_of` | Containment hierarchy | No |
| `next` | Sequential predecessor -> successor | No |

## Temporal kinds

Chronicle and ritual kinds extend the memory layout for temporal operations. See [`KINDS.md`](KINDS.md) for path rules.

| Kind | Path | Mutability | Purpose |
|------|------|------------|---------|
| `chronicle` | `~/.agents/memory/events/chronicle/<slug>.md` | Append-only beats | Ordered record of what happened (not inbox, not decision) |
| `ritual` | `<repo>/.agents/memory/rituals/baton.md` | Mutable by ritual MCP only | Session handoff marker — who was here, what was in progress, what to do next |
| `event` | `~/.agents/memory/events/<name>.md` | Append-only | Generic append-only event log (optional; chronicle is the primary temporal kind) |

Chronicle beats are **observations**, not decisions. A beat records that something happened; it does not prescribe what to do about it. Beats carry optional `refs:` linking to memory files or external ids involved.

Baton is mutable because its purpose is to be updated at session boundaries. Only the ritual MCP tools (`get_baton`, `set_baton`) write it. A stale baton triggers a nag, not an auto-fix.

## Hygiene checklist (for implementors)

Before adding a feature to agents-memory, check:

- [ ] Does it write to a product folder? → **No.** Evidence stays where the product put it.
- [ ] Does it skip staging and write directly to typed memory? → **Only** with explicit `kind` + `name`.
- [ ] Does it auto-promote staging bullets? → **No.** Distill is intentional.
- [ ] Does it make the index non-rebuildable? → **No.** Index is cache.
- [ ] Does it merge external stores or databases? → **No.** Explicit references, not merged tables.
- [ ] Does it rewrite user text on write? → **No.** File as given; path is the tool's job.
- [ ] Does it make always-on injection longer than identity + project map? → **No.** Details are retrieved, not injected.
- [ ] Does it require an embedding database for correctness? → **No.** Embeddings are optional ranking boost.
