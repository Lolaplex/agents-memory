import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents_memory import mcp_server, store


class MCPServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.repo = self.root / "repo"
        self.user.mkdir(parents=True)
        self.repo.mkdir(parents=True)
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n"
            f"| demo | `{self.repo}` | demo project | py | active |\n",
            encoding="utf-8",
        )
        self.scan_json = self.user / "scan.json"
        self.scan_json.write_text(
            json.dumps({"roots": [str(self.root)], "ignore_slugs": []}),
            encoding="utf-8",
        )
        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "PROJECTS_MD", self.projects_md),
            patch.object(store, "SCAN_JSON", self.scan_json),
            patch.object(store, "ORPHANS", self.user / "orphans"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_list_projects(self):
        out = mcp_server.list_projects()
        self.assertIn("1 projects:", out)
        self.assertIn("demo |", out)
        self.assertIn("demo project", out)

    def test_list_projects_empty(self):
        self.projects_md.write_text("# Empty\n", encoding="utf-8")
        out = mcp_server.list_projects()
        self.assertIn("No projects in PROJECTS.md", out)

    def test_inventory_projects(self):
        res_str = mcp_server.inventory_projects()
        res = json.loads(res_str)
        self.assertIn("tracked", res)
        self.assertIn("unknown", res)
        self.assertIn("missing", res)
        self.assertEqual(len(res["tracked"]), 1)
        self.assertEqual(res["tracked"][0]["slug"], "demo")

    def test_add_and_search_memory(self):
        store.clear_memory_cache()
        add_res = mcp_server.add_memory(
            "Universal indexing rule",
            kind="concept",
            name="indexing",
        )
        self.assertIn("Saved to user/concepts/indexing.md", add_res)

        search_res = mcp_server.search_memory("Universal indexing")
        self.assertIn("Found 1 hits:", search_res)
        self.assertIn("user/concepts/indexing.md", search_res)

        no_res = mcp_server.search_memory("nonexistent_term_xyz")
        self.assertIn("No local memories for 'nonexistent_term_xyz'", no_res)

    def test_add_memory_missing_kind_error(self):
        res = mcp_server.add_memory("dangling fact without kind or project")
        self.assertIn("Error saving memory:", res)

    def test_get_staging_inbox_and_distill_batch(self):
        staging = self.user / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "captured.md").write_text(
            "# Staging\n\n- durable tech fact\n- throwaway noise\n",
            encoding="utf-8",
        )

        inbox_str = mcp_server.get_staging_inbox()
        inbox = json.loads(inbox_str)
        self.assertEqual(inbox["total"], 2)
        self.assertGreaterEqual(len(inbox["groups"]), 1)

        batch_payload = [
            {
                "bullet": "durable tech fact",
                "kind": "concept",
                "name": "tech-fact",
                "source_path": "user/staging/captured.md",
            },
            {
                "bullet": "throwaway noise",
                "discard": True,
                "source_path": "user/staging/captured.md",
            },
        ]
        res_str = mcp_server.distill_batch(json.dumps(batch_payload))
        res = json.loads(res_str)
        self.assertEqual(res["promoted"], 1)
        self.assertEqual(res["discarded"], 1)
        self.assertEqual(res["remaining_staging_count"], 0)
        self.assertEqual(res["errors"], [])

        # Verify staging file is now clean
        inbox_after = mcp_server.get_staging_inbox()
        self.assertEqual(inbox_after, "Staging inbox is empty (all caught up).")

    def test_distill_batch_invalid_input(self):
        res = mcp_server.distill_batch("invalid json")
        self.assertIn("Error in distill_batch:", res)

        res_not_list = mcp_server.distill_batch(json.dumps({"bullet": "foo"}))
        self.assertIn("Error: expected a JSON list of items", res_not_list)

    def test_promote_bullet(self):
        staging = self.user / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "captured.md").write_text(
            "# Staging\n\n- single fact to promote\n",
            encoding="utf-8",
        )
        res = mcp_server.promote_bullet(
            "single fact to promote",
            kind="workflow",
            name="single-flow",
            source_path="user/staging/captured.md",
        )
        self.assertIn("Promoted to user/workflows/single-flow.md and removed from staging", res)
        self.assertTrue((self.user / "workflows" / "single-flow.md").exists())

    def test_get_project_memories(self):
        # Create in-tree project memory
        proj_mem = self.repo / ".agents" / "memory"
        proj_mem.mkdir(parents=True, exist_ok=True)
        (proj_mem / "README.md").write_text("# Project Info\n\nDetails.\n", encoding="utf-8")

        res = mcp_server.get_project_memories("demo")
        self.assertIn("slug: demo", res)
        self.assertIn("Details.", res)

        res_unknown = mcp_server.get_project_memories("unknown-slug")
        self.assertIn("Unknown project 'unknown-slug'", res_unknown)

    def test_delete_memory(self):
        concept_file = self.user / "concepts" / "del-test.md"
        concept_file.parent.mkdir(parents=True, exist_ok=True)
        concept_file.write_text("# Header\n\n- line to delete\n- keep this\n", encoding="utf-8")

        res = mcp_server.delete_memory("user/concepts/del-test.md:3")
        self.assertIn("Deleted user/concepts/del-test.md:3", res)
        self.assertNotIn("line to delete", concept_file.read_text(encoding="utf-8"))
        self.assertIn("keep this", concept_file.read_text(encoding="utf-8"))

    def test_delete_memory_invalid(self):
        res = mcp_server.delete_memory("bad_id_without_colon")
        self.assertIn("Error deleting memory:", res)

    def test_ignore_project(self):
        res = mcp_server.ignore_project("junk-repo")
        self.assertIn("Ignored slug 'junk-repo'", res)
        scan = json.loads(self.scan_json.read_text(encoding="utf-8"))
        self.assertIn("junk-repo", scan.get("ignore_slugs", []))

    def test_register_project(self):
        new_repo = self.root / "new-app"
        new_repo.mkdir()
        with patch.object(mcp_server, "sync_injection", return_value=(["synced.md"], [])):
            res = mcp_server.register_project(
                slug="new-app",
                path=str(new_repo),
                role="test app",
                stack="ts",
            )
        self.assertIn("Registered new-app", res)
        self.assertTrue((new_repo / ".agents" / "memory" / "staging" / "captured.md").exists())

    def test_sync_local_agents_md(self):
        with patch.object(
            mcp_server,
            "sync_injection",
            return_value=(["user/AGENTS.md"], ["sample warning"]),
        ):
            res = mcp_server.sync_local_agents_md()
        self.assertIn("Synced:", res)
        self.assertIn("user/AGENTS.md", res)
        self.assertIn("sample warning", res)

    def test_ingest_status(self):
        res_str = mcp_server.ingest_status()
        res = json.loads(res_str)
        self.assertIn("state_file", res)
        self.assertIn("sources", res)


if __name__ == "__main__":
    unittest.main()
