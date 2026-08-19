"""Rewrite always-on injection files for Cursor + Antigravity + Zed."""
from __future__ import annotations

import argparse
import sys

from store import merge_cursor_mcp, merge_zed_mcp, sync_injection, user_profile_looks_blank


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-repos",
        action="store_true",
        help="only global Gemini/Cursor/Zed files, skip per-repo copies",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="copy example memory files if missing, sync injection, merge Cursor + Zed MCP",
    )
    args = parser.parse_args()
    written, warnings = sync_injection(include_repos=not args.no_repos)
    print(f"wrote {len(written)} files")
    for w in written:
        print(w)
    for warn in warnings:
        print(f"WARN {warn}")
    if args.init:
        print(merge_cursor_mcp())
        print(merge_zed_mcp())
        if user_profile_looks_blank():
            print(
                "\nUSER.md still blank (Name:). Fill ~/.agents/memory/USER.md + scan.json, "
                "then run: python sync.py"
            )
        print("\nReload Cursor / Zed so MCP `agent-memory` appears.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
