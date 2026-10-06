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
from .sync_bundle import apply_sync_bundle, collect_sync_bundle, enforce_tombstones
from .protocol import (
    as_epoch,
    bump_epoch,
    load_epoch,
    min_client_version,
    update_hint,
    upgrade_required_message,
    version_older,
)
from .tombstones import (
    absorb_deleted_list,
    compact,
    diff_projects_text,
    empty_tombstones,
    empty_writes,
    file_blocked,
    file_tombstone_paths,
    load_tombstones,
    load_writes,
    merge_tombstones,
    normalize_tombstones,
    normalize_writes,
    now_iso,
    record_explicit_file_write,
    record_file,
    revive,
    save_tombstones,
    save_writes,
)

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


def _protocol_fields() -> dict[str, Any]:
    minimum = min_client_version()
    return {
        "epoch": load_epoch(USER_MEMORY),
        "min_client_version": minimum,
        "update_hint": update_hint() if minimum else "",
    }


def _reject_old_client(request: Request) -> Optional[JSONResponse]:
    """426 for writers below ``min_client_version``, including a missing header."""
    minimum = min_client_version()
    if not minimum:
        return None
    client_version = request.headers.get("x-agents-memory-version", "").strip()
    if client_version and not version_older(client_version, minimum):
        return None
    message = upgrade_required_message(minimum)
    return JSONResponse(
        {
            "error": message,
            "min_client_version": minimum,
            "update": update_hint(),
        },
        status_code=426,
    )


def _client_epoch(request: Request, body: Any) -> int:
    raw = request.headers.get("x-agents-memory-epoch")
    if raw is not None and str(raw).strip() != "":
        return as_epoch(raw)
    if isinstance(body, dict) and "epoch" in body:
        return as_epoch(body.get("epoch"))
    return 0


def _reject_old_epoch(request: Request, body: Any) -> Optional[JSONResponse]:
    """409 when the writer last synced an older vault epoch. Epoch 0 accepts everyone."""
    server_epoch = load_epoch(USER_MEMORY)
    client_epoch = _client_epoch(request, body)
    if client_epoch >= server_epoch:
        return None
    message = (
        f"vault epoch {client_epoch} is behind server epoch {server_epoch}. "
        "Replace-pull the snapshot before writing. Do not push the old vault over the new epoch."
    )
    return JSONResponse(
        {
            "error": message,
            "code": "epoch_mismatch",
            "epoch": server_epoch,
            "client_epoch": client_epoch,
        },
        status_code=409,
    )


async def health_endpoint(request: Request) -> JSONResponse:
    """Return health status and basic memory stats."""
    ensure_memory_layout()
    files = get_all_memory_files()
    body = {
        "status": "ok",
        "version": __version__,
        "files_count": len(files),
        "store_path": str(USER_MEMORY),
    }
    body.update(_protocol_fields())
    return JSONResponse(body)


def _tombstones_file() -> Path:
    return USER_MEMORY / ".tombstones.json"


def record_server_tombstone(rel_path: str) -> None:
    """Record a deletion tombstone on the server."""
    record_file(USER_MEMORY, rel_path)


def get_server_tombstones() -> list[str]:
    """Active file-tombstone paths (legacy list). Full document is ``tombstones``."""
    return file_tombstone_paths(load_tombstones(USER_MEMORY))


def _prepare_server_tombstones(incoming: Any = None, deleted: Any = None, writes: Any = None, mtimes: Any = None) -> dict:
    """Merge client tombstones, honor old ``deleted`` lists, revive newer writes, compact."""
    server_ts = load_tombstones(USER_MEMORY)
    merged = merge_tombstones(server_ts, normalize_tombstones(incoming))
    merged = absorb_deleted_list(merged, deleted, when=now_iso())
    explicit = normalize_writes(writes if isinstance(writes, dict) else {})
    # Push payload uses ``files`` for mtimes and ``explicit_files`` for re-adds.
    if isinstance(writes, dict) and isinstance(writes.get("explicit_files"), dict):
        explicit = normalize_writes({"explicit_files": writes.get("explicit_files"), "prefixes": writes.get("prefixes"), "rows": writes.get("rows"), "bullets": writes.get("bullets")})
    mt = mtimes if isinstance(mtimes, dict) else {}
    if not mt and isinstance(writes, dict) and isinstance(writes.get("files"), dict) and "explicit_files" in writes:
        mt = {str(k): str(v) for k, v in writes["files"].items() if isinstance(v, str)}
    merged = revive(merged, explicit, mtimes=mt)
    merged = compact(merged)
    save_tombstones(USER_MEMORY, merged)
    return merged


