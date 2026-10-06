"""Disposable full-text search index and hybrid retrieval cache.

Source of truth is always markdown on disk.
The index lives in USER_MEMORY/.index/ (gitignored) and is rebuildable in one command.
USER_MEMORY follows AGENTS_MEMORY_PATH, else AGENTS_HOME/memory.

One SQLite file holds FTS5 BM25 and sparse TF-IDF postings. Query-time RRF
fuses the two rank lists. No embedding model; no second store.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .store import (
    CHRONICLE_DIR,
    PROJECTS_MD,
    SEARCH_ALL,
    USER_MEMORY,
    _read,
    parse_projects,
    resolve_search_project,
)

INDEX_DIR = USER_MEMORY / ".index"
FTS_DB = INDEX_DIR / "fts.sqlite"

# Reciprocal Rank Fusion constant (Cormack et al.; Azure Search default).
RRF_K = 60
# How many candidates to pull from each list before fusion.
_CANDIDATE_MULT = 5
_CANDIDATE_FLOOR = 50

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def ensure_index_dir() -> Path:
    """Ensure ~/.agents/memory/.index exists and is gitignored."""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    gi = INDEX_DIR / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")
    return INDEX_DIR


def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    ensure_index_dir()
    target_path = db_path or (INDEX_DIR / "fts.sqlite")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                project TEXT NOT NULL,
                title TEXT NOT NULL,
                headings TEXT,
                frontmatter_json TEXT,
                content TEXT NOT NULL,
                mtime REAL NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                id,
                title,
                headings,
                content,
                tokenize='porter unicode61'
            );
            """
        )
        # Sparse TF-IDF lives in the same disposable cache as FTS5.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tfidf_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tfidf_idf (
                term TEXT PRIMARY KEY,
                idf REAL NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tfidf_postings (
                term TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                weight REAL NOT NULL,
                PRIMARY KEY (term, doc_id)
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tfidf_postings_term ON tfidf_postings(term);"
        )


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _doc_tf(text: str) -> Dict[str, int]:
    tf: Dict[str, int] = {}
    for t in _tokenize(text):
        tf[t] = tf.get(t, 0) + 1
    return tf


def parse_frontmatter_and_content(text: str) -> Tuple[Dict[str, Any], str, str, List[str]]:
    """Parse YAML frontmatter, title, headings, and clean body text."""
    frontmatter: Dict[str, Any] = {}
    content = text
    title = ""
    headings: List[str] = []

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            content = parts[2]
            # Simple line-based YAML parser for zero-dep guarantee
            cur_key: Optional[str] = None
            for line in fm_text.splitlines():
                line_str = line.strip()
                if not line_str or line_str.startswith("#"):
                    continue
                if line_str.startswith("- ") and cur_key:
                    val = line_str[2:].strip().strip("\"'")
                    if not isinstance(frontmatter.get(cur_key), list):
                        frontmatter[cur_key] = []
                    frontmatter[cur_key].append(val)
                elif ":" in line_str:
                    k, v = line_str.split(":", 1)
                    k = k.strip()
                    v = v.strip().strip("\"'")
                    cur_key = k
                    if v:
                        frontmatter[k] = v
                    else:
                        frontmatter[k] = []

    # Extract wikilinks from content into refs
    wikilinks = re.findall(r"\[\[([^\]\|#]+)(?:[\|#][^\]]*)?\]\]", content)
    if wikilinks:
        refs = frontmatter.setdefault("refs", [])
        if isinstance(refs, list):
            for wl in wikilinks:
                wl_clean = wl.strip()
                if wl_clean and wl_clean not in refs:
                    refs.append(wl_clean)

    # Title extraction
    title = str(frontmatter.get("title") or "")
    for line in content.splitlines():
        line_str = line.strip()
        if not title and line_str.startswith("# "):
            title = line_str[2:].strip()
        elif line_str.startswith("## ") or line_str.startswith("### "):
            headings.append(line_str.lstrip("#").strip())

    if not title:
        title = "Untitled"

    return frontmatter, title, content.strip(), headings


