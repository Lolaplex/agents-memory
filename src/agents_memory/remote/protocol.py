"""Vault epoch and minimum client version for remote sync.

The epoch is an integer in the server store (``.epoch``, not part of the
bundle). Clients remember the epoch they last synced in ``remote_config.json``.
A writer whose epoch is behind the server is rejected so a stale vault cannot
union-merge itself back in.

``min_client_version`` (env ``AGENTS_MEMORY_MIN_CLIENT_VERSION``) rejects
writers that send no ``X-Agents-Memory-Version`` header or an older version.
Reads stay open.
"""
from __future__ import annotations

import os
from pathlib import Path

EPOCH_FILE = ".epoch"
VERSION_HEADER = "X-Agents-Memory-Version"
EPOCH_HEADER = "X-Agents-Memory-Epoch"
DEFAULT_UPDATE_HINT = (
    "uv tool install --upgrade agents-memory (or: pip install --upgrade agents-memory)"
)


def load_epoch(root: Path) -> int:
    path = Path(root) / EPOCH_FILE
    try:
        return max(0, int(path.read_text(encoding="utf-8").strip() or "0"))
    except (OSError, ValueError):
        return 0


def save_epoch(root: Path, epoch: int) -> int:
    epoch = max(0, int(epoch))
    path = Path(root) / EPOCH_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{epoch}\n", encoding="utf-8")
    return epoch


def bump_epoch(root: Path) -> int:
    return save_epoch(root, load_epoch(root) + 1)


def min_client_version() -> str:
    return os.environ.get("AGENTS_MEMORY_MIN_CLIENT_VERSION", "").strip()


def update_hint() -> str:
    return os.environ.get("AGENTS_MEMORY_UPDATE_HINT", "").strip() or DEFAULT_UPDATE_HINT


def upgrade_required_message(minimum: str, hint: str | None = None) -> str:
    """Sentence returned to old writers. The install hint is configurable."""
    return f"agents-memory {minimum} required. Update: {hint or update_hint()}"


def version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in str(value).strip().split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def version_older(client: str, minimum: str) -> bool:
    """True when ``client`` is missing or strictly older than ``minimum``."""
    if not str(client).strip():
        return True
    left = version_tuple(client)
    right = version_tuple(minimum)
    width = max(len(left), len(right))
    left = left + (0,) * (width - len(left))
    right = right + (0,) * (width - len(right))
    return left < right


def as_epoch(value: object) -> int:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
