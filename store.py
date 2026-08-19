"""Local markdown memory store. No cloud.

Two layers, one retrieval:

- User: ``~/.agents/memory`` — identity, project map, concepts/entities/workflows,
  project **links**, personal notes, chat index.
- Project: ``<repo>/.agents/memory`` — staging (inbox), research, sequential
  plans/tasks/waves/roadmap, decisions (ADRs), lifecycle notes.

Search unions both. Always-on injection stays short (USER.md + PROJECTS.md).
Chat bodies stay in product folders; only titles/paths are ingested.
`add_memory` requires kind+name (user taxonomy) or project= (in-tree notes).
AGENTS.md is the real instruction file. CLAUDE.md is bound to it (git symlink in
this repo; installed homes symlink, else hardlink, else copy). Windows without
symlink privilege uses a hardlink so the two names cannot drift.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "memory"
LEGACY_MEMORY = ROOT / "memory"
AGENTS_HOME = Path.home() / ".agents"
USER_MEMORY = AGENTS_HOME / "memory"
MEMORY = USER_MEMORY
ORPHANS = USER_MEMORY / "orphans"
USER_MD = USER_MEMORY / "USER.md"
PROJECTS_MD = USER_MEMORY / "PROJECTS.md"
SCAN_JSON = USER_MEMORY / "scan.json"
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
POINTER_MARK = "<!-- agent-memory-sync-pointer -->"
STAGING_HEADER = (
    "# Staging\n\n"
    "Not memory. Distill each bullet into a typed file "
    "(`plans/001-…`, `tasks/001-…`, `waves/001-…`, `roadmap/001-…`, "
    "`decisions/001-…`, `notes/proposed|implemented|rejected/<class>/`), "
    "then delete it here.\n"
)

MARKER = "<!-- agent-memory-sync -->"
PATHS_BEGIN = "<!-- agent-memory-paths -->"
PATHS_END = "<!-- /agent-memory-paths -->"
DEFAULT_RULE_NAME = "user-rules.mdc"
LEGACY_RULE_STEMS = ("felix-always",)
SKILL_TEMPLATE = ROOT / "skills" / "memory-sync" / "SKILL.md"
SKIP_SKILL_NAMES = {
    "antigravity_guide",
    "agy-customizations",
    "permissioned-github",
}

INJECTION_GEMINI = Path.home() / ".gemini" / "config" / "AGENTS.md"
INJECTION_AGENTS_MD = ROOT / ".agents" / "AGENTS.md"

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
    path.write_text(content, encoding="utf-8")


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
        "cursor_rule_name": DEFAULT_RULE_NAME,
        "ignore_dir_names": sorted(SKIP_DIR_DEFAULT),
        "ignore_slugs": [],
        "expand_children": [],
    }


LAYOUT_TEXT = """# Agent memory layout

User store `~/.agents/memory` plus `<repo>/.agents/memory`. Search unions all markdown.

One home per fact. Path encodes where it belongs. No dump files (`facts.md`, `MEMORY.md`).

## User (`~/.agents/memory`)

| Folder | Holds |
|--------|--------|
| `concepts/` `entities/` `workflows/` | Cross-cutting ideas, named things, procedures |
| `projects/<slug>/` | **Link** to a real tree (`path` in README). Not a second copy of the repo. |
| `notes/<collection>/` | Personal notes. Guide collections below — add a folder when a fact does not fit. |

Note collection **guides** (not a closed set): `projects/` `interests/` `education/` `finance/` `family/` `preferences/` `programming/` `work/` `certifications/` `scratch/`.
`notes/projects/<slug>/` is personal notes *about* a project.

## Project (`<repo>/.agents/memory`) — Cordis layering

Cordis: a service claims one `ctx.key`; nested fibers have their own lifecycle; registrations are reversible; serial work has an order.

| Folder | Role |
|--------|------|
| `staging/` | **Inbox only.** `captured.md` / `from-chats.md`. Distill, then empty. |
| `research/` | Input. Not a decision. |
| `plans/` `tasks/` `waves/` `roadmap/` | Ordered work. Files are `001-topic.md`, `002-…`. |
| `notes/proposed/<class>/` | In flight (fiber PENDING). |
| `notes/implemented/<class>/` | Shipped rationale — **revise in place** when code/paths change (facts track reality). |
| `notes/rejected/<class>/` | Declined; **frozen** after reject. |
| `decisions/` | ADRs: `001-title.md`. **Revise present tense** when the contract changes; new number when superseding. |