def _build_tfidf(
    conn: sqlite3.Connection,
    records: List[Tuple[str, str, str, str, str, str, str, float]],
) -> int:
    """Write L2-normalized TF-IDF postings for the same docs as FTS."""
    conn.execute("DELETE FROM tfidf_meta;")
    conn.execute("DELETE FROM tfidf_idf;")
    conn.execute("DELETE FROM tfidf_postings;")
    if not records:
        conn.execute(
            "INSERT INTO tfidf_meta(key, value) VALUES ('n_docs', '0'), ('kind', 'tfidf');"
        )
        return 0

    # record: id, path, project, title, headings, fm, content, mtime
    doc_tfs: List[Tuple[str, Dict[str, int]]] = []
    df: Dict[str, int] = defaultdict(int)
    for r in records:
        text = f"{r[3]}\n{r[4]}\n{r[6]}"
        tf = _doc_tf(text)
        doc_tfs.append((r[0], tf))
        for term in tf:
            df[term] += 1

    n_docs = len(doc_tfs)
    idf = {t: math.log((n_docs + 1) / (c + 1)) + 1.0 for t, c in df.items()}
    conn.executemany(
        "INSERT INTO tfidf_idf(term, idf) VALUES (?, ?);",
        list(idf.items()),
    )

    postings: List[Tuple[str, str, float]] = []
    for doc_id, tf in doc_tfs:
        weights = {t: c * idf[t] for t, c in tf.items() if t in idf}
        norm = math.sqrt(sum(v * v for v in weights.values())) or 1.0
        for t, w in weights.items():
            postings.append((t, doc_id, w / norm))
    conn.executemany(
        "INSERT INTO tfidf_postings(term, doc_id, weight) VALUES (?, ?, ?);",
        postings,
    )
    conn.execute(
        "INSERT INTO tfidf_meta(key, value) VALUES ('n_docs', ?), ('kind', 'tfidf');",
        (str(n_docs),),
    )
    return len(postings)


def rebuild_index(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Crawl user memory + project memory trees and rebuild the FTS+TF-IDF index."""
    t0 = time.perf_counter()
    target_path = db_path or (INDEX_DIR / "fts.sqlite")
    conn = get_db(target_path)

    # Collect all markdown files
    records: List[Tuple[str, str, str, str, str, str, str, float]] = []

    # 1. User memory
    for p in USER_MEMORY.rglob("*.md"):
        if ".index" in p.parts or "export" in p.parts:
            continue
        rel = str(p.relative_to(USER_MEMORY)).replace("\\", "/")
        doc_id = f"user/{rel}"
        try:
            mtime = p.stat().st_mtime
            text = _read(p)
        except OSError:
            continue
        fm, title, body, headings = parse_frontmatter_and_content(text)
        records.append((
            doc_id,
            str(p.resolve()),
            "",
            title,
            " | ".join(headings),
            json.dumps(fm),
            body,
            mtime,
        ))

    # 2. Registered project in-tree memory
    for proj in parse_projects():
        mem_dir = proj.memory_dir
        if not mem_dir.is_dir():
            continue
        for p in mem_dir.rglob("*.md"):
            try:
                rel = str(p.relative_to(mem_dir)).replace("\\", "/")
                doc_id = f"project/{proj.slug}/{rel}"
                mtime = p.stat().st_mtime
                text = _read(p)
            except (ValueError, OSError):
                continue
            fm, title, body, headings = parse_frontmatter_and_content(text)
            records.append((
                doc_id,
                str(p.resolve()),
                proj.slug,
                title,
                " | ".join(headings),
                json.dumps(fm),
                body,
                mtime,
            ))

    # Write into SQLite (FTS5 + sparse TF-IDF, one disposable cache)
    with conn:
        conn.execute("DELETE FROM documents;")
        conn.execute("DELETE FROM documents_fts;")
        conn.executemany(
            """
            INSERT INTO documents (id, file_path, project, title, headings, frontmatter_json, content, mtime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            records,
        )
        conn.executemany(
            """
            INSERT INTO documents_fts (id, title, headings, content)
            VALUES (?, ?, ?, ?);
            """,
            [(r[0], r[3], r[4], r[6]) for r in records],
        )
        n_postings = _build_tfidf(conn, records)

    conn.close()
    duration_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "indexed": len(records),
        "tfidf_postings": n_postings,
        "duration_ms": round(duration_ms, 2),
        "db_path": str(target_path),
    }


def _candidate_limit(limit: int) -> int:
    return max(_CANDIDATE_FLOOR, max(1, limit) * _CANDIDATE_MULT)


def _fts_ranked(
    conn: sqlite3.Connection,
    terms: List[str],
    project: str,
    pool: int,
) -> List[Tuple[str, str, str, str, str, float]]:
    """Return (id, title, project, fm_json, snippet, bm25_rank) ordered by FTS rank."""
    fts_query = " OR ".join(f'"{t}"' for t in terms)
    sql = """
        SELECT d.id, d.title, d.project, d.frontmatter_json,
               snippet(documents_fts, 3, '<b>', '</b>', '...', 15) as snip,
               rank
        FROM documents_fts
        JOIN documents d ON documents_fts.id = d.id
        WHERE documents_fts MATCH ?
    """
    params: List[Any] = [fts_query]
    if project:
        sql += " AND d.project = ?"
        params.append(project)
    sql += " ORDER BY rank LIMIT ?"
    params.append(pool)
    cur = conn.cursor()
    cur.execute(sql, params)
    return list(cur.fetchall())


