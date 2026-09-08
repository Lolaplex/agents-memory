import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CLIComprehensiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.user.mkdir()
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n",
            encoding="utf-8",
        )
        self.scan_json = self.user / "scan.json"
        self.scan_json.write_text(
            json.dumps({"roots": [str(self.root)], "ignore_slugs": []}),
            encoding="utf-8",
        )
        self.env = dict(os.environ)
        self.env["PYTHONPATH"] = str(ROOT / "src")

    def tearDown(self):
        self.tmp.cleanup()

    def _run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "agents_memory", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=check,
            env=self.env,
        )

    def test_root_help(self):
        res = self._run_cli("-h")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Usage: python -m agents_memory COMMAND", res.stdout)
        self.assertIn("sync", res.stdout)
        self.assertIn("inventory", res.stdout)
        self.assertIn("distill", res.stdout)
        self.assertIn("search", res.stdout)
        self.assertIn("write", res.stdout)
        self.assertIn("delete", res.stdout)
        self.assertIn("related", res.stdout)

    def test_unknown_command(self):
        res = self._run_cli("unknown_command_xyz", check=False)
        self.assertEqual(res.returncode, 2)
        self.assertIn("unknown command: unknown_command_xyz", res.stderr)

    def test_help_json_command(self):
        res = self._run_cli("help-json")
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data["name"], "agents-memory")
        self.assertIn("scripts", data)
        self.assertIn("commands", data)
        self.assertIn("injection", data)
        self.assertIn("search", data["scripts_no_flags"])
        self.assertIn("write", data["commands"])

    def test_write_read_delete_roundtrip(self):
        agents = self.root / "agents"
        mem = agents / "memory"
        note = mem / "notes"
        note.mkdir(parents=True)
        target = note / "cli-roundtrip.md"
        target.write_text("line-one\nline-two\nline-three\n", encoding="utf-8")
        (mem / "USER.md").write_text("# User\n\nName: Test\n", encoding="utf-8")
        (mem / "PROJECTS.md").write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n",
            encoding="utf-8",
        )
        (mem / "scan.json").write_text(
            json.dumps({"roots": [], "ignore_slugs": []}),
            encoding="utf-8",
        )
        self.env["AGENTS_HOME"] = str(agents)

        write = self._run_cli(
            "write",
            "user/notes/cli-roundtrip.md",
            "alpha\nbeta\ngamma\n",
        )
        self.assertEqual(write.returncode, 0)
        self.assertIn("Wrote", write.stdout)
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "alpha\nbeta\ngamma\n",
        )

        read = self._run_cli("read", "user/notes/cli-roundtrip.md")
        self.assertEqual(read.returncode, 0)
        self.assertIn("beta", read.stdout)

        deleted = self._run_cli("delete", "user/notes/cli-roundtrip.md:2")
        self.assertEqual(deleted.returncode, 0)
        body = target.read_text(encoding="utf-8")
        self.assertNotIn("beta", body)
        self.assertIn("alpha", body)
        self.assertIn("gamma", body)

    def test_write_requires_content(self):
        agents = self.root / "agents"
        mem = agents / "memory"
        mem.mkdir(parents=True)
        target = mem / "USER.md"
        target.write_text("# keep\n", encoding="utf-8")
        env = dict(self.env)
        env["AGENTS_HOME"] = str(agents)
        res = subprocess.run(
            [sys.executable, "-m", "agents_memory", "write", "user/USER.md"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            input="",
            env=env,
        )
        self.assertEqual(res.returncode, 2)
        self.assertIn("usage: python -m agents_memory write", res.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "# keep\n")

    def test_delete_requires_id(self):
        res = self._run_cli("delete", check=False)
        self.assertEqual(res.returncode, 2)
        self.assertIn("usage: python -m agents_memory delete", res.stderr)

    def test_related_requires_id(self):
        res = self._run_cli("related", check=False)
        self.assertEqual(res.returncode, 2)

    def test_extract_openai_deprecation_notice(self):
        res = self._run_cli("extract-openai", "--help", check=False)
        # argparse help exits 0; deprecation prints on stderr before run path —
        # --help may short-circuit inside extract_openai. Force missing export path.
        res = self._run_cli("extract-openai", "--zip", str(self.root / "missing.zip"), check=False)
        self.assertIn("DEPRECATED", res.stderr)
    def test_inventory_cli_json(self):
        res = self._run_cli("inventory", "--json")
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertIn("tracked", data)
        self.assertIn("unknown", data)

    def test_distill_cli_empty(self):
        res = self._run_cli("distill")
        self.assertEqual(res.returncode, 0)
        # Should output either empty message or bullet items
        self.assertTrue(
            "Staging inbox is empty" in res.stdout
            or "Staging inbox" in res.stdout
        )

    def test_sync_cli_help_json(self):
        res = self._run_cli("sync", "--help-json")
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data["name"], "sync")
        self.assertIn("abi_version", data)

    def test_search_cli_requires_query(self):
        res = self._run_cli("search", check=False)
        self.assertEqual(res.returncode, 2)
        self.assertIn("usage: python -m agents_memory search QUERY", res.stderr)

    def test_ingest_cli_status(self):
        res = self._run_cli("ingest", "status")
        self.assertEqual(res.returncode, 0)
        self.assertIn("state_file", res.stdout)


if __name__ == "__main__":
    unittest.main()
