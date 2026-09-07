"""Rewrite always-on injection for your Agent."""
from __future__ import annotations

import argparse
import sys

from .cli_help import emit_help_json
from .ingest_config import migrate_ingest_legacy_ids
from .store import consolidate_repo_leaks, merge_agent_mcp, merge_zed_mcp, sync_injection, user_profile_looks_blank


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rewrite always-on injection for your Agent.",
        epilog="Machine-readable: python -m agents_memory sync --help-json. Full spec: python -m agents_memory --help-json.",
    )
    parser.add_argument(
        "--no-repos",
        action="store_true",
        help="only global inject files, skip per-repo copies",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="copy example memory files if missing, sync injection, merge your Agent MCP config",
    )
    parser.add_argument(
        "--help-json",
        action="store_true",
        help="print machine-readable CLI spec as JSON and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if "--help-json" in argv:
        emit_help_json(argv, build_parser(), name="sync")
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    written, warnings = sync_injection(include_repos=not args.no_repos)
    migrated = migrate_ingest_legacy_ids()
    print(f"wrote {len(written)} files")
    for w in written:
        print(w)
    for warn in warnings:
        print(f"WARN {warn}")
    for note in migrated:
        print(f"ingest {note}")
    if args.init:
        moved = consolidate_repo_leaks()
        if moved:
            print(f"consolidated {len(moved)} clone leaks into ~/.agents/memory")
        print(merge_agent_mcp())
        print(merge_zed_mcp())
        if user_profile_looks_blank():
            print(
                "\nUSER.md still blank (Name:). Fill ~/.agents/memory/USER.md + scan.json, "
                "then run: python -m agents_memory sync"
            )
        print("\nReload your Agent so MCP `agents-memory` appears.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
