# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-09-08

### Added
- Multi-device **cloud mirror sync**. `agents-memory remote serve` hosts an authenticated bundle; `connect` / `disconnect` / `sync --push` keep each workstation’s markdown as the working copy and merge across machines. Writes (ingest, distill, `add_memory`) auto-push. Chat graves, the FTS index, and `remote_config.json` stay local. See [`abi/REMOTE.md`](abi/REMOTE.md).
- Optional extra project root (`remote attach`): pull a snapshot into a registered clone’s `.agents/memory` without replacing `USER.md` or switching MCP. Speaks a DID snapshot ABI; not the personal mirror.
- Ranked **hybrid search** inside `search_memory`: exact substring first, then FTS5 fill so a weak exact hit does not hide other files. CLI `rebuild-index` rebuilds the disposable cache (MCP start already does).
- Typed **relations** (`get_related`) over frontmatter `refs` / `supersedes` / `same_as`.
- Distill loop: `get_staging_inbox` grouped by source, `distill_batch`, `auto_distill`, and tiered staging nags in always-on inject.
- Direct file tools: MCP `read_memory_file` / `write_memory_file` and CLI `read` / `add` / `search` / `projects`.
- Closed YAML frontmatter schema and `agents-memory check` (stubs, duplicates, dangling refs, index staleness, sandbox leaks).
- `AGENTS_HOME` so a sandbox vault cannot touch live `~/.agents/memory`.
- Compact always-on inject (one line per project; detail via MCP).
- Ingest extract fixtures for all six source kinds. Catalog writes titles and paths only (`chats-index.md`); bodies stay in product folders.
- vand `source.yml` so install and verify are catalogued.
- CLI `--help-json` and a Cordis-oriented `search` verb.
- GitHub Actions: CI on pull requests to `dev`/`main` (Ubuntu, Python 3.12), GitHub Releases on `v*.*.*` tags without automated PyPI, Discord webhooks for CI failure and feature/release notices.
- CLI vault CRUD mirrors MCP: `write`, `delete`, `related` (plus aliases `put` / `rm` / `rels`).
- `--help-json` ships a full `commands` catalog (every top-level verb + aliases), not only `sync`/`inventory`.

### Changed
- Conversation bodies belong to **agents-traces**. This package keeps catalog pointers. Session reads are not markdown memory.
- `sync --init` **splices** host `AGENTS.md` between HTML comment markers instead of replacing the file.
- MCP clerk is **15 tools**: the 14 after prune plus `get_related`. FTS lives inside `search_memory`, not a second search verb.
- README uses the organization 4:1 hero asset.
- Copyright and package authors are Lolaplex.
- Package / GitHub description: product one-liner (MCP + cross-agent vault), not ABI/reference-impl jargon.
- README “Where it runs”: honest support tiers (universal MCP/CLI floor, sync autowire, chat ingest) — no fake parity for Aider/Continue/Goose.
- README: MCP tools section before CLI; CLI framed as ops/install/batch, vault CRUD as MCP mirrors.
- README agent-setup tip: require clone path or GitHub URL so the agent follows `AGENTS.md` (package name `agents-memory`, not `agent-memory`).
- Root `--help` groups vault CRUD, projects/inject, staging/ingest, and ops; documents aliases and deprecations.
- `ingest-chats` is an explicit alias of `ingest catalog`.
- `connect` / `disconnect` documented as `remote` aliases (still work top-level).
- Dynamic remote configuration resolution in `agents_memory.remote.client` for strict test environment isolation.

### Deprecated
- `extract-openai` → prefer `ingest extract` (openai-export source). Wrapper still runs with a stderr notice.

### Removed
- MCP tools for ingest (`ingest_catalog`, `ingest_extract`, `ingest_status`), session reads (`session_snap`, `session_grep`, `session_tail`), and baton/chronicle (`get_baton`, `set_baton`, `append_chronicle`). Use CLI ingest, [agents-traces](https://github.com/Lolaplex/agents-traces), and on-disk ritual/chronicle files instead.
- Extra MCP verbs that duplicated the clerk: `search_hybrid` (folded into `search_memory`), `rebuild_index` (MCP start / CLI), `promote_bullet` (`distill_batch` covers one or many), `suggest_links`, `check_memory_freshness`.
- Automated PyPI publish from CI. Releases are GitHub assets plus local twine when you want PyPI.
- Personal-host pinning in the remote SSE DNS-rebinding guard.
- Root `requirements.txt` (duplicate of `pyproject.toml`; install via `pip install -e .`).
- Redundant `source.yaml` at repository root in favor of standard `source.yml`.
- Legacy hardcoded rule prefix filter in store rule purger.
- Synthetic personal name references in remote test suites.
- Root `ROADMAP.md` (stale package backlog). Non-goals stay in [`abi/WHY.md`](abi/WHY.md).
- `deploy/` Docker, compose, and systemd templates. Host the mirror with `agents-memory remote serve`.

### Fixed
- Staging and path resolution for child and moved repositories (`inventory --repair-moved`).
- Remote SSE hang, streaming auth, JSON merge, status schema, file scanner, and CLI syntax.
- CI: SSE tests no longer open infinite streams; job timeouts; Discord notify uses curl (Cloudflare blocks urllib).
- Search CLI usage message; Starlette TestClient via httpx.
- CLI `write` with empty piped stdin exits 2 and does not overwrite the target file.
- CI runs `scripts/sync_bundled.py --check` before pytest so wheel `abi/` drift fails fast.

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
