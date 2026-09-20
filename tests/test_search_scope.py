"""Search default is user-store only; hybrid fill must not starve other files."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents_memory import index, store


class SearchScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.repo_a = self.root / "repo-a"
        self.repo_b = self.root / "repo-b"
        self.user.mkdir()
        self.repo_a.mkdir()
        self.repo_b.mkdir()
        mem_a = self.repo_a / ".agents" / "memory"
        mem_b = self.repo_b / ".agents" / "memory"
        mem_a.mkdir(parents=True)
        mem_b.mkdir(parents=True)
        (mem_a / "facts.md").write_text("# A\n\n- alpha-unique-canary\n", encoding="utf-8")
        (mem_b / "facts.md").write_text("# B\n\n- beta-unique-canary\n", encoding="utf-8")
        concepts = self.user / "concepts"
        concepts.mkdir()
        (concepts / "prefs.md").write_text(
            "# Prefs\n\n- user-unique-canary\n", encoding="utf-8"
        )
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n"
            f"| alpha | `{self.repo_a}` | test | py | active |\n"
            f"| beta | `{self.repo_b}` | test | py | active |\n",
            encoding="utf-8",
        )
        self.index_dir = self.user / ".index"
        self.fts = self.index_dir / "fts.sqlite"
        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "PROJECTS_MD", self.projects_md),
            patch.object(index, "USER_MEMORY", self.user),
            patch.object(index, "INDEX_DIR", self.index_dir),
            patch.object(index, "FTS_DB", self.fts),
        ]
        for p in self.patches:
            p.start()
        store.clear_memory_cache()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _texts(self, hits: list) -> str:
        return "\n".join(h["text"] for h in hits)

    def test_unqualified_search_is_user_store_only(self) -> None:
        hits = store.search_memory("unique-canary")
        blob = self._texts(hits)
        self.assertIn("user-unique-canary", blob)
        self.assertNotIn("alpha-unique-canary", blob)
        self.assertNotIn("beta-unique-canary", blob)

    def test_slug_includes_that_clone_and_user_not_other(self) -> None:
        hits = store.search_memory("unique-canary", project="alpha")
        blob = self._texts(hits)
        self.assertIn("user-unique-canary", blob)
        self.assertIn("alpha-unique-canary", blob)
        self.assertNotIn("beta-unique-canary", blob)

    def test_star_unions_every_clone(self) -> None:
        hits = store.search_memory("unique-canary", project="*")
        blob = self._texts(hits)
        self.assertIn("user-unique-canary", blob)
        self.assertIn("alpha-unique-canary", blob)
        self.assertIn("beta-unique-canary", blob)

    def test_cwd_infer_picks_containing_clone(self) -> None:
        nested = self.repo_a / "src"
        nested.mkdir()
        self.assertEqual(store.project_slug_for_cwd(nested), "alpha")
        self.assertEqual(store.project_slug_for_cwd(self.root), "")

    def test_exact_saturation_does_not_hide_fts_file(self) -> None:
        noisy = self.user / "notes"
        noisy.mkdir()
        lines = ["# Noise"] + [f"- prefer pnpm filler {i}" for i in range(25)]
        (noisy / "noise.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (self.user / "concepts" / "pkg.md").write_text(
            "# Pkg\n\n- package manager: pnpm\n", encoding="utf-8"
        )
        index.rebuild_index(db_path=self.fts)
        store.clear_memory_cache()
        hits = store.search_memory("prefer pnpm", limit=20)
        files = {h["file"] for h in hits}
        self.assertIn("user/notes/noise.md", files)
        self.assertIn("user/concepts/pkg.md", files)
        for h in hits:
            self.assertNotIn(":0", h["id"].split("#")[0])
            self.assertGreater(h["line"], 0)

    def test_scrubbed_secret_does_not_return_from_search(self) -> None:
        secret = "sk-abcdefghijklmnopqrstuvwxyz"
        store.add_memory(
            f"openai key {secret}",
            kind="concept",
            name="keys",
            auto_sync=False,
        )
        blob = self._texts(store.search_memory("openai key"))
        self.assertNotIn(secret, blob)
        self.assertIn("[redacted]", blob)


if __name__ == "__main__":
    unittest.main()
