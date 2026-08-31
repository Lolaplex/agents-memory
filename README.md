# agents-memory

<p align="left">
  <a href="https://github.com/Lolaplex/agents-memory/releases"><img src="https://img.shields.io/badge/version-1.1.0-blue.svg?style=flat-square" alt="Version 1.1.0"></a>
  <a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP-Standard-orange.svg?style=flat-square" alt="MCP"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://pypi.org/project/agents-memory/"><img src="https://img.shields.io/pypi/v/agents-memory.svg?style=flat-square" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License"></a>
</p>

**Local markdown memory & cross-agent context engine for AI coding assistants.**  
One persistent identity, shared across **Claude Code**, **Cursor**, **Antigravity**, and **Zed**.

---

## Quickstart

### 1-Step Setup

```bash
pip install agents-memory && agents-memory sync --init
```

Scaffolds `~/.agents/memory/`, autowires MCP configurations into your installed IDEs, and registers assistant skills.

> [!TIP]
> **🤖 Agent-Driven Setup (Zero Friction):**  
> Simply tell your coding agent: **"Install and set up agents-memory for me."**  
> The agent installs the package, asks your stack preferences once, fills your `USER.md` profile, and registers your repositories autonomously.

*Source checkouts can also be installed and managed using [vand](https://github.com/Lolaplex/vand).*

---

## Why `.agents/memory`?

The name **`agents-memory`** comes directly from its universal storage standard: **`.agents/memory`**.

- **Global:** `~/.agents/memory/` stores your persistent identity, stack defaults, durable concepts, and project index.
- **Repository:** `<repo>/.agents/memory/` stores repo-specific facts, architecture ADRs, and staging inboxes.

While AI vendors fragment their configuration across proprietary stores, `.agents/` provides a single, open, vendor-neutral filesystem hub for all agent configurations and shared intelligence.

`agents-memory` delivers this with a **pure Markdown-first architecture**:

- **Local & Offline:** Your identity and repo memory live in plain files (`~/.agents/memory/` and `<repo>/.agents/memory/`).
- **Human-Readable & Git-Friendly:** Edit with any text editor, diff with git, commit when you want.
- **Universal MCP Server:** Exposes memory tools (`search_memory`, `add_memory`, `get_project_memories`, `distill_batch`, `get_baton`, `set_baton`, `append_chronicle`, `session_snap`, `session_grep`, `search_hybrid`, `get_related`, `suggest_links`, `check_memory_freshness`) to all modern agents.
- **Ranked Hybrid Retrieval:** Exact-substring precision first with SQLite FTS5 fallback and bidirectional wikilink relation navigation.
- **Autonomous Ingest & Distillation:** Extracts durable rules and architecture decisions from session logs (OpenAI, Claude, Cursor, Copilot, Antigravity, Pi).

---

## Architecture & Flow

```text
 ┌─────────────────────────────────────────────────────────────┐
 │                       SESSION INGEST                        │
 │  OpenAI Exports · Claude JSONL · Cursor · Antigravity · Pi  │
 └──────────────────────────────┬──────────────────────────────┘
                                │  ingest catalog / extract
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                       STAGING INBOX                         │
 │        Raw captured bullets & noise-filtered facts          │
 └──────────────────────────────┬──────────────────────────────┘
                                │  distill_batch / skill
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                     LOCAL MEMORY STORE                      │
 │   ~/.agents/memory/USER.md     ~/.agents/memory/PROJECTS.md │
 │   ~/.agents/memory/concepts/   <repo>/.agents/memory/       │
 └──────────────┬───────────────────────────────┬──────────────┘
                │                               │
                ▼                               ▼
 ┌─────────────────────────────┐ ┌─────────────────────────────┐
 │       IDE INJECTION         │ │     MCP SERVER & CLERK      │
 │  Cursor Rules · Zed Context │ │  search_memory · add_memory │
 │  Antigravity AGENTS.md      │ │  Universal Tool Integration │
 └─────────────────────────────┘ └─────────────────────────────┘
```

---

## CLI Reference

| Command | Purpose |
|---------|---------|
| `agents-memory sync` | Updates canonical `AGENTS.md`, host rules, and MCP registrations |
| `agents-memory sync --init` | First-time scaffolding, example creation, and host discovery |
| `agents-memory inventory` | Discovers unregistered local repositories across workspace roots |
| `agents-memory inventory --register SLUG PATH ROLE STACK` | Registers a new repository |
| `agents-memory ingest catalog` | Indexes local chat transcripts across all supported providers |
| `agents-memory ingest extract` | Runs heuristic filters to extract durable facts into staging |
| `agents-memory distill` | Inspects staging inbox for distillation |
| `agents-memory check` | Zero-AI mechanical store health checks (stubs, duplicates, leaks) |
| `agents-memory rebuild-index` | Rebuilds the disposable local SQLite FTS5 search index |
| `agents-memory serve` | Starts local interactive memory browser on localhost:8765 |
| `agents-memory remote serve` | Starts remote MCP & cloud sync server (FastMCP SSE + REST) |
| `agents-memory connect` | Connects local machine to remote cloud memory server |
| `agents-memory disconnect` | Disconnects from cloud and restores local stdio mode |
| `agents-memory web` | Exports static HTML documentation site for your memory store |
| `agents-memory consolidate` | Ensures no private state leaked into working repository |

---

## Cloud Sync & Multi-Device Coordination (v1.1.0)

Sync memory across multiple development machines, remote servers, and VPS assistants without data loss:

### 1. Host Server (VPS / Cloud)
Start the authenticated remote MCP and synchronization server:
```bash
agents-memory remote serve --port 8443 --token <YOUR_SECRET_TOKEN>
```

### 2. Connect Local Clients (Laptops / Workstations)
Connect any local machine to the cloud server with deterministic multi-device merge:
```bash
agents-memory connect https://memory.your-domain.com --token <YOUR_SECRET_TOKEN>
```

- **Mirror sync:** Cloud holds merged bundle; local files are the working copy on each device.
- **All MCP local:** Ingest, distill, search, CRUD run on workstation; push/pull keeps devices aligned.
- **Project memory synced:** `<repo>/.agents/memory/` mirrored via `mirror/projects/<slug>/` in bundle.
- **Auto-push:** Writes (ingest, distill, `add_memory`) push mirror bundle after mutation.
- **Fast offline injection:** Local `AGENTS.md` / rules for 0ms IDE startup; pull on MCP start.
- **Disconnect anytime:** `agents-memory disconnect` pulls final snapshot and restores local stdio mode.

See [`abi/REMOTE.md`](abi/REMOTE.md) for bundle layout and merge rules.

---

## MCP Tools Reference

| Tool | Parameters | Description |
| :--- | :--- | :--- |
| `search_memory` | `query`, `project`, `limit` | Exact-substring precision first with ranked SQLite FTS5 fallback. |
| `add_memory` | `fact`, `kind`, `name`, `project` | Proactively save durable facts, concepts, ADRs, or rules directly to memory. |
| `get_project_memories` | `project`, `cwd` | Retrieve project-specific facts, architecture decisions, and active work files. |
| `get_staging_inbox` | *None* | Retrieve unreviewed captured bullets across user and project staging files. |
| `distill_batch` | `items_json` | Batch promote durable facts to permanent files or discard throwaway noise. |
| `promote_bullet` | `bullet`, `kind`, `name`, `project` | Promote a single staging bullet to permanent memory. |
| `get_baton` | `project`, `cwd` | Read the active session baton handover note for context continuity. |
| `set_baton` | `text`, `project`, `cwd` | Update the session baton handover note for the next agent session. |
| `append_chronicle` | `beat`, `project`, `emoji`, `refs` | Record a major milestone or beat in the project's temporal chronicle. |
| `session_snap` | `limit`, `project`, `cwd` | Snapshot recent user query history and active session baton. |
| `session_grep` | `pattern`, `since`, `project` | Fast regex search across indexed session transcripts. |
| `session_tail` | `session_id`, `limit` | Tail recent user interaction lines from session logs. |
| `search_hybrid` | `query`, `limit` | Hybrid search combining SQLite FTS5 text rank with wikilink relations. |
| `get_related` | `file_path`, `depth` | Traverse explicit wikilink relations, references, and backlinks. |
| `check_memory_freshness` | *None* | Mechanical audit of staging backlog and stale project batons. |

---

## Supported Ecosystem

- **Claude Code:** Bound via symlink / canonical `AGENTS.md` and MCP server.
- **Google Antigravity:** Integrated via `.gemini/config` rules and `agents-memory` MCP.
- **Cursor:** Automatically injects rules and configures `.cursor/mcp.json`.
- **Zed:** Configures `context_servers` and mirrors assistant skills.
- **VS Code / Copilot:** Ingests session history from local state databases.

**Also compatible with:** Windsurf, Cline, Roo-Code, Aider, Continue.dev, OpenAI ChatGPT, Pi, Goose, and any MCP-compliant AI assistant.

---

## Open ABI Specification

The formal, implementation-agnostic layout specification lives in [`abi/`](abi/):

- [`abi/WHY.md`](abi/WHY.md) — Architecture decisions & why Markdown wins over RAG.
- [`abi/LAYOUT.md`](abi/LAYOUT.md) — Directory taxonomy and path contracts.
- [`abi/KINDS.md`](abi/KINDS.md) — Typed memory taxonomy (`concepts`, `facts`, `decisions`).
- [`abi/HYGIENE.md`](abi/HYGIENE.md) — Store hygiene doctrine, anti-bloat rules, and health checks.
- [`abi/MCP.md`](abi/MCP.md) — Tool surface definitions and request/response specifications.
- [`abi/INGEST.md`](abi/INGEST.md) — Catalog, extract, and distillation pipeline.
- [`abi/INJECTION.md`](abi/INJECTION.md) — Host rule injection mechanisms.

---

## Testing & Verification

Run the comprehensive test suite and distillation benchmark:

```bash
python tests/run_all_tests.py
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
