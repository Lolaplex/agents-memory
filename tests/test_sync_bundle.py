import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agents_memory.remote.sync_bundle as sync_mod
from agents_memory.remote.merge import merge_table_markdown_with_conflicts
from agents_memory.remote.sync_bundle import (
    MIRROR_PREFIX,
    apply_sync_bundle,
    collect_sync_bundle,
)


class TestProjectsMergeIncomingWins(unittest.TestCase):
    def test_incoming_row_replaces_base(self):
        base = "| slug | path |\n| --- | --- |\n| dumbo | C:\\old |\n"
        incoming = "| slug | path |\n| --- | --- |\n| dumbo | C:\\new |\n"
        merged, conflicts = merge_table_markdown_with_conflicts(base, incoming)
        self.assertIn("C:\\new", merged)
        self.assertNotIn("C:\\old", merged)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["slug"], "dumbo")


class TestSyncBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.user.mkdir(parents=True)
        self.rules = self.root / "rules"
        self.rules.mkdir(parents=True)
        self.repo = self.root / "repos" / "demo"
        self.mem = self.repo / ".agents" / "memory"
        self.mem.mkdir(parents=True)
        (self.mem / "facts.md").write_text("# Facts\n- alpha\n", encoding="utf-8")
        (self.user / "USER.md").write_text("# Me\n", encoding="utf-8")
        (self.rules / "user-rules.mdc").write_text("rule\n", encoding="utf-8")

        from types import SimpleNamespace

        self.proj = SimpleNamespace(
            slug="demo",
            path=str(self.repo),
            path_obj=self.repo,
            memory_dir=self.mem,
        )

        self.patchers = [
            patch.object(sync_mod, "USER_MEMORY", self.user),
            patch.object(sync_mod, "AGENTS_RULES", self.rules),
            patch("agents_memory.remote.sync_bundle.parse_projects", return_value=[self.proj]),
            patch.object(sync_mod, "projects_by_slug", return_value={"demo": self.proj}),
            patch.object(sync_mod, "sync_injection", return_value=([], [])),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.tmp.cleanup()

    def test_collect_includes_rules_and_mirror(self):
        bundle = collect_sync_bundle(include_projects=True)
        self.assertIn("USER.md", bundle)
        self.assertIn("rules/user-rules.mdc", bundle)
        self.assertIn(f"{MIRROR_PREFIX}demo/facts.md", bundle)

    def test_apply_mirror_to_repo(self):
        incoming = {
            "USER.md": "# Me\n",
            f"{MIRROR_PREFIX}demo/facts.md": "# Facts\n- beta\n",
        }
        report = apply_sync_bundle(incoming, target_root=self.user, apply_to_repos=True)
        self.assertTrue((self.mem / "facts.md").exists())
        self.assertIn("beta", (self.mem / "facts.md").read_text(encoding="utf-8"))
        self.assertIn("demo/facts.md", "".join(report["repos"]["applied"]))

    def test_collect_stored_mirrors_when_repos_missing(self):
        stored = self.user / "mirror" / "projects" / "ghost"
        stored.mkdir(parents=True)
        (stored / "facts.md").write_text("# Facts\n- ghost\n", encoding="utf-8")
        with patch("agents_memory.remote.sync_bundle.parse_projects", return_value=[]):
            bundle = collect_sync_bundle(include_projects=True, memory_root=self.user)
        self.assertIn(f"{MIRROR_PREFIX}ghost/facts.md", bundle)
        self.assertIn("ghost", bundle[f"{MIRROR_PREFIX}ghost/facts.md"])

    def test_live_repo_wins_over_stored_mirror(self):
        stored = self.user / "mirror" / "projects" / "demo"
        stored.mkdir(parents=True)
        (stored / "facts.md").write_text("# Facts\n- stale\n", encoding="utf-8")
        bundle = collect_sync_bundle(include_projects=True, memory_root=self.user)
        self.assertIn("alpha", bundle[f"{MIRROR_PREFIX}demo/facts.md"])
        self.assertNotIn("stale", bundle[f"{MIRROR_PREFIX}demo/facts.md"])

    def test_collect_skips_board_attach_sidecar(self):
        (self.user / "board_attach.json").write_text('{"attaches":[]}', encoding="utf-8")
        bundle = collect_sync_bundle(include_projects=False, memory_root=self.user)
        self.assertNotIn("board_attach.json", bundle)


if __name__ == "__main__":
    unittest.main()
