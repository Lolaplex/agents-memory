import json
import unittest
from pathlib import Path


class FlowProbesTests(unittest.TestCase):
    """L2 frozen probe evaluations over examples/flow/ artifacts."""

    def setUp(self):
        self.flow_dir = Path(__file__).resolve().parent.parent / "examples" / "flow"

    def test_probe_scope_capabilities(self):
        probes = [
            ("scope-memory.v1.json", "memory.promote", ["bullet", "kind", "name"], ["promoted", "rejected"]),
            ("scope-plex.v1.json", "records.open", ["record"], ["opened", "unsupported", "failed"]),
            ("scope-media.v1.json", "media.play", ["grant"], ["playing", "failed"]),
        ]

        for fname, cap_id, expected_inputs, expected_outcomes in probes:
            path = self.flow_dir / fname
            self.assertTrue(path.exists(), f"Missing {fname}")
            data = json.loads(path.read_text(encoding="utf-8"))
            caps = {c["id"]: c for c in data.get("capabilities", [])}
            self.assertIn(cap_id, caps)
            cap = caps[cap_id]
            input_names = [i["name"] for i in cap.get("inputs", [])]
            for exp_in in expected_inputs:
                self.assertIn(exp_in, input_names)
            for exp_out in expected_outcomes:
                self.assertIn(exp_out, cap.get("outcomes", []))

    def test_probe_relation_vocabulary_completeness(self):
        rel_vocab_path = self.flow_dir / "relation-vocabulary.json"
        self.assertTrue(rel_vocab_path.exists())
        vocab = json.loads(rel_vocab_path.read_text(encoding="utf-8"))
        kinds = {r["name"]: r for r in vocab.get("relation_kinds", [])}

        # Assert mandatory relations exist
        for expected in ["refs", "supersedes", "same_as", "at_project", "part_of", "next"]:
            self.assertIn(expected, kinds)
            self.assertIsInstance(kinds[expected]["symmetric"], bool)


if __name__ == "__main__":
    unittest.main()
