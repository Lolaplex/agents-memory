import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agent_memory.ingest_config import normalize_ingest, list_sources
from agent_memory.ingest_common import keep_user_line, scrub, write_staging


class NormalizeTests(unittest.TestCase):
    def test_legacy_keys_become_sources(self):
        raw = {
            "openai_export_globs": ["~/Downloads/*chatgpt*"],
            "chat_sources": [{"id": "pi", "kind": "pi-jsonl", "paths": ["~/.pi"]}],
        }
        cfg = normalize_ingest(raw)
        ids = [s["id"] for s in cfg["sources"]]
        self.assertIn("openai-export", ids)
        self.assertIn("pi", ids)

    def test_unified_sources_passthrough(self):
        raw = {"version": 1, "sources": [{"id": "x", "kind": "agent-jsonl"}]}
        cfg = normalize_ingest(raw)
        self.assertEqual(list_sources(cfg)[0]["id"], "x")
        self.assertEqual(cfg["extract_max_bullets"], 100)
        self.assertEqual(cfg["staging_nag_threshold"], 50)


class StagingTests(unittest.TestCase):
    def test_write_staging_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = Path(tmp)
            with patch("agent_memory.ingest_common.USER_MEMORY", mem):
                path = write_staging("test-src", "Test", ["[t] fact one"])
                text = path.read_text(encoding="utf-8")
                self.assertIn("ingest: test-src", text)
                self.assertIn("[t] fact one", text)


class FilterTests(unittest.TestCase):
    def test_drops_howto(self):
        self.assertFalse(keep_user_line("Q", "How can I fix this bug?"))

    def test_scrubs_token(self):
        self.assertIn("[redacted]", scrub("key sk-abcdefghijklmnopqrstuvwxyz1234567890"))


if __name__ == "__main__":
    unittest.main()
