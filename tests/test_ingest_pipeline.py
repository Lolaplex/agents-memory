import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agent_memory import ingest_catalog, ingest_common, ingest_config, ingest_extractors, store

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class IngestPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.user.mkdir(parents=True)
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n| slug | path | role | stack | status |\n",
            encoding="utf-8",
        )
        self.ingest_json = self.user / "ingest.json"
        self.sources = [
            {
                "id": "cursor",
                "kind": "agent-jsonl",
                "label": "Cursor",
                "paths": [str(FIXTURES / "agent-jsonl")],
            },
            {
                "id": "openai-export",
                "kind": "openai-export",
                "label": "Open AI — GDPR export",
                "paths": [str(FIXTURES / "openai-export")],
            },
            {
                "id": "copilot-sessions",
                "kind": "copilot-jsonl",
                "label": "Copilot Sessions",
                "paths": [str(FIXTURES / "copilot-jsonl" / "chatSessions")],
            },
        ]
        self.ingest_json.write_text(
            json.dumps({"version": 1, "sources": self.sources, "extract_max_bullets": 50}),
            encoding="utf-8",
        )
        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(ingest_common, "USER_MEMORY", self.user),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_ingest_catalog_and_chats_index(self):
        result = ingest_catalog.run_catalog()
        self.assertIn("chats_index", result)
        self.assertIn("sources", result)

        # Check chats-index.md was created
        chats_index = self.user / "chats-index.md"
        self.assertTrue(chats_index.is_file())
        content = chats_index.read_text(encoding="utf-8")
        self.assertIn("# Chat index", content)

    def test_ingest_extract_and_state(self):
        res = ingest_extractors.run_extract()
        self.assertIn("sources", res)
        self.assertEqual(len(res["sources"]), 3)

        # Verify staging files were created
        staging_dir = self.user / "staging" / "ingest"
        self.assertTrue(staging_dir.is_dir())

        # Verify state.json was written
        state_file = self.user / "ingest" / "state.json"
        self.assertTrue(state_file.is_file())
        state = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertIn("sources", state)
        for s in self.sources:
            self.assertIn(s["id"], state["sources"])
            self.assertIn("last_extract", state["sources"][s["id"]])

    def test_token_and_secret_scrubbing(self):
        raw_text = (
            "My OpenAI API key is sk-1234567890abcdef1234567890abcdef12 and "
            "contact me at test.user@example.com."
        )
        scrubbed = ingest_common.scrub(raw_text)
        self.assertNotIn("sk-1234567890", scrubbed)
        self.assertNotIn("test.user@example.com", scrubbed)
        self.assertIn("[redacted]", scrubbed)

    def test_empty_sources_handled_safely(self):
        self.ingest_json.write_text(json.dumps({"version": 1, "sources": []}), encoding="utf-8")
        cat_res = ingest_catalog.run_catalog()
        self.assertEqual(cat_res["sources"], 0)

        ext_res = ingest_extractors.run_extract()
        self.assertEqual(len(ext_res["sources"]), 0)


if __name__ == "__main__":
    unittest.main()
