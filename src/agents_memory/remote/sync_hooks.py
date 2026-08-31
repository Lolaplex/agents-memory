"""Auto push/pull mirror sync when remote is connected."""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from .client import get_remote_config, remote_pull, remote_push_merge

_push_lock = threading.Lock()
_bg_thread: Optional[threading.Thread] = None
_bg_stop = threading.Event()


def _verify_ssl(cfg: dict[str, Any]) -> bool:
    return cfg.get("verify_ssl") is not False


def _refresh_index() -> None:
    try:
        from ..index import rebuild_index

        rebuild_index()
    except Exception:
        pass


def push_if_connected(refresh_index: bool = True) -> Optional[dict[str, Any]]:
    cfg = get_remote_config()
    if not cfg or not cfg.get("url"):
        return None
    with _push_lock:
        try:
            res = remote_push_merge(
                str(cfg["url"]),
                token=str(cfg.get("token") or ""),
                verify_ssl=_verify_ssl(cfg),
            )
            if refresh_index:
                _refresh_index()
            return res
        except Exception:
            return None


def pull_if_connected(refresh_index: bool = True) -> Optional[dict[str, Any]]:
    cfg = get_remote_config()
    if not cfg or not cfg.get("url"):
        return None
    with _push_lock:
        try:
            res = remote_pull(
                str(cfg["url"]),
                token=str(cfg.get("token") or ""),
                verify_ssl=_verify_ssl(cfg),
            )
            if refresh_index:
                _refresh_index()
            return res
        except Exception:
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
