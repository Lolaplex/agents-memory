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

Installed homes get the **same marked block spliced** into their `AGENTS.md`. They are not bound to `~/.agents/AGENTS.md` (a bind would delete local instructions). `CLAUDE.md` is bound to the local `AGENTS.md` only when it has no text outside the memory block.

- `~/.agents/` (`CLAUDE.md` bound to `AGENTS.md` when CLAUDE is not a separate hand-written file)
- `~/.agents/rules/*.mdc` → host slots such as `~/.cursor/rules/`
- Gemini / Antigravity `AGENTS.md` (spliced)
- Zed `AGENTS.md` (spliced)
- `~/.claude/AGENTS.md` (spliced); `CLAUDE.md` spliced if it already has other text

## Marker

Generated inject is a closed pair so sync can update memory without deleting the rest of the file:

```
<!-- agents-memory-sync -->
… USER + PROJECTS (or the project slice) …
<!-- /agents-memory-sync -->
```

If the file already exists, the block is appended (or replaced in place). Text outside the comments is never deleted. Host copies (`~/.gemini/config/AGENTS.md`, Zed, `~/.claude/AGENTS.md`) are real files with the same block — not a bind that would wipe local instructions.

## Platform notes

See [`PLATFORM.md`](PLATFORM.md) for Windows symlink stubs, hardlink fallback, and per-machine ingest paths.
