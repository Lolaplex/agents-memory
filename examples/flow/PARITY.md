# Example pack parity

This file documents the parallel relationship between flow examples in two repos.

## Repos

| Repo | Scope | Path |
|------|-------|------|
| agents-memory | `memory.v1` | `examples/flow/` |
| noble-kepler | `plex.v1` | `examples/flow/` |

## File-by-file cross-reference

| File | agents-memory | noble-kepler | Same schema? |
|------|--------------|--------------|-------------|
| `root-manifest.json` | `memory.v1` scope | `plex.v1` scope | Yes — `protocol`, `version`, `scopes[]`, `encodings[]` |
| `scope-*.v1.json` | `scope-memory.v1.json` | `scope-plex.v1.json` | Yes — `scope`, `budget`, `capabilities[]` with `id`, `cost`, `inputs[]`, `outcomes[]`, `semantic` |
| `flow-resolve-*.flow` | `flow-resolve-promote.flow` | `flow-resolve-open.flow` | Same branch syntax; different continuation targets |
| `flow-quarantine.flow` | staging inbox gate | quarantine table gate | Same branch syntax; both are agent-safe write boundaries |
| `flow-open-record.flow` | — | `flow-open-record.flow` | Pure flow record open by ID |
| `scope-media.v1.json` | `scope-media.v1.json` | `scope-media.v1.json` | **Byte-identical** media capability descriptor |
| `flow-play-episode.flow` | `flow-play-episode.flow` | `flow-play-episode.flow` | **Byte-identical** show -> episode -> authorize -> play |
| `media-result-budget.json` | `media-result-budget.json` | `media-result-budget.json` | **Byte-identical** playback session result with obligations |
| `entity-ref-samples.json` | agents-memory path ids, ingest session ids | plexd record/landmark ids, import URIs | Same `kind`/`value`/`context` schema; different id schemes |
| `relation-vocabulary.json` | ← **identical** → | ← **identical** → | **Byte-identical** |
| `flow-result-budget.json` | MCP result shape | HTTP cap response (with obligation) | Same top-level: `status`, `cost`, `result`, `obligations[]`, `links[]` |

## Rules

1. `relation-vocabulary.json` must remain **identical** across repos. Edit one, copy to the other.
2. Root manifest and scope manifest schemas must match — same field names, same types. Only the scope `id` and capability list differ.
3. Flow result budget JSON must share the same top-level structure: `status`, `cost.used`, `cost.remaining`, `result.branch`, `result.fields`, `obligations[]`, `links[]`.
4. `.flow` files use the same branch continuation syntax. Capability ids differ per scope.

## Verification

Wave 004 adds fixture tests in both repos:
- noble-kepler: live manifest endpoint returns JSON matching `scope-plex.v1.json`
- agents-memory: MCP tool catalog covers every capability in `scope-memory.v1.json`
