"""Closed frontmatter schema for memory markdown.

Notes without a YAML fence are valid. Notes that open `---` must close it
and may only use keys in SCHEMA. Unknown keys fail the check: that is how
UMP-shaped envelopes stay out of the vault.

This module is the machine-readable half of abi/HYGIENE.md § Frontmatter schema.
"""

from __future__ import annotations

from typing import Any, Iterable

from .index import parse_frontmatter_and_content

# Relation keys: list or scalar string. Resolved as memory ids unless the
# value uses an external prefix (survey:, record:, external:, entity:, urn:,
# http:, https:, did:).
RELATION_KEYS = frozenset(
    {
        "refs",
        "supersedes",
        "same_as",
        "at_project",
        "at_landmark",
        "part_of",
        "next",
        "near",
        "survey_ref",
        "on_trail",
    }
)
LIST_KEYS = frozenset({"refs"})
# Project cards (stub_project_md) plus optional identity on typed notes.
CARD_KEYS = frozenset(
    {
        "slug",
        "path",
        "role",
        "stack",
        "status",
        "title",
        "kind",
        "name",
        "collection",
        "date",
        "id",
    }
)
# Human pins that must survive a later rewrite (Karpathy gist / L1.5).
PIN_KEYS = frozenset({"provenance", "checked_at", "pin_kind"})
SCHEMA_KEYS = RELATION_KEYS | CARD_KEYS | PIN_KEYS

EXTERNAL_PREFIXES = (
    "survey:",
    "record:",
    "external:",
    "entity:",
    "urn:",
    "http:",
    "https:",
    "did:",
)

PROVENANCE_VALUES = frozenset({"human", "agent", "import"})
PIN_KIND_VALUES = frozenset({"correction", "addition", "deletion"})
STATUS_VALUES = frozenset(
    {
        "active",
        "sandbox",
        "paused",
        "archived",
        "planned",
        "accepted",
        "implemented",
        "proposed",
        "rejected",
    }
)


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def is_external_target(target: str) -> bool:
    t = target.strip()
    return t.startswith(EXTERNAL_PREFIXES)


def relation_targets(frontmatter: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in RELATION_KEYS:
        if key not in frontmatter:
            continue
        out.extend(_as_list(frontmatter[key]))
    return out


def lint_frontmatter_text(text: str) -> list[str]:
    """Return issue strings. Empty list means the file is schema-clean.

    Files with no opening fence are skipped (no issues).
    """
    if not text.lstrip().startswith("---"):
        return []
    stripped = text.lstrip()
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        return ["unclosed frontmatter fence"]
    fm, _, _, _ = parse_frontmatter_and_content(stripped)
    issues: list[str] = []
    unknown = sorted(k for k in fm if k not in SCHEMA_KEYS)
    if unknown:
        issues.append("unknown keys: " + ", ".join(unknown))
    for key in LIST_KEYS:
        if key in fm and not isinstance(fm[key], list):
            issues.append(f"{key} must be a YAML list")
    if "provenance" in fm:
        val = str(fm["provenance"]).strip()
        if val not in PROVENANCE_VALUES:
            issues.append(
                f"provenance must be one of {sorted(PROVENANCE_VALUES)}, got {val!r}"
            )
    if "pin_kind" in fm:
        val = str(fm["pin_kind"]).strip()
        if val not in PIN_KIND_VALUES:
            issues.append(
                f"pin_kind must be one of {sorted(PIN_KIND_VALUES)}, got {val!r}"
            )
    if "status" in fm:
        val = str(fm["status"]).strip()
        if val not in STATUS_VALUES:
            issues.append(f"status must be one of {sorted(STATUS_VALUES)}, got {val!r}")
    return issues


def near_duplicate_stems(paths: Iterable) -> list[tuple[str, str]]:
    """Pairs of filenames in the same directory where one stem prefixes the other.

    Catches concurrent-ingest forks (eori vs eori-number) without flagging
    every README.md across trees.
    """
    from collections import defaultdict
    from pathlib import Path

    by_dir: dict[str, list[Path]] = defaultdict(list)
    for p in paths:
        path = Path(p)
        by_dir[str(path.parent)].append(path)
    pairs: list[tuple[str, str]] = []
    for group in by_dir.values():
        stems = [(p, p.stem.lower()) for p in group]
        for i, (pa, sa) in enumerate(stems):
            for pb, sb in stems[i + 1 :]:
                if sa == sb:
                    continue
                if sa.startswith(sb + "-") or sa.startswith(sb + "_") or sb.startswith(
                    sa + "-"
                ) or sb.startswith(sa + "_"):
                    pairs.append((str(pa), str(pb)))
    return pairs
