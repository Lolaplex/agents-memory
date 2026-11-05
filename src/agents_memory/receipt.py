"""Verified receipts for memory writes.

A success result is issued only after the bytes on disk are read back and
match the text that was written. Callers that already treat ``add_memory`` /
``write_memory_file`` as a path string keep working: ``MemoryReceipt`` is that
id, and the structured fields sit on the same object.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

RECEIPT_SCHEMA = "agents_memory.write_receipt.v1"
RECEIPT_FIELDS = ("schema", "id", "path", "sha256", "bytes", "written_at", "verified")


class MemoryWriteVerificationError(Exception):
    """The write did not land, was partial, or did not match the read-back.

    This is never a success. ``reason`` is one of ``missing``, ``partial_write``,
    ``readback_mismatch``, ``not_utf8``, or ``unreadable``.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        memory_id: str,
        expected_bytes: Optional[int] = None,
        actual_bytes: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.memory_id = memory_id
        self.expected_bytes = expected_bytes
        self.actual_bytes = actual_bytes


class MemoryReceipt(str):
    """Stable memory id plus the receipt of the bytes read back from disk.

    String equality, formatting, and containment follow the id
    (``user/...``, ``project/<slug>/...``, ``rules/...``), which is what
    existing callers compare against.
    """

    __slots__ = ("sha256", "_byte_count", "written_at", "verified")

    def __new__(
        cls,
        location: str,
        *,
        sha256: str,
        byte_count: int,
        written_at: str,
    ) -> "MemoryReceipt":
        if not isinstance(location, str) or not location:
            raise MemoryWriteVerificationError(
                "memory write verification failed: empty memory id",
                reason="missing",
                memory_id="",
            )
        obj = str.__new__(cls, location)
        obj.sha256 = sha256
        obj._byte_count = int(byte_count)
        obj.written_at = written_at
        obj.verified = True
        return obj

    @property
    def id(self) -> str:
        return str.__str__(self)

    @property
    def path(self) -> str:
        return self.id

    @property
    def bytes(self) -> int:
        return self._byte_count

    def as_dict(self) -> dict[str, Any]:
        """Receipt fields. ``id`` and ``path`` are the same stable memory id."""
        return {
            "schema": RECEIPT_SCHEMA,
            "id": self.id,
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "written_at": self.written_at,
            "verified": self.verified,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_persisted_bytes(path: Path) -> bytes:
    """Read the file that a write claims to have persisted. Tests may patch this."""
    return path.read_bytes()


def _newline_normalized(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _fail(
    memory_id: str,
    reason: str,
    *,
    expected_bytes: Optional[int] = None,
    actual_bytes: Optional[int] = None,
) -> MemoryWriteVerificationError:
    detail = reason
    if expected_bytes is not None or actual_bytes is not None:
        detail += f" (expected {expected_bytes} bytes, read {actual_bytes} bytes)"
    target = memory_id or "(unknown)"
    return MemoryWriteVerificationError(
        f"memory write verification failed: {detail}: {target}",
        reason=reason,
        memory_id=memory_id,
        expected_bytes=expected_bytes,
        actual_bytes=actual_bytes,
    )


def verify_memory_write(path: Path, expected_text: str, *, file_id: str) -> MemoryReceipt:
    """Read ``path`` back and return a receipt only when it matches ``expected_text``.

    Comparison is exact on the raw bytes, or, when the only difference is
    platform newline translation, on LF-normalized UTF-8 text. ``sha256`` and
    ``bytes`` always describe the raw file that was read.
    """
    memory_id = file_id
    if not path.is_file():
        raise _fail(memory_id, "missing")
    try:
        raw = read_persisted_bytes(path)
    except OSError as exc:
        raise _fail(memory_id, "unreadable") from exc

    expected_raw = expected_text.encode("utf-8")
    try:
        actual_text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        reason = "partial_write" if expected_raw.startswith(raw) else "not_utf8"
        raise _fail(
            memory_id,
            reason,
            expected_bytes=len(expected_raw),
            actual_bytes=len(raw),
        ) from exc

    if raw != expected_raw:
        actual_norm = _newline_normalized(actual_text)
        expected_norm = _newline_normalized(expected_text)
        if actual_norm != expected_norm:
            reason = (
                "partial_write"
                if expected_norm.startswith(actual_norm)
                else "readback_mismatch"
            )
            raise _fail(
                memory_id,
                reason,
                expected_bytes=len(expected_raw),
                actual_bytes=len(raw),
            )

    return MemoryReceipt(
        memory_id,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
        written_at=utc_now_iso(),
    )


def render_mcp_receipt(receipt: MemoryReceipt, message: str) -> str:
    """Legacy success line plus one JSON object a harness can parse.

    The JSON object repeats ``message`` so the old text stays available when
    the caller only keeps the structured payload. Failures must not call this.
    """
    if not isinstance(receipt, MemoryReceipt) or receipt.verified is not True:
        raise MemoryWriteVerificationError(
            "memory write verification failed: refusing success text without a verified receipt",
            reason="missing",
            memory_id=str(receipt or ""),
        )
    payload = receipt.as_dict()
    payload["message"] = message
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{message}\n{body}"
