# Decision 001 — Semantic capability platform

**Status:** accepted  
**Date:** 2026-08-24  
**Scope:** agents-memory, noble-kepler (plex-shell), dumbo, orca

## Context

agents-memory is operational memory for coding agents. plex-shell (noble-kepler) is a personal cognition control plane with daemon, TUI, and WebView record shell. Dumbo is a Tauri overlay serving as the test app for plex-shell's GUI projection. ORCA is an Open Resource Capability Archive backed by a semantic graph.

These products share architectural patterns (typed entities, relations, capability-scoped operations, append-only temporal records) but have different stores, write rules, and query shapes. A flow-based capability protocol (PCL-style: self-describing, schema translation at runtime) ties their scopes together without merging data.

## Decision

Build the semantic capability platform as **parallel tracks with shared examples**, not a merged store.

### Architecture

1. **Three stores, three owners, no merge.**
   - `~/.agents/memory` — coding-agent ops (agents-memory ABI)
   - `~/.plex` — human cognition terrain (plexd SQLite)
   - ORCA evidence store — public OSS capabilities (orca importer SQLite)

2. **Flow-based capability protocol as the integration layer.**
   - Generic, not branded to any one product. The koruflow protocol doc is one dialect.
   - Each product declares a scope (`memory.v1`, `plex.v1`, `media.v1`) with capability descriptors.
   - Scopes map to MCP tools (agents-memory) or HTTP caps (plexd, Orisha).
   - Shared `examples/flow/` in both repos carry identical JSON shapes — manifest tests stay aligned.

3. **Dumbo as GUI projection testbed.**
   - Tauri 2 + Svelte 5 overlay (Alt+Space, tray, keyring, BYOK).
   - Queries plexd HTTP surface; renders records; promotes/rejects quarantine.
   - Validates what plex-shell GUI needs before committing to Qt/niri.
   - Not a second store — a thin view over the same plexd records.

4. **ORCA as semantic graph frontend.**
   - Indexes public open-source capabilities (license, deps, evidence).
   - Reachable via MCP (`search_capabilities`, `get_repository`).
   - agents-memory reads ORCA but never writes to it.

5. **WEBVIEW three-layer model** (from noble-kepler `docs/concepts/WEBVIEW_RECORD_SHELL.md`):
   - Profile (one) — cookies, logins, permissions
   - Record (many) — URL, title, tags, links, notes, status, snapshot
   - Instance (few) — live WebView bound to a record id

6. **Index-as-cache law.**
   - Any index (FTS, embeddings) is rebuildable from markdown/SQLite source files.
   - Delete the index, rebuild, same results.
   - Embeddings are optional ranking boost, not correctness requirement.

7. **Temporal kinds** extend agents-memory for session continuity:
   - `chronicle` — append-only beats (what happened)
   - `ritual` / baton — mutable session handoff (who was here, what to do next)
   - `event` — generic append-only log

8. **Cross-product bridges are read-only or quarantine-gated.**
   - agents-memory → plex: `search_records` (read), `quarantine.propose` (agent proposes, human promotes)
   - agents-memory → ORCA: `search_capabilities` (read)
   - plex → agents-memory: survey pointers only (chronicle refs may cite record ids)

### ISAR connection

Relation frontmatter keys (`refs`, `supersedes`, `same_as`, `at_project`) align with ISAR join semantics: explicit typed edges between canonical entities, not implicit similarity. The flow protocol's `RelationKind` vocabulary parallels the `U(i,s,a,r)` join algebra. Full tensor kernel integration is Phase 4+ — SQLite is fine for the control plane; the algebra informs the schema now.

## Consequences

- Agents-memory stays pure markdown + MCP. No SQLite for agent memory (that's plexd's domain).
- noble-kepler and agents-memory must keep `examples/flow/` in sync (PARITY.md enforces).
- New capabilities require scope declarations, not ad-hoc HTTP routes.
- Dumbo is the first non-TUI consumer of plexd — validates that the HTTP surface is sufficient.
- agents-bench L2 findings gate index implementation choices (Wave 003/009 dependency).

## Alternatives considered

| Alternative | Why rejected |
|-------------|-------------|
| Merged SoT across all products | Write rules diverge; lifetimes diverge; identity schemes diverge |
| Embedding DB as primary store | Similarity ≠ importance; not rebuildable from source without the model |
| Obsidian as shared vault | LLM reorganizing your notes destroys the reasoning that *is* the organization |
| REST-documented endpoint catalog | Not capability-scoped; no budget/obligation/branch semantics |
| Full ISAR tensor backend now | SQLite is fine for v0; tensor joins needed only when relation queries bottleneck |

## References

- [`abi/HYGIENE.md`](../../abi/HYGIENE.md) — three lifetimes, write boundaries, index-as-cache
- [`abi/KINDS.md`](../../abi/KINDS.md) — memory kinds including temporal
- noble-kepler `docs/concepts/WEBVIEW_RECORD_SHELL.md` — three-layer model
- noble-kepler `docs/concepts/koruflow-semantic-capability-protocol.md` — flow protocol
- noble-kepler `docs/concepts/PLEXD_LOCAL_AGENT_HANDOFF.md` — daemon architecture
- dumbo `README.md` — Tauri overlay, vision roadmap
- orca `README.md` — capability archive, MCP tools
