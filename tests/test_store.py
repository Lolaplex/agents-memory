import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import store


class AddMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.repo = self.root / "repo"
        self.user.mkdir()
        self.repo.mkdir()
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n"
            f"| demo | `{self.repo}` | test | py | active |\n",
            encoding="utf-8",
        )
        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "PROJECTS_MD", self.projects_md),
            patch.object(store, "ORPHANS", self.user / "orphans"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_concept_file(self):
        loc = store.add_memory("Rank-4 kernel", kind="concept", name="isar")
        path = self.user / "concepts" / "isar.md"
        self.assertTrue(path.exists())
        self.assertIn("Rank-4 kernel", path.read_text(encoding="utf-8"))
        self.assertEqual(loc, "user/concepts/isar.md")

    def test_note_under_project_slug(self):
        store.add_memory("koruc pin still open", kind="note", name="open-questions", project="koru")
        path = self.user / "notes" / "koru" / "open-questions.md"
        self.assertTrue(path.exists())

    def test_scratch(self):
        store.add_memory("throwaway", kind="scratch", name="tmp")
        self.assertTrue((self.user / "notes" / "scratch" / "tmp.md").exists())

    def test_repo_facts_without_kind(self):
        loc = store.add_memory("local only", project="demo")
        path = self.repo / ".agents" / "memory" / "facts.md"
        self.assertTrue(path.exists())
        self.assertIn("local only", path.read_text(encoding="utf-8"))
        self.assertTrue(loc.endswith("project/demo/facts.md") or "facts.md" in loc)

    def test_refuses_dump_without_kind(self):
        with self.assertRaises(ValueError):
            store.add_memory("orphan fact")

    def test_duplicate_skipped(self):
        store.add_memory("same", kind="entity", name="lars")
        store.add_memory("same", kind="entity", name="lars")
        text = (self.user / "entities" / "lars.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("- same"), 1)


if __name__ == "__main__":
    unittest.main()
