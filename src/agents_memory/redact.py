"""Write-time secret redaction.

Secrets are replaced with ``[redacted]`` before a memory write. The rest of
the text stays, including markdown. Rejection was rejected: a write is usually
a durable fact that happens to contain one secret, and failing the whole write
drops the fact. The secret bytes are what must not reach disk.

Built-in patterns are vendor token shapes, authorization credentials, URL
userinfo, PEM armor that actually contains key material, and assignments whose
key is a secret name. Ordinary prose is left alone (``token: preferences``,
``password=changeme``, a PEM skeleton with no base64 body).

Extra patterns are operator config, not product defaults. They come from
``<memory>/redact.json`` (``extra_patterns``) and/or
``AGENTS_MEMORY_REDACT_PATTERNS`` (a JSON array of strings, same shape as
``AGENTS_TRACE_REDACT_EXTRA``). ``AGENTS_MEMORY_REDACT_CONFIG`` overrides the
file path. A pattern that does not compile, matches the empty string, is
shorter than 4 characters, is longer than 200 characters, matches ordinary
prose, or has nested or ambiguous quantifiers is skipped. Extra patterns are
not applied to inputs longer than ``MAX_EXTRA_INPUT`` characters. If the
third-party ``regex`` module is installed, each extra pattern also gets a
short match timeout. ``sync`` does not create the file.

``MemoryReceipt.secrets_redacted`` is the count for that write. It is not part
of the receipt JSON schema. MCP and CLI append a notice only when the count
is non-zero.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

try:
    import regex as _regex_mod
except ImportError:  # optional; stdlib re has no match timeout
    _regex_mod = None

try:
    from re import _parser as _re_parser
except ImportError:  # pragma: no cover - Python 3.10 keeps the public parser name
    import sre_parse as _re_parser  # type: ignore

REDACTED = "[redacted]"
CONFIG_NAME = "redact.json"
ENV_PATTERNS = "AGENTS_MEMORY_REDACT_PATTERNS"
ENV_CONFIG = "AGENTS_MEMORY_REDACT_CONFIG"
_MIN_EXTRA = 4
_MAX_EXTRA = 200
# Extra patterns never see more than this many characters in one match.
MAX_EXTRA_INPUT = 8192
_EXTRA_TIMEOUT_SEC = 0.1
_REPEAT_OPS = frozenset({"MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"})

# Prose and placeholder values that sit next to the words password/token/secret
# and are not credentials. High-confidence keys still replace other values.
_PLACEHOLDERS = frozenset(
    {
        "changeme",
        "change-me",
        "change_me",
        "password",
        "secret",
        "token",
        "passwd",
        "your-token",
        "your_token",
        "your-api-key",
        "your_api_key",
        "your-password",
        "your_password",
        "your-secret",
        "your_secret",
        "your-key",
        "your_key",
        "todo",
        "fixme",
        "placeholder",
        "example",
        "sample",
        "dummy",
        "redacted",
        "none",
        "null",
        "undefined",
        "nil",
        "false",
        "true",
        "test",
        "testing",
        "required",
        "optional",
        "enabled",
        "disabled",
        "missing",
        "empty",
        "default",
        "hidden",
        "stored",
        "rotated",
        "unset",
        "blank",
        "unknown",
        "n/a",
        "na",
        "tbd",
        "foo",
        "bar",
        "baz",
        "localhost",
        "policy",
        "policies",
        "rotation",
        "handling",
        "storage",
        "hygiene",
        "scanning",
        "detection",
        "manager",
        "managers",
        "quarterly",
        "practice",
        "practices",
        "workflow",
        "workflows",
        "material",
        "materials",
        "value",
        "values",
        "string",
        "strings",
        "field",
        "fields",
        "note",
        "notes",
        "memory",
        "memories",
        "budget",
        "characters",
        "auth",
        "model",
        "based",
        "role",
        "preferences",
        "preference",
        "management",
        "managed",
    }
)

# Sentences extra patterns must not match. Built-ins are tested against these too.
_CANARIES = (
    "Prefer dark mode and Tailwind CSS version 3.",
    "The token budget is 2000 characters.",
    "Password managers belong in the stack notes.",
    "kind=note name=preferences project=demo",
    "https://example.com/docs/api",
    "sha256 a1b2c3d4e5f6789012345678901234567890abcd",
    "Authorization model is role-based.",
    "Always run the linter before pushing.",
    "Rank-4 kernel survives a read-back check",
    "fragments plus app.css tokens only",
    "stack: typescript, python",
    "See the ghp_ prefix in the vendor docs.",
)

_SCHEME_WORDS = frozenset(
    {"bearer", "basic", "token", "digest", "apikey", "api-key", "negotiate", "oauth"}
)

# Longer key names first. Python alternation is left-first, not longest.
_SECRET_KEY = (
    r"aws[_-]?secret[_-]?access[_-]?key"
    r"|database[_-]?password"
    r"|db[_-]?password"
    r"|client[_-]?secret"
    r"|access[_-]?token"
    r"|refresh[_-]?token"
    r"|session[_-]?token"
    r"|auth(?:orization)?[_-]?token"
    r"|id[_-]?token"
    r"|private[_-]?key"
    r"|account[_-]?key"
    r"|password[_-]?hash"
    r"|secret[_-]?key"
    r"|api[_-]?secret"
    r"|x[_-]?api[_-]?key"
    r"|api[_-]?key"
    r"|password"
    r"|passwd"
    r"|pwd"
    r"|secret"
    r"|token"
)

_ASSIGN_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<q>[\"']?)(?P<key>{_SECRET_KEY})(?P=q)\s*(?P<sep>[=:])\s*",
    re.IGNORECASE,
)

_PEM_RE = re.compile(
    r"-----BEGIN ([A-Z0-9][A-Z0-9 ]{0,48})-----([\s\S]*?)-----END \1-----"
)
_B64_RUN = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")

_USERINFO_RE = re.compile(
    r"(?i)(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)([^/\s:@]+)(@)"
)

_AUTH_RE = re.compile(r"(?i)(\b(?:proxy-)?authorization\s*:\s*)(\S+)")

_BEARER_RE = re.compile(
    r"(?i)(\b(?:bearer|basic)\s+)([A-Za-z0-9._~+/=-]{12,})"
)

# Vendor shapes. Case-sensitive on purpose: the published prefix is the signal,
# so `sk-implementation` and `ghp_ prefix` stay.
_TOKEN_RES = (
    re.compile(
        r"(?<![A-Za-z0-9])sk-(?:ant-api\d{2}-|ant-|proj-)?"
        r"(?:(?=[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-]))[A-Za-z0-9_-]+"
        r"|(?=[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-]))[A-Za-z0-9_-]*[0-9][A-Za-z0-9_-]*)"
        r"(?![A-Za-z0-9_-])"
    ),
    re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{22,}"),
    # Fixed prefix. No digit gate: a letters-only ghp_/gho_/ghu_/ghs_/ghr_
    # token is still a credential. The body must be at least 16 characters,
    # so `ghp_` followed by a short word stays.
    re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9_]{16,}(?![A-Za-z0-9_])"),
    re.compile(
        r"(?<![A-Za-z0-9])xox[baprs]-(?=[0-9A-Za-z-]*[0-9])"
        r"[0-9A-Za-z-]{10,}(?:-[0-9A-Za-z-]{10,})+"
    ),
    re.compile(r"(?<![A-Za-z0-9])xapp-\d-[A-Za-z0-9-]{10,}-[A-Za-z0-9-]{10,}"),
    re.compile(
        r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"
    ),
    re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z\-_]{35}(?![A-Za-z0-9_\-])"),
    re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])"),
    re.compile(
        r"(?<![A-Za-z0-9])eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    ),
    re.compile(
        r"(?<![A-Za-z0-9])(?:sk|rk|pk)_(?:live|test)_[0-9A-Za-z]{16,}"
    ),
    re.compile(r"(?<![A-Za-z0-9])npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{34,}(?![A-Za-z0-9])"),
    re.compile(
        r"(?<![A-Za-z0-9])SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])"
    ),
    re.compile(r"(?<![A-Za-z0-9])pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{20,}"),
    re.compile(
        r"(?<![A-Za-z0-9])glpat-(?=[A-Za-z0-9_-]*[0-9])[A-Za-z0-9_-]{16,}"
    ),
    re.compile(r"(?<![A-Za-z0-9])re_(?=[A-Za-z0-9_]*[0-9])[A-Za-z0-9_]{15,}"),
    re.compile(r"(?<![A-Za-z0-9])nfp_(?=[A-Za-z0-9_]*[0-9])[A-Za-z0-9_]{15,}"),
    re.compile(r"(?<![A-Za-z0-9])gsk_(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]{20,}"),
)

_VERSION_RE = re.compile(r"v?\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.]+)?\Z")
_ENV_REF_RE = re.compile(
    r"\A(?:\$[A-Za-z_][A-Za-z0-9_]*|\$\{[A-Za-z_][A-Za-z0-9_]*\}|%[A-Za-z_][A-Za-z0-9_]*%\Z)\Z"
)
_LOW_WORD_RE = re.compile(r"[A-Za-z][A-Za-z_-]{0,30}\Z")

_lock = threading.Lock()
_cache: Optional[tuple] = None
_warned: set[str] = set()


@dataclass(frozen=True)
class Redaction:
    """Replacement result. ``count`` is how many secret spans were replaced."""

    text: str
    count: int

    @property
    def changed(self) -> bool:
        return self.count > 0


def redaction_notice(count: int) -> str:
    """Short success-line suffix, or ``\"\"`` when nothing was replaced."""
    n = int(count or 0)
    if n <= 0:
        return ""
    noun = "secret" if n == 1 else "secrets"
    return f"{n} {noun} replaced with {REDACTED}"