def _persist_client_writes(payload: Any) -> None:
    """Keep explicit re-adds so a later snapshot does not re-delete them under a prefix."""
    if not isinstance(payload, dict):
        return
    from .tombstones import norm_rel as _norm

    current = load_writes(USER_MEMORY)
    explicit = payload.get("explicit_files") if isinstance(payload.get("explicit_files"), dict) else {}
    for key, stamp in explicit.items():
        if not isinstance(stamp, str):
            continue
        rel = _norm(str(key))
        prev = current["files"].get(rel)
        if rel and (prev is None or stamp > prev):
            current["files"][rel] = stamp
    prefixes = payload.get("prefixes") if isinstance(payload.get("prefixes"), dict) else {}
    for key, stamp in prefixes.items():
        if not isinstance(stamp, str):
            continue
        rel = _norm(str(key))
        if rel and not rel.endswith("/"):
            rel += "/"
        prev = current["prefixes"].get(rel)
        if rel and (prev is None or stamp > prev):
            current["prefixes"][rel] = stamp
    rows = payload.get("rows") if isinstance(payload.get("rows"), dict) else {}
    for file_key, mapping in rows.items():
        if not isinstance(mapping, dict):
            continue
        bucket = current["rows"].setdefault(str(file_key), {})
        for pk, stamp in mapping.items():
            if isinstance(stamp, str) and str(pk).strip():
                name = str(pk).strip().lower()
                prev = bucket.get(name)
                if prev is None or stamp > prev:
                    bucket[name] = stamp
    save_writes(USER_MEMORY, current)


def _snapshot_files(tombstones: dict) -> dict[str, str]:
    writes = load_writes(USER_MEMORY)
    enforce_tombstones(USER_MEMORY, tombstones, writes=writes, apply_to_repos=False)
    files = collect_sync_bundle(include_projects=True, memory_root=USER_MEMORY)
    kept = {}
    for key, content in files.items():
        if file_blocked(
            tombstones,
            key,
            explicit_files=writes.get("files") or {},
            explicit_prefixes=writes.get("prefixes") or {},
        ):
            continue
        kept[key] = content
    return kept


async def snapshot_endpoint(request: Request) -> JSONResponse:
    """Download full snapshot of memory files and active deletions."""
    ensure_memory_layout()
    tombstones = compact(load_tombstones(USER_MEMORY))
    save_tombstones(USER_MEMORY, tombstones)
    files = _snapshot_files(tombstones)
    body = {
        "status": "ok",
        "version": __version__,
        "files": files,
        "deleted": file_tombstone_paths(tombstones),
        "tombstones": tombstones,
    }
    body.update(_protocol_fields())
    return JSONResponse(body)


def _replace_server_store(incoming_files: dict[str, str]) -> JSONResponse:
    """Make the server store match the client bundle, then bump the vault epoch."""
    from .sync_bundle import apply_snapshot_replace

    files = {
        str(rel).replace("\\", "/").lstrip("/"): content
        for rel, content in incoming_files.items()
        if isinstance(content, str)
    }
    report = apply_snapshot_replace(files, target_root=USER_MEMORY, apply_to_repos=False)
    save_tombstones(USER_MEMORY, empty_tombstones())
    save_writes(USER_MEMORY, empty_writes())
    epoch = bump_epoch(USER_MEMORY)
    fresh = load_tombstones(USER_MEMORY)
    snapshot = _snapshot_files(fresh)
    body = {
        "status": "ok",
        "replaced": True,
        "epoch": epoch,
        "report": report,
        "snapshot": snapshot,
        "deleted": [],
        "tombstones": fresh,
    }
    body.update(_protocol_fields())
    body["epoch"] = epoch
    return JSONResponse(body)


