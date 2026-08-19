# Ingest pipeline

Version: 1.0.0 (see `abi/VERSION`)

Chat and brain stores stay on disk in product folders. Ingest turns them into **searchable references** and optional **staging bullets** for distillation into typed memory under `~/.agents/memory`.

## Phases (serial)

| Phase | Command | Effect | Revert |
|-------|---------|--------|--------|
| **Catalog** | `python -m agent_memory ingest catalog` | `chats-index.md` + `entities/chat-source-<id>.md` | Delete cards; rebuild index |
| **Extract** | `python -m agent_memory ingest extract [--source ID]` | `staging/ingest/<id>/captured.md` | Delete staging file |
| **Distill** | MCP `add_memory(kind=..., name=...)` | Typed markdown in `concepts/`, `notes/`, etc. | Edit or delete memory file |

Run both catalog and extract: `python -m agent_memory ingest run`. Status: `python -m agent_memory ingest status` → `ingest/state.json`.

Distill is intentional human/agent work — no auto-promotion to memory.

## Config

`~/.agents/memory/ingest.json` (seed from `examples/ingest.example.json`):

```json
{
  "version": 1,
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
| `antigravity-brain` | brain folder titles | bullet lines from task/walkthrough md |
| `pi-jsonl` | Pi session jsonl | user messages |

Set `"catalog": false` or `"extract": false` to skip a phase per source.

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
- `ingest_extract(source_id="")` — extract one or all sources
- `ingest_status()` — JSON summary from `ingest/state.json`

## Filters (extract)

Shared with OpenAI export filter: drop PII patterns, how-to prompts, long code dumps, duplicates. Bodies never copy wholesale into memory.

## Thin wrappers

- `python -m agent_memory ingest-chats` → `ingest catalog`
- `python -m agent_memory extract-openai` → `ingest extract` for `openai-export` (`--out` keeps legacy JSON)