def annotate_success(message: str, count: int) -> str:
    """Append the redaction notice only when ``count`` is non-zero."""
    note = redaction_notice(count)
    if not note:
        return message
    return f"{message} ({note})"


def clear_redact_cache() -> None:
    """Drop the compiled extra-pattern cache. Tests call this between cases."""
    global _cache
    with _lock:
        _cache = None
        _warned.clear()


def redact_secrets(
    text: str,
    *,
    extra_patterns: Optional[Sequence[str]] = None,
    use_config: bool = True,
) -> Redaction:
    """Replace secret spans in ``text``. Structure outside those spans stays.

    ``use_config`` loads ``redact.json`` and ``AGENTS_MEMORY_REDACT_PATTERNS``.
    ``extra_patterns`` are always applied on top of the built-ins (and on top
    of config when ``use_config`` is true). Pass ``use_config=False`` for a
    pure built-in pass.
    """
    if not isinstance(text, str):
        raise TypeError("redact_secrets expects str")
    if not text:
        return Redaction(text, 0)
    count = 0
    text, n = _redact_pem(text)
    count += n
    text, n = _redact_userinfo(text)
    count += n
    text, n = _redact_authorization(text)
    count += n
    text, n = _redact_assignments(text)
    count += n
    text, n = _redact_bearer(text)
    count += n
    text, n = _sub_count(text, _TOKEN_RES)
    count += n
    text, n = _redact_extra(text, extra_patterns, use_config)
    count += n
    return Redaction(text, count)


