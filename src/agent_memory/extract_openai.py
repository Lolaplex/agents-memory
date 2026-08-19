"""Filter ChatGPT export: durable user lines → staging/ingest/openai-export/captured.md."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
import zipfile
from pathlib import Path

from .ingest_common import keep_user_line, scrub, write_staging
from .ingest_config import discover_openai_exports, get_source, load_ingest
from .ingest_extractors import extract_openai, user_messages

keep_message = keep_user_line  # tests + legacy name


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


def extract_facts(root: Path) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for shard in sorted(root.glob("conversations-*.json")):
        data = json.loads(shard.read_text(encoding="utf-8"))
        for conv in data if isinstance(data, list) else []:
            if not isinstance(conv, dict):
                continue
            title = str(conv.get("title") or "(untitled)")
            for raw in user_messages(conv):
                text = scrub(raw)
                if not keep_message(title, text):
                    continue
                key = re.sub(r"\s+", " ", text.lower())
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"title": title, "text": text[:400], "shard": shard.name})
    return rows


def resolve_export(path: str) -> Path:
    if path:
        p = Path(path).expanduser()
        if p.exists():
            return p
        raise FileNotFoundError(path)
    found = discover_openai_exports()
    if not found:
        raise FileNotFoundError(
            "no ChatGPT export found — configure openai-export in ~/.agents/memory/ingest.json"
        )
    return found[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Filter ChatGPT export to ingest staging")
    parser.add_argument("--zip", help="export zip or unpacked folder")
    parser.add_argument("--out", help="legacy: write JSON instead of markdown staging")
    args = parser.parse_args(argv)

    if args.out:
        src = resolve_export(args.zip or "")
        root = unzip_export(src)
        rows = extract_facts(root)
        out = Path(args.out)
        out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"source {src}")
        print(f"kept {len(rows)} user statements")
        print(f"staging {out}")
        return 0

    cfg = load_ingest()
    src = get_source("openai-export", cfg) or {
        "id": "openai-export",
        "kind": "openai-export",
        "label": "ChatGPT export",
        "paths": [str(resolve_export(args.zip or ""))],
        "extract": True,
    }
    if args.zip:
        src = dict(src)
        src["paths"] = [str(Path(args.zip).expanduser())]
    lines = extract_openai(src)
    label = str(src.get("label") or "ChatGPT export")
    path = write_staging("openai-export", label, lines)
    print(f"kept {len(lines)} user statements")
    print(f"staging {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
