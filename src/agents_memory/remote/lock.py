"""Cross-process lock so replace-pull and the MCP background pull do not interleave."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SyncBusy(TimeoutError):
    """Another pull, push, or replace holds the memory sync lock."""


def _acquire(fh) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release(fh) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    import fcntl

    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextmanager
def exclusive_sync_lock(root: Path, timeout: float = 15.0) -> Iterator[None]:
    """Hold ``root/.sync.lock``. Raise ``SyncBusy`` if it is not free in time.

    Safe to run while an IDE has ``sync_mcp`` up: that process takes the same
    lock around pull and push. If it stays busy past ``timeout``, refuse.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".sync.lock"
    fh = open(path, "a+b")
    try:
        if fh.seek(0, os.SEEK_END) < 1:
            fh.write(b"\0")
            fh.flush()
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            try:
                _acquire(fh)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise SyncBusy(
                        "memory sync is in progress (another pull, push, or the IDE MCP). "
                        "Retry in a few seconds."
                    ) from None
                time.sleep(0.05)
        yield
    finally:
        try:
            _release(fh)
        except OSError:
            pass
        fh.close()
