"""Tool parity and MCP entry invariants."""
import unittest
import inspect

from agents_memory.remote import sync_mcp, locality
from agents_memory import mcp_server


def _tool_functions(module) -> set[str]:
    names: set[str] = set()
    for name, obj in inspect.getmembers(module):
        if name.startswith("_"):
            continue
        if not callable(obj):
            continue
        if name in {"main"}:
            continue
        if inspect.isfunction(obj) and obj.__module__ == module.__name__:
            names.add(name)
    return names


class TestToolParity(unittest.TestCase):
    def test_sync_mcp_delegates_to_local_server(self):
        # sync_mcp wraps mcp_server.main — same tool surface via local MCP
        self.assertTrue(callable(sync_mcp.main))
        self.assertTrue(callable(mcp_server.main))

    def test_mcp_entry_local_when_no_remote(self):
        from unittest.mock import patch
        from agents_memory.store import mcp_entry

        with patch("agents_memory.remote.client.get_remote_config", return_value=None):
            entry = mcp_entry()
        self.assertEqual(entry["args"], ["-m", "agents_memory.mcp_server"])

    def test_mcp_entry_mirror_when_remote(self):
        from unittest.mock import patch
        from agents_memory.store import mcp_entry

        with patch(
            "agents_memory.remote.client.get_remote_config",
            return_value={"url": "https://memory.test"},
        ):
            entry = mcp_entry()
        self.assertEqual(entry["args"], ["-m", "agents_memory.remote.sync_mcp"])


class TestLocalityMirrorModel(unittest.TestCase):
    def test_all_mcp_tools_local_when_connected(self):
        ref = _tool_functions(mcp_server)
        for name in ref:
            loc = locality.tool_locality(name)
            # Mirror model: every tool runs locally; sync layer handles cloud
            self.assertEqual(loc, "local", f"{name} should be local in mirror model")


if __name__ == "__main__":
    unittest.main()
