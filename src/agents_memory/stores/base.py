"""Store protocol — the adapter seam.

One contract for every backing source: search() returns hit dicts with
``file``/``line``/``text`` keys (same shape as store.search_memory hits,
plus ``store`` stamped by the fan-out). A store may be a markdown corpus,
a repo's decisions/concepts docs, agents-store, or a vendored index —
the engine only sees this protocol.
"""

from __future__ import annotations

from typing import Any, Protocol


class Store(Protocol):
    name: str
    kind: str

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return up to ``limit`` hits for ``query``, best first."""
        ...

    def status(self) -> dict[str, Any]:
        """Health/counts for `stores list` and sense surfaces."""
        ...