def _sub_count(text: str, patterns: Sequence[re.Pattern[str]]) -> Tuple[str, int]:
    count = 0
    for pattern in patterns:
        def repl(match: re.Match[str]) -> str:
            nonlocal count
            span = match.group(0)
            if not span or span == REDACTED:
                return span
            count += 1
            return REDACTED

        text = pattern.sub(repl, text)
    return text, count


def _redact_pem(text: str) -> Tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        if not _B64_RUN.search(match.group(2) or ""):
            return match.group(0)
        count += 1
        return REDACTED

    return _PEM_RE.sub(repl, text), count


def _redact_userinfo(text: str) -> Tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        secret = match.group(2)
        if not _userinfo_is_secret(secret):
            return match.group(0)
        count += 1
        return f"{match.group(1)}{REDACTED}{match.group(3)}"

    return _USERINFO_RE.sub(repl, text), count


def _strip_tail(raw: str) -> Tuple[str, str]:
    value = raw.rstrip(".,;:)]}\"'")
    return value, raw[len(value) :]


def _redact_authorization(text: str) -> Tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        raw = match.group(2)
        value, tail = _strip_tail(raw)
        if value.lower() in _SCHEME_WORDS:
            return match.group(0)
        if not _credential_is_secret(value):
            return match.group(0)
        count += 1
        return f"{match.group(1)}{REDACTED}{tail}"

    return _AUTH_RE.sub(repl, text), count


