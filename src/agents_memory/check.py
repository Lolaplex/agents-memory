"""Mechanical store health checks — read-only, zero AI.

Wave 5 primitive: `python -m agents_memory check [--json]`.
Exit code = number of failing checks (runner-friendly). Designed to be
invoked by agents-harness / later plexd; never self-triggers.

Each result uses a stable `check` id so a care-schedule can name failures
instead of one boolean kitchen sink.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from . import frontmatter as fm_schema
from . import store
from .index import parse_frontmatter_and_content

SKIP_PARTS = frozenset({".index", "export", "staging", "orphans"})


def _iter_notes() -> list[Path]:
    files: list[Path] = []
    for md in store.iter_user_memory_files():
        if SKIP_PARTS.intersection(md.parts):
            continue
        files.append(md)
    for md in store.iter_project_memory_files():
        if SKIP_PARTS.intersection(md.parts):
            continue
        files.append(md)
    return files


def check_staging() -> dict:
    try:
        paths = store._collect_staging_paths()
    except Exception:
        paths = []
    bullets = 0
    for p in paths:
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            bullets += sum(1 for l in text.splitlines() if l.strip().startswith("- "))
    return {
        "check": "staging-leftovers",
        "ok": bullets == 0,
        "detail": f"{bullets} unprocessed bullets",
    }


def _is_user_project_card(path: Path) -> bool:
    """user/projects/<slug>/README.md is a generated mirror of the in-tree card."""
    try:
        rel = path.resolve().relative_to(store.USER_MEMORY.resolve())
    except ValueError:
        return False
    parts = rel.parts
    return len(parts) >= 3 and parts[0] == "projects" and parts[-1] == "README.md"


def _resolve_relation_target(source: Path, target: str) -> Path | None:
    candidates = [target]
    if not target.endswith(".md"):
        candidates.append(target + ".md")
    for cand in candidates:
        try:
            path = store.resolve_memory_path(cand)
        except FileNotFoundError:
            continue
        if path.is_file():
            return path
    if target.startswith(".agents/memory/"):
        for parent in source.parents:
            if parent.name == "memory" and parent.parent.name == ".agents":
                inner = target[len(".agents/memory/") :]
                path = parent / inner
                if path.suffix != ".md":
                    path = path.with_suffix(".md")
                if path.is_file():
                    return path
                break
    return None


def check_duplicates() -> dict:
    by_hash: dict[str, list[str]] = defaultdict(list)
    for md in _iter_notes():
        if _is_user_project_card(md):
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        body = re.sub(r"[-#`\s]", "", text.lower())
        if len(body) < 20:
            continue
        by_hash[hashlib.sha1(body.encode()).hexdigest()].append(str(md))
    dupes = {h: v for h, v in by_hash.items() if len(v) > 1}
    files = [f for v in dupes.values() for f in v]
    return {
        "check": "duplicate-notes",
        "ok": not dupes,
        "detail": f"{len(dupes)} duplicate groups",
        "files": files[:20],
    }


def check_near_duplicate_slugs() -> dict:
    pairs = fm_schema.near_duplicate_stems(_iter_notes())
    files = [p for pair in pairs for p in pair]
    return {
        "check": "near-duplicate-slugs",
        "ok": not pairs,
        "detail": f"{len(pairs)} prefix-stem pairs in the same directory",
        "files": files[:20],
    }


def check_stubs(min_chars: int = 40) -> dict:
    stubs = []
    for md in _iter_notes():
        text = md.read_text(encoding="utf-8", errors="replace").strip()
        body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
        if len(body.strip()) < min_chars:
            stubs.append(str(md))
    return {
        "check": "stub-notes",
        "ok": not stubs,
        "detail": f"{len(stubs)} notes under {min_chars} chars",
        "files": stubs[:20],
    }


def check_index_stale() -> dict:
    from .index import FTS_DB

    db = FTS_DB
    if not db.exists():
        return {
            "check": "index-stale",
            "ok": True,
            "detail": "no FTS index built (skipped)",
        }
    notes = _iter_notes()
    newest = max((f.stat().st_mtime for f in notes), default=0)
    stale = db.stat().st_mtime < newest
    return {
        "check": "index-stale",
        "ok": not stale,
        "detail": "index newer than all notes"
        if not stale
        else "index older than newest note — run rebuild-index",
    }


def check_frontmatter_schema() -> dict:
    files: list[str] = []
    n_issues = 0
    for md in _iter_notes():
        text = md.read_text(encoding="utf-8", errors="replace")
        issues = fm_schema.lint_frontmatter_text(text)
        if issues:
            n_issues += len(issues)
            files.append(f"{md}: {'; '.join(issues)}")
    return {
        "check": "frontmatter-schema",
        "ok": n_issues == 0,
        "detail": f"{n_issues} schema issues in {len(files)} files"
        if files
        else "all fenced frontmatter matches SCHEMA_KEYS",
        "files": files[:20],
    }


def check_dangling_refs() -> dict:
    dangling: list[str] = []
    for md in _iter_notes():
        text = md.read_text(encoding="utf-8", errors="replace")
        if not text.lstrip().startswith("---"):
            continue
        parsed, _, _, _ = parse_frontmatter_and_content(text)
        for target in fm_schema.relation_targets(parsed):
            if fm_schema.is_external_target(target):
                continue
            path = _resolve_relation_target(md, target)
            if path is None:
                dangling.append(f"{md} -> {target}")
    return {
        "check": "dangling-refs",
        "ok": not dangling,
        "detail": f"{len(dangling)} unresolved relation targets",
        "files": dangling[:20],
    }


def run_all(as_json: bool = False) -> int:
    results = [
        check_staging(),
        check_duplicates(),
        check_near_duplicate_slugs(),
        check_stubs(),
        check_index_stale(),
        check_frontmatter_schema(),
        check_dangling_refs(),
    ]
    failures = sum(1 for r in results if not r["ok"])
    if as_json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for r in results:
            mark = "OK  " if r["ok"] else "FAIL"
            print(f"[{mark}] {r['check']}: {r['detail']}")
            for f in r.get("files", [])[:10]:
                print(f"       - {f}")
    return failures


def main(argv: list[str] | None = None) -> int:
    as_json = "--json" in (argv or [])
    return run_all(as_json=as_json)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
