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
from .sync_bundle import apply_sync_bundle, collect_sync_bundle

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
        if resp.status_code == 401:
            raise PermissionError("Unauthorized: Token rejected by remote server.")
        resp.raise_for_status()
        return resp.json()


def remote_pull(
    url: str,
    token: str = "",
    target_dir: Optional[Path] = None,
    timeout: float = 30.0,
    verify_ssl: Optional[bool] = None,
) -> dict[str, Any]:
    """Download memory snapshot from remote and update target directory."""
    clean_url = url.strip().rstrip("/")
    target = f"{clean_url}/api/v1/snapshot"
    headers = _get_auth_headers(token)
    dest_root = target_dir or USER_MEMORY
    verify = verify_ssl if verify_ssl is not None else _is_ssl_verify_enabled()

    with _get_http_client(timeout=timeout, verify_ssl=verify) as client:
        resp = client.get(target, headers=headers)
        if resp.status_code == 401:
            raise PermissionError("Unauthorized: Token rejected by remote server.")
        resp.raise_for_status()
        data = resp.json()

    files = data.get("files", {})
    report = apply_sync_bundle(files, target_root=dest_root, apply_to_repos=True)

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
    verify_ssl: Optional[bool] = None,
) -> dict[str, Any]:
    """Upload local mirror bundle to remote server for deterministic merging."""
    clean_url = url.strip().rstrip("/")
    target = f"{clean_url}/api/v1/merge"
    headers = _get_auth_headers(token)
    verify = verify_ssl if verify_ssl is not None else _is_ssl_verify_enabled()

    local_files = collect_sync_bundle(
        include_projects=True,
        memory_root=source_dir or USER_MEMORY,
    )
    payload = {"files": local_files}

    with _get_http_client(timeout=timeout, verify_ssl=verify) as client:
        resp = client.post(target, json=payload, headers=headers)
        if resp.status_code == 401:
            raise PermissionError("Unauthorized: Token rejected by remote server.")
        resp.raise_for_status()
        data = resp.json()

    server_snapshot = data.get("snapshot", {})
    if server_snapshot:
        apply_sync_bundle(server_snapshot, target_root=USER_MEMORY, apply_to_repos=True)

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


def _slug_from_memory_url(url: str) -> str:
    parts = urllib.parse.urlparse(url).path.strip("/").split("/")
    if "projects" in parts:
        i = parts.index("projects")
        if i + 1 < len(parts):
            return parts[i + 1]
    return "board"


def board_attach(
    url: str,
    token: str = "",
    dest_dir: Optional[Path] = None,
    timeout: float = 30.0,
    verify_ssl: Optional[bool] = None,
) -> dict[str, Any]:
    """Pull a board project memory snapshot into a directory that is not USER_MEMORY."""
    clean_url = url.strip().rstrip("/")
    snap = clean_url if clean_url.endswith("/snapshot") else f"{clean_url}/snapshot"
    slug = _slug_from_memory_url(clean_url)
    dest = dest_dir or (Path.home() / ".agents" / "board-memory" / slug)
    dest = dest.expanduser().resolve()
    personal = USER_MEMORY.resolve()
    if dest == personal or personal in dest.parents:
        raise ValueError("attach dir must not be inside the personal memory store")
    verify = verify_ssl if verify_ssl is not None else _is_ssl_verify_enabled()
    headers = _get_auth_headers(token)
    headers["Accept"] = "application/json"

    with _get_http_client(timeout=timeout, verify_ssl=verify) as client:
        resp = client.get(snap, headers=headers)
        if resp.status_code == 401:
            raise PermissionError("Unauthorized: Token rejected by board.")
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
    save_attach({
        "url": clean_url,
        "token": token,
        "dir": str(dest),
        "slug": slug,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "ok", "dir": str(dest), "slug": slug, "report": report}


def main_bridge() -> int:
    """Entrypoint for `python -m agents_memory remote client` (mirror sync MCP)."""
    from .sync_mcp import main as sync_main

    return sync_main()
