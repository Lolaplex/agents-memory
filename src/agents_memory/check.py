"""Mechanical store health checks — read-only, zero AI.

The Wave 5 primitive: `python -m agents_memory check [--json]`.
Exit code = number of failing checks (runner-friendly). Designed to be
invoked by external scheduling (agents-runner); never self-triggers.

Checks:
  staging     bullets left in staging/ (unprocessed ingest)
  duplicates  identical normalized note bodies across files
  stubs       notes with suspiciously little content
  index-stale FTS index older than the newest note (if index exists)
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from .store import USER_MEMORY, _collect_staging_paths


def _iter_notes():
    for md in USER_MEMORY.rglob("*.md"):
        if "/staging/" in str(md.as_posix()) or "\\staging\\" in str(md):
            continue
        yield md


def check_staging() -> dict:
    try:
        paths = _collect_staging_paths()
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


def check_duplicates() -> dict:
    by_hash: dict[str, list[str]] = defaultdict(list)
    for md in _iter_notes():
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


def check_stubs(min_chars: int = 40) -> dict:
    stubs = []
    for md in _iter_notes():
        text = md.read_text(encoding="utf-8", errors="replace").strip()
        # strip frontmatter-ish header lines starting with #
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
    db = USER_MEMORY / ".fts-index.db"
    if not db.exists():
        return {
            "check": "index-stale",
            "ok": True,
            "detail": "no FTS index built (skipped)",
        }
    newest = max((f.stat().st_mtime for f in _iter_notes()), default=0)
    stale = db.stat().st_mtime < newest
    return {
        "check": "index-stale",
        "ok": not stale,
        "detail": "index newer than all notes"
        if not stale
        else "index older than newest note — run rebuild-index",
    }


def run_all(as_json: bool = False) -> int:
    results = [
        check_staging(),
        check_duplicates(),
        check_stubs(),
        check_index_stale(),
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
