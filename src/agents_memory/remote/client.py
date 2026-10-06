"""Client utilities, sync client, and Stdio-to-Remote SSE bridge."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import anyio
import httpx
from mcp.client.sse import sse_client
from mcp.server.stdio import stdio_server

from .. import __version__
from ..store import (
    AGENTS_HOME,
    USER_MEMORY,
    ensure_memory_layout,
    ensure_repo_agents_gitignored,
    find_project,
    is_engine_repo,
    sync_injection,
)
from .lock import exclusive_sync_lock
from .merge import merge_file_trees
from .protocol import (
    EPOCH_HEADER,
    VERSION_HEADER,
    as_epoch,
    upgrade_required_message,
    version_older,
)
from .sync_bundle import (
    EPOCH_QUESTIONS_REL,
    apply_snapshot_replace,
    apply_sync_bundle,
    capture_pending,
    collect_sync_bundle,
    infer_from_baseline,
    infer_remote_project_absences,
    load_baseline,
    save_baseline,
    stage_epoch_questions,
)
from .tombstones import (
    clear_writes,
    file_blocked,
    load_tombstones,
    load_writes,
    merge_tombstones,
    normalize_tombstones,
    revive,
    save_tombstones,
)

CONFIG_FILE = USER_MEMORY / "remote_config.json"


class UpgradeRequired(RuntimeError):
    """Server rejected a write because this client is too old or sent no version."""


class EpochMismatch(RuntimeError):
    """Server vault epoch is ahead of the epoch this client last synced."""

    def __init__(self, message: str, server_epoch: int = 0, client_epoch: int = 0):
        super().__init__(message)
        self.server_epoch = server_epoch
        self.client_epoch = client_epoch


def _config_file() -> Path:
    from .. import store
    cfg = getattr(sys.modules.get(__name__), "CONFIG_FILE", None)
    if cfg is not None and cfg != (USER_MEMORY / "remote_config.json"):
        return Path(cfg)
    return store.USER_MEMORY / "remote_config.json"


def get_remote_config() -> Optional[dict[str, Any]]:
    """Load remote sync configuration if present."""
    cfg_path = _config_file()
    if not cfg_path.exists():
        return None
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("url"):
            return data
    except Exception:
        pass
    return None


def save_remote_config(
    url: str,
    token: str = "",
    auto_pull: bool = True,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Save remote sync configuration to ~/.agents/memory/remote_config.json."""
    ensure_memory_layout()
    clean_url = url.strip().rstrip("/")
    cfg_path = _config_file()
    previous: dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded
        except (OSError, json.JSONDecodeError):
            previous = {}
    cfg = {
        "url": clean_url,
        "token": token.strip(),
        "auto_pull": auto_pull,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Same server: do not drop the epoch a sync just stored. A new URL starts at 0.
    if str(previous.get("url") or "").rstrip("/") == clean_url:
        for key in ("epoch", "last_sync", "upgrade_required"):
            if key in previous and (not extra or key not in extra):
                cfg[key] = previous[key]
    if extra:
        cfg.update(extra)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def clear_remote_config() -> bool:
    """Remove remote configuration (disconnect from cloud)."""
    cfg_path = _config_file()
    if cfg_path.exists():
        try:
            cfg_path.unlink()
            return True
        except Exception:
            return False
    return False


def local_epoch() -> int:
    """Epoch this device last synced. Missing config or key means 0."""
    cfg = get_remote_config() or {}
    return as_epoch(cfg.get("epoch"))


def remember_epoch(epoch: int) -> None:
    """Persist the server epoch in remote_config.json when a config exists."""
    cfg = get_remote_config()
    if not cfg:
        return
    cfg["epoch"] = as_epoch(epoch)
    cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        _config_file().write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


def upgrade_notice() -> str:
    """Message the server told this client to show, or empty."""
    cfg = get_remote_config() or {}
    return str(cfg.get("upgrade_required") or "").strip()


def note_upgrade_required(message: str) -> None:
    """Remember a 426 (or snapshot min-version) so MCP can show it and pushes stop."""
    message = str(message).strip()
    if not message:
        return
    cfg = get_remote_config()
    if cfg is not None and cfg.get("upgrade_required") != message:
        cfg["upgrade_required"] = message
        cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            _config_file().write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except OSError:
            pass
    try:
        from ..store import USER_MEMORY as store_root
        from ..store import _write

        path = Path(store_root) / "staging" / "upgrade-required.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, f"# Upgrade required\n\n{message}\n")
    except Exception:
        pass
    print(message, file=sys.stderr)


def clear_upgrade_required() -> None:
    cfg = get_remote_config()
    if not cfg or "upgrade_required" not in cfg:
        return
    cfg.pop("upgrade_required", None)
    cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        _config_file().write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


def _get_auth_headers(token: str) -> dict[str, str]:
    headers = {
        "User-Agent": f"agents-memory-client/{__version__}",
        VERSION_HEADER: __version__,
        EPOCH_HEADER: str(local_epoch()),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except Exception:
        data = None
    if isinstance(data, dict) and data.get("error"):
        return str(data["error"])
    text = (resp.text or "").strip()
    return text or f"HTTP {resp.status_code}"


def _raise_for_sync(resp: httpx.Response) -> None:
    if resp.status_code == 401:
        raise PermissionError("Unauthorized: Token rejected by remote server.")
    if resp.status_code == 426:
        message = _error_message(resp)
        note_upgrade_required(message)
        raise UpgradeRequired(message)
    if resp.status_code == 409:
        message = _error_message(resp)
        try:
            data = resp.json()
        except Exception:
            data = {}
        if isinstance(data, dict) and data.get("code") == "epoch_mismatch":
            raise EpochMismatch(
                message,
                server_epoch=as_epoch(data.get("epoch")),
                client_epoch=as_epoch(data.get("client_epoch")),
            )
        raise RuntimeError(message)
    resp.raise_for_status()


def _observe_server_requirements(data: dict[str, Any]) -> None:
    """Surface min_client_version from a snapshot or health body. Reads are allowed."""
    minimum = str(data.get("min_client_version") or "").strip()
    if minimum and version_older(__version__, minimum):
        hint = str(data.get("update_hint") or "").strip() or None
        note_upgrade_required(upgrade_required_message(minimum, hint))
    else:
        clear_upgrade_required()


def _is_ssl_verify_enabled(cfg: Optional[dict[str, Any]] = None) -> bool:
    if os.environ.get("AGENTS_MEMORY_INSECURE", "").lower() in ("1", "true", "yes"):
        return False
    if cfg and cfg.get("verify_ssl") is False:
        return False
    return True


def _get_http_client(timeout: float = 30.0, verify_ssl: bool = True) -> httpx.Client:
    return httpx.Client(timeout=timeout, verify=verify_ssl)


def verify_remote_tool_api(
    url: str,
    token: str = "",
    timeout: float = 10.0,
    verify_ssl: Optional[bool] = None,
) -> dict[str, Any]:
    """Confirm remote server supports hybrid REST tool proxy (/api/v1/tool)."""
    clean_url = url.strip().rstrip("/")
    headers = _get_auth_headers(token)
    verify = verify_ssl if verify_ssl is not None else _is_ssl_verify_enabled()
    with _get_http_client(timeout=timeout, verify_ssl=verify) as client:
        resp = client.post(
            f"{clean_url}/api/v1/tool",
            json={"name": "__probe__", "arguments": {}},
            headers={**headers, "Content-Type": "application/json"},
        )
        # 404 unknown tool = API present; 401 = auth issue; connection error = missing deploy
        if resp.status_code == 404:
            return {"ok": True, "tool_api": True}
        if resp.status_code == 401:
            raise PermissionError("Unauthorized: token rejected by remote server.")
        if resp.status_code == 400:
            data = resp.json()
            if data.get("locality") == "local":
                return {"ok": True, "tool_api": True}
        if resp.status_code == 426:
            _raise_for_sync(resp)
        resp.raise_for_status()
        return {"ok": True, "tool_api": True}


def remote_health_check(
    url: str,
    token: str = "",
    timeout: float = 10.0,
    verify_ssl: Optional[bool] = None,
) -> dict[str, Any]:
    """Check connectivity and authentication against remote memory server."""
    clean_url = url.strip().rstrip("/")
    target = f"{clean_url}/api/v1/health"
    headers = _get_auth_headers(token)
    verify = verify_ssl if verify_ssl is not None else _is_ssl_verify_enabled()

    with _get_http_client(timeout=timeout, verify_ssl=verify) as client:
        resp = client.get(target, headers=headers)
        _raise_for_sync(resp)
        data = resp.json()
        if isinstance(data, dict):
            _observe_server_requirements(data)
        return data


def touch_remote_config_sync_time() -> None:
    """Update last_sync and updated_at timestamp in remote_config.json."""
    cfg = get_remote_config()
    if cfg:
        now_iso = datetime.now(timezone.utc).isoformat()
        cfg["last_sync"] = now_iso
        cfg["updated_at"] = now_iso
        try:
            _config_file().write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception:
            pass


def _pending_deletions(root: Path) -> list[str]:
    path = Path(root) / ".deleted.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [str(item) for item in data]
    return []


def _clear_unsent_deletions(root: Path) -> None:
    """Drop the local deletion outbox.

    A replace-pull adopts the snapshot. Unsent ``.deleted.json`` entries were
    recorded against the previous store; the next push would tombstone them
    on the epoch just adopted.
    """
    path = Path(root) / ".deleted.json"
    if path.is_file():
        path.unlink()


def _clear_pending_deletions(root: Path, acknowledged: list[str]) -> None:
    path = Path(root) / ".deleted.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        path.unlink(missing_ok=True)
        return
    if not isinstance(data, list):
        path.unlink(missing_ok=True)
        return
    acked = set(acknowledged)
    remain = [item for item in data if item not in acked]
    if remain:
        path.write_text(json.dumps(remain, indent=2) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def _fetch_snapshot(
    url: str,
    token: str,
    timeout: float,
    verify: bool,
) -> dict[str, Any]:
    clean_url = url.strip().rstrip("/")
    headers = _get_auth_headers(token)
    with _get_http_client(timeout=timeout, verify_ssl=verify) as client:
        resp = client.get(f"{clean_url}/api/v1/snapshot", headers=headers)
        _raise_for_sync(resp)
        data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("snapshot was not a JSON object")
    return data


def _merged_pull_tombstones(dest_root: Path, data: dict[str, Any]) -> dict[str, Any]:
    local_ts = load_tombstones(dest_root)
    server_ts = normalize_tombstones(data.get("tombstones"))
    deleted = data.get("deleted") if isinstance(data.get("deleted"), list) else []
    from .tombstones import now_iso

    for rel in deleted:
        clean = str(rel).replace("\\", "/").strip().lstrip("/")
        if clean and clean not in server_ts["files"]:
            server_ts["files"][clean] = now_iso()
    merged = merge_tombstones(local_ts, server_ts)
    explicit = load_writes(dest_root)
    merged = revive(merged, explicit)
    from .tombstones import compact

    merged = compact(merged)
    save_tombstones(dest_root, merged)
    return merged


def _snapshot_files(data: dict[str, Any]) -> dict[str, str]:
    files = data.get("files") or {}
    if not isinstance(files, dict):
        return {}
    return {
        str(key).replace("\\", "/").lstrip("/"): value
        for key, value in files.items()
        if isinstance(value, str)
    }


def remote_pull(
    url: str,
    token: str = "",
    target_dir: Optional[Path] = None,
    timeout: float = 30.0,
    verify_ssl: Optional[bool] = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Download memory snapshot from remote and update target directory.

    ``replace=True`` makes the local synced store match the snapshot exactly
    (backup first, no table union). Machine-local files stay. Explicit replace
    does not park local edits; the caller asked for the snapshot.

    A snapshot whose ``epoch`` is ahead of this device also replaces (startup
    pull and the 60s pull). Files changed or added since the last baseline are
    parked in ``staging/epoch-questions.md`` and are not pushed. Deletions
    since that baseline do not become tombstones on the new epoch.
    """
    dest_root = target_dir or USER_MEMORY
    verify = verify_ssl if verify_ssl is not None else _is_ssl_verify_enabled()
    with exclusive_sync_lock(dest_root):
        data = _fetch_snapshot(url, token, timeout, verify)
        _observe_server_requirements(data)
        files = _snapshot_files(data)
        server_epoch = as_epoch(data.get("epoch"))
        auto_epoch = (not replace) and server_epoch > local_epoch()

        if replace or auto_epoch:
            pending: dict[str, Any] = {"files": {}, "project_rows": []}
            if auto_epoch:
                current = collect_sync_bundle(include_projects=True, memory_root=dest_root)
                pending = capture_pending(dest_root, current)
                # Keep an existing review queue even when it matches the baseline.
                # Replace would delete it when the snapshot does not have it yet.
                qpath = dest_root / EPOCH_QUESTIONS_REL
                if qpath.is_file():
                    held = dict(pending.get("files") or {})
                    held.setdefault(EPOCH_QUESTIONS_REL, qpath.read_text(encoding="utf-8"))
                    pending = {**pending, "files": held}
            report = apply_snapshot_replace(files, target_root=dest_root, apply_to_repos=True)
            staged: list[str] = []
            if auto_epoch:
                staged = stage_epoch_questions(dest_root, pending, server_epoch)
            # Snapshot is the store now. Old unsent deletions must not tombstone it.
            _clear_unsent_deletions(dest_root)
            save_tombstones(dest_root, normalize_tombstones(data.get("tombstones")))
            save_baseline(dest_root, collect_sync_bundle(include_projects=True, memory_root=dest_root))
            remember_epoch(server_epoch)
            touch_remote_config_sync_time()
            result = {
                "status": "ok",
                "replaced": True,
                "auto_epoch": auto_epoch,
                "epoch": server_epoch,
                "staged": staged,
                "total_files": len(files),
                "backup": report.get("backup"),
                "report": report,
            }
        else:
            current = collect_sync_bundle(include_projects=True, memory_root=dest_root)
            infer_from_baseline(dest_root, current)
            tombstones = _merged_pull_tombstones(dest_root, data)
            explicit = load_writes(dest_root)
            filtered = {
                k: v
                for k, v in files.items()
                if not file_blocked(
                    tombstones,
                    k,
                    explicit_files=explicit.get("files") or {},
                    explicit_prefixes=explicit.get("prefixes") or {},
                )
            }
            report = apply_sync_bundle(
                filtered,
                target_root=dest_root,
                apply_to_repos=True,
                tombstones=tombstones,
                writes=explicit,
            )
            save_baseline(dest_root, collect_sync_bundle(include_projects=True, memory_root=dest_root))
            remember_epoch(server_epoch)
            touch_remote_config_sync_time()
            result = {
                "status": "ok",
                "epoch": server_epoch,
                "total_files": len(filtered),
                "report": report,
            }
    return result


def remote_push_merge(
    url: str,
    token: str = "",
    source_dir: Optional[Path] = None,
    timeout: float = 30.0,
    verify_ssl: Optional[bool] = None,
    publish_absences: bool = False,
    replace: bool = False,
    _retry: bool = True,
) -> dict[str, Any]:
    """Upload local mirror bundle to remote server for deterministic merging.

    ``publish_absences`` (CLI ``remote push``) tombstones project rows and
    project-tree files the remote still has but this store does not, when this
    device has no sync baseline yet. Background pushes leave it off.

    ``replace=True`` (CLI ``remote push --replace``) makes the server store
    match this machine and bumps the vault epoch.

    A 409 epoch mismatch replace-pulls the snapshot and parks baseline-diverged
    edits in staging. It does not push those edits. With no baseline, nothing
    is parked (a stale vault must not replay itself).
    """
    root = source_dir or USER_MEMORY
    verify = verify_ssl if verify_ssl is not None else _is_ssl_verify_enabled()
    try:
        return _push_once(
            url,
            token=token,
            root=root,
            timeout=timeout,
            verify=verify,
            publish_absences=publish_absences and not replace,
            replace=replace,
        )
    except EpochMismatch:
        if replace or not _retry:
            raise
        # Adopt the server epoch. Do not write local diffs back or push them.
        return remote_pull(
            url,
            token=token,
            target_dir=root,
            timeout=timeout,
            verify_ssl=verify,
            replace=False,
        )


def _push_once(
    url: str,
    token: str,
    root: Path,
    timeout: float,
    verify: bool,
    publish_absences: bool,
    replace: bool,
) -> dict[str, Any]:
    clean_url = url.strip().rstrip("/")
    target = f"{clean_url}/api/v1/merge"
    with exclusive_sync_lock(root):
        headers = _get_auth_headers(token)
        stamps: dict[str, str] = {}
        local_files = collect_sync_bundle(
            include_projects=True,
            memory_root=root,
            stamps=stamps,
        )
        if not replace:
            infer_from_baseline(root, local_files)
            if publish_absences and load_baseline(root) is None:
                snap = _fetch_snapshot(url, token, timeout, verify)
                remote_files = snap.get("files") if isinstance(snap.get("files"), dict) else {}
                infer_remote_project_absences(root, local_files, remote_files)
                stamps = {}
                local_files = collect_sync_bundle(
                    include_projects=True,
                    memory_root=root,
                    stamps=stamps,
                )

        tombstones = load_tombstones(root)
        explicit = load_writes(root)
        send_files: dict[str, str] = {}
        for key, content in local_files.items():
            if not replace and file_blocked(
                tombstones,
                key,
                mtime=stamps.get(key),
                explicit_files=explicit.get("files") or {},
                explicit_prefixes=explicit.get("prefixes") or {},
            ):
                continue
            send_files[key] = content

        local_deleted = [] if replace else _pending_deletions(root)
        payload: dict[str, Any] = {
            "files": send_files,
            "deleted": local_deleted,
            "tombstones": tombstones,
            "epoch": local_epoch(),
            "writes": {
                "files": stamps,
                "explicit_files": explicit.get("files") or {},
                "prefixes": explicit.get("prefixes") or {},
                "rows": explicit.get("rows") or {},
                "bullets": explicit.get("bullets") or {},
            },
        }
        if replace:
            payload["replace"] = True

        with _get_http_client(timeout=timeout, verify_ssl=verify) as client:
            resp = client.post(target, json=payload, headers=headers)
            _raise_for_sync(resp)
            data = resp.json()

        if local_deleted:
            _clear_pending_deletions(root, local_deleted)
        if not replace:
            clear_writes(root)

        server_ts = normalize_tombstones(data.get("tombstones"))
        if not data.get("tombstones"):
            server_ts = merge_tombstones(tombstones, server_ts)
            for rel in data.get("deleted") or []:
                clean = str(rel).replace("\\", "/").strip().lstrip("/")
                if clean:
                    server_ts["files"].setdefault(clean, stamps.get(clean) or "1970-01-01T00:00:00Z")
        save_tombstones(root, server_ts)

        server_deleted = set(data.get("deleted") or [])
        server_snapshot = data.get("snapshot") or {}
        if not replace and isinstance(server_snapshot, dict) and server_snapshot:
            filtered_snapshot = {
                k: v
                for k, v in server_snapshot.items()
                if isinstance(v, str)
                and k not in server_deleted
                and not file_blocked(server_ts, str(k))
            }
            apply_sync_bundle(
                filtered_snapshot,
                target_root=root,
                apply_to_repos=True,
                tombstones=server_ts,
            )
        save_baseline(root, collect_sync_bundle(include_projects=True, memory_root=root))
        if "epoch" in data:
            remember_epoch(as_epoch(data.get("epoch")))
        touch_remote_config_sync_time()

        return {
            "status": "ok",
            "replaced": bool(data.get("replaced")),
            "epoch": as_epoch(data.get("epoch")),
            "server_report": data.get("report", {}),
            "total_files": len(server_snapshot) or len(send_files),
        }


def remote_bump_epoch(
    url: str,
    token: str = "",
    timeout: float = 30.0,
    verify_ssl: Optional[bool] = None,
) -> dict[str, Any]:
    """Ask the server to increment the vault epoch and remember the new value."""
    clean_url = url.strip().rstrip("/")
    verify = verify_ssl if verify_ssl is not None else _is_ssl_verify_enabled()
    headers = _get_auth_headers(token)
    with _get_http_client(timeout=timeout, verify_ssl=verify) as client:
        resp = client.post(f"{clean_url}/api/v1/epoch", headers=headers)
        _raise_for_sync(resp)
        data = resp.json()
    if isinstance(data, dict) and "epoch" in data:
        remember_epoch(as_epoch(data.get("epoch")))
    return data if isinstance(data, dict) else {"status": "ok"}


def remote_delete_file(
    url: str,
    path: str,
    token: str = "",
    timeout: float = 10.0,
    verify_ssl: Optional[bool] = None,
) -> bool:
    """Delete a memory file directly on the remote server via REST API."""
    clean_url = url.strip().rstrip("/")
    clean_path = urllib.parse.quote(path.replace("\\", "/").strip().lstrip("/"))
    target = f"{clean_url}/api/v1/file?path={clean_path}"
    headers = _get_auth_headers(token)
    verify = verify_ssl if verify_ssl is not None else _is_ssl_verify_enabled()

    with _get_http_client(timeout=timeout, verify_ssl=verify) as client:
        resp = client.delete(target, headers=headers)
        _raise_for_sync(resp)
        return resp.status_code == 200


def remote_mirror_injection(url: str, token: str = "") -> bool:
    """Pull key prompt files (USER.md, PROJECTS.md) quickly for local IDE cache."""
    try:
        remote_pull(url, token)
        return True
    except Exception:
        return False


async def run_client_bridge(
    url: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """Run bidirectional stdio-to-remote-SSE MCP bridge for local IDEs."""
    cfg = get_remote_config() or {}
    server_url = (url or cfg.get("url") or os.environ.get("AGENTS_MEMORY_URL", "")).strip().rstrip("/")
    server_token = (token or cfg.get("token") or os.environ.get("AGENTS_MEMORY_TOKEN", "")).strip()

    if not server_url:
        print(
            "Error: No remote memory URL configured. Run 'agents-memory remote connect <URL>' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Optional quick sync of prompt injection
    if cfg.get("auto_pull", True):
        try:
            remote_mirror_injection(server_url, server_token)
        except Exception:
            pass

    sse_url = f"{server_url}/sse"
    headers = _get_auth_headers(server_token)

    async with stdio_server() as (read_stdio, write_stdio):
        async with sse_client(sse_url, headers=headers) as (read_sse, write_sse):
            async with anyio.create_task_group() as tg:
                async def pipe_stdio_to_sse():
                    try:
                        async for message in read_stdio:
                            await write_sse.send(message)
                    except (anyio.ClosedResourceError, anyio.EndOfStream):
                        pass
                    except Exception as e:
                        print(f"Bridge stdio->sse error: {e}", file=sys.stderr)

                async def pipe_sse_to_stdio():
                    try:
                        async for message in read_sse:
                            await write_stdio.send(message)
                    except (anyio.ClosedResourceError, anyio.EndOfStream):
                        pass
                    except Exception as e:
                        print(f"Bridge sse->stdio error: {e}", file=sys.stderr)

                async def periodic_background_sync():
                    interval = float(cfg.get("sync_interval_seconds", 60))
                    while True:
                        await anyio.sleep(interval)
                        try:
                            await anyio.to_thread.run_sync(
                                remote_mirror_injection, server_url, server_token
                            )
                        except Exception:
                            pass

                tg.start_soon(pipe_stdio_to_sse)
                tg.start_soon(pipe_sse_to_stdio)
                if cfg.get("auto_pull", True):
                    tg.start_soon(periodic_background_sync)


ATTACH_FILE = USER_MEMORY / "board_attach.json"
FORBIDDEN_ATTACH_NAMES = {
    "user.md",
    "projects.md",
    "scan.json",
    "chats-index.md",
    "remote_config.json",
    "ingest.json",
    "board_attach.json",
}
ALLOWED_ATTACH_PREFIXES = (
    "decisions/",
    "plans/",
    "tasks/",
    "waves/",
    "roadmap/",
    "staging/",
    "notes/",
    "research/",
)


def board_memory_path_ok(rel: str) -> bool:
    rel = rel.replace("\\", "/").lower().lstrip("/")
    if rel == "" or ".." in rel or rel.startswith("."):
        return False
    if any(part.startswith(".") for part in rel.split("/")):
        return False
    if Path(rel).name.lower() in FORBIDDEN_ATTACH_NAMES:
        return False
    if not rel.endswith(".md"):
        return False
    return any(rel.startswith(p) for p in ALLOWED_ATTACH_PREFIXES)


def load_attaches() -> list[dict[str, Any]]:
    if not ATTACH_FILE.exists():
        return []
    try:
        data = json.loads(ATTACH_FILE.read_text(encoding="utf-8"))
        items = data.get("attaches") if isinstance(data, dict) else data
        return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []
    except Exception:
        return []


def save_attach(entry: dict[str, Any]) -> None:
    ensure_memory_layout()
    items = load_attaches()
    key = (entry.get("url") or "").rstrip("/")
    items = [x for x in items if (x.get("url") or "").rstrip("/") != key]
    items.append(entry)
    ATTACH_FILE.write_text(json.dumps({"attaches": items}, indent=2), encoding="utf-8")


def canonical_attach_url(url: str) -> str:
    u = url.strip().rstrip("/")
    if u.lower().endswith("/snapshot"):
        u = u[: -len("/snapshot")].rstrip("/")
    return u


def unregistered_attach_dest(url: str) -> Path:
    digest = hashlib.sha256(canonical_attach_url(url).encode("utf-8")).hexdigest()[:16]
    return (AGENTS_HOME / "shared" / "by-url" / digest).resolve()


def attach_dest_from_url(url: str, project: str = "") -> Path:
    """Registered clone ``.agents/memory`` when known; else opaque URL id (not a project name)."""
    wanted = project.strip()
    if not wanted:
        parsed = _slug_from_memory_url(canonical_attach_url(url))
        if parsed != "board":
            wanted = parsed
    if wanted:
        found = find_project(wanted)
        if found and found.path_obj.is_dir() and not is_engine_repo(found.path_obj):
            return found.memory_dir.resolve()
        if project.strip():
            raise ValueError(f"no registered project for {wanted!r}")
    return unregistered_attach_dest(url)


def _slug_from_memory_url(url: str) -> str:
    parts = urllib.parse.urlparse(url).path.strip("/").split("/")
    if "projects" in parts:
        i = parts.index("projects")
        if i + 1 < len(parts):
            return parts[i + 1]
    return "board"


def board_origin(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("board URL needs a host")
    return f"{parsed.scheme}://{parsed.netloc}"


def keys_cli(*args: str) -> str:
    """Shell out to agents-keys. Sign/mint live in that process, not this MCP."""
    proc = subprocess.run(
        [sys.executable, "-m", "agents_keys", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "agents-keys failed").strip()
        raise RuntimeError(err)
    return proc.stdout.strip()


def board_did_session(client: httpx.Client, origin: str, slug: str) -> str:
    """Challenge/sign/verify. Leaves board_sid on the client cookie jar. Returns did:key."""
    did = keys_cli("did", slug)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": f"agents-memory-client/{__version__}",
    }
    ch = client.post(
        f"{origin}/login",
        json={"verb": "challenge", "did": did},
        headers=headers,
    )
    if ch.status_code >= 400:
        raise PermissionError(f"challenge failed: {ch.text}")
    body = ch.json()
    nonce = str(body.get("nonce") or "")
    if nonce == "":
        raise PermissionError(f"challenge failed: {ch.text}")
    signature = keys_cli("sign", slug, nonce)
    ver = client.post(
        f"{origin}/login",
        json={
            "verb": "verify",
            "did": did,
            "nonce": nonce,
            "signature": signature,
        },
        headers=headers,
    )
    if ver.status_code == 403:
        raise PermissionError("This DID is not a user on this board.")
    if ver.status_code >= 400:
        raise PermissionError(f"verify failed: {ver.text}")
    return did


def board_attach(
    url: str,
    token: str = "",
    dest_dir: Optional[Path] = None,
    timeout: float = 30.0,
    verify_ssl: Optional[bool] = None,
    project: str = "",
    slug: str = "",
) -> dict[str, Any]:
    """Pull a board project memory snapshot into a directory that is not USER_MEMORY."""
    clean_url = canonical_attach_url(url)
    snap = f"{clean_url}/snapshot"
    dest = dest_dir or attach_dest_from_url(clean_url, project=project)
    dest = dest.expanduser().resolve()
    personal = USER_MEMORY.resolve()
    if dest == personal or personal in dest.parents:
        raise ValueError("attach dir must not be inside the personal memory store")
    if dest.name == "memory" and dest.parent.name == ".agents":
        ensure_repo_agents_gitignored(dest.parent.parent)
    slug = slug.strip()
    token = token.strip()
    if slug == "" and token == "":
        raise ValueError(
            "pass --slug <agent> (file ~/.agents/keys/<slug>.ed25519). "
            "--token is a spare door, not the model."
        )
    verify = verify_ssl if verify_ssl is not None else _is_ssl_verify_enabled()
    headers = _get_auth_headers(token)
    headers["Accept"] = "application/json"
    did = ""

    with _get_http_client(timeout=timeout, verify_ssl=verify) as client:
        if slug:
            did = board_did_session(client, board_origin(clean_url), slug)
            headers.pop("Authorization", None)
        resp = client.get(snap, headers=headers)
        if resp.status_code == 401:
            raise PermissionError("Unauthorized: board rejected this principal.")
        if resp.status_code == 403:
            raise PermissionError("Forbidden: this principal has no memory.read on that project.")
        resp.raise_for_status()
        data = resp.json()

    files = data.get("files") or {}
    allowed: dict[str, str] = {}
    skipped: list[str] = []
    for rel, content in files.items():
        if isinstance(content, str) and board_memory_path_ok(str(rel)):
            allowed[str(rel).replace("\\", "/")] = content
        else:
            skipped.append(str(rel))

    dest.mkdir(parents=True, exist_ok=True)
    report = merge_file_trees(dest, allowed)
    report["skipped"] = skipped
    local_slug = project.strip() or _slug_from_memory_url(clean_url)
    found = find_project(local_slug) if local_slug else None
    entry: dict[str, Any] = {
        "url": clean_url,
        "dir": str(dest),
        "project": found.slug if found else "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if slug:
        entry["slug"] = slug
        entry["did"] = did
    save_attach(entry)
    return {"status": "ok", "dir": str(dest), "project": found.slug if found else "", "did": did, "report": report}


def main_bridge() -> int:
    """Entrypoint for `python -m agents_memory remote client` (mirror sync MCP)."""
    from .sync_mcp import main as sync_main

    return sync_main()
