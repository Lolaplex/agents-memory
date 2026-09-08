"""Machine-readable CLI specs derived from argparse (source of truth)."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List

from . import __version__ as ABI_VERSION


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _action_spec(action: argparse.Action) -> dict[str, Any] | None:
    if action.help is argparse.SUPPRESS:
        return None
    if action.option_strings and action.option_strings[0] in ("-h", "--help"):
        return None
    if action.dest in ("help", "func"):
        return None
    if isinstance(action, argparse._SubParsersAction):
        return None
    flags = list(action.option_strings)
    is_option = bool(flags)
    is_flag = action.nargs == 0 or isinstance(action, argparse._StoreTrueAction)
    spec: dict[str, Any] = {
        "name": action.metavar or action.dest,
        "dest": action.dest,
        "help": action.help or "",
        "required": bool(action.required),
    }
    if is_option:
        spec["flags"] = flags
        spec["kind"] = "flag" if is_flag else "option"
    else:
        spec["kind"] = "argument"
        if action.nargs is not None:
            spec["nargs"] = str(action.nargs)
    default = action.default
    if default is not argparse.SUPPRESS and default is not None:
        spec["default"] = _json_safe(default)
    if action.choices:
        spec["choices"] = [_json_safe(c) for c in action.choices]
    return spec


def cli_spec(parser: argparse.ArgumentParser, *, name: str, description: str = "") -> dict[str, Any]:
    options: List[dict[str, Any]] = []
    arguments: List[dict[str, Any]] = []
    for action in parser._actions:
        item = _action_spec(action)
        if not item:
            continue
        if item["kind"] == "argument":
            arguments.append(item)
        else:
            options.append(item)
    return {
        "name": name,
        "abi_version": ABI_VERSION,
        "description": description or parser.description or "",
        "usage": parser.format_usage().strip(),
        "options": options,
        "arguments": arguments,
    }


def injection_spec() -> dict[str, Any]:
    return {
        "scan_skips": [".agents", ".cursor", ".git", "node_modules"],
        "no_empty_folders": True,
        "generated_on_sync": [
            {
                "path": "~/.agents/AGENTS.md",
                "from": ["~/.agents/memory/USER.md", "~/.agents/memory/PROJECTS.md"],
                "edit": "Edit USER.md / PROJECTS.md, then re-run python -m agents_memory sync",
            },
            {
                "path": "~/.agents/CLAUDE.md",
                "bind": "~/.agents/AGENTS.md",
                "edit": "Edit AGENTS.md only",
            },
            {
                "path": "~/.agents/rules/<agent_rule_name>.mdc",
                "hosts": ["~/.cursor/rules/<agent_rule_name>.mdc (bound on sync)"],
                "config": "scan.json agent_rule_name (default user-rules.mdc)",
            },
            {
                "path": "<repo>/.agents/AGENTS.md + CLAUDE.md",
                "when": "registered project with path on disk",
                "marker": "<!-- agents-memory-sync -->",
                "marker_end": "<!-- /agents-memory-sync -->",
                "note": "No <repo>/.cursor/ — scan skips .cursor; no empty memory subfolders",
            },
            {
                "path": "<repo>/.agents/memory/README.md + staging/captured.md",
                "when": "register_project",
            },
            {
                "path": "~/.agents/skills/memory-sync/SKILL.md",
                "also": ["host skill dirs per INSTALL.md"],
            },
        ],
        "merged_on_init": [
            {"path": "~/.cursor/mcp.json", "key": "mcpServers.agents-memory"},
            {"path": "Zed settings.json", "key": "context_servers"},
        ],
        "copied_not_generated": [
            {"path": "~/.agents/memory/LAYOUT.md", "source": "abi/LAYOUT.md in engine clone"},
        ],
        "marker": "<!-- agents-memory-sync -->",
        "marker_end": "<!-- /agents-memory-sync -->",
        "inject": "splice marked block; never replace the rest of AGENTS.md",
    }


def full_spec() -> dict[str, Any]:
    from .sync import build_parser as sync_parser
    from .inventory import build_parser as inventory_parser

    sync = cli_spec(
        sync_parser(),
        name="sync",
        description="Rewrite always-on injection for your Agent.",
    )
    inventory = cli_spec(
        inventory_parser(),
        name="inventory",
        description="Compare scan.json roots to PROJECTS.md.",
    )

    # Lightweight entries for commands without a dedicated argparse module.
    simple: dict[str, dict[str, Any]] = {
        "projects": {
            "description": "List tracked projects, or dump one project's memory (projects SLUG).",
            "usage": "python -m agents_memory projects [SLUG] [--json]",
            "aliases": ["list-projects"],
        },
        "search": {
            "description": "Lexical search over the markdown vault (exact then FTS5 fill).",
            "usage": "python -m agents_memory search QUERY",
        },
        "add": {
            "description": "File a durable fact/note (MCP add_memory mirror).",
            "usage": "python -m agents_memory add TEXT [--kind KIND] [--name STEM] [--project SLUG] [--collection NAME]",
            "aliases": ["save"],
        },
        "read": {
            "description": "Read raw markdown or rule file by id.",
            "usage": "python -m agents_memory read FILE_ID",
            "aliases": ["cat", "get"],
        },
        "write": {
            "description": "Overwrite a memory/rule file (MCP write_memory_file mirror).",
            "usage": "python -m agents_memory write FILE_ID [--file PATH | TEXT...]",
            "aliases": ["put"],
        },
        "delete": {
            "description": "Delete one search-hit line by id (file.md:N).",
            "usage": "python -m agents_memory delete MEMORY_ID",
            "aliases": ["rm"],
        },
        "related": {
            "description": "Follow frontmatter refs/supersedes/same_as from a hit id.",
            "usage": "python -m agents_memory related MEMORY_ID [--limit N]",
            "aliases": ["rels"],
        },
        "distill": {
            "description": "Peek staging inbox, or auto_distill with --auto.",
            "usage": "python -m agents_memory distill [--auto]",
        },
        "ingest": {
            "description": "Catalog references, extract to staging, status. Distill via MCP/CLI distill.",
            "usage": "python -m agents_memory ingest {catalog,extract,run,status}",
            "aliases": ["ingest-chats→catalog"],
        },
        "consolidate": {
            "description": "Move live markdown leaked into the engine clone into ~/.agents/memory.",
            "usage": "python -m agents_memory consolidate",
        },
        "check": {
            "description": "Mechanical store health checks (read-only, zero AI).",
            "usage": "python -m agents_memory check",
        },
        "rebuild-index": {
            "description": "Rebuild disposable FTS5 cache (markdown stays source of truth).",
            "usage": "python -m agents_memory rebuild-index",
            "aliases": ["index"],
        },
        "serve": {
            "description": "Start local memory browser (default port 8765).",
            "usage": "python -m agents_memory serve [PORT]",
        },
        "web": {
            "description": "Export static HTML website of the vault.",
            "usage": "python -m agents_memory web [DIR]",
        },
        "remote": {
            "description": "Cloud mirror: serve/connect/disconnect/status/push/pull/client/attach.",
            "usage": "python -m agents_memory remote {serve,connect,disconnect,status,push,pull,client,attach}",
            "aliases": ["cloud", "connect", "disconnect"],
        },
        "reset": {
            "description": "Clear local memory caches and temporary state (requires --yes).",
            "usage": "python -m agents_memory reset --yes",
            "aliases": ["clean"],
        },
        "mcp": {
            "description": "MCP stdio server. Tools: see abi/MCP.md.",
            "usage": "python -m agents_memory mcp",
        },
        "extract-openai": {
            "description": "DEPRECATED thin wrapper → ingest extract (openai-export; --out = legacy JSON).",
            "usage": "python -m agents_memory extract-openai [--zip PATH] [--out JSON]",
            "deprecated": True,
            "prefer": "ingest extract",
        },
        "help-json": {
            "description": "Print machine-readable CLI + injection spec.",
            "usage": "python -m agents_memory --help-json",
        },
        "init": {
            "description": "Alias for sync --init.",
            "usage": "python -m agents_memory init",
            "alias_of": "sync --init",
        },
    }

    commands: dict[str, Any] = {
        "sync": sync,
        "inventory": inventory,
        **{
            name: {
                "name": name,
                "abi_version": ABI_VERSION,
                **meta,
            }
            for name, meta in simple.items()
        },
    }

    # Back-compat keys (older agents/skills scrape these).
    scripts_no_flags = {
        name: meta["description"]
        for name, meta in simple.items()
        if name not in {"help-json", "init"}
    }

    return {
        "name": "agents-memory",
        "abi_version": ABI_VERSION,
        "commands": commands,
        "scripts": {
            "sync": sync,
            "inventory": inventory,
        },
        "scripts_no_flags": scripts_no_flags,
        "injection": injection_spec(),
        "discover": "python -m agents_memory --help-json",
    }


def emit_help_json(argv: list[str], parser: argparse.ArgumentParser, *, name: str, description: str = "") -> None:
    payload = cli_spec(parser, name=name, description=description)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = list(argv if argv is not None else sys.argv[1:])
    if "--help-json" in args:
        print(json.dumps(full_spec(), indent=2, ensure_ascii=False))
        return 0
    print("Usage: python -m agents_memory --help-json", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
