"""Shared ingest filters, staging paths, and reversible state."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

from .store import USER_MEMORY, _append_bullet, _read, _write

# Expanded bilingual ephemeral chat patterns (EN + DE)
CHATTER_RE = re.compile(
    r"^(?:"
    # Greetings / confirmations / fillers / reactions (DE + EN)
    r"(?:ok|okay|danke|vielen dank|super|perfekt|thanks|thx|thank you|hi|hallo|hey|heya|heyho|"
    r"yes|no|ja|nein|cool|top|nice|alles klar|genau|stimmt|achso|ach so|hä|warte|warte mal|moment|"
    r"probiers|versuchs|ja safe|safe|yep|nope|sure|done|testung|ah nvm|nvm|wait|hmm aber|ja wow)\b"
    # Conversational commands & questions (DE)
    r"|(?:kannst du|könntest du|kann man|könnte man|bitte |warum |wieso |weshalb |was ist|wo ist|"
    r"schau mal|guck mal|lies mal|sag mal|hilf mir|zeig mir|mach mal|mach weiter|weiter|"
    r"hä das|das hab ich schon|er behauptet|ich habs gefühl|ich fänds|meine frage ist|"
    r"hätte aber halt gerne|hätte aber|lass mal|probiere|probiert|versuche|check mal|wait und|ja wow|hmm aber)\b"
    # Conversational commands & questions (EN)
    r"|(?:can you|could you|how (?:can|do|to|would)|why (?:is|does|do|won't)|what is the|"
    r"write (?:a|me|the)|fix |create (?:a|an)|implement |help me|please |instead of |"
    r"check line|look at|did you|have you|wait and)\b"
    r")",
    re.I,
)

BUILD_TEST_RE = re.compile(
    r"(?:"
    r"(?:npm|cargo|pytest|pnpm|yarn|mvn|gradle)\s+(?:test|run|build|check|lint)\b"
    r"|\b(?:unit-?tests?|tests?)\s+(?:erfolgreich|bestanden|passed|failed|running)\b"
    r"|\b\d+/\d+\s+tests?\s+(?:bestanden|passed)\b"
    r"|\b\d+\s+passed\b"
    r"|\b(?:build|typecheck|lint)\s+(?:erfolgreich|fehlerfrei|passed|failed|abgeschlossen)\b"
    r"|\b0\s+errors?\b"
    r"|\bexit code \d+\b"
    r"|\b(?:syntaxerror|typeerror|referenceerror|traceback|stack trace)\b"
    r")",
    re.I,
)

CODE_OR_SQL_RE = re.compile(
    r"(?:"
    r"^\s*(?:ALTER\s+TABLE|CREATE\s+TABLE|DROP\s+TABLE|INSERT\s+INTO|UPDATE\s+\w+\s+SET|SELECT\s+.*?\s+FROM)\b"
    r"|^\s*(?:git\s+(?:commit|push|pull|checkout|status|diff|add|branch|merge|stash))\b"
    r"|^\s*(?:npm\s+i|pip\s+install|cargo\s+add)\b"
    r"|^\s*(?:export\s+(?:const|let|var|default|function|class)|import\s+.*?\s+from)\b"
    r"|^\s*(?:pub\s+fn|pub\s+struct|fn\s+\w+\(|def\s+\w+\(|class\s+\w+[\(:])"
    r")",
    re.I,
)

HEADER_STUB_RE = re.compile(r"^\s*(?:#+\s+.*|\*{2}[^*]+\*{2}:?\s*)$")
URL_ONLY_RE = re.compile(r"^\s*https?://\S+\s*$", re.I)

CHANGELOG_NOISE_RE = re.compile(
    r"(?:"
    r"file:///"
    r"|\b(?:integriert|ersetzt|angepasst|überarbeitet|implementiert|unterst[üu]tzt jetzt|gerendert|wiederhergestellt|behoben|gefixt)\b"
    r"|^(?:neue funktion|neuer endpoint|funktion |komponente |crate |suchleiste |toolbar)\b"
    r"|\b(?:erfolgreich ausgef[üu]hrt|fehlerfrei abgeschlossen)\b"
    r")",
    re.I,
)

BUG_REPORT_RE = re.compile(
    r"(?:"
    r"^(?:das (?:problem|asynchronit[äa]tsproblem) (?:besteht|ist)|es gibt ein problem|funktioniert (?:nicht|immer noch nicht)|klappt (?:nicht|0%))\b"
    r")",
    re.I,
)

DURABLE_RULE_KEYWORDS = (
    "always",
    "never",
    "prefer",
    "standard",
    "stack",
    "convention",
    "rule",
    "policy",
    "immer",
    "nie",
    "bevorzuge",
    "standard",
    "konvention",
    "regel",
    "richtlinie",
    "datenschutz",
    "privacy",
)

HOW_TO = CHATTER_RE


def is_ephemeral_noise(text: str) -> tuple[bool, str]:
    """Classify whether a line is ephemeral noise, chatter, build log, or question."""
    t = re.sub(r"^\[.*?\]\s*", "", text or "").strip()
    if not t or len(t) < 8:
        return True, "too_short"
    if HEADER_STUB_RE.match(t):
        return True, "header_stub"
    if URL_ONLY_RE.match(t):
        return True, "url_only"
    if CHATTER_RE.search(t):
        return True, "chatter"
    if BUILD_TEST_RE.search(t):
        return True, "build_test"
    if CODE_OR_SQL_RE.search(t):
        return True, "code_sql"
    if CHANGELOG_NOISE_RE.search(t):
        return True, "changelog"
    if BUG_REPORT_RE.search(t):
        return True, "bug_report"
    if t.endswith("?") and not any(k in t.lower() for k in DURABLE_RULE_KEYWORDS):
        return True, "question"
    return False, ""

PII = re.compile(
    r"("
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    r"|(\+?\d[\d\s().-]{8,}\d)"
    r"|sk-[A-Za-z0-9_\-]{10,}"
    r"|sk-ant-[A-Za-z0-9_\-]{10,}"
    r"|github_pat_[A-Za-z0-9_]+"
    r"|gh[pors]_[A-Za-z0-9_]+"
    r"|re_[A-Za-z0-9_]{15,}"
    r"|nfp_[A-Za-z0-9_]{15,}"
    r"|xox[baprs]-[A-Za-z0-9-]+"
    r"|Bearer\s+[A-Za-z0-9._\-]{15,}"
    r"|AIza[0-9A-Za-z\-_]{35}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ey[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}"
    r")",
    re.I,
)
SECRET_FILENAMES = frozenset({
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.staging",
    "id_rsa",
    "id_rsa.pub",
    "id_ed25519",
    "id_ed25519.pub",
    "credentials.json",
    "service-account.json",
    "token.json",
})
SECRET_EXTENSIONS = frozenset({".pem", ".key", ".pfx", ".p12", ".kdbx"})


def is_secret_or_env_path(path: Path | str) -> bool:
    """Return True if path represents a secret or environment file that should never be ingested."""
    p = Path(path)
    name = p.name.lower()
    if name in SECRET_FILENAMES or name.startswith(".env"):
        return True
    if p.suffix.lower() in SECRET_EXTENSIONS:
        return True
    if any(part.lower() in (".ssh", ".gnupg", "secrets") for part in p.parts):
        return True
    return False

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
    is_noise, _ = is_ephemeral_noise(text)
    if is_noise:
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


def load_state() -> dict[str, Any]:
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


def save_state(state: dict[str, Any]) -> None:
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


def write_entity_card(source: dict[str, Any], paths: List[Path], catalog_count: int) -> Path:
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
