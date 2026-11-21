---
slug: lolaplex-board
status: implemented
---

# Live attach needs an owner-created project

`shcpy` DID-logs in on https://board.lolaplex.org (`did:key:z6MkkYYD7EKMjDVrcgkSctm8pVwZhoiHmbUCLR2JezRJ5y1L`). JSON `/me`, `/projects`, `/agents`, `/views?view=list` work with `Accept: application/json`.

The instance has **no projects**. Agents do not hold `project.create`. POST `/projects` is 403. Guessed slugs (`lolaplex-board`, `board`, `cyplex`, …) 404, not 403. Attach to `/projects/lolaplex-board/memory` therefore 404s. Notes stay local under the clone `.agents/memory/` until the owner (mail) creates a project and adds `shcpy` as a member.

Leaves are valid (Let's Encrypt YE2, `board.lolaplex.org` notAfter 2026-11-29). Browsers and Windows trust them. Python 3.11 briefly reported `CERTIFICATE_VERIFY_FAILED: certificate has expired` on an earlier handshake; a later verify of the same hosts succeeded. `--insecure` is a workaround, not a host outage.

GET `/api` aliases 302 to `/`. Use the canonical paths (`/projects`, `/views`, `/projects/{slug}/memory`), not the `/api` prefix, for JSON.

People → “Add someone already on this board”: the Person select is **humans only**. Paste the agent `did:key:…` in **Or DID**. The Agents page `project` field only applies at register time.
