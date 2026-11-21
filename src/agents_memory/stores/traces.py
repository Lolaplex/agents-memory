"""Traces store: agents-traces session logs as a retrieval source.

Reads append-only `YYYY-MM-DD.jsonl` files — each line a typed event whose
`metadata.content` carries message text. Procedural memory searchable next
to the semantic corpus: "which session did we decide X in" becomes one
fan-out query. Scans newest files first, bounded by file count, not by a
hidden index.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .repo_docs import _terms

_MAX_FILES = 90  # ~3 months of daily logs; older history is session_*'s job


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(c.get("text", c)) if isinstance(c, dict) else str(c) for c in content)
    return ""


class TracesStore:
    kind = "traces"

    def __init__(self, traces_root: Path | str, name: str = "traces") -> None:
        self.root = Path(traces_root)
        self.name = name

    def _files(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        files = sorted(self.root.glob("????-??-??.jsonl"), reverse=True)
        return files[:_MAX_FILES]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        q = query.lower().strip()
        terms = _terms(q)
        hits: list[tuple[float, dict[str, Any]]] = []
        for path in self._files():
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                low = line.lower()
                if q and q not in low and not any(t in low for t in terms):
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = _content_text(d.get("metadata", {}).get("content"))
                if not text:
                    continue
                tlow = text.lower()
                score = (10.0 if q and q in tlow else 0.0) + sum(
                    1.0 for t in terms if t in tlow
                )
                if score <= 0:
                    continue
                hits.append((score, {
                    "file": path.name,
                    "line": i,
                    "text": text.strip()[:200],
                    "session": d.get("session", ""),
                    "role": d.get("metadata", {}).get("role", ""),
                    "ts": d.get("ts", ""),
                }))
        hits.sort(key=lambda x: -x[0])
        return [h for _, h in hits[: max(1, limit)]]

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "files": len(self._files()),
            "root": str(self.root),
        }
