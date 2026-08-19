---
name: memory-distill
description: Destilliert rohe Staging-Inbox-Bullets (staging/captured.md) in bleibende, getypte Memory-Dateien. Verwende diesen Skill, wenn der User 'distill', 'Staging aufräumen', 'Inbox abarbeiten', 'Memory verdichten' sagt oder nach einem Ingest-Lauf.
---

# memory-distill

Staging inbox is temporary. Distill durable facts into typed paths, discard ephemeral noise.

## Workflow

1. Call MCP `get_staging_inbox(limit=20)` to fetch un-distilled bullets.
2. For each bullet, evaluate:
   - **Keep (Durable Fact)**: Core decisions, tech stack choices, preferences, personal workflow rules, durable architecture constraints.
     - Select target `kind`: `concept`, `entity`, `workflow`, `note`, `project`, `decision`, `proposed`, `implemented`.
     - Assign clean slug `name` (and `project` / `collection` if applicable).
   - **Discard (Noise / Ephemeral)**: One-off debug talk, temporary questions, code snippets with no lasting rule, accidental transcript dumps.
3. Call MCP `distill_batch(items_json)` with the classified items:
   ```json
   [
     {"bullet": "Always use Tailwind v3 for customs", "kind": "note", "name": "stack", "project": "customs"},
     {"bullet": "Can you check line 40 of main.py", "discard": true}
   ]
   ```
4. Repeat until `get_staging_inbox` returns empty.
5. Report a short summary of promoted and discarded items to the human.