async def merge_endpoint(request: Request) -> JSONResponse:
    """Receive incoming memory files and deterministically merge them into server store."""
    ensure_memory_layout()
    denied = _reject_old_client(request)
    if denied is not None:
        return denied
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)

    incoming_files = data.get("files", {})
    if not isinstance(incoming_files, dict):
        return JSONResponse({"error": "Expected 'files' dictionary"}, status_code=400)

    if data.get("replace") is True:
        return _replace_server_store(incoming_files)

    denied = _reject_old_epoch(request, data)
    if denied is not None:
        return denied

    # Tombstones first, so an old client pushing stale bytes cannot resurrect them.
    tombstones = _prepare_server_tombstones(
        incoming=data.get("tombstones"),
        deleted=data.get("deleted"),
        writes=data.get("writes"),
    )
    _persist_client_writes(data.get("writes"))
    kept_writes = load_writes(USER_MEMORY)
    filtered: dict[str, str] = {}
    for rel, content in incoming_files.items():
        rel_clean = str(rel).replace("\\", "/").lstrip("/")
        mtime = None
        explicit = {}
        prefixes = kept_writes.get("prefixes") or {}
        if isinstance(data.get("writes"), dict):
            raw_files = data["writes"].get("files") or {}
            if isinstance(raw_files, dict):
                mtime = raw_files.get(rel_clean)
            raw_explicit = data["writes"].get("explicit_files") or {}
            if isinstance(raw_explicit, dict):
                explicit = raw_explicit
            raw_prefixes = data["writes"].get("prefixes") or {}
            if isinstance(raw_prefixes, dict):
                prefixes = {**prefixes, **raw_prefixes}
        explicit = {**(kept_writes.get("files") or {}), **explicit}
        if file_blocked(
            tombstones,
            rel_clean,
            mtime=str(mtime) if isinstance(mtime, str) else None,
            explicit_files=explicit,
            explicit_prefixes=prefixes,
        ):
            continue
        if isinstance(content, str):
            filtered[rel_clean] = content

    report = apply_sync_bundle(
        filtered,
        target_root=USER_MEMORY,
        apply_to_repos=False,
        tombstones=tombstones,
        writes={
            "explicit_files": {**(kept_writes.get("files") or {}), **((data.get("writes") or {}).get("explicit_files") or {})},
            "prefixes": {**(kept_writes.get("prefixes") or {}), **((data.get("writes") or {}).get("prefixes") or {})},
            "rows": (data.get("writes") or {}).get("rows") if isinstance(data.get("writes"), dict) else {},
            "bullets": (data.get("writes") or {}).get("bullets") if isinstance(data.get("writes"), dict) else {},
        },
    )

    deleted_report: list[str] = []
    requested = data.get("deleted") if isinstance(data.get("deleted"), list) else []
    for rel in requested:
        rel_clean = str(rel).replace("\\", "/").strip().lstrip("/")
        if not rel_clean or ".." in rel_clean:
            continue
        target = (USER_MEMORY / rel_clean).resolve()
        try:
            inside = target.is_relative_to(USER_MEMORY.resolve())
        except AttributeError:
            inside = str(target).startswith(str(USER_MEMORY.resolve()))
        if not inside:
            continue
        if target.is_file():
            target.unlink()
        deleted_report.append(rel_clean)
    for rel in report.get("removed") or []:
        if rel not in deleted_report:
            deleted_report.append(rel)
    report["deleted"] = deleted_report

    try:
        sync_injection()
    except Exception:
        pass

    current_snapshot = _snapshot_files(load_tombstones(USER_MEMORY))
    fresh = load_tombstones(USER_MEMORY)
    body = {
        "status": "ok",
        "report": report,
        "snapshot": current_snapshot,
        "deleted": file_tombstone_paths(fresh),
        "tombstones": fresh,
    }
    body.update(_protocol_fields())
    return JSONResponse(body)


async def delete_file_endpoint(request: Request) -> JSONResponse:
    """Delete a single memory file directly via DELETE /api/v1/file?path=..."""
    denied = _reject_old_client(request)
    if denied is not None:
        return denied
    denied = _reject_old_epoch(request, None)
    if denied is not None:
        return denied
    rel_path = request.query_params.get("path", "").strip().lstrip("/\\")
    if not rel_path or ".." in rel_path:
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    target = (USER_MEMORY / rel_path).resolve()
    try:
        if not target.is_relative_to(USER_MEMORY.resolve()):
            return JSONResponse({"error": "Forbidden path traversal"}, status_code=403)
    except AttributeError:
        if not str(target).startswith(str(USER_MEMORY.resolve())):
            return JSONResponse({"error": "Forbidden path traversal"}, status_code=403)

    existed = target.is_file()
    if existed:
        target.unlink()

    record_server_tombstone(rel_path)
    try:
        sync_injection()
    except Exception:
        pass
    return JSONResponse({"status": "ok", "deleted": rel_path, "existed": existed})


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
        "get_staging_inbox",
        "distill_batch",
        "get_project_memories",
        "delete_memory",
        "list_projects",
        "inventory_projects",
        "register_project",
        "ignore_project",
        "sync_local_agents_md",
        "get_related",
    ]
    out: dict[str, Any] = {}
    for name in names:
        fn = getattr(ms, name, None)
        if callable(fn):
            out[name] = fn
    return out


async def tool_call_endpoint(request: Request) -> JSONResponse:
    """Execute one MCP tool on the canonical remote store."""
    denied = _reject_old_client(request)
    if denied is not None:
        return denied
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
    denied = _reject_old_client(request)
    if denied is not None:
        return denied
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload"}, status_code=400)
    denied = _reject_old_epoch(request, data)
    if denied is not None:
        return denied

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

    previous = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
    record_explicit_file_write(USER_MEMORY, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if Path(rel_path).name.lower() == "projects.md":
        diff_projects_text(USER_MEMORY, previous, content)

    try:
        sync_injection()
    except Exception:
        pass

    return JSONResponse({"status": "ok", "path": rel_path})


async def bump_epoch_endpoint(request: Request) -> JSONResponse:
    """Increment the vault epoch. Writers still on the old epoch are rejected."""
    denied = _reject_old_client(request)
    if denied is not None:
        return denied
    ensure_memory_layout()
    epoch = bump_epoch(USER_MEMORY)
    body = {"status": "ok", "epoch": epoch}
    body.update(_protocol_fields())
    body["epoch"] = epoch
    return JSONResponse(body)


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
        Route("/api/v1/epoch", bump_epoch_endpoint, methods=["POST"]),
        Route("/api/v1/file", get_file_endpoint, methods=["GET"]),
        Route("/api/v1/file", put_file_endpoint, methods=["POST", "PUT"]),
        Route("/api/v1/file", delete_file_endpoint, methods=["DELETE"]),
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
