# 009 Splice AGENTS.md, do not replace it

`sync --init` must not replace an existing `AGENTS.md`. Upsert `<!-- agents-memory-sync -->` … `<!-- /agents-memory-sync -->` and leave every other line.

Host copies (Gemini, Zed, `~/.claude/AGENTS.md`) are real files with that block, not a bind to `~/.agents/AGENTS.md`. `CLAUDE.md` is bound only when it has no text outside the block.

Repo-root `AGENTS.md` is not a sync target. Per-repo inject is `<repo>/.agents/AGENTS.md`, also spliced.
