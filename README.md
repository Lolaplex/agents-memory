# agent-memory

<p align="left">
  <a href="https://github.com/Lolaplex/agent-memory/releases"><img src="https://img.shields.io/badge/version-0.42-blue.svg?style=flat-square" alt="Version 0.42"></a>
  <a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP-Standard-orange.svg?style=flat-square" alt="MCP"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License"></a>
</p>

**Local markdown memory & cross-agent context engine for AI coding assistants.**  
One persistent identity, shared across **Claude Code**, **Cursor**, **Antigravity**, and **Zed**.

---

## Why agent-memory?

Without a shared memory layout, **every AI tool lives in its own silo**:
- Each vendor locks chat history in proprietary local databases or remote clouds.
- Switching IDEs or agents means starting from scratch and repeating preferences.
- Vector DBs and RAG solutions add infrastructure complexity, drift out of date, and are not human-editable.

`agent-memory` solves this with a **pure Markdown-first architecture**:
- **Local & Offline:** Your identity and repo memory live in plain files (`~/.agents/memory/` and `<repo>/.agents/memory/`).
- **Human-Readable & Git-Friendly:** Edit with any text editor, diff with git, commit when you want.
- **Universal MCP Server:** Exposes memory tools (`search_memory`, `add_memory`, `get_project_memories`, `distill_batch`) to all modern agents.
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

## Quickstart

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/Lolaplex/agent-memory.git
cd agent-memory

# Install in editable mode
python -m pip install -e .
```

### 2. Initialize & Sync

```bash
# Scaffold initial directories and wire into host IDEs / MCP configs
agent-memory sync --init

# Audit and register local repositories
agent-memory inventory
```

Fill in `~/.agents/memory/USER.md` with your profile and stack preferences. Reload your agent to connect to the MCP server.

---

## CLI Reference

| Command | Purpose |
|---------|---------|
| `agent-memory sync` | Updates canonical `AGENTS.md`, host rules, and MCP registrations |
| `agent-memory sync --init` | First-time scaffolding and host discovery |
| `agent-memory inventory` | Discovers unregistered local repositories across workspace roots |
| `agent-memory inventory --register SLUG PATH ROLE STACK` | Registers a new repository |
| `agent-memory ingest catalog` | Indexes local chat transcripts across all supported providers |
| `agent-memory ingest extract` | Runs heuristic filters to extract durable facts into staging |
| `agent-memory consolidate` | Ensures no private state leaked into working repository |

---

## Supported Ecosystem

- **Claude Code:** Bound via symlink / canonical `AGENTS.md` and MCP server.
- **Google Antigravity:** Integrated via `.gemini/config` rules and `agent-memory` MCP.
- **Cursor:** Automatically injects rules and configures `.cursor/mcp.json`.
- **Zed:** Configures `context_servers` and mirrors assistant skills.
- **VS Code / Copilot:** Ingests session history from local state databases.

---

## Open ABI Specification

The formal, implementation-agnostic layout specification lives in [`abi/`](abi/):

- [`abi/WHY.md`](abi/WHY.md) — Architecture decisions & why Markdown wins over RAG.
- [`abi/LAYOUT.md`](abi/LAYOUT.md) — Directory taxonomy and path contracts.
- [`abi/KINDS.md`](abi/KINDS.md) — Typed memory taxonomy (`concepts`, `facts`, `decisions`).
- [`abi/MCP.md`](abi/MCP.md) — Tool definitions and request/response specifications.
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
