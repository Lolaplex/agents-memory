# agents-memory

<p align="left">
  <a href="https://github.com/Lolaplex/agents-memory/releases"><img src="https://img.shields.io/badge/version-1.0.1-blue.svg?style=flat-square" alt="Version 1.0.1"></a>
  <a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP-Standard-orange.svg?style=flat-square" alt="MCP"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://pypi.org/project/agents-memory/"><img src="https://img.shields.io/pypi/v/agents-memory.svg?style=flat-square" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License"></a>
</p>

**Local markdown memory & cross-agent context engine for AI coding assistants.**  
One persistent identity, shared across **Claude Code**, **Cursor**, **Antigravity**, and **Zed**.

---

## Why `.agents/memory`?

The name **`agents-memory`** comes directly from its universal storage standard: **`.agents/memory`**.
- **Global:** `~/.agents/memory/` stores your persistent identity, stack defaults, durable concepts, and project index.
- **Repository:** `<repo>/.agents/memory/` stores repo-specific facts, architecture ADRs, and staging inboxes.

While AI vendors fragment their configuration across proprietary stores, `.agents/` provides a single, open, vendor-neutral filesystem hub for all agent configurations and shared intelligence.

`agents-memory` delivers this with a **pure Markdown-first architecture**:
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

### 1-Step Setup

```bash
pip install agents-memory && agents-memory sync --init
```

Scaffolds `~/.agents/memory/`, autowires MCP configurations into your installed IDEs, and registers assistant skills.

> [!TIP]
> **🤖 Agent-Driven Setup (Zero Friction):**  
> Simply tell your coding agent: **"Install and set up agents-memory for me."**  
> The agent installs the package, asks your stack preferences once, fills your `USER.md` profile, and registers your repositories autonomously.

*Source checkouts can also be installed and managed using [vand](https://github.com/Lolaplex/vand) (`vand clone Lolaplex/agents-memory`).*

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
| `agents-memory consolidate` | Ensures no private state leaked into working repository |

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
