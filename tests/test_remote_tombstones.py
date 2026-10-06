"""Replace-pull and deletion tombstones for multi-device sync."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

import agents_memory.remote.client as client_mod
import agents_memory.remote.server as server_mod
import agents_memory.remote.sync_bundle as bundle_mod
import agents_memory.store as store_mod
from agents_memory.remote.client import remote_pull
from agents_memory.remote.server import create_remote_app
from agents_memory.remote.sync_bundle import apply_snapshot_replace
from agents_memory.store import ignore_slug, write_projects
from agents_memory.store import Project


def _iso(days_ago: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _projects(*rows: tuple[str, str]) -> str:
    lines = [
        "# Projects",
        "",
        "| slug | path | role | stack | status |",
        "|------|------|------|-------|--------|",
    ]
    for slug, path in rows:
        lines.append(f"| {slug} | `{path}` | app | py | active |")
    return "\n".join(lines) + "\n"


class TombstoneMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.server_dir = Path(self.tmp.name) / "server"
        self.server_dir.mkdir()
        self.rules = Path(self.tmp.name) / "rules"
        self.rules.mkdir()
        self.patches = [
            patch.object(server_mod, "USER_MEMORY", self.server_dir),
            patch.object(bundle_mod, "AGENTS_RULES", self.rules),
            patch.object(bundle_mod, "sync_injection", lambda **kwargs: ([], [])),
            patch.object(server_mod, "sync_injection", lambda *args, **kwargs: ([], [])),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(create_remote_app(token="tok"))
        self.headers = {"Authorization": "Bearer tok"}

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def _merge(self, payload: dict) -> dict:
        resp = self.client.post("/api/v1/merge", json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def _snapshot(self) -> dict:
        resp = self.client.get("/api/v1/snapshot", headers=self.headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def test_deleted_file_stays_deleted_when_second_device_pushes(self) -> None:
        (self.server_dir / "notes").mkdir()
        (self.server_dir / "notes" / "old.md").write_text("# Old\n", encoding="utf-8")
        (self.server_dir / "notes" / "keep.md").write_text("# Keep\n", encoding="utf-8")

        deleted_at = _iso(10)
        self._merge(
            {
                "files": {"notes/keep.md": "# Keep\n"},
                "tombstones": {
                    "version": 1,
                    "files": {"notes/old.md": deleted_at},
                    "prefixes": {},
                    "rows": {},
                    "bullets": {},
                },
            }
        )
        self.assertFalse((self.server_dir / "notes" / "old.md").is_file())

        # 1.1 client: file bytes, no tombstones, no write stamps.
        self._merge({"files": {"notes/old.md": "# Old\n", "notes/keep.md": "# Keep\n"}})
        self.assertFalse((self.server_dir / "notes" / "old.md").is_file())
        self.assertTrue((self.server_dir / "notes" / "keep.md").is_file())

        # Newer client that still has the stale file (mtime older than the deletion).
        self._merge(
            {
                "files": {"notes/old.md": "# Old\n"},
                "writes": {
                    "files": {"notes/old.md": _iso(40)},
                    "explicit_files": {},
                    "prefixes": {},
                    "rows": {},
                    "bullets": {},
                },
            }
        )
        self.assertFalse((self.server_dir / "notes" / "old.md").is_file())

        snap = self._snapshot()
        self.assertNotIn("notes/old.md", snap["files"])
        self.assertIn("notes/old.md", snap["deleted"])

        device_b = Path(self.tmp.name) / "device-b"
        device_b.mkdir()
        (device_b / "notes").mkdir()
        (device_b / "notes" / "old.md").write_text("# Old\n", encoding="utf-8")
        (device_b / "notes" / "keep.md").write_text("# Keep\n", encoding="utf-8")
        with patch.object(client_mod, "_fetch_snapshot", return_value=snap):
            remote_pull("http://memory.test", target_dir=device_b)
        self.assertFalse((device_b / "notes" / "old.md").exists())
        self.assertTrue((device_b / "notes" / "keep.md").is_file())

    def test_removed_projects_row_survives_old_client_push(self) -> None:
        table = _projects(("keep", "/data/keep"), ("stale", "/data/stale"))
        (self.server_dir / "PROJECTS.md").write_text(table, encoding="utf-8")
        deleted_at = _iso(10)
        cleaned = _projects(("keep", "/data/keep"))
        self._merge(
            {
                "files": {"PROJECTS.md": cleaned},
                "tombstones": {
                    "version": 1,
                    "files": {},
                    "prefixes": {"mirror/projects/stale/": deleted_at},
                    "rows": {"PROJECTS.md": {"stale": deleted_at}},
                    "bullets": {},
                },
            }
        )
        body = (self.server_dir / "PROJECTS.md").read_text(encoding="utf-8")
        self.assertIn("keep", body)
        self.assertNotIn("stale", body)

        self._merge({"files": {"PROJECTS.md": table}})
        body = (self.server_dir / "PROJECTS.md").read_text(encoding="utf-8")
        self.assertIn("| keep |", body)
        self.assertNotIn("stale", body)
        self.assertNotIn("mirror/projects/stale/README.md", self._snapshot()["files"])

    def test_readd_after_delete_wins_when_newer(self) -> None:
        (self.server_dir / "notes").mkdir()
        (self.server_dir / "notes" / "old.md").write_text("# Old\n", encoding="utf-8")
        table = _projects(("keep", "/data/keep"), ("stale", "/data/stale"))
        (self.server_dir / "PROJECTS.md").write_text(table, encoding="utf-8")
        deleted_at = _iso(10)
        self._merge(
            {
                "files": {
                    "PROJECTS.md": _projects(("keep", "/data/keep")),
                    "notes/keep.md": "# Keep\n",
                },
                "tombstones": {
                    "version": 1,
                    "files": {"notes/old.md": deleted_at},
                    "prefixes": {"mirror/projects/stale/": deleted_at},
                    "rows": {"PROJECTS.md": {"stale": deleted_at}},
                    "bullets": {},
                },
            }
        )
        revived = _iso(1)
        self._merge(
            {
                "files": {
                    "notes/old.md": "# Back\n",
                    "PROJECTS.md": table,
                },
                "writes": {
                    "files": {"notes/old.md": revived},
                    "explicit_files": {"notes/old.md": revived},
                    "prefixes": {
                        "mirror/projects/stale/": revived,
                        "projects/stale/": revived,
                    },
                    "rows": {"PROJECTS.md": {"stale": revived}},
                    "bullets": {},
                },
            }
        )
        self.assertEqual(
            (self.server_dir / "notes" / "old.md").read_text(encoding="utf-8"),
            "# Back\n",
        )
        body = (self.server_dir / "PROJECTS.md").read_text(encoding="utf-8")
        self.assertIn("stale", body)

        # A later stale push without a newer write must not drop the re-add.
        self._merge(
            {
                "files": {
                    "notes/old.md": "# Ancient\n",
                    "PROJECTS.md": _projects(("keep", "/data/keep")),
                },
                "writes": {
                    "files": {"notes/old.md": _iso(40)},
                    "explicit_files": {},
                },
            }
        )
        self.assertIn(
            "# Back",
            (self.server_dir / "notes" / "old.md").read_text(encoding="utf-8"),
        )
        self.assertIn("stale", (self.server_dir / "PROJECTS.md").read_text(encoding="utf-8"))

    def test_expired_tombstone_does_not_block(self) -> None:
        (self.server_dir / "notes").mkdir()
        self._merge(
            {
                "files": {"notes/old.md": "# Fresh\n"},
                "tombstones": {
                    "version": 1,
                    "files": {"notes/old.md": "2000-01-01T00:00:00Z"},
                    "prefixes": {},
                    "rows": {},
                    "bullets": {},
                },
            }
        )
        self.assertTrue((self.server_dir / "notes" / "old.md").is_file())
        self.assertIn("# Fresh", (self.server_dir / "notes" / "old.md").read_text(encoding="utf-8"))


class ReplacePullTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = self.root / "memory"
        self.store.mkdir()
        self.rules = self.root / "rules"
        self.rules.mkdir()
        self.repo = self.root / "repo"
        (self.repo / ".agents" / "memory").mkdir(parents=True)
        self.patches = [
            patch.object(bundle_mod, "AGENTS_RULES", self.rules),
            patch.object(store_mod, "USER_MEMORY", self.store),
            patch.object(bundle_mod, "sync_injection", lambda **kwargs: ([], [])),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_replace_removes_stale_files_and_keeps_remote_config(self) -> None:
        (self.store / "USER.md").write_text("# Local\n- extra\n", encoding="utf-8")
        (self.store / "stale.md").write_text("# Stale\n", encoding="utf-8")
        (self.store / "remote_config.json").write_text(
            json.dumps({"url": "https://memory.example", "token": "secret"}),
            encoding="utf-8",
        )
        index = self.store / ".index"
        index.mkdir()
        (index / "cache.txt").write_text("fts", encoding="utf-8")
        (self.repo / ".agents" / "memory" / "extra.md").write_text("# extra\n", encoding="utf-8")
        (self.store / "PROJECTS.md").write_text(
            _projects(("demo", str(self.repo))),
            encoding="utf-8",
        )

        snapshot = {
            "USER.md": "# Remote\n",
            "PROJECTS.md": _projects(("demo", str(self.repo))),
            "mirror/projects/demo/README.md": "# demo\n",
            "rules/user-rules.mdc": "---\nalwaysApply: true\n---\n",
        }
        with patch.object(
            client_mod,
            "_fetch_snapshot",
            return_value={"files": snapshot, "deleted": [], "tombstones": {}},
        ):
            result = remote_pull("http://memory.test", target_dir=self.store, replace=True)

        self.assertTrue(result["replaced"])
        self.assertFalse((self.store / "stale.md").exists())
        self.assertEqual((self.store / "USER.md").read_text(encoding="utf-8"), "# Remote\n")
        cfg = json.loads((self.store / "remote_config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["token"], "secret")
        self.assertEqual((index / "cache.txt").read_text(encoding="utf-8"), "fts")
        self.assertEqual(
            (self.repo / ".agents" / "memory" / "README.md").read_text(encoding="utf-8"),
            "# demo\n",
        )
        self.assertFalse((self.repo / ".agents" / "memory" / "extra.md").exists())
        self.assertEqual(
            (self.rules / "user-rules.mdc").read_text(encoding="utf-8"),
            "---\nalwaysApply: true\n---\n",
        )
        backup = Path(result["backup"])
        self.assertTrue(backup.is_dir())
        self.assertTrue((backup / "stale.md").is_file())
        self.assertTrue(str(backup.name).startswith("memory.bak-"))

    def test_replace_helper_does_not_union_tables(self) -> None:
        (self.store / "PROJECTS.md").write_text(
            _projects(("keep", "/k"), ("stale", "/s")),
            encoding="utf-8",
        )
        report = apply_snapshot_replace(
            {"PROJECTS.md": _projects(("keep", "/k"))},
            target_root=self.store,
            apply_to_repos=False,
        )
        text = (self.store / "PROJECTS.md").read_text(encoding="utf-8")
        self.assertNotIn("stale", text)
        self.assertIn("keep", text)
        self.assertTrue(report["replaced"])


class ProjectRemovalTombstoneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "memory"
        self.store.mkdir()
        self.projects = self.store / "PROJECTS.md"
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.projects.write_text(_projects(("demo", str(self.repo)), ("gone", str(self.repo))), encoding="utf-8")
        mirror = self.store / "mirror" / "projects" / "gone"
        mirror.mkdir(parents=True)
        (mirror / "README.md").write_text("# gone\n", encoding="utf-8")
        self.patches = [
            patch.object(store_mod, "USER_MEMORY", self.store),
            patch.object(store_mod, "PROJECTS_MD", self.projects),
            patch.object(store_mod, "SCAN_JSON", self.store / "scan.json"),
        ]
        for item in self.patches:
            item.start()
        (self.store / "scan.json").write_text(
            json.dumps({"roots": [], "ignore_slugs": []}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_ignore_tracked_slug_tombstones_row_and_prefix(self) -> None:
        ignore_slug("gone")
        text = self.projects.read_text(encoding="utf-8")
        self.assertNotIn("gone", text)
        self.assertIn("demo", text)
        self.assertFalse((self.store / "mirror" / "projects" / "gone" / "README.md").exists())
        raw = json.loads((self.store / ".tombstones.json").read_text(encoding="utf-8"))
        self.assertIn("gone", raw["rows"]["PROJECTS.md"])
        self.assertIn("mirror/projects/gone/", raw["prefixes"])

    def test_write_projects_drop_records_row_tombstone(self) -> None:
        write_projects(
            [Project(slug="demo", path=str(self.repo), role="app", stack="py", status="active")]
        )
        raw = json.loads((self.store / ".tombstones.json").read_text(encoding="utf-8"))
        self.assertIn("gone", raw["rows"]["PROJECTS.md"])


if __name__ == "__main__":
    unittest.main()
