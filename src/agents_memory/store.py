"""Local markdown memory store. No cloud.

Two layers, one retrieval:

- User: ``~/.agents/memory`` — identity, project map, concepts/entities/workflows,
  project **links**, personal notes, chat index.
- Project: ``<repo>/.agents/memory`` — staging (inbox), research, sequential
  plans/tasks/waves/roadmap, decisions, lifecycle notes.

Search unions both. Always-on injection stays short (USER.md + PROJECTS.md).
Chat bodies stay in product folders; only titles/paths are ingested.
`add_memory` requires kind+name (user taxonomy) or project= (in-tree notes).
AGENTS.md is the instruction file. CLAUDE.md is bound to it (symlink, else hardlink, else copy).
"""
from __future__ import annotations
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import PACKAGE_DIR, ROOT


def is_engine_repo(repo: Path) -> bool:
    """True for this engine clone — no in-tree ``.agents/`` or ``.cursor/``."""
    try:
        return repo.resolve() == ROOT.resolve()
    except OSError:
        return False


ABI_DIR = ROOT / "abi" if (ROOT / "abi").is_dir() else PACKAGE_DIR / "bundled" / "abi"
ABI_LAYOUT = ABI_DIR / "LAYOUT.md"
EXAMPLES = ROOT / "examples" if (ROOT / "examples").is_dir() else PACKAGE_DIR / "bundled" / "examples"
CLONE_LEAK_DIRS = (ROOT / "memory", ROOT / "examples")
LEGACY_MEMORY = ROOT / "memory"
AGENTS_HOME = Path.home() / ".agents"
AGENTS_RULES = AGENTS_HOME / "rules"
USER_MEMORY = AGENTS_HOME / "memory"
MEMORY = USER_MEMORY
ORPHANS = USER_MEMORY / "orphans"
USER_MD = USER_MEMORY / "USER.md"
PROJECTS_MD = USER_MEMORY / "PROJECTS.md"
SCAN_JSON = USER_MEMORY / "scan.json"
INGEST_JSON = USER_MEMORY / "ingest.json"
FACTS_MD = USER_MEMORY / "facts.md"
CHATS_INDEX = USER_MEMORY / "chats-index.md"
LAYOUT_MD = USER_MEMORY / "LAYOUT.md"
PROJECTS_DIR = USER_MEMORY / "projects"
CLAUDE_HOME = Path.home() / ".claude"
HOME_AGENTS = AGENTS_HOME / "AGENTS.md"
HOME_CLAUDE = AGENTS_HOME / "CLAUDE.md"

NOTE_COLLECTIONS = (
    "projects",
    "interests",
    "education",
    "finance",
    "family",
    "preferences",
    "programming",
    "work",
    "certifications",
    "scratch",
)
PROJECT_ARTIFACTS = {
    "research": "research",
    "plan": "plans",
    "plans": "plans",
    "task": "tasks",
    "tasks": "tasks",
    "roadmap": "roadmap",
    "wave": "waves",
    "waves": "waves",
    "decision": "decisions",
    "decisions": "decisions",
    "adr": "decisions",
    "staging": "staging",
    "captured": "staging",
}
SEQUENTIAL_FOLDERS = frozenset({"plans", "tasks", "roadmap", "waves", "decisions"})
NOTE_LIFECYCLES = ("proposed", "implemented", "rejected")
NOTE_CLASSES = (
    "feature",
    "bug-fix",
    "simplification",
    "architecture",
    "process",
    "testing",
)
# add_memory appends bullets. These kinds should be edited in place when facts change.
REVISE_IN_PLACE_KINDS = frozenset(
    {"research", "implemented", "decision", "decisions", "adr", "project", "projects"}
)
APPEND_INBOX_KINDS = frozenset({"staging", "captured", "scratch"})
PROJECT_MEMORY_TOP = (
    "staging",
    "research",
    "plans",
    "tasks",
    "roadmap",
    "waves",
    "decisions",
)
SEQ_RE = re.compile(r"^(\d{2,4})(?:-|$)")
POINTER_MARK = "<!-- agents-memory-sync-pointer -->"
STAGING_HEADER = (
    "# Staging\n\n"
    "Not memory. Distill each bullet into a typed file "
    "(`plans/001-…`, `tasks/001-…`, `waves/001-…`, `roadmap/001-…`, "
    "`decisions/001-…`, `notes/proposed|implemented|rejected/<class>/`), "
    "then delete it here.\n"
)

MARKER = "<!-- agents-memory-sync -->"
PATHS_BEGIN = "<!-- agents-memory-paths -->"
PATHS_END = "<!-- /agents-memory-paths -->"
DEFAULT_RULE_NAME = "user-rules.mdc"
LEGACY_RULE_STEMS = ("felix-always",)
SKILL_TEMPLATE = (
    (ROOT / "skills" / "memory-sync" / "SKILL.md")
    if (ROOT / "skills" / "memory-sync" / "SKILL.md").is_file()
    else (PACKAGE_DIR / "bundled" / "skills" / "memory-sync" / "SKILL.md")
)
SKIP_SKILL_NAMES = {
    "antigravity_guide",
    "agy-customizations",
    "permissioned-github",
}

INJECTION_GEMINI = Path.home() / ".gemini" / "config" / "AGENTS.md"

SKIP_DIR_DEFAULT = {
    ".git",
    ".agents",
    ".cursor",
    ".gemini",
    ".github",
    ".next",
    ".svelte-kit",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}

ROW_RE = re.compile(
    r"^\|\s*(?P<slug>[^|]+?)\s*\|\s*`?(?P<path>[^|`]+?)`?\s*\|\s*(?P<role>[^|]+?)\s*\|\s*(?P<stack>[^|]+?)\s*\|\s*(?P<status>[^|]+?)\s*\|$"
)


@dataclass
class Project:
    slug: str
    path: str
    role: str
    stack: str
    status: str = "active"

    @property
    def path_obj(self) -> Path:
        return Path(self.path)

    @property
    def memory_dir(self) -> Path:
        repo = self.path_obj
        if repo.is_dir():
            return repo / ".agents" / "memory"
        return ORPHANS / self.slug

    @property
    def detail_path(self) -> Path:
        return self.memory_dir / "README.md"

    @property
    def user_link_dir(self) -> Path:
        return USER_MEMORY / "projects" / self.slug

    @property
    def user_link_path(self) -> Path:
        return self.user_link_dir / "README.md"


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    # Atomic write via thread-unique temp file + os.replace
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(str(tmp_path), str(path))
                break
            except OSError:
                if attempt == 4:
                    path.write_text(content, encoding="utf-8")
                time.sleep(0.02 * (attempt + 1))
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass



def _default_roots() -> List[str]:
    candidates = [
        Path.home() / "Coding",
        Path.home() / "code",
        Path.home() / "Developer",
        Path.home() / "src",
    ]
    found = [str(p) for p in candidates if p.is_dir()]
    return found or [str(Path.home())]


def default_scan() -> dict:
    return {
        "roots": _default_roots(),
        "agent_rule_name": DEFAULT_RULE_NAME,
        "ignore_dir_names": sorted(SKIP_DIR_DEFAULT),
        "ignore_slugs": [],
        "expand_children": [],
    }


def shipped_layout_text() -> str:
    if not ABI_LAYOUT.is_file():
        raise FileNotFoundError(f"Missing shipped layout contract: {ABI_LAYOUT}")
    return _read(ABI_LAYOUT)


def _copy_if_missing(src: Path, dst: Path) -> bool:
    if not src.exists() or dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _is_scaffold_file(path: Path) -> bool:
    name = path.name
    return ".example." in name or name.endswith(".example.json") or name == "orphans.example.md"


def consolidate_repo_leaks() -> List[str]:
    """Move live markdown from the engine clone into ~/.agents/memory; delete clone copies."""
    moved: List[str] = []
    orphans_doc = ORPHANS / "README.md"
    if not orphans_doc.exists() and (EXAMPLES / "orphans.example.md").is_file():
        _write(orphans_doc, _read(EXAMPLES / "orphans.example.md"))

    def relocate(src: Path, dest: Path) -> None:
        if not src.is_file() or _is_scaffold_file(src):
            return
        if dest.exists() and dest.stat().st_size > 0:
            if src.resolve() != dest.resolve():
                orphan = ORPHANS / src.name
                orphan.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, orphan)
                moved.append(f"orphan copy {src} -> {orphan}")
            src.unlink()
            moved.append(f"removed clone leak {src}")
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append(str(dest))

    for clone_root in CLONE_LEAK_DIRS:
        if not clone_root.is_dir():
            continue
        relocate(clone_root / "USER.md", USER_MD)
        relocate(clone_root / "PROJECTS.md", PROJECTS_MD)
        relocate(clone_root / "scan.json", SCAN_JSON)
        relocate(clone_root / "chats-index.md", CHATS_INDEX)
        relocate(clone_root / "ingest.json", INGEST_JSON)
        facts = clone_root / "facts.md"
        if facts.is_file() and not _is_scaffold_file(facts):
            dest = ORPHANS / "facts.md"
            if dest.exists():
                for line in _read(facts).splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        _append_bullet(dest, stripped[2:].strip())
            else:
                relocate(facts, dest)
            if facts.exists():
                facts.unlink()
                moved.append(f"removed clone leak {facts}")
        projects = clone_root / "projects"
        if projects.is_dir():
            for src in sorted(projects.glob("*.md")):
                slug = src.stem
                dest = USER_MEMORY / "projects" / slug / "README.md"
                relocate(src, dest)
        for child in sorted(clone_root.rglob("*"), reverse=True):
            if child.is_dir() and not any(child.iterdir()):
                try:
                    child.rmdir()
                    moved.append(f"removed empty {child}")
                except OSError:
                    pass
    migrate_taxonomy()
    moved.extend(purge_engine_repo_injection())
    return moved