def _redact_bearer(text: str) -> Tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        raw = match.group(2)
        value, tail = _strip_tail(raw)
        if not _credential_is_secret(value):
            return match.group(0)
        count += 1
        return f"{match.group(1)}{REDACTED}{tail}"

    return _BEARER_RE.sub(repl, text), count


def _read_value(text: str, index: int) -> Tuple[str, int, bool]:
    """Return ``(value, end_index, quoted)`` starting at ``index``."""
    if index >= len(text):
        return "", index, False
    if text[index] in "\"'":
        quote = text[index]
        chars: List[str] = []
        j = index + 1
        while j < len(text):
            if text[j] == "\\" and j + 1 < len(text):
                chars.append(text[j + 1])
                j += 2
                continue
            if text[j] == quote:
                return "".join(chars), j + 1, True
            chars.append(text[j])
            j += 1
        return "".join(chars), len(text), True
    j = index
    while j < len(text) and text[j] not in " \t\r\n,;&\"'`":
        j += 1
    return text[index:j], j, False


def _redact_assignments(text: str) -> Tuple[str, int]:
    parts: List[str] = []
    count = 0
    pos = 0
    for match in _ASSIGN_RE.finditer(text):
        if match.start() < pos:
            continue
        value, end, quoted = _read_value(text, match.end())
        if not _should_redact_assignment(match.group("key"), match.group("sep"), value, quoted=quoted):
            continue
        parts.append(text[pos : match.end()])
        if quoted and match.end() < len(text):
            quote = text[match.end()]
            parts.append(f"{quote}{REDACTED}{quote}")
        else:
            parts.append(REDACTED)
        count += 1
        pos = end
    parts.append(text[pos:])
    return "".join(parts), count


def _norm_key(key: str) -> str:
    return re.sub(r"[\s_-]+", "", key).lower()


def _is_placeholder(value: str) -> bool:
    stripped = value.strip()
    low = stripped.lower()
    if low in _PLACEHOLDERS:
        return True
    if re.fullmatch(r"[xX*]+", stripped):
        return True
    if _ENV_REF_RE.fullmatch(stripped):
        return True
    if stripped.startswith("<") and stripped.endswith(">") and len(stripped) < 64:
        return True
    if re.fullmatch(
        r"(your[-_ ]?(api[-_ ]?)?(key|token|secret|password)|change[-_ ]?me|placeholder|insert[-_ ]?(token|key|secret))",
        low,
    ):
        return True
    return False


def _is_version(value: str) -> bool:
    return _VERSION_RE.fullmatch(value.strip()) is not None


def _is_low_entropy_word(value: str) -> bool:
    stripped = value.strip()
    return _LOW_WORD_RE.fullmatch(stripped) is not None and len(stripped) < 16


def _looks_like_reference(value: str) -> bool:
    stripped = value.strip()
    if re.match(r"(?i)^(?:https?|file|git\+https)://", stripped):
        rest = stripped.split("://", 1)[1]
        host = rest.split("/", 1)[0]
        if "@" in host:
            return False
        if re.search(
            r"(?i)[?&](?:api[_-]?key|token|secret|password|access[_-]?token)=",
            stripped,
        ):
            return False
        return True
    if stripped.startswith(("/", "./", "../", "~/", "user/", "project/", "rules/")):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", stripped):
        return True
    return False


def _high_entropy(value: str) -> bool:
    if re.fullmatch(r"\d{8,}", value):
        return True
    if re.search(r"\d", value) and re.search(r"[A-Za-z]", value):
        return True
    if re.search(r"[a-z]", value) and re.search(r"[A-Z]", value):
        return True
    if re.search(r"[!@#$%^&*+=/~]", value):
        return True
    return False


def _credential_is_secret(value: str) -> bool:
    if len(value) < 12 or len(value) > 4096:
        return False
    if _is_placeholder(value) or _is_version(value) or _is_low_entropy_word(value):
        return False
    return _high_entropy(value)


def _userinfo_is_secret(value: str) -> bool:
    if len(value) < 6 or len(value) > 4096:
        return False
    if _is_placeholder(value) or _is_version(value):
        return False
    return True


