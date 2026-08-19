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
                "edit": "Edit USER.md / PROJECTS.md, then re-run python -m agent_memory sync",
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
                "marker": "<!-- agent-memory-sync -->",
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
            {"path": "~/.cursor/mcp.json", "key": "mcpServers.agent-memory"},
            {"path": "Zed settings.json", "key": "context_servers"},
        ],
        "copied_not_generated": [
            {"path": "~/.agents/memory/LAYOUT.md", "source": "abi/LAYOUT.md in engine clone"},
        ],
        "marker": "<!-- agent-memory-sync -->",
    }


def full_spec() -> dict[str, Any]:
    from .sync import build_parser as sync_parser
    from .inventory import build_parser as inventory_parser

    return {
        "name": "agent-memory",
        "abi_version": ABI_VERSION,
        "scripts": {
            "sync": cli_spec(sync_parser(), name="sync", description="Rewrite always-on injection for your Agent."),
            "inventory": cli_spec(
                inventory_parser(),
                name="inventory",
                description="Compare scan.json roots to PROJECTS.md.",
            ),
        },
        "scripts_no_flags": {
            "ingest": "Serial ingest: catalog (references) -> extract (staging) -> distill via MCP add_memory.",
            "consolidate": "Move live markdown leaked into the engine clone into ~/.agents/memory.",
            "extract-openai": "Thin wrapper: ingest extract for openai-export ( --out = legacy JSON ).",
            "mcp": "MCP stdio server. Tools: see abi/MCP.md.",
        },
        "injection": injection_spec(),
        "discover": "python -m agent_memory --help-json | python -m agent_memory sync --help-json | python -m agent_memory inventory --help-json",
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
    print("Usage: python -m agent_memory --help-json", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