def _tfidf_ranked(
    conn: sqlite3.Connection,
    terms: List[str],
    project: str,
    pool: int,
) -> List[Tuple[str, float]]:
    """Cosine-style scores via pre-normalized TF-IDF postings. Ordered desc."""
    cur = conn.cursor()
    cur.execute("SELECT term, idf FROM tfidf_idf WHERE term IN (%s)" % ",".join("?" * len(terms)), terms)
    idf_rows = {t: float(i) for t, i in cur.fetchall()}
    if not idf_rows:
        return []

    q_tf: Dict[str, int] = {}
    for t in terms:
        if t in idf_rows:
            q_tf[t] = q_tf.get(t, 0) + 1
    if not q_tf:
        return []

    q_w = {t: c * idf_rows[t] for t, c in q_tf.items()}
    q_norm = math.sqrt(sum(v * v for v in q_w.values())) or 1.0

    scores: Dict[str, float] = defaultdict(float)
    for t, qw in q_w.items():
        qw_n = qw / q_norm
        if project:
            cur.execute(
                """
                SELECT p.doc_id, p.weight FROM tfidf_postings p
                JOIN documents d ON d.id = p.doc_id
                WHERE p.term = ? AND d.project = ?
                """,
                (t, project),
            )
        else:
            cur.execute(
                "SELECT doc_id, weight FROM tfidf_postings WHERE term = ?",
                (t,),
            )
        for doc_id, weight in cur.fetchall():
            scores[str(doc_id)] += qw_n * float(weight)

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked[:pool]


def _rrf_fuse(
    fts_ids: List[str],
    tfidf_ids: List[str],
    *,
    k: int = RRF_K,
) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion over two ordered id lists."""
    scores: Dict[str, float] = defaultdict(float)
    for rank, doc_id in enumerate(fts_ids, start=1):
        scores[doc_id] += 1.0 / (k + rank)
    for rank, doc_id in enumerate(tfidf_ids, start=1):
        scores[doc_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _ensure_tfidf(conn: sqlite3.Connection) -> bool:
    """True if TF-IDF tables have postings; rebuild path handles empty vaults."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT value FROM tfidf_meta WHERE key = 'n_docs'")
        row = cur.fetchone()
        if row is None:
            return False
        cur.execute("SELECT 1 FROM tfidf_idf LIMIT 1")
        return cur.fetchone() is not None or int(row[0] or 0) == 0
    except sqlite3.OperationalError:
        return False


