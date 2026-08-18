"""Scan Coding folders vs PROJECTS.md. Optional register/ignore."""
from __future__ import annotations

import argparse
import json
import sys

from store import (
    ignore_slug,
    inventory_report,
    register_project,
    sync_injection,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bestandaufnahme: disk vs local agent memory"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument(
        "--register",
        nargs=4,
        metavar=("SLUG", "PATH", "ROLE", "STACK"),
        help="add/update a project then sync",
    )
    parser.add_argument("--ignore", metavar="SLUG", help="never prompt this folder again")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="rewrite Cursor + Antigravity + Zed injection files",
    )
    parser.add_argument(
        "--no-repos",
        action="store_true",
        help="with --sync, only write global injection (not per-repo rules)",
    )
    args = parser.parse_args()

    if args.register:
        slug, path, role, stack = args.register
        p = register_project(slug, path, role, stack)
        written = sync_injection(include_repos=not args.no_repos)
        print(f"registered {p.slug} -> {p.path}")
        print("synced:")
        for w in written:
            print(f"  {w}")
        return 0

    if args.ignore:
        ignore_slug(args.ignore)
        print(f"ignored {args.ignore}")
        return 0

    report = inventory_report()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"tracked: {len(report['tracked'])}")
        print(f"unknown (on disk, not in memory): {len(report['unknown'])}")
        for u in report["unknown"]:
            print(f"  + {u['slug']}\t{u['path']}")
        print(f"missing (in memory, path gone): {len(report['missing'])}")
        for m in report["missing"]:
            print(f"  - {m['slug']}\t{m['path']}")
        if report["ignored"]:
            print("ignored slugs:", ", ".join(report["ignored"]))
        if not report["unknown"] and not report["missing"]:
            print("memory map matches disk.")

    if args.sync:
        written = sync_injection(include_repos=not args.no_repos)
        print("synced:")
        for w in written:
            print(f"  {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
