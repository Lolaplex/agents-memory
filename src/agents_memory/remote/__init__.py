"""Remote cloud sync and multi-device coordination package for agents-memory."""
from __future__ import annotations

from .client import (
    clear_remote_config,
    get_remote_config,
    remote_health_check,
    remote_mirror_injection,
    remote_pull,
    remote_push_merge,
    run_client_bridge,
    save_remote_config,
)
from .locality import (
    LOCAL_TOOLS,
    REMOTE_TOOLS,
    HYBRID_TOOLS,
    assert_ingest_runs_locally,
    tool_locality,
)
from .merge import (
    merge_bullet_markdown,
    merge_file_trees,
    merge_markdown_files,
    merge_staging_markdown,
    merge_table_markdown,
)
from .server import create_remote_app, run_server

__all__ = [
    "clear_remote_config",
    "create_remote_app",
    "get_remote_config",
    "merge_bullet_markdown",
    "merge_file_trees",
    "merge_markdown_files",
    "merge_staging_markdown",
    "merge_table_markdown",
    "remote_health_check",
    "remote_mirror_injection",
    "remote_pull",
    "remote_push_merge",
    "run_client_bridge",
    "run_server",
    "save_remote_config",
    "LOCAL_TOOLS",
    "REMOTE_TOOLS",
    "HYBRID_TOOLS",
    "assert_ingest_runs_locally",
    "tool_locality",
]
