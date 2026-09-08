"""Hybrid MCP server: local ingest/inventory + remote canonical store."""
from __future__ import annotations

import json
import os
import sys

from mcp.server.fastmcp import FastMCP

from ..store import ensure_memory_layout

ensure_memory_layout()
os.environ.setdefault("AGENTS_MEMORY_HYBRID", "1")

from .. import mcp_server as local_mcp  # noqa: E402
from .client import get_remote_config, remote_mirror_injection  # noqa: E402
from .tool_dispatch import dispatch_tool, remote_connected  # noqa: E402

mcp = FastMCP("agents-memory")


def _wrap(name: str, fn):
    def handler(**kwargs):
        return dispatch_tool(name, fn, **kwargs)

    handler.__name__ = name
    return handler


@mcp.tool()
def search_memory(query: str, project: str = "") -> str:
    """Search user store (remote canonical) plus local repo .agents/memory trees."""
    return dispatch_tool("search_memory", local_mcp.search_memory, query=query, project=project)


@mcp.tool()
def add_memory(
    fact_or_message: str,
    kind: str = "",
    name: str = "",
    project: str = "",
    collection: str = "",
) -> str:
    """File durable fact. User-store → remote. Repo facts → local repo path."""
    return dispatch_tool(
        "add_memory",
        local_mcp.add_memory,
        fact_or_message=fact_or_message,
        kind=kind,
        name=name,
        project=project,
        collection=collection,
    )


@mcp.tool()
def read_memory_file(file_id: str) -> str:
    return dispatch_tool("read_memory_file", local_mcp.read_memory_file, file_id=file_id)


@mcp.tool()
def write_memory_file(file_id: str, content: str) -> str:
    return dispatch_tool(
        "write_memory_file", local_mcp.write_memory_file, file_id=file_id, content=content
    )


@mcp.tool()
def auto_distill(limit: int = 50, discard_noise: bool = True) -> str:
    return dispatch_tool(
        "auto_distill",
        local_mcp.auto_distill,
        limit=limit,
        discard_noise=discard_noise,
    )


@mcp.tool()
def get_staging_inbox(project: str = "", limit: int = 20) -> str:
    return dispatch_tool(
        "get_staging_inbox",
        local_mcp.get_staging_inbox,
        project=project,
        limit=limit,
    )


@mcp.tool()
def distill_batch(items_json: str) -> str:
    return dispatch_tool("distill_batch", local_mcp.distill_batch, items_json=items_json)


@mcp.tool()
def get_project_memories(project: str) -> str:
    return dispatch_tool("get_project_memories", local_mcp.get_project_memories, project=project)


@mcp.tool()
def delete_memory(memory_id: str) -> str:
    return dispatch_tool("delete_memory", local_mcp.delete_memory, memory_id=memory_id)


@mcp.tool()
def list_projects() -> str:
    return dispatch_tool("list_projects", local_mcp.list_projects)


@mcp.tool()
def inventory_projects() -> str:
    return dispatch_tool("inventory_projects", local_mcp.inventory_projects)


@mcp.tool()
def register_project(
    slug: str,
    path: str,
    role: str = "unclassified",
    stack: str = "—",
    status: str = "active",
) -> str:
    return dispatch_tool(
        "register_project",
        local_mcp.register_project,
        slug=slug,
        path=path,
        role=role,
        stack=stack,
        status=status,
    )


@mcp.tool()
def ignore_project(slug: str) -> str:
    return dispatch_tool("ignore_project", local_mcp.ignore_project, slug=slug)


@mcp.tool()
def sync_local_agents_md(project_folder_path: str = "", project_slug: str = "") -> str:
    return dispatch_tool(
        "sync_local_agents_md",
        local_mcp.sync_local_agents_md,
        project_folder_path=project_folder_path,
        project_slug=project_slug,
    )


@mcp.tool()
def get_related(memory_id: str, limit: int = 5) -> str:
    return dispatch_tool("get_related", local_mcp.get_related, memory_id=memory_id, limit=limit)


try:
    from agents_traces import auto_trace_mcp

    auto_trace_mcp(mcp)
except Exception:
    pass


def _startup_pull() -> None:
    cfg = get_remote_config() or {}
    if not cfg.get("url") or not cfg.get("auto_pull", True):
        return
    try:
        from .client import remote_pull
        from .tool_dispatch import maybe_refresh_local_index

        remote_pull(str(cfg["url"]), str(cfg.get("token") or ""))
        maybe_refresh_local_index()
    except Exception:
        try:
            remote_mirror_injection(str(cfg["url"]), str(cfg.get("token") or ""))
        except Exception:
            pass


def main() -> int:
    mode = "hybrid (local ingest + remote store)" if remote_connected() else "hybrid (local only; not connected)"
    print(f"Starting agents-memory MCP [{mode}]...", file=sys.stderr)
    _startup_pull()
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
