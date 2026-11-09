---
name: memory-remote
description: Remote memory CLI — connect/push/pull a personal mirror, or attach a shared project snapshot as an extra root. Use when the user mentions remote connect, remote attach, remote push, remote pull, remote serve, or board_attach.json.
---

# memory-remote

Two remotes. Pick one command family. Flags: `python -m agents_memory --help-json` (and `python -m agents_memory remote --help` only if help-json has no `remote` block). Layout of the bundle: [`abi/REMOTE.md`](../../abi/REMOTE.md).

```
- [ ] Which remote: connect (personal) or attach (shared project)
- [ ] Command ran
- [ ] Done condition below is true
```

## Connect — personal mirror

One `USER_MEMORY` (`~/.agents/memory`) replicated to a memory server. Writes `~/.agents/memory/remote_config.json`. Never copies a board tree into this store.

```powershell
python -m agents_memory remote connect <url> --token <token>
python -m agents_memory remote status
python -m agents_memory remote push
python -m agents_memory remote pull
python -m agents_memory remote disconnect
```

Host a server: `python -m agents_memory remote serve --port 8443 --token <token>`.

Done when:

| Command | Observable |
|---------|------------|
| `connect` | `remote_config.json` has that URL; `status` prints REMOTE and health OK |
| `push` / `pull` | stdout counts added/merged/unchanged; exit 0 |
| `disconnect` | `remote_config.json` gone; `status` prints LOCAL |

MCP tools still write **local files**. Push/pull moves the mirror bundle. Chat graves and `.index/` stay on the device.

## Attach — extra project root

Pull a **shared** project snapshot. Does not write `remote_config.json`. Does not replace `USER.md` / `PROJECTS.md`.

```powershell
python -m agents_memory remote attach <memory-url> --slug <agent> --project <local-slug>
```

`<memory-url>` is `https://<board>/projects/<slug>/memory`. `--slug` is `~/.agents/keys/<slug>.ed25519` (`python -m agents_keys did <slug>`). `--token` is a spare bearer, not the model. `--project` selects the registered clone when the URL slug differs.

Dest:

- Registered clone → `<repo>/.agents/memory` (only — register the project first)
- Not registered → attach fails; no `~/.agents/shared/` shadow tree and no copy under `~/.agents/memory/`

Dest must not sit inside `~/.agents/memory`. Sidecar: `~/.agents/memory/board_attach.json`.

Only these markdown prefixes are written: `decisions/` `plans/` `tasks/` `waves/` `roadmap/` `staging/` `notes/` `research/`.

Done when: stdout `Wrote extra root` and that path is the dest above. `attach` is **pull**. Writes go to the board HTTP API (`POST …/memory`), not `remote push`.

Auth failures (401/403/404) come from the board. Stop; do not invent a project or a DID.

## Pick

| Intent | Command |
|--------|---------|
| This machine's identity + notes on a VPS | `connect` then `push` / `pull` |
| Shared project tree next to a clone | `attach` |
| Stop replicating identity | `disconnect` |

`connect` and `attach` are both valid on one machine. They are different roots.
