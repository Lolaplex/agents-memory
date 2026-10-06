"""Hard rules: one vault file, one renderer, budgeted user-owned writes.

Global rules live in ``<user store>/rules/HARD.md``. A project may add an
overlay in ``<user store>/projects/<slug>/RULES.md``. One rule per line.

Everything that shows rules to an agent (MCP ``instructions``, the first tool
response of a session, ``agents-memory context``, the always-on injection
files) goes through :func:`render_rules`, so there is one source and no drift.

Agents only propose rules (``propose_rule`` -> staging). The rule files are
changed through the user-facing CLI (``agents-memory rules ...``), which calls
:func:`save_rules` with ``user_intent=True``. Store writes from MCP tools are
refused for these paths.
"""
from __future__ import annotations

import hashlib
import inspect
import os
import re
import threading
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import store

RULES_REL = "rules/HARD.md"
PROJECT_RULES_NAME = "RULES.md"
PROPOSALS_REL = "staging/rule-proposals.md"

DEFAULT_MAX_LINES = 30
DEFAULT_MAX_CHARS = 2000
DEFAULT_PROJECT_MAX_LINES = 10
ENV_MAX_LINES = "AGENTS_MEMORY_RULES_MAX_LINES"
ENV_MAX_CHARS = "AGENTS_MEMORY_RULES_MAX_CHARS"
ENV_PROJECT_MAX_LINES = "AGENTS_MEMORY_RULES_PROJECT_MAX_LINES"

BLOCK_TAG = "memory_rules"
SESSION_HINT = (
    "At session start in a repository, call get_project_memories(project=<slug>) "
    "to load that project's memory."
)
USER_EDIT_HINT = "agents-memory rules add|edit|remove|set"

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LIST_PREFIX_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")


class RulesError(ValueError):
    """Invalid rule input."""


class RulesBudgetError(RulesError):
    """A write would exceed the rule budget."""


class RulesWriteDenied(PermissionError):
    """Rule files are user-owned; agents propose into staging instead."""


# --- limits -----------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def max_lines() -> int:
    return _env_int(ENV_MAX_LINES, DEFAULT_MAX_LINES)


def max_chars() -> int:
    return _env_int(ENV_MAX_CHARS, DEFAULT_MAX_CHARS)


def project_max_lines() -> int:
    return _env_int(ENV_PROJECT_MAX_LINES, DEFAULT_PROJECT_MAX_LINES)


def limits() -> Dict[str, int]:
    return {
        "max_lines": max_lines(),
        "max_chars": max_chars(),
        "project_max_lines": project_max_lines(),
    }


# --- paths --------------------------------------------------------------------


def normalize_project(project: Optional[str]) -> str:
    """Return a safe project slug, or "" for none. Raises on path-like input."""
    slug = (project or "").strip()
    if not slug or slug in ("*", "all"):
        return ""
    if not _SLUG_RE.match(slug) or ".." in slug:
        raise RulesError(f"invalid project slug: {project!r}")
    return slug


def global_rules_path() -> Path:
    return store.USER_MEMORY / RULES_REL


def project_rules_path(project: str) -> Path:
    slug = normalize_project(project)
    if not slug:
        raise RulesError("project slug required")
    return store.USER_MEMORY / "projects" / slug / PROJECT_RULES_NAME


def rules_path(project: Optional[str] = None) -> Path:
    slug = normalize_project(project)
    return project_rules_path(slug) if slug else global_rules_path()


def proposals_path() -> Path:
    return store.USER_MEMORY / PROPOSALS_REL


