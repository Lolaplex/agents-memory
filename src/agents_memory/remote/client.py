"""Client utilities, sync client, and Stdio-to-Remote SSE bridge."""
from __future__ import annotations

import json
import os
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
    USER_MEMORY,
    ensure_memory_layout,
    sync_injection,
)
from .merge import merge_file_trees

CONFIG_FILE = USER_MEMORY / "remote_config.json"


def get_remote_config() -> Optional[dict[str, Any]]:
    """Load remote sync configuration if present."""
    if not CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
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
    cfg = {
        "url": clean_url,
        "token": token.strip(),
        "auto_pull": auto_pull,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        cfg.update(extra)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def clear_remote_config() -> bool:
    """Remove remote configuration (disconnect from cloud)."""
    if CONFIG_FILE.exists():
        try:
            CONFIG_FILE.unlink()
            return True
        except Exception:
            return False
    return False


def _get_auth_headers(token: str) -> dict[str, str]:
    headers = {"User-Agent": f"agents-memory-client/{__version__}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def remote_health_check(url: str, token: str = "", timeout: float = 10.0) -> dict[str, Any]:
    """Check connectivity and authentication against remote memory server."""
    clean_url = url.strip().rstrip("/")
    target = f"{clean_url}/api/v1/health"
    headers = _get_auth_headers(token)

    with httpx.Client(timeout=timeout) as client:
        resp = client.get(target, headers=headers)
        if resp.status_code == 401:
            raise PermissionError("Unauthorized: Token rejected by remote server.")
        resp.raise_for_status()
        return resp.json()


def remote_pull(
    url: str,
    token: str = "",
    target_dir: Optional[Path] = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Download memory snapshot from remote and update target directory."""
    clean_url = url.strip().rstrip("/")
    target = f"{clean_url}/api/v1/snapshot"
    headers = _get_auth_headers(token)
    dest_root = target_dir or USER_MEMORY

    with httpx.Client(timeout=timeout) as client:
        resp = client.get(target, headers=headers)
        if resp.status_code == 401:
            raise PermissionError("Unauthorized: Token rejected by remote server.")
        resp.raise_for_status()
        data = resp.json()

    files = data.get("files", {})
    report = merge_file_trees(dest_root, files)

    try:
        sync_injection()
    except Exception:
        pass

    return {
        "status": "ok",
        "total_files": len(files),
        "report": report,
    }


def remote_push_merge(
    url: str,
    token: str = "",
    source_dir: Optional[Path] = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Upload local memory files to remote server for deterministic merging."""
    from .server import get_all_memory_files

    clean_url = url.strip().rstrip("/")
    target = f"{clean_url}/api/v1/merge"
    headers = _get_auth_headers(token)
    src_root = source_dir or USER_MEMORY

    local_files = get_all_memory_files(src_root)
    payload = {"files": local_files}

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(target, json=payload, headers=headers)
        if resp.status_code == 401:
            raise PermissionError("Unauthorized: Token rejected by remote server.")
        resp.raise_for_status()
        data = resp.json()

    # Mirror server response back locally
    server_snapshot = data.get("snapshot", {})
    if server_snapshot:
        merge_file_trees(src_root, server_snapshot)
        try:
            sync_injection()
        except Exception:
            pass

    return {
        "status": "ok",
        "server_report": data.get("report", {}),
        "total_files": len(server_snapshot) or len(local_files),
    }


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

                tg.start_soon(pipe_stdio_to_sse)
                tg.start_soon(pipe_sse_to_stdio)


def main_bridge() -> int:
    """Entrypoint for `python -m agents_memory remote client`."""
    try:
        anyio.run(run_client_bridge)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"agents-memory client error: {e}", file=sys.stderr)
        return 1