Note classes (guide): `feature` `bug-fix` `simplification` `architecture` `process` `testing`.

**Mutability:** staging/scratch = inbox (append, then distill/delete). Sequential work = new `001-` file per tranche; edit the *current* plan/tasks in place; archive superseded plans to `plans/PLAN-NNN.md`. Research = topical files you revise. Implemented notes and ADRs = edit the file when shipped reality changes — do not only append forever. Rejected = frozen. User `concepts/`/`entities/`/`workflows/` = grow by append or edit the one home.

Archive a previous plan as `plans/PLAN-NNN.md` (GAIA) instead of overwriting the current one.

## Instruction files

Canonical user always-on: `~/.agents/AGENTS.md` (USER.md + PROJECTS.md).
`CLAUDE.md` next to it is **bound** to `AGENTS.md` (symlink → hardlink → copy). DeepSeek git-symlinks `CLAUDE.md` → `AGENTS.md` in git; this repo does too.

**Windows:** without symlink privilege, a fresh `git clone` may leave `CLAUDE.md` as a 9-byte file containing the text `AGENTS.md` — run `python sync.py` to repair (hardlink or symlink if Developer Mode is on). Without Developer Mode, hardlink is used (same inode, no drift). exFAT/network drives may force a copy — sync warns.

**macOS/Linux:** git symlinks work out of the box; `sync.py` still binds installed homes the same way.

Installed: `~/.agents/`, Gemini config, Zed (`%APPDATA%/Zed` on Windows, `~/.config/zed` elsewhere), `~/.claude/` — all bind to canonical unless a repo-root file is foreign (no `<!-- agent-memory-sync -->`). Foreign `~/.claude/CLAUDE.md` from another tool is replaced on sync; back it up first if you still need it.

