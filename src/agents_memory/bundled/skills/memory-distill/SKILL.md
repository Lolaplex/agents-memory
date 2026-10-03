---
name: memory-distill
description: Destilliert rohe Staging-Inbox-Bullets (staging/captured.md) in bleibende, getypte Memory-Dateien. Verwende diesen Skill, wenn der User 'distill', 'Staging aufräumen', 'Inbox abarbeiten', 'Memory verdichten' sagt oder nach einem Ingest-Lauf oder Staging-Nag.
---

# memory-distill

Staging inbox is temporary — from **any** ingest source (`staging/ingest/<id>/captured.md`) or project/user staging. Distill durable facts into typed paths; discard ephemeral noise.

When remote-connected, all distill tools run **locally**; writes auto-push the mirror bundle to cloud. Other devices pull to stay current.

## Pipeline order (connected mode)

1. **Ingest** (local): `ingest_catalog` → `ingest_extract` — auto-pushes staging.
2. **Distill** (local): `get_staging_inbox` → classify → `distill_batch` — auto-pushes typed memory + repo mirrors.
3. Pull on MCP start / periodic pull on other devices updates local files.

When staging inbox depth reaches `staging_nag_threshold` (default 50):
- **50–74:** soft notice — distill during memory maintenance, not on every unrelated tool call.
- **≥75** (`staging_force_threshold`): strong notice — prioritize `auto_distill` + `distill_batch` before other memory MCP work this session.
- After **ingest extract** only: deterministic noise pass when inbox >= `auto_distill_noise_threshold` (discards obvious noise; no silent promote).
- MCP start noise pass: off by default (`auto_distill_on_start: false`).

Inbox→0 for non-noise bullets remains agent judgment via `distill_batch`.

## Standard 2-Step Agent Workflow

1. **Step 1: Run Auto-Distill (Noise Pruning & Heuristics)**
   - Call MCP `auto_distill(limit=50, discard_noise=true)` (or CLI: `python -m agents_memory distill --auto`).
   - Deterministically removes build/test logs, SQL/code dumps, bug reports, questions, and ephemeral banter.
   - Automatically promotes clear preferences (`always`, `never`, `prefer`, `stack:`, `datenschutz`).
   - Returns a structured list of remaining `candidates` with suggested targets (`suggested_kind`, `suggested_name`).

2. **Step 2: Confirm Remaining Candidates via Distill Batch**
   - If `candidates` remain (typically 1–5 bullets):
   - Review the candidate list returned by `auto_distill`.
   - Call MCP `distill_batch(items)` in a single call to promote or discard the remaining bullets:
     ```json
     [
       {
         "bullet": "Die Controls sollen alle einzeln switchable sein",
         "kind": "note",
         "name": "ux",
         "project": "veadio",
         "source_path": "user/staging/ingest/antigravity/captured.md"
       },
       {
         "bullet": "Can you check line 40 of main.py",
         "discard": true,
         "source_path": "user/staging/ingest/cursor/captured.md"
       }
     ]
     ```
   - Inbox drops to 0 cleanly in one turn.
3. `distill_batch` automatically syncs to all IDEs/CLIs upon completion.
