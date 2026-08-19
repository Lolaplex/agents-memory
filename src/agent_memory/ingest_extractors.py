"""Extract phase: filter durable user lines into staging/ingest/<source-id>/captured.md."""
from __future__ import annotations

import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Dict, List

from .ingest_catalog import brain_rows
from .ingest_common import (
    USER_MEMORY,
    format_bullet,
    keep_user_line,
    record_phase,
    scrub,
    write_staging,
)
from .ingest_config import get_source, list_sources, load_ingest, resolve_source_roots


def _parts_text(content: object) -> str:
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts") or []
    bits: list[str] = []
    for part in parts:
        if isinstance(part, str):
            bits.append(part)
        elif isinstance(part, dict):
            bits.append(str(part.get("text") or ""))
    return "\n".join(bits)


def user_messages(conv: dict) -> List[str]:
    out: List[str] = []
    mapping = conv.get("mapping") or {}
    for node in mapping.values():
        if not isinstance(node, dict):
            continue
        msg = node.get("message") or {}
        if not isinstance(msg, dict):
            continue
        if (msg.get("author") or {}).get("role") != "user":
            continue
        text = _parts_text(msg.get("content"))
        if text.strip():
            out.append(text)
    return out


def unzip_export(src: Path, dest: Path | None = None) -> Path:
    dest = dest or Path(tempfile.gettempdir()) / "agent-memory-openai-export"
    dest.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".zip" and src.is_file():
        with zipfile.ZipFile(src) as zf:
            zf.extractall(dest)
        return dest
    if src.is_dir():
        return src
    raise FileNotFoundError(f"not a ChatGPT export zip or folder: {src}")


