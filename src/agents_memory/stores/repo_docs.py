"""Repo docs store: a repository's decisions, concepts, and agent docs.

The post-`.agents` world keeps durable rulings as versioned docs
(`docs/decisions/`, `concepts/frag-*.md`, `AGENTS.md`, `docs/research/`).
Corpora are small — a plain scan with term scoring is honest; no index.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DOC_GLOBS = (
    "AGENTS.md",
    "docs/decisions/**/*.md",
    "docs/research/**/*.md",
    "docs/plans/**/*.md",
    "concepts/frag-*.md",
    "SPEC.md",
    "GOAL.md",
)

_STOP = frozenset(
    "the a an and or of to in on for with is are was were be been it its "
    "that this from by at as not but".split()
)


def _terms(query: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z0-9_-]+", query.lower()) if t not in _STOP]


class RepoDocsStore:
    kind = "repo-docs"

    def __init__(self, repo_root: Path | str, name: str = "") -> None:
        self.root = Path(repo_root)
        self.name = name or self.root.name

    def _files(self) -> list[Path]:
        out: list[Path] = []
        for pat in DOC_GLOBS:
            out.extend(self.root.glob(pat))
        return sorted(set(p for p in out if p.is_file()))

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        q = query.lower().strip()
        terms = _terms(q)
        hits: list[tuple[float, dict[str, Any]]] = []
        for path in self._files():
            rel = path.relative_to(self.root).as_posix()
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            best: dict[str, Any] | None = None
            best_score = 0.0
            for i, line in enumerate(lines, 1):
                low = line.lower()
                score = 0.0
                if q and q in low:
                    score += 10.0
                score += sum(1.0 for t in terms if t in low)
                if score > best_score:
                    best_score = score
                    best = {"file": rel, "line": i, "text": line.strip()[:200]}
            if best is not None and best_score > 0:
                hits.append((best_score, best))
        hits.sort(key=lambda x: -x[0])
        return [h for _, h in hits[: max(1, limit)]]

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "files": len(self._files()),
            "root": str(self.root),
        }
