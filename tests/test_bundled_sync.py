"""Ensure PyPI bundled/ trees stay aligned with repo sources."""
from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
