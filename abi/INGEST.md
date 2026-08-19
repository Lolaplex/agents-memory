# Ingest pipeline

Version: see [`VERSION`](VERSION)

Chat and brain stores stay on disk in product folders. Ingest turns them into **searchable references** and optional **staging bullets** for distillation into typed memory under `~/.agents/memory`.

## Phases (serial)

| Phase | Command | Effect | Revert |
|-------|---------|--------|--------|
| **Catalog** | `python -m agents_memory ingest catalog` | `chats-index.md` + `entities/chat-source-<id>.md` | Delete cards; rebuild index |
| **Extract** | `python -m agents_memory ingest extract [--source ID]` | `staging/ingest/<id>/captured.md` | Delete staging file |
| **Distill** | MCP `promote_bullet` / `distill_batch` / skill `memory-distill` | Typed markdown in `concepts/`, `notes/`, etc. | Edit or delete memory file |

Run both catalog and extract: `python -m agents_memory ingest run`. Status: `python -m agents_memory ingest status` → `ingest/state.json` plus staging nag.

Distill is intentional human/agent work — no auto-promotion to memory. Use `get_staging_inbox` (grouped by source) then `distill_batch` with `source_path` on each item.

## Division of labor

| Who | Phases | Why |
|-----|--------|-----|
| **Python (this repo)** | Catalog + extract | Cheap, deterministic: walk paths, parse json/jsonl, pull titles, drop tool calls / assistant blobs / PII / how-tos, dedupe, cap bullets → **clean staging** |
| **Agent (you)** | Distill | Judgment: durable fact vs noise, pick `kind` + `name`, promote or discard |

Extract is not “the AI reads raw graves.” Distill is not “Python guesses memory.” Staging is the handoff: filtered bullets in, typed markdown out.

Source **`id`** is product-specific (`cursor`, `vscode-copilot`, `openai-export`, …). **`kind`** is the shared parser (`agent-jsonl`, `copilot-jsonl`, …) — same extract filters, different paths.

## Uniform contract (every source)

Same rules for **every** configured path in `ingest.json` — Cursor transcripts, Open AI surfaces, Copilot, Claude Code, Antigravity brains, Pi, Windsurf, Cline, etc. No provider gets wholesale import.

| Phase | What lands in `~/.agents/memory` | What stays on disk |
|-------|----------------------------------|--------------------|
| **Catalog** | `chats-index.md` rows + `entities/chat-source-<id>.md` — **title hints and paths only** | Full jsonl, export shards, brain folders, message sidecars |
| **Extract** | Filtered **bullets** in `staging/ingest/<id>/captured.md` (revertible inbox, capped per run) | Everything else in the product store |
| **Distill** | Typed markdown (`concepts/`, `notes/`, `decisions/`, …) only when you call `promote_bullet` / `distill_batch` / `add_memory` | Staging bullet removed after promote; archives untouched |

**Never (any source):**

- Copy transcript bodies, export JSON, or brain jsonl into typed memory or always-on inject
- Auto-promote staging → memory without explicit distill
- Index product graves in `search_memory` — it unions markdown under `~/.agents/memory` and registered repos only. Use catalog paths to open the real file on disk

