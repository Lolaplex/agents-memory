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

USAGE = """Usage: python -m agents_memory COMMAND [args]

Vault CRUD (MCP mirror):
  search QUERY              Lexical search over the markdown vault
  add TEXT [--kind ...]     File a durable fact/note
  read FILE_ID              Raw markdown / rule file
  write FILE_ID [--file P]  Overwrite file (TEXT args, --file, or stdin)
  delete MEMORY_ID          Drop one search hit line (file.md:N)
  related MEMORY_ID         Follow frontmatter refs/supersedes/same_as

Projects / inject:
  sync [--init] [--push]    Rewrite always-on injection
  inventory [...]           Disk vs PROJECTS.md (--register / --ignore / --repair-moved)
  projects [SLUG]           List projects, or dump one project's memory

Staging / ingest (CLI-owned):
  distill [--auto]          Staging inbox peek, or auto_distill
  ingest catalog|extract|run|status
  consolidate               Move clone leaks into ~/.agents/memory

Ops:
  check                     Mechanical store health (read-only, no LLM)
  rebuild-index             Rebuild disposable FTS5 cache
  serve [PORT]              Local memory browser (default 8765)
  web [DIR]                 Static HTML export
  remote ...                Cloud mirror (serve/connect/disconnect/push/pull/attach)
  reset --yes               Clear local memory caches / temp state
  mcp                       stdio MCP clerk (always local markdown)
  help-json                 Machine-readable CLI + injection spec

Aliases: init→sync --init | connect|disconnect→remote … | cat|get→read |
  save→add | put→write | list-projects→projects | ingest-chats→ingest catalog |
  index→rebuild-index | clean→reset | cloud→remote
Deprecated: extract-openai → use ingest extract (openai-export source)
"""


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE, end="")
        return 0 if args else 2
    if args[0] in ("-v", "--version", "version"):
        from . import __version__

        print(f"agents-memory {__version__}")
        return 0
    if args[0] in ("--help-json", "help-json"):
        from .cli_help import main as help_main

        return help_main(["--help-json"])
    cmd, rest = args[0], args[1:]
    if cmd != "mcp":
        try:
            from . import __version__
            from .updates import check_for_updates

            check_for_updates("agents-memory", __version__)
        except Exception:
            pass
    if cmd == "init":
        from .sync import main as run

        return run(["--init", *rest])
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
        from .store import auto_distill, get_staging_inbox

        if "--auto" in rest or "-a" in rest:
            res = auto_distill(limit=50, discard_noise=True, auto_sync=True)
            print(
                f"Auto-distill result: {res['promoted']} promoted, {res['discarded']} discarded, {res['remaining_staging_count']} remaining."
            )
            if res.get("errors"):
                for err in res["errors"]:
                    print(f"  Error: {err}")
            return 0

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
        print(
            "\nTo distill, tell your Agent: 'run memory-distill' or use the memory-distill skill (or: python -m agents_memory distill --auto)."
        )
        return 0
    if cmd in ("ingest-chats", "ingest_chats"):
        from .ingest import main as run

        return run(["catalog", *rest])
    if cmd == "consolidate":
        from .consolidate import main as run

        return run()
    if cmd in ("extract-openai", "extract_openai"):
        print(
            "DEPRECATED: use `python -m agents_memory ingest extract` "
            "(openai-export source). extract-openai remains a thin wrapper.",
            file=sys.stderr,
        )
        from .extract_openai import main as run

        return run(rest)
    if cmd == "check":
        from .check import main as run_check

        return run_check(rest)
    if cmd == "serve":
        from .viewer import serve_viewer

        port = int(rest[0]) if rest and rest[0].isdigit() else 8765
        serve_viewer(port=port)
        return 0
    if cmd == "web":
        from .viewer import export_static_web

        out_dir = Path(rest[0]) if rest else None
        res = export_static_web(dest_dir=out_dir)
        print(
            f"Exported static memory website: {res['files']} files to {res['export_dir']}"
        )
        return 0
    if cmd in ("remote", "cloud"):
        from .remote.cli import main as run_remote

        return run_remote(rest)
    if cmd == "connect":
        from .remote.cli import main as run_remote

        return run_remote(["connect", *rest])
    if cmd == "disconnect":
        from .remote.cli import main as run_remote

        return run_remote(["disconnect", *rest])
    if cmd in ("rebuild-index", "rebuild_index", "index"):
        from .index import rebuild_index

        res = rebuild_index()
        print(
            f"Indexed {res['indexed']} markdown documents in {res['duration_ms']}ms -> {res['db_path']}"
        )
        return 0
    if cmd in ("read", "cat", "get"):
        from .store import read_memory_file

        if not rest:
            print("usage: python -m agents_memory read FILE_ID", file=sys.stderr)
            return 2
        file_id = rest[0].strip()
        try:
            content = read_memory_file(file_id)
            print(content)
            return 0
        except Exception as e:
            print(f"Error reading memory file '{file_id}': {e}", file=sys.stderr)
            return 1
    if cmd in ("write", "put"):
        import argparse

        parser = argparse.ArgumentParser(prog="agents_memory write")
        parser.add_argument("file_id", help="Memory file id (e.g. user/USER.md)")
        parser.add_argument(
            "text",
            nargs="*",
            help="Content as argv (or use --file / stdin)",
        )
        parser.add_argument(
            "--file",
            "-f",
            dest="from_file",
            default="",
            help="Read content from path (- = stdin)",
        )
        try:
            ns = parser.parse_args(rest)
        except SystemExit:
            return 2
        write_usage = (
            "usage: python -m agents_memory write FILE_ID [--file PATH | TEXT...]"
        )
        if ns.from_file:
            if ns.from_file == "-":
                content = sys.stdin.read()
            else:
                content = Path(ns.from_file).expanduser().read_text(encoding="utf-8")
        elif ns.text:
            content = " ".join(ns.text)
        elif not sys.stdin.isatty():
            content = sys.stdin.read()
            if content == "":
                print(write_usage, file=sys.stderr)
                return 2
        else:
            print(write_usage, file=sys.stderr)
            return 2
        from .store import write_memory_file

        try:
            loc = write_memory_file(ns.file_id.strip(), content)
            print(f"Wrote {loc}")
            return 0
        except Exception as e:
            print(f"Error writing memory file '{ns.file_id}': {e}", file=sys.stderr)
            return 1
    if cmd in ("delete", "rm"):
        from .store import delete_memory

        if not rest:
            print(
                "usage: python -m agents_memory delete MEMORY_ID  "
                "(e.g. user/notes/foo.md:3)",
                file=sys.stderr,
            )
            return 2
        memory_id = rest[0].strip()
        try:
            removed = delete_memory(memory_id)
            print(f"Deleted {memory_id}: {removed}")
            return 0
        except Exception as e:
            print(f"Error deleting memory '{memory_id}': {e}", file=sys.stderr)
            return 1
    if cmd in ("related", "rels"):
        import argparse
        import json

        parser = argparse.ArgumentParser(prog="agents_memory related")
        parser.add_argument("memory_id", help="Search hit id or document id")
        parser.add_argument("--limit", "-n", type=int, default=5)
        try:
            ns = parser.parse_args(rest)
        except SystemExit:
            return 2
        from .index import get_related

        try:
            res = get_related(ns.memory_id.strip(), limit=ns.limit)
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0
        except Exception as e:
            print(f"Error fetching related for '{ns.memory_id}': {e}", file=sys.stderr)
            return 1
    if cmd in ("projects", "list-projects", "list_projects"):
        from .store import get_project_memories, parse_projects

        if rest and not rest[0].startswith("-"):
            slug = rest[0].strip()
            try:
                print(get_project_memories(slug))
                return 0
            except Exception as e:
                print(f"Error reading project '{slug}': {e}", file=sys.stderr)
                return 1
        rows = parse_projects()
        if "--json" in rest:
            import json

            print(
                json.dumps(
                    [
                        {
                            "slug": p.slug,
                            "path": p.path,
                            "role": p.role,
                            "stack": p.stack,
                            "status": p.status,
                        }
                        for p in rows
                    ],
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0
        if not rows:
            print("No projects in PROJECTS.md")
            return 0
        for p in rows:
            print(f"{p.slug}\t{p.path}\t{p.role}\t{p.stack}\t{p.status}")
        return 0
    if cmd in ("add", "save"):
        import argparse

        parser = argparse.ArgumentParser(prog="agents_memory add")
        parser.add_argument("fact", help="Fact or memory text to save")
        parser.add_argument("--kind", "-k", default="", help="Kind (note, fact, concept, workflow, etc.)")
        parser.add_argument("--name", "-n", default="", help="File name/stem")
        parser.add_argument("--project", "-p", default="", help="Project slug")
        parser.add_argument("--collection", "-c", default="", help="Collection name")
        try:
            ns = parser.parse_args(rest)
        except SystemExit:
            return 2
        from .store import add_memory

        try:
            loc = add_memory(
                ns.fact,
                kind=ns.kind,
                name=ns.name,
                project=ns.project,
                collection=ns.collection,
            )
            print(f"Saved to {loc}")
            return 0
        except Exception as e:
            print(f"Error saving memory: {e}", file=sys.stderr)
            return 1
    if cmd == "search":
        from .store import search_memory

        query = " ".join(rest).strip()
        if not query:
            print("usage: python -m agents_memory search QUERY", file=sys.stderr)
            return 2
        hits = search_memory(query)
        for hit in hits:
            file_id = hit.get("file", "?")
            line = hit.get("line", 0)
            text = hit.get("text", "")
            print(f"{file_id}:{line} {text}")
        return 0
    if cmd in ("reset", "clean"):
        if "--yes" not in rest and "-y" not in rest:
            print(
                "WARNING: This will clear local memory caches and temporary state. Pass --yes to confirm."
            )
            return 1
        from .store import clear_memory_cache

        clear_memory_cache()
        print("Memory state and cache reset successfully.")
        return 0
    if cmd in ("mcp", "mcp-server", "mcp_server"):
        from .mcp_server import main as run

        return run()
    print(f"unknown command: {cmd}\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
