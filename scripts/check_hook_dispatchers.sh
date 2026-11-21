#!/usr/bin/env bash
# CI leg: tracked hook dispatchers must be executable in the git index (100755).
# With core.hooksPath=hooks, mode 100644 means git silently skips the hook.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
DISPATCHERS=(commit-msg pre-commit post-commit install.sh)
FAIL=0
for f in "${DISPATCHERS[@]}"; do
  line="$(git ls-files -s "hooks/$f" || true)"
  if [ -z "$line" ]; then
    echo "::error::hooks/$f is not tracked"
    FAIL=1
    continue
  fi
  mode="${line%% *}"
  if [ "$mode" != "100755" ]; then
    echo "::error::hooks/$f must be git index mode 100755 (got $mode); run: git update-index --chmod=+x hooks/$f"
    FAIL=1
  fi
done
if [ "$FAIL" -ne 0 ]; then
  echo "hook dispatcher mode check FAILED"
  exit 1
fi
echo "hook dispatchers: all 100755 in index"