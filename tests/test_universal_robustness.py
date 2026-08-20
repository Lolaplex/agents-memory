"""Tests for universal robustness, auto-discovery, secret blacklist, and priority features."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents_memory import store, ingest_common
from agents_memory.ingest_common import PII, is_secret_or_env_path, scrub


class UniversalRobustnessTests(unittest.TestCase):
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

    def test_secret_filtering_and_scrubbing(self):
        # 1. Path filtering
        self.assertTrue(is_secret_or_env_path(".env"))
        self.assertTrue(is_secret_or_env_path(".env.local"))
        self.assertTrue(is_secret_or_env_path("id_rsa"))
        self.assertTrue(is_secret_or_env_path("server.key"))
        self.assertTrue(is_secret_or_env_path("cert.pem"))
        self.assertTrue(is_secret_or_env_path("/home/user/.ssh/config"))
        self.assertFalse(is_secret_or_env_path("src/index.ts"))
        self.assertFalse(is_secret_or_env_path("README.md"))

        # 2. Key scrubbing
        test_samples = [
            ("sk-1234567890abcdef1234567890", "[redacted]"),
            ("sk-ant-api03-abcdefghijklmnopqrstuvwxyz", "[redacted]"),
            ("ghp_123456789012345678901234567890", "[redacted]"),
            ("re_12345678901234567890", "[redacted]"),
            ("nfp_12345678901234567890", "[redacted]"),
            ("AIzaSyD-1234567890123456789012345678901", "[redacted]"),
            ("AKIAIOSFODNN7EXAMPLE", "[redacted]"),
        ]
        for secret_sample, expected in test_samples:
            scrubbed = scrub(f"Here is my key: {secret_sample}")
            self.assertNotIn(secret_sample, scrubbed)
            self.assertIn(expected, scrubbed)

    def test_add_memory_auto_scrubs_secrets(self):
        store.add_memory("Use OpenAI key sk-abcdef1234567890abcdef for testing", kind="concept", name="api")
        target_file = self.user / "concepts" / "api.md"
        self.assertTrue(target_file.exists())
        content = target_file.read_text(encoding="utf-8")
        self.assertNotIn("sk-abcdef1234567890abcdef", content)
        self.assertIn("[redacted]", content)

    def test_atomic_write_concurrency(self):
        target = self.root / "concurrent.txt"
        errors = []

        def worker(num: int):
            try:
                for i in range(15):
                    store._write(target, f"worker-{num}-step-{i}\n")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertTrue(target.exists())
        self.assertTrue(len(target.read_text(encoding="utf-8").strip()) > 0)

    def test_legacy_mcp_cleanup(self):
        mcp_file = self.root / "mcp.json"
        initial_data = {
            "mcpServers": {
                "agent-memory": {"command": "python", "args": ["-m", "agent_memory"]},
                "agent_memory": {"command": "python", "args": ["-m", "agent_memory"]},
                "fetch": {"command": "python", "args": ["-m", "mcp_server_fetch"]},
            }
        }
        mcp_file.write_text(json.dumps(initial_data), encoding="utf-8")
        res = store._merge_mcp_server_into_file(mcp_file)
        self.assertIn("OK", res)

        updated = json.loads(mcp_file.read_text(encoding="utf-8"))
        servers = updated["mcpServers"]
        self.assertNotIn("agent-memory", servers)
        self.assertNotIn("agent_memory", servers)
        self.assertIn("agents-memory", servers)
        self.assertIn("fetch", servers)

    def test_priority_project_over_user_memory(self):
        # Create a user concept and a project plan
        store.add_memory("User level fact", kind="concept", name="auth")
        project_mem = self.repo / ".agents" / "memory" / "plans"
        project_mem.mkdir(parents=True, exist_ok=True)
        (project_mem / "001-auth.md").write_text("# Project Auth Plan\n\n- Project level fact\n", encoding="utf-8")

        files = store.iter_memory_files(project="demo")
        self.assertTrue(len(files) >= 2)
        # First file must be project file
        self.assertIn("repo", str(files[0]))
        self.assertIn("001-auth.md", str(files[0]))

    def test_moved_repo_detection(self):
        # Simulate demo repo moved to demo-v2
        moved_repo = self.root / "demo-v2"
        moved_repo.mkdir()
        (moved_repo / "package.json").write_text("{}", encoding="utf-8")
        # Remove original repo to simulate missing path
        for p in self.repo.iterdir():
            if p.is_dir():
                for sub in p.rglob("*"):
                    if sub.is_file():
                        sub.unlink()
            elif p.is_file():
                p.unlink()
        self.repo.rmdir()

        with patch.object(store, "discover_disk", return_value=[("demo-v2", moved_repo)]):
            report = store.inventory_report()
            self.assertTrue(len(report["missing"]) > 0)
            self.assertTrue(len(report.get("moved", [])) > 0)
            self.assertEqual(report["moved"][0]["slug"], "demo")
            self.assertEqual(report["moved"][0]["new_path"], str(moved_repo.resolve()))


if __name__ == "__main__":
    unittest.main()