Per source, set `"catalog": false` or `"extract": false` to skip a phase. Extract always uses shared filters (PII, how-tos, code dumps, length, dedupe) — see [Filters](#filters-extract).

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
      "label": "Open AI — GDPR export",
      "paths": [],
      "globs": ["~/Downloads/*chatgpt*", "~/Downloads/*openai*export*"],
      "catalog": true,
      "extract": true
    },
    {
      "id": "cursor",
      "kind": "agent-jsonl",
      "label": "Cursor",
      "paths": ["~/.cursor/projects/*/agent-transcripts"],
      "catalog": true,
      "extract": true
    }
  ]
}
```

Legacy keys (`openai_export_globs`, `chat_sources`) normalize to `sources[]`. Renamed source ids (`agent-transcripts` → `cursor`, etc.) migrate on **`python -m agents_memory sync`**: staging folder, `ingest/state.json`, entity cards. Re-extract is **not** automatic — run `ingest extract` when you want fresh bullets.

### Source kinds

All kinds follow the [uniform contract](#uniform-contract-every-source).

| kind | Catalog (link for search) | Extract (filter → staging) | Ignored on extract |
|------|---------------------------|----------------------------|--------------------|
| `openai-export` | title + shard path from GDPR export `conversations-*.json` | filtered user lines | assistant turns, metadata |
| `agent-jsonl` | workspace + transcript path | user `<user_query>` / text | tool calls, assistant blobs |
| `copilot-jsonl` | session path | user messages | assistant / system |
| `claude-jsonl` | project jsonl path | user messages | assistant / tool results |
| `antigravity-brain` | conversation folder path | artifact bullets + `USER_INPUT` / `<USER_REQUEST>` from transcript | MODEL lines, tool dumps, file views, sidecars |
| `pi-jsonl` | session jsonl path | user messages | assistant / session meta |

### Open AI surfaces (reference implementation)

Open AI ships **several** local/cloud stores. Only **`openai-export`** (GDPR/data export zip or unpacked folder) is implemented in this repo today. Configure others when a parser exists — same [uniform contract](#uniform-contract-every-source) either way.

| Surface | Where bodies live | Ingest today | Notes |
|---------|-------------------|--------------|-------|
| **GDPR / data export** | `~/Downloads/…` zip or folder with `conversations-*.json` | `kind: openai-export` | One-time export from ChatGPT settings — not live chat |
| **Codex CLI sessions** | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` (`.zst` when cold) | not yet | Live Codex rollouts; internal schema — catalog + user-line extract when added |
| **ChatGPT desktop app** | `%LOCALAPPDATA%/Packages/OpenAI.ChatGPT-Desktop_*/LocalCache/Roaming/ChatGPT/` (LevelDB / IndexedDB) | not yet | Live app cache — not the GDPR export |
| **Open AI memory** (`/memory`) | Codex: `~/.codex/memories/`; ChatGPT: product cloud + app (`/memories`, Settings → Personalization) | not ingest | **Their** durable memory layer, not chat logs. Do not wholesale-import. Distill chosen facts into `~/.agents/memory/` (`entities/`, `notes/`) for cross-agent use |

`id` / `kind` stay `openai-export` for the GDPR export source (stable staging path). **Label** should read **Open AI — GDPR export**, not “ChatGPT” or generic “OpenAI”.

### Antigravity brain layout (reference implementation)

Still under the Gemini product home (not `%APPDATA%` on Windows):

| Surface | Brain root |
|---------|------------|
| Antigravity (IDE) | `~/.gemini/antigravity/brain/<conversation-id>/` |
| Antigravity IDE (alternate install) | `~/.gemini/antigravity-ide/brain/<conversation-id>/` |
| Antigravity CLI | `~/.gemini/antigravity-cli/brain/<conversation-id>/` |

Many machines have **more than one** of these (e.g. IDE + CLI, or `antigravity` + `antigravity-ide` after upgrades). List every `*/brain` root that exists in `ingest.json` — overlap in conversation IDs is fine; extract dedupes bullets within a run.

Per conversation:

| Path | Role |
|------|------|
| `task.md`, `walkthrough.md`, `implementation_plan.md` | Generated artifacts (catalog title + extract bullets) |
| `.system_generated/logs/transcript.jsonl` | Chat log — extract `USER_INPUT` / `<USER_REQUEST>` only |
| `.system_generated/logs/transcript_full.jsonl` | Same contract as other logs: catalog pointer only unless extract adds the same user filter |
| `.system_generated/messages/*.json` | Sidecars — catalog pointer only unless extract adds user-only filter |
| `*.metadata.json`, `*.resolved*` | Tooling sidecars — ignored |

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

Shared across **all** extract kinds (see [uniform contract](#uniform-contract-every-source)): drop PII patterns, how-to prompts, long code dumps, duplicates. User/durable lines only — never copy bodies wholesale into memory or always-on inject.

Fixture transcripts: `tests/fixtures/` (one anonymized sample per extract kind). Tests: `tests/test_extract_filters.py`.

## Thin wrappers

- `python -m agents_memory ingest-chats` → `ingest catalog`
- `python -m agents_memory extract-openai` → `ingest extract` for `openai-export` (Open AI GDPR export; `--out` keeps legacy JSON)
