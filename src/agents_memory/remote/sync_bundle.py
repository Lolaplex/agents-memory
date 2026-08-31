"""Collect and apply full mirror sync bundles (user store + rules + project mirrors)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..store import (
    AGENTS_RULES,
    USER_MEMORY,
    _read,
    _write,
    parse_projects,
    projects_by_slug,
    sync_injection,
)
from .merge import merge_file_trees, merge_markdown_files

MIRROR_PREFIX = "mirror/projects/"
RULES_PREFIX = "rules/"
SYNC_CONFLICTS = USER_MEMORY / "staging" / "sync-conflicts.md"

_SKIP_SUFFIXES = {".sqlite", ".db", ".lock", ".tmp", ".pyc"}
_SKIP_NAMES = {"remote_config.json"}
_SKIP_PARTS = {".index", "export"}


def _should_skip_file(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    if any(part.startswith(".") for part in rel.parts):
        return True
    if any(part in _SKIP_PARTS for part in rel.parts):
        return True
    if path.suffix in _SKIP_SUFFIXES or path.name in _SKIP_NAMES:
        return True
    return False


def _collect_tree(root: Path, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if _should_skip_file(p, root):
            continue
        rel = p.relative_to(root).as_posix()
        key = f"{prefix}{rel}" if prefix else rel
        try:
            out[key] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return out


def collect_sync_bundle(
    include_projects: bool = True,
    memory_root: Optional[Path] = None,
) -> dict[str, str]:
    """Build full sync payload: user store + rules + slug-keyed project mirrors."""
    root = memory_root or USER_MEMORY
    files = _collect_tree(root)
    # Server-side mirror copies live under user store but use mirror/ prefix in bundle
    files = {k: v for k, v in files.items() if not k.startswith("mirror/")}

    if AGENTS_RULES.is_dir():
        for p in sorted(AGENTS_RULES.glob("*.mdc")):
            if p.is_file():
                files[f"{RULES_PREFIX}{p.name}"] = _read(p)

    if include_projects:
        for proj in parse_projects():
            mem = proj.memory_dir
            if not mem.is_dir():
                continue
            prefix = f"{MIRROR_PREFIX}{proj.slug}/"
            files.update(_collect_tree(mem, prefix=prefix))

    return files


def _parse_mirror_path(rel: str) -> tuple[str, str] | None:
    if not rel.startswith(MIRROR_PREFIX):
        return None
    rest = rel[len(MIRROR_PREFIX) :]
    slug, _, inner = rest.partition("/")
    if not slug:
        return None
    return slug, inner


def _record_sync_conflicts(conflicts: list[dict[str, str]]) -> None:
    if not conflicts:
        return
    SYNC_CONFLICTS.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if SYNC_CONFLICTS.exists():
        lines = _read(SYNC_CONFLICTS).splitlines()
    if not lines or not lines[0].startswith("#"):
        lines = ["# Sync conflicts (resolved: incoming wins; logged for review)", ""] + lines
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for c in conflicts:
        slug = c.get("slug") or c.get("file") or "?"
        lines.append(f"- [{ts}] **{slug}**: incoming applied over base")
        if c.get("base"):
            lines.append(f"  - was: `{c['base'].strip()}`")
        if c.get("incoming"):
            lines.append(f"  - now: `{c['incoming'].strip()}`")
    _write(SYNC_CONFLICTS, "\n".join(lines).strip() + "\n")


def _merge_user_files(
    user_files: dict[str, str],
    target_root: Path,
) -> dict[str, Any]:
    from .merge import merge_table_markdown_with_conflicts

    report: dict[str, Any] = {
        "added": [],
        "merged": [],
        "unchanged": [],
        "conflicts": [],
        "total_incoming": len(user_files),
    }
    target_root.mkdir(parents=True, exist_ok=True)

    for rel_path, content in user_files.items():
        dest = target_root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        if not dest.exists():
            dest.write_text(content, encoding="utf-8")
            report["added"].append(rel_path)
            continue

        if dest.name.lower() == "projects.md":
            base_content = dest.read_text(encoding="utf-8", errors="replace")
            merged, conflicts = merge_table_markdown_with_conflicts(base_content, content)
            if merged.strip() != base_content.strip():
                dest.write_text(merged, encoding="utf-8")
                report["merged"].append(rel_path)
                if conflicts:
                    report["conflicts"].extend(conflicts)
            else:
                report["unchanged"].append(rel_path)
            continue

        merged, modified = merge_markdown_files(dest, content)
        if modified:
            dest.write_text(merged, encoding="utf-8")
            report["merged"].append(rel_path)
        else:
            report["unchanged"].append(rel_path)

    if report["conflicts"]:
        _record_sync_conflicts(report["conflicts"])

    return report


def _apply_rules(rules_files: dict[str, str]) -> dict[str, list[str]]:
    report = {"added": [], "merged": []}
    AGENTS_RULES.mkdir(parents=True, exist_ok=True)
    for rel, content in rules_files.items():
        name = rel[len(RULES_PREFIX) :]
        if not name.endswith(".mdc"):
            continue
        dest = AGENTS_RULES / name
        if not dest.exists():
            dest.write_text(content, encoding="utf-8")
            report["added"].append(rel)
        else:
            merged, modified = merge_markdown_files(dest, content)
            if modified:
                dest.write_text(merged, encoding="utf-8")
                report["merged"].append(rel)
    return report


def _apply_mirrors_to_repos(mirror_files: dict[str, str]) -> dict[str, list[str]]:
    """Write mirror/projects/<slug>/… into local <repo>/.agents/memory/ when registered."""
    report: dict[str, list[str]] = {"applied": [], "skipped": []}
    by_slug: dict[str, dict[str, str]] = {}
    for rel, content in mirror_files.items():
        parsed = _parse_mirror_path(rel)
        if not parsed:
            continue
        slug, inner = parsed
        by_slug.setdefault(slug, {})[inner] = content

    for slug, inner_files in by_slug.items():
        proj = projects_by_slug().get(slug)
        if not proj or not proj.path_obj.is_dir():
            for inner in inner_files:
                report["skipped"].append(f"{slug}/{inner}")
            continue
        mem = proj.memory_dir
        mem.mkdir(parents=True, exist_ok=True)
        inner_report = merge_file_trees(mem, inner_files)
        for key in ("added", "merged"):
            for item in inner_report.get(key, []):
                report["applied"].append(f"mirror/projects/{slug}/{item}")

    return report


def _store_mirrors_on_server(mirror_files: dict[str, str], target_root: Path) -> dict[str, Any]:
    """Persist mirror/projects/<slug>/… under user store on the server."""
    server_mirror: dict[str, str] = {}
    for rel, content in mirror_files.items():
        if rel.startswith(MIRROR_PREFIX):
            server_mirror[rel] = content
    if not server_mirror:
        return {"added": [], "merged": [], "unchanged": []}
    return merge_file_trees(target_root, server_mirror)


def apply_sync_bundle(
    incoming_files: dict[str, str],
    target_root: Optional[Path] = None,
    apply_to_repos: bool = True,
) -> dict[str, Any]:
    """Split bundle and merge into user store, rules, repo trees, and server mirrors."""
    root = target_root or USER_MEMORY
    user_files: dict[str, str] = {}
    rules_files: dict[str, str] = {}
    mirror_files: dict[str, str] = {}

    for rel, content in incoming_files.items():
        norm = rel.replace("\\", "/").lstrip("/")
        if norm.startswith(MIRROR_PREFIX):
            mirror_files[norm] = content
        elif norm.startswith(RULES_PREFIX):
            rules_files[norm] = content
        else:
            user_files[norm] = content

    user_report = _merge_user_files(user_files, root)
    rules_report = _apply_rules(rules_files)
    mirror_store_report = _store_mirrors_on_server(mirror_files, root)
    repo_report = _apply_mirrors_to_repos(mirror_files) if apply_to_repos else {"applied": [], "skipped": []}

    try:
        sync_injection(include_repos=True)
    except Exception:
        pass

    return {
        "user": user_report,
        "rules": rules_report,
        "mirror_store": mirror_store_report,
        "repos": repo_report,
    }


def get_all_memory_files(memory_dir: Optional[Path] = None) -> dict[str, str]:
    """Backward-compatible alias: full mirror sync bundle."""
    return collect_sync_bundle(include_projects=True)
