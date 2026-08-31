"""Remote MCP & Cloud Sync Server for agents-memory."""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Optional

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
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
from .merge import merge_file_trees


def get_all_memory_files(memory_dir: Optional[Path] = None) -> dict[str, str]:
    """Collect all relative path -> text content pairs under memory_dir."""
    root = memory_dir or USER_MEMORY
    if not root.exists():
        return {}

    files: dict[str, str] = {}
    for p in root.rglob("*"):
        if p.is_file():
            # Skip hidden, git, cache, lock files
            rel = p.relative_to(root).as_posix()
            if any(part.startswith(".") for part in p.parts):
                continue
            if p.suffix in (".sqlite", ".db", ".lock", ".tmp", ".pyc"):
                continue
            try:
                files[rel] = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    return files


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate requests via Bearer token header or token query parameter."""

    def __init__(self, app, expected_token: str = ""):
        super().__init__(app)
        self.expected_token = expected_token.strip()

    async def dispatch(self, request: Request, call_next):
        if not self.expected_token:
            return await call_next(request)

        # Allow open preflight CORS if any
        if request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif "token" in request.query_params:
            token = request.query_params["token"].strip()

        if not token or not secrets.compare_digest(token, self.expected_token):
            return JSONResponse(
                {"error": "Unauthorized: invalid or missing token"},
                status_code=401,
            )

        return await call_next(request)


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

    report = merge_file_trees(USER_MEMORY, incoming_files)
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

    # FastMCP SSE sub-app
    sse_subapp = mcp.sse_app()

    routes = [
        Route("/health", health_endpoint, methods=["GET"]),
        Route("/api/v1/health", health_endpoint, methods=["GET"]),
        Route("/api/v1/snapshot", snapshot_endpoint, methods=["GET"]),
        Route("/api/v1/merge", merge_endpoint, methods=["POST"]),
        Route("/api/v1/file", get_file_endpoint, methods=["GET"]),
        Route("/api/v1/file", put_file_endpoint, methods=["POST", "PUT"]),
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