Always-on injection: `USER.md` + `PROJECTS.md` only.
Chat bodies stay in product folders. `chats-index.md` is the catalog.
"""


MEMORY_FOLDERS = (
    "concepts",
    "entities",
    "workflows",
    "projects",
) + tuple(f"notes/{name}" for name in NOTE_COLLECTIONS)


def _copy_if_missing(src: Path, dst: Path) -> bool:
    if not src.exists() or dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def migrate_legacy_store() -> List[str]:
    """Copy clone `memory/` live files into ~/.agents/memory once.

    Prefer the clone if the user store is still an empty example.
    """
    moved: List[str] = []
    if not LEGACY_MEMORY.is_dir():
        return moved

    def take(src: Path, dst: Path, replace: bool) -> None:
        if not src.exists():
            return
        if dst.exists() and not replace:
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        moved.append(str(dst))

    take(LEGACY_MEMORY / "USER.md", USER_MD, replace=user_profile_looks_blank())
    take(
        LEGACY_MEMORY / "PROJECTS.md",
        PROJECTS_MD,
        replace=not parse_projects(),
    )
    take(LEGACY_MEMORY / "scan.json", SCAN_JSON, replace=False)
    legacy_scan = LEGACY_MEMORY / "scan.json"
    if legacy_scan.exists():
        dest_ok = False
        if SCAN_JSON.exists():
            try:
                dest_ok = any(
                    Path(r).expanduser().is_dir()
                    for r in (json.loads(_read(SCAN_JSON)).get("roots") or [])
                )
            except json.JSONDecodeError:
                dest_ok = False
        take(legacy_scan, SCAN_JSON, replace=not dest_ok)
    take(LEGACY_MEMORY / "chats-index.md", CHATS_INDEX, replace=not CHATS_INDEX.exists())

    by_slug = {p.slug: p for p in parse_projects()}
    legacy_projects = LEGACY_MEMORY / "projects"
    if legacy_projects.is_dir():
        for src in sorted(legacy_projects.glob("*.md")):
            slug = src.stem
            p = by_slug.get(slug)
            dest = p.detail_path if p else ORPHANS / src.name
            take(src, dest, replace=False)
            orphan = ORPHANS / src.name
            if p and p.path_obj.is_dir() and orphan.exists() and dest != orphan:
                take(orphan, dest, replace=False)
                if dest.exists():
                    orphan.unlink()
                    moved.append(f"removed orphan {orphan}")
    return moved


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


def ensure_project_memory_tree(mem: Path) -> None:
    for folder in PROJECT_MEMORY_TOP:
        (mem / folder).mkdir(parents=True, exist_ok=True)
    for lifecycle in NOTE_LIFECYCLES:
        for cls in NOTE_CLASSES:
            (mem / "notes" / lifecycle / cls).mkdir(parents=True, exist_ok=True)


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
        mem = p.memory_dir
        if not mem.is_dir():
            continue
        ensure_project_memory_tree(mem)
        _merge_relocate(mem / "facts.md", mem / "staging" / "captured.md")
        _merge_relocate(mem / "notes" / "captured.md", mem / "staging" / "captured.md")
        _merge_relocate(mem / "from-chats.md", mem / "staging" / "from-chats.md")
        _merge_relocate(mem / "research" / "from-chats.md", mem / "staging" / "from-chats.md")
        if not p.detail_path.exists():
            _write(p.detail_path, stub_project_md(p))
        if not p.user_link_path.exists():
            _write(p.user_link_path, stub_project_md(p))


def ensure_memory_layout() -> None:
    """Create ~/.agents/memory, migrate clone leftovers, then fill missing examples."""
    USER_MEMORY.mkdir(parents=True, exist_ok=True)
    ORPHANS.mkdir(parents=True, exist_ok=True)
    for rel in MEMORY_FOLDERS:
        (USER_MEMORY / rel).mkdir(parents=True, exist_ok=True)
    migrate_legacy_store()
    migrate_taxonomy()
    _write(LAYOUT_MD, LAYOUT_TEXT)
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
    if not cfg.get("cursor_rule_name"):
        cfg["cursor_rule_name"] = DEFAULT_RULE_NAME
    if not cfg.get("roots"):
        cfg["roots"] = _default_roots()
    if "ignore_dir_names" not in cfg:
        cfg["ignore_dir_names"] = sorted(SKIP_DIR_DEFAULT)
    if "ignore_slugs" not in cfg:
        cfg["ignore_slugs"] = []
    if "expand_children" not in cfg:
        cfg["expand_children"] = []
    return cfg


def cursor_rule_name() -> str:
    name = str(load_scan().get("cursor_rule_name") or DEFAULT_RULE_NAME).strip()
    if not name.endswith(".mdc"):
        name += ".mdc"
    return name


def injection_cursor_user() -> Path:
    return Path.home() / ".cursor" / "rules" / cursor_rule_name()


def profile_title() -> str:
    for line in _read(USER_MD).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "agent memory"


def scan_roots() -> List[str]:
    return [str(Path(r).expanduser()) for r in (load_scan().get("roots") or [])]


def mcp_entry() -> dict:
    return {
        "command": sys.executable,
        "args": [str(ROOT / "mcp_server.py")],
    }


def mcp_snippet() -> str:
    return json.dumps({"agent-memory": mcp_entry()}, indent=2)


def cursor_mcp_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def user_profile_looks_blank() -> bool:
    return bool(re.search(r"^- Name:\s*$", _read(USER_MD), re.M))


def merge_cursor_mcp() -> str:
    """Insert/update the agent-memory server in ~/.cursor/mcp.json. Other servers untouched."""
    path = cursor_mcp_path()
    if path.exists():
        raw = _read(path)
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            return f"FAIL {path}: invalid JSON ({e}). Merge skipped. Add:\n{mcp_snippet()}"
        if not isinstance(data, dict):
            return f"FAIL {path}: root is not an object. Merge skipped."
    else:
        data = {}
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return f"FAIL {path}: mcpServers is not an object. Merge skipped."
    servers["agent-memory"] = mcp_entry()
    _write(path, json.dumps(data, indent=2, ensure_ascii=False))
    return f"OK {path}"


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
    """Union of Cursor + Antigravity MCP configs. Later files fill missing fields only."""
    home = Path.home()
    sources = [
        home / ".cursor" / "mcp.json",
        home / ".gemini" / "config" / "mcp_config.json",
        home / ".gemini" / "config" / "mcp.json",
        home / ".gemini" / "antigravity-ide" / "mcp_config.json",
    ]
    merged: Dict[str, dict] = {}
    for path in sources:
        for name, spec in _mcp_servers_from_file(path).items():
            if name not in merged:
                merged[name] = dict(spec)
                continue
            for key, val in spec.items():
                if key not in merged[name] or merged[name][key] in (None, "", {}, []):
                    merged[name][key] = val
    merged["agent-memory"] = mcp_entry()
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
    """Upsert Cursor/AG MCP servers into Zed settings.json context_servers."""
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
    """Copy user skills from Cursor/AG/Claude into ~/.agents/skills (Zed global)."""
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
        "Canonical map. Change via `inventory.py`, MCP `register_project`, or skill `memory-sync`.",
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
    )
    return any((path / m).exists() for m in markers)


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

    for root in cfg.get("roots") or []:
        root_path = Path(root).expanduser()
        if not root_path.is_dir():
            continue
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
    return found


def inventory_report() -> dict:
    tracked = parse_projects()
    by_slug = {p.slug: p for p in tracked}
    by_path = {str(p.path_obj.resolve()).lower(): p for p in tracked if p.path_obj.exists()}
    disk = discover_disk()
    unknown = []
    known = []
    for slug, path in disk:
        key = str(path).lower()
        if slug in by_slug or key in by_path:
            known.append({"slug": slug, "path": str(path), "status": "tracked"})
        else:
            unknown.append({"slug": slug, "path": str(path)})
    missing = []
    for p in tracked:
        if not p.path_obj.exists():
            missing.append({"slug": p.slug, "path": p.path})
    cfg = load_scan()
    return {
        "tracked": [p.__dict__ for p in tracked],
        "unknown": unknown,
        "missing": missing,
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
        f"{p.role}\n\n"
        f"**Path:** `{p.path}`\n\n"
        f"In-tree: `{p.path}/.agents/memory/` "
        f"(staging, research, plans, tasks, waves, roadmap, decisions, "
        f"notes/proposed|implemented|rejected).\n"
        f"User notes: `notes/projects/{p.slug}/`.\n"
    )


def ensure_project_file(p: Project, overwrite_empty: bool = False) -> None:
    dest = p.detail_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    ensure_project_memory_tree(p.memory_dir)
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


def always_on_body() -> str:
    user = _read(USER_MD).strip()
    projects = _read(PROJECTS_MD).strip()
    return f"{user}\n\n---\n\n{projects}\n"


def cursor_rule_text() -> str:
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
    details = _read(p.detail_path).strip() if p.detail_path.exists() else stub_project_md(p).strip()
    return (
        f"{MARKER}\n\n"
        f"# Project: {p.slug}\n\n"
        f"User memory: `{USER_MEMORY}`.\n"
        "Project memory: `.agents/memory/` "
        "(staging, research, plans, tasks, waves, roadmap, decisions, "
        "notes/proposed|implemented|rejected).\n"
        "Instruction files: `.agents/AGENTS.md` (this slice). "
        "`CLAUDE.md` is bound to it. User always-on: `~/.agents/AGENTS.md`.\n"
        "Zed personal: `%APPDATA%/Zed/AGENTS.md` (Windows) or `~/.config/zed/AGENTS.md`.\n"
        "Retrieval is overarching (MCP `search_memory`). This file is the local slice.\n\n"
        f"{details}\n"
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


def repo_pointer_rule_text() -> str:
    roots = scan_roots()
    roots_txt = ", ".join(f"`{r}`" for r in roots) if roots else "`scan.json` roots"
    return (
        "---\n"
        "description: Pointer to local agent memory. Always apply.\n"
        "alwaysApply: true\n"
        "---\n\n"
        f"{MARKER}\n\n"
        f"User memory: `{USER_MEMORY}` (identity, project map, chat index).\n"
        "This repo: `.agents/memory/` (staging / research / plans / tasks / waves / roadmap / decisions).\n"
        "Search both via MCP `agent-memory` / `search_memory`.\n\n"
        f"- New folder under {roots_txt} -> skill `memory-sync` or "
        "`register_project`. Do not leave it unlisted.\n"
    )


def purge_legacy_rules(rules_dir: Path) -> List[str]:
    """Delete old rule filenames so alwaysApply does not double-load."""
    if not rules_dir.is_dir():
        return []
    current = cursor_rule_name().lower()
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

    add(Path.home() / ".cursor" / "rules")
    add(ROOT / ".cursor" / "rules")
    for p in parse_projects():
        add(p.path_obj / ".cursor" / "rules")
    for _slug, path in discover_disk():
        add(path / ".cursor" / "rules")
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
                "edit AGENTS.md only; re-run sync.py after changes or use Developer Mode / native FS)"
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

    The engine repo root always binds: CLAUDE.md is the DeepSeek alias of AGENTS.md.
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
    if not repo.is_dir():
        return written
    ensure_project_file(p)
    written.append(str(p.detail_path))
    written.append(str(p.user_link_path))
    rule = repo / ".cursor" / "rules" / cursor_rule_name()
    _write(rule, repo_pointer_rule_text())
    written.append(str(rule))
    written.extend(purge_legacy_rules(repo / ".cursor" / "rules"))
    written.extend(write_instruction_pair(repo / ".agents", project_agents_text(p)))
    return written


def _machine_paths_block() -> str:
    inv = ROOT / "inventory.py"
    syn = ROOT / "sync.py"
    ingest = ROOT / "ingest_chats.py"
    roots = ", ".join(f"`{r}`" for r in scan_roots()) or "`scan.json` roots"
    return (
        f"Install (engine): `{ROOT}`  \n"
        f"User memory: `{USER_MEMORY}`  \n"
        f"Project memory: `<repo>/.agents/memory`  \n"
        f"Cursor rule: `{cursor_rule_name()}`  \n"
        f"Scan roots: {roots}\n\n"
        "Scripts (absolute, any workspace):\n\n"
        "```powershell\n"
        f"python {inv}\n"
        f"python {inv} --json\n"
        f"python {syn}\n"
        f"python {ingest}\n"
        "```\n\n"
        "Register:\n\n"
        "```powershell\n"
        f'python {inv} --register SLUG "C:\\path\\to\\repo" "role here" "stack here"\n'
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
    if not text:
        return []
    written: List[str] = []
    targets = [
        Path.home() / ".cursor" / "skills" / "memory-sync" / "SKILL.md",
        Path.home() / ".agents" / "skills" / "memory-sync" / "SKILL.md",
        Path.home() / ".gemini" / "config" / "skills" / "memory-sync" / "SKILL.md",
    ]
    for path in targets:
        _write(path, text)
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
    written.extend(repair_instruction_stub(ROOT))
    cursor_user = injection_cursor_user()
    _write(cursor_user, cursor_rule_text())
    written.append(str(cursor_user))
    written.extend(purge_legacy_rules_everywhere())
    written.extend(install_skills())
    written.extend(mirror_skills_to_zed())
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
    raise FileNotFoundError(rel)


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
    """Overarching retrieval: user store plus every (or one) project store."""
    seen: set[str] = set()
    out: List[Path] = []
    chunks = iter_user_memory_files()
    chunks.extend(iter_project_memory_files(project.strip() if project else ""))
    if project:
        # still include user layer so cross-cutting facts remain findable
        pass
    for path in chunks:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def search_memory(query: str, project: str = "", limit: int = 20) -> List[dict]:
    q = query.lower().strip()
    files = iter_memory_files(project=project)
    hits: List[dict] = []
    for path in files:
        for i, line in enumerate(_read(path).splitlines(), 1):
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
) -> str:
    """File a durable fact. kind+name → taxonomy; project= alone → staging/captured.md (inbox)."""
    fact = fact.strip()
    if not fact:
        raise ValueError("empty fact")
    path = memory_file_for(
        kind=kind, name=name, project=project, collection=collection
    )
    existed = path.exists()
    loc = _append_bullet(path, fact)
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


def delete_memory(memory_id: str) -> str:
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
    return removed
