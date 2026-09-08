"""Execution locality — mirror sync model: all MCP tools run locally."""
from __future__ import annotations

import os
from typing import Literal

Locality = Literal["local", "remote", "hybrid"]

# Mirror model: every tool executes on the workstation/server filesystem.
# Cloud sync is a separate push/pull layer (sync_bundle + sync_hooks).
LOCAL_TOOLS: frozenset[str] = frozenset({"*"})  # documentation marker

REMOTE_TOOLS: frozenset[str] = frozenset()
HYBRID_TOOLS: frozenset[str] = frozenset()

PUSH_AFTER_LOCAL: frozenset[str] = frozenset(
    {
        "ingest_catalog",
        "ingest_extract",
        "inventory_projects",
        "register_project",
        "ignore_project",
        "sync_local_agents_md",
    }
)

INGEST_TOOLS: frozenset[str] = frozenset(
    {"ingest_catalog", "ingest_extract", "ingest_status"}
)


def tool_locality(name: str) -> Locality:
    return "local"


def is_hybrid_mode() -> bool:
    return os.environ.get("AGENTS_MEMORY_HYBRID", "").lower() in ("1", "true", "yes")


def is_remote_server() -> bool:
    return os.environ.get("AGENTS_MEMORY_REMOTE_SERVER", "").lower() in (
        "1",
        "true",
        "yes",
    )


def ingest_roots_available() -> bool:
    """True when at least one configured ingest source path exists on this machine."""
    try:
        from ..ingest_config import list_sources, resolve_source_roots

        for src in list_sources():
            for root in resolve_source_roots(src):
                if root.exists():
                    return True
    except Exception:
        pass
    return False


def assert_ingest_runs_locally() -> None:
    if ingest_roots_available():
        return
    raise RuntimeError(
        "Ingest requires local chat stores on this machine (Cursor jsonl, Antigravity brain, …). "
        "Run ingest on a workstation with chat exports, then sync pushes results to the server."
    )
