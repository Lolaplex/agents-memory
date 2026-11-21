"""The default store: the markdown memory corpus.

Delegates to the existing ``search_memory`` path (exact substring, then
FTS5+TF-IDF RRF fill). The corpus root comes from the workspace, not from
this module — the store never resolves global state at import time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class MarkdownStore:
    kind = "markdown"

    def __init__(self, mem_root: Path, name: str = "memory") -> None:
        self.root = Path(mem_root)
        self.name = name

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        from ..store import search_memory

        return search_memory(query, limit=limit)

    def status(self) -> dict[str, Any]:
        n = sum(1 for _ in self.root.rglob("*.md")) if self.root.is_dir() else 0
        return {"name": self.name, "kind": self.kind, "files": n, "root": str(self.root)}
