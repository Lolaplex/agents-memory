"""Shared ingest filters, staging paths, and reversible state."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .store import USER_MEMORY, _append_bullet, _read, _write

HOW_TO = re.compile(
    r"^(how (can|do|to|would)|write (a|me|the)|fix |create (a|an) |"
    r"implement |help me|can you|could you|please |instead of |"
    r"why (is|does|do|won't)|what is the (best|correct) )",
    re.I,
)
PII = re.compile(
    r"("
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    r"|(\+?\d[\d\s().-]{8,}\d)"
    r"|sk-[A-Za-z0-9]{10,}"
    r"|github_pat_[A-Za-z0-9_]+"
    r"|ghp_[A-Za-z0-9]+"
    r"|xox[baprs]-[A-Za-z0-9-]+"
    r")",
    re.I,
)
CODEISH = re.compile(
    r"^\s*(def |class |import |from |function |const |let |var |#include )",
    re.M,
)


def staging_path(source_id: str) -> Path:
    return USER_MEMORY / "staging" / "ingest" / source_id / "captured.md"


def ingest_state_path() -> Path:
    return USER_MEMORY / "ingest" / "state.json"


def chats_index_path() -> Path:
    return USER_MEMORY / "chats-index.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scrub(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = PII.sub("[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def keep_user_line(title: str, text: str) -> bool:
    if not text or len(text) < 12:
        return False
    if text.count("[redacted]") and len(text) < 40:
        return False
    if len(text) > 600:
        return False
    if CODEISH.search(text) and len(text) > 120:
        return False
    if HOW_TO.search(text):
        return False
    return True


def clip(text: str, n: int = 120) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[: n - 1] + "…" if len(text) > n else text


def entity_path(source_id: str) -> Path:
    return USER_MEMORY / "entities" / f"chat-source-{source_id}.md"


def staging_header(source_id: str, label: str) -> str:
    return (
        f"# Staging (ingest: {source_id})\n\n"
        f"Source: {label}. Not memory. "
        "Distill each bullet with MCP `add_memory(kind=..., name=...)`, then delete here.\n\n"
        "## Captured\n\n"
    )


def load_state() -> dict:
    path = ingest_state_path()
    if not path.is_file():
        return {"sources": {}}
    try:
        data = json.loads(_read(path))
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {"sources": {}}


def save_state(state: dict) -> None:
    path = ingest_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, json.dumps(state, indent=2, ensure_ascii=False))


def record_phase(source_id: str, phase: str, **fields: Any) -> None:
    state = load_state()
    entry = state.setdefault("sources", {}).setdefault(source_id, {})
    entry[f"last_{phase}"] = utc_now()
    entry.update(fields)
    save_state(state)


def write_staging(source_id: str, label: str, lines: List[str]) -> Path:
    path = staging_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = staging_header(source_id, label)
    body = header
    for line in lines:
        body += f"- {line}\n"
    if body == header:
        body += "- (none yet)\n"
    _write(path, body)
    return path


def append_staging_bullets(source_id: str, label: str, lines: List[str]) -> Path:
    path = staging_path(source_id)
    if not path.exists():
        return write_staging(source_id, label, lines)
    for line in lines:
        if line.strip():
            _append_bullet(path, line.strip())
    return path


def write_entity_card(source: dict, paths: List[Path], catalog_count: int) -> Path:
    sid = str(source["id"])
    label = str(source.get("label") or sid)
    kind = str(source.get("kind") or "")
    path_lines = "\n".join(f"- `{p}`" for p in paths[:8]) or "- (not found on disk)"
    body = (
        f"---\n"
        f"id: {sid}\n"
        f"kind: {kind}\n"
        f"role: chat-source\n"
        f"---\n\n"
        f"# {label}\n\n"
        f"**Kind:** `{kind}`  \n"
        f"**Catalog count:** {catalog_count}  \n"
        f"**Paths:**\n{path_lines}\n\n"
        f"Bodies stay on disk. Titles in `chats-index.md`. "
        f"Extract: `python -m agents_memory ingest extract --source {sid}` -> "
        f"`staging/ingest/{sid}/captured.md`. "
        f"Distill with MCP `add_memory`, then clear staging.\n"
    )
    dest = entity_path(sid)
    _write(dest, body)
    return dest


def format_bullet(title: str, text: str, origin: str = "") -> str:
    title = clip(title, 80)
    text = clip(text, 280)
    if origin:
        return f"[{title} @ {origin}] {text}"
    return f"[{title}] {text}"
