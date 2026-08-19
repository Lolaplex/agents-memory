import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agent_memory import ingest_common
from agent_memory.ingest_config import normalize_ingest
from agent_memory.ingest_extractors import extract_agent_jsonl, extract_copilot_jsonl, extract_source

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class ExtractFilterTests(unittest.TestCase):
    def test_agent_jsonl_fixture_keep_drop(self):
        root = FIXTURES / "agent-jsonl"
        src = {
            "id": "agent-transcripts",
            "kind": "agent-jsonl",
            "label": "Agent transcripts",
            "paths": [str(root)],
        }
        lines = extract_agent_jsonl(src)
        joined = "\n".join(lines)
        self.assertIn("isa-physics-kopie", joined)
        self.assertNotIn("How can I fix", joined)
        self.assertNotIn("[ok]", joined)

    def test_copilot_jsonl_fixture_keep_drop(self):
        root = FIXTURES / "copilot-jsonl" / "chatSessions"
        src = {
            "id": "vscode-copilot",
            "kind": "copilot-jsonl",
            "label": "VS Code Copilot",
            "paths": [str(root)],
        }
        lines = extract_copilot_jsonl(src)
        joined = "\n".join(lines)
        self.assertIn("vendor.lock", joined)
        self.assertNotIn("How do I run pytest", joined)
        self.assertNotIn("[hi]", joined)

    def test_extract_cap_per_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = Path(tmp)
            root = FIXTURES / "agent-jsonl"
            src = {
                "id": "agent-transcripts",
                "kind": "agent-jsonl",
                "label": "Agent transcripts",
                "paths": [str(root)],
            }
            cfg = normalize_ingest(
                {
                    "version": 1,
                    "sources": [src],
                    "extract_max_bullets": 1,
                }
            )
            with patch.object(ingest_common, "USER_MEMORY", mem):
                count, path = extract_source(src, cfg=cfg)
            self.assertEqual(count, 1)
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("\n- "), 1)
            state = __import__("json").loads((mem / "ingest" / "state.json").read_text(encoding="utf-8"))
            entry = state["sources"]["agent-transcripts"]
            self.assertTrue(entry.get("extract_capped"))
            self.assertGreater(entry.get("extract_total_before_cap") or 0, 1)


if __name__ == "__main__":
    unittest.main()
