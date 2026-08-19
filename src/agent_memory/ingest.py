"""Serial ingest pipeline: catalog -> extract -> (distill via MCP add_memory)."""
from __future__ import annotations

import argparse
import json
import sys

from .ingest_catalog import run_catalog
from .ingest_common import ingest_state_path, load_state
from .ingest_config import list_sources, load_ingest
from .ingest_extractors import run_extract
from .store import ensure_memory_layout


def cmd_catalog(_args: argparse.Namespace) -> int:
    result = run_catalog()
    print(f"catalog: {result['chats_index']}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    result = run_extract(source_id=args.source or "")
    active = 0
    for sid, info in result.get("sources", {}).items():
        if info.get("count", 0) > 0:
            print(f"extract {sid}: {info['count']} bullets -> {info['staging']}")
            active += 1
    if active == 0:
        print("extract: no new bullets extracted from active sources")
    return 0


def cmd_run(_args: argparse.Namespace) -> int:
    run_catalog()
    result = run_extract()
    active_sources = [v for v in result.get("sources", {}).values() if v.get("count", 0) > 0]
    total = sum(v["count"] for v in active_sources)
    if total > 0:
        print(f"run: catalog refreshed, {total} staging bullets across {len(active_sources)} sources")
    else:
        print("run: catalog refreshed, no new staging bullets found")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    cfg = load_ingest()
    state = load_state()
    rows = []
    for src in list_sources(cfg):
        sid = str(src["id"])
        entry = state.get("sources", {}).get(sid, {})
        rows.append(
            {
                "id": sid,
                "kind": src.get("kind"),
                "catalog": src.get("catalog", True),
                "extract": src.get("extract", True),
                "last_catalog": entry.get("last_catalog"),
                "last_extract": entry.get("last_extract"),
                "catalog_count": entry.get("catalog_count"),
                "extract_count": entry.get("extract_count"),
                "staging": entry.get("staging"),
            }
        )
    print(json.dumps({"state_file": str(ingest_state_path()), "sources": rows}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest pipeline: catalog references, extract to staging, distill with MCP add_memory"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog", help="Rebuild chats-index.md and entity reference cards")
    p_extract = sub.add_parser("extract", help="Filter durable lines into staging/ingest/<id>/")
    p_extract.add_argument("--source", help="single source id from ingest.json")
    sub.add_parser("run", help="catalog then extract (all enabled sources)")
    sub.add_parser("status", help="Print ingest/state.json summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_memory_layout()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "catalog":
        return cmd_catalog(args)
    if args.command == "extract":
        return cmd_extract(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "status":
        return cmd_status(args)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
