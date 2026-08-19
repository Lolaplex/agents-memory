"""Tests for --help-json CLI specs."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HelpJsonTests(unittest.TestCase):
    def _run(self, *args: str) -> dict:
        proc = subprocess.run(
            [sys.executable, "-m", "agent_memory", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(proc.stdout)

    def test_sync_help_json(self) -> None:
        spec = self._run("sync", "--help-json")
        self.assertEqual(spec["name"], "sync")
        self.assertIn("abi_version", spec)
        flags = {o["dest"] for o in spec["options"]}
        self.assertIn("init", flags)
        self.assertIn("no_repos", flags)

    def test_inventory_help_json(self) -> None:
        spec = self._run("inventory", "--help-json")
        self.assertEqual(spec["name"], "inventory")
        flags = {o["dest"] for o in spec["options"]}
        self.assertIn("register", flags)
        self.assertIn("json", flags)

    def test_full_spec(self) -> None:
        spec = self._run("--help-json")
        self.assertEqual(spec["name"], "agent-memory")
        self.assertIn("sync", spec["scripts"])
        self.assertIn("injection", spec)
        self.assertIn("generated_on_sync", spec["injection"])


if __name__ == "__main__":
    unittest.main()
