<p align="center">
  <img src="https://raw.githubusercontent.com/Lolaplex/.github/main/assets/agents-memory/hero-4x1.png" alt=".agents / memory" width="1280">
</p>

<p align="center">
  <a href="https://github.com/Lolaplex/agents-memory/releases"><img src="https://img.shields.io/badge/version-1.1.0-blue.svg?style=flat-square" alt="Version 1.1.0"></a>
  <a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP-Standard-orange.svg?style=flat-square" alt="MCP"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://pypi.org/project/agents-memory/"><img src="https://img.shields.io/pypi/v/agents-memory.svg?style=flat-square" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License"></a>
</p>

<p align="center">
  <strong>Local markdown memory &amp; cross-agent context engine for clankers.</strong><br>
  One persistent identity, shared across all your agents.
</p>

## Quickstart

```bash
pip install agents-memory && agents-memory sync --init
```

Scaffolds `~/.agents/memory/`, autowires MCP into installed IDEs, and registers assistant skills.

> [!TIP]
> **🤖 Agent-Driven Setup (Zero Friction):**
> Tell your coding agent: **"Install and set up agents-memory for me."**
> It installs the package, asks stack preferences once, fills `USER.md`, and registers your repos.

Source checkouts can also be installed and managed with [vand](https://github.com/Lolaplex/vand).

---

## What it does

Vendors keep chat in product graves (Cursor jsonl, Claude sessions, Antigravity brains, Open AI exports). **agents-memory** is the portable layer on top: identity, project map, typed facts. Markdown on disk is the source of truth. MCP is a clerk, not a second store. The search index is disposable FTS5 — delete it, rebuild, same results.

| Layer | Where | What lives there |
| --- | --- | --- |
| **Global** | `~/.agents/memory/` | `USER.md`, `PROJECTS.md`, concepts, decisions, staging |
| **Per repo** | `<repo>/.agents/memory/` | facts, ADRs, in-progress work (gitignored) |
| **Always-on** | host `AGENTS.md` / rules | short inject; agents `search_memory` for the rest |

**Search.** `search_memory` tries exact substring first, then ranked FTS5. `get_related` / `suggest_links` follow explicit frontmatter relations (`refs`, `supersedes`, `same_as`), not cosine similarity.

**Ingest → staging → distill.** Catalog writes titles and paths to `chats-index.md`. Extract filters user lines into `staging/` (PII, how-tos, dumps dropped). You (or `distill_batch` / `memory-distill`) promote durable facts into typed files. Chat bodies never become memory. Conversation logs belong to [agents-traces](https://github.com/Lolaplex/agents-traces).

**IDE injection.** One `sync` splices Cursor, Claude Code, Antigravity, and Zed. Existing `AGENTS.md` text outside the `<!-- agents-memory-sync -->` block stays.

**Cloud sync (new in 1.1.0).** Several machines, one vault — see below.

---

## Cloud sync

Mirror the personal store across laptops, a VPS, and other workstations. Each device keeps **local files** as the working copy. The server holds a merged bundle. MCP tools still run locally; push/pull keeps devices aligned.

**1. Host** (VPS / always-on box):

```bash
agents-memory remote serve --port 8443 --token <YOUR_SECRET_TOKEN>
```

**2. Clients** (laptops / workstations):

```bash
agents-memory connect https://memory.your-domain.com --token <YOUR_SECRET_TOKEN>
```

- New slugs append. Same-slug edits: incoming wins. Conflicts land in `staging/sync-conflicts.md`.
- Project trees sync as `mirror/projects/<slug>/` in the bundle, then merge back into registered clones.
- Ingest still reads **local** chat folders, then pushes the distilled markdown.
- `agents-memory disconnect` pulls a last snapshot and restores stdio MCP.

Layout and merge rules: [`abi/REMOTE.md`](abi/REMOTE.md).

---

## CLI

| Command | Purpose |
|---------|---------|
| `agents-memory sync [--init] [--push]` | Always-on inject, first-run scaffold, optional mirror push |
| `agents-memory inventory [--register …] [--repair-moved]` | Disk vs `PROJECTS.md`; register or fix moved clones |
| `agents-memory search QUERY` | Lexical vault search |
| `agents-memory add "…" [--kind …] [--project …]` | File a durable fact |
| `agents-memory read FILE_ID` | Raw markdown / rule file |
| `agents-memory ingest catalog\|extract\|status` | Chat catalog and staging extract |
| `agents-memory distill [--auto]` | Staging inbox / noise pass |
| `agents-memory check` | Mechanical store health (no LLM) |
| `agents-memory rebuild-index` | Rebuild disposable FTS5 cache |
| `agents-memory connect` / `disconnect` | Join or leave cloud mirror |
| `agents-memory remote serve` | Host the mirror bundle |
| `agents-memory serve` / `web` | Local viewer / static HTML export |
| `agents-memory mcp` | stdio MCP clerk |

`python -m agents_memory --help-json` is the machine-readable spec. Do not scrape `--help`.

---

## MCP tools

| Tool | What it does |
| :--- | :--- |
| `search_memory` | Exact substring, then ranked FTS5. Not chat graves. |
| `search_hybrid` | FTS5 rank with phrase/term fallback |
| `add_memory` | File a typed fact; auto-syncs inject |
| `read_memory_file` / `write_memory_file` | Raw file by id (`user/USER.md`, `project/<slug>/…`) |
| `get_project_memories` | One slug’s in-tree memory |
| `list_projects` / `inventory_projects` / `register_project` / `ignore_project` | Project map |
| `get_staging_inbox` / `promote_bullet` / `distill_batch` / `auto_distill` | Staging → typed memory |
| `delete_memory` | Drop a search hit by id |
| `sync_local_agents_md` | Rewrite always-on inject |
| `rebuild_index` | Rebuild FTS cache from markdown |
| `get_related` / `suggest_links` | Explicit relations, then overlap suggestions |
| `check_memory_freshness` | Staging backlog, stale batons, index |

Ingest is CLI. Session snap/grep/tail live on **agents-traces**.

---

## Supported hosts

- **Claude Code** — canonical `AGENTS.md` + MCP
- **Cursor** — rules + `.cursor/mcp.json`
- **Google Antigravity** — `.gemini` rules + MCP
- **Zed** — `context_servers` + mirrored skills
- **VS Code / Copilot** — ingest from local session stores

Also: Windsurf, Cline, Roo, Aider, Continue, ChatGPT exports, Pi, Goose, and any MCP host.

---

## ABI

Implementation-agnostic layout in [`abi/`](abi/):

- [`WHY.md`](abi/WHY.md) — why markdown wins over RAG-as-memory
- [`LAYOUT.md`](abi/LAYOUT.md) — directory contract
- [`KINDS.md`](abi/KINDS.md) — typed taxonomy
- [`HYGIENE.md`](abi/HYGIENE.md) — lifetimes, write boundaries
- [`MCP.md`](abi/MCP.md) — tool surface
- [`INGEST.md`](abi/INGEST.md) — catalog → extract → distill
- [`INJECTION.md`](abi/INJECTION.md) — host inject
- [`REMOTE.md`](abi/REMOTE.md) — mirror bundle (and extra project roots)

---

## Tests

```bash
python tests/run_all_tests.py
```

---

## License

MIT. See [LICENSE](LICENSE).
