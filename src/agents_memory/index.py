"""Disposable full-text search index and hybrid retrieval cache.

Source of truth is always markdown on disk.
The index lives in ~/.agents/memory/.index/ (gitignored) and is rebuildable in one command.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .store import (
    CHRONICLE_DIR,
    PROJECTS_MD,
    USER_MEMORY,
    Project,
    _read,
    parse_projects,
)

INDEX_DIR = USER_MEMORY / ".index"
FTS_DB = INDEX_DIR / "fts.sqlite"
EMBEDDINGS_DB = INDEX_DIR / "embeddings.sqlite"


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
        # FTS5 virtual table
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


def rebuild_index(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Crawl user memory + project memory trees and rebuild the FTS index."""
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

    # Write into SQLite
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

    conn.close()
    duration_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "indexed": len(records),
        "duration_ms": round(duration_ms, 2),
        "db_path": str(target_path),
    }


def search_hybrid(
    query: str,
    semantic: bool = False,
    project: str = "",
    limit: int = 20,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Hybrid FTS search across indexed markdown files."""
    if not query.strip():
        return []

    target_path = db_path or (INDEX_DIR / "fts.sqlite")
    # Auto-rebuild if db missing
    if not target_path.exists():
        rebuild_index(target_path)

    conn = get_db(target_path)
    # Sanitize FTS5 query terms (safe match)
    clean_terms = re.findall(r"\w+", query)
    if not clean_terms:
        return []

    # Match exact phrase or individual words
    fts_query = ' OR '.join(f'"{t}"' for t in clean_terms)

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
    params.append(max(1, limit))

    hits: List[Dict[str, Any]] = []
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        for row in cur.fetchall():
            doc_id, title, proj, fm_json, snip, rank = row
            fm = json.loads(fm_json) if fm_json else {}
            hits.append({
                "id": doc_id,
                "title": title,
                "project": proj,
                "snippet": snip,
                "rank": rank,
                "frontmatter": fm,
            })
    except sqlite3.OperationalError:
        # Fallback: rebuild and retry once
        rebuild_index(target_path)
    finally:
        conn.close()

    return hits


def get_related(
    memory_id: str,
    limit: int = 5,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Retrieve explicit relations (refs/supersedes/same_as) and content-related documents."""
    target_path = db_path or (INDEX_DIR / "fts.sqlite")
    if not target_path.exists():
        rebuild_index(target_path)

    conn = get_db(target_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, title, frontmatter_json, headings, content FROM documents WHERE id = ? OR id LIKE ?",
        (memory_id, f"%{memory_id}%"),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"id": memory_id, "explicit_relations": {}, "related_documents": []}

    doc_id, title, fm_json, headings, content = row
    fm = json.loads(fm_json) if fm_json else {}

    explicit = {
        "refs": fm.get("refs") or [],
        "supersedes": fm.get("supersedes") or "",
        "same_as": fm.get("same_as") or "",
        "at_project": fm.get("at_project") or "",
    }

    # Query for related docs using title terms
    clean_terms = [t for t in re.findall(r"\w+", title) if len(t) > 2]
    related: List[Dict[str, Any]] = []

    if clean_terms:
        fts_query = " OR ".join(f'"{t}"' for t in clean_terms[:5])
        cur.execute(
            """
            SELECT d.id, d.title, snippet(documents_fts, 3, '<b>', '</b>', '...', 12) as snip
            FROM documents_fts
            JOIN documents d ON documents_fts.id = d.id
            WHERE documents_fts MATCH ? AND d.id != ?
            ORDER BY rank LIMIT ?
            """,
            (fts_query, doc_id, limit),
        )
        for r in cur.fetchall():
            related.append({"id": r[0], "title": r[1], "snippet": r[2]})

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

    for doc in rel.get("related_documents", []):
        doc_id = doc.get("id")
        if not doc_id or doc_id == from_id or doc_id in existing_refs:
            continue
        suggestions.append({
            "from": from_id,
            "target": doc_id,
            "proposed_relation": "refs",
            "reason": f"Content overlap with '{doc.get('title')}'",
            "snippet": doc.get("snippet", ""),
        })

    return suggestions[:limit]
