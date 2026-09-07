# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-09-07

### Added
- Multi-device **cloud mirror sync**. `agents-memory remote serve` hosts an authenticated bundle; `connect` / `disconnect` / `sync --push` keep each workstation’s markdown as the working copy and merge across machines. Writes (ingest, distill, `add_memory`) auto-push. Chat graves, the FTS index, and `remote_config.json` stay local. See [`abi/REMOTE.md`](abi/REMOTE.md).
- Optional extra project root (`remote attach`): pull a snapshot into a registered clone’s `.agents/memory` without replacing `USER.md` or switching MCP. Speaks a DID snapshot ABI; not the personal mirror.
- Ranked **hybrid search**: exact-substring first, disposable SQLite FTS5 fallback (`search_memory`, `search_hybrid`, `rebuild-index`).
- Typed **relations** (`get_related`, `suggest_links`) over frontmatter `refs` / `supersedes` / `same_as`.
- Distill loop: `get_staging_inbox` grouped by source, `promote_bullet`, `distill_batch`, `auto_distill`, and tiered staging nags in always-on inject.
- Direct file tools: MCP `read_memory_file` / `write_memory_file` and CLI `read` / `add` / `search` / `projects`.
- Closed YAML frontmatter schema and `agents-memory check` (stubs, duplicates, dangling refs, index staleness, sandbox leaks).
- `AGENTS_HOME` so a sandbox vault cannot touch live `~/.agents/memory`.
- Compact always-on inject (one line per project; detail via MCP).
- Ingest extract fixtures for all six source kinds. Catalog writes titles and paths only (`chats-index.md`); bodies stay in product folders.
- vand `source.yml` so install and verify are catalogued.
- CLI `--help-json` and a Cordis-oriented `search` verb.
- GitHub Actions: CI on pull requests to `dev`/`main` (Ubuntu, Python 3.12), GitHub Releases on `v*.*.*` tags without automated PyPI, Discord webhooks for CI failure and feature/release notices.

### Changed
- Conversation bodies belong to **agents-traces**. This package keeps catalog pointers. Session reads are not markdown memory.
- `sync --init` **splices** host `AGENTS.md` between HTML comment markers instead of replacing the file.
- MCP stays the **local clerk** even when a device is connected. Ingest always runs on the workstation.
- README uses the organization 4:1 hero asset.
- Copyright and package authors are Lolaplex.

### Removed
- MCP tools for ingest (`ingest_catalog`, `ingest_extract`, `ingest_status`), session reads (`session_snap`, `session_grep`, `session_tail`), and baton/chronicle (`get_baton`, `set_baton`, `append_chronicle`). Use CLI ingest, [agents-traces](https://github.com/Lolaplex/agents-traces), and on-disk ritual/chronicle files instead.
- Automated PyPI publish from CI. Releases are GitHub assets plus local twine when you want PyPI.
- Personal-host pinning in the remote SSE DNS-rebinding guard.

### Fixed
- Staging and path resolution for child and moved repositories (`inventory --repair-moved`).
- Remote SSE hang, streaming auth, JSON merge, status schema, file scanner, and CLI syntax.
- CI: SSE tests no longer open infinite streams; job timeouts; Discord notify uses curl (Cloudflare blocks urllib).
- Search CLI usage message; Starlette TestClient via httpx.

### Security
- Secret blacklist and scrubbing on memory writes; `.env*`, SSH keys, and PEM files are ignored.
- Remote serve uses token auth (TLS when configured).
- Extra-root attach signs through `agents-keys` (secret stays in that process), not in-process crypto.
- Closed frontmatter rejects unknown keys so foreign envelopes cannot land in the vault.

## [1.0.2] - 2026-08-31

### Fixed
- Staging and file path resolution for child repositories.

## [1.0.1] - 2026-08-20

### Added
- Initial vendor integration and `source.yaml` for dependency pinning.

## [1.0.0] - 2026-08-19

### Added
- Initial release of local markdown memory and FastMCP server.

[Unreleased]: https://github.com/Lolaplex/agents-memory/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Lolaplex/agents-memory/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/Lolaplex/agents-memory/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/Lolaplex/agents-memory/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Lolaplex/agents-memory/releases/tag/v1.0.0
