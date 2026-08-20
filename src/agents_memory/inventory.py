"""Scan Coding folders vs PROJECTS.md. Optional register/ignore."""
from __future__ import annotations

import argparse
import json
import sys

from .cli_help import emit_help_json
from .store import (
    ignore_slug,
    inventory_report,
    register_project,
    sync_injection,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bestandaufnahme: disk vs local agent memory",
        epilog="Machine-readable: python -m agents_memory inventory --help-json. Full spec: python -m agents_memory --help-json.",
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
        "--repair-moved",
        action="store_true",
        help="automatically update paths for moved repositories and sync",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="rewrite your Agent injection files",
    )
    parser.add_argument(
        "--no-repos",
        action="store_true",
        help="with --sync, only write global injection (not per-repo rules)",
    )
    parser.add_argument(
        "--help-json",
        action="store_true",
        help="print machine-readable CLI spec as JSON and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    argv = list(argv if argv is not None else sys.argv[1:])
    if "--help-json" in argv:
        emit_help_json(argv, build_parser(), name="inventory")
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.repair_moved:
        report = inventory_report()
        repaired = 0
        for mv in report.get("moved", []):
            slug = mv["slug"]
            new_path = mv["new_path"]
            p_exist = next((p for p in report["tracked"] if p["slug"] == slug), None)
            role = p_exist["role"] if p_exist else "unclassified"
            stack = p_exist["stack"] if p_exist else "—"
            status = p_exist.get("status", "active") if p_exist else "active"
            register_project(slug, new_path, role=role, stack=stack, status=status)
            print(f"repaired path for {slug} -> {new_path}")
            repaired += 1
        if repaired:
            sync_injection(include_repos=not args.no_repos)
            print(f"successfully repaired {repaired} moved project(s).")
        else:
            print("no moved projects detected.")
        return 0

    if args.register:
        slug, path, role, stack = args.register
        p = register_project(slug, path, role, stack)
        written, _ = sync_injection(include_repos=not args.no_repos)
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
            sug = f" (suggested: {u['suggested_slug']})" if "suggested_slug" in u else ""
            print(f"  + {u['slug']}{sug}\t{u['path']}")
        print(f"missing (in memory, path gone): {len(report['missing'])}")
        for m in report["missing"]:
            print(f"  - {m['slug']}\t{m['path']}")
        if report.get("moved"):
            print(f"moved (detected repo path changes): {len(report['moved'])}")
            for mv in report["moved"]:
                print(f"  ~ {mv['slug']}: {mv['old_path']} -> {mv['new_path']}")
        if report["ignored"]:
            print("ignored slugs:", ", ".join(report["ignored"]))
        if not report["unknown"] and not report["missing"] and not report.get("moved"):
            print("memory map matches disk.")

    if args.sync:
        written, _ = sync_injection(include_repos=not args.no_repos)
        print("synced:")
        for w in written:
            print(f"  {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
