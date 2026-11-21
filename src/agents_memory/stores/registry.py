"""Named stores from stores.json — what backs each store is config, not code.

    <ws>/memory/stores.json
    {"stores": [
      {"name": "klanker", "kind": "repo-docs", "path": "C:/repos/klanker"},
      {"name": "isar",    "kind": "repo-docs", "path": "C:/repos/isar-proofs"}
    ]}

The markdown memory corpus is always present as ``memory`` whether or not
stores.json exists. Unknown kinds are named refusals in ``status()``, never
silent skips.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import Store
from .markdown import MarkdownStore
from .repo_docs import RepoDocsStore
from .traces import TracesStore

_KINDS = {
    "markdown": MarkdownStore,
    "repo-docs": RepoDocsStore,
    "traces": TracesStore,
}


def _mem_root() -> Path:
    from ..store import _attr

    return Path(_attr("USER_MEMORY"))


def list_stores() -> list[Store | dict[str, Any]]:
    """Resolved stores; unreadable/misconfigured entries become refusal dicts."""
    mem = _mem_root()
    stores: list[Store | dict[str, Any]] = [MarkdownStore(mem)]
    cfg = mem / "stores.json"
    if not cfg.is_file():
        return stores
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return stores + [{"name": "stores.json", "kind": "error", "error": str(e)}]
    for spec in data.get("stores", []):
        kind, name = spec.get("kind", ""), spec.get("name", "")
        cls = _KINDS.get(kind)
        if cls is None:
            stores.append({"name": name or "?", "kind": "error",
                           "error": f"unknown store kind {kind!r}"})
            continue
        path = spec.get("path", "")
        if not path:
            stores.append({"name": name or kind, "kind": "error",
                           "error": "store spec missing path"})
            continue
        stores.append(cls(Path(path), name=name))
    return stores


def get_store(name: str) -> Store | dict[str, Any] | None:
    for s in list_stores():
        if (getattr(s, "name", None) or s.get("name")) == name:
            return s
    return None
