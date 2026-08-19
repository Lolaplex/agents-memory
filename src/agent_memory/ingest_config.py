"""Normalize ingest.json and discover source paths."""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from .store import EXAMPLES, _read

INGEST_EXAMPLE = EXAMPLES / "ingest.example.json"


def _expand(path: str) -> Path:
    raw = path.replace("%APPDATA%", os.environ.get("APPDATA") or "")
    return Path(os.path.expandvars(os.path.expanduser(raw)))


def _expand_glob(pattern: str) -> List[Path]:
    pat = str(pattern).replace("%APPDATA%", os.environ.get("APPDATA") or "")
    pat = os.path.expanduser(pat)
    out: List[Path] = []
    for hit in glob.glob(pat):
        p = Path(hit)
        if p.exists():
            out.append(p)
    return out


def default_ingest() -> dict:
    if INGEST_EXAMPLE.is_file():
        return normalize_ingest(json.loads(_read(INGEST_EXAMPLE)))
    return {"version": 1, "sources": []}


def ingest_defaults(raw: dict) -> dict:
    return {
        "extract_max_bullets": max(0, int(raw.get("extract_max_bullets") or 100)),
        "staging_nag_threshold": max(0, int(raw.get("staging_nag_threshold") or 50)),
    }


def extract_max_bullets(cfg: dict, src: dict) -> int:
    if src.get("extract_max_bullets") is not None:
        return max(0, int(src["extract_max_bullets"]))
    return max(0, int(cfg.get("extract_max_bullets") or 100))


def _migrate_source(src: dict) -> dict:
    """Rename legacy generic ids to product-specific ones."""
    src = dict(src)
    if src.get("id") in ("agent-transcripts", "cursor-transcripts"):
        src["id"] = "cursor"
        label = str(src.get("label") or "")
        if not label or label == "your Agent transcripts":
            src["label"] = "Cursor"
    return src


def normalize_ingest(raw: dict) -> dict:
    """Accept legacy split keys or unified sources list."""
    defaults = ingest_defaults(raw)
    if raw.get("sources"):
        sources = [_migrate_source(s) for s in raw["sources"]]
        return {"version": int(raw.get("version") or 1), "sources": sources, **defaults}
    sources: List[dict] = []
    for item in raw.get("openai_export_dirs") or []:
        sources.append(
            {
                "id": "openai-export",
                "kind": "openai-export",
                "label": "Open AI — GDPR export",
                "paths": [str(item)],
                "catalog": True,
                "extract": True,
            }
        )
    globs = raw.get("openai_export_globs") or []
    if globs and not any(s.get("id") == "openai-export" for s in sources):
        sources.append(
            {
                "id": "openai-export",
                "kind": "openai-export",
                "label": "Open AI — GDPR export",
                "paths": [],
                "globs": globs,
                "catalog": True,
                "extract": True,
            }
        )
    elif globs:
        for s in sources:
            if s.get("id") == "openai-export":
                s.setdefault("globs", globs)
    for src in raw.get("chat_sources") or []:
        if isinstance(src, dict) and src.get("id"):
            src.setdefault("catalog", True)
            src.setdefault("extract", True)
            sources.append(_migrate_source(src))
    sources = [_migrate_source(s) for s in sources]
    return {"version": 1, "sources": sources, **defaults}


INGEST_SOURCE_ID_ALIASES: Dict[str, str] = {
    "agent-transcripts": "cursor",
    "cursor-transcripts": "cursor",
}


