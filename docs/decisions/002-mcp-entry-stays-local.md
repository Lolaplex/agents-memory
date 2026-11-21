---
slug: lolaplex-board
status: implemented
---

# Default MCP is the local clerk

`python -m agents_memory.mcp_server` is always the host MCP entry. `remote connect` stores replicate credentials only; it does not switch the IDE to `sync_mcp`.

FTS5 / hybrid rank lives in `index.py` and backs `search_memory`. It is not a separate agent tool.
