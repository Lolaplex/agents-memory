"""Unified CLI: python -m agent_memory <command> …"""
from __future__ import annotations

import sys

USAGE = """Usage: python -m agent_memory COMMAND [args]

Commands:
  sync             Rewrite always-on injection
  inventory        Disk vs PROJECTS.md
  ingest           Catalog / extract pipeline
  consolidate      Move clone leaks into ~/.agents/memory
  extract-openai   Filter ChatGPT export into staging
  mcp              stdio MCP server
  help-json        Machine-readable CLI + injection spec
"""


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0 if args else 2
    if args[0] in ("--help-json", "help-json"):
        from .cli_help import main as help_main

        return help_main(["--help-json"])
    cmd, rest = args[0], args[1:]
    if cmd == "sync":
        from .sync import main as run

        return run(rest)
    if cmd == "inventory":
        from .inventory import main as run

        return run(rest)
    if cmd == "ingest":
        from .ingest import main as run

        return run(rest)
    if cmd in ("ingest-chats", "ingest_chats"):
        from .ingest_chats import main as run

        return run()
    if cmd == "consolidate":
        from .consolidate import main as run

        return run()
    if cmd in ("extract-openai", "extract_openai"):
        from .extract_openai import main as run

        return run(rest)
    if cmd in ("mcp", "mcp-server", "mcp_server"):
        from .mcp_server import main as run

        return run()
    print(f"unknown command: {cmd}\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
