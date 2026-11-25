---
type: belief
id: frag-memory-write-roots-exclude-the-workspace-dir
provenance: 2026-11-24 — R04 review of PR #42: POSIX lstrip order, ws/ confinement base, partial fts.sqlite
ts: 2026-11-24
---

Memory tools confine to memory roots only: the user store, the rules
directory, and each registered project's `.agents/memory`. The workspace
directory itself is never a store root — it carries host config
(`mcp.json`, `config.json`), the state db (`store.db`), and module and
schedule manifests, so a `ws/` prefix or an absolute path inside it must
raise `ValueError`, never confine. Granting it once granted overwrite of
the workspace's own control files — a takeover primitive, not a feature.

Two adjacent rulings. Absolute paths classify as absolute before any
separator normalization: on POSIX a stripped leading `/` smuggles an
outside path through as a false relative and double-joins a legit one.
And an absent `fts.sqlite` stays absent on single-doc upserts — a 1-doc
index is worse than none, because its existence suppresses the full
rebuild that the next search needs to see the corpus already on disk.

Open questions: whether orphan `fts.sqlite` files should self-heal via
rebuild-on-open instead of deferring to first search; whether `rules/`
writes keep a dedicated refusal path or fold into one confinement table.
