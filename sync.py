"""Rewrite always-on injection files for Cursor + Antigravity."""
from __future__ import annotations

import argparse
import sys

from store import merge_cursor_mcp, sync_injection, user_profile_looks_blank


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-repos",
        action="store_true",
        help="only global Gemini/Cursor files, skip per-repo copies",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="copy example memory files if missing, sync injection, merge ~/.cursor/mcp.json",
    )
    args = parser.parse_args()
    written = sync_injection(include_repos=not args.no_repos)
    print(f"wrote {len(written)} files")
    for w in written:
        print(w)
    if args.init:
        print(merge_cursor_mcp())
        if user_profile_looks_blank():
            print(
                "\nUSER.md still blank (Name:). Fill ~/.agents/memory/USER.md + scan.json, "
                "then run: python sync.py"
            )
        print("\nReload Cursor so MCP `agent-memory` appears.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
