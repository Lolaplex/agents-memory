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
        self.assertIn("injection", data)

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

    def test_ingest_cli_status(self):
        res = self._run_cli("ingest", "status")
        self.assertEqual(res.returncode, 0)
        self.assertIn("state_file", res.stdout)


if __name__ == "__main__":
    unittest.main()
