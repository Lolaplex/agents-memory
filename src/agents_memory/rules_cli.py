"""CLI for hard rules: ``context`` (render) and ``rules`` (user-intent edits)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import rules as R


def build_context_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agents_memory context",
        description="Print the rendered hard rules (global plus optional project overlay).",
    )
    parser.add_argument("--project", "-p", default="", help="Project slug for the overlay")
    parser.add_argument(
        "--format", "-f", dest="fmt", choices=("md", "json"), default="md", help="Output format"
    )
    return parser


def build_rules_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agents_memory rules",
        description=(
            "Edit hard rules (rules/HARD.md, projects/<slug>/RULES.md). "
            "This is the user-intent write path; MCP agents only propose_rule."
        ),
    )
    sub = parser.add_subparsers(dest="action")

    def scoped(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.add_argument("--project", "-p", default="", help="Project slug (overlay file)")
        return p

    scoped("show", "List rules with numbers, budget usage, and pending proposals")
    add = scoped("add", "Append one rule (removes the matching staged proposal)")
    add.add_argument("rule", nargs="+", help="Rule text, one line")
    edit = scoped("edit", "Replace rule number N")
    edit.add_argument("number", type=int, help="Rule number from `rules show`")
    edit.add_argument("rule", nargs="+", help="New rule text, one line")
    remove = scoped("remove", "Delete rule number N")
    remove.add_argument("number", type=int, help="Rule number from `rules show`")
    setp = scoped("set", "Replace the whole rule file (from --file or stdin)")
    setp.add_argument("--file", "-f", dest="from_file", default="-", help="Path, or - for stdin")
    scoped("check", "Exit 1 when the rule file is over budget")
    return parser


def context_main(argv: Optional[List[str]] = None) -> int:
    parser = build_context_parser()
    try:
        ns = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    try:
        if ns.fmt == "json":
            print(json.dumps(R.render_rules_data(ns.project or None), indent=2, ensure_ascii=False))
        else:
            block = R.render_rules(ns.project or None)
            if block:
                print(block)
    except R.RulesError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


def _show(project: str) -> int:
    slug = R.normalize_project(project)
    current = R.load_rules(slug)
    usage = R.budget_usage(current, slug)
    path = R.rules_path(slug)
    limit = f"{usage['lines']}/{usage['max_lines']} lines"
    if usage["max_chars"] is not None:
        limit += f", {usage['chars']}/{usage['max_chars']} chars"
    print(f"{path} ({limit})")
    for i, rule in enumerate(current, 1):
        print(f"{i:>3}. {rule}")
    problems = R.budget_problems(current, slug)
    if problems:
        print(f"Over budget: {', '.join(problems)}. Consolidate.")
    pending = _pending_proposals()
    if pending:
        print(f"\nPending proposals ({R.PROPOSALS_REL}):")
        for line in pending:
            print(f"  {line}")
    return 0


def _pending_proposals() -> List[str]:
    path = R.proposals_path()
    if not path.is_file():
        return []
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("- [rule @")
    ]


def rules_main(argv: Optional[List[str]] = None) -> int:
    parser = build_rules_parser()
    try:
        ns = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    action = ns.action or "show"
    project = getattr(ns, "project", "") or ""
    try:
        if action == "show":
            return _show(project)
        if action == "check":
            slug = R.normalize_project(project)
            problems = R.budget_problems(R.load_rules(slug), slug)
            if problems:
                print(f"Over budget: {', '.join(problems)}", file=sys.stderr)
                return 1
            print("Within budget.")
            return 0
        if action == "add":
            path = R.add_rule(" ".join(ns.rule), project or None, user_intent=True)
        elif action == "edit":
            path = R.edit_rule(ns.number, " ".join(ns.rule), project or None, user_intent=True)
        elif action == "remove":
            path = R.remove_rule(ns.number, project or None, user_intent=True)
        elif action == "set":
            if ns.from_file == "-":
                text = sys.stdin.read()
            else:
                text = Path(ns.from_file).expanduser().read_text(encoding="utf-8")
            path = R.save_rules_text(text, project or None, user_intent=True)
        else:
            parser.print_usage(sys.stderr)
            return 2
    except (R.RulesError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {path}")
    return 0
