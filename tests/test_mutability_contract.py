"""Tests for strict mutability contract enforcement on REVISE_IN_PLACE_KINDS."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents_memory import mcp_server, store


class MutabilityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.repo = self.root / "myrepo"
        self.user.mkdir(parents=True, exist_ok=True)
        self.repo.mkdir(parents=True, exist_ok=True)
        mem = self.repo / ".agents" / "memory"
        mem.mkdir(parents=True, exist_ok=True)

        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n"
            f"| myrepo | `{self.repo}` | test | py | active |\n",
            encoding="utf-8",
        )

        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "PROJECTS_MD", self.projects_md),
            patch.object(store, "AGENTS_RULES", self.root / "rules"),
        ]
        for p in self.patches:
            p.start()
        store.clear_memory_cache()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_initial_creation_of_revise_in_place_succeeds(self) -> None:
        loc = store.add_memory(
            "Use Ed25519 for board authentication",
            kind="decision",
            name="001-board-auth",
            project="myrepo",
            auto_sync=False,
        )
        self.assertTrue(loc.startswith("project/myrepo/decisions/"))
        p = store.resolve_memory_path(loc)
        self.assertTrue(p.is_file())
        self.assertIn("Use Ed25519 for board authentication", p.read_text(encoding="utf-8"))

    def test_subsequent_add_to_existing_revise_in_place_raises(self) -> None:
        loc = store.add_memory(
            "Initial decision",
            kind="decision",
            name="001-arch",
            project="myrepo",
            auto_sync=False,
        )
        p = store.resolve_memory_path(loc)
        initial_content = p.read_text(encoding="utf-8")

        with self.assertRaises(ValueError) as ctx:
            store.add_memory(
                "Appended decision fact",
                kind="decision",
                name="001-arch",
                project="myrepo",
                auto_sync=False,
            )
        self.assertIn("revise-in-place", str(ctx.exception))
        self.assertIn("write_memory_file", str(ctx.exception))

        # File content must remain unmodified
        self.assertEqual(p.read_text(encoding="utf-8"), initial_content)

    def test_mcp_tool_returns_error_for_existing_revise_in_place(self) -> None:
        store.add_memory(
            "Initial research findings",
            kind="research",
            name="browser-cdp",
            project="myrepo",
            auto_sync=False,
        )
        res = mcp_server.add_memory(
            fact_or_message="More research findings",
            kind="research",
            name="browser-cdp",
            project="myrepo",
        )
        self.assertTrue(res.startswith("Error saving memory: Cannot append to existing"))
        self.assertIn("write_memory_file", res)

    def test_normal_append_kinds_still_append(self) -> None:
        loc1 = store.add_memory(
            "FastAPI for backend",
            kind="concept",
            name="stack",
            auto_sync=False,
        )
        loc2 = store.add_memory(
            "Tailwind v3 for styling",
            kind="concept",
            name="stack",
            auto_sync=False,
        )
        self.assertEqual(loc1, loc2)
        p = store.resolve_memory_path(loc1)
        text = p.read_text(encoding="utf-8")
        self.assertIn("FastAPI for backend", text)
        self.assertIn("Tailwind v3 for styling", text)


if __name__ == "__main__":
    unittest.main()
