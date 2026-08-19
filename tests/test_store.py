import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agent_memory import store


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

    def test_promote_bullet_removes_from_staging(self):
        staging = self.user / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        captured = staging / "captured.md"
        captured.write_text("# Staging\n\n- fact to promote\n- other fact\n", encoding="utf-8")

        loc, removed = store.promote_bullet(
            "fact to promote",
            kind="concept",
            name="promoted-concept",
        )
        self.assertTrue(removed)
        self.assertIn("promoted-concept.md", loc)
        concept_file = self.user / "concepts" / "promoted-concept.md"
        self.assertTrue(concept_file.exists())
        self.assertIn("fact to promote", concept_file.read_text(encoding="utf-8"))
        captured_text = captured.read_text(encoding="utf-8")
        self.assertNotIn("fact to promote", captured_text)
        self.assertIn("other fact", captured_text)

    def test_get_staging_inbox(self):
        staging = self.user / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "captured.md").write_text("# Staging\n\n- item 1\n- item 2\n", encoding="utf-8")

        inbox = store.get_staging_inbox()
        self.assertEqual(inbox["total"], 2)
        self.assertEqual(len(inbox["groups"]), 1)
        bullets = inbox["groups"][0]["bullets"]
        self.assertEqual(bullets[0]["bullet"], "item 1")
        self.assertEqual(bullets[1]["bullet"], "item 2")
        self.assertEqual(bullets[0]["source_path"], bullets[0]["file"])

    def test_get_staging_inbox_groups_by_source(self):
        ingest_a = self.user / "staging" / "ingest" / "src-a"
        ingest_b = self.user / "staging" / "ingest" / "src-b"
        ingest_a.mkdir(parents=True, exist_ok=True)
        ingest_b.mkdir(parents=True, exist_ok=True)
        (ingest_a / "captured.md").write_text("# A\n\n- shared text\n", encoding="utf-8")
        (ingest_b / "captured.md").write_text("# B\n\n- shared text\n", encoding="utf-8")

        inbox = store.get_staging_inbox(limit=0)
        self.assertEqual(inbox["total"], 2)
        self.assertEqual(len(inbox["groups"]), 2)

    def test_get_staging_inbox_parses_title(self):
        staging = self.user / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        line = "[Homelab @ C:/tmp/x.jsonl] Never force-reset vendor.lock"
        (staging / "captured.md").write_text(f"# Staging\n\n- {line}\n", encoding="utf-8")

        item = store.get_staging_inbox()["groups"][0]["bullets"][0]
        self.assertEqual(item["title"], "Homelab")
        self.assertEqual(item["origin"], "C:/tmp/x.jsonl")
        self.assertIn("vendor.lock", item["text"])

    def test_staging_status_summary_nag(self):
        staging = self.user / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        lines = "\n".join(f"- bullet {i}" for i in range(5))
        (staging / "captured.md").write_text(f"# Staging\n\n{lines}\n", encoding="utf-8")
        ingest = {"version": 1, "sources": [], "staging_nag_threshold": 3}
        with patch("agent_memory.ingest_config.load_ingest", lambda: ingest):
            summary = store.staging_status_summary()
        self.assertEqual(summary["bullet_count"], 5)
        self.assertIn("memory-distill", summary["nag"])

    def test_distill_batch(self):
        staging = self.user / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "captured.md").write_text("# Staging\n\n- keep me\n- throw me away\n", encoding="utf-8")

        res = store.distill_batch([
            {"bullet": "keep me", "kind": "concept", "name": "kept"},
            {"bullet": "throw me away", "discard": True},
        ])
        self.assertEqual(res["promoted"], 1)
        self.assertEqual(res["discarded"], 1)
        self.assertEqual(res["remaining_staging_count"], 0)
        self.assertTrue((self.user / "concepts" / "kept.md").exists())
        self.assertIn("keep me", (self.user / "concepts" / "kept.md").read_text(encoding="utf-8"))

    def test_search_memory_caching(self):
        store.clear_memory_cache()
        doc = self.user / "concepts" / "cached-doc.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("# Cached Doc\n\n- search_term_unique_123\n", encoding="utf-8")

        hits1 = store.search_memory("search_term_unique_123")
        self.assertEqual(len(hits1), 1)

        self.assertIn(str(doc.resolve()), store._MEMORY_FILE_CACHE)

        hits2 = store.search_memory("search_term_unique_123")
        self.assertEqual(len(hits2), 1)

    def test_compact_always_on(self):
        scan_cfg = {"roots": [str(self.root)], "compact_always_on": True}
        with patch.object(store, "load_scan", lambda: scan_cfg), patch.object(
            store, "USER_MD", self.user / "USER.md"
        ):
            (self.user / "USER.md").write_text("Name: Tester\n", encoding="utf-8")
            body = store.always_on_body()
            self.assertIn("# Projects (Compact)", body)
            self.assertIn("| demo | test | py | active |", body)

    def test_compact_always_on_default(self):
        scan_cfg = {"roots": [str(self.root)]}
        with patch.object(store, "load_scan", lambda: scan_cfg), patch.object(
            store, "USER_MD", self.user / "USER.md"
        ):
            (self.user / "USER.md").write_text("Name: Tester\n", encoding="utf-8")
            body = store.always_on_body()
            self.assertIn("# Projects (Compact)", body)

    def test_project_agents_text_is_slice(self):
        p = store.Project(
            slug="demo",
            path=str(self.root / "demo"),
            role="test role",
            stack="py",
            status="active",
        )
        text = store.project_agents_text(p)
        self.assertIn("Project: demo", text)
        self.assertIn("get_project_memories", text)
        self.assertNotIn("notes/proposed", text)

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


