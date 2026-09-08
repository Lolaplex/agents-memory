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
> **🤖 Agent-Driven Setup:**
> Give your coding agent **this repo** (clone or URL), then tell it to **"install and set up agents-memory."**

Source checkouts can also be installed and managed with [vand](https://github.com/Lolaplex/vand).

---

## What it does

Vendors keep chat in product graves (Cursor jsonl, Claude sessions, Antigravity brains, Open AI exports). **agents-memory** is the portable layer on top: identity, project map, typed facts. Markdown on disk is the source of truth. MCP is a clerk, not a second store. The search index is disposable FTS5 — delete it, rebuild, same results.

| Layer | Where | What lives there |
| --- | --- | --- |
| **Global** | `~/.agents/memory/` | `USER.md`, `PROJECTS.md`, concepts, decisions, staging |
| **Per repo** | `<repo>/.agents/memory/` | facts, ADRs, in-progress work (gitignored) |
| **Always-on** | host `AGENTS.md` / rules | short inject; agents `search_memory` for the rest |

**Search.** `search_memory` tries exact substring first, then FTS5 fill. `get_related` follows explicit frontmatter relations (`refs`, `supersedes`, `same_as`), not cosine similarity. Known project slug → `get_project_memories`.

**Ingest → staging → distill.** Catalog writes titles and paths to `chats-index.md`. Extract filters user lines into `staging/` (PII, how-tos, dumps dropped). You (or `distill_batch` / `memory-distill`) promote durable facts into typed files. Chat bodies never become memory. Conversation logs belong to [agents-traces](https://github.com/Lolaplex/agents-traces).

**IDE injection.** One `sync` splices always-on context into hosts it knows (`AGENTS.md` / rules) and merges MCP where a config file already lives. Text outside `<!-- agents-memory-sync -->` stays. Details: [Where it runs](#where-it-runs).

**Cloud sync (new in 1.1.0).** Several machines, one vault — see below.

---

## Where it runs

**Floor:** anywhere with a terminal or an MCP client. Markdown vault + `python -m agents_memory mcp` is enough. No IDE lock-in.

Deeper support is layered — `sync --init` autowires what it finds on disk; ingest only covers graves we actually parse.

| Layer | What you get | Who |
|-------|----------------|-----|
| **Vault + MCP/CLI** | Full tools (`search_memory`, `add_memory`, …) or CLI mirrors | Any MCP host / any shell |
| **Autowire on sync** | Merge `agents-memory` into host MCP config; splice always-on `AGENTS.md`; install skills where the host has a slot | Cursor, Claude Code, Claude Desktop, Zed (`context_servers`), Antigravity / Gemini, Windsurf, Codex MCP paths, Roo, Cline |
| **Always-on / rules** | Marked inject block + bound rules | `~/.agents/AGENTS.md` (canonical); also Gemini, Zed, Claude home; rules → Cursor / Gemini / Windsurf |
| **Chat ingest** | `ingest catalog` + `extract` → `chats-index.md` + staging (bodies stay in product folders) | Cursor, Claude Code, Antigravity, VS Code Copilot, Windsurf, Roo, Cline, Pi, Open AI GDPR export |

**Ingest ≠ “supports the product.”** Titles/paths + filtered user bullets only — same contract for every source ([`abi/INGEST.md`](abi/INGEST.md)). Distill is still agent/human judgment.

**MCP without autowire:** Aider, Continue, Goose, stock Copilot Chat, … — point the host at our stdio server yourself. Vault works; we just do not invent their config path.

**Not ingested yet:** live Codex rollouts, ChatGPT desktop LevelDB, vendor `/memory` clouds. Add a source when a parser exists — do not wholesale-import foreign memory.

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

## MCP tools

Primary surface. Agents talk to the vault here — not via scraping CLI help.

| Tool | What it does |
| :--- | :--- |
| `search_memory` | Exact substring, then FTS5 fill. Not chat graves. Known slug → `get_project_memories`. |
| `get_related` | Follow frontmatter `refs` / `supersedes` / `same_as` from a hit id |
| `add_memory` | File a typed fact; auto-syncs inject |
| `read_memory_file` / `write_memory_file` | Raw file by id (`user/USER.md`, `project/<slug>/…`) |
| `get_project_memories` | One slug’s in-tree memory (call when opening a repo) |
| `list_projects` / `inventory_projects` / `register_project` / `ignore_project` | Project map |
| `get_staging_inbox` / `distill_batch` / `auto_distill` | Staging → typed memory |
| `delete_memory` | Drop a search hit by id |
| `sync_local_agents_md` | Rewrite always-on inject |

Fifteen tools. Full contract: [`abi/MCP.md`](abi/MCP.md). Session snap/grep/tail live on **agents-traces**.

---

## CLI

Ops / install / batch. Humans and agents rarely need the vault CRUD verbs — those mirror MCP for scripts. Machine-readable catalog: `python -m agents_memory --help-json` (do not scrape `--help`).

| Command | Purpose |
|---------|---------|
| `agents-memory sync [--init] [--push]` | Always-on inject, first-run scaffold, optional mirror push |
| `agents-memory inventory [--register …] [--repair-moved]` | Disk vs `PROJECTS.md`; register or fix moved clones |
| `agents-memory search` / `add` / `read` / `write` / `delete` / `related` | MCP vault mirrors (scripts / no-MCP hosts) |
| `agents-memory ingest catalog\|extract\|status` | Chat catalog and staging extract |
| `agents-memory distill [--auto]` | Staging inbox / noise pass |
| `agents-memory check` | Mechanical store health (no LLM) |
| `agents-memory rebuild-index` | Rebuild disposable FTS5 cache (MCP start already rebuilds) |
| `agents-memory remote …` / `connect` / `disconnect` | Cloud mirror (`connect`/`disconnect` = aliases) |
| `agents-memory serve` / `web` | Local viewer / static HTML export |
| `agents-memory reset --yes` | Clear local caches / temp state |
| `agents-memory mcp` | stdio MCP clerk |

`extract-openai` is deprecated → `ingest extract` (openai-export source).

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
