import sys
from pathlib import Path

# Bootstrap src/ on sys.path if invoked without editable install
_SRC_DIR = str(Path(__file__).resolve().parent.parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

USAGE = """Usage: python -m agent_memory COMMAND [args]

Commands:
  sync             Rewrite always-on injection
  inventory        Disk vs PROJECTS.md
  ingest           Catalog / extract pipeline
  consolidate      Move clone leaks into ~/.agents/memory
  extract-openai   Filter ChatGPT export into staging
  distill          Inspect staging inbox for distillation
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
    if cmd == "distill":
        from .store import get_staging_inbox

        inbox = get_staging_inbox(limit=15)
        if inbox["total"] == 0:
            print("Staging inbox is empty (all caught up).")
            return 0
        print(f"Staging inbox: {inbox['total']} bullets ({inbox['shown']} shown)")
        for group in inbox["groups"]:
            label = group.get("source") or group.get("file")
            extra = ""
            if group.get("truncated"):
                extra = f" (showing {group['count']} of {group['count']}+)"
            print(f"\n## {label}{extra}")
            for item in group["bullets"]:
                title = item.get("title") or ""
                prefix = f"[{title}] " if title else ""
                print(f"- {prefix}{item.get('text') or item.get('bullet')}")
        print("\nTo distill, tell your Agent: 'run memory-distill' or use the memory-distill skill.")
        return 0
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
