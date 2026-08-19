"""Move live markdown out of the engine clone into ~/.agents/memory."""
from __future__ import annotations

import sys

from .store import consolidate_repo_leaks, ensure_memory_layout


def main() -> int:
    ensure_memory_layout()
    moved = consolidate_repo_leaks()
    if not moved:
        print("nothing to consolidate")
        return 0
    print(f"consolidated {len(moved)} paths:")
    for line in moved:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
