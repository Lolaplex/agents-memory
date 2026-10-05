"""Vault epoch and minimum client version."""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from starlette.testclient import TestClient

import agents_memory.mcp_server as mcp_server
import agents_memory.remote.client as client_mod
import agents_memory.remote.server as server_mod
import agents_memory.remote.sync_bundle as bundle_mod
import agents_memory.remote.sync_hooks as sync_hooks
import agents_memory.store as store_mod
from agents_memory.remote.client import remote_pull, remote_push_merge, save_remote_config
from agents_memory.remote.protocol import DEFAULT_UPDATE_HINT, upgrade_required_message
from agents_memory.remote.server import create_remote_app
from agents_memory.remote.sync_bundle import save_baseline

EXACT = upgrade_required_message("1.2.0", DEFAULT_UPDATE_HINT)


class ProtocolHttpTests(unittest.TestCase):
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
        self.http = TestClient(create_remote_app(token="tok"))
        self.auth = {"Authorization": "Bearer tok"}
        self._env = {
            "AGENTS_MEMORY_MIN_CLIENT_VERSION": os.environ.get("AGENTS_MEMORY_MIN_CLIENT_VERSION"),
            "AGENTS_MEMORY_UPDATE_HINT": os.environ.get("AGENTS_MEMORY_UPDATE_HINT"),
        }

    def tearDown(self) -> None:
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def _require(self, version: str = "1.2.0") -> None:
        os.environ["AGENTS_MEMORY_MIN_CLIENT_VERSION"] = version
        os.environ.pop("AGENTS_MEMORY_UPDATE_HINT", None)

    def test_426_for_missing_and_old_version_reads_still_work(self) -> None:
        self._require()
        (self.server_dir / "USER.md").write_text("# User\n", encoding="utf-8")

        missing = self.http.post("/api/v1/merge", json={"files": {"stale.md": "# no\n"}}, headers=self.auth)
        self.assertEqual(missing.status_code, 426, missing.text)
        self.assertEqual(missing.json()["error"], EXACT)
        self.assertFalse((self.server_dir / "stale.md").exists())

        old = self.http.post(
            "/api/v1/merge",
            json={"files": {"stale.md": "# no\n"}},
            headers={**self.auth, "X-Agents-Memory-Version": "1.1.1"},
        )
        self.assertEqual(old.status_code, 426, old.text)
        self.assertEqual(old.json()["error"], EXACT)

        put = self.http.put(
            "/api/v1/file",
            json={"path": "stale.md", "content": "# no\n"},
            headers=self.auth,
        )
        self.assertEqual(put.status_code, 426, put.text)
        deleted = self.http.delete("/api/v1/file?path=USER.md", headers=self.auth)
        self.assertEqual(deleted.status_code, 426, deleted.text)

        current = self.http.post(
            "/api/v1/merge",
            json={"files": {"notes.md": "# ok\n"}},
            headers={**self.auth, "X-Agents-Memory-Version": "1.2.0"},
        )
        self.assertEqual(current.status_code, 200, current.text)
        self.assertTrue((self.server_dir / "notes.md").is_file())

        snap = self.http.get("/api/v1/snapshot", headers=self.auth)
        self.assertEqual(snap.status_code, 200, snap.text)
        self.assertEqual(snap.json()["min_client_version"], "1.2.0")
        body = self.http.get("/api/v1/file?path=USER.md", headers=self.auth)
        self.assertEqual(body.status_code, 200, body.text)
        health = self.http.get("/api/v1/health", headers=self.auth)
        self.assertEqual(health.status_code, 200, health.text)

    def test_legacy_raise_for_status_hides_the_update_sentence(self) -> None:
        """1.1.1 push calls raise_for_status(). The exception text is not the JSON body."""
        self._require()
        resp = self.http.post("/api/v1/merge", json={"files": {}}, headers=self.auth)
        self.assertEqual(resp.status_code, 426)
        self.assertEqual(resp.json()["error"], EXACT)

        def legacy_push() -> str:
            try:
                if resp.status_code == 401:
                    raise PermissionError("Unauthorized")
                resp.raise_for_status()
            except Exception as exc:
                return str(exc)
            return ""

        logged = legacy_push()
        self.assertIn("426", logged)
        self.assertNotIn("agents-memory 1.2.0 required", logged)

    def test_epoch_mismatch_rejects_stale_merge(self) -> None:
        (self.server_dir / ".epoch").write_text("2\n", encoding="utf-8")
        (self.server_dir / "USER.md").write_text("# Clean\n", encoding="utf-8")
        resp = self.http.post(
            "/api/v1/merge",
            json={"files": {"stale.md": "# old vault\n"}, "epoch": 0},
            headers={**self.auth, "X-Agents-Memory-Epoch": "0"},
        )
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["code"], "epoch_mismatch")
        self.assertFalse((self.server_dir / "stale.md").exists())
        self.assertIn("# Clean", (self.server_dir / "USER.md").read_text(encoding="utf-8"))

    def test_push_replace_bumps_epoch_and_drops_server_files(self) -> None:
        (self.server_dir / "stale.md").write_text("# stale\n", encoding="utf-8")
        (self.server_dir / "USER.md").write_text("# Old\n", encoding="utf-8")
        resp = self.http.post(
            "/api/v1/merge",
            json={"replace": True, "files": {"USER.md": "# Clean\n"}},
            headers=self.auth,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["epoch"], 1)
        self.assertFalse((self.server_dir / "stale.md").exists())
        self.assertEqual((self.server_dir / "USER.md").read_text(encoding="utf-8"), "# Clean\n")
        snap = self.http.get("/api/v1/snapshot", headers=self.auth)
        self.assertEqual(snap.json()["epoch"], 1)
        self.assertNotIn("stale.md", snap.json()["files"])

    def test_bump_epoch(self) -> None:
        first = self.http.post("/api/v1/epoch", headers=self.auth)
        second = self.http.post("/api/v1/epoch", headers=self.auth)
        self.assertEqual(first.json()["epoch"], 1)
        self.assertEqual(second.json()["epoch"], 2)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ClientEpochRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.server_dir = Path(self.tmp.name) / "server"
        self.client_dir = Path(self.tmp.name) / "client"
        self.rules = Path(self.tmp.name) / "rules"
        self.server_dir.mkdir()
        self.client_dir.mkdir()
        self.rules.mkdir()
        self.patches = [
            patch.object(server_mod, "USER_MEMORY", self.server_dir),
            patch.object(client_mod, "USER_MEMORY", self.client_dir),
            patch.object(client_mod, "CONFIG_FILE", self.client_dir / "remote_config.json"),
            patch.object(store_mod, "USER_MEMORY", self.client_dir),
            patch.object(bundle_mod, "AGENTS_RULES", self.rules),
            patch.object(bundle_mod, "sync_injection", lambda **kwargs: ([], [])),
            patch.object(server_mod, "sync_injection", lambda *args, **kwargs: ([], [])),
        ]
        for item in self.patches:
            item.start()
        port = _free_port()
        self.base = f"http://127.0.0.1:{port}"
        app = create_remote_app(token="tok")
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(50):
            try:
                resp = httpx.get(f"{self.base}/api/v1/health", headers={"Authorization": "Bearer tok"}, timeout=0.2)
                if resp.status_code == 200:
                    break
            except Exception:
                time.sleep(0.05)
        save_remote_config(url=self.base, token="tok", extra={"epoch": 0})

    def tearDown(self) -> None:
        self.server.should_exit = True
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_pull_replace_on_newer_epoch_drops_stale_and_keeps_config(self) -> None:
        (self.server_dir / "USER.md").write_text("# Clean\n", encoding="utf-8")
        (self.server_dir / ".epoch").write_text("3\n", encoding="utf-8")
        (self.client_dir / "USER.md").write_text("# Dirty\n", encoding="utf-8")
        (self.client_dir / "stale.md").write_text("# stale\n", encoding="utf-8")

        result = remote_pull(self.base, token="tok", target_dir=self.client_dir)
        self.assertTrue(result.get("replaced"))
        self.assertFalse((self.client_dir / "stale.md").exists())
        self.assertEqual((self.client_dir / "USER.md").read_text(encoding="utf-8"), "# Clean\n")
        cfg = (self.client_dir / "remote_config.json").read_text(encoding="utf-8")
        self.assertIn('"token": "tok"', cfg)
        self.assertIn('"epoch": 3', cfg)
        self.assertFalse((self.server_dir / "stale.md").exists())

    def test_push_409_replaces_then_retries_pending_write(self) -> None:
        (self.server_dir / "USER.md").write_text("# Clean\n", encoding="utf-8")
        (self.server_dir / ".epoch").write_text("1\n", encoding="utf-8")
        user = "# Clean\n"
        stale = "# stale\n"
        (self.client_dir / "USER.md").write_text(user, encoding="utf-8")
        (self.client_dir / "stale.md").write_text(stale, encoding="utf-8")
        save_baseline(self.client_dir, {"USER.md": user, "stale.md": stale})
        notes = self.client_dir / "notes"
        notes.mkdir(exist_ok=True)
        (notes / "fresh.md").write_text("# Fresh\n", encoding="utf-8")

        result = remote_push_merge(self.base, token="tok", source_dir=self.client_dir)
        self.assertEqual(result["status"], "ok")
        self.assertFalse((self.server_dir / "stale.md").exists())
        self.assertFalse((self.client_dir / "stale.md").exists())
        self.assertEqual((self.server_dir / "notes" / "fresh.md").read_text(encoding="utf-8"), "# Fresh\n")
        self.assertTrue((self.client_dir / "notes" / "fresh.md").is_file())
        self.assertIn('"epoch": 1', (self.client_dir / "remote_config.json").read_text(encoding="utf-8"))