def _norm(path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return os.path.normcase(str(resolved))


def is_rules_path(path: Path) -> bool:
    """True for the global rule file or any project overlay in the user store."""
    target = _norm(path)
    if target == _norm(global_rules_path()):
        return True
    projects_dir = _norm(store.USER_MEMORY / "projects")
    parent = os.path.dirname(target)
    return (
        os.path.basename(target) == os.path.normcase(PROJECT_RULES_NAME)
        and os.path.dirname(parent) == projects_dir
    )


def assert_agent_write_allowed(path: Path) -> None:
    """Refuse store writes to rule files (MCP write/add/delete and CLI vault CRUD)."""
    if is_rules_path(path):
        raise RulesWriteDenied(
            "Hard rules are user-owned. Propose a rule with propose_rule "
            f"(lands in {PROPOSALS_REL} for review). The user applies it with "
            f"`{USER_EDIT_HINT}`."
        )


# --- parse / load -------------------------------------------------------------


def _rule_line(raw: str) -> str:
    stripped = raw.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("<!--"):
        return ""
    return _LIST_PREFIX_RE.sub("", stripped).strip()


def parse_rules(text: str) -> List[str]:
    """One rule per non-empty line. Headings and HTML comments are not rules."""
    rules: List[str] = []
    for raw in (text or "").splitlines():
        rule = _rule_line(raw)
        if rule:
            rules.append(rule)
    return rules


def _rule_line_indexes(lines: List[str]) -> List[int]:
    return [i for i, raw in enumerate(lines) if _rule_line(raw)]


def load_rules(project: Optional[str] = None) -> List[str]:
    """Rules from the global file, or from one project overlay. Missing file -> []."""
    try:
        path = rules_path(project)
    except RulesError:
        return []
    if not path.is_file():
        return []
    try:
        return parse_rules(path.read_text(encoding="utf-8"))
    except OSError:
        return []


# --- budget -------------------------------------------------------------------


def budget_usage(rules: List[str], project: Optional[str] = None) -> Dict[str, Any]:
    chars = len("\n".join(rules))
    if normalize_project(project):
        return {
            "lines": len(rules),
            "max_lines": project_max_lines(),
            "chars": chars,
            "max_chars": None,
        }
    return {
        "lines": len(rules),
        "max_lines": max_lines(),
        "chars": chars,
        "max_chars": max_chars(),
    }


def budget_problems(rules: List[str], project: Optional[str] = None) -> List[str]:
    usage = budget_usage(rules, project)
    problems: List[str] = []
    if usage["lines"] > usage["max_lines"]:
        problems.append(f"{usage['lines']}/{usage['max_lines']} rule lines")
    if usage["max_chars"] is not None and usage["chars"] > usage["max_chars"]:
        problems.append(f"{usage['chars']}/{usage['max_chars']} characters")
    return problems


def check_budget(
    rules: List[str],
    project: Optional[str] = None,
    previous: Optional[List[str]] = None,
) -> None:
    """Raise when ``rules`` is over budget.

    A file that is already over budget (hand-edited) may still shrink: the
    write passes when it adds neither lines nor characters versus ``previous``.
    """
    problems = budget_problems(rules, project)
    if problems and previous is not None:
        now, before = budget_usage(rules, project), budget_usage(previous, project)
        if now["lines"] <= before["lines"] and now["chars"] <= before["chars"]:
            return
    if problems:
        scope = f"project '{normalize_project(project)}' rules" if normalize_project(project) else "global hard rules"
        raise RulesBudgetError(
            f"Over budget for {scope}: {', '.join(problems)}. "
            "Consolidate first: merge overlapping rules, drop the weakest, "
            "keep one short imperative rule per line. Nothing was written."
        )


# --- render -------------------------------------------------------------------


def render_rules(project: Optional[str] = None, include_global: bool = True) -> str:
    """Compact ``<memory_rules>`` block: global rules plus an optional project overlay.

    Missing files render as an empty string. ``include_global=False`` renders
    only the project overlay (used when the global block was already delivered).
    """
    try:
        slug = normalize_project(project)
    except RulesError:
        slug = ""
    global_rules = load_rules() if include_global else []
    overlay = load_rules(slug) if slug else []
    if not global_rules and not overlay:
        return ""
    if include_global:
        lines = [f"<{BLOCK_TAG}>"]
        lines.extend(f"- {r}" for r in global_rules)
        if overlay:
            lines.append(f'<project name="{slug}">')
            lines.extend(f"- {r}" for r in overlay)
            lines.append("</project>")
        lines.append(f"</{BLOCK_TAG}>")
        return "\n".join(lines)
    lines = [f'<{BLOCK_TAG} project="{slug}">']
    lines.extend(f"- {r}" for r in overlay)
    lines.append(f"</{BLOCK_TAG}>")
    return "\n".join(lines)


def render_rules_data(project: Optional[str] = None) -> Dict[str, Any]:
    """Structured view for ``agents-memory context --format json``."""
    slug = normalize_project(project)
    global_rules = load_rules()
    overlay = load_rules(slug) if slug else []
    return {
        "project": slug or None,
        "rules": global_rules,
        "project_rules": overlay,
        "block": render_rules(slug or None),
        "usage": {
            "global": budget_usage(global_rules),
            **({"project": budget_usage(overlay, slug)} if slug else {}),
        },
    }


def render_instructions() -> str:
    """MCP ``initialize`` instructions: global rules plus one generic hint."""
    block = render_rules()
    return f"{block}\n\n{SESSION_HINT}" if block else SESSION_HINT


def refresh_instructions(server: Any) -> None:
    """Re-render instructions right before serving (after a startup pull)."""
    low = getattr(server, "_mcp_server", None)
    if low is not None and hasattr(low, "instructions"):
        low.instructions = render_instructions()


# --- user-intent writes -----------------------------------------------------------


def _header(project: str) -> str:
    return f"# Project rules: {project}\n" if project else "# Hard rules\n"


def _clean_rule(rule: str) -> str:
    text = (rule or "").strip()
    if not text:
        raise RulesError("empty rule")
    if "\n" in text or "\r" in text:
        raise RulesError("one rule per line: the rule must not contain line breaks")
    text = _rule_line(text)
    if not text:
        raise RulesError("a rule cannot be a heading or comment")
    return text


def _require_user_intent(user_intent: bool) -> None:
    if not user_intent:
        raise RulesWriteDenied(
            f"Rule files change only through `{USER_EDIT_HINT}`. Agents use propose_rule."
        )


def _write_rules(text: str, slug: str) -> Path:
    path = rules_path(slug)
    previous = path.read_text(encoding="utf-8") if path.is_file() else ""
    check_budget(parse_rules(text), slug, previous=parse_rules(previous) if previous else None)
    store._write(path, text)
    store._note_memory_write(path, previous, text)
    store.clear_memory_cache()
    return path


def save_rules_text(text: str, project: Optional[str] = None, *, user_intent: bool = False) -> Path:
    """Replace a rule file. Only the user-facing CLI passes ``user_intent=True``."""
    _require_user_intent(user_intent)
    path = _write_rules(text, normalize_project(project))
    store._finish_store_write()
    return path


def _current_lines(project: str) -> List[str]:
    path = rules_path(project)
    if path.is_file():
        return path.read_text(encoding="utf-8").splitlines()
    return _header(project).splitlines() + [""]


def add_rule(rule: str, project: Optional[str] = None, *, user_intent: bool = False) -> Path:
    """Append one rule; drops the matching staged proposal if there is one."""
    _require_user_intent(user_intent)
    slug = normalize_project(project)
    text = _clean_rule(rule)
    lines = _current_lines(slug)
    if text.lower() in {r.lower() for r in parse_rules("\n".join(lines))}:
        raise RulesError(f"rule already present: {text}")
    while lines and not lines[-1].strip():
        lines.pop()
    lines.append(f"- {text}")
    path = _write_rules("\n".join(lines) + "\n", slug)
    remove_proposal(text, slug)
    store._finish_store_write()
    return path


def _replace_rule_line(
    project: Optional[str], number: int, new_rule: Optional[str], *, user_intent: bool
) -> Path:
    _require_user_intent(user_intent)
    slug = normalize_project(project)
    path = rules_path(slug)
    if not path.is_file():
        raise RulesError(f"no rules file yet: {path.name}")
    lines = path.read_text(encoding="utf-8").splitlines()
    idx = _rule_line_indexes(lines)
    if number < 1 or number > len(idx):
        raise RulesError(f"rule number out of range: {number} (have {len(idx)})")
    pos = idx[number - 1]
    if new_rule is None:
        del lines[pos]
    else:
        lines[pos] = f"- {_clean_rule(new_rule)}"
    path = _write_rules("\n".join(lines) + "\n", slug)
    store._finish_store_write()
    return path


def edit_rule(number: int, rule: str, project: Optional[str] = None, *, user_intent: bool = False) -> Path:
    return _replace_rule_line(project, number, rule, user_intent=user_intent)


def remove_rule(number: int, project: Optional[str] = None, *, user_intent: bool = False) -> Path:
    return _replace_rule_line(project, number, None, user_intent=user_intent)


# --- agent proposals (staging) ------------------------------------------------------


def _proposal_origin(project: str) -> str:
    return f"project:{project}" if project else "global"


def proposal_bullet(rule: str, project: Optional[str] = None) -> str:
    slug = normalize_project(project)
    return f"[rule @ {_proposal_origin(slug)}] {_clean_rule(rule)}"


def propose_rule(rule: str, project: Optional[str] = None) -> Dict[str, Any]:
    """Append a rule proposal to the user staging inbox. Never touches rule files."""
    from .ingest_common import scrub

    slug = normalize_project(project)
    text = _clean_rule(scrub(_clean_rule(rule)))
    path = proposals_path()
    loc = store._append_bullet(path, proposal_bullet(text, slug))
    store.clear_memory_cache()
    store._finish_store_write()
    current = load_rules(slug)
    return {
        "staged": loc,
        "rule": text,
        "project": slug or None,
        "usage": budget_usage(current, slug),
    }


def is_proposals_file(file_id_or_path: str) -> bool:
    norm = str(file_id_or_path or "").replace("\\", "/")
    return norm == f"user/{PROPOSALS_REL}" or norm.endswith(f"/{PROPOSALS_REL}")


def remove_proposal(rule: str, project: Optional[str] = None) -> bool:
    path = proposals_path()
    if not path.is_file():
        return False
    try:
        bullet = proposal_bullet(rule, project)
    except RulesError:
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if ln.strip().lstrip("-").strip().lower() != bullet.lower()]
    if len(kept) == len(lines):
        return False
    store._write(path, "\n".join(kept) + "\n")
    store.clear_memory_cache()
    return True


