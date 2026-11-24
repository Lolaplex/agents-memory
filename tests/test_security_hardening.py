"""Path confinement, FTS index freshness, and turn-scoped auto_sync."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents_memory import index, store


class TraversalTests(unittest.TestCase):
    """resolve_memory_path must refuse escapes on every rooted prefix."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.rules = self.root / "rules"
        self.repo = self.root / "repo"
        for d in (self.user, self.rules, self.repo):
            d.mkdir(parents=True)
        mem = self.repo / ".agents" / "memory"
        mem.mkdir(parents=True)
        (mem / "facts.md").write_text("# f\n", encoding="utf-8")
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n"
            f"| foo | `{self.repo}` | t | py | active |\n",
            encoding="utf-8",
        )
        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "AGENTS_RULES", self.rules),
            patch.object(store, "PROJECTS_MD", self.projects_md),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_user_traversal_raises(self) -> None:
        for bad in ("user/../../etc/passwd", "user/notes/../../../etc/passwd",
                    "user/../secrets"):
            with self.assertRaises(ValueError):
                store.resolve_memory_path(bad)

    def test_rules_traversal_raises(self) -> None:
        with self.assertRaises(ValueError):
            store.resolve_memory_path("rules/../secrets")

    def test_project_traversal_raises(self) -> None:
        with self.assertRaises(ValueError):
            store.resolve_memory_path("project/foo/../../bar")
        with self.assertRaises(ValueError):
            store.resolve_memory_path("project/foo/notes/../../../etc/passwd")

    def test_ws_traversal_raises(self) -> None:
        with self.assertRaises(ValueError):
            store.resolve_memory_path("ws/../escape")
        with self.assertRaises(ValueError):
            store.resolve_memory_path("ws/../../etc/passwd")

    def test_ws_prefix_is_never_a_store_root(self) -> None:
        # ws/ would hand agents the whole workspace dir — mcp.json,
        # config.json, store.db, modules/, schedules/ are takeover targets.
        for bad in ("ws/mcp.json", "ws/config.json", "ws/store.db",
                    "ws/modules/host.json", "ws/schedules/job.json"):
            with self.assertRaises(ValueError):
                store.resolve_memory_path(bad)
        with self.assertRaises(ValueError):
            store.write_memory_file("ws/mcp.json", "{}", auto_sync=False)
        with self.assertRaises(ValueError):
            store.delete_memory_file("ws/store.db", auto_sync=False)

    def test_bare_and_absolute_traversal_raise(self) -> None:
        with self.assertRaises(ValueError):
            store.resolve_memory_path("notes/../../etc/passwd")
        outside = str(self.root / "outside.md")
        with self.assertRaises(ValueError):
            store.resolve_memory_path(outside)
        # POSIX-style absolute outside any root: a leading "/" must classify
        # as absolute before normalization, on every platform.
        with self.assertRaises(ValueError):
            store.resolve_memory_path("/tmp/outside.md")

    def test_legit_paths_still_resolve(self) -> None:
        f = self.user / "notes" / "x.md"
        f.parent.mkdir(parents=True)
        f.write_text("# x\n", encoding="utf-8")
        self.assertEqual(store.resolve_memory_path("user/notes/x.md"), f.resolve())
        self.assertEqual(
            store.resolve_memory_path("project/foo/facts.md"),
            (self.repo / ".agents" / "memory" / "facts.md").resolve(),
        )
        # absolute path inside a root stays legal
        self.assertEqual(store.resolve_memory_path(str(f)), f.resolve())
        # posix-style absolute inside a root stays legal too
        self.assertEqual(
            store.resolve_memory_path(f"{self.user.as_posix()}/notes/x.md"),
            f.resolve(),
        )
        # traversal that stays inside the root is allowed
        self.assertEqual(
            store.resolve_memory_path("user/notes/../notes/x.md"), f.resolve())

    def test_read_write_delete_propagate_value_error(self) -> None:
        with self.assertRaises(ValueError):
            store.read_memory_file("user/../../etc/passwd")
        with self.assertRaises(ValueError):
            store.write_memory_file("user/../../etc/x.md", "x", auto_sync=False)
        with self.assertRaises(ValueError):
            store.delete_memory_file("project/foo/../../bar", auto_sync=False)


