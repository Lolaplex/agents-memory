"""Tests for deterministic markdown merge engine."""
import unittest
import tempfile
from pathlib import Path

from agents_memory.remote.merge import (
    merge_bullet_markdown,
    merge_table_markdown,
    merge_staging_markdown,
    merge_file_trees,
)


class TestRemoteMerge(unittest.TestCase):
    def test_merge_bullet_markdown_basic(self):
        base = """# Global Facts
- User is Felix
- Uses Windows 11
"""
        incoming = """# Global Facts
- User is Felix
- Prefers Python FastAPI
- Uses Windows 11
"""
        merged = merge_bullet_markdown(base, incoming)
        self.assertIn("- User is Felix", merged)
        self.assertIn("- Uses Windows 11", merged)
        self.assertIn("- Prefers Python FastAPI", merged)
        self.assertEqual(merged.count("User is Felix"), 1)
        self.assertEqual(merged.count("Windows 11"), 1)

    def test_merge_bullet_markdown_new_section(self):
        base = """# Global Facts
- Fact 1
"""
        incoming = """# Global Facts
- Fact 1

# New Rules
- Never use emojis
"""
        merged = merge_bullet_markdown(base, incoming)
        self.assertIn("# Global Facts", merged)
        self.assertIn("# New Rules", merged)
        self.assertIn("- Never use emojis", merged)

    def test_merge_table_markdown_projects(self):
        base = """# Projects (Compact)

| slug | role | stack | status |
| --- | --- | --- | --- |
| demo | test | py | active |
"""
        incoming = """# Projects (Compact)

| slug | role | stack | status |
| --- | --- | --- | --- |
| demo | test | py | active |
| web-app | client frontend | react/ts | dev |
"""
        merged = merge_table_markdown(base, incoming)
        self.assertIn("| demo | test | py | active |", merged)
        self.assertIn("| web-app | client frontend | react/ts | dev |", merged)
        self.assertEqual(merged.count("demo"), 1)
        self.assertEqual(merged.count("web-app"), 1)

    def test_merge_table_incoming_wins_on_edit(self):
        base = """| slug | path |\n| --- | --- |\n| demo | /old/path |\n"""
        incoming = """| slug | path |\n| --- | --- |\n| demo | /new/path |\n"""
        merged = merge_table_markdown(base, incoming)
        self.assertIn("/new/path", merged)
        self.assertNotIn("/old/path", merged)

    def test_merge_staging_markdown(self):
        base = """# Staging Inbox
## Session 1
- Initial raw thought 1
"""
        incoming = """# Staging Inbox
## Session 1
- Initial raw thought 1
- Thought 2 from device B
"""
        merged = merge_staging_markdown(base, incoming)
        self.assertIn("Initial raw thought 1", merged)
        self.assertIn("Thought 2 from device B", merged)
        self.assertEqual(merged.count("Initial raw thought 1"), 1)

    def test_merge_file_trees_tempdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "facts.md").write_text("# Facts\n- Fact 1\n", encoding="utf-8")

            incoming = {
                "facts.md": "# Facts\n- Fact 1\n- Fact 2\n",
                "projects/new_proj.md": "# Project New\nRole: Dev\n",
            }

            report = merge_file_trees(root, incoming)
            self.assertIn("projects/new_proj.md", report["added"])
            self.assertIn("facts.md", report["merged"])

            facts_content = (root / "facts.md").read_text(encoding="utf-8")
            self.assertIn("- Fact 1", facts_content)
            self.assertIn("- Fact 2", facts_content)

            new_proj_content = (root / "projects/new_proj.md").read_text(encoding="utf-8")
            self.assertIn("Role: Dev", new_proj_content)


if __name__ == "__main__":
    unittest.main()