def migrate_ingest_legacy_ids() -> List[str]:
    """Rename on-disk ingest artifacts when source ids change (called from sync)."""
    from .store import USER_MEMORY, _read, _write

    notes: List[str] = []
    staging_base = USER_MEMORY / "staging" / "ingest"
    for old, new in INGEST_SOURCE_ID_ALIASES.items():
        if old == new:
            continue
        old_dir = staging_base / old
        new_dir = staging_base / new
        if old_dir.is_dir() and not new_dir.exists():
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            old_dir.rename(new_dir)
            notes.append(f"migrated staging/ingest/{old} -> {new}")

    state_path = USER_MEMORY / "ingest" / "state.json"
    if state_path.is_file():
        try:
            state = json.loads(_read(state_path))
        except json.JSONDecodeError:
            state = {}
        sources = state.setdefault("sources", {})
        for old, new in INGEST_SOURCE_ID_ALIASES.items():
            if old == new or old not in sources:
                continue
            entry = sources.pop(old)
            staging = str(entry.get("staging") or "")
            if staging:
                entry["staging"] = staging.replace(f"/{old}/", f"/{new}/").replace(
                    f"\\{old}\\", f"\\{new}\\"
                )
            if new in sources:
                for key, value in entry.items():
                    sources[new].setdefault(key, value)
            else:
                sources[new] = entry
            notes.append(f"migrated ingest state {old} -> {new}")
        _write(state_path, json.dumps(state, indent=2) + "\n")

    entities = USER_MEMORY / "entities"
    for old, new in INGEST_SOURCE_ID_ALIASES.items():
        if old == new:
            continue
        old_card = entities / f"chat-source-{old}.md"
        new_card = entities / f"chat-source-{new}.md"
        if old_card.is_file() and not new_card.is_file():
            new_card.parent.mkdir(parents=True, exist_ok=True)
            old_card.rename(new_card)
            notes.append(f"migrated entity chat-source-{old} -> chat-source-{new}")

    return notes


def load_ingest(path: Path | None = None) -> dict:
    from .store import USER_MEMORY

    ingest_json = path or (USER_MEMORY / "ingest.json")
    if ingest_json.is_file():
        try:
            return normalize_ingest(json.loads(_read(ingest_json)))
        except json.JSONDecodeError:
            pass
    return default_ingest()


def list_sources(cfg: dict | None = None) -> List[dict]:
    cfg = cfg or load_ingest()
    return [s for s in cfg.get("sources") or [] if isinstance(s, dict) and s.get("id")]


def get_source(source_id: str, cfg: dict | None = None) -> dict | None:
    for src in list_sources(cfg):
        if src.get("id") == source_id:
            return src
    return None


def chat_sources(cfg: dict | None = None) -> List[dict]:
    """Non-OpenAI sources that participate in chats-index (legacy name)."""
    return [
        s
        for s in list_sources(cfg)
        if s.get("catalog", True) and (s.get("kind") or "") != "openai-export"
    ]


def discover_openai_exports(cfg: dict | None = None) -> List[Path]:
    src = get_source("openai-export", cfg)
    if not src:
        return []
    return resolve_source_roots(src)


def resolve_source_paths(src: dict) -> List[Path]:
    return resolve_source_roots(src)


def resolve_source_roots(src: dict) -> List[Path]:
    roots: List[Path] = []
    seen: set[str] = set()
    for item in src.get("paths") or []:
        raw = str(item)
        if "*" in raw:
            for hit in _expand_glob(raw):
                key = str(hit.resolve())
                if key not in seen:
                    seen.add(key)
                    roots.append(hit)
        else:
            p = _expand(raw)
            if p.exists():
                key = str(p.resolve())
                if key not in seen:
                    seen.add(key)
                    roots.append(p)
    for pattern in src.get("globs") or []:
        for hit in _expand_glob(str(pattern)):
            key = str(hit.resolve())
            if key in seen:
                continue
            kind = src.get("kind") or ""
            if kind == "openai-export":
                if hit.is_dir() and any(hit.glob("conversations-*.json")):
                    seen.add(key)
                    roots.append(hit)
                elif hit.is_file() and hit.suffix.lower() == ".zip":
                    seen.add(key)
                    roots.append(hit)
                continue
            if not hit.is_dir():
                continue
            seen.add(key)
            roots.append(hit)
    return roots
