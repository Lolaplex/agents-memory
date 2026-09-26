"""Tests for stable content-hash memory IDs and shift-tolerant deletion."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents_memory import store


class TestStableMemoryIds(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.user = self.root / "user"
        self.user.mkdir(parents=True, exist_ok=True)
        store.clear_memory_cache()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_line_content_hash(self):
        h1 = store.line_content_hash("- prefer pnpm over npm")
        h2 = store.line_content_hash("  - prefer pnpm over npm  \n")
        self.assertEqual(len(h1), 8)
        self.assertEqual(h1, h2)

    def test_search_memory_returns_hash_anchored_id(self):
        doc = self.user / "concepts" / "pkg.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("# Concepts\n\n- prefer pnpm over npm\n- avoid yarn\n", encoding="utf-8")

        with patch.object(store, "USER_MEMORY", self.user), patch.object(store, "AGENTS_RULES", self.root / "rules"):
            hits = store.search_memory("prefer pnpm")
            self.assertEqual(len(hits), 1)
            hit = hits[0]
            expected_hash = store.line_content_hash("- prefer pnpm over npm")
            self.assertEqual(hit["id"], f"user/concepts/pkg.md:3#{expected_hash}")
            self.assertEqual(hit["line"], 3)
            self.assertEqual(hit["text"], "- prefer pnpm over npm")

    def test_delete_memory_fast_path_with_hash(self):
        doc = self.user / "concepts" / "pkg.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("# Concepts\n\n- line 3\n- line 4\n", encoding="utf-8")

        with patch.object(store, "USER_MEMORY", self.user), patch.object(store, "AGENTS_RULES", self.root / "rules"):
            h = store.line_content_hash("- line 3")
            removed = store.delete_memory(f"user/concepts/pkg.md:3#{h}", auto_sync=False)
            self.assertEqual(removed, "- line 3")
            self.assertEqual(doc.read_text(encoding="utf-8"), "# Concepts\n\n- line 4\n")

    def test_delete_memory_shift_tolerance(self):
        """When an earlier line is deleted, line numbers shift down.
        A delete with the original line number and hash anchor MUST still find and delete the correct line!"""
        doc = self.user / "concepts" / "stack.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(
            "# Stack\n\n- first item (line 3)\n- second item (line 4)\n- third item (line 5)\n",
            encoding="utf-8",
        )

        with patch.object(store, "USER_MEMORY", self.user), patch.object(store, "AGENTS_RULES", self.root / "rules"):
            # Original search results
            h3 = store.line_content_hash("- first item (line 3)")
            h5 = store.line_content_hash("- third item (line 5)")
            id3 = f"user/concepts/stack.md:3#{h3}"
            id5 = f"user/concepts/stack.md:5#{h5}"

            # 1. Delete line 3
            removed3 = store.delete_memory(id3, auto_sync=False)
            self.assertEqual(removed3, "- first item (line 3)")

            # In the file, "third item" is now at line 4, NOT line 5!
            # 2. Delete using id5 (which points to line 5). It must shift-resolve to line 4!
            removed5 = store.delete_memory(id5, auto_sync=False)
            self.assertEqual(removed5, "- third item (line 5)")

            # Verify file only contains "second item"
            content = doc.read_text(encoding="utf-8")
            self.assertIn("- second item (line 4)", content)
            self.assertNotIn("first item", content)
            self.assertNotIn("third item", content)

    def test_delete_memory_double_delete_refusal(self):
        """Deleting the same hash ID twice must raise ValueError, not silently delete a different line."""
        doc = self.user / "concepts" / "todo.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("# Todo\n\n- item A\n- item B\n", encoding="utf-8")

        with patch.object(store, "USER_MEMORY", self.user), patch.object(store, "AGENTS_RULES", self.root / "rules"):
            h = store.line_content_hash("- item A")
            mem_id = f"user/concepts/todo.md:3#{h}"

            # First delete succeeds
            store.delete_memory(mem_id, auto_sync=False)

            # Second delete must fail
            with self.assertRaises(ValueError) as ctx:
                store.delete_memory(mem_id, auto_sync=False)
            self.assertIn("already deleted or modified", str(ctx.exception))

            # item B must still be intact
            self.assertIn("- item B", doc.read_text(encoding="utf-8"))

    def test_delete_memory_uniform_prefix_and_pure_hash(self):
        doc = self.user / "concepts" / "uniform.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("# Uniform\n\n- item one\n- item two\n", encoding="utf-8")

        with patch.object(store, "USER_MEMORY", self.user), patch.object(store, "AGENTS_RULES", self.root / "rules"):
            h1 = store.line_content_hash("- item one")
            h2 = store.line_content_hash("- item two")

            # With memory: prefix
            rem1 = store.delete_memory(f"memory:user/concepts/uniform.md:3#{h1}", auto_sync=False)
            self.assertEqual(rem1, "- item one")

            # Pure hash without line number
            rem2 = store.delete_memory(f"memory:user/concepts/uniform.md#{h2}", auto_sync=False)
            self.assertEqual(rem2, "- item two")

    def test_delete_memory_legacy_without_hash(self):
        doc = self.user / "concepts" / "legacy.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("# Legacy\n\n- line three\n", encoding="utf-8")

        with patch.object(store, "USER_MEMORY", self.user), patch.object(store, "AGENTS_RULES", self.root / "rules"):
            rem = store.delete_memory("user/concepts/legacy.md:3", auto_sync=False)
            self.assertEqual(rem, "- line three")


if __name__ == "__main__":
    unittest.main()
