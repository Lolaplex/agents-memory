# Agent memory layout

User store `~/.agents/memory` plus `<repo>/.agents/memory`. Search unions all markdown.

One home per fact. Path encodes where it belongs. No dump files (`facts.md`, `MEMORY.md`).

## User (`~/.agents/memory`)

| Folder | Holds |
|--------|--------|
| `concepts/` `entities/` `workflows/` | Cross-cutting ideas, named things, procedures |
| `projects/<slug>/` | **Link** to a real tree (`path` in README). Not a second copy of the repo. |
| `notes/<collection>/` | Personal notes. Guide collections below — add a folder when a fact does not fit. |

Note collection **guides** (not a closed set): `projects/` `interests/` `education/` `finance/` `family/` `preferences/` `programming/` `work/` `certifications/` `scratch/`.
`notes/projects/<slug>/` is personal notes *about* a project.

## Project (`<repo>/.agents/memory`)

Each repo owns its work notes. Staging is inbox. Research is input. Numbered files are ordered work. Lifecycle notes sit under `notes/proposed|implemented|rejected`.

| Folder | Role |
|--------|------|
| `staging/` | **Inbox only.** `captured.md` / `from-chats.md`. Distill, then empty. |
| `research/` | Input. Not a decision. |
| `plans/` `tasks/` `waves/` `roadmap/` | Ordered work. Files are `001-topic.md`, `002-…`. |
| `notes/proposed/<class>/` | In flight. |
| `notes/implemented/<class>/` | Shipped rationale — **revise in place** when code/paths change (facts track reality). |
| `notes/rejected/<class>/` | Declined; **frozen** after reject. |
| `decisions/` | Numbered records: `001-title.md`. **Revise present tense** when the contract changes; new number when superseding. |

Note classes (guide): `feature` `bug-fix` `simplification` `architecture` `process` `testing`.

**Mutability:** staging/scratch = inbox (append, then distill/delete). Sequential work = new `001-` file per tranche; edit the *current* plan/tasks in place; archive a superseded plan as `plans/PLAN-NNN.md` instead of overwriting it. Research = topical files you revise. Implemented notes and decisions = edit the file when shipped reality changes — do not only append forever. Rejected = frozen. User `concepts/`/`entities/`/`workflows/` = grow by append or edit the one home.

## Instruction files

See [`INJECTION.md`](INJECTION.md). Always-on injection: `USER.md` + `PROJECTS.md` only.
Chat bodies stay in product folders. `chats-index.md` is the catalog (pointers for every configured ingest source — not a transcript dump).
