"""Ensure PyPI bundled/ trees stay aligned with repo sources."""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = ROOT / "scripts" / "sync_bundled.py"


class BundledSyncTests(unittest.TestCase):
    def test_bundled_matches_source_trees(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(SYNC_SCRIPT), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            self.fail(detail)

    def test_abi_version_matches_pyproject(self) -> None:
        """abi/VERSION is __version__; it must not drift from the released version."""
        abi_version = (ROOT / "abi" / "VERSION").read_text(encoding="utf-8").strip()
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
        self.assertIsNotNone(match, "pyproject.toml has no [project] version")
        self.assertEqual(
            abi_version,
            match.group(1),
            "abi/VERSION drifted from the pyproject.toml version",
        )


if __name__ == "__main__":
    unittest.main()
