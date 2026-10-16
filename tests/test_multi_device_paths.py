"""Tests for multi-device path resolution and host_paths.json overrides."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents_memory.store import Project


class MultiDevicePathTests(unittest.TestCase):
    def test_project_path_obj_dynamic_resolution(self):
        """When self.path is from another OS, resolve dynamically via scan roots."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            roots_dir = tmp_path / "Coding"
            roots_dir.mkdir(parents=True)
            repo_dir = roots_dir / "veadio"
            repo_dir.mkdir()

            with (
                patch("agents_memory.store.scan_roots", lambda: [str(roots_dir)]),
                patch("agents_memory.store.load_host_paths", lambda: {}),
            ):
                p = Project(slug="veadio", path=r"Z:\foreign_device\Coding\veadio", role="app", stack="TS")
                self.assertEqual(p.path_obj, repo_dir)
                self.assertTrue(p.path_obj.is_dir())

    def test_project_path_obj_host_override(self):
        """Host-local override in host_paths.json takes precedence."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            custom_dir = tmp_path / "custom" / "my-veadio"
            custom_dir.mkdir(parents=True)

            with patch("agents_memory.store.load_host_paths", lambda: {"veadio": str(custom_dir)}):
                p = Project(slug="veadio", path=r"Z:\foreign_device\Coding\veadio", role="app", stack="TS")
                self.assertEqual(p.path_obj, custom_dir)


if __name__ == "__main__":
    unittest.main()
