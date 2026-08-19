# agent-memory

**Local markdown memory for coding agents — any provider, any tool.**

Without a shared layout, **each vendor owns a graveyard** — session archives that never become durable identity unless you re-teach every new agent. See **[`abi/WHY.md`](abi/WHY.md)** for the full rationale (vs RAG, vs vaults, vs vendor memory). Reference-implementation roadmap: [`ROADMAP.md`](ROADMAP.md).

Your memory lives in folders you own: `~/.agents/memory` (identity + project map) and `<repo>/.agents/memory` (per-project work). Your Agent — or any host that reads markdown and optional MCP — uses the same layout.

Markdown is the **source of truth**. The Python MCP in this repo is the **reference implementation**, not a proprietary backend.

## ABI (stable contract)

Shipped under [`abi/`](abi/) — versioned, documented, implementation-agnostic:

| Doc | What |
|-----|------|
| [`abi/README.md`](abi/README.md) | Overview + conformance |
| [`abi/WHY.md`](abi/WHY.md) | Why this exists (vs RAG, vaults, vendor graves) |
| [`ROADMAP.md`](ROADMAP.md) | Reference-implementation roadmap (not ABI) |
| [`abi/LAYOUT.md`](abi/LAYOUT.md) | Folder taxonomy |
| [`abi/KINDS.md`](abi/KINDS.md) | Where facts go |
| [`abi/MCP.md`](abi/MCP.md) | Tool contract |
| [`abi/INJECTION.md`](abi/INJECTION.md) | AGENTS / CLAUDE binding |
| [`abi/PLATFORM.md`](abi/PLATFORM.md) | Windows, symlinks, per-machine paths |
| [`abi/INSTALL.md`](abi/INSTALL.md) | Sync, injection, scan.json, `--help-json` |
| [`abi/INGEST.md`](abi/INGEST.md) | Catalog / extract / distill pipeline |

Install copies `abi/LAYOUT.md` → `~/.agents/memory/LAYOUT.md`. Injection and CLI flags: [`abi/INSTALL.md`](abi/INSTALL.md). Machine-readable: `python -m agent_memory --help-json`.

## Reference implementation (this repo)

Python lives in `src/agent_memory/` (`pip install -e .` from the clone).

| Piece | Role |
|-------|------|
| `agent_memory.mcp_server` | MCP: search / add / register / inventory / sync / ingest |
| `agent_memory.store` | Layout engine, taxonomy, injection |
| `python -m agent_memory sync` | Canonical `~/.agents/AGENTS.md`, bound `CLAUDE.md`, host inject |
| `python -m agent_memory inventory` | Disk vs `PROJECTS.md` (skips `.agents`, `.cursor`) |
| `python -m agent_memory ingest` | Chat catalog + extract pipeline |
| `skills/memory-sync/` | Agent install skill |

Templates only in git: `examples/*.example.*`. Live store: `~/.agents/memory`. Run `python -m agent_memory consolidate` if markdown leaked into this clone.

**Coding agents:** follow [`AGENTS.md`](AGENTS.md) for install.

## Layout (summary)

| Path | What |
|------|------|
| `~/.agents/memory/USER.md` | Always-on identity |
| `~/.agents/memory/PROJECTS.md` | slug / path / role / stack / status |
| `~/.agents/memory/concepts/` … | Cross-cutting typed memory (created on first write) |
| `~/.agents/memory/projects/<slug>/` | Link to real tree (not a copy) |
| `<repo>/.agents/memory/` | Files only when used — staging inbox, then typed paths on write |
| `~/.agents/AGENTS.md` | Short inject; `CLAUDE.md` bound to it |

Search unions user + all registered project trees. Chat *bodies* stay in product folders; `chats-index.md` is titles + paths only.

## Setup

Same interpreter for pip and MCP:

```bash
python -m pip install -e .
python -m agent_memory sync --init
python -m agent_memory inventory
```

Fill `~/.agents/memory/USER.md` and `scan.json` (from `examples/*.example.*` on first run). Reload your Agent after MCP merge.

See [`abi/PLATFORM.md`](abi/PLATFORM.md) for Windows symlink stubs and hardlink fallback.

## Scripts

```bash
python -m agent_memory inventory
python -m agent_memory inventory --json
python -m agent_memory inventory --register SLUG "/path/to/repo" "role" "stack"
python -m agent_memory sync
python -m agent_memory --help-json
python -m agent_memory sync --help-json
python -m agent_memory inventory --help-json
python -m agent_memory ingest catalog
```

After install, `agent-memory` on PATH is the same as `python -m agent_memory`.