class IndexFreshnessTests(unittest.TestCase):
    """Mutations keep .index/fts.sqlite in step — no stale docs served."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.repo = self.root / "repo"
        for d in (self.user, self.repo):
            d.mkdir(parents=True)
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n"
            f"| foo | `{self.repo}` | t | py | active |\n",
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

    def _ids(self) -> set:
        hits = index.search_hybrid("canary-term", db_path=self.fts)
        return {h["id"] for h in hits}

    def _row_ids(self) -> set:
        import sqlite3
        conn = sqlite3.connect(str(self.fts))
        try:
            return {r[0] for r in conn.execute("SELECT id FROM documents_fts")}
        finally:
            conn.close()

    def test_add_upserts_row_without_rebuild(self) -> None:
        index.rebuild_index(db_path=self.fts)
        store.add_memory("a canary-term fact", kind="concept", name="can",
                         auto_sync=False)
        self.assertIn("user/concepts/can.md", self._ids())
        rel = index.get_related("user/concepts/can.md", db_path=self.fts)
        self.assertEqual(rel["id"], "user/concepts/can.md")

    def test_write_memory_file_refreshes_row(self) -> None:
        store.write_memory_file("user/notes/w.md", "# W\n\n- canary-term\n",
                                auto_sync=False)
        index.rebuild_index(db_path=self.fts)
        store.write_memory_file("user/notes/w.md", "# W\n\n- other\n",
                                auto_sync=False)
        self.assertNotIn("user/notes/w.md", self._ids())

    def test_delete_memory_file_hides_doc_immediately(self) -> None:
        store.write_memory_file("user/notes/doomed.md",
                                "# D\n\n- canary-term\n", auto_sync=False)
        store.write_memory_file("user/notes/keeper.md",
                                "# K\n\n- canary-term\n", auto_sync=False)
        index.rebuild_index(db_path=self.fts)
        self.assertIn("user/notes/doomed.md", self._ids())
        rel = index.get_related("user/notes/keeper.md", db_path=self.fts)
        self.assertTrue(
            any(d["id"] == "user/notes/doomed.md"
                for d in rel["related_documents"]))
        store.delete_memory_file("user/notes/doomed.md", auto_sync=False)
        self.assertNotIn("user/notes/doomed.md", self._ids())
        rel = index.get_related("user/notes/keeper.md", db_path=self.fts)
        self.assertFalse(
            any(d["id"] == "user/notes/doomed.md"
                for d in rel["related_documents"]))
        self.assertFalse(
            any(h["file"] == "user/notes/doomed.md"
                for h in store.search_memory("canary-term")))

    def test_delete_memory_line_updates_row(self) -> None:
        store.write_memory_file(
            "user/notes/lines.md",
            "# L\n\n- canary-term alpha\n- stay beta\n",
            auto_sync=False)
        index.rebuild_index(db_path=self.fts)
        store.delete_memory("user/notes/lines.md:3", auto_sync=False)
        self.assertNotIn("user/notes/lines.md", self._ids())

    def test_write_in_unindexed_workspace_rebuilds_all(self) -> None:
        # First write in a fresh/synced workspace must not mint a 1-doc
        # fts.sqlite — that blinds search to every pre-existing file.
        notes = self.user / "notes"
        notes.mkdir(parents=True, exist_ok=True)
        for i in range(25):
            (notes / f"n{i}.md").write_text(
                f"# N{i}\n\n- canary-term\n", encoding="utf-8")
        self.assertFalse(self.fts.exists())
        store.write_memory_file("user/notes/new.md",
                                "# New\n\n- canary-term\n", auto_sync=False)
        self.assertFalse(self.fts.exists())
        hits = {h["id"] for h in index.search_hybrid(
            "canary-term", limit=100, db_path=self.fts)}
        expected = {f"user/notes/n{i}.md" for i in range(25)}
        expected.add("user/notes/new.md")
        self.assertTrue(expected.issubset(hits))
        self.assertTrue(expected.issubset(self._row_ids()))

    def test_project_file_delete_hides_doc(self) -> None:
        mem = self.repo / ".agents" / "memory"
        mem.mkdir(parents=True)
        f = mem / "facts.md"
        f.write_text("# F\n\n- canary-term\n", encoding="utf-8")
        index.rebuild_index(db_path=self.fts)
        index.upsert_document(f, db_path=self.fts)
        self.assertIn("project/foo/facts.md", self._row_ids())
        store.delete_memory_file("project/foo/facts.md", auto_sync=False)
        self.assertNotIn("project/foo/facts.md", self._row_ids())


class AutoSyncDefaultTests(unittest.TestCase):
    """auto_sync=None inside an agent turn must not rewrite host injection."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.user = Path(self.tmp.name) / "user"
        self.user.mkdir(parents=True)
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text("# Projects\n", encoding="utf-8")
        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "PROJECTS_MD", self.projects_md),
        ]
        for p in self.patches:
            p.start()
        self.finish_p = patch.object(store, "_finish_store_write")
        self.finish = self.finish_p.start()
        class _WS:
            def __init__(self, root: Path) -> None:
                self.user_root = root
                self.index_dir = root / ".index"

            def __getattr__(self, name):
                p = self.user_root / name
                p.mkdir(parents=True, exist_ok=True)
                return p

        fake_ws = _WS(self.user)
        self.store_p = patch.object(store, "memory_store", return_value=fake_ws)
        self.store_p.start()
        store.clear_memory_cache()

    def tearDown(self) -> None:
        self.finish_p.stop()
        self.store_p.stop()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_workspace_turn_defaults_no_sync(self) -> None:
        with patch.dict(os.environ, {"AGENTS_WORKSPACE": "ws1"}):
            store.add_memory("fact x", kind="concept", name="n1")
            self.finish.assert_not_called()
            store.write_memory_file("user/notes/n2.md", "# n\n")
            self.finish.assert_not_called()

    def test_outside_turn_defaults_sync(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "AGENTS_WORKSPACE"}
        with patch.dict(os.environ, env, clear=True):
            store.add_memory("fact y", kind="concept", name="n3")
            self.finish.assert_called_once()

    def test_explicit_auto_sync_wins(self) -> None:
        with patch.dict(os.environ, {"AGENTS_WORKSPACE": "ws1"}):
            store.add_memory("fact z", kind="concept", name="n4", auto_sync=True)
            self.finish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
