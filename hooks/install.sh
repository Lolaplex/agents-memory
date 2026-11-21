#!/usr/bin/env bash
# Install living-software discipline: core.hooksPath points at this repo's hooks/
# directory (mode 100755 — C16). Do not point core.hooksPath at /dev/null.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
git config core.hooksPath hooks
chmod +x hooks/commit-msg hooks/commit-msg.cjs hooks/pre-commit hooks/post-commit hooks/post-commit.cjs
mkdir -p concepts signals scripts
[ -e concepts/.gitkeep ] || : > concepts/.gitkeep
[ -f scripts/git_wall_allowlist.txt ] || printf '# git_wall allowlist — grandfather only\n' > scripts/git_wall_allowlist.txt
for sig in hooks/signals/*.signal; do
  [ -e "$sig" ] || continue
  dest="signals/$(basename "$sig")"
  [ -e "$dest" ] || cp "$sig" "$dest"
done
echo "core.hooksPath=hooks"
echo "Run: git -c core.hooksPath=hooks -c commit.template= commit"