def _should_redact_assignment(key: str, sep: str, value: str, *, quoted: bool) -> bool:
    value = value.strip()
    if len(value) < 6 or len(value) > 4096 or value == REDACTED:
        return False
    if _is_placeholder(value) or _is_version(value) or _looks_like_reference(value):
        return False
    ambiguous = _norm_key(key) == "token"
    if ambiguous and _is_low_entropy_word(value):
        return False
    if quoted or sep == "=":
        return True
    if ambiguous:
        return _high_entropy(value)
    if _high_entropy(value) or re.fullmatch(r"\d{6,}", value):
        return True
    return len(value) >= 10


def _config_path() -> Optional[Path]:
    override = os.environ.get(ENV_CONFIG, "").strip()
    if override:
        return Path(os.path.expanduser(override))
    try:
        from .store import _attr

        root = _attr("USER_MEMORY")
    except Exception:
        return None
    if not root:
        return None
    return Path(root) / CONFIG_NAME


def _parse_env_patterns(raw: str) -> List[str]:
    """``AGENTS_MEMORY_REDACT_PATTERNS`` is a JSON array of strings.

    The same shape as ``AGENTS_TRACE_REDACT_EXTRA``. A line list or ``;;``
    separator is not accepted.
    """
    text = (raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        _warn_once(
            "skipped extra patterns: AGENTS_MEMORY_REDACT_PATTERNS must be a JSON array of strings"
        )
        return []
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        _warn_once(
            "skipped extra patterns: AGENTS_MEMORY_REDACT_PATTERNS must be a JSON array of strings"
        )
        return []
    return list(data)


def _patterns_from_file(path: Optional[Path]) -> List[str]:
    if path is None or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _warn_once(f"skipped extra patterns: {path.name} is not valid JSON")
        return []
    if not isinstance(data, dict):
        _warn_once(f"skipped extra patterns: {path.name} must be a JSON object")
        return []
    extra = data.get("extra_patterns", [])
    if extra is None:
        return []
    if not isinstance(extra, list) or not all(isinstance(item, str) for item in extra):
        _warn_once(f"skipped extra patterns: {path.name} extra_patterns must be a list of strings")
        return []
    return [item for item in extra if isinstance(item, str)]


def _cache_key() -> tuple:
    env = os.environ.get(ENV_PATTERNS, "")
    path = _config_path()
    if path is None:
        return (env, "", None)
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    return (env, str(path), stamp)


def _configured_patterns() -> List[_ExtraPattern]:
    global _cache
    key = _cache_key()
    with _lock:
        if _cache is not None and _cache[0] == key:
            return _cache[1]
    sources = _patterns_from_file(_config_path())
    sources.extend(_parse_env_patterns(os.environ.get(ENV_PATTERNS, "")))
    compiled = _compile_extra(sources)
    with _lock:
        _cache = (key, compiled)
    return compiled


def _warn_once(message: str) -> None:
    with _lock:
        if message in _warned:
            return
        _warned.add(message)
    print(f"agents-memory redact: {message}", file=sys.stderr)


def _matches_canary(pattern: re.Pattern[str]) -> bool:
    return any(pattern.search(sample) for sample in _CANARIES)


def _op_name(op: Any) -> str:
    return str(getattr(op, "name", op))


def _child_patterns(op: Any, av: Any) -> List[Any]:
    """Sub-patterns of one regex opcode. Repeats are not descended here."""
    name = _op_name(op)
    children: List[Any] = []
    if name == "SUBPATTERN":
        children.append(av[-1])
    elif name == "BRANCH":
        children.extend(av[1])
    elif name in {"ASSERT", "ASSERT_NOT"}:
        body = av[-1]
        if body is not None and not isinstance(body, int):
            children.append(body)
    elif name == "ATOMIC_GROUP":
        children.append(av)
    elif name == "GROUPREF_EXISTS":
        children.append(av[1])
        if av[2] is not None:
            children.append(av[2])
    return children


def _has_opcode(nodes: Any, wanted: str) -> bool:
    for op, av in nodes:
        if _op_name(op) == wanted:
            return True
        for child in _child_patterns(op, av):
            if _has_opcode(child, wanted):
                return True
        if _op_name(op) in _REPEAT_OPS and _has_opcode(av[2], wanted):
            return True
    return False


def _pattern_risk(nodes: Any, *, in_repeat: bool) -> Optional[str]:
    """Reject nested quantifiers and quantified alternation.

    ``(a+)+`` is nested. ``(a|aa)+`` is one quantifier over an alternation
    that can match the same text two ways. Both are catastrophic on stdlib
    ``re``, which has no match deadline.
    """
    for op, av in nodes:
        name = _op_name(op)
        if name in _REPEAT_OPS:
            if in_repeat:
                return "nested quantifiers"
            sub = av[2]
            inner = _pattern_risk(sub, in_repeat=True)
            if inner:
                return inner
            if _has_opcode(sub, "BRANCH"):
                return "ambiguous quantifiers"
            continue
        for child in _child_patterns(op, av):
            found = _pattern_risk(child, in_repeat=in_repeat)
            if found:
                return found
    return None


def _lint_extra(source: str) -> Optional[str]:
    try:
        parsed = _re_parser.parse(source)
    except re.error:
        return "does not compile"
    return _pattern_risk(parsed, in_repeat=False)


@dataclass(frozen=True)
class _ExtraPattern:
    """A user pattern. ``rx`` is the optional ``regex`` module compile."""

    std: re.Pattern[str]
    rx: Any = None


def _timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if _regex_mod is None:
        return False
    timeout_type = getattr(_regex_mod, "TimeoutError", None)
    return bool(timeout_type) and isinstance(exc, timeout_type)


def _apply_extra(pattern: _ExtraPattern, text: str) -> Tuple[str, int]:
    if len(text) > MAX_EXTRA_INPUT:
        _warn_once(
            f"skipped extra patterns (input longer than {MAX_EXTRA_INPUT} characters)"
        )
        return text, 0
    count = 0

    def repl(match: Any) -> str:
        nonlocal count
        span = match.group(0)
        if not span or span == REDACTED:
            return span
        count += 1
        return REDACTED

    try:
        if pattern.rx is not None:
            try:
                replaced = pattern.rx.sub(repl, text, timeout=_EXTRA_TIMEOUT_SEC)
            except TypeError:
                replaced = pattern.std.sub(repl, text)
        else:
            replaced = pattern.std.sub(repl, text)
    except Exception as exc:
        if _timeout_error(exc):
            _warn_once("skipped extra pattern (timed out)")
            return text, 0
        raise
    return replaced, count


def _compile_extra(sources: Sequence[str]) -> List[_ExtraPattern]:
    compiled: List[_ExtraPattern] = []
    seen: set[str] = set()
    for raw in sources:
        source = (raw or "").strip()
        if not source or source.startswith("#"):
            continue
        if source in seen:
            continue
        seen.add(source)
        label = f"#{len(seen)}"
        if len(source) < _MIN_EXTRA:
            _warn_once(f"skipped extra pattern {label} (shorter than 4 characters)")
            continue
        if len(source) > _MAX_EXTRA:
            _warn_once(f"skipped extra pattern {label} (longer than 200 characters)")
            continue
        risk = _lint_extra(source)
        if risk:
            _warn_once(f"skipped extra pattern {label} ({risk})")
            continue
        try:
            std = re.compile(source)
        except re.error:
            _warn_once(f"skipped extra pattern {label} (does not compile)")
            continue
        if std.search("") is not None:
            _warn_once(f"skipped extra pattern {label} (matches empty string)")
            continue
        if _matches_canary(std):
            _warn_once(f"skipped extra pattern {label} (matches ordinary prose)")
            continue
        rx = None
        if _regex_mod is not None:
            try:
                rx = _regex_mod.compile(source)
            except Exception:
                rx = None
        compiled.append(_ExtraPattern(std=std, rx=rx))
    return compiled


def _redact_extra(
    text: str,
    extra_patterns: Optional[Sequence[str]],
    use_config: bool,
) -> Tuple[str, int]:
    patterns: List[_ExtraPattern] = []
    if use_config:
        patterns.extend(_configured_patterns())
    if extra_patterns:
        patterns.extend(_compile_extra(extra_patterns))
    if not patterns:
        return text, 0
    count = 0
    for pattern in patterns:
        text, n = _apply_extra(pattern, text)
        count += n
    return text, count