# --- per-session piggyback ------------------------------------------------------------


class RuleDelivery:
    """Prefix rule blocks onto tool results, once per content hash per session."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_session: "weakref.WeakKeyDictionary[Any, set]" = weakref.WeakKeyDictionary()
        self._by_id: Dict[int, set] = {}
        self._process: set = set()

    def reset(self) -> None:
        with self._lock:
            self._by_session = weakref.WeakKeyDictionary()
            self._by_id = {}
            self._process = set()

    def _seen(self, session: Any) -> set:
        if session is None:
            return self._process
        try:
            return self._by_session.setdefault(session, set())
        except TypeError:
            return self._by_id.setdefault(id(session), set())

    def pending_blocks(self, project: str = "", session: Any = None) -> List[str]:
        """Blocks not yet delivered in this session; marks them delivered."""
        candidates: List[str] = [render_rules()]
        try:
            slug = normalize_project(project)
        except RulesError:
            slug = ""
        if slug:
            candidates.append(render_rules(slug, include_global=False))
        out: List[str] = []
        with self._lock:
            seen = self._seen(session)
            for block in candidates:
                if not block:
                    continue
                digest = hashlib.sha256(block.encode("utf-8")).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                out.append(block)
        return out

    def apply(self, result: str, project: str = "", session: Any = None) -> str:
        blocks = self.pending_blocks(project, session)
        if not blocks:
            return result
        return "\n\n".join(blocks) + "\n\n" + result


DELIVERY = RuleDelivery()

PROJECT_ARG_NAMES: Tuple[str, ...] = ("project", "project_slug")


def project_from_arguments(arguments: Dict[str, Any]) -> str:
    for name in PROJECT_ARG_NAMES:
        value = arguments.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def session_of(server: Any) -> Any:
    """The MCP session of the current request, or None outside a request."""
    try:
        return server.get_context().session
    except Exception:
        return None


def deliver_for_call(server: Any, fn: Any, args: tuple, kwargs: dict, result: str) -> str:
    """Prefix rule blocks not yet delivered in this MCP session onto a tool result.

    The first result of a session carries the global block; a project-scoped call
    adds that project's overlay once. Never fails the tool call.
    """
    try:
        try:
            arguments = dict(inspect.signature(fn).bind_partial(*args, **kwargs).arguments)
        except (TypeError, ValueError):
            arguments = dict(kwargs)
        project = project_from_arguments(arguments)
        return DELIVERY.apply(result, project, session_of(server))
    except Exception:
        return result
