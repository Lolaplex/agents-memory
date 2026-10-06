"""Collect and apply full mirror sync bundles (user store + rules + project mirrors)."""
from __future__ import annotations

import hashlib
import json
import shutil
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
from .merge import merge_file_trees, merge_markdown_files, strip_bullet_lines
from .tombstones import (
    blocked_bullet_norms,
    blocked_row_pks,
    delete_prefix_tree,
    file_blocked,
    load_tombstones,
    mtime_iso,
    norm_rel,
    record_file,
    record_prefix,
    record_row,
)

MIRROR_PREFIX = "mirror/projects/"
RULES_PREFIX = "rules/"
SYNC_CONFLICTS = USER_MEMORY / "staging" / "sync-conflicts.md"
# Not sync-*.md: those logs are hidden from get_staging_inbox. This file is a review queue.
EPOCH_QUESTIONS_REL = "staging/epoch-questions.md"
_EPOCH_QUESTIONS_HEADER = (
    "# Epoch questions\n\n"
    "Not memory. The remote vault epoch changed, so these local edits were not pushed.\n"
    "They show up in `get_staging_inbox`. Re-add with add/write on the new epoch if you still want the file.\n\n"
)

_SKIP_SUFFIXES = {".sqlite", ".db", ".lock", ".tmp", ".pyc"}
_SKIP_NAMES = {"remote_config.json", "board_attach.json", "host_paths.json"}
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


def _collect_tree(
    root: Path,
    prefix: str = "",
    stamps: Optional[dict[str, str]] = None,
) -> dict[str, str]:
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
            continue
        if stamps is not None:
            stamps[key] = mtime_iso(p)
    return out


