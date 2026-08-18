"""Build memory/chats-index.md from local chat stores. Titles + paths only."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from store import USER_MEMORY, ensure_memory_layout

HOME = Path.home()
ensure_memory_layout()
OUT = USER_MEMORY / "chats-index.md"
OPENAI_EXPORT = HOME / (
    "Downloads/"
    "e0bd92032af87b3465c43bde842d3c52538fb6983cc2815fb62ad9ce4d6d7a59"
    "-2026-07-05-01-59-40-118659443e0948c3abacf001a505be16"
)


def _clip(text: str, n: int = 120) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[: n - 1] + "…" if len(text) > n else text


def _md_cell(text: str) -> str:
    return _clip(text).replace("|", "\\|")


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


def openai_rows() -> list[tuple[str, str, str]]:
    rows = []
    if not OPENAI_EXPORT.is_dir():
        return rows
    for shard in sorted(OPENAI_EXPORT.glob("conversations-*.json")):
        data = json.loads(shard.read_text(encoding="utf-8"))
        for conv in data if isinstance(data, list) else []:
            if not isinstance(conv, dict):
                continue
            title = conv.get("title") or "(untitled)"
            created = _ts(conv.get("create_time"))
            rows.append((created, title, shard.name))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def cursor_rows() -> list[tuple[str, str, str]]:
    rows = []
    root = HOME / ".cursor" / "projects"
    if not root.is_dir():
        return rows
    for proj in sorted(root.iterdir()):
        tdir = proj / "agent-transcripts"
        if not tdir.is_dir():
            continue
        workspace = proj.name.replace("c-Users-fabi0-", "").replace("-", "/")
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
                            title = _clip(m.group(1), 90)
                        elif blob.strip():
                            title = _clip(blob, 90)
                        break
            except (OSError, json.JSONDecodeError):
                pass
            rows.append((workspace, title, str(path)))
    return rows


def vscode_rows() -> list[tuple[str, str, str]]:
    rows = []
    root = HOME / "AppData/Roaming/Code/User/workspaceStorage"
    if not root.is_dir():
        return rows
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
        try:
            with session.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    obj = json.loads(line)
                    v = obj.get("v")
                    if isinstance(v, dict):
                        text = (v.get("inputState") or {}).get("inputText") or ""
                        if text.strip():
                            title = _clip(text, 90)
                            break
                    if obj.get("kind") == 1 and "requests" in (obj.get("k") or []):
                        reqs = v if isinstance(v, list) else []
                        for req in reqs:
                            if isinstance(req, dict):
                                msg = req.get("message") or {}
                                t = msg.get("text") if isinstance(msg, dict) else None
                                if t:
                                    title = _clip(str(t), 90)
                                    break
        except (OSError, json.JSONDecodeError):
            pass
        rows.append((folder, title, str(session)))
    return rows


def antigravity_rows() -> list[tuple[str, str, str]]:
    rows = []
    for label, root in (
        ("antigravity", HOME / ".gemini/antigravity/brain"),
        ("antigravity-ide", HOME / ".gemini/antigravity-ide/brain"),
    ):
        if not root.is_dir():
            continue
        for brain in sorted(root.iterdir()):
            if not brain.is_dir() or brain.name.startswith("."):
                continue
            title = brain.name[:8]
            for name in ("task.md", "walkthrough.md", "implementation_plan.md"):
                path = brain / name
                if not path.exists():
                    continue
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line.startswith("# "):
                        title = _clip(line[2:], 90)
                        break
                break
            rows.append((label, title, str(brain)))
    return rows


def pi_rows() -> list[tuple[str, str, str]]:
    rows = []
    root = HOME / ".pi/agent/sessions"
    if not root.is_dir():
        return rows
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
                            title = _clip(blob, 90)
                            break
        except (OSError, json.JSONDecodeError):
            pass
        rows.append((cwd, title, str(path)))
    return rows


def plex_summary() -> tuple[int, list[tuple[str, int]]]:
    db = HOME / ".plex/plexd.sqlite3"
    if not db.exists():
        return 0, []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM commands").fetchone()[0]
    routes = list(
        con.execute("SELECT route, COUNT(*) FROM commands GROUP BY 1 ORDER BY 2 DESC")
    )
    con.close()
    return n, routes


def render_table(headers: list[str], rows: list[tuple]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(str(c)) for c in row) + " |")
    return "\n".join(lines)


def main() -> int:
    openai = openai_rows()
    cursor = cursor_rows()
    vscode = vscode_rows()
    gravity = antigravity_rows()
    pi = pi_rows()
    plex_n, plex_routes = plex_summary()

    parts = [
        "# Chat index",
        "",
        "Catalog of **where chats already live**. Not a transcript dump.",
        "`search_memory` can match titles here. Raw bodies stay in product folders.",
        "",
        "## Store map",
        "",
        render_table(
            ["source", "path", "count", "what it is"],
            [
                (
                    "ChatGPT export",
                    str(OPENAI_EXPORT),
                    str(len(openai)),
                    "GDPR dump: conversations-*.json + chat.html",
                ),
                (
                    "Cursor agent",
                    str(HOME / ".cursor/projects/*/agent-transcripts"),
                    str(len(cursor)),
                    "JSONL per composer/agent thread, keyed by workspace slug",
                ),
                (
                    "VS Code Copilot",
                    str(HOME / "AppData/Roaming/Code/User/workspaceStorage/*/chatSessions"),
                    str(len(vscode)),
                    "chatSessions JSONL per workspaceStorage id",
                ),
                (
                    "Antigravity",
                    str(HOME / ".gemini/antigravity/brain"),
                    str(sum(1 for r in gravity if r[0] == "antigravity")),
                    "brain UUID folders: task.md + transcript.jsonl",
                ),
                (
                    "Antigravity IDE",
                    str(HOME / ".gemini/antigravity-ide/brain"),
                    str(sum(1 for r in gravity if r[0] == "antigravity-ide")),
                    "same brain layout, IDE-scoped",
                ),
                (
                    "Pi",
                    str(HOME / ".pi/agent/sessions"),
                    str(len(pi)),
                    "JSONL sessions keyed by cwd slug; extensions in agent/git",
                ),
                (
                    "plex-shell",
                    str(HOME / ".plex/plexd.sqlite3"),
                    str(plex_n),
                    "not chats: command log (exec/semantic) + HTML snapshots",
                ),
                (
                    ".agents",
                    str(HOME / ".agents"),
                    "skills only",
                    "portable Agent Skills lockfile — no sessions",
                ),
            ],
        ),
        "",
        "## ChatGPT export",
        "",
        render_table(["date", "title", "shard"], openai),
        "",
        "## Cursor agent transcripts",
        "",
        render_table(["workspace", "first user turn", "path"], cursor),
        "",
        "## VS Code Copilot",
        "",
        render_table(["workspace", "title hint", "path"], vscode),
        "",
        "## Antigravity brains",
        "",
        render_table(["surface", "heading", "path"], gravity),
        "",
        "## Pi sessions",
        "",
        render_table(["cwd", "first user turn", "path"], pi),
        "",
        "## plex-shell",
        "",
        f"Command rows: **{plex_n}**. Routes: "
        + ", ".join(f"{r}={c}" for r, c in plex_routes)
        + ".",
        "",
        "This is a resolver daemon log, not a chat store. Semantic hits are unmatched shell input.",
        "",
    ]
    USER_MEMORY.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(
        "counts",
        {
            "openai": len(openai),
            "cursor": len(cursor),
            "vscode": len(vscode),
            "antigravity": len(gravity),
            "pi": len(pi),
            "plex_commands": plex_n,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
