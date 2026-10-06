"""Deletion tombstones for multi-device merge.

Markdown stays the source of truth. Tombstones are a small JSON side file
(``.tombstones.json``) so generic JSON/table union cannot resurrect a key.
They travel in the merge/snapshot API, not inside the file bundle: dotfiles
are skipped by the collector, and a union-merged JSON document cannot drop keys.

Schema (version 1):

```json
{
  "version": 1,
  "files": {"notes/old.md": "2026-10-05T12:00:00Z"},
  "prefixes": {"mirror/projects/old/": "2026-10-05T12:00:00Z"},
  "rows": {"PROJECTS.md": {"old": "2026-10-05T12:00:00Z"}},
  "bullets": {"concepts/x.md": {"normalized text": "2026-10-05T12:00:00Z"}}
}
```

Timestamps are UTC ``YYYY-MM-DDTHH:MM:SSZ`` and compare lexicographically.
A strictly newer write wins (re-add). Entries older than 90 days are dropped.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

TOMBSTONE_VERSION = 1
EXPIRY_DAYS = 90
TOMBSTONE_FILE = ".tombstones.json"
WRITES_FILE = ".sync-writes.json"
DELETED_FILE = ".deleted.json"
_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FMT)


def mtime_iso(path: Path) -> str:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return now_iso()
    return datetime.fromtimestamp(stamp, timezone.utc).strftime(_TS_FMT)


def norm_rel(rel: str) -> str:
    return str(rel).replace("\\", "/").strip().lstrip("/")


def empty_tombstones() -> dict[str, Any]:
    return {"version": TOMBSTONE_VERSION, "files": {}, "prefixes": {}, "rows": {}, "bullets": {}}


def empty_writes() -> dict[str, Any]:
    return {"files": {}, "prefixes": {}, "rows": {}, "bullets": {}}


def newer(write_iso: Optional[str], tomb_iso: Optional[str]) -> bool:
    """True when ``write_iso`` is a strictly later UTC stamp than the tombstone."""
    if not write_iso or not tomb_iso:
        return False
    return str(write_iso) > str(tomb_iso)


def normalize_tombstones(data: Any) -> dict[str, Any]:
    """Accept the versioned document or the legacy flat ``{path: iso}`` map."""
    out = empty_tombstones()
    if not isinstance(data, dict):
        return out
    nested = "files" in data or "rows" in data or "prefixes" in data or "bullets" in data
    if nested or data.get("version") == TOMBSTONE_VERSION:
        files = data.get("files") if isinstance(data.get("files"), dict) else {}
        prefixes = data.get("prefixes") if isinstance(data.get("prefixes"), dict) else {}
        out["files"] = {norm_rel(k): str(v) for k, v in files.items() if k and isinstance(v, str)}
        out["prefixes"] = {
            _norm_prefix(k): str(v) for k, v in prefixes.items() if k and isinstance(v, str)
        }
        out["rows"] = _norm_nested(data.get("rows"))
        out["bullets"] = _norm_nested(data.get("bullets"))
        return out
    # Legacy server file: {relative path: iso}
    for key, val in data.items():
        if key in {"version", "files", "prefixes", "rows", "bullets"}:
            continue
        if isinstance(val, str) and key:
            out["files"][norm_rel(str(key))] = val
    return out


def normalize_writes(data: Any) -> dict[str, Any]:
    out = empty_writes()
    if not isinstance(data, dict):
        return out
    # ``files`` here are explicit re-adds. Push also sends mtimes separately
    # under the same key when talking to the server; callers split those.
    files = data.get("explicit_files")
    if not isinstance(files, dict):
        files = data.get("files") if isinstance(data.get("files"), dict) else {}
    prefixes = data.get("prefixes") if isinstance(data.get("prefixes"), dict) else {}
    out["files"] = {norm_rel(k): str(v) for k, v in files.items() if k and isinstance(v, str)}
    out["prefixes"] = {
        _norm_prefix(k): str(v) for k, v in prefixes.items() if k and isinstance(v, str)
    }
    out["rows"] = _norm_nested(data.get("rows"))
    out["bullets"] = _norm_nested(data.get("bullets"))
    return out


def _norm_prefix(prefix: str) -> str:
    clean = norm_rel(prefix)
    if clean and not clean.endswith("/"):
        clean += "/"
    return clean


def _norm_nested(raw: Any) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not isinstance(raw, dict):
        return out
    for file_key, rows in raw.items():
        if not isinstance(rows, dict):
            continue
        cleaned: dict[str, str] = {}
        for pk, stamp in rows.items():
            if isinstance(stamp, str) and str(pk).strip():
                cleaned[str(pk).strip().lower()] = stamp
        if cleaned:
            out[str(file_key)] = cleaned
    return out


def _merge_stamp_map(base: dict[str, str], incoming: dict[str, str]) -> dict[str, str]:
    merged = dict(base)
    for key, stamp in incoming.items():
        prev = merged.get(key)
        if prev is None or stamp > prev:
            merged[key] = stamp
    return merged


def _merge_nested(
    base: dict[str, dict[str, str]], incoming: dict[str, dict[str, str]]
) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {k: dict(v) for k, v in base.items()}
    for file_key, rows in incoming.items():
        merged[file_key] = _merge_stamp_map(merged.get(file_key, {}), rows)
    return merged


def merge_tombstones(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Keep the later deletion stamp per key."""
    left = normalize_tombstones(base)
    right = normalize_tombstones(incoming)
    return {
        "version": TOMBSTONE_VERSION,
        "files": _merge_stamp_map(left["files"], right["files"]),
        "prefixes": _merge_stamp_map(left["prefixes"], right["prefixes"]),
        "rows": _merge_nested(left["rows"], right["rows"]),
        "bullets": _merge_nested(left["bullets"], right["bullets"]),
    }


