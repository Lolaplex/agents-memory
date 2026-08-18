"""Unzip the ChatGPT export and keep durable user facts only.

Drops: assistant text, PII, code dumps, one-shot how-tos, user.json.
Writes a staging JSON next to the unzip dir — not into ~/.agents/memory.
"""
from __future__ import annotations

import json
import re
import tempfile
import zipfile
from pathlib import Path

HOME = Path.home()
DOWNLOADS = HOME / "Downloads"
EXPORT_STEM = (
    "e0bd92032af87b3465c43bde842d3c52538fb6983cc2815fb62ad9ce4d6d7a59"
    "-2026-07-05-01-59-40-118659443e0948c3abacf001a505be16"
)

SIGNAL = re.compile(
    r"\b("
    r"isar|hdisar|sari|rsq|iras|koru|koruc|koru_pump|taint|"
    r"living.?software|quine|lean ?4|gscatter|graswald|synology|reolink|"
    r"clustta|nagato|kitsu|plex-shell|create.?with.?clint|\bcwc\b|"
    r"homelab|\bdsm\b|openusd|openfx|hydra|ocio|agx|pixdesigner|cyberboot|"
    r"git-updater|agent-memory|medushu|orisha|lolaplex|"
    r"vendor\.lock|records as|only primitive|note on plex"
    r")\b",
    re.I,
)
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


def export_zip() -> Path:
    return DOWNLOADS / f"{EXPORT_STEM}.zip"


def unzip_export(dest: Path | None = None) -> Path:
    dest = dest or Path(tempfile.gettempdir()) / "agent-memory-openai-export"
    dest.mkdir(parents=True, exist_ok=True)
    zpath = export_zip()
    if zpath.is_file():
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(dest)
        return dest
    folder = DOWNLOADS / EXPORT_STEM
    if folder.is_dir():
        return folder
    raise FileNotFoundError(f"no ChatGPT export zip or folder for {EXPORT_STEM}")


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


def user_messages(conv: dict) -> list[str]:
    out: list[str] = []
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


def scrub(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = PII.sub("[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def keep_message(title: str, text: str) -> bool:
    if not text or len(text) < 12:
        return False
    if text.count("[redacted]") and len(text) < 40:
        return False
    if len(text) > 600:
        return False
    if CODEISH.search(text) and not SIGNAL.search(title + " " + text):
        return False
    blob = f"{title} {text}"
    if not SIGNAL.search(blob):
        return False
    if HOW_TO.search(text) and not SIGNAL.search(title):
        return False
    return True


def bucket_for(title: str, text: str) -> str:
    blob = f"{title} {text}".lower()
    rules = (
        ("isar", r"isar|hdisar|sari|rsq|iras|uniqueness|dirac|spacetime"),
        ("koru", r"koru|koruc|taint|orisha|medushu"),
        ("living-software", r"living.?software|quine|records as|lean 4"),
        ("gscatter", r"gscatter|graswald"),
        ("cwc", r"create.?with.?clint|\bcwc\b|nova |discord activity"),
        ("homelab", r"synology|reolink|homelab|\bdsm\b"),
        ("plex", r"plex-shell|plexes|resolver"),
        ("vfx", r"openusd|hydra|houdini|blender|ocio|agx|clustta|nagato"),
        ("identity", r"who am i|karriere|i am |i work"),
    )
    for name, pat in rules:
        if re.search(pat, blob):
            return name
    return "other"


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
                rows.append(
                    {
                        "title": title,
                        "bucket": bucket_for(title, text),
                        "text": text[:400],
                        "shard": shard.name,
                    }
                )
    return rows


def main() -> None:
    root = unzip_export()
    rows = extract_facts(root)
    out = root / "filtered-facts.json"
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    by = {}
    for row in rows:
        by.setdefault(row["bucket"], 0)
        by[row["bucket"]] += 1
    print(f"unzipped {root}")
    print(f"kept {len(rows)} user statements; dropped the rest")
    print("buckets", json.dumps(by, sort_keys=True))
    print(f"staging {out}")


if __name__ == "__main__":
    main()
