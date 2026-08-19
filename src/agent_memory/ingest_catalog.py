"""Catalog phase: chats-index.md + entity reference cards (bodies stay on disk)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from .ingest_common import chats_index_path, clip, record_phase, write_entity_card
from .ingest_config import (
    discover_openai_exports,
    get_source,
    list_sources,
    load_ingest,
    resolve_source_roots,
)
from .store import USER_MEMORY, ensure_memory_layout, _write

Row = Tuple[str, str, str]


def _ts(value) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, (int, float)):
            if value > 1e12:
                value = value / 1000.0
            return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")
        return str(value)[:10]
    except (OSError, OverflowError, ValueError, TypeError):
        return ""


def _md_cell(text: str) -> str:
    return clip(text).replace("|", "\\|")


def openai_rows(root: Path) -> List[Row]:
    rows: List[Row] = []
    if not root.is_dir():
        return rows
    for shard in sorted(root.glob("conversations-*.json")):
        data = json.loads(shard.read_text(encoding="utf-8"))
        for conv in data if isinstance(data, list) else []:
            if not isinstance(conv, dict):
                continue
            title = conv.get("title") or "(untitled)"
            created = _ts(conv.get("create_time"))
            rows.append((created, title, shard.name))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def agent_transcript_rows(root: Path) -> List[Row]:
    rows: List[Row] = []
    if not root.is_dir():
        return rows
    tdir = root / "agent-transcripts" if (root / "agent-transcripts").is_dir() else root
    workspace = root.name
    if workspace.startswith("c-Users-"):
        parts = workspace.split("-")
        if len(parts) > 3:
            workspace = "/".join(parts[3:])
    for path in sorted(tdir.glob("*/*.jsonl")):
        if "subagents" in path.parts:
            continue
        title = path.parent.name[:8]
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    obj = json.loads(line)
                    if obj.get("role") != "user":
                        continue
                    msg = obj.get("message") or {}
                    content = msg.get("content") or []
                    texts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            texts.append(part.get("text") or "")
                    blob = "\n".join(texts)
                    m = re.search(r"<user_query>\s*(.*?)\s*</user_query>", blob, re.S)
                    if m:
                        title = clip(m.group(1), 90)
                    elif blob.strip():
                        title = clip(blob, 90)
                    break
        except (OSError, json.JSONDecodeError):
            pass
        rows.append((workspace, title, str(path)))
    return rows


def copilot_rows(root: Path) -> List[Row]:
    rows: List[Row] = []
    for session in sorted(root.glob("*/chatSessions/*.jsonl")):
        folder = "?"
        wj = session.parents[1] / "workspace.json"
        if wj.exists():
            try:
                raw = json.loads(wj.read_text(encoding="utf-8")).get("folder") or "?"
                folder = raw.replace("file:///", "").replace("%3A", ":")
            except json.JSONDecodeError:
                pass
        title = session.stem[:8]
        rows.append((folder, title, str(session)))
    return rows


def claude_rows(root: Path) -> List[Row]:
    rows: List[Row] = []
    if not root.is_dir():
        return rows
    for path in sorted(root.rglob("*.jsonl")):
        project = path.parent.name
        title = path.stem[:12]
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    obj = json.loads(line)
                    role = obj.get("role") or (obj.get("message") or {}).get("role")
                    if role != "user":
                        continue
                    msg = obj.get("message") or obj
                    content = msg.get("content")
                    blob = ""
                    if isinstance(content, str):
                        blob = content
                    elif isinstance(content, list):
                        texts = [
                            p.get("text") or ""
                            for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        ]
                        blob = " ".join(texts)
                    if blob.strip():
                        title = clip(blob, 90)
                        break
        except (OSError, json.JSONDecodeError):
            pass
        rows.append((project, title, str(path)))
    return rows


def brain_rows(label: str, root: Path) -> List[Row]:
    rows: List[Row] = []
    if not root.is_dir():
        return rows
    for brain in sorted(root.iterdir()):
        if not brain.is_dir() or brain.name.startswith("."):
            continue
        title = brain.name[:8]
        for name in ("task.md", "walkthrough.md", "implementation_plan.md"):
            path = brain / name
            if path.exists():
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line.startswith("# "):
                        title = clip(line[2:], 90)
                        break
                break
        rows.append((label, title, str(brain)))
    return rows


def pi_rows(root: Path) -> List[Row]:
    rows: List[Row] = []
    for path in sorted(root.rglob("*.jsonl")):
        cwd = ""
        title = path.stem[:19]
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    obj = json.loads(line)
                    if obj.get("type") == "session":
                        cwd = obj.get("cwd") or ""
                    if obj.get("type") == "message":
                        msg = obj.get("message") or {}
                        if msg.get("role") != "user":
                            continue
                        parts = msg.get("content") or []
                        texts = [
                            p.get("text") or ""
                            for p in parts
                            if isinstance(p, dict) and p.get("type") == "text"
                        ]
                        blob = " ".join(texts).strip()
                        if blob:
                            title = clip(blob, 90)
                            break
        except (OSError, json.JSONDecodeError):
            pass
        rows.append((cwd, title, str(path)))
    return rows


def collect_source_rows(src: dict) -> List[Row]:
    kind = src.get("kind") or ""
    label = str(src.get("label") or src.get("id") or kind)
    rows: List[Row] = []
    for path in resolve_source_roots(src):
        if kind == "agent-jsonl":
            rows.extend(agent_transcript_rows(path))
        elif kind == "copilot-jsonl":
            rows.extend(copilot_rows(path))
        elif kind == "claude-jsonl":
            rows.extend(claude_rows(path))
        elif kind == "antigravity-brain":
            rows.extend(brain_rows(label, path))
        elif kind == "pi-jsonl":
            rows.extend(pi_rows(path))
    return rows


def render_table(headers: List[str], rows: List[Tuple]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(str(c)) for c in row) + " |")
    return "\n".join(lines)


def catalog_source(src: dict) -> int:
    sid = str(src["id"])
    if not src.get("catalog", True):
        return 0
    roots = resolve_source_roots(src)
    if src.get("kind") == "openai-export":
        count = sum(len(openai_rows(r)) for r in roots)
    else:
        count = len(collect_source_rows(src))
    write_entity_card(src, roots, count)
    record_phase(sid, "catalog", catalog_count=count, paths=[str(p) for p in roots[:8]])
    return count


def build_index(cfg: dict | None = None) -> Path:
    cfg = cfg or load_ingest()
    exports = discover_openai_exports(cfg)
    openai: List[Row] = []
    for export_dir in exports:
        openai.extend(openai_rows(export_dir))

    source_tables: list[tuple[str, List[Row]]] = []
    map_rows: list[tuple[str, str, str, str]] = []

    openai_src = get_source("openai-export", cfg)
    if openai_src and openai_src.get("catalog", True):
        catalog_source(openai_src)
        map_rows.append(
            (
                str(openai_src.get("label") or "ChatGPT export"),
                str(exports[0]) if exports else "(configure ingest.json)",
                str(len(openai)),
                "openai-export",
            )
        )

    for src in list_sources(cfg):
        if (src.get("kind") or "") == "openai-export":
            continue
        if not src.get("catalog", True):
            continue
        rows = collect_source_rows(src)
        catalog_source(src)
        source_tables.append((str(src.get("label") or src.get("id")), rows))
        roots = resolve_source_roots(src)
        map_rows.append(
            (
                str(src.get("label") or src.get("id")),
                ", ".join(str(p) for p in roots[:2]) or "(not found)",
                str(len(rows)),
                str(src.get("kind") or ""),
            )
        )

    parts = [
        "# Chat index",
        "",
        "Catalog of **where chats already live**. Not a transcript dump.",
        "Configure sources in `~/.agents/memory/ingest.json`. "
        "Run `python -m agent_memory ingest catalog` to refresh.",
        "",
        "## Store map",
        "",
        render_table(["source", "path", "count", "kind"], map_rows),
        "",
    ]
    if openai:
        parts.extend(["## ChatGPT export", "", render_table(["date", "title", "shard"], openai), ""])
    for title, rows in source_tables:
        if not rows:
            continue
        parts.extend([f"## {title}", "", render_table(["workspace", "title hint", "path"], rows), ""])

    index = chats_index_path()
    USER_MEMORY.mkdir(parents=True, exist_ok=True)
    _write(index, "\n".join(parts) + "\n")
    return index


def run_catalog(cfg: dict | None = None) -> dict:
    ensure_memory_layout()
    cfg = cfg or load_ingest()
    path = build_index(cfg)
    return {"chats_index": str(path), "sources": len(list_sources(cfg))}
