import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents_memory.remote import sync_hooks


class TestSyncHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.user = Path(self.tmp.name)
        (self.user / "staging").mkdir(parents=True)
        self.patchers = [
            patch.object(sync_hooks, "get_remote_config", return_value={"url": "http://x", "token": "t"}),
            patch("agents_memory.store.USER_MEMORY", self.user),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.tmp.cleanup()

    def test_push_retries_then_succeeds(self):
        calls = {"n": 0}

        def boom_then_ok(*_a, **_k):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("offline")
            return {"status": "ok"}

        with patch.object(sync_hooks, "remote_push_merge", side_effect=boom_then_ok), patch.object(
            sync_hooks, "_refresh_index"
        ), patch.object(sync_hooks.time, "sleep"):
            res = sync_hooks.push_if_connected(refresh_index=False, retries=3)
        self.assertEqual(res, {"status": "ok"})
        self.assertEqual(calls["n"], 3)

    def test_push_logs_error_after_retries(self):
        with patch.object(
            sync_hooks, "remote_push_merge", side_effect=ConnectionError("offline")
        ), patch.object(sync_hooks, "_refresh_index"), patch.object(sync_hooks.time, "sleep"):
            res = sync_hooks.push_if_connected(refresh_index=False, retries=2)
        self.assertIsNone(res)
        log = self.user / "staging" / "sync-errors.md"
        self.assertTrue(log.is_file())
        self.assertIn("offline", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
