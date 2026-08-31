"""Remote MCP & Cloud Sync Server for agents-memory."""
from __future__ import annotations

import inspect
import json
import os
import secrets
from pathlib import Path
from typing import Any, Optional

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from .. import __version__
from ..mcp_server import mcp
from ..store import (
    USER_MEMORY,
    ensure_memory_layout,
    sync_injection,
)
from .locality import INGEST_TOOLS, LOCAL_TOOLS, assert_ingest_runs_locally
from .sync_bundle import apply_sync_bundle, collect_sync_bundle, get_all_memory_files

os.environ.setdefault("AGENTS_MEMORY_REMOTE_SERVER", "1")


def get_all_memory_files(memory_dir: Optional[Path] = None) -> dict[str, str]:
    """Collect full mirror sync bundle (user store + rules + stored project mirrors)."""
    return collect_sync_bundle(include_projects=True, memory_root=memory_dir or USER_MEMORY)


class TokenAuthMiddleware:
    """Authenticate requests via Bearer token header or token query parameter (pure ASGI)."""

    def __init__(self, app, expected_token: str = ""):
        self.app = app
        self.expected_token = expected_token.strip()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.expected_token:
            return await self.app(scope, receive, send)

        request = Request(scope)
        # Allow open preflight CORS if any
        if request.method == "OPTIONS":
            return await self.app(scope, receive, send)

        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif "token" in request.query_params:
            token = request.query_params["token"].strip()

        if not token or not secrets.compare_digest(token, self.expected_token):
            response = JSONResponse(
                {"error": "Unauthorized: invalid or missing token"},
                status_code=401,
            )
            return await response(scope, receive, send)

        return await self.app(scope, receive, send)


async def health_endpoint(request: Request) -> JSONResponse:
    """Return health status and basic memory stats."""
    ensure_memory_layout()
    files = get_all_memory_files()
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "files_count": len(files),
            "store_path": str(USER_MEMORY),
        }
    )


async def snapshot_endpoint(request: Request) -> JSONResponse:
    """Download full snapshot of memory files."""
    ensure_memory_layout()
    files = get_all_memory_files()
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "files": files,
        }
    )


async def merge_endpoint(request: Request) -> JSONResponse:
    """Receive incoming memory files and deterministically merge them into server store."""
    ensure_memory_layout()
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

    incoming_files = data.get("files", {})
    if not isinstance(incoming_files, dict):
        return JSONResponse({"error": "Expected 'files' dictionary"}, status_code=400)

    report = apply_sync_bundle(incoming_files, target_root=USER_MEMORY, apply_to_repos=False)
    # Sync always-on injection after merge
    try:
        sync_injection()
    except Exception:
        pass

    current_snapshot = get_all_memory_files()
    return JSONResponse(
        {
            "status": "ok",
            "report": report,
            "snapshot": current_snapshot,
        }
    )


async def get_file_endpoint(request: Request) -> Response:
    """Read a single memory file."""
    rel_path = request.query_params.get("path", "").strip().lstrip("/\\")
    if not rel_path or ".." in rel_path:
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    target = (USER_MEMORY / rel_path).resolve()
    try:
        if not target.is_relative_to(USER_MEMORY.resolve()):
            return JSONResponse({"error": "Forbidden path traversal"}, status_code=403)
    except AttributeError:
        # Python < 3.9 fallback
        if not str(target).startswith(str(USER_MEMORY.resolve())):
            return JSONResponse({"error": "Forbidden path traversal"}, status_code=403)

    if not target.is_file():
        return JSONResponse({"error": "File not found"}, status_code=404)

    content = target.read_text(encoding="utf-8", errors="replace")
    return Response(content, media_type="text/plain; charset=utf-8")


def _mcp_tool_handlers() -> dict[str, Any]:
    """Map MCP tool names to callables from the reference server module."""
    from .. import mcp_server as ms

    names = [
        "search_memory",
        "add_memory",
        "read_memory_file",
        "write_memory_file",
        "auto_distill",
        "promote_bullet",
        "get_staging_inbox",
        "distill_batch",
        "get_project_memories",
        "delete_memory",
        "list_projects",
        "inventory_projects",
        "register_project",
        "ignore_project",
        "sync_local_agents_md",
        "ingest_catalog",
        "ingest_extract",
        "ingest_status",
        "get_baton",
        "set_baton",
        "append_chronicle",
        "session_snap",
        "session_grep",
        "session_tail",
        "rebuild_index",
        "search_hybrid",
        "get_related",
        "suggest_links",
        "check_memory_freshness",
    ]
    out: dict[str, Any] = {}
    for name in names:
        fn = getattr(ms, name, None)
        if callable(fn):
            out[name] = fn
    return out