def collect_sync_bundle(
    include_projects: bool = True,
    memory_root: Optional[Path] = None,
    stamps: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Build full sync payload: user store + rules + slug-keyed project mirrors."""
    root = memory_root or USER_MEMORY
    files = _collect_tree(root, stamps=stamps)
    # Server-side mirror copies live under user store but use mirror/ prefix in bundle.
    # Stamps for those keys are re-added below when the mirror store fills gaps.
    mirror_stamps = {
        k: v for k, v in (stamps or {}).items() if k.startswith("mirror/")
    }
    if stamps is not None:
        for key in list(stamps):
            if key.startswith("mirror/"):
                stamps.pop(key, None)
    files = {k: v for k, v in files.items() if not k.startswith("mirror/")}

    rules_dir = _rules_dir()
    if rules_dir.is_dir():
        for p in sorted(rules_dir.glob("*.mdc")):
            if p.is_file():
                key = f"{RULES_PREFIX}{p.name}"
                files[key] = _read(p)
                if stamps is not None:
                    stamps[key] = mtime_iso(p)

    if include_projects:
        projects_text = ""
        projects_md = root / "PROJECTS.md"
        if projects_md.is_file():
            projects_text = projects_md.read_text(encoding="utf-8", errors="replace")
        for proj in parse_projects(projects_text):
            mem = proj.memory_dir
            if not mem.is_dir():
                continue
            prefix = f"{MIRROR_PREFIX}{proj.slug}/"
            files.update(_collect_tree(mem, prefix=prefix, stamps=stamps))

        # VPS has no repo paths; keep stored slug mirrors as fallback.
        # Live repo trees win via setdefault (already in `files`).
        mirror_store = root / "mirror" / "projects"
        if mirror_store.is_dir():
            mirror_only_stamps: dict[str, str] = {}
            stored = _collect_tree(
                mirror_store, prefix=MIRROR_PREFIX, stamps=mirror_only_stamps
            )
            for key, content in stored.items():
                if key not in files:
                    files[key] = content
                    if stamps is not None:
                        stamps[key] = mirror_only_stamps.get(key) or mirror_stamps.get(key, "")

    return files


def _rules_dir() -> Path:
    return AGENTS_RULES


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


def _explicit_file_maps(writes: Optional[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    """Explicit re-adds only. Mtimes are not in this map (they must not beat a prefix)."""
    writes = writes or {}
    files = writes.get("explicit_files")
    if not isinstance(files, dict):
        files = writes.get("files") if isinstance(writes.get("files"), dict) else {}
    prefixes = writes.get("prefixes") if isinstance(writes.get("prefixes"), dict) else {}
    return files, prefixes


def _apply_tombstones_to_text(
    rel_path: str,
    content: str,
    tombstones: Optional[dict[str, Any]],
    writes: Optional[dict[str, Any]],
) -> str:
    if not tombstones:
        return content
    name = Path(rel_path).name.lower()
    if name == "projects.md":
        from .merge import _without_pks

        content = _without_pks(content, blocked_row_pks(tombstones, writes))
    norms = blocked_bullet_norms(tombstones, rel_path, writes)
    if norms and name.endswith(".md"):
        content = strip_bullet_lines(content, norms)
    return content


def _merge_user_files(
    user_files: dict[str, str],
    target_root: Path,
    tombstones: Optional[dict[str, Any]] = None,
    writes: Optional[dict[str, Any]] = None,
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
    drop_rows = blocked_row_pks(tombstones, writes) if tombstones else set()

    for rel_path, content in user_files.items():
        content = _apply_tombstones_to_text(rel_path, content, tombstones, writes)
        dest = target_root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        if not dest.exists():
            dest.write_text(content, encoding="utf-8")
            report["added"].append(rel_path)
            continue

        if dest.name.lower() == "projects.md":
            base_content = dest.read_text(encoding="utf-8", errors="replace")
            merged, conflicts = merge_table_markdown_with_conflicts(
                base_content, content, drop_pks=drop_rows
            )
            merged = _apply_tombstones_to_text(rel_path, merged, tombstones, writes)
            if merged.strip() != base_content.strip():
                dest.write_text(merged, encoding="utf-8")
                report["merged"].append(rel_path)
                if conflicts:
                    report["conflicts"].extend(conflicts)
            else:
                report["unchanged"].append(rel_path)
            continue

        merged, modified = merge_markdown_files(dest, content)
        merged = _apply_tombstones_to_text(rel_path, merged, tombstones, writes)
        if merged.strip() != dest.read_text(encoding="utf-8", errors="replace").strip():
            modified = True
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
    rules_dir = _rules_dir()
    rules_dir.mkdir(parents=True, exist_ok=True)
    for rel, content in rules_files.items():
        name = rel[len(RULES_PREFIX) :]
        if not name.endswith(".mdc"):
            continue
        dest = rules_dir / name
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


def _bundle_key_skipped(rel: str) -> bool:
    parts = Path(rel).parts
    if any(part.startswith(".") or part in _SKIP_PARTS for part in parts):
        return True
    path = Path(rel)
    if path.suffix in _SKIP_SUFFIXES or path.name in _SKIP_NAMES:
        return True
    return False


def is_agent_rule_key(rel: str) -> bool:
    """``rules/<name>.mdc`` is a host rule file (``~/.agents/rules``).

    Anything else under ``rules/`` (e.g. ``rules/HARD.md``) is user-store content.
    """
    if not rel.startswith(RULES_PREFIX):
        return False
    name = rel[len(RULES_PREFIX):]
    return name.endswith(".mdc") and "/" not in name


def _split_bundle(
    incoming_files: dict[str, str],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    user_files: dict[str, str] = {}
    rules_files: dict[str, str] = {}
    mirror_files: dict[str, str] = {}
    for rel, content in incoming_files.items():
        norm = norm_rel(rel)
        if norm.startswith(MIRROR_PREFIX):
            mirror_files[norm] = content
        elif is_agent_rule_key(norm):
            rules_files[norm] = content
        else:
            user_files[norm] = content
    return user_files, rules_files, mirror_files


def apply_sync_bundle(
    incoming_files: dict[str, str],
    target_root: Optional[Path] = None,
    apply_to_repos: bool = True,
    tombstones: Optional[dict[str, Any]] = None,
    writes: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Split bundle and merge into user store, rules, repo trees, and server mirrors."""
    root = target_root or USER_MEMORY
    user_files, rules_files, mirror_files = _split_bundle(incoming_files)

    user_report = _merge_user_files(user_files, root, tombstones=tombstones, writes=writes)
    rules_report = _apply_rules(rules_files)
    mirror_store_report = (
        _store_mirrors_on_server(mirror_files, root)
        if not apply_to_repos
        else {"added": [], "merged": [], "unchanged": []}
    )
    repo_report = _apply_mirrors_to_repos(mirror_files) if apply_to_repos else {"applied": [], "skipped": []}

    removed: list[str] = []
    if tombstones:
        removed = enforce_tombstones(root, tombstones, writes, apply_to_repos=apply_to_repos)

    try:
        sync_injection(include_repos=True)
    except Exception:
        pass

    return {
        "user": user_report,
        "rules": rules_report,
        "mirror_store": mirror_store_report,
        "repos": repo_report,
        "removed": removed,
    }


def enforce_tombstones(
    root: Path,
    tombstones: dict[str, Any],
    writes: Optional[dict[str, Any]] = None,
    *,
    apply_to_repos: bool = False,
) -> list[str]:
    """Strip tombstoned rows/bullets and delete blocked files already on disk."""
    writes = writes or {}
    explicit_files, explicit_prefixes = _explicit_file_maps(writes)
    removed: list[str] = []

    projects = root / "PROJECTS.md"
    if projects.is_file():
        text = projects.read_text(encoding="utf-8", errors="replace")
        stripped = _apply_tombstones_to_text("PROJECTS.md", text, tombstones, writes)
        if stripped != text:
            projects.write_text(stripped, encoding="utf-8")

    for path in list(root.rglob("*")):
        if not path.is_file() or _should_skip_file(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        if rel.endswith(".md"):
            norms = blocked_bullet_norms(tombstones, rel, writes)
            if norms:
                text = path.read_text(encoding="utf-8", errors="replace")
                stripped = strip_bullet_lines(text, norms)
                if stripped != text:
                    path.write_text(stripped, encoding="utf-8")
        if file_blocked(
            tombstones,
            rel,
            explicit_files=explicit_files,
            explicit_prefixes=explicit_prefixes,
        ):
            try:
                path.unlink()
                removed.append(rel)
            except OSError:
                pass

    if apply_to_repos:
        removed.extend(_enforce_repo_tombstones(root, tombstones, writes))
    return removed


def _enforce_repo_tombstones(
    root: Path, tombstones: dict[str, Any], writes: dict[str, Any]
) -> list[str]:
    removed: list[str] = []
    explicit_files, explicit_prefixes = _explicit_file_maps(writes)
    projects_text = ""
    projects_md = root / "PROJECTS.md"
    if projects_md.is_file():
        projects_text = projects_md.read_text(encoding="utf-8", errors="replace")
    for proj in parse_projects(projects_text):
        if not proj.path_obj.is_dir():
            continue
        mem = proj.memory_dir
        if not mem.is_dir():
            continue
        for path in list(mem.rglob("*")):
            if not path.is_file() or _should_skip_file(path, mem):
                continue
            rel = f"{MIRROR_PREFIX}{proj.slug}/{path.relative_to(mem).as_posix()}"
            if file_blocked(
                tombstones,
                rel,
                explicit_files=explicit_files,
                explicit_prefixes=explicit_prefixes,
            ):
                try:
                    path.unlink()
                    removed.append(rel)
                except OSError:
                    pass
    return removed


def _backup_store(root: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = root.parent / f"{root.name}.bak-{ts}"
    n = 0
    while dest.exists():
        n += 1
        dest = root.parent / f"{root.name}.bak-{ts}-{n}"
    if root.is_dir():
        shutil.copytree(
            root,
            dest,
            symlinks=True,
            ignore=shutil.ignore_patterns(".sync.lock", "*.lock"),
        )
    else:
        dest.mkdir(parents=True, exist_ok=True)
    return dest


def _write_verbatim(dest: Path, content: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")


def _replace_tree(root: Path, desired: dict[str, str]) -> dict[str, list[str]]:
    """Make synced files under ``root`` match ``desired`` exactly. Skip dotfiles and host files."""
    existing = _collect_tree(root)
    removed: list[str] = []
    written: list[str] = []
    for rel in existing:
        if rel not in desired:
            path = root / rel
            if path.is_file():
                path.unlink()
                removed.append(rel)
    for rel, content in desired.items():
        _write_verbatim(root / rel, content)
        written.append(rel)
    return {"removed": removed, "written": written}


def _replace_rules(rules_files: dict[str, str]) -> dict[str, list[str]]:
    rules_dir = _rules_dir()
    desired: dict[str, str] = {}
    for rel, content in rules_files.items():
        name = rel[len(RULES_PREFIX):]
        if name.endswith(".mdc") and "/" not in name and ".." not in name:
            desired[name] = content
    rules_dir.mkdir(parents=True, exist_ok=True)
    removed: list[str] = []
    for path in list(rules_dir.glob("*.mdc")):
        if path.name not in desired and path.is_file():
            path.unlink()
            removed.append(path.name)
    written: list[str] = []
    for name, content in desired.items():
        _write_verbatim(rules_dir / name, content)
        written.append(name)
    return {"removed": removed, "written": written}


def _replace_registered_repos(
    root: Path, mirror_files: dict[str, str], backup: Path
) -> dict[str, list[str]]:
    """Replace each registered repo's ``.agents/memory`` with that slug's snapshot mirror.

    Slugs that are no longer in PROJECTS.md are left on disk. They are not
    registered, so the next push does not upload them. Deleting a checkout
    from here would destroy a working tree that this tool does not own.
    """
    by_slug: dict[str, dict[str, str]] = {}
    for rel, content in mirror_files.items():
        parsed = _parse_mirror_path(rel)
        if not parsed:
            continue
        slug, inner = parsed
        if inner:
            by_slug.setdefault(slug, {})[inner] = content
        else:
            by_slug.setdefault(slug, {})

    report: dict[str, list[str]] = {"applied": [], "removed": [], "skipped": []}
    projects_md = root / "PROJECTS.md"
    text = projects_md.read_text(encoding="utf-8", errors="replace") if projects_md.is_file() else ""
    snap_root = backup / "repo-memory-snapshot"
    for proj in parse_projects(text):
        if not proj.path_obj.is_dir():
            report["skipped"].append(proj.slug)
            continue
        mem = proj.memory_dir
        inner = by_slug.get(proj.slug, {})
        if mem.is_dir():
            dest = snap_root / proj.slug
            try:
                shutil.copytree(mem, dest, symlinks=True, dirs_exist_ok=True)
            except OSError:
                pass
        mem.mkdir(parents=True, exist_ok=True)
        tree = _replace_tree(mem, inner)
        for rel in tree["removed"]:
            report["removed"].append(f"{MIRROR_PREFIX}{proj.slug}/{rel}")
        for rel in tree["written"]:
            report["applied"].append(f"{MIRROR_PREFIX}{proj.slug}/{rel}")
    return report


def apply_snapshot_replace(
    incoming_files: dict[str, str],
    target_root: Optional[Path] = None,
    apply_to_repos: bool = True,
) -> dict[str, Any]:
    """Make the local synced store match ``incoming_files`` exactly.

    Backs up the store first (``<store>.bak-<UTC>``). Files the bundle never
    syncs (``remote_config.json``, ``host_paths.json``, ``board_attach.json``,
    ``.index/``, other dotfiles) stay in place. Snapshot bytes are written
    verbatim — no table union.
    """
    root = target_root or USER_MEMORY
    root.mkdir(parents=True, exist_ok=True)
    backup = _backup_store(root)
    user_files, rules_files, mirror_files = _split_bundle(incoming_files)
    user_files = {k: v for k, v in user_files.items() if not _bundle_key_skipped(k)}
    mirror_files = {k: v for k, v in mirror_files.items() if not _bundle_key_skipped(k)}
    desired_user = {**user_files, **mirror_files}
    user_report = _replace_tree(root, desired_user)
    rules_report = _replace_rules(rules_files)
    repo_report = (
        _replace_registered_repos(root, mirror_files, backup)
        if apply_to_repos
        else {"applied": [], "removed": [], "skipped": []}
    )
    try:
        sync_injection(include_repos=True)
    except Exception:
        pass
    return {
        "replaced": True,
        "backup": str(backup),
        "user": user_report,
        "rules": rules_report,
        "repos": repo_report,
        "removed": user_report["removed"],
    }


BASELINE_FILE = ".sync-baseline.json"


def load_baseline(root: Path) -> Optional[dict[str, Any]]:
    path = Path(root) / BASELINE_FILE
    if not path.is_file():
        return None
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _file_sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _table_slug_lines(text: str) -> dict[str, str]:
    """Map a markdown table's slug cell to its raw line. Skips the header."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        slug = cells[0].strip().lower()
        if not slug or slug == "slug" or set(slug) <= {"-", ":"}:
            continue
        out[slug] = line
    return out


def save_baseline(root: Path, files: dict[str, str]) -> None:
    import json

    text = files.get("PROJECTS.md", "")
    rows = [p.slug.lower() for p in parse_projects(text)]
    payload = {
        "files": sorted(files),
        "rows": {"PROJECTS.md": rows},
        "hashes": {path: _file_sha(content) for path, content in files.items()},
    }
    path = Path(root) / BASELINE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def capture_pending(root: Path, files: dict[str, str]) -> dict[str, Any]:
    """Edits since the last sync baseline.

    No baseline means nothing is pending. A first sync after an epoch bump
    must not replay a whole stale vault on top of the snapshot.
    """
    base = load_baseline(root)
    if not base:
        return {"files": {}, "project_rows": []}
    known = {str(item) for item in (base.get("files") or [])}
    hashes = base.get("hashes") if isinstance(base.get("hashes"), dict) else {}
    raw_rows = []
    if isinstance(base.get("rows"), dict):
        raw_rows = (base.get("rows") or {}).get("PROJECTS.md") or []
    base_rows = {str(slug).strip().lower() for slug in raw_rows} if isinstance(raw_rows, list) else set()
    changed: dict[str, str] = {}
    for path, content in files.items():
        digest = _file_sha(content)
        if path not in known or (hashes and str(hashes.get(path) or "") != digest):
            changed[path] = content
    new_rows: list[str] = []
    for slug, line in _table_slug_lines(files.get("PROJECTS.md") or "").items():
        if slug not in base_rows:
            new_rows.append(line)
    return {"files": changed, "project_rows": new_rows}


def _epoch_question_bullet(path: str, content: str, server_epoch: int) -> str:
    return (
        f"- [{path} @ epoch {server_epoch}] Remote epoch changed. "
        "Local edit was not pushed. Re-add with add/write on the new epoch if you still want it. "
        f"Local content (JSON string): {json.dumps(content, ensure_ascii=False)}"
    )


def _union_question_lines(*texts: str) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- ") or stripped in seen:
                continue
            seen.add(stripped)
            lines.append(stripped)
    return lines


def stage_epoch_questions(root: Path, pending: dict[str, Any], server_epoch: int) -> list[str]:
    """Park baseline-diverged files for review. Do not write them back onto the store.

    ``sync-conflicts.md`` is a merge log and is excluded from ``get_staging_inbox``.
    Epoch questions use the same bullet log, in ``staging/epoch-questions.md``, so
    agents see them in the inbox. Deletions are not pending and are not staged.
    """
    files = pending.get("files") if isinstance(pending.get("files"), dict) else {}
    rows = pending.get("project_rows") if isinstance(pending.get("project_rows"), list) else []
    preserved = files.get(EPOCH_QUESTIONS_REL)
    preserved_text = preserved if isinstance(preserved, str) else ""
    server_epoch = max(0, int(server_epoch))
    staged: list[str] = []
    bullets: list[str] = []

    def add(path: str, content: str) -> None:
        clean = norm_rel(path)
        if not clean or clean == EPOCH_QUESTIONS_REL or ".." in clean.split("/"):
            return
        bullets.append(_epoch_question_bullet(clean, content, server_epoch))
        if clean not in staged:
            staged.append(clean)

    for path in sorted(files):
        content = files[path]
        if not isinstance(content, str) or path == EPOCH_QUESTIONS_REL:
            continue
        add(str(path), content)
    if "PROJECTS.md" not in files:
        for line in rows:
            if isinstance(line, str) and line.strip():
                add("PROJECTS.md", line.strip())

    dest = Path(root) / EPOCH_QUESTIONS_REL
    on_disk = dest.read_text(encoding="utf-8") if dest.is_file() else ""
    kept = _union_question_lines(on_disk, preserved_text, *bullets)
    if not kept:
        return []
    body = _EPOCH_QUESTIONS_HEADER + "\n".join(kept) + "\n"
    if body != on_disk:
        _write(dest, body)
    return staged


def infer_from_baseline(root: Path, current: dict[str, str]) -> None:
    """Tombstone files and PROJECTS rows this device had and then removed."""
    base = load_baseline(root)
    if not base:
        return
    known = load_tombstones(root)
    previous_files = set(base.get("files") or [])
    for rel in sorted(previous_files - set(current)):
        if rel not in known["files"]:
            record_file(root, rel)
            known = load_tombstones(root)
    previous_rows = {
        str(s).lower() for s in (base.get("rows") or {}).get("PROJECTS.md") or []
    }
    current_rows = {p.slug.lower() for p in parse_projects(current.get("PROJECTS.md", ""))}
    for slug in sorted(previous_rows - current_rows):
        record_row(root, "PROJECTS.md", slug)
        record_prefix(root, f"mirror/projects/{slug}/")
        record_prefix(root, f"projects/{slug}/")
        delete_prefix_tree(root, f"mirror/projects/{slug}/")
        delete_prefix_tree(root, f"projects/{slug}/")
    from .tombstones import record_prefix_write, record_row_write

    for slug in sorted(current_rows - previous_rows):
        record_row_write(root, slug)
        record_prefix_write(root, f"mirror/projects/{slug}/")
        record_prefix_write(root, f"projects/{slug}/")


def infer_remote_project_absences(
    root: Path, local_files: dict[str, str], remote_files: dict[str, str]
) -> None:
    """First explicit ``remote push`` with no baseline: publish project deletions.

    Only project rows and ``mirror/projects/`` / ``projects/`` paths. A missing
    USER.md is not treated as a deletion. An empty local PROJECTS.md does not
    wipe a non-empty remote map (that is a fresh device, not a cleanup).
    """
    if "PROJECTS.md" not in local_files:
        return
    local_rows = {p.slug.lower() for p in parse_projects(local_files.get("PROJECTS.md", ""))}
    remote_rows = {p.slug.lower() for p in parse_projects(remote_files.get("PROJECTS.md", ""))}
    # Empty local map against a populated remote is a fresh device, not a cleanup.
    if not local_rows and remote_rows:
        return
    for slug in sorted(remote_rows - local_rows):
        record_row(root, "PROJECTS.md", slug)
        delete_prefix_tree(root, f"mirror/projects/{slug}/")
        delete_prefix_tree(root, f"projects/{slug}/")
    known = load_tombstones(root)
    for rel in remote_files:
        if rel in local_files:
            continue
        if rel.startswith("mirror/projects/") or rel.startswith("projects/"):
            if rel not in known["files"]:
                record_file(root, rel)
                known = load_tombstones(root)


def get_all_memory_files(memory_dir: Optional[Path] = None) -> dict[str, str]:
    """Backward-compatible alias: full mirror sync bundle."""
    return collect_sync_bundle(include_projects=True, memory_root=memory_dir)
