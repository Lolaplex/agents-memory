"""Tool parity and local MCP entry invariants."""
import inspect
import unittest

from agents_memory import mcp_server
from agents_memory.store import mcp_entry


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
    def test_mcp_server_entrypoint_callable(self):
        self.assertTrue(callable(mcp_server.main))
        self.assertGreater(len(_tool_functions(mcp_server)), 10)

    def test_mcp_entry_always_local(self):
        entry = mcp_entry()
        self.assertEqual(entry["args"], ["-m", "agents_memory.mcp_server"])


if __name__ == "__main__":
    unittest.main()