class RegisterBootstrapTests(unittest.TestCase):
    def test_register_no_empty_memory_dirs(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        user = root / "user"
        repo = root / "repo"
        user.mkdir()
        repo.mkdir()
        projects_md = user / "PROJECTS.md"
        projects_md.write_text(
            "# Projects\n\n| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n",
            encoding="utf-8",
        )
        with patch.object(store, "USER_MEMORY", user), patch.object(
            store, "PROJECTS_MD", projects_md
        ), patch.object(store, "ORPHANS", user / "orphans"), patch.object(
            store, "sync_injection", lambda **k: ([], [])
        ):
            store.register_project("demo", str(repo), "test", "py")
        mem = repo / ".agents" / "memory"
        self.assertTrue((mem / "README.md").exists())
        self.assertTrue((mem / "staging" / "captured.md").exists())
        for child in mem.rglob("*"):
            if child.is_dir():
                self.assertTrue(any(child.iterdir()), f"empty dir: {child}")


    def test_engine_repo_skips_in_tree_agents(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        user = root / "user"
        engine = root / "engine-clone"
        user.mkdir()
        engine.mkdir()
        projects_md = user / "PROJECTS.md"
        projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n"
            f"| engine-clone | `{engine}` | engine | py | active |\n",
            encoding="utf-8",
        )
        with patch.object(store, "ROOT", engine), patch.object(
            store, "USER_MEMORY", user
        ), patch.object(store, "PROJECTS_MD", projects_md), patch.object(
            store, "ORPHANS", user / "orphans"
        ), patch.object(store, "sync_injection", lambda **k: ([], [])):
            store.register_project("engine-clone", str(engine), "engine", "py")
            written = store.inject_into_repo(
                store.Project("engine-clone", str(engine), "engine", "py")
            )
        self.assertFalse((engine / ".agents").exists())
        self.assertEqual(written, [])

    def test_purge_engine_repo_injection(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        user = root / "user"
        engine = root / "engine-clone"
        user.mkdir()
        engine.mkdir()
        agents = engine / ".agents" / "memory" / "staging"
        agents.mkdir(parents=True)
        (agents / "captured.md").write_text("# Staging\n\n- stray fact\n", encoding="utf-8")
        (engine / ".cursor" / "skills").mkdir(parents=True)
        with patch.object(store, "ROOT", engine), patch.object(
            store, "USER_MEMORY", user
        ):
            moved = store.purge_engine_repo_injection()
        self.assertFalse((engine / ".agents").exists())
        self.assertFalse((engine / ".cursor").exists())
        self.assertTrue(any("removed engine" in line for line in moved))
        dest = user / "staging" / "captured.md"
        self.assertIn("stray fact", dest.read_text(encoding="utf-8"))

    def test_shipped_layout_exists(self):
        self.assertTrue(store.ABI_LAYOUT.is_file())
        text = store.shipped_layout_text()
        self.assertIn("# Agent memory layout", text)
        self.assertIn("staging/", text)
        self.assertIn("No dump files", text)


if __name__ == "__main__":
    unittest.main()
