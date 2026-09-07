# Flow examples — agents-memory (`memory.v1`)

Generic, flow-based capability examples for the agents-memory scope. Same JSON schema as the parallel pack in noble-kepler (`plex.v1`).

## Scope

`memory.v1` — agent memory capabilities exposed via MCP tools.

| Capability | MCP tool |
|------------|----------|
| `memory.resolve` | `search_memory` |
| `memory.relate` | `get_related` (Wave 003) |
| `memory.promote` | `promote_bullet` / `distill_batch` |
| `quarantine.propose` | `add_memory(project=)` (staging gate) |

## Files

| File | Shape from protocol doc | This scope's adaptation |
|------|------------------------|------------------------|
| `root-manifest.json` | Root manifest (`protocol: flow`, scopes list) | Lists `memory.v1` |
| `scope-memory.v1.json` | Scope manifest (capabilities, cost, semantic) | `memory.resolve`, `memory.relate`, `memory.promote`, `quarantine.propose` |
| `flow-resolve-promote.flow` | Branch continuation syntax | resolve → found → promote staging bullet |
| `flow-quarantine.flow` | Agent-safe boundary | propose → staging inbox (no direct typed memory write) |
| `entity-ref-samples.json` | Reference / EntityId / ExternalId | `user/concepts/foo`, `project/bar/decisions/001`, ingest session ids |
| `relation-vocabulary.json` | RelationKind table (shared) | frontmatter `refs`, `supersedes`, `same_as`, `at_project` |
| `flow-result-budget.json` | Response with cost + obligations | MCP tool result shape |

## Parity

Paired with: `noble-kepler/examples/flow/` (plex.v1 scope)

Both packs share:
- `root-manifest.json` — same schema, different scope id
- `relation-vocabulary.json` — **identical file**
- `flow-result-budget.json` — same JSON shape, different field values
- Branch continuation syntax in `.flow` files

See [`PARITY.md`](PARITY.md) for the file-by-file cross-reference.

## Protocol framing

These examples are one dialect of a generic flow-based capability protocol — PCL-style: self-describing objects/capabilities, a semantic graph that mediates schema translation at runtime. Not branded to any single product.
