"""Manifest-index store: read-side of a bench quotient tower.

A bench-built `*.sqlite` tower (docs/meta/manifest/lineage/superseded)
becomes a search surface — the measured 1.000/.982 arm from agents-bench,
read through the Store protocol. Seeding = smallest live node whose
manifest covers all query terms (coverage boundary); descent picks
children by manifest coverage to leaves. Read-only: tower building
stays with the benchmark for now.

Spec: {"name": "msc", "kind": "manifest-index", "path": "<tower.sqlite>"}
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

_WORD = re.compile(r"[A-Za-z0-9_]+")
_LIVE = "doc_id NOT IN (SELECT doc_id FROM superseded)"
_TOPC = 3


def _terms(query: str) -> set[str]:
    return set(_WORD.findall(query.lower()))


class ManifestIndexStore:
    kind = "manifest-index"

    def __init__(self, db_path: Path | str, name: str = "manifest-index") -> None:
        self.path = Path(db_path)
        self.name = name
        self._conn: sqlite3.Connection | None = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        return self._conn

    def _descend(self, cur, terms: set[str], node: tuple) -> list[tuple]:
        doc_id = node[0]
        children = cur.execute(
            "SELECT m.doc_id, m.path, m.level, m.text FROM meta m "
            "JOIN lineage l ON l.source_id = m.doc_id WHERE l.node_id = ? "
            f"AND m.{_LIVE}",
            (doc_id,),
        ).fetchall()
        if not children:
            return [node]
        covers = {
            r[0]: set(r[1].split())
            for r in cur.execute(
                "SELECT doc_id, terms FROM manifest "
                f"WHERE doc_id IN ({','.join('?' * len(children))})",
                [c[0] for c in children],
            ).fetchall()
        }
        picked = [
            c for c in sorted(children, key=lambda c: -len(terms & covers.get(c[0], set())))[:_TOPC]
            if terms & covers.get(c[0], set())
        ]
        if not picked:
            return [node]
        out: list[tuple] = []
        for c in picked:
            out.extend(self._descend(cur, terms, c))
        return out

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        terms = _terms(query)
        if not terms or not self.path.is_file():
            return []
        cur = self._db().cursor()
        wh = " AND ".join(f"(' '||f.terms||' ') LIKE '% {t} %'" for t in terms)
        seeds = cur.execute(
            "SELECT m.doc_id, m.path, m.level, m.text FROM meta m "
            "JOIN manifest f ON f.doc_id = m.doc_id "
            f"WHERE m.{_LIVE} AND {wh} "
            "ORDER BY LENGTH(f.terms) LIMIT ?",
            (max(limit, _TOPC),),
        ).fetchall()
        hits: list[dict[str, Any]] = []
        for seed in seeds:
            for (_did, path, level, text) in self._descend(cur, terms, seed):
                hits.append({
                    "file": str(path),
                    "line": 0,
                    "text": (text or "")[:200],
                    "level": level,
                })
                if len(hits) >= limit:
                    return hits
        return hits

    def status(self) -> dict[str, Any]:
        st = {"name": self.name, "kind": self.kind, "root": str(self.path)}
        if self.path.is_file():
            cur = self._db().cursor()
            st["docs"] = cur.execute(f"SELECT COUNT(*) FROM meta WHERE {_LIVE}").fetchone()[0]
        else:
            st["error"] = "tower db not found"
        return st