def _dedupe_bullets(lines: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for line in lines:
        key = re.sub(r"\s+", " ", line.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def extract_openai(src: dict) -> List[str]:
    lines: List[str] = []
    for root in resolve_source_roots(src):
        export = root
        if root.suffix.lower() == ".zip":
            export = unzip_export(root)
        elif not any(root.glob("conversations-*.json")) and root.is_dir():
            continue
        for shard in sorted(export.glob("conversations-*.json")):
            data = json.loads(shard.read_text(encoding="utf-8"))
            for conv in data if isinstance(data, list) else []:
                if not isinstance(conv, dict):
                    continue
                title = str(conv.get("title") or "(untitled)")
                for raw in user_messages(conv):
                    text = scrub(raw)
                    if not keep_user_line(title, text):
                        continue
                    lines.append(format_bullet(title, text[:400], shard.name))
    return _dedupe_bullets(lines)


def _jsonl_user_lines(path: Path, parse_user) -> List[tuple[str, str]]:
    rows: List[tuple[str, str]] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                obj = json.loads(line)
                title, text = parse_user(obj)
                if text:
                    rows.append((title, text))
    except (OSError, json.JSONDecodeError):
        pass
    return rows


def extract_agent_jsonl(src: dict) -> List[str]:
    lines: List[str] = []
    for root in resolve_source_roots(src):
        tdir = root / "agent-transcripts" if (root / "agent-transcripts").is_dir() else root
        for path in sorted(tdir.glob("*/*.jsonl")):
            if "subagents" in path.parts:
                continue
            title = path.parent.name[:8]

            def parse(obj, _title=title, _path=path):
                if obj.get("role") != "user":
                    return _title, ""
                msg = obj.get("message") or {}
                content = msg.get("content") or []
                texts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        texts.append(part.get("text") or "")
                blob = "\n".join(texts)
                m = re.search(r"<user_query>\s*(.*?)\s*</user_query>", blob, re.S)
                if m:
                    return m.group(1)[:80], m.group(1)
                if blob.strip():
                    return blob[:80], blob
                return _title, ""

            for t, raw in _jsonl_user_lines(path, parse):
                text = scrub(raw)
                if keep_user_line(t, text):
                    lines.append(format_bullet(t, text[:400], str(path)))
    return _dedupe_bullets(lines)


def extract_copilot_jsonl(src: dict) -> List[str]:
    lines: List[str] = []
    for root in resolve_source_roots(src):
        if not root.is_dir():
            continue
        if root.name == "chatSessions":
            sessions = sorted(root.glob("*.jsonl"))
        elif (root / "chatSessions").is_dir():
            sessions = sorted((root / "chatSessions").glob("*.jsonl"))
        else:
            sessions = sorted(root.glob("*/chatSessions/*.jsonl"))
            if not sessions:
                sessions = sorted(root.rglob("*.jsonl"))

        for session in sessions:
            title = session.stem[:12]

            def parse(obj, _session=session):
                nonlocal title
                if obj.get("kind") == 1 and obj.get("k") == ["customTitle"] and obj.get("v"):
                    title = str(obj["v"])
                    return title, ""
                # Parse v -> inputText or requests
                v = obj.get("v")
                if isinstance(v, dict):
                    input_text = v.get("inputText") or ""
                    if input_text.strip():
                        return title, input_text
                    for req in v.get("requests") or []:
                        if isinstance(req, dict):
                            msg_text = req.get("message", {}).get("text") or req.get("inputText") or ""
                            if msg_text.strip():
                                return title, msg_text
                # Fallback standard role
                role = obj.get("role") or (obj.get("message") or {}).get("role")
                if role == "user":
                    msg = obj.get("message") or obj
                    content = msg.get("content")
                    blob = content if isinstance(content, str) else ""
                    if isinstance(content, list):
                        blob = " ".join(
                            p.get("text") or ""
                            for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    return title, blob
                return title, ""

            for t, raw in _jsonl_user_lines(session, parse):
                text = scrub(raw)
                if keep_user_line(t, text):
                    lines.append(format_bullet(t, text[:400], str(session)))
    return _dedupe_bullets(lines)


def extract_claude_jsonl(src: dict) -> List[str]:
    lines: List[str] = []
    for root in resolve_source_roots(src):
        for path in sorted(root.rglob("*.jsonl")):

            def parse(obj, _path=path):
                role = obj.get("role") or (obj.get("message") or {}).get("role")
                if role != "user":
                    return _path.stem, ""
                msg = obj.get("message") or obj
                content = msg.get("content")
                blob = content if isinstance(content, str) else ""
                if isinstance(content, list):
                    blob = " ".join(
                        p.get("text") or ""
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                return _path.stem, blob

            for t, raw in _jsonl_user_lines(path, parse):
                text = scrub(raw)
                if keep_user_line(t, text):
                    lines.append(format_bullet(t, text[:400], str(path)))
    return _dedupe_bullets(lines)


def extract_antigravity_brain(src: dict) -> List[str]:
    lines: List[str] = []
    label = str(src.get("label") or src.get("id"))
    for root in resolve_source_roots(src):
        for _label, title, brain_path in brain_rows(label, root):
            brain = Path(brain_path)
            for name in ("task.md", "walkthrough.md", "implementation_plan.md"):
                md = brain / name
                if not md.exists():
                    continue
                for line in md.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("- ") or line.startswith("* "):
                        text = scrub(line[2:])
                        if keep_user_line(title, text):
                            lines.append(format_bullet(title, text[:400], name))
                break
    return _dedupe_bullets(lines)


def extract_pi_jsonl(src: dict) -> List[str]:
    lines: List[str] = []
    for root in resolve_source_roots(src):
        for path in sorted(root.rglob("*.jsonl")):

            def parse(obj, _path=path):
                if obj.get("type") != "message":
                    return _path.stem, ""
                msg = obj.get("message") or {}
                if msg.get("role") != "user":
                    return _path.stem, ""
                parts = msg.get("content") or []
                blob = " ".join(
                    p.get("text") or ""
                    for p in parts
                    if isinstance(p, dict) and p.get("type") == "text"
                )
                return _path.stem, blob

            for t, raw in _jsonl_user_lines(path, parse):
                text = scrub(raw)
                if keep_user_line(t, text):
                    lines.append(format_bullet(t, text[:400], str(path)))
    return _dedupe_bullets(lines)


EXTRACTORS: Dict[str, Callable[[dict], List[str]]] = {
    "openai-export": extract_openai,
    "agent-jsonl": extract_agent_jsonl,
    "copilot-jsonl": extract_copilot_jsonl,
    "claude-jsonl": extract_claude_jsonl,
    "antigravity-brain": extract_antigravity_brain,
    "pi-jsonl": extract_pi_jsonl,
}


def extract_source(src: dict) -> tuple[int, Path]:
    sid = str(src["id"])
    label = str(src.get("label") or sid)
    kind = str(src.get("kind") or "")
    if not src.get("extract", True):
        return 0, write_staging(sid, label, [])
    handler = EXTRACTORS.get(kind)
    if not handler:
        raise ValueError(f"no extractor for kind={kind!r} (source {sid})")
    lines = handler(src)
    path = write_staging(sid, label, lines)
    record_phase(
        sid,
        "extract",
        extract_count=len(lines),
        staging=str(path.relative_to(USER_MEMORY)).replace("\\", "/"),
    )
    return len(lines), path


def run_extract(source_id: str = "", cfg: dict | None = None) -> dict:
    cfg = cfg or load_ingest()
    results: dict = {"sources": {}}
    targets = list_sources(cfg)
    if source_id:
        src = get_source(source_id, cfg)
        if not src:
            raise ValueError(f"unknown source id: {source_id}")
        targets = [src]
    for src in targets:
        if not src.get("extract", True):
            continue
        count, path = extract_source(src)
        results["sources"][str(src["id"])] = {"count": count, "staging": str(path)}
    return results
