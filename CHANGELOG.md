# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-09-05

### Added
- MCP reference contract alignment with full tool parity (`search_memory`, `search_hybrid`, `get_related`, `suggest_links`, `promote_bullet`, `check_memory_freshness`, `rebuild_index`).
- Comprehensive testing matrix across all modules, CLI, MCP, and extraction pipelines.
- CI and Release workflows aligned with Autonomous GitHub Standard (CI on PRs only, GitHub Releases on tag push without automated PyPI).

### Changed
- Memory store optimization and FTS5 rank-ordered hybrid search indexing.
- Streamlined injection and sync pipelines across IDEs and projects.

## [1.0.2] - 2026-08-31

### Fixed
- Staging and file path resolution for child repositories.

## [1.0.1] - 2026-08-20

### Added
- Initial vendor integration and `source.yaml` for dependency pinning.

## [1.0.0] - 2026-08-19

### Added
- Initial release of local markdown memory and FastMCP server.
