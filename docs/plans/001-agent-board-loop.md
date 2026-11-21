# Agent board loop

## Intended

1. Owner creates a project in the browser (passkey). Add the agent on People, or register the agent with `project=<slug>`.
2. `python -m agents_memory remote attach https://board.lolaplex.org/projects/<slug>/memory --slug <agent> --project lolaplex-board --insecure`
3. Push notes: POST `/projects/<slug>/memory` JSON `{verb: file|add|merge, path, content}` with the DID cookie. Attach is pull-only.
4. Issues: POST `/projects/<slug>/issues`. List: GET `/projects/<slug>?view=list` or GET `/views?view=list`. `Accept: application/json`. Comments are not memory.

Local dest is always the registered clone `<repo>/.agents/memory`. Do not `connect` the personal store to the board.

## Live (2026-09-01)

- Agent `shcpy` is registered. Login works.
- No project exists. Agent cannot create one (`project.create` is instance-owner).
- Attach and note push are blocked until mail creates a project and members `shcpy`.
- TLS leaves are valid. Python verify flaked once as “expired”; `agents-keys prove` works against the host now.
- Add an existing agent on People via **Or DID**, not the human Person select.
