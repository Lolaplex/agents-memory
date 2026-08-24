import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents_memory import index, mcp_server, store, viewer


class IndexAndViewerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.repo = self.root / "repo"
        self.user.mkdir(parents=True)
        self.repo.mkdir(parents=True)

        # Write test documents
        concepts = self.user / "concepts"
        concepts.mkdir(parents=True)
        (concepts / "cache-law.md").write_text(
            "---\nrefs:\n  - project/demo/decisions/001\nsupersedes: user/notes/old\n---\n\n"
            "# Index As Cache Law\n\n## Principle\n\nAny index is a disposable cache derived from markdown.\n",
            encoding="utf-8",
        )

        proj_mem = self.repo / ".agents" / "memory"
        proj_mem.mkdir(parents=True)
        (proj_mem / "README.md").write_text(
            "# Demo Project\n\nDemonstration repository for memory indexing.\n",
            encoding="utf-8",
        )

        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|---|---|---|---|---|\n"
            f"| demo | `{self.repo}` | demo project | py | active |\n",
            encoding="utf-8",
        )

        self.test_index_dir = self.user / ".index"
        self.test_fts_db = self.test_index_dir / "fts.sqlite"

        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "PROJECTS_MD", self.projects_md),
            patch.object(index, "USER_MEMORY", self.user),
            patch.object(index, "INDEX_DIR", self.test_index_dir),
            patch.object(index, "FTS_DB", self.test_fts_db),
            patch.object(viewer, "USER_MEMORY", self.user),
            patch.object(viewer, "EXPORT_DIR", self.user / "export"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_rebuild_index_and_search_hybrid(self):
        stats = index.rebuild_index(db_path=self.test_fts_db)
        self.assertGreaterEqual(stats["indexed"], 2)
        self.assertTrue(self.test_fts_db.exists())

        # Search exact & hybrid terms
        hits = index.search_hybrid("disposable cache", db_path=self.test_fts_db)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["id"], "user/concepts/cache-law.md")
        self.assertEqual(hits[0]["title"], "Index As Cache Law")

        # Project scoped search
        proj_hits = index.search_hybrid("Demonstration", project="demo", db_path=self.test_fts_db)
        self.assertEqual(len(proj_hits), 1)
        self.assertEqual(proj_hits[0]["project"], "demo")

    def test_get_related_explicit_and_content(self):
        index.rebuild_index(db_path=self.test_fts_db)
        rel = index.get_related("user/concepts/cache-law.md", db_path=self.test_fts_db)
        self.assertEqual(rel["id"], "user/concepts/cache-law.md")
        self.assertIn("project/demo/decisions/001", rel["explicit_relations"]["refs"])
        self.assertEqual(rel["explicit_relations"]["supersedes"], "user/notes/old")

    def test_viewer_markdown_to_html(self):
        md = "# Heading 1\n\nParagraph with **bold** and `code`.\n\n- item 1\n- item 2\n"
        html_out = viewer._md_to_html(md)
        self.assertIn("<h1>Heading 1</h1>", html_out)
        self.assertIn("<strong>bold</strong>", html_out)
        self.assertIn("<code>code</code>", html_out)
        self.assertIn("<li>item 1</li>", html_out)

    def test_viewer_export_static_web(self):
        res = viewer.export_static_web()
        self.assertEqual(res["status"], "ok")
        export_dir = self.user / "export"
        self.assertTrue((export_dir / "index.html").exists())
        self.assertTrue((export_dir / "chronicle.html").exists())
        self.assertTrue((export_dir / "hygiene.html").exists())
        self.assertTrue((export_dir / "flow-protocol.html").exists())
        self.assertTrue((export_dir / "webview.html").exists())
        self.assertTrue((export_dir / "projects" / "demo.html").exists())

    def test_mcp_rebuild_and_search(self):
        rebuild_res = mcp_server.rebuild_index()
        self.assertIn("Index rebuilt:", rebuild_res)
        search_res = mcp_server.search_hybrid("disposable cache")
        self.assertIn("Index As Cache Law", search_res)
        rel_res = json.loads(mcp_server.get_related("user/concepts/cache-law.md"))
        self.assertIn("project/demo/decisions/001", rel_res["explicit_relations"]["refs"])

    def test_suggest_links_and_freshness(self):
        mcp_server.rebuild_index()
        suggestions_raw = mcp_server.suggest_links("user/concepts/cache-law.md")
        suggestions = json.loads(suggestions_raw)
        self.assertIsInstance(suggestions, list)

        freshness_raw = mcp_server.check_memory_freshness()
        freshness = json.loads(freshness_raw)
        self.assertIn("status", freshness)
        self.assertIn("staging_count", freshness)
        self.assertIn("nags", freshness)


if __name__ == "__main__":
    unittest.main()
