# Ingest pipeline

Version: 1.0.0 (see `abi/VERSION`)

Chat and brain stores stay on disk in product folders. Ingest turns them into **searchable references** and optional **staging bullets** for distillation into typed memory under `~/.agents/memory`.

## Phases (serial)

| Phase | Command | Effect | Revert |
|-------|---------|--------|--------|
| **Catalog** | `python -m agent_memory ingest catalog` | `chats-index.md` + `entities/chat-source-<id>.md` | Delete cards; rebuild index |
| **Extract** | `python -m agent_memory ingest extract [--source ID]` | `staging/ingest/<id>/captured.md` | Delete staging file |
| **Distill** | MCP `promote_bullet` / `distill_batch` / skill `memory-distill` | Typed markdown in `concepts/`, `notes/`, etc. | Edit or delete memory file |

Run both catalog and extract: `python -m agent_memory ingest run`. Status: `python -m agent_memory ingest status` → `ingest/state.json` plus staging nag.

Distill is intentional human/agent work — no auto-promotion to memory. Use `get_staging_inbox` (grouped by source) then `distill_batch` with `source_path` on each item.

## Config

`~/.agents/memory/ingest.json` (seed from `examples/ingest.example.json`):

```json
{
  "version": 1,
  "extract_max_bullets": 100,
  "staging_nag_threshold": 50,
  "sources": [
    {
      "id": "openai-export",
      "kind": "openai-export",
      "label": "ChatGPT export",
      "paths": [],
      "globs": ["~/Downloads/*chatgpt*"],
      "catalog": true,
      "extract": true
    },
    {
      "id": "agent-transcripts",
      "kind": "agent-jsonl",
      "label": "your Agent transcripts",
      "paths": ["~/.cursor/projects/*/agent-transcripts"],
      "catalog": true,
      "extract": true
    }
  ]
}
```

Legacy keys (`openai_export_globs`, `chat_sources`) normalize to `sources[]`.

### Source kinds

| kind | Catalog | Extract |
|------|---------|---------|
| `openai-export` | titles from `conversations-*.json` | filtered user lines |
| `agent-jsonl` | Cursor/agent transcript jsonl | user `<user_query>` / text |
| `copilot-jsonl` | VS Code Copilot sessions | user messages |
| `claude-jsonl` | Claude Code project jsonl | user messages |
| `antigravity-brain` | brain folder titles | artifact bullets + `USER_INPUT` from transcript |
| `pi-jsonl` | Pi session jsonl | user messages |

### Antigravity brain layout (reference implementation)

Still under the Gemini product home (not `%APPDATA%` on Windows):

| Surface | Brain root |
|---------|------------|
| Antigravity IDE | `~/.gemini/antigravity/brain/<conversation-id>/` |
| Antigravity CLI | `~/.gemini/antigravity-cli/brain/<conversation-id>/` |

Per conversation:

| Path | Role |
|------|------|
| `task.md`, `walkthrough.md`, `implementation_plan.md` | Generated artifacts (catalog title + extract bullets) |
| `.system_generated/logs/transcript.jsonl` | Chat log (`USER_INPUT` / `<USER_REQUEST>` extract) |
| `*.metadata.json`, `*.resolved*` | Tooling sidecars — ignored by ingest |

macOS/Linux use the same `~/.gemini/...` layout; only path separators differ.

Set `"catalog": false` or `"extract": false` to skip a phase per source.

Global options:

| Key | Default | Effect |
|-----|---------|--------|
| `extract_max_bullets` | `100` | Max bullets written per source per extract run (0 = unlimited) |
| `staging_nag_threshold` | `50` | `ingest_status` / MCP `ingest_status` emits `staging.nag` when inbox exceeds this |

Per-source `"extract_max_bullets"` overrides the global cap.

## Layout

```
~/.agents/memory/
  ingest.json
  ingest/state.json          # last run per source
  chats-index.md             # catalog (references only)
  entities/chat-source-*.md  # one card per configured source
  staging/ingest/<id>/captured.md   # extract inbox (not memory)
```

## MCP tools

- `ingest_catalog()` — catalog phase
- `ingest_extract(source_id="")` — extract one or all sources (respects bullet cap)
- `ingest_status()` — JSON summary from `ingest/state.json` + staging bullet count / nag
- `get_staging_inbox()` — grouped staging bullets for distill
- `distill_batch()` / `promote_bullet()` — distill phase (see [`MCP.md`](MCP.md))

## Filters (extract)

Shared with OpenAI export filter: drop PII patterns, how-to prompts, long code dumps, duplicates. Bodies never copy wholesale into memory.

Fixture transcripts: `tests/fixtures/` (one anonymized sample per extract kind). Tests: `tests/test_extract_filters.py`.

## Thin wrappers

- `python -m agent_memory ingest-chats` → `ingest catalog`
- `python -m agent_memory extract-openai` → `ingest extract` for `openai-export` (`--out` keeps legacy JSON)
