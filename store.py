"""Local markdown memory store. No cloud."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
MEMORY = ROOT / "memory"
PROJECTS_DIR = MEMORY / "projects"
USER_MD = MEMORY / "USER.md"
PROJECTS_MD = MEMORY / "PROJECTS.md"
SCAN_JSON = MEMORY / "scan.json"
FACTS_MD = MEMORY / "facts.md"

MARKER = "<!-- agent-memory-sync -->"
PATHS_BEGIN = "<!-- agent-memory-paths -->"
PATHS_END = "<!-- /agent-memory-paths -->"
DEFAULT_RULE_NAME = "user-rules.mdc"
LEGACY_RULE_NAMES = ("felix-always.mdc",)
SKILL_TEMPLATE = ROOT / "skills" / "memory-sync" / "SKILL.md"

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
    def detail_path(self) -> Path:
        return PROJECTS_DIR / f"{self.slug}.md"


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


def ensure_memory_layout() -> None:
    """Create memory/ and copy *.example.* into live files if they are missing."""
    MEMORY.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    gitkeep = PROJECTS_DIR / ".gitkeep"
    if not gitkeep.exists():
        _write(gitkeep, "")
    pairs = (
        (MEMORY / "USER.example.md", USER_MD),
        (MEMORY / "PROJECTS.example.md", PROJECTS_MD),
        (MEMORY / "facts.example.md", FACTS_MD),
        (MEMORY / "scan.example.json", SCAN_JSON),
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
        f"**Path:** `{p.path}`  \n"
        f"**Stack:** {p.stack}\n\n"
        f"## Captured\n\n"
        f"- (none yet)\n"
    )


def ensure_project_file(p: Project, overwrite_empty: bool = False) -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    if p.detail_path.exists() and not overwrite_empty:
        return
    _write(p.detail_path, stub_project_md(p))


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
        f"Global profile is synced into `.cursor/rules/{cursor_rule_name()}` and "
        f"`~/.gemini/config/AGENTS.md`.\n\n"
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
        f"Read `{USER_MD}` and `{PROJECTS_MD}` at session start before coding.\n\n"
        "- MCP: `agent-memory` (local markdown).\n"
        f"- New folder under {roots_txt} -> skill `memory-sync` or "
        "`register_project`. Do not leave it unlisted.\n"
    )


def purge_legacy_rules(rules_dir: Path) -> List[str]:
    """Delete old rule filenames so alwaysApply does not double-load."""
    if not rules_dir.is_dir():
        return []
    current = cursor_rule_name().lower()
    removed: List[str] = []
    for name in LEGACY_RULE_NAMES:
        if name.lower() == current:
            continue
        path = rules_dir / name
        if path.is_file():
            path.unlink()
            removed.append(str(path))
    return removed


def inject_into_repo(p: Project) -> List[str]:
    written: List[str] = []
    repo = p.path_obj
    if not repo.is_dir():
        return written
    rule = repo / ".cursor" / "rules" / cursor_rule_name()
    _write(rule, repo_pointer_rule_text())
    written.append(str(rule))
    written.extend(purge_legacy_rules(repo / ".cursor" / "rules"))
    agents = repo / ".agents" / "AGENTS.md"
    if _should_overwrite_agents(agents):
        _write(agents, project_agents_text(p))
        written.append(str(agents))
    return written


def _machine_paths_block() -> str:
    inv = ROOT / "inventory.py"
    syn = ROOT / "sync.py"
    roots = ", ".join(f"`{r}`" for r in scan_roots()) or "`scan.json` roots"
    return (
        f"Install: `{ROOT}`  \n"
        f"Live store: `{MEMORY}`  \n"
        f"Cursor rule: `{cursor_rule_name()}`  \n"
        f"Scan roots: {roots}\n\n"
        "Scripts (absolute, any workspace):\n\n"
        "```powershell\n"
        f"python {inv}\n"
        f"python {inv} --json\n"
        f"python {syn}\n"
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
    targets = [Path.home() / ".cursor" / "skills" / "memory-sync" / "SKILL.md"]
    agents_root = Path.home() / ".agents" / "skills"
    if agents_root.is_dir() or (agents_root / "memory-sync" / "SKILL.md").exists():
        targets.append(agents_root / "memory-sync" / "SKILL.md")
    for path in targets:
        _write(path, text)
        written.append(str(path))
    return written


def sync_injection(include_repos: bool = True) -> List[str]:
    ensure_memory_layout()
    written: List[str] = []
    _write(INJECTION_GEMINI, gemini_agents_text())
    written.append(str(INJECTION_GEMINI))
    cursor_user = injection_cursor_user()
    _write(cursor_user, cursor_rule_text())
    written.append(str(cursor_user))
    written.extend(purge_legacy_rules(Path.home() / ".cursor" / "rules"))
    _write(INJECTION_AGENTS_MD, gemini_agents_text())
    written.append(str(INJECTION_AGENTS_MD))
    written.extend(install_skills())
    if include_repos:
        for p in parse_projects():
            written.extend(inject_into_repo(p))
    return written


def iter_memory_files() -> List[Path]:
    files = [USER_MD, PROJECTS_MD, FACTS_MD]
    if PROJECTS_DIR.is_dir():
        files.extend(sorted(PROJECTS_DIR.glob("*.md")))
    return [f for f in files if f.exists()]


def search_memory(query: str, project: str = "", limit: int = 20) -> List[dict]:
    q = query.lower().strip()
    files = iter_memory_files()
    if project:
        slug = project.strip()
        files = [f for f in files if f.stem == slug or f.name.lower() == f"{slug}.md"]
        p = projects_by_slug().get(slug)
        if p:
            files.append(p.detail_path)
        files = [f for f in files if f.exists()]
    hits: List[dict] = []
    for path in files:
        for i, line in enumerate(_read(path).splitlines(), 1):
            if q and q not in line.lower():
                continue
            if not q:
                continue
            rel = path.relative_to(MEMORY).as_posix()
            hits.append(
                {
                    "id": f"{rel}:{i}",
                    "file": rel,
                    "line": i,
                    "text": line.strip(),
                }
            )
            if len(hits) >= limit:
                return hits
    return hits


def add_memory(fact: str, project: str = "") -> str:
    fact = fact.strip()
    if not fact:
        raise ValueError("empty fact")
    if project:
        p = projects_by_slug().get(project)
        if not p:
            raise ValueError(f"unknown project '{project}' — register it first")
        ensure_project_file(p)
        text = _read(p.detail_path)
        if "## Captured" not in text:
            text = text.rstrip() + "\n\n## Captured\n\n"
        lines = text.splitlines()
        # drop placeholder
        lines = [ln for ln in lines if ln.strip() != "- (none yet)"]
        if not any(ln.strip() == "## Captured" for ln in lines):
            lines.append("")
            lines.append("## Captured")
            lines.append("")
        # insert after heading
        out: List[str] = []
        inserted = False
        for ln in lines:
            out.append(ln)
            if not inserted and ln.strip() == "## Captured":
                out.append(f"- {fact}")
                inserted = True
        if not inserted:
            out.append(f"- {fact}")
        _write(p.detail_path, "\n".join(out))
        return f"{p.detail_path.relative_to(MEMORY).as_posix()}"
    if not FACTS_MD.exists():
        _write(FACTS_MD, "# Captured facts\n\n")
    text = _read(FACTS_MD).rstrip() + f"\n- {fact}\n"
    _write(FACTS_MD, text)
    return "facts.md"


def get_project_memories(project: str) -> str:
    p = projects_by_slug().get(project)
    if not p:
        return f"Unknown project '{project}'. See PROJECTS.md."
    body = _read(p.detail_path) if p.detail_path.exists() else stub_project_md(p)
    header = (
        f"slug: {p.slug}\npath: {p.path}\nrole: {p.role}\n"
        f"stack: {p.stack}\nstatus: {p.status}\n\n"
    )
    return header + body


def delete_memory(memory_id: str) -> str:
    if ":" not in memory_id:
        raise ValueError("id must look like 'facts.md:12' or 'projects/omnus.md:8'")
    rel, _, line_s = memory_id.rpartition(":")
    line_no = int(line_s)
    path = MEMORY / rel
    if not path.exists():
        raise FileNotFoundError(rel)
    lines = _read(path).splitlines()
    if line_no < 1 or line_no > len(lines):
        raise IndexError(memory_id)
    removed = lines.pop(line_no - 1)
    _write(path, "\n".join(lines))
    return removed
