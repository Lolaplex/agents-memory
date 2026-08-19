# Extract test fixtures

Synthetic, anonymized samples for ingest extract keep/drop tests.

- No real usernames, repo paths, API keys, or chat titles from production machines.
- Each kind includes at least one **keep** line (durable rule/fact) and **drop** lines (how-to prompt, too-short filler).
- PII patterns use `@example.com` placeholders; extract scrub replaces secrets before filtering.

Kinds mirror `ingest.json` extract handlers:

| folder | kind |
|--------|------|
| `agent-jsonl/` | `agent-jsonl` |
| `copilot-jsonl/` | `copilot-jsonl` |
| `openai-export/` | `openai-export` |
| `claude-jsonl/` | `claude-jsonl` |
| `pi-jsonl/` | `pi-jsonl` |
| `antigravity-brain/` | `antigravity-brain` — `<id>/task.md`, `walkthrough.md`, `implementation_plan.md`, `.system_generated/logs/transcript.jsonl` |
