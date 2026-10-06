"""MCP tool surface contract — no duplicate board tools, disambiguated search/session tiers."""
import inspect
import unittest

from agents_memory import mcp_server


EXPECTED_TOOLS = {
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
}

FORBIDDEN_TOOLS = {
    "attach_board_memory",
    "push_board_memory",
    "list_board_attaches",
    "board_push",
    "board_push_paths",
}


class McpToolContractTests(unittest.TestCase):
    def test_expected_tools_present(self):
        names = {
            name
            for name, obj in inspect.getmembers(mcp_server)
            if name in EXPECTED_TOOLS and callable(obj)
        }
        self.assertEqual(names, EXPECTED_TOOLS)

    def test_no_board_duplicate_tools(self):
        for name in FORBIDDEN_TOOLS:
            self.assertFalse(hasattr(mcp_server, name), f"dead duplicate tool: {name}")

    def test_search_tier_disambiguation(self):
        sm = inspect.getdoc(mcp_server.search_memory) or ""
        sh = inspect.getdoc(mcp_server.search_hybrid) or ""
        self.assertIn("first", sm.lower())
        self.assertIn("search_memory", sh)
        self.assertIn("session", sm.lower())

    def test_session_tier_not_memory_search(self):
        for fn in (mcp_server.session_snap, mcp_server.session_grep, mcp_server.session_tail):
            doc = (inspect.getdoc(fn) or "").lower()
            self.assertIn("traces", doc)
            self.assertNotIn("markdown memory", doc.replace("not markdown memory", ""))


if __name__ == "__main__":
    unittest.main()