class UpgradeSurfaceTests(unittest.TestCase):
    def test_upgrade_stops_background_push_and_prefixes_tool_result(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            (root / "staging").mkdir()
            cfg = {
                "url": "http://x",
                "token": "t",
                "upgrade_required": EXACT,
            }
            with patch.object(sync_hooks, "get_remote_config", return_value=cfg), patch.object(
                client_mod, "get_remote_config", return_value=cfg
            ), patch.object(sync_hooks, "remote_push_merge") as pushed, patch.object(store_mod, "USER_MEMORY", root):
                self.assertIsNone(sync_hooks.push_if_connected(refresh_index=False))
                pushed.assert_not_called()
                tool = mcp_server.mcp._tool_manager.get_tool("list_projects")
                self.assertIsNotNone(tool)
                text = tool.fn()
            self.assertTrue(text.startswith(EXACT), text)
        finally:
            tmp.cleanup()

    def test_upgrade_required_is_not_retried(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            (root / "staging").mkdir()
            calls = {"n": 0}

            def boom(*_a, **_k):
                calls["n"] += 1
                raise client_mod.UpgradeRequired(EXACT)

            with patch.object(sync_hooks, "get_remote_config", return_value={"url": "http://x", "token": "t"}), patch.object(
                sync_hooks, "remote_push_merge", side_effect=boom
            ), patch.object(sync_hooks, "_refresh_index"), patch.object(store_mod, "USER_MEMORY", root), patch.object(
                sync_hooks.time, "sleep"
            ):
                result = sync_hooks.push_if_connected(refresh_index=False, retries=3)
            self.assertIsNone(result)
            self.assertEqual(calls["n"], 1)
            log = (root / "staging" / "sync-errors.md").read_text(encoding="utf-8")
            self.assertIn("agents-memory 1.2.0 required", log)
        finally:
            tmp.cleanup()
