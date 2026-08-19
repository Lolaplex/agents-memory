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
from agent_memory.ingest_extractors import (
    EXTRACTORS,
    extract_agent_jsonl,
    extract_copilot_jsonl,
    extract_source,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _src(kind: str, fixture_dir: str, label: str, sid: str) -> dict:
    return {
        "id": sid,
        "kind": kind,
        "label": label,
        "paths": [str(FIXTURES / fixture_dir)],
    }


class ExtractFilterTests(unittest.TestCase):
    def test_agent_jsonl_fixture_keep_drop(self):
        lines = extract_agent_jsonl(_src("agent-jsonl", "agent-jsonl", "Agent", "agent-transcripts"))
        joined = "\n".join(lines)
        self.assertIn("sandbox clone", joined)
        self.assertIn("project map", joined)
        self.assertNotIn("How can I fix", joined)
        self.assertNotIn("[ok]", joined)

    def test_copilot_jsonl_fixture_keep_drop(self):
        lines = extract_copilot_jsonl(
            _src("copilot-jsonl", "copilot-jsonl/chatSessions", "Copilot", "vscode-copilot")
        )
        joined = "\n".join(lines)
        self.assertIn("lockfile SHAs", joined)
        self.assertNotIn("How do I run", joined)
        self.assertNotIn("[hi]", joined)

    def test_openai_export_fixture_keep_drop(self):
        lines = EXTRACTORS["openai-export"](
            _src("openai-export", "openai-export", "ChatGPT export", "openai-export")
        )
        joined = "\n".join(lines)
        self.assertIn("Markdown with a path", joined)
        self.assertNotIn("How can I export", joined)
        self.assertNotIn("[sure]", joined)
        self.assertNotIn("example.com", joined)

    def test_claude_jsonl_fixture_keep_drop(self):
        lines = EXTRACTORS["claude-jsonl"](
            _src("claude-jsonl", "claude-jsonl", "Claude Code", "claude-code")
        )
        joined = "\n".join(lines)
        self.assertIn("numbered files", joined)
        self.assertNotIn("Could you walk", joined)
        self.assertNotIn("[done]", joined)

    def test_pi_jsonl_fixture_keep_drop(self):
        lines = EXTRACTORS["pi-jsonl"](_src("pi-jsonl", "pi-jsonl", "Pi", "pi"))
        joined = "\n".join(lines)
        self.assertIn("Staging is an inbox", joined)
        self.assertNotIn("best way to debug", joined)
        self.assertNotIn("[yep]", joined)

    def test_antigravity_brain_fixture_keep_drop(self):
        lines = EXTRACTORS["antigravity-brain"](
            _src("antigravity-brain", "antigravity-brain", "Antigravity", "antigravity")
        )
        joined = "\n".join(lines)
        self.assertIn("MCP search", joined)
        self.assertIn("numbered markdown", joined)
        self.assertIn("project map", joined)
        self.assertIn("typed memory paths", joined)
        self.assertIn("transcript.jsonl", joined)
        self.assertNotIn("How can I rewrite", joined)
        self.assertNotIn("stack trace", joined)
        self.assertNotIn("auto-import", joined)
        self.assertNotIn("configure lint", joined)

    def test_all_kinds_have_fixtures(self):
        expected = {
            "agent-jsonl",
            "copilot-jsonl",
            "openai-export",
            "claude-jsonl",
            "pi-jsonl",
            "antigravity-brain",
        }
        self.assertEqual(set(EXTRACTORS.keys()), expected)

    def test_extract_cap_per_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = Path(tmp)
            src = _src("agent-jsonl", "agent-jsonl", "Agent", "agent-transcripts")
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
