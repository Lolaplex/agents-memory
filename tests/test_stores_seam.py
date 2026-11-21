import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents_memory.stores.repo_docs import RepoDocsStore
from agents_memory.stores.registry import list_stores
from agents_memory.stores.search import search_stores


class RepoDocsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "klanker"
        (self.repo / "docs" / "decisions").mkdir(parents=True)
        (self.repo / "concepts").mkdir(parents=True)
        (self.repo / "docs" / "decisions" / "001-shell.md").write_text(
            "# Shell ruling\n\nklanker bare is the interactive shell.\n",
            encoding="utf-8",
        )
        (self.repo / "concepts" / "frag-slimemold.md").write_text(
            "---\nid: frag-slimemold\n---\n\nGrows feelers by host sensing.\n",
            encoding="utf-8",
        )
        (self.repo / "AGENTS.md").write_text("# klanker\nAdaptive agent shell.\n")

    def test_hits_decisions_and_concepts(self):
        hits = RepoDocsStore(self.repo).search("interactive shell")
        files = {h["file"] for h in hits}
        self.assertIn("docs/decisions/001-shell.md", files)

    def test_no_match_returns_empty(self):
        self.assertEqual(RepoDocsStore(self.repo).search("zzznomatch"), [])

    def test_status_counts_files(self):
        st = RepoDocsStore(self.repo).status()
        self.assertEqual(st["files"], 3)


class RegistryAndFanoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = Path(self.tmp.name) / "mem"
        self.mem.mkdir(parents=True)

    def test_default_is_markdown_only(self):
        with patch("agents_memory.stores.registry._mem_root", return_value=self.mem):
            names = [getattr(s, "name", None) or s.get("name") for s in list_stores()]
        self.assertEqual(names, ["memory"])

    def test_unknown_kind_is_named_refusal(self):
        (self.mem / "stores.json").write_text(
            json.dumps({"stores": [{"name": "x", "kind": "bogus", "path": "/n"}]}),
            encoding="utf-8",
        )
        with patch("agents_memory.stores.registry._mem_root", return_value=self.mem):
            stores = list_stores()
        refusal = [s for s in stores if isinstance(s, dict)]
        self.assertEqual(len(refusal), 1)
        self.assertIn("unknown store kind", refusal[0]["error"])

    def test_search_stores_merges_and_tags(self):
        repo = Path(self.tmp.name) / "r"
        (repo / "docs" / "decisions").mkdir(parents=True)
        (repo / "docs" / "decisions" / "001.md").write_text(
            "the relay owns wire protocols\n", encoding="utf-8",
        )
        (self.mem / "stores.json").write_text(
            json.dumps({"stores": [{"name": "r", "kind": "repo-docs",
                                    "path": str(repo)}]}),
            encoding="utf-8",
        )
        with patch("agents_memory.stores.registry._mem_root", return_value=self.mem):
            out = search_stores("wire protocols")
        tagged = [h for h in out["hits"] if h.get("store") == "r"]
        self.assertTrue(tagged)
        self.assertIn("rrf", out["hits"][0])
        rows = {r["store"]: r for r in out["stores"]}
        self.assertIn("r", rows)


if __name__ == "__main__":
    unittest.main()
