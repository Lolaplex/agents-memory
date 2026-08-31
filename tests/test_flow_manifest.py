import json
import unittest
from pathlib import Path

from agents_memory import mcp_server, store


class FlowManifestCoverageTests(unittest.TestCase):
    def test_scope_memory_manifest_coverage(self):
        manifest_path = Path(__file__).resolve().parent.parent / "examples" / "flow" / "scope-memory.v1.json"
        self.assertTrue(manifest_path.exists())

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["scope"], "memory.v1")

        cap_ids = [c["id"] for c in manifest.get("capabilities", [])]
        self.assertIn("memory.resolve", cap_ids)
        self.assertIn("memory.relate", cap_ids)
        self.assertIn("memory.promote", cap_ids)
        self.assertIn("quarantine.propose", cap_ids)

        # Verify corresponding tool availability in MCP
        self.assertTrue(callable(getattr(mcp_server, "search_memory", None)))
        self.assertTrue(callable(getattr(mcp_server, "search_hybrid", None)))
        self.assertTrue(callable(getattr(mcp_server, "get_related", None)))
        self.assertTrue(callable(getattr(mcp_server, "promote_bullet", None)))
        self.assertTrue(callable(getattr(mcp_server, "add_memory", None)))

    def test_scope_media_manifest_coverage(self):
        manifest_path = Path(__file__).resolve().parent.parent / "examples" / "flow" / "scope-media.v1.json"
        self.assertTrue(manifest_path.exists())

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["scope"], "media.v1")

        cap_ids = [c["id"] for c in manifest.get("capabilities", [])]
        self.assertIn("media.resolve", cap_ids)
        self.assertIn("media.relate", cap_ids)
        self.assertIn("media.authorize", cap_ids)
        self.assertIn("media.play", cap_ids)

        # Protocol check: flow files must not leak filesystem paths
        flow_path = Path(__file__).resolve().parent.parent / "examples" / "flow" / "flow-play-episode.flow"
        self.assertTrue(flow_path.exists())
        flow_text = flow_path.read_text(encoding="utf-8")
        self.assertNotIn("/home/", flow_text)
        self.assertNotIn("C:\\", flow_text)
        self.assertNotIn("/mnt/", flow_text)
        self.assertIn("media.resolve", flow_text)
        self.assertIn("media.play", flow_text)


if __name__ == "__main__":
    unittest.main()
