# Memory kinds (`add_memory`)

Conforming MCP servers expose `add_memory(fact, kind=, name=, project=, collection=)`.
Bare facts with no `kind`/`name` and no `project=` are rejected.

## User store kinds

| kind | Path | Notes |
|------|------|-------|
| `concept` | `~/.agents/memory/concepts/<name>.md` | Reusable ideas |
| `entity` | `~/.agents/memory/entities/<name>.md` | Named people, orgs, products |
| `workflow` | `~/.agents/memory/workflows/<name>.md` | Procedures |
| `project` | `~/.agents/memory/projects/<slug>/README.md` | Project link card (usually via `register_project`) |
| `note` | `~/.agents/memory/notes/<collection>/<name>.md` | `collection=` required (guide folders or new folder) |
| `scratch` | `~/.agents/memory/notes/scratch/<name>.md` | Inbox; distill or delete |

### Temporal kinds (user store)

| kind | Path | Notes |
|------|------|-------|
| `chronicle` | `~/.agents/memory/events/chronicle/<name>.md` | Append-only beats — ordered record of what happened |
| `event` | `~/.agents/memory/events/<name>.md` | Generic append-only event log (optional; chronicle is the primary temporal kind) |

## Project store kinds (`project=` required)

| kind | Path | Notes |
|------|------|-------|
| *(empty kind)* | `<repo>/.agents/memory/facts.md` | Direct fact; skips staging |
| `fact` / `facts` | `<repo>/.agents/memory/facts.md` | Direct project fact |
| `staging` | `<repo>/.agents/memory/staging/captured.md` | Explicit inbox; distill then delete |
| `research` | `<repo>/.agents/memory/research/<name>.md` | Input, not a decision |
| `plans` | `<repo>/.agents/memory/plans/001-<name>.md` | Sequential |
| `tasks` | `<repo>/.agents/memory/tasks/001-<name>.md` | Sequential |
| `waves` | `<repo>/.agents/memory/waves/001-<name>.md` | Sequential |
| `roadmap` | `<repo>/.agents/memory/roadmap/001-<name>.md` | Sequential |
| `decision` | `<repo>/.agents/memory/decisions/001-<name>.md` | Numbered decision record |
| `proposed` | `<repo>/.agents/memory/notes/proposed/<class>/001-<name>.md` | `collection=` = note class |
| `implemented` | `<repo>/.agents/memory/notes/implemented/<class>/…` | Revise in place |
| `rejected` | `<repo>/.agents/memory/notes/rejected/<class>/…` | Frozen after reject |
| `ritual` | `<repo>/.agents/memory/rituals/baton.md` | Mutable by ritual MCP only (`get_baton`/`set_baton`). Session handoff marker |

Note classes (guide): `feature` `bug-fix` `simplification` `architecture` `process` `testing`.

## Mutability hints

| Behavior | Kinds |
|----------|-------|
| Inbox (append, distill, delete) | `staging`, `scratch`, bare `project=` |
| New sequential file per tranche | `plans`, `tasks`, `waves`, `roadmap`, `decisions`, lifecycle notes |
| Revise file in place | `research`, `implemented`, `decision`, `concept`, `entity`, `workflow` |
| Append-only | `chronicle`, `event` |
| Mutable by ritual MCP only | `ritual` (baton) |
| Frozen | `rejected` |

Do not store transcripts, emails, phones, tokens, or one-shot how-tos as durable memory.
