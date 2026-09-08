"""Auto push/pull mirror sync when remote is connected."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from .client import get_remote_config, remote_pull, remote_push_merge

_push_lock = threading.Lock()
_bg_thread: Optional[threading.Thread] = None
_bg_stop = threading.Event()

_MAX_RETRIES = 3


def _verify_ssl(cfg: dict[str, Any]) -> bool:
    return cfg.get("verify_ssl") is not False


def _refresh_index() -> None:
    try:
        from ..index import rebuild_index

        rebuild_index()
    except Exception:
        pass


def _log_sync_error(action: str, err: BaseException) -> None:
    try:
        from ..store import USER_MEMORY, _read, _write

        path = USER_MEMORY / "staging" / "sync-errors.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        prev = _read(path) if path.exists() else ""
        if not prev.strip():
            prev = "# Sync errors\n\n"
        line = f"- [{ts}] {action}: {err}\n"
        _write(path, prev.rstrip() + "\n" + line)
    except Exception:
        pass


def push_if_connected(refresh_index: bool = True, retries: int = _MAX_RETRIES) -> Optional[dict[str, Any]]:
    cfg = get_remote_config()
    if not cfg or not cfg.get("url"):
        return None
    attempts = max(1, min(int(retries), 5))
    last_err: Optional[BaseException] = None
    with _push_lock:
        for attempt in range(1, attempts + 1):
            try:
                res = remote_push_merge(
                    str(cfg["url"]),
                    token=str(cfg.get("token") or ""),
                    verify_ssl=_verify_ssl(cfg),
                )
                if refresh_index:
                    _refresh_index()
                return res
            except Exception as e:
                last_err = e
                if attempt < attempts:
                    time.sleep(0.4 * attempt)
        if last_err is not None:
            _log_sync_error("push", last_err)
        return None


def pull_if_connected(refresh_index: bool = True, retries: int = _MAX_RETRIES) -> Optional[dict[str, Any]]:
    cfg = get_remote_config()
    if not cfg or not cfg.get("url"):
        return None
    attempts = max(1, min(int(retries), 5))
    last_err: Optional[BaseException] = None
    with _push_lock:
        for attempt in range(1, attempts + 1):
            try:
                res = remote_pull(
                    str(cfg["url"]),
                    token=str(cfg.get("token") or ""),
                    verify_ssl=_verify_ssl(cfg),
                )
                if refresh_index:
                    _refresh_index()
                return res
            except Exception as e:
                last_err = e
                if attempt < attempts:
                    time.sleep(0.4 * attempt)
        if last_err is not None:
            _log_sync_error("pull", last_err)
        return None


def after_memory_mutation() -> None:
    """Push local mirror to remote after store writes (best-effort)."""
    push_if_connected(refresh_index=True)


def _background_loop(interval: float) -> None:
    while not _bg_stop.wait(timeout=interval):
        cfg = get_remote_config() or {}
        if not cfg.get("auto_pull", True):
            continue
        pull_if_connected(refresh_index=True)


def start_background_sync(interval: float = 60.0) -> None:
    global _bg_thread
    cfg = get_remote_config()
    if not cfg or not cfg.get("url"):
        return
    if _bg_thread and _bg_thread.is_alive():
        return
    _bg_stop.clear()
    _bg_thread = threading.Thread(
        target=_background_loop,
        args=(interval,),
        name="agents-memory-sync",
        daemon=True,
    )
    _bg_thread.start()


def stop_background_sync() -> None:
    _bg_stop.set()