def search_hybrid(
    query: str,
    project: str = "",
    limit: int = 20,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """FTS5 BM25 + sparse TF-IDF cosine, fused with RRF. Same disposable index."""
    if not query.strip():
        return []

    target_path = db_path or (INDEX_DIR / "fts.sqlite")
    if not target_path.exists():
        rebuild_index(target_path)

    terms = _tokenize(query)
    if not terms:
        return []

    pool = _candidate_limit(limit)
    conn = get_db(target_path)
    try:
        if not _ensure_tfidf(conn):
            conn.close()
            rebuild_index(target_path)
            conn = get_db(target_path)

        sql = """
            SELECT d.id, d.title, d.project, d.frontmatter_json,
                snippet(documents_fts, 3, '<b>', '</b>', '...', 15) as snip,
                rank
            FROM documents_fts
            JOIN documents d ON documents_fts.id = d.id
            WHERE documents_fts MATCH ?
        """
        params: List[Any] = [fts_query]
        token = resolve_search_project(project)
        if token == SEARCH_ALL:
            pass
        elif token:
            sql += " AND (d.project = ? OR d.project = '')"
            params.append(token)
        else:
            sql += " AND d.project = ''"
        try:
            fts_rows = _fts_ranked(conn, terms, project, pool)
        except sqlite3.OperationalError:
            conn.close()
            rebuild_index(target_path)
            conn = get_db(target_path)
            fts_rows = _fts_ranked(conn, terms, project, pool)

        tfidf_rows = _tfidf_ranked(conn, terms, project, pool)

        fts_ids = [r[0] for r in fts_rows]
        tfidf_ids = [r[0] for r in tfidf_rows]
        fused = _rrf_fuse(fts_ids, tfidf_ids)[: max(1, limit)]

        fts_by_id = {r[0]: r for r in fts_rows}
        tfidf_score = {doc_id: score for doc_id, score in tfidf_rows}

        hits: List[Dict[str, Any]] = []
        cur = conn.cursor()
        for doc_id, rrf in fused:
            if doc_id in fts_by_id:
                _id, title, proj, fm_json, snip, bm25 = fts_by_id[doc_id]
            else:
                cur.execute(
                    "SELECT id, title, project, frontmatter_json, content FROM documents WHERE id = ?",
                    (doc_id,),
                )
                row = cur.fetchone()
                if not row:
                    continue
                _id, title, proj, fm_json, content = row
                snip = (content or "").replace("\n", " ").strip()[:160]
                bm25 = 0.0
            fm = json.loads(fm_json) if fm_json else {}
            hits.append({
                "id": _id,
                "title": title,
                "project": proj,
                "snippet": snip,
                "rank": bm25,
                "tfidf": tfidf_score.get(doc_id, 0.0),
                "rrf": rrf,
                "frontmatter": fm,
            })
        return hits
    finally:
        conn.close()


def get_related(
    memory_id: str,
    limit: int = 5,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Retrieve explicit relations (refs/supersedes/same_as/backlinks) and content-related documents."""
    target_path = db_path or (INDEX_DIR / "fts.sqlite")
    if not target_path.exists():
        rebuild_index(target_path)

    clean_id = memory_id.strip()
    if clean_id.startswith("memory:"):
        clean_id = clean_id[len("memory:") :].strip()
    doc_lookup = clean_id.split("#")[0].split(":")[0].strip() or clean_id

    conn = get_db(target_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, project, frontmatter_json, headings, content FROM documents WHERE id = ? OR id = ? OR id LIKE ?",
        (doc_lookup, memory_id, f"%{doc_lookup}%"),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"id": memory_id, "explicit_relations": {}, "related_documents": []}

    doc_id, title, proj, fm_json, headings_str, content = row
    fm = json.loads(fm_json) if fm_json else {}

    # 1. Backlink discovery across documents table
    stem = Path(doc_id).stem
    cur.execute(
        """
        SELECT d.id, d.title FROM documents d
        WHERE d.id != ? AND (
            d.frontmatter_json LIKE ? OR d.content LIKE ? OR d.content LIKE ?
        ) LIMIT 20
        """,
        (doc_id, f"%{doc_id}%", f"%[[{doc_id}]]%", f"%[[{stem}]]%"),
    )
    backlinks = [{"id": r[0], "title": r[1]} for r in cur.fetchall()]

    explicit = {
        "refs": fm.get("refs") or [],
        "backlinks": backlinks,
        "supersedes": fm.get("supersedes") or "",
        "same_as": fm.get("same_as") or "",
        "at_project": fm.get("at_project") or "",
    }

    # 2. Content neighbors via the same fused search (not a second store)
    related: List[Dict[str, Any]] = []
    seed = f"{title} {headings_str or ''}".strip() or " ".join(_tokenize(content[:400])[:8])
    if seed.strip():
        conn.close()
        neighbors = search_hybrid(seed, project=proj or "", limit=limit + 3, db_path=target_path)
        for n in neighbors:
            if n["id"] == doc_id:
                continue
            related.append({
                "id": n["id"],
                "title": n["title"],
                "snippet": n["snippet"],
            })
            if len(related) >= limit:
                break
        return {
            "id": doc_id,
            "title": title,
            "explicit_relations": explicit,
            "related_documents": related,
        }

    conn.close()
    return {
        "id": doc_id,
        "title": title,
        "explicit_relations": explicit,
        "related_documents": related,
    }


def suggest_links(
    from_id: str,
    limit: int = 5,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Propose candidate typed relation links for human review.
    Human accepts via add_memory with explicit refs or editing YAML frontmatter.
    """
    rel = get_related(from_id, limit=limit, db_path=db_path)
    suggestions: List[Dict[str, Any]] = []
    existing_refs = set(rel.get("explicit_relations", {}).get("refs", []))
    backlink_ids = {b.get("id") for b in rel.get("explicit_relations", {}).get("backlinks", []) if isinstance(b, dict)}

    for doc in rel.get("related_documents", []):
        doc_id = doc.get("id")
        if not doc_id or doc_id == from_id or doc_id in existing_refs or doc_id in backlink_ids:
            continue
        suggestions.append({
            "from": from_id,
            "target": doc_id,
            "proposed_relation": "refs",
            "reason": f"Content overlap with '{doc.get('title')}'",
            "snippet": doc.get("snippet", ""),
        })

    return suggestions[:limit]
