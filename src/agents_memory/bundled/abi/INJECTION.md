# Instruction injection (ABI)

Agents read short always-on context from markdown instruction files. The memory **store** is separate from injection.

## Canonical always-on

| File | Content |
|------|---------|
| `~/.agents/memory/USER.md` | Identity, talk style, stack defaults |
| `~/.agents/memory/PROJECTS.md` | slug / path / role / stack / status table |
| `~/.agents/AGENTS.md` | Generated summary of USER + PROJECTS (+ optional paths block) |

### Compact always-on (`scan.json`)

When `"compact_always_on": true` (default when omitted), generated inject uses a **one-line-per-project table** (slug, role, stack, status) instead of the full `PROJECTS.md` body. Paths live in `~/.agents/memory/projects/<slug>/README.md` — agents resolve detail via MCP `get_project_memories(project=slug)` or `search_memory`. Set `"compact_always_on": false` in `scan.json` to inject the full projects table including paths.

Per-repo injection (when registered): `<repo>/.agents/AGENTS.md` and bound `<repo>/.agents/CLAUDE.md` with project paths and memory pointers.

**Exception:** the agents-memory **engine clone** itself has install instructions at repo-root `AGENTS.md` only. Sync never writes `<engine>/.agents/` or `<engine>/.cursor/`. Project link for the engine lives at `~/.agents/memory/projects/agents-memory/README.md`.

## AGENTS.md / CLAUDE.md binding

Canonical user always-on: `~/.agents/AGENTS.md`.
`CLAUDE.md` next to it is **bound** to `AGENTS.md` (symlink → hardlink → copy). In git, `CLAUDE.md` is a symlink to `AGENTS.md`.

Binding order: **symlink → hardlink → copy**. Copy is last resort and can drift if you edit only one file.

Installed homes that bind to canonical unless repo-root files are foreign (no `<!-- agents-memory-sync -->` marker):

- `~/.agents/` (AGENTS + CLAUDE)
- `~/.agents/rules/*.mdc` → host slots such as `~/.cursor/rules/` (all personal `.mdc` files, not only `user-rules.mdc`)
- Gemini / Antigravity config
- Zed (`%APPDATA%/Zed` on Windows, `~/.config/zed` elsewhere)
- `~/.claude/` (AGENTS + CLAUDE)

Foreign `~/.claude/CLAUDE.md` from another tool may be replaced on sync — back it up first if you still need it.

## Marker

Generated files include `<!-- agents-memory-sync -->` so sync can distinguish owned injection from hand-written rules.

## Platform notes

See [`PLATFORM.md`](PLATFORM.md) for Windows symlink stubs, hardlink fallback, and per-machine ingest paths.