async def tool_call_endpoint(request: Request) -> JSONResponse:
    """Execute one MCP tool on the canonical remote store."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

    name = str(data.get("name") or "").strip()
    arguments = data.get("arguments") or {}
    if not name:
        return JSONResponse({"error": "Missing tool name"}, status_code=400)
    if not isinstance(arguments, dict):
        return JSONResponse({"error": "arguments must be an object"}, status_code=400)

    if name in INGEST_TOOLS:
        try:
            assert_ingest_runs_locally()
        except RuntimeError as e:
            return JSONResponse({"error": str(e), "locality": "local"}, status_code=400)

    handlers = _mcp_tool_handlers()
    handler = handlers.get(name)
    if not handler:
        return JSONResponse({"error": f"Unknown tool: {name}"}, status_code=404)

    try:
        sig = inspect.signature(handler)
        filtered = {
            k: v for k, v in arguments.items() if k in sig.parameters
        }
        result = handler(**filtered)
        if not isinstance(result, str):
            result = json.dumps(result, indent=2, ensure_ascii=False)
        return JSONResponse({"status": "ok", "result": result})
    except Exception as e:
        return JSONResponse({"error": str(e), "tool": name}, status_code=500)


async def put_file_endpoint(request: Request) -> JSONResponse:
    """Write/merge a single memory file."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

    rel_path = str(data.get("path", "")).strip().lstrip("/\\")
    content = str(data.get("content", ""))
    if not rel_path or ".." in rel_path:
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    target = (USER_MEMORY / rel_path).resolve()
    try:
        if not target.is_relative_to(USER_MEMORY.resolve()):
            return JSONResponse({"error": "Forbidden path traversal"}, status_code=403)
    except AttributeError:
        if not str(target).startswith(str(USER_MEMORY.resolve())):
            return JSONResponse({"error": "Forbidden path traversal"}, status_code=403)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    try:
        sync_injection()
    except Exception:
        pass

    return JSONResponse({"status": "ok", "path": rel_path})


def create_remote_app(token: str = "") -> Starlette:
    """Create the unified Starlette app containing REST sync endpoints and SSE FastMCP."""
    ensure_memory_layout()
    token = token or os.environ.get("AGENTS_MEMORY_TOKEN", "")

    # FastMCP SSE sub-app (disable DNS rebinding host checks for domain / reverse proxy traffic)
    try:
        from mcp.server.transport_security import TransportSecuritySettings

        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
    except Exception:
        pass

    sse_subapp = mcp.sse_app()

    routes = [
        Route("/health", health_endpoint, methods=["GET"]),
        Route("/api/v1/health", health_endpoint, methods=["GET"]),
        Route("/api/v1/snapshot", snapshot_endpoint, methods=["GET"]),
        Route("/api/v1/merge", merge_endpoint, methods=["POST"]),
        Route("/api/v1/file", get_file_endpoint, methods=["GET"]),
        Route("/api/v1/file", put_file_endpoint, methods=["POST", "PUT"]),
        Route("/api/v1/tool", tool_call_endpoint, methods=["POST"]),
        # Mount FastMCP SSE under root or /mcp
        Mount("", app=sse_subapp),
    ]

    middleware = []
    if token:
        middleware.append(Middleware(TokenAuthMiddleware, expected_token=token))

    return Starlette(routes=routes, middleware=middleware)


def run_server(
    host: str = "0.0.0.0",
    port: int = 8443,
    token: str = "",
    log_level: str = "info",
) -> None:
    """Run the memory cloud server."""
    ensure_memory_layout()
    token = token or os.environ.get("AGENTS_MEMORY_TOKEN", "")
    app = create_remote_app(token=token)

    masked_token = (token[:4] + "..." + token[-4:]) if len(token) > 8 else ("***" if token else "NONE (open)")
    print("=" * 60)
    print(f"  AGENTS-MEMORY CLOUD & REMOTE MCP SERVER (v{__version__})")
    print(f"  Listen   : http://{host}:{port}")
    print(f"  SSE MCP  : http://{host}:{port}/sse")
    print(f"  Auth     : Bearer {masked_token}")
    print(f"  Store    : {USER_MEMORY}")
    print("=" * 60)

    uvicorn.run(app, host=host, port=port, log_level=log_level)
