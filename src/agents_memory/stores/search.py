"""Fan-out search over named stores — RRF merge of per-store ranked lists.

Each store returns its own ranked hits; ranks fuse via reciprocal rank
fusion (k=60, same constant as the FTS/TF-IDF path) so no store needs
commensurate scores. Refusal/error stores surface as named rows, not
silence.
"""

from __future__ import annotations

from typing import Any

from .registry import list_stores

_RRF_K = 60


def search_stores(query: str, store: str = "", limit: int = 20) -> dict[str, Any]:
    """Search one named store or fan out over all and RRF-merge.

    Returns {"hits": [...], "stores": [per-store status/failure rows]}.
    Each hit carries ``store`` (which store produced it).
    """
    limit = max(1, limit)
    rrf: dict[tuple, float] = {}
    best: dict[tuple, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []

    for s in list_stores():
        name = getattr(s, "name", None) or s.get("name", "?")
        if store and name != store:
            continue
        if isinstance(s, dict):  # refusal row from the registry
            rows.append({"store": name, "error": s.get("error", "refused")})
            continue
        try:
            hits = s.search(query, limit=limit)
        except Exception as e:  # a store that raises is a named refusal
            rows.append({"store": name, "error": f"{type(e).__name__}: {e}"})
            continue
        rows.append({"store": name, "hits": len(hits)})
        for rank, hit in enumerate(hits):
            key = (hit.get("file"), hit.get("line"))
            rrf[key] = rrf.get(key, 0.0) + 1.0 / (_RRF_K + rank)
            merged = best.setdefault(key, dict(hit))
            merged.setdefault("store", name)

    ordered = sorted(rrf.items(), key=lambda kv: -kv[1])
    return {
        "hits": [best[k] | {"rrf": round(score, 6)} for (k, score) in ordered[:limit]],
        "stores": rows,
    }
