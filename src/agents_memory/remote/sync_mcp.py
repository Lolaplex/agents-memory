"""Local MCP entry with mirror sync (pull on start, push after mutations)."""
from __future__ import annotations

import sys

from ..store import ensure_memory_layout

ensure_memory_layout()


def main() -> int:
    from .sync_hooks import pull_if_connected, start_background_sync

    cfg_import = __import__(
        "agents_memory.remote.client", fromlist=["get_remote_config"]
    )
    cfg = cfg_import.get_remote_config() or {}
    if cfg.get("url"):
        print(
            "Starting agents-memory MCP [mirror sync: local tools + cloud mirror]...",
            file=sys.stderr,
        )
        pull_if_connected(refresh_index=True)
        interval = float(cfg.get("sync_interval_seconds", 60))
        start_background_sync(interval=interval)
    else:
        print("Starting local agents-memory MCP on stdio...", file=sys.stderr)

    from ..mcp_server import main as local_main

    return local_main()


if __name__ == "__main__":
    raise SystemExit(main())