def revive(tombstones: dict[str, Any], writes: dict[str, Any], mtimes: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Drop tombstones beaten by a strictly newer write.

    ``writes`` holds explicit re-adds (file, prefix, row, bullet).
    ``mtimes`` can revive a single-file tombstone but cannot punch through a
    prefix tombstone — a touched project tree must not undo a project removal.
    """
    ts = normalize_tombstones(tombstones)
    explicit = normalize_writes(writes)
    mtimes = mtimes or {}
    for rel, stamp in list(ts["files"].items()):
        if newer(explicit["files"].get(rel), stamp) or newer(mtimes.get(rel), stamp):
            ts["files"].pop(rel, None)
    for prefix, stamp in list(ts["prefixes"].items()):
        if newer(explicit["prefixes"].get(prefix), stamp):
            ts["prefixes"].pop(prefix, None)
    for file_key, rows in list(ts["rows"].items()):
        explicit_rows = explicit["rows"].get(file_key, {})
        for pk, stamp in list(rows.items()):
            if newer(explicit_rows.get(pk), stamp):
                rows.pop(pk, None)
        if not rows:
            ts["rows"].pop(file_key, None)
    for file_key, bullets in list(ts["bullets"].items()):
        explicit_bullets = explicit["bullets"].get(file_key, {})
        for norm, stamp in list(bullets.items()):
            if newer(explicit_bullets.get(norm), stamp):
                bullets.pop(norm, None)
        if not bullets:
            ts["bullets"].pop(file_key, None)
    return ts


def compact(tombstones: dict[str, Any], *, now: Optional[datetime] = None, days: int = EXPIRY_DAYS) -> dict[str, Any]:
    """Drop tombstones older than ``days`` so a later re-add does not need a stamp forever."""
    ts = normalize_tombstones(tombstones)
    moment = now or datetime.now(timezone.utc)
    cutoff = (moment - timedelta(days=days)).strftime(_TS_FMT)

    def keep(stamp: str) -> bool:
        return stamp >= cutoff

    ts["files"] = {k: v for k, v in ts["files"].items() if keep(v)}
    ts["prefixes"] = {k: v for k, v in ts["prefixes"].items() if keep(v)}
    ts["rows"] = {
        fk: {pk: stamp for pk, stamp in rows.items() if keep(stamp)}
        for fk, rows in ts["rows"].items()
    }
    ts["rows"] = {fk: rows for fk, rows in ts["rows"].items() if rows}
    ts["bullets"] = {
        fk: {pk: stamp for pk, stamp in rows.items() if keep(stamp)}
        for fk, rows in ts["bullets"].items()
    }
    ts["bullets"] = {fk: rows for fk, rows in ts["bullets"].items() if rows}
    return ts


def file_blocked(
    tombstones: dict[str, Any],
    rel: str,
    *,
    mtime: Optional[str] = None,
    explicit_files: Optional[dict[str, str]] = None,
    explicit_prefixes: Optional[dict[str, str]] = None,
) -> bool:
    """True when this path must not be written or kept."""
    ts = normalize_tombstones(tombstones)
    rel = norm_rel(rel)
    if not rel or ".." in rel.split("/"):
        return False
    explicit_files = explicit_files or {}
    explicit_prefixes = explicit_prefixes or {}
    file_stamp = ts["files"].get(rel)
    file_blocks = bool(file_stamp) and not (
        newer(explicit_files.get(rel), file_stamp) or newer(mtime, file_stamp)
    )
    prefix_blocks = False
    for prefix, stamp in ts["prefixes"].items():
        if not rel.startswith(prefix):
            continue
        if newer(explicit_prefixes.get(prefix), stamp) or newer(explicit_files.get(rel), stamp):
            continue
        prefix_blocks = True
        break
    return file_blocks or prefix_blocks


def blocked_row_pks(tombstones: dict[str, Any], writes: Optional[dict[str, Any]] = None) -> set[str]:
    ts = normalize_tombstones(tombstones)
    explicit = normalize_writes(writes or {})
    stamps = ts["rows"].get("PROJECTS.md", {})
    revived = explicit["rows"].get("PROJECTS.md", {})
    return {pk for pk, stamp in stamps.items() if not newer(revived.get(pk), stamp)}


def blocked_bullet_norms(
    tombstones: dict[str, Any], rel: str, writes: Optional[dict[str, Any]] = None
) -> set[str]:
    ts = normalize_tombstones(tombstones)
    explicit = normalize_writes(writes or {})
    rel = norm_rel(rel)
    stamps = ts["bullets"].get(rel, {})
    revived = explicit["bullets"].get(rel, {})
    return {norm for norm, stamp in stamps.items() if not newer(revived.get(norm), stamp)}


def tombstone_path(root: Path) -> Path:
    return Path(root) / TOMBSTONE_FILE


def load_tombstones(root: Path) -> dict[str, Any]:
    path = tombstone_path(root)
    if not path.is_file():
        return empty_tombstones()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_tombstones()
    return normalize_tombstones(data)


def save_tombstones(root: Path, tombstones: dict[str, Any]) -> None:
    path = tombstone_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = normalize_tombstones(tombstones)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_writes(root: Path) -> dict[str, Any]:
    path = Path(root) / WRITES_FILE
    if not path.is_file():
        return empty_writes()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_writes()
    return normalize_writes(data)


def save_writes(root: Path, writes: dict[str, Any]) -> None:
    path = Path(root) / WRITES_FILE
    payload = normalize_writes(writes)
    if not any(payload[k] for k in ("files", "prefixes", "rows", "bullets")):
        if path.is_file():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def clear_writes(root: Path) -> None:
    path = Path(root) / WRITES_FILE
    if path.is_file():
        path.unlink()


def _remember_deleted_list(root: Path, rel: str) -> None:
    """Keep the legacy ``.deleted.json`` list in sync for callers that still read it."""
    log = Path(root) / DELETED_FILE
    items: list[str] = []
    if log.is_file():
        try:
            data = json.loads(log.read_text(encoding="utf-8"))
            if isinstance(data, list):
                items = [str(x) for x in data]
        except (OSError, json.JSONDecodeError):
            items = []
    if rel not in items:
        items.append(rel)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")


def record_file(root: Path, rel: str, when: Optional[str] = None) -> None:
    rel = norm_rel(rel)
    if not rel or ".." in rel.split("/"):
        return
    ts = load_tombstones(root)
    if rel not in ts["files"]:
        ts["files"][rel] = when or now_iso()
        save_tombstones(root, ts)
    _remember_deleted_list(root, rel)
    writes = load_writes(root)
    if rel in writes["files"]:
        writes["files"].pop(rel, None)
        save_writes(root, writes)


def record_prefix(root: Path, prefix: str, when: Optional[str] = None) -> None:
    prefix = _norm_prefix(prefix)
    if not prefix or ".." in prefix.split("/"):
        return
    ts = load_tombstones(root)
    if prefix not in ts["prefixes"]:
        ts["prefixes"][prefix] = when or now_iso()
        save_tombstones(root, ts)
    writes = load_writes(root)
    if prefix in writes["prefixes"]:
        writes["prefixes"].pop(prefix, None)
        save_writes(root, writes)


def record_row(root: Path, file_key: str, pk: str, when: Optional[str] = None) -> None:
    pk = pk.strip().lower()
    if not pk or pk in {"slug", "------"} or pk.startswith("-"):
        return
    ts = load_tombstones(root)
    rows = ts["rows"].setdefault(file_key, {})
    if pk not in rows:
        rows[pk] = when or now_iso()
        save_tombstones(root, ts)
    writes = load_writes(root)
    file_writes = writes["rows"].get(file_key, {})
    if pk in file_writes:
        file_writes.pop(pk, None)
        if file_writes:
            writes["rows"][file_key] = file_writes
        else:
            writes["rows"].pop(file_key, None)
        save_writes(root, writes)


def record_bullet(root: Path, rel: str, norm: str, when: Optional[str] = None) -> None:
    rel = norm_rel(rel)
    norm = norm.strip().lower()
    if not rel or not norm:
        return
    ts = load_tombstones(root)
    bullets = ts["bullets"].setdefault(rel, {})
    if norm not in bullets:
        bullets[norm] = when or now_iso()
        save_tombstones(root, ts)
    writes = load_writes(root)
    file_writes = writes["bullets"].get(rel, {})
    if norm in file_writes:
        file_writes.pop(norm, None)
        if file_writes:
            writes["bullets"][rel] = file_writes
        else:
            writes["bullets"].pop(rel, None)
        save_writes(root, writes)


def record_explicit_file_write(root: Path, rel: str, when: Optional[str] = None) -> None:
    rel = norm_rel(rel)
    if not rel:
        return
    when = when or now_iso()
    ts = load_tombstones(root)
    if rel in ts["files"]:
        ts["files"].pop(rel, None)
        save_tombstones(root, ts)
    writes = load_writes(root)
    writes["files"][rel] = when
    save_writes(root, writes)


def record_prefix_write(root: Path, prefix: str, when: Optional[str] = None) -> None:
    prefix = _norm_prefix(prefix)
    if not prefix:
        return
    when = when or now_iso()
    ts = load_tombstones(root)
    ts["prefixes"].pop(prefix, None)
    revived_files = []
    for rel in list(ts["files"]):
        if rel.startswith(prefix):
            ts["files"].pop(rel, None)
            revived_files.append(rel)
    save_tombstones(root, ts)
    writes = load_writes(root)
    writes["prefixes"][prefix] = when
    for rel in revived_files:
        writes["files"][rel] = when
    save_writes(root, writes)


def record_row_write(root: Path, pk: str, when: Optional[str] = None) -> None:
    pk = pk.strip().lower()
    if not pk:
        return
    when = when or now_iso()
    ts = load_tombstones(root)
    rows = ts["rows"].get("PROJECTS.md", {})
    if pk in rows:
        rows.pop(pk, None)
        if rows:
            ts["rows"]["PROJECTS.md"] = rows
        else:
            ts["rows"].pop("PROJECTS.md", None)
        save_tombstones(root, ts)
    writes = load_writes(root)
    writes["rows"].setdefault("PROJECTS.md", {})[pk] = when
    save_writes(root, writes)


def record_bullet_write(root: Path, rel: str, norm: str, when: Optional[str] = None) -> None:
    rel = norm_rel(rel)
    norm = norm.strip().lower()
    if not rel or not norm:
        return
    when = when or now_iso()
    ts = load_tombstones(root)
    bullets = ts["bullets"].get(rel, {})
    if norm in bullets:
        bullets.pop(norm, None)
        if bullets:
            ts["bullets"][rel] = bullets
        else:
            ts["bullets"].pop(rel, None)
        save_tombstones(root, ts)
    writes = load_writes(root)
    writes["bullets"].setdefault(rel, {})[norm] = when
    save_writes(root, writes)


def absorb_deleted_list(tombstones: dict[str, Any], deleted: Any, when: Optional[str] = None) -> dict[str, Any]:
    """Old clients send ``deleted: [path, ...]`` with no stamps. Honor those paths."""
    ts = normalize_tombstones(tombstones)
    if not isinstance(deleted, list):
        return ts
    stamp = when or now_iso()
    for item in deleted:
        rel = norm_rel(str(item))
        if not rel or ".." in rel.split("/"):
            continue
        prev = ts["files"].get(rel)
        if prev is None or stamp > prev:
            ts["files"][rel] = stamp
    return ts


def file_tombstone_paths(tombstones: dict[str, Any]) -> list[str]:
    return sorted(normalize_tombstones(tombstones)["files"])


def delete_prefix_tree(root: Path, prefix: str) -> list[str]:
    """Tombstone and unlink files under ``prefix`` inside ``root``. Returns bundle paths."""
    prefix = _norm_prefix(prefix)
    base = Path(root) / prefix
    removed: list[str] = []
    if not base.exists():
        record_prefix(root, prefix)
        return removed
    files = [p for p in base.rglob("*") if p.is_file()]
    for path in files:
        rel = path.relative_to(root).as_posix()
        record_file(root, rel)
        try:
            path.unlink()
            removed.append(rel)
        except OSError:
            pass
    record_prefix(root, prefix)
    dirs = sorted((p for p in base.rglob("*") if p.is_dir()), reverse=True)
    for directory in dirs:
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        base.rmdir()
    except OSError:
        pass
    return removed


def note_project_diff(root: Path, before_slugs: set[str], after_slugs: set[str]) -> None:
    """Row + project-tree tombstones when PROJECTS.md slugs change."""
    removed = {s.strip().lower() for s in before_slugs if s.strip()} - {
        s.strip().lower() for s in after_slugs if s.strip()
    }
    added = {s.strip().lower() for s in after_slugs if s.strip()} - {
        s.strip().lower() for s in before_slugs if s.strip()
    }
    for slug in sorted(removed):
        record_row(root, "PROJECTS.md", slug)
        delete_prefix_tree(root, f"mirror/projects/{slug}/")
        delete_prefix_tree(root, f"projects/{slug}/")
    for slug in sorted(added):
        record_row_write(root, slug)
        record_prefix_write(root, f"mirror/projects/{slug}/")
        record_prefix_write(root, f"projects/{slug}/")


def diff_projects_text(root: Path, before: str, after: str) -> None:
    from ..store import parse_projects

    before_slugs = {p.slug.lower() for p in parse_projects(before)}
    after_slugs = {p.slug.lower() for p in parse_projects(after)}
    note_project_diff(root, before_slugs, after_slugs)
    # An edited row (same slug, new cells) is a write, so a stale tombstone cannot freeze it.
    before_rows = {p.slug.lower(): (p.path, p.role, p.stack, p.status) for p in parse_projects(before)}
    after_rows = {p.slug.lower(): (p.path, p.role, p.stack, p.status) for p in parse_projects(after)}
    for slug in before_slugs & after_slugs:
        if before_rows.get(slug) != after_rows.get(slug):
            record_row_write(root, slug)
