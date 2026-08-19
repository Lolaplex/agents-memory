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
        path = self.user / "notes" / "projects" / "koru" / "open-questions.md"
        self.assertTrue(path.exists())

    def test_note_collection(self):
        store.add_memory("prefer dark terminals", kind="note", name="ui", collection="preferences")
        path = self.user / "notes" / "preferences" / "ui.md"
        self.assertTrue(path.exists())

    def test_custom_collection(self):
        store.add_memory("blood type O", kind="note", name="health", collection="health")
        path = self.user / "notes" / "health" / "health.md"
        self.assertTrue(path.exists())

    def test_scratch(self):
        store.add_memory("throwaway", kind="scratch", name="tmp")
        self.assertTrue((self.user / "notes" / "scratch" / "tmp.md").exists())

    def test_repo_captured_without_kind(self):
        loc = store.add_memory("local only", project="demo")
        path = self.repo / ".agents" / "memory" / "staging" / "captured.md"
        self.assertTrue(path.exists())
        self.assertIn("local only", path.read_text(encoding="utf-8"))
        self.assertIn("Staging", path.read_text(encoding="utf-8"))
        self.assertIn("captured.md", loc)

    def test_research_in_repo(self):
        store.add_memory("T(ijkl) uniqueness", kind="research", name="isar", project="demo")
        path = self.repo / ".agents" / "memory" / "research" / "isar.md"
        self.assertTrue(path.exists())

    def test_sequential_wave(self):
        store.add_memory("first", kind="waves", name="kernel", project="demo")
        store.add_memory("second", kind="waves", name="proof", project="demo")
        waves = self.repo / ".agents" / "memory" / "waves"
        self.assertTrue((waves / "001-kernel.md").exists())
        self.assertTrue((waves / "002-proof.md").exists())

    def test_lifecycle_and_adr(self):
        store.add_memory(
            "claim one ctx.key per seam",
            kind="proposed",
            name="one-home",
            project="demo",
            collection="architecture",
        )
        store.add_memory(
            "ADR: staging is not memory",
            kind="decision",
            name="staging-inbox",
            project="demo",
        )
        self.assertTrue(
            (
                self.repo
                / ".agents"
                / "memory"
                / "notes"
                / "proposed"
                / "architecture"
                / "001-one-home.md"
            ).exists()
        )
        self.assertTrue(
            (self.repo / ".agents" / "memory" / "decisions" / "001-staging-inbox.md").exists()
        )

    def test_append_same_sequential_name(self):
        store.add_memory("a", kind="tasks", name="hook", project="demo")
        store.add_memory("b", kind="tasks", name="hook", project="demo")
        text = (self.repo / ".agents" / "memory" / "tasks" / "001-hook.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("- a", text)
        self.assertIn("- b", text)
        self.assertFalse(
            (self.repo / ".agents" / "memory" / "tasks" / "002-hook.md").exists()
        )

    def test_project_link_folder(self):
        store.add_memory("canonical tree", kind="project", name="demo")
        path = self.user / "projects" / "demo" / "README.md"
        self.assertTrue(path.exists())

    def test_refuses_dump_without_kind(self):
        with self.assertRaises(ValueError):
            store.add_memory("orphan fact")

    def test_duplicate_skipped(self):
        store.add_memory("same", kind="entity", name="lars")
        store.add_memory("same", kind="entity", name="lars")
        text = (self.user / "entities" / "lars.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("- same"), 1)

    def test_instruction_pair_replaces_symlink_stub(self):
        d = self.root / "pair"
        d.mkdir()
        (d / "CLAUDE.md").write_text("AGENTS.md\n", encoding="utf-8")
        body = f"{store.MARKER}\n\n# test\n"
        written = store.write_instruction_pair(d, body)
        self.assertGreaterEqual(len(written), 1)
        agents = (d / "AGENTS.md").read_bytes()
        claude = (d / "CLAUDE.md").read_bytes()
        self.assertEqual(agents, claude)
        self.assertIn(store.MARKER.encode(), claude)
        self.assertTrue(store._bound_to(d / "CLAUDE.md", d / "AGENTS.md") or agents == claude)

    def test_instruction_pair_skips_foreign_sibling(self):
        d = self.root / "foreign"
        d.mkdir()
        (d / "AGENTS.md").write_text("# someone else's file\n", encoding="utf-8")
        body = f"{store.MARKER}\n\n# test\n"
        written = store.write_instruction_pair(d, body)
        self.assertEqual(written, [])
        self.assertFalse((d / "CLAUDE.md").exists())
        self.assertEqual(
            (d / "AGENTS.md").read_text(encoding="utf-8"),
            "# someone else's file\n",
        )

    def test_foreign_claude_replaced_in_claude_home(self):
        claude_home = self.root / "claude"
        with patch.object(store, "CLAUDE_HOME", claude_home):
            claude_home.mkdir()
            (claude_home / "CLAUDE.md").write_text("# graphify\n", encoding="utf-8")
            canonical = claude_home / "canonical.md"
            canonical.write_text(f"{store.MARKER}\n\n# test\n", encoding="utf-8")
            written, warnings = store.bind_claude_home(canonical)
            claude_text = (claude_home / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertTrue((claude_home / "AGENTS.md").exists())
            self.assertNotIn("graphify", claude_text)
            self.assertIn(store.MARKER, claude_text)
            self.assertTrue(written)


if __name__ == "__main__":
    unittest.main()