def _relocate_engine_staging(captured: Path) -> None:
    if not captured.is_file():
        return
    bullets = [
        ln.strip()[2:].strip()
        for ln in _read(captured).splitlines()
        if ln.strip().startswith("- ")
    ]
    if not bullets:
        return
    dest = USER_MEMORY / "staging" / "captured.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        _write(dest, STAGING_HEADER + "\n")
    for bullet in bullets:
        _append_bullet(dest, bullet)


def purge_engine_repo_injection() -> List[str]:
    """Remove ``.agents/`` and ``.cursor/`` from the engine clone (never project memory here)."""
    moved: List[str] = []
    captured = ROOT / ".agents" / "memory" / "staging" / "captured.md"
    _relocate_engine_staging(captured)
    for name in (".agents", ".cursor"):
        path = ROOT / name
        if not path.exists():
            continue
        shutil.rmtree(path)
        moved.append(f"removed engine {path}")
    return moved


def migrate_legacy_store() -> List[str]:
    """Deprecated alias. Use consolidate_repo_leaks()."""
    return consolidate_repo_leaks()


def _relocate(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dst.resolve():
        return False
    if dst.exists():
        return False
    shutil.move(str(src), str(dst))
    return True


def ensure_staging_inbox(mem: Path) -> None:
    """Bootstrap project memory with files only — no empty folder tree."""
    captured = mem / "staging" / "captured.md"
    if not captured.exists():
        _write(captured, STAGING_HEADER + "\n")


def _ensure_staging_banner(path: Path) -> None:
    if not path.exists() or path.parent.name != "staging":
        return
    text = _read(path)
    if text.lstrip().startswith("# Staging"):
        return
    _write(path, STAGING_HEADER + "\n" + text.lstrip())


def _merge_relocate(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dest.resolve():
        _ensure_staging_banner(dest)
        return
    if not dest.exists():
        _relocate(src, dest)
        _ensure_staging_banner(dest)
        return
    for line in _read(src).splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            _append_bullet(dest, stripped[2:].strip())
    src.unlink()
    _ensure_staging_banner(dest)


def migrate_taxonomy() -> None:
    """Folders instead of dump files. Safe to re-run."""
    projects_root = USER_MEMORY / "projects"
    if projects_root.is_dir():
        for src in list(projects_root.glob("*.md")):
            if src.name.lower() == "readme.md":
                continue
            _relocate(src, projects_root / src.stem / "README.md")
    notes_root = USER_MEMORY / "notes"
    known = {p.slug for p in parse_projects()} if PROJECTS_MD.exists() else set()
    if projects_root.is_dir():
        for child in projects_root.iterdir():
            if child.is_dir():
                known.add(child.name)
    collections = set(NOTE_COLLECTIONS)
    if notes_root.is_dir():
        for child in list(notes_root.iterdir()):
            if not child.is_dir() or child.name in collections:
                continue
            if child.name in known:
                _relocate(child, notes_root / "projects" / child.name)
            if child.is_dir() and child.exists() and not any(child.iterdir()):
                child.rmdir()
    if FACTS_MD.exists():
        dest = notes_root / "programming" / "chat-stores.md"
        if _relocate(FACTS_MD, dest) is False and dest.exists():
            FACTS_MD.unlink()
    for p in parse_projects():
        if is_engine_repo(p.path_obj):
            if not p.user_link_path.exists():
                _write(p.user_link_path, stub_project_md(p))
            continue
        mem = p.memory_dir
        if not mem.is_dir():
            continue
        ensure_staging_inbox(mem)
        _merge_relocate(mem / "facts.md", mem / "staging" / "captured.md")
        _merge_relocate(mem / "notes" / "captured.md", mem / "staging" / "captured.md")
        _merge_relocate(mem / "from-chats.md", mem / "staging" / "from-chats.md")
        _merge_relocate(mem / "research" / "from-chats.md", mem / "staging" / "from-chats.md")
        if not p.detail_path.exists():
            _write(p.detail_path, stub_project_md(p))
        if not p.user_link_path.exists():
            _write(p.user_link_path, stub_project_md(p))


def ensure_memory_layout() -> None:
    """Create ~/.agents/memory and copy example scaffolding if missing."""
    USER_MEMORY.mkdir(parents=True, exist_ok=True)
    _write(LAYOUT_MD, shipped_layout_text())
    orphans_doc = ORPHANS / "README.md"
    if not orphans_doc.exists() and (EXAMPLES / "orphans.example.md").is_file():
        _write(orphans_doc, _read(EXAMPLES / "orphans.example.md"))
    notes_readme = USER_MEMORY / "notes" / "README.md"
    if not notes_readme.exists():
        _write(
            notes_readme,
            "# Note collections\n\n"
            "Guide folders (not a closed set): `projects/` `interests/` "
            "`education/` `finance/` `family/` `preferences/` `programming/` "
            "`work/` `certifications/` `scratch/`.\n\n"
            "Add a new folder when a fact does not fit. "
            "`notes/projects/<slug>/` is personal notes about a project. "
            "The project **link** is `projects/<slug>/README.md`. "
            "Research, plans, tasks, waves, roadmap, decisions, and lifecycle notes live in "
            "`<repo>/.agents/memory/`. `staging/` there is an inbox, not memory.\n",
        )
    pairs = (
        (EXAMPLES / "USER.example.md", USER_MD),
        (EXAMPLES / "PROJECTS.example.md", PROJECTS_MD),
        (EXAMPLES / "scan.example.json", SCAN_JSON),
        (EXAMPLES / "ingest.example.json", INGEST_JSON),
    )
    for src, dst in pairs:
        if dst.exists() or not src.exists():
            continue
        _write(dst, _read(src))


def load_scan() -> dict:
    ensure_memory_layout()
    if not SCAN_JSON.exists():
        cfg = default_scan()
        save_scan(cfg)
        return cfg
    cfg = json.loads(_read(SCAN_JSON))
    if not cfg.get("agent_rule_name"):
        cfg["agent_rule_name"] = cfg.get("cursor_rule_name") or DEFAULT_RULE_NAME
    if not cfg.get("roots"):
        cfg["roots"] = _default_roots()
    if "ignore_dir_names" not in cfg:
        cfg["ignore_dir_names"] = sorted(SKIP_DIR_DEFAULT)
    if "ignore_slugs" not in cfg:
        cfg["ignore_slugs"] = []
    if "expand_children" not in cfg:
        cfg["expand_children"] = []
    return cfg


def agent_rule_name() -> str:
    cfg = load_scan()
    name = str(cfg.get("agent_rule_name") or cfg.get("cursor_rule_name") or DEFAULT_RULE_NAME).strip()
    if not name.endswith(".mdc"):
        name += ".mdc"
    return name


def canonical_agent_rule() -> Path:
    return AGENTS_RULES / agent_rule_name()


def injection_agent_rule() -> Path:
    """Canonical always-on rule path (provider-agnostic)."""
    return canonical_agent_rule()


HOST_RULE_DIRS = (
    Path.home() / ".cursor" / "rules",
)


def bind_host_rules(canonical: Path) -> Tuple[List[str], List[str]]:
    """Bind every ``~/.agents/rules/*.mdc`` into host rule slots (e.g. ``~/.cursor/rules/``)."""
    written: List[str] = []
    warnings: List[str] = []
    AGENTS_RULES.mkdir(parents=True, exist_ok=True)
    sources = sorted(AGENTS_RULES.glob("*.mdc"), key=lambda p: p.name.lower())
    if canonical.exists() and canonical not in sources:
        sources.insert(0, canonical)
    for rules_dir in HOST_RULE_DIRS:
        rules_dir.mkdir(parents=True, exist_ok=True)
        for src in sources:
            dest = rules_dir / src.name
            if dest.resolve() == src.resolve():
                continue
            path, method = bind_to(dest, src)
            _bind_collect(path, method, written, warnings)
    return written, warnings


def profile_title() -> str:
    for line in _read(USER_MD).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "agent memory"


def scan_roots() -> List[str]:
    return [str(Path(r).expanduser()) for r in (load_scan().get("roots") or [])]


def mcp_entry() -> dict:
    entry: dict = {
        "command": sys.executable,
        "args": ["-m", "agents_memory.mcp_server"],
    }
    src_dir = ROOT / "src"
    if src_dir.is_dir():
        entry["env"] = {"PYTHONPATH": str(src_dir.resolve())}
    return entry


def mcp_snippet() -> str:
    return json.dumps({"agents-memory": mcp_entry()}, indent=2)


def cursor_mcp_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def claude_desktop_config_path() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def known_host_mcp_paths() -> List[Path]:
    """All known agent and IDE MCP configuration file paths across operating systems."""
    home = Path.home()
    paths: List[Path] = [
        # Cursor
        home / ".cursor" / "mcp.json",
        # Windsurf
        home / ".codeium" / "windsurf" / "mcp_config.json",
        # Claude Desktop
        claude_desktop_config_path(),
        # Antigravity / Gemini CLI
        home / ".gemini" / "antigravity-ide" / "mcp_config.json",
        home / ".gemini" / "config" / "mcp_config.json",
        home / ".gemini" / "config" / "mcp.json",
        # OpenAI / Codex
        home / ".codex" / "mcp.json",
        home / ".codex" / "config.json",
        home / ".openai" / "mcp.json",
    ]

    # Roo Code & Cline (VS Code, VS Code Insiders, VSCodium)
    vscode_roots: List[Path] = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        vscode_roots.extend(
            [
                Path(appdata) / "Code" / "User",
                Path(appdata) / "Code - Insiders" / "User",
                Path(appdata) / "VSCodium" / "User",
            ]
        )
    elif sys.platform == "darwin":
        vscode_roots.extend(
            [
                home / "Library" / "Application Support" / "Code" / "User",
                home / "Library" / "Application Support" / "Code - Insiders" / "User",
                home / "Library" / "Application Support" / "VSCodium" / "User",
            ]
        )
    else:
        vscode_roots.extend(
            [
                home / ".config" / "Code" / "User",
                home / ".config" / "Code - Insiders" / "User",
                home / ".config" / "VSCodium" / "User",
            ]
        )

    for vroot in vscode_roots:
        paths.extend(
            [
                vroot
                / "globalStorage"
                / "rooveterinaryinc.roo-cline"
                / "settings"
                / "cline_mcp_settings.json",
                vroot
                / "globalStorage"
                / "saoudrizwan.claude-dev"
                / "settings"
                / "cline_mcp_settings.json",
                vroot
                / "globalStorage"
                / "claude-dev"
                / "settings"
                / "cline_mcp_settings.json",
            ]
        )

    return paths


def user_profile_looks_blank() -> bool:
    return bool(re.search(r"^- Name:\s*$", _read(USER_MD), re.M))


def _merge_mcp_server_into_file(path: Path) -> str:
    if not path.parent.exists():
        return ""
    if path.exists():
        raw = _read(path)
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            return f"FAIL {path}: invalid JSON ({e})."
        if not isinstance(data, dict):
            return f"FAIL {path}: root is not an object."
    else:
        data = {}
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return f"FAIL {path}: mcpServers is not an object."
    servers.pop("agent-memory", None)
    servers.pop("agent_memory", None)
    servers["agents-memory"] = mcp_entry()
    _write(path, json.dumps(data, indent=2, ensure_ascii=False))
    return f"OK {path}"


def merge_agent_mcp() -> str:
    """Insert/update the agents-memory server in all installed host MCP configs."""
    cursor_p = cursor_mcp_path()
    cursor_p.parent.mkdir(parents=True, exist_ok=True)
    targets = known_host_mcp_paths()
    results: List[str] = []
    seen: set[str] = set()
    for target in targets:
        key = str(target.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        if target.parent.exists() or target == cursor_p:
            res = _merge_mcp_server_into_file(target)
            if res:
                results.append(res)
    return "; ".join(results) if results else f"OK {cursor_p}"


def zed_config_dir() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "Zed"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "zed"
    return Path.home() / ".config" / "zed"


def zed_settings_path() -> Path:
    return zed_config_dir() / "settings.json"


def zed_agents_path() -> Path:
    return zed_config_dir() / "AGENTS.md"


def _strip_jsonc(text: str) -> str:
    out: List[str] = []
    i = 0
    n = len(text)
    in_str = False
    escape = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_str:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
            continue
        out.append(ch)
        i += 1
    stripped = "".join(out)
    stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
    return stripped


def _load_jsonc(path: Path) -> dict:
    raw = _read(path)
    if not raw.strip():
        return {}
    data = json.loads(_strip_jsonc(raw))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root is not an object")
    return data


def _resolve_cmd(cmd: str) -> str:
    if not cmd:
        return cmd
    p = Path(cmd)
    if p.is_file():
        return str(p)
    found = shutil.which(cmd)
    return found or cmd


def _mcp_servers_from_file(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(_read(path) or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    servers = data.get("mcpServers") or data.get("context_servers") or {}
    if not isinstance(servers, dict):
        return {}
    out: Dict[str, dict] = {}
    for name, spec in servers.items():
        if isinstance(name, str) and isinstance(spec, dict):
            out[name] = spec
    return out


def collect_mcp_servers() -> Dict[str, dict]:
    """Union of your Agent host MCP configs. Later files fill missing fields only."""
    sources = known_host_mcp_paths()
    merged: Dict[str, dict] = {}
    seen: set[str] = set()
    for path in sources:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        for name, spec in _mcp_servers_from_file(path).items():
            if name not in merged:
                merged[name] = dict(spec)
                continue
            for k, val in spec.items():
                if k not in merged[name] or merged[name][k] in (None, "", {}, []):
                    merged[name][k] = val
    merged.pop("agent-memory", None)
    merged.pop("agent_memory", None)
    merged["agents-memory"] = mcp_entry()
    return merged


def mcp_spec_to_zed(spec: dict) -> dict:
    url = spec.get("url")
    if isinstance(url, str) and url.strip():
        entry: dict = {"source": "custom", "url": url.strip()}
        headers = spec.get("headers")
        if isinstance(headers, dict) and headers:
            entry["headers"] = headers
        return entry
    cmd = spec.get("command")
    if isinstance(cmd, dict):
        path = str(cmd.get("path") or cmd.get("command") or "")
        args = cmd.get("args") or []
        env = cmd.get("env") or {}
        entry = {
            "source": "custom",
            "command": _resolve_cmd(path),
            "args": list(args) if isinstance(args, list) else [],
        }
        if isinstance(env, dict) and env:
            entry["env"] = env
        return entry
    command = _resolve_cmd(str(cmd or ""))
    args = spec.get("args") or []
    env = spec.get("env") or {}
    entry = {
        "source": "custom",
        "command": command,
        "args": list(args) if isinstance(args, list) else [],
    }
    if isinstance(env, dict) and env:
        entry["env"] = env
    return entry


def merge_zed_mcp() -> str:
    """Upsert merged MCP servers into Zed settings.json context_servers."""
    path = zed_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            data = _load_jsonc(path)
        except (json.JSONDecodeError, ValueError) as e:
            return f"FAIL {path}: {e}. Merge skipped."
    else:
        data = {}
    servers = data.get("context_servers")
    if not isinstance(servers, dict):
        servers = {}
        data["context_servers"] = servers
    servers.pop("agent-memory", None)
    servers.pop("agent_memory", None)
    for name, spec in collect_mcp_servers().items():
        servers[name] = mcp_spec_to_zed(spec)
    agent = data.get("agent")
    if not isinstance(agent, dict):
        agent = {}
        data["agent"] = agent
    perms = agent.get("tool_permissions")
    if not isinstance(perms, dict):
        perms = {}
        agent["tool_permissions"] = perms
    perms.setdefault("default", "allow")
    _write(path, json.dumps(data, indent=2, ensure_ascii=False))
    return f"OK {path} ({len(servers)} context_servers)"


def skill_source_roots() -> List[Path]:
    home = Path.home()
    return [
        home / ".cursor" / "skills",
        home / ".gemini" / "config" / "skills",
        home / ".claude" / "skills",
    ]


def zed_skills_root() -> Path:
    return Path.home() / ".agents" / "skills"


def mirror_skills_to_zed() -> List[str]:
    """Copy user skills from agent host folders into ~/.agents/skills (Zed global)."""
    dest_root = zed_skills_root()
    dest_root.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    for src_root in skill_source_roots():
        if not src_root.is_dir():
            continue
        for child in sorted(src_root.iterdir()):
            if not child.is_dir() or child.name in SKIP_SKILL_NAMES:
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue
            dest = dest_root / child.name
            if dest.resolve() == child.resolve():
                continue
            if dest.exists():
                continue
            shutil.copytree(child, dest)
            written.append(str(dest / "SKILL.md"))
    return written


def save_scan(cfg: dict) -> None:
    _write(SCAN_JSON, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def parse_projects(md: Optional[str] = None) -> List[Project]:
    text = md if md is not None else _read(PROJECTS_MD)
    out: List[Project] = []
    for line in text.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        slug = m.group("slug").strip()
        if slug in {"slug", "------"} or slug.startswith("-"):
            continue
        out.append(
            Project(
                slug=slug,
                path=m.group("path").strip(),
                role=m.group("role").strip(),
                stack=m.group("stack").strip(),
                status=m.group("status").strip(),
            )
        )
    return out


def projects_by_slug() -> Dict[str, Project]:
    return {p.slug: p for p in parse_projects()}


def render_projects_table(projects: Iterable[Project]) -> str:
    rows = [
        "# Projects",
        "",
        "Canonical map. Change via `python -m agents_memory inventory`, MCP `register_project`, or skill `memory-sync`.",
        "",
        "| slug | path | role | stack | status |",
        "|------|------|------|-------|--------|",
    ]
    for p in sorted(projects, key=lambda x: x.slug.lower()):
        rows.append(
            f"| {p.slug} | `{p.path}` | {p.role} | {p.stack} | {p.status} |"
        )
    return "\n".join(rows) + "\n"


def write_projects(projects: List[Project]) -> None:
    _write(PROJECTS_MD, render_projects_table(projects))


def _looks_like_project(path: Path) -> bool:
    if not path.is_dir():
        return False
    markers = (
        ".git",
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "AGENTS.md",
        "README.md",
        "src",
        "src-tauri",
        "go.mod",
    )
    return any((path / m).exists() for m in markers)


def _parse_workspace_uri(uri: str) -> Optional[Path]:
    if not uri or not isinstance(uri, str):
        return None
    uri = uri.strip()
    if uri.startswith("file://"):
        raw = urllib.parse.unquote(uri[7:])
        if os.name == "nt" and raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
            raw = raw[1:]
        p = Path(raw)
        if p.is_dir():
            return p.resolve()
    else:
        p = Path(uri).expanduser()
        if p.is_dir():
            return p.resolve()
    return None


def discover_ide_workspaces() -> List[Path]:
    """Auto-discover active and historical project workspaces from IDE configs and brains without user input."""
    discovered: List[Path] = []
    seen: set[str] = set()

    def add(p: Optional[Path]) -> None:
        if not p or not p.is_dir():
            return
        key = str(p.resolve()).lower()
        if key in seen:
            return
        seen.add(key)
        discovered.append(p.resolve())

    home = Path.home()

    # 1. Antigravity IDE brains (brain/*/task.md, transcript.jsonl)
    antigravity_brains = home / ".gemini" / "antigravity-ide" / "brain"
    if antigravity_brains.is_dir():
        for brain in antigravity_brains.iterdir():
            if not brain.is_dir() or brain.name.startswith("."):
                continue
            transcript = brain / ".system_generated" / "logs" / "transcript.jsonl"
            if transcript.is_file():
                try:
                    with transcript.open(encoding="utf-8", errors="replace") as fh:
                        for idx, line in enumerate(fh):
                            if idx > 20:
                                break
                            for match in re.finditer(r"(?:[a-zA-Z]:[/\\][^\r\n<>\"'\s]+|/(?:Users|home|root)/[^\r\n<>\"'\s]+)", line):
                                candidate = Path(match.group(0).strip().rstrip(";,.)]"))
                                if candidate.is_dir() and _looks_like_project(candidate):
                                    add(candidate)
                except OSError:
                    pass

    # 2. Cursor, VS Code, VSCodium workspaceStorage
    storage_roots: List[Path] = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        for ide_name in ("Cursor", "Code", "Code - Insiders", "VSCodium"):
            storage_roots.append(Path(appdata) / ide_name / "User" / "workspaceStorage")
    elif sys.platform == "darwin":
        for ide_name in ("Cursor", "Code", "Code - Insiders", "VSCodium"):
            storage_roots.append(home / "Library" / "Application Support" / ide_name / "User" / "workspaceStorage")
    else:
        for ide_name in ("Cursor", "Code", "Code - Insiders", "VSCodium"):
            storage_roots.append(home / ".config" / ide_name / "User" / "workspaceStorage")

    for storage_root in storage_roots:
        if not storage_root.is_dir():
            continue
        try:
            for ws_dir in storage_root.iterdir():
                if not ws_dir.is_dir():
                    continue
                ws_json = ws_dir / "workspace.json"
                if ws_json.is_file():
                    try:
                        data = json.loads(_read(ws_json))
                        folder = data.get("folder") or (data.get("configuration") or {}).get("folder")
                        if folder:
                            add(_parse_workspace_uri(str(folder)))
                    except (json.JSONDecodeError, OSError):
                        pass
        except OSError:
            pass

    # 3. Cursor projects folder (~/.cursor/projects)
    cursor_projects = home / ".cursor" / "projects"
    if cursor_projects.is_dir():
        try:
            for proj in cursor_projects.iterdir():
                if proj.is_dir():
                    name = proj.name
                    if name.startswith("c-Users-") or name.startswith("c--") or name.startswith("Users-"):
                        parts = name.split("-")
                        if len(parts) >= 4 and parts[0].lower() == "c" and parts[1].lower() == "users":
                            reconstructed = Path(f"C:/{parts[2]}/{'/'.join(parts[3:])}")
                            if reconstructed.is_dir() and _looks_like_project(reconstructed):
                                add(reconstructed)
        except OSError:
            pass

    return discovered


def discover_disk() -> List[Tuple[str, Path]]:
    cfg = load_scan()
    ignore_names = set(cfg.get("ignore_dir_names") or []) | SKIP_DIR_DEFAULT
    ignore_slugs = set(cfg.get("ignore_slugs") or [])
    expand = set(cfg.get("expand_children") or [])
    found: List[Tuple[str, Path]] = []
    seen_paths = set()

    def add(slug: str, path: Path) -> None:
        if slug in ignore_slugs:
            return
        resolved = path.resolve()
        key = str(resolved).lower()
        if key in seen_paths:
            return
        seen_paths.add(key)
        found.append((slug, resolved))

    # 1. Configured roots
    for root in cfg.get("roots") or []:
        root_path = Path(root).expanduser()
        if not root_path.is_dir():
            continue
        try:
            for child in sorted(root_path.iterdir()):
                if not child.is_dir() or child.name in ignore_names:
                    continue
                if child.name.startswith("."):
                    continue
                add(child.name, child)
                if child.name in expand:
                    for nested in sorted(child.iterdir()):
                        if not nested.is_dir() or nested.name in ignore_names:
                            continue
                        if nested.name.startswith("."):
                            continue
                        if _looks_like_project(nested):
                            add(nested.name, nested)
        except OSError:
            pass

    # 2. Auto-discovered IDE workspaces (Zero manual folder searching!)
    for ws_path in discover_ide_workspaces():
        if ws_path.name in ignore_names or ws_path.name.startswith("."):
            continue
        add(ws_path.name, ws_path)

    return found


def inventory_report() -> dict:
    tracked = parse_projects()
    by_slug = {p.slug: p for p in tracked}
    by_path = {str(p.path_obj.resolve()).lower(): p for p in tracked if p.path_obj.exists()}
    disk = discover_disk()
    unknown = []
    known = []
    moved = []
    seen_moved_slugs = set()

    for slug, path in disk:
        resolved = path.resolve()
        key = str(resolved).lower()
        if key in by_path:
            known.append({"slug": slug, "path": str(resolved), "status": "tracked"})
        elif slug in by_slug:
            existing_p = by_slug[slug]
            if existing_p.path_obj.exists():
                unknown.append({"slug": slug, "path": str(resolved)})
            else:
                moved.append({
                    "slug": slug,
                    "old_path": existing_p.path,
                    "new_path": str(resolved),
                    "confidence": "high",
                })
                seen_moved_slugs.add(slug)
        else:
            unknown.append({"slug": slug, "path": str(resolved)})

    missing = []
    for p in tracked:
        if not p.path_obj.exists():
            missing.append({"slug": p.slug, "path": p.path})

    # Additional moved-repo heuristic for renamed directories
    for m in missing:
        if m["slug"] in seen_moved_slugs:
            continue
        old_slug = m["slug"].lower()
        old_dir_name = Path(m["path"]).name.lower()
        for u in unknown:
            u_slug = u["slug"].lower()
            u_path = Path(u["path"])
            u_dir_name = u_path.name.lower()
            is_exact = (u_slug == old_slug or u_dir_name == old_dir_name)
            is_partial = (
                (len(old_slug) >= 3 and (old_slug in u_slug or u_slug in old_slug))
                or (len(old_dir_name) >= 3 and (old_dir_name in u_dir_name or u_dir_name in old_dir_name))
            )
            if is_exact or is_partial:
                moved.append({
                    "slug": m["slug"],
                    "old_path": m["path"],
                    "new_path": u["path"],
                    "confidence": "high" if is_exact else "medium",
                })
                seen_moved_slugs.add(m["slug"])
                break

    # Disambiguate slug collisions among unknown projects
    slug_counts: dict[str, int] = {}
    for u in unknown:
        s = u["slug"]
        slug_counts[s] = slug_counts.get(s, 0) + 1
    for u in unknown:
        if slug_counts[u["slug"]] > 1:
            p = Path(u["path"])
            parent_name = p.parent.name.lower()
            if parent_name and parent_name not in ("coding", "src", "code", "dev", "developer"):
                u["suggested_slug"] = f"{parent_name}-{u['slug']}"

    cfg = load_scan()
    return {
        "tracked": [p.__dict__ for p in tracked],
        "unknown": unknown,
        "missing": missing,
        "moved": moved,
        "ignored": cfg.get("ignore_slugs") or [],
        "known_on_disk": known,
    }


def stub_project_md(p: Project) -> str:
    return (
        f"---\n"
        f"slug: {p.slug}\n"
        f"path: {p.path}\n"
        f"role: {p.role}\n"
        f"stack: {p.stack}\n"
        f"status: {p.status}\n"
        f"---\n\n"
        f"# {p.slug}\n\n"
        f"{p.role} · `{p.stack}` · {p.status}\n\n"
        f"Path: `{p.path}`. MCP `get_project_memories(\"{p.slug}\")` for in-tree memory.\n"
    )


def ensure_project_file(p: Project, overwrite_empty: bool = False) -> None:
    if is_engine_repo(p.path_obj):
        p.user_link_path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite_empty or not p.user_link_path.exists():
            _write(p.user_link_path, stub_project_md(p))
        return
    dest = p.detail_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not is_engine_repo(p.path_obj):
        ensure_staging_inbox(p.memory_dir)
        if p.path_obj.is_dir():
            gi = dest.parent / ".gitignore"
            if not gi.exists():
                _write(gi, "*\n!.gitignore\n")
    if overwrite_empty or not dest.exists():
        _write(dest, stub_project_md(p))
    if overwrite_empty or not p.user_link_path.exists():
        _write(p.user_link_path, stub_project_md(p))


def register_project(
    slug: str,
    path: str,
    role: str = "unclassified",
    stack: str = "—",
    status: str = "active",
) -> Project:
    slug = slug.strip()
    path = str(Path(path).expanduser().resolve())
    projects = parse_projects()
    existing = {p.slug: p for p in projects}
    p = Project(slug=slug, path=path, role=role, stack=stack, status=status)
    existing[slug] = p
    write_projects(list(existing.values()))
    ensure_project_file(p)
    return p


def ignore_slug(slug: str) -> None:
    cfg = load_scan()
    ignored = list(cfg.get("ignore_slugs") or [])
    if slug not in ignored:
        ignored.append(slug)
        cfg["ignore_slugs"] = sorted(ignored)
        save_scan(cfg)


def is_compact_always_on() -> bool:
    cfg = load_scan()
    return bool(cfg.get("compact_always_on", True))


def compact_projects_text(projects: List[Project]) -> str:
    lines = [
        "# Projects (Compact)",
        "",
        "Use MCP `get_project_memories(project=slug)` or `search_memory` for details.",
        "",
        "| slug | role | stack | status |",
        "| --- | --- | --- | --- |",
    ]
    for p in projects:
        lines.append(f"| {p.slug} | {p.role} | {p.stack} | {p.status} |")
    return "\n".join(lines) + "\n"


def always_on_body() -> str:
    user = _read(USER_MD).strip()
    if is_compact_always_on():
        projects = compact_projects_text(parse_projects()).strip()
    else:
        projects = _read(PROJECTS_MD).strip()
    summary = staging_status_summary()
    nag = summary.get("nag")
    alert_section = ""
    if nag:
        alert_section = (
            "\n\n---\n\n"
            "# Active Alerts\n\n"
            f"> ⚠️ **Memory Staging Action Required**: {nag}\n"
            "> Proactively process the staging inbox using MCP `get_staging_inbox` + `distill_batch` (or `auto_distill` / skill `memory-distill`).\n"
        )
    return f"{user}\n\n---\n\n{projects}{alert_section}\n"


def agent_rule_text() -> str:
    return (
        "---\n"
        f"description: {profile_title()}. Always apply.\n"
        "alwaysApply: true\n"
        "---\n\n"
        f"{MARKER}\n\n"
        f"{always_on_body()}"
    )


def gemini_agents_text() -> str:
    return f"{MARKER}\n\n{always_on_body()}"


def project_agents_text(p: Project) -> str:
    return (
        f"{MARKER}\n\n"
        f"# Project: {p.slug}\n\n"
        f"**Path:** `{p.path}`  \n"
        f"**Role:** {p.role}  \n"
        f"**Stack:** {p.stack}\n\n"
        f"In-tree memory: `.agents/memory/` (staging inbox — distill, do not hoard). "
        f"Global profile: `~/.agents/AGENTS.md`. "
        f"MCP `search_memory` / `get_project_memories(\"{p.slug}\")` for detail.\n"
    )


def _should_overwrite_agents(path: Path) -> bool:
    if not path.exists():
        return True
    text = _read(path)
    if MARKER in text:
        return True
    if "mem0" in text.lower() or "Mem0" in text:
        return True
    stripped = text.lstrip()
    if stripped.startswith("# Globales User-Profil"):
        return True
    return False


def purge_legacy_rules(rules_dir: Path) -> List[str]:
    """Delete old rule filenames so alwaysApply does not double-load."""
    if not rules_dir.is_dir():
        return []
    current = agent_rule_name().lower()
    removed: List[str] = []
    for path in list(rules_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name == current:
            continue
        stem = path.stem.lower()
        drop = stem in LEGACY_RULE_STEMS or name.startswith("felix-always.")
        if not drop and path.suffix.lower() in {".mdc", ".md", ".mdr"}:
            if MARKER in _read(path):
                drop = True
        if drop:
            path.unlink()
            removed.append(str(path))
    return removed


def iter_rules_dirs() -> List[Path]:
    seen = set()
    out: List[Path] = []

    def add(path: Path) -> None:
        key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        out.append(path)

    add(AGENTS_RULES)
    for rules_dir in HOST_RULE_DIRS:
        add(rules_dir)
    return out


def purge_legacy_rules_everywhere() -> List[str]:
    removed: List[str] = []
    for rules_dir in iter_rules_dirs():
        removed.extend(purge_legacy_rules(rules_dir))
    return removed


def _is_git_symlink_stub(path: Path) -> bool:
    """True when a Windows checkout turned a git symlink into a 9-byte path file."""
    try:
        if path.is_symlink():
            return False
    except OSError:
        pass
    if not path.exists() or path.stat().st_size > 64:
        return False
    return _read(path).strip() in {"AGENTS.md", "CLAUDE.md"}


def _is_foreign_instruction_file(path: Path) -> bool:
    """True if the file exists and is not ours to overwrite."""
    if not path.exists() and not path.is_symlink():
        return False
    if _is_git_symlink_stub(path):
        return False
    if MARKER in _read(path) or _should_overwrite_agents(path):
        return False
    return True


def _ensure_claude_pointer(path: Path) -> None:
    text = _read(path)
    if POINTER_MARK in text:
        return
    extra = (
        f"\n\n{POINTER_MARK}\n"
        "Also read `AGENTS.md` in this folder (bound to `~/.agents/AGENTS.md`) "
        "for user memory.\n"
    )
    path.write_text(text.rstrip() + extra + ("\n" if not extra.endswith("\n") else ""), encoding="utf-8")


def _bound_to(link: Path, target: Path) -> bool:
    if not target.exists():
        return False
    try:
        if link.is_symlink():
            got = Path(os.readlink(str(link)))
            if not got.is_absolute():
                got = (link.parent / got)
            return got.resolve() == target.resolve()
        if not link.exists():
            return False
        ls, ts = link.stat(), target.stat()
        return ls.st_ino == ts.st_ino and ls.st_dev == ts.st_dev
    except OSError:
        return False


def bind_to(link: Path, target: Path, force: bool = False) -> Tuple[str, str]:
    """Point `link` at `target`: symlink, else hardlink, else copy.

    Returns ``(path, method)`` where method is ``symlink``, ``hardlink``,
    ``copy``, ``skip``, or ``already``.
    """
    target = Path(target)
    if not target.exists():
        raise FileNotFoundError(target)
    link = Path(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    if _bound_to(link, target):
        return str(link), "already"
    if link.exists() or link.is_symlink():
        if (
            not force
            and _is_foreign_instruction_file(link)
            and not _is_git_symlink_stub(link)
        ):
            try:
                same = target.exists() and _read(link) == _read(target)
            except OSError:
                same = False
            if not same:
                return "", "skip"
        link.unlink()
    rel = os.path.relpath(str(target), start=str(link.parent))
    try:
        os.symlink(rel, str(link))
        return str(link), "symlink"
    except OSError:
        pass
    try:
        os.link(str(target), str(link))
        return str(link), "hardlink"
    except OSError:
        shutil.copy2(str(target), str(link))
        return str(link), "copy"


def write_instruction_pair(directory: Path, body: str) -> List[str]:
    """Write AGENTS.md, then bind CLAUDE.md to it.

    If CLAUDE.md is foreign, leave it and append a pointer. If AGENTS.md is
    foreign, skip the directory.
    """
    directory.mkdir(parents=True, exist_ok=True)
    agents = directory / "AGENTS.md"
    claude = directory / "CLAUDE.md"
    if _is_foreign_instruction_file(agents):
        return []
    _write(agents, body)
    written = [str(agents)]
    if _is_foreign_instruction_file(claude):
        _ensure_claude_pointer(claude)
        written.append(str(claude))
        return written
    bound, _method = bind_to(claude, agents)
    if bound:
        written.append(bound)
    return written


def bind_dir_to_canonical(directory: Path, canonical: Path) -> Tuple[List[str], List[str]]:
    """AGENTS.md and CLAUDE.md in `directory` bound to the canonical user file."""
    directory.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    warnings: List[str] = []
    agents = directory / "AGENTS.md"
    claude = directory / "CLAUDE.md"
    if _is_foreign_instruction_file(agents):
        return written, warnings
    path, method = bind_to(agents, canonical)
    _bind_collect(path, method, written, warnings)
    if _is_foreign_instruction_file(claude):
        _ensure_claude_pointer(claude)
        written.append(str(claude))
        return written, warnings
    path, method = bind_to(claude, agents if agents.exists() else canonical)
    _bind_collect(path, method, written, warnings)
    return written, warnings


def bind_claude_home(canonical: Path) -> Tuple[List[str], List[str]]:
    """~/.claude/AGENTS.md and CLAUDE.md → canonical (replaces foreign CLAUDE.md)."""
    CLAUDE_HOME.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    warnings: List[str] = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        dest = CLAUDE_HOME / name
        path, method = bind_to(dest, canonical, force=True)
        if path:
            written.append(path)
        if method == "copy":
            warnings.append(
                f"{dest}: bound by copy (symlink/hardlink failed — "
                "edit AGENTS.md only; re-run python -m agents_memory sync after changes or use Developer Mode / native FS)"
            )
    return written, warnings


def _bind_collect(path: str, method: str, written: List[str], warnings: List[str]) -> None:
    if path:
        written.append(path)
    if method == "copy":
        warnings.append(
            f"{path}: bound by copy (symlink/hardlink failed — may drift; see LAYOUT.md / README)"
        )


def repair_instruction_stub(directory: Path) -> List[str]:
    """Replace a 9-byte git-symlink checkout (or an identical copy) with a bind to AGENTS.md.

    The engine repo root always binds: CLAUDE.md and AGENTS.md are the same content.
    """
    agents = directory / "AGENTS.md"
    claude = directory / "CLAUDE.md"
    if not agents.exists():
        return []
    force = directory.resolve() == ROOT.resolve()
    same = False
    try:
        same = claude.exists() and not claude.is_symlink() and _read(claude) == _read(agents)
    except OSError:
        same = False
    stub = _is_git_symlink_stub(claude)
    if _is_foreign_instruction_file(claude) and not stub and not same and not force:
        return []
    if force and (claude.exists() or claude.is_symlink()) and not _bound_to(claude, agents):
        claude.unlink()
    bound, method = bind_to(claude, agents)
    return [bound] if bound else []


def inject_into_repo(p: Project) -> List[str]:
    written: List[str] = []
    repo = p.path_obj
    if not repo.is_dir() or is_engine_repo(repo):
        return written
    ensure_project_file(p)
    written.append(str(p.detail_path))
    written.append(str(p.user_link_path))
    written.extend(write_instruction_pair(repo / ".agents", project_agents_text(p)))
    return written


def _machine_paths_block() -> str:
    py = sys.executable
    roots = ", ".join(f"`{r}`" for r in scan_roots()) or "`scan.json` roots"
    return (
        f"Install (engine): `{ROOT}`  \n"
        f"User memory: `{USER_MEMORY}`  \n"
        f"Project memory: `<repo>/.agents/memory`  \n"
        f"Agent rule: `{AGENTS_RULES / agent_rule_name()}`  \n"
        f"Scan roots: {roots}\n\n"
        "Scripts (any workspace, after `pip install -e` this clone):\n\n"
        "```powershell\n"
        f"{py} -m agents_memory inventory\n"
        f"{py} -m agents_memory inventory --json\n"
        f"{py} -m agents_memory sync\n"
        f"{py} -m agents_memory ingest catalog\n"
        f"{py} -m agents_memory ingest run\n"
        "```\n\n"
        "Register:\n\n"
        "```powershell\n"
        f'{py} -m agents_memory inventory --register SLUG "C:\\path\\to\\repo" "role here" "stack here"\n'
        "```\n"
    )


def machine_skill_text() -> str:
    template = _read(SKILL_TEMPLATE)
    if not template:
        return ""
    if PATHS_BEGIN in template and PATHS_END in template:
        pre, rest = template.split(PATHS_BEGIN, 1)
        _, post = rest.split(PATHS_END, 1)
        return (
            pre
            + PATHS_BEGIN
            + "\n"
            + _machine_paths_block().rstrip()
            + "\n"
            + PATHS_END
            + post
        )
    return template


def install_skills() -> List[str]:
    text = machine_skill_text()
    written: List[str] = []
    if text:
        targets = [
            Path.home() / ".cursor" / "skills" / "memory-sync" / "SKILL.md",
            Path.home() / ".agents" / "skills" / "memory-sync" / "SKILL.md",
            Path.home() / ".gemini" / "config" / "skills" / "memory-sync" / "SKILL.md",
        ]
        for path in targets:
            _write(path, text)
            written.append(str(path))

    distill_src = (
        (ROOT / "skills" / "memory-distill" / "SKILL.md")
        if (ROOT / "skills" / "memory-distill" / "SKILL.md").is_file()
        else (PACKAGE_DIR / "bundled" / "skills" / "memory-distill" / "SKILL.md")
    )
    if distill_src.is_file():
        d_text = _read(distill_src)
        d_targets = [
            Path.home() / ".cursor" / "skills" / "memory-distill" / "SKILL.md",
            Path.home() / ".agents" / "skills" / "memory-distill" / "SKILL.md",
            Path.home() / ".gemini" / "config" / "skills" / "memory-distill" / "SKILL.md",
        ]
        for path in d_targets:
            _write(path, d_text)
            written.append(str(path))
    return written


def sync_injection(include_repos: bool = True) -> Tuple[List[str], List[str]]:
    ensure_memory_layout()
    written: List[str] = []
    warnings: List[str] = []
    body = gemini_agents_text()
    AGENTS_HOME.mkdir(parents=True, exist_ok=True)
    _write(HOME_AGENTS, body)
    written.append(str(HOME_AGENTS))
    written.extend(repair_instruction_stub(AGENTS_HOME))
    for fn in (
        lambda: bind_dir_to_canonical(INJECTION_GEMINI.parent, HOME_AGENTS),
        lambda: bind_dir_to_canonical(zed_config_dir(), HOME_AGENTS),
    ):
        w, warn = fn()
        written.extend(w)
        warnings.extend(warn)
    claude_written, claude_warn = bind_claude_home(HOME_AGENTS)
    written.extend(claude_written)
    warnings.extend(claude_warn)
    AGENTS_RULES.mkdir(parents=True, exist_ok=True)
    rule = canonical_agent_rule()
    _write(rule, agent_rule_text())
    written.append(str(rule))
    host_rules, host_warn = bind_host_rules(rule)
    written.extend(host_rules)
    warnings.extend(host_warn)
    written.extend(purge_legacy_rules_everywhere())
    written.extend(install_skills())
    written.extend(mirror_skills_to_zed())
    written.append(merge_agent_mcp())
    written.append(merge_zed_mcp())
    if include_repos:
        for p in parse_projects():
            written.extend(inject_into_repo(p))
        written.extend(purge_legacy_rules_everywhere())
    return written, warnings


def file_id(path: Path) -> str:
    path = path.resolve()
    try:
        rel = path.relative_to(USER_MEMORY.resolve())
        return f"user/{rel.as_posix()}"
    except ValueError:
        pass
    try:
        rel = path.relative_to(AGENTS_RULES.resolve())
        return f"rules/{rel.as_posix()}"
    except ValueError:
        pass
    for p in parse_projects():
        if not p.path_obj.is_dir():
            continue
        root = (p.path_obj / ".agents" / "memory").resolve()
        try:
            rel = path.relative_to(root)
            return f"project/{p.slug}/{rel.as_posix()}"
        except ValueError:
            continue
    return path.as_posix()


def resolve_memory_path(rel: str) -> Path:
    rel = rel.replace("\\", "/").lstrip("/")
    if rel in ("user/USER.md", "USER.md", "user.md"):
        return USER_MD
    if rel in ("user/PROJECTS.md", "PROJECTS.md", "projects.md"):
        return PROJECTS_MD
    if rel in ("user/scan.json", "scan.json"):
        return SCAN_JSON
    if rel in ("user/ingest.json", "ingest.json"):
        return INGEST_JSON
    if rel.startswith("rules/"):
        return (AGENTS_RULES / rel[len("rules/") :]).resolve()
    if rel.startswith("user/"):
        return (USER_MEMORY / rel[len("user/") :]).resolve()
    if rel.startswith("project/"):
        rest = rel[len("project/") :]
        slug, _, inner = rest.partition("/")
        p = projects_by_slug().get(slug)
        if not p:
            raise FileNotFoundError(rel)
        if not inner:
            return p.detail_path
        return (p.memory_dir / inner).resolve()
    legacy = USER_MEMORY / rel
    if legacy.exists():
        return legacy
    if rel.startswith("projects/"):
        slug = Path(rel).stem
        p = projects_by_slug().get(slug)
        if p:
            return p.detail_path
    if "/" in rel or "." in rel:
        return (USER_MEMORY / rel).resolve()
    raise FileNotFoundError(rel)


def read_memory_file(file_id_or_path: str) -> str:
    """Read the raw content of any memory or rule file by id or path."""
    path = resolve_memory_path(file_id_or_path)
    if not path.is_file():
        raise FileNotFoundError(f"Memory file not found: {file_id_or_path}")
    return _read(path)


def write_memory_file(file_id_or_path: str, content: str, auto_sync: bool = True) -> str:
    """Write/overwrite any memory or rule file and automatically sync to all IDEs/CLIs."""
    path = resolve_memory_path(file_id_or_path)
    _write(path, content)
    clear_memory_cache()
    if auto_sync:
        try:
            sync_injection(include_repos=True)
        except Exception:
            pass
    return file_id(path)


def _markdown_under(root: Path) -> List[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def iter_user_memory_files() -> List[Path]:
    return _markdown_under(USER_MEMORY)


def iter_project_memory_files(slug: str = "") -> List[Path]:
    files: List[Path] = []
    for p in parse_projects():
        if slug and p.slug != slug:
            continue
        if p.path_obj.is_dir():
            folder = p.path_obj / ".agents" / "memory"
            files.extend(_markdown_under(folder))
            continue
        if p.detail_path.exists():
            files.append(p.detail_path)
    return files


def iter_memory_files(project: str = "") -> List[Path]:
    """Overarching retrieval: project store(s) first (higher priority), then user store."""
    seen: set[str] = set()
    out: List[Path] = []
    # Project-specific facts have higher priority than global user facts
    chunks = iter_project_memory_files(project.strip() if project else "")
    chunks.extend(iter_user_memory_files())
    for path in chunks:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


_MEMORY_FILE_CACHE: dict[str, Tuple[float, List[str]]] = {}


def clear_memory_cache() -> None:
    _MEMORY_FILE_CACHE.clear()


def _read_cached_lines(path: Path) -> List[str]:
    key = str(path.resolve())
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    cached = _MEMORY_FILE_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    text = _read(path)
    lines = text.splitlines()
    _MEMORY_FILE_CACHE[key] = (mtime, lines)
    return lines


def search_memory(query: str, project: str = "", limit: int = 20) -> List[dict]:
    q = query.lower().strip()
    files = iter_memory_files(project=project)
    hits: List[dict] = []
    for path in files:
        lines = _read_cached_lines(path)
        for i, line in enumerate(lines, 1):
            if not q or q not in line.lower():
                continue
            ident = file_id(path)
            hits.append(
                {
                    "id": f"{ident}:{i}",
                    "file": ident,
                    "line": i,
                    "text": line.strip(),
                }
            )
            if len(hits) >= limit:
                return hits
    return hits


KIND_FOLDERS = {
    "concept": "concepts",
    "concepts": "concepts",
    "entity": "entities",
    "entities": "entities",
    "workflow": "workflows",
    "workflows": "workflows",
}

KIND_HELP = (
    "add_memory needs kind=concept|entity|workflow|project|note|scratch|"
    "research|plans|tasks|roadmap|waves|decision|proposed|implemented|rejected|"
    "staging plus name=. collection= is a notes/ folder or a note class "
    "(feature, bug-fix, simplification, architecture, process, testing). "
    "plans/tasks/waves/roadmap/decisions are 001-topic.md. "
    "project= alone writes <repo>/.agents/memory/staging/captured.md (inbox, distill it)"
)


def slugify_name(name: str) -> str:
    name = (name or "").strip().replace("\\", "/").split("/")[-1]
    if name.lower().endswith(".md"):
        name = name[:-3]
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-._").lower()
    if not name:
        raise ValueError("empty name")
    return name


def next_seq(folder: Path) -> int:
    n = 0
    if folder.is_dir():
        for path in folder.glob("*.md"):
            match = SEQ_RE.match(path.stem)
            if match:
                n = max(n, int(match.group(1)))
    return n + 1


def sequential_path(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    slug = slugify_name(name)
    numbered = SEQ_RE.match(slug)
    if numbered and "-" in slug:
        return folder / f"{slug}.md"
    existing = sorted(folder.glob(f"*-{slug}.md")) if folder.is_dir() else []
    plain = folder / f"{slug}.md"
    if plain.exists():
        return plain
    if existing:
        return existing[0]
    return folder / f"{next_seq(folder):03d}-{slug}.md"
    name = (name or "").strip().replace("\\", "/").split("/")[-1]
    if name.lower().endswith(".md"):
        name = name[:-3]
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-._").lower()
    if not name:
        raise ValueError("empty name")
    return name


def _heading_from_stem(stem: str) -> str:
    return stem.replace("-", " ").replace("_", " ").strip().title()


def memory_file_for(
    kind: str = "",
    name: str = "",
    project: str = "",
    collection: str = "",
) -> Path:
    """Resolve where a fact belongs."""
    kind = (kind or "").strip().lower()
    name = (name or "").strip()
    project = (project or "").strip()
    collection = (collection or "").strip().lower()
    if kind in {"notes"}:
        kind = "note"

    if kind == "scratch" or collection == "scratch":
        return USER_MEMORY / "notes" / "scratch" / f"{slugify_name(name or 'captured')}.md"

    if kind in NOTE_LIFECYCLES:
        if not project:
            raise ValueError("proposed/implemented/rejected need project=")
        p = projects_by_slug().get(project)
        if not p:
            raise ValueError(f"unknown project '{project}' — register it first")
        ensure_project_file(p)
        cls = collection or "architecture"
        if cls not in NOTE_CLASSES:
            cls = slugify_name(cls)
        folder = p.memory_dir / "notes" / kind / cls
        return sequential_path(folder, name or "note")

    if kind in PROJECT_ARTIFACTS:
        slug = project or name
        p = projects_by_slug().get(slug)
        if not p:
            raise ValueError(f"unknown project '{slug}' — register it first")
        ensure_project_file(p)
        folder_name = PROJECT_ARTIFACTS[kind]
        dest_dir = p.memory_dir / folder_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        if folder_name == "staging":
            stem = slugify_name(name) if name and name != slug else "captured"
            if stem in {"from-chats", "chats"}:
                stem = "from-chats"
            return dest_dir / f"{stem}.md"
        stem = slugify_name(name) if name and name != slug else folder_name.rstrip("s")
        if folder_name in SEQUENTIAL_FOLDERS:
            return sequential_path(dest_dir, stem)
        return dest_dir / f"{stem}.md"

    if kind == "note":
        registered = projects_by_slug()
        stem = slugify_name(name) if name else "captured"
        if collection:
            coll = collection.strip()
            if coll in registered:
                return (
                    USER_MEMORY
                    / "notes"
                    / "projects"
                    / slugify_name(coll)
                    / f"{stem}.md"
                )
            return USER_MEMORY / "notes" / slugify_name(coll) / f"{stem}.md"
        if project:
            return (
                USER_MEMORY
                / "notes"
                / "projects"
                / slugify_name(project)
                / f"{stem}.md"
            )
        return USER_MEMORY / "notes" / "scratch" / f"{stem}.md"

    if kind in {"project", "projects"}:
        slug = slugify_name(name or project)
        p = projects_by_slug().get(slug)
        if p:
            ensure_project_file(p)
            return p.user_link_path
        return USER_MEMORY / "projects" / slug / "README.md"

    if kind in KIND_FOLDERS:
        stem = slugify_name(name or project)
        return USER_MEMORY / KIND_FOLDERS[kind] / f"{stem}.md"

    if project:
        p = projects_by_slug().get(project)
        if not p:
            raise ValueError(f"unknown project '{project}' — register it first")
        ensure_project_file(p)
        return p.memory_dir / "staging" / "captured.md"

    raise ValueError(KIND_HELP)


def _already_has_fact(text: str, fact: str) -> bool:
    needle = fact.strip().lstrip("-").strip().lower()
    if not needle:
        return True
    for line in text.splitlines():
        if line.strip().lstrip("-").strip().lower() == needle:
            return True
    return False


def _append_bullet(path: Path, fact: str) -> str:
    bullet = fact if fact.lstrip().startswith("- ") else f"- {fact}"
    if path.exists():
        text = _read(path)
        if _already_has_fact(text, fact):
            return file_id(path)
        body = text.rstrip()
        if body and not body.splitlines()[-1].lstrip().startswith("- "):
            body += "\n"
        _write(path, body + f"\n{bullet}\n")
        return file_id(path)
    if not path.exists():
        header = STAGING_HEADER if path.parent.name == "staging" else f"# {_heading_from_stem(path.stem)}\n"
        _write(path, f"{header}\n{bullet}\n")
        return file_id(path)


def _append_repo_captured(path: Path, fact: str) -> str:
    text = _read(path)
    if _already_has_fact(text, fact):
        return file_id(path)
    if "## Captured" not in text:
        text = text.rstrip() + "\n\n## Captured\n\n"
    lines = [ln for ln in text.splitlines() if ln.strip() != "- (none yet)"]
    if not any(ln.strip() == "## Captured" for ln in lines):
        lines.extend(["", "## Captured", ""])
    out: List[str] = []
    inserted = False
    for ln in lines:
        out.append(ln)
        if not inserted and ln.strip() == "## Captured":
            out.append(f"- {fact}")
            inserted = True
    if not inserted:
        out.append(f"- {fact}")
    _write(path, "\n".join(out))
    return file_id(path)


def add_memory(
    fact: str,
    kind: str = "",
    name: str = "",
    project: str = "",
    collection: str = "",
    auto_sync: bool = True,
) -> str:
    """File a durable fact. kind+name → taxonomy; project= alone → staging/captured.md (inbox)."""
    from .ingest_common import scrub
    fact = scrub(fact.strip())
    if not fact:
        raise ValueError("empty fact")
    path = memory_file_for(
        kind=kind, name=name, project=project, collection=collection
    )
    existed = path.exists()
    loc = _append_bullet(path, fact)
    clear_memory_cache()
    if auto_sync:
        try:
            sync_injection(include_repos=True)
        except Exception:
            pass
    k = (kind or "").strip().lower()
    if k in REVISE_IN_PLACE_KINDS and existed:
        return (
            f"{loc} — revise this file in place when facts change; "
            "do not only append bullets"
        )
    return loc


def get_project_memories(project: str) -> str:
    p = projects_by_slug().get(project)
    if not p:
        return f"Unknown project '{project}'. See PROJECTS.md."
    header = (
        f"slug: {p.slug}\npath: {p.path}\nrole: {p.role}\n"
        f"stack: {p.stack}\nstatus: {p.status}\n"
        f"file: {p.detail_path}\n\n"
    )
    files = _markdown_under(p.memory_dir) if p.path_obj.is_dir() else []
    if not files and p.detail_path.exists():
        files = [p.detail_path]
    if not files:
        return header + stub_project_md(p)
    parts = [header]
    for path in files:
        parts.append(f"## {file_id(path)}\n\n{_read(path).rstrip()}\n")
    return "\n".join(parts)


def delete_memory(memory_id: str, auto_sync: bool = True) -> str:
    if ":" not in memory_id:
        raise ValueError(
            "id must look like 'user/notes/programming/chat-stores.md:12' "
            "or 'project/slug/staging/captured.md:8'"
        )
    rel, _, line_s = memory_id.rpartition(":")
    line_no = int(line_s)
    path = resolve_memory_path(rel)
    if not path.exists():
        raise FileNotFoundError(rel)
    lines = _read(path).splitlines()
    if line_no < 1 or line_no > len(lines):
        raise IndexError(memory_id)
    removed = lines.pop(line_no - 1)
    _write(path, "\n".join(lines))
    clear_memory_cache()
    if auto_sync:
        try:
            sync_injection(include_repos=True)
        except Exception:
            pass
    return removed


def remove_staging_bullet(
    bullet: str,
    project: str = "",
    source_path: str = "",
) -> bool:
    clean_bullet = bullet.strip().lstrip("-").strip().lower()
    if not clean_bullet:
        return False
    candidate_paths: List[Path] = []
    if source_path:
        candidate_paths.append(resolve_memory_path(source_path))
    if project:
        p = projects_by_slug().get(project)
        if p:
            candidate_paths.append(p.memory_dir / "staging" / "captured.md")
            candidate_paths.append(p.memory_dir / "staging" / "from-chats.md")

    candidate_paths.extend(
        [
            USER_MEMORY / "staging" / "captured.md",
            USER_MEMORY / "staging" / "from-chats.md",
        ]
    )
    if (USER_MEMORY / "staging").is_dir():
        for f in sorted((USER_MEMORY / "staging").glob("*.md")):
            if f not in candidate_paths:
                candidate_paths.append(f)
        for f in sorted((USER_MEMORY / "staging").rglob("*.md")):
            if f not in candidate_paths:
                candidate_paths.append(f)

    for path in candidate_paths:
        if not path.is_file():
            continue
        lines = _read(path).splitlines()
        new_lines: List[str] = []
        file_modified = False
        for line in lines:
            normalized_line = line.strip().lstrip("-").strip().lower()
            if not file_modified and normalized_line == clean_bullet:
                file_modified = True
                continue
            new_lines.append(line)
        if file_modified:
            _write(path, "\n".join(new_lines))
            _MEMORY_FILE_CACHE.pop(str(path.resolve()), None)
            return True
    return False


def promote_bullet(
    bullet: str,
    kind: str,
    name: str,
    project: str = "",
    collection: str = "",
    source_path: str = "",
    auto_sync: bool = True,
) -> Tuple[str, bool]:
    """Promote a staging bullet into a typed memory file and remove it from staging.

    Returns (saved_location, removed_from_staging).
    """
    clean_bullet = bullet.strip().lstrip("-").strip()
    if not clean_bullet:
        raise ValueError("empty bullet")

    loc = add_memory(
        clean_bullet,
        kind=kind,
        name=name,
        project=project,
        collection=collection,
        auto_sync=False,
    )
    removed = remove_staging_bullet(clean_bullet, project=project, source_path=source_path)
    clear_memory_cache()
    if auto_sync:
        try:
            sync_injection(include_repos=True)
        except Exception:
            pass
    return loc, removed


_STAGING_BULLET_RE = re.compile(
    r"^\[(?P<title>[^\]]+?)(?:\s@\s(?P<origin>[^\]]+))?\]\s*(?P<body>.+)$"
)


def parse_staging_bullet(text: str) -> dict:
    text = text.strip()
    match = _STAGING_BULLET_RE.match(text)
    if match:
        return {
            "bullet": text,
            "title": match.group("title").strip(),
            "origin": (match.group("origin") or "").strip(),
            "text": match.group("body").strip(),
        }
    return {"bullet": text, "title": "", "origin": "", "text": text}


def _collect_staging_paths(project: str = "") -> List[Path]:
    candidate_paths: List[Path] = []
    if project:
        p = projects_by_slug().get(project)
        if p:
            candidate_paths.append(p.memory_dir / "staging" / "captured.md")
            candidate_paths.append(p.memory_dir / "staging" / "from-chats.md")
    else:
        candidate_paths.extend(
            [
                USER_MEMORY / "staging" / "captured.md",
                USER_MEMORY / "staging" / "from-chats.md",
            ]
        )
        if (USER_MEMORY / "staging").is_dir():
            for f in sorted((USER_MEMORY / "staging").rglob("*.md")):
                if f not in candidate_paths:
                    candidate_paths.append(f)
    return candidate_paths


def _staging_file_meta(path: Path) -> dict:
    fid = file_id(path)
    meta = {"file": fid, "ingest_id": "", "source": fid, "project": ""}
    try:
        rel_u = path.resolve().relative_to(USER_MEMORY.resolve()).as_posix()
    except ValueError:
        rel_u = ""
    if rel_u.startswith("staging/ingest/"):
        parts = rel_u.split("/")
        if len(parts) >= 3:
            meta["ingest_id"] = parts[2]
            meta["source"] = parts[2]
    for slug, proj in projects_by_slug().items():
        try:
            path.resolve().relative_to(proj.memory_dir.resolve())
            meta["project"] = slug
            break
        except ValueError:
            continue
    if meta["ingest_id"]:
        from .ingest_config import get_source, load_ingest

        src = get_source(meta["ingest_id"], load_ingest())
        if src:
            meta["source"] = str(src.get("label") or meta["ingest_id"])
    return meta


def get_staging_inbox(project: str = "", limit: int = 20) -> dict:
    """Retrieve un-distilled bullets grouped by staging source file.

    limit=0 returns all groups with no cap on shown bullets.
    """
    groups: List[dict] = []
    total = 0
    for path in _collect_staging_paths(project):
        if not path.is_file():
            continue
        meta = _staging_file_meta(path)
        seen_in_file: set[str] = set()
        bullets: List[dict] = []
        for line in _read(path).splitlines():
            stripped = line.strip()
            if not stripped.startswith(("- ", "* ")):
                continue
            text = stripped[2:].strip()
            if not text or text == "(none yet)":
                continue
            key = text.lower()
            if key in seen_in_file:
                continue
            seen_in_file.add(key)
            item = parse_staging_bullet(text)
            item["file"] = meta["file"]
            item["source_path"] = meta["file"]
            if meta["project"]:
                item["project"] = meta["project"]
            if meta["ingest_id"]:
                item["ingest_id"] = meta["ingest_id"]
                item["source"] = meta["source"]
            bullets.append(item)
        if bullets:
            groups.append(
                {
                    "source": meta["source"],
                    "ingest_id": meta["ingest_id"],
                    "project": meta["project"],
                    "file": meta["file"],
                    "count": len(bullets),
                    "bullets": bullets,
                }
            )
            total += len(bullets)

    shown = total
    if limit > 0 and total > limit:
        capped_groups: List[dict] = []
        remaining = limit
        for group in groups:
            if remaining <= 0:
                break
            take = group["bullets"][:remaining]
            if not take:
                continue
            capped_groups.append(
                {
                    **group,
                    "bullets": take,
                    "count": len(take),
                    "truncated": len(take) < len(group["bullets"]),
                }
            )
            remaining -= len(take)
        groups = capped_groups
        shown = limit

    return {"total": total, "shown": shown, "groups": groups}


def count_staging_bullets(project: str = "") -> int:
    return int(get_staging_inbox(project=project, limit=0)["total"])


def staging_status_summary() -> dict:
    from .ingest_config import load_ingest

    inbox = get_staging_inbox(limit=0)
    cfg = load_ingest()
    threshold = max(0, int(cfg.get("staging_nag_threshold") or 50))
    total = int(inbox["total"])
    nag = ""
    if threshold > 0 and total >= threshold:
        nag = (
            f"{total} staging bullets waiting — run memory-distill, "
            "MCP get_staging_inbox, or `python -m agents_memory distill`"
        )
    return {
        "bullet_count": total,
        "group_count": len(inbox["groups"]),
        "threshold": threshold,
        "nag": nag,
    }


def distill_batch(items: List[dict], auto_sync: bool = True) -> dict:
    """Batch process staging bullets into typed memory or discard them.

    Each item is a dict with:
      - bullet: str (required)
      - discard: bool (if True, removes from staging without adding to memory)
      - kind, name, project, collection: str (for add_memory)
    """
    promoted = 0
    discarded = 0
    errors: List[str] = []
    for item in items:
        bullet = str(item.get("bullet") or "").strip()
        if not bullet:
            continue
        proj = str(item.get("project") or "")
        src_path = str(item.get("source_path") or item.get("file") or "")
        if item.get("discard"):
            if remove_staging_bullet(bullet, project=proj, source_path=src_path):
                discarded += 1
            continue
        kind = str(item.get("kind") or "")
        name = str(item.get("name") or "")
        coll = str(item.get("collection") or "")
        try:
            loc, rem = promote_bullet(
                bullet=bullet,
                kind=kind,
                name=name,
                project=proj,
                collection=coll,
                source_path=src_path,
                auto_sync=False,
            )
            promoted += 1
        except Exception as e:
            errors.append(f"{bullet[:30]}...: {e}")

    clear_memory_cache()
    if auto_sync:
        try:
            sync_injection(include_repos=True)
        except Exception:
            pass

    remaining = count_staging_bullets()
    return {
        "promoted": promoted,
        "discarded": discarded,
        "remaining_staging_count": remaining,
        "errors": errors,
    }


_NOISE_LINE_PATTERNS = (
    r"^(?:ok|okay|danke|super|perfekt|thanks|thx|hi|hallo|yes|no|ja|nein|cool|top|alles klar)\.?$",
    r"\?$",
    r"^(?:can you|kannst du|kann man|wie kann|what is|how do|check line|zeile|error:|syntaxerror|traceback)",
)


def auto_distill(limit: int = 50, discard_noise: bool = True, auto_sync: bool = True) -> dict:
    """Automatically classify and distill staging inbox bullets into memory or discard noise."""
    inbox = get_staging_inbox(limit=limit)
    items_to_distill = []
    noise_re = [re.compile(pat, re.IGNORECASE) for pat in _NOISE_LINE_PATTERNS]

    for group in inbox.get("groups", []):
        for item in group.get("bullets", []):
            raw_text = item.get("text") or item.get("bullet") or ""
            bullet_text = item.get("bullet") or raw_text
            src_path = item.get("source_path") or item.get("file") or ""
            proj = item.get("project") or ""

            # Check noise
            is_noise = False
            for r in noise_re:
                if r.search(raw_text.strip()):
                    is_noise = True
                    break

            if len(raw_text.strip()) < 8:
                is_noise = True

            if is_noise:
                if discard_noise:
                    items_to_distill.append({
                        "bullet": bullet_text,
                        "discard": True,
                        "project": proj,
                        "source_path": src_path,
                    })
                continue

            # Check for stack/preferences
            lower = raw_text.lower()
            if any(k in lower for k in ("always ", "never ", "prefer ", "immer ", "nie ", "bevorzuge ", "stack:", "stack defaults")):
                items_to_distill.append({
                    "bullet": bullet_text,
                    "kind": "note",
                    "name": "preferences",
                    "collection": "preferences",
                    "project": proj,
                    "source_path": src_path,
                })
            elif proj:
                items_to_distill.append({
                    "bullet": bullet_text,
                    "kind": "note",
                    "name": "facts",
                    "project": proj,
                    "source_path": src_path,
                })

    if not items_to_distill:
        return {
            "promoted": 0,
            "discarded": 0,
            "remaining_staging_count": count_staging_bullets(),
            "errors": [],
            "message": "No obvious rules or noise auto-classified; manual distillation required for remaining items.",
        }

    res = distill_batch(items_to_distill, auto_sync=auto_sync)
    return res
