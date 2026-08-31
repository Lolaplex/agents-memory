"""Tests for hybrid tool locality and remote tool endpoint guards."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

import agents_memory.remote.server as server_mod
from agents_memory.remote.locality import (
    INGEST_TOOLS,
    assert_ingest_runs_locally,
    tool_locality,
)
from agents_memory.remote.server import create_remote_app


class TestLocality(unittest.TestCase):
    def test_ingest_tools_are_local(self):
        for name in ("ingest_catalog", "ingest_extract", "ingest_status"):
            self.assertEqual(tool_locality(name), "local")
            self.assertIn(name, INGEST_TOOLS)

    def test_distill_tools_are_local(self):
        for name in ("auto_distill", "distill_batch", "get_staging_inbox"):
            self.assertEqual(tool_locality(name), "local")

    def test_assert_ingest_without_roots_raises(self):
        with patch(
            "agents_memory.remote.locality.ingest_roots_available",
            return_value=False,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                assert_ingest_runs_locally()
            self.assertIn("local chat stores", str(ctx.exception))


class TestRemoteToolEndpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.patchers = [
            patch.object(server_mod, "USER_MEMORY", self.tmp_path),
        ]
        for p in self.patchers:
            p.start()
        self.client = TestClient(create_remote_app(token="tok"))

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.tmp.cleanup()

    def test_rejects_ingest_without_chat_roots(self):
        with patch(
            "agents_memory.remote.locality.ingest_roots_available",
            return_value=False,
        ):
            resp = self.client.post(
                "/api/v1/tool",
                json={"name": "ingest_extract", "arguments": {}},
                headers={"Authorization": "Bearer tok"},
            )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertIn("local chat stores", data.get("error", "").lower())

    def test_remote_search_tool(self):
        (self.tmp_path / "USER.md").write_text("# Test\n", encoding="utf-8")
        resp = self.client.post(
            "/api/v1/tool",
            json={"name": "search_memory", "arguments": {"query": "Test"}},
            headers={"Authorization": "Bearer tok"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("result", data)


if __name__ == "__main__":
    unittest.main()
