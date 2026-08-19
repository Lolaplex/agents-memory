#!/usr/bin/env python3
"""Sync abi/, examples/, and skills/ into src/agents_memory/bundled/ for PyPI wheels."""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "agents_memory" / "bundled"

SOURCE_TREES: tuple[tuple[str, str], ...] = (
    ("abi", "abi"),
    ("examples", "examples"),
    ("skills", "skills"),
)


def _iter_files(tree: Path) -> dict[Path, Path]:
    if not tree.is_dir():
        return {}
    return {path.relative_to(tree): path for path in sorted(tree.rglob("*")) if path.is_file()}


def collect_drift() -> list[str]:
    """Return human-readable drift messages between source trees and bundled/."""
    issues: list[str] = []
    for src_name, dst_name in SOURCE_TREES:
        src = ROOT / src_name
        dst = BUNDLED / dst_name
        if not src.is_dir():
            issues.append(f"missing source tree: {src_name}/")
            continue
        src_files = _iter_files(src)
        dst_files = _iter_files(dst)
        for rel in sorted(src_files):
            src_file = src_files[rel]
            dst_file = dst_files.get(rel)
            if dst_file is None:
                issues.append(f"missing bundled: {dst_name}/{rel.as_posix()}")
                continue
            if not filecmp.cmp(src_file, dst_file, shallow=False):
                issues.append(f"diff: {src_name}/{rel.as_posix()}")
        for rel in sorted(dst_files):
            if rel not in src_files:
                issues.append(f"extra bundled: {dst_name}/{rel.as_posix()}")
    return issues


def sync_bundled() -> list[str]:
    """Copy source trees into bundled/. Returns list of copied relative paths."""
    copied: list[str] = []
    BUNDLED.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in SOURCE_TREES:
        src = ROOT / src_name
        dst = BUNDLED / dst_name
        if not src.is_dir():
            raise FileNotFoundError(f"Expected source tree at {src}")
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        for path in sorted(dst.rglob("*")):
            if path.is_file():
                copied.append(path.relative_to(BUNDLED).as_posix())
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when bundled/ drifts from abi/, examples/, or skills/",
    )
    args = parser.parse_args(argv)

    if args.check:
        issues = collect_drift()
        if issues:
            for issue in issues:
                print(issue, file=sys.stderr)
            print(
                f"\n{bundled_hint()}",
                file=sys.stderr,
            )
            return 1
        print(f"bundled/ in sync ({BUNDLED})")
        return 0

    copied = sync_bundled()
    print(f"synced {len(copied)} files into {BUNDLED}")
    return 0


def bundled_hint() -> str:
    return f"Run: {sys.executable} scripts/sync_bundled.py"


if __name__ == "__main__":
    raise SystemExit(main())
