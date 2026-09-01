"""Tests for remote server, client config, and sync endpoints (isolated)."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from starlette.testclient import TestClient

import agents_memory.remote.server as server_mod
import agents_memory.remote.client as client_mod
from agents_memory.remote.server import create_remote_app
from agents_memory.remote.client import (
    save_remote_config,
    get_remote_config,
    clear_remote_config,
)


class TestRemoteServerClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.patchers = [
            patch.object(server_mod, "USER_MEMORY", self.tmp_path),
            patch.object(client_mod, "USER_MEMORY", self.tmp_path),
            patch.object(client_mod, "CONFIG_FILE", self.tmp_path / "remote_config.json"),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.tmp.cleanup()

    def test_server_health_unauthenticated(self):
        app = create_remote_app(token="supersecret123")
        client = TestClient(app)

        # Missing token -> 401
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 401)

        # Invalid token -> 401
        resp = client.get("/health", headers={"Authorization": "Bearer wrongtoken"})
        self.assertEqual(resp.status_code, 401)

        # Valid token header -> 200
        resp = client.get("/health", headers={"Authorization": "Bearer supersecret123"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("version", data)

        # Valid token query param -> 200
        resp = client.get("/health?token=supersecret123")
        self.assertEqual(resp.status_code, 200)

    def test_server_endpoints(self):
        app = create_remote_app(token="testtoken")
        client = TestClient(app)
        headers = {"Authorization": "Bearer testtoken"}

        # Test snapshot
        resp = client.get("/api/v1/snapshot", headers=headers)
        self.assertEqual(resp.status_code, 200)
        snap = resp.json()
        self.assertEqual(snap["status"], "ok")
        self.assertIsInstance(snap.get("files"), dict)

        # Test merge
        merge_payload = {
            "files": {
                "test_remote_sync_file.md": "# Test Sync\n- Hello from test client\n"
            }
        }
        resp = client.post("/api/v1/merge", json=merge_payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        res = resp.json()
        self.assertEqual(res["status"], "ok")
        self.assertIn("report", res)

        # Test get file
        resp = client.get("/api/v1/file?path=test_remote_sync_file.md", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Hello from test client", resp.text)

    def test_client_config_cycle(self):
        # Save config
        saved = save_remote_config(
            url="https://memory.test.dev",
            token="mytoken",
            auto_pull=True,
        )
        self.assertEqual(saved["url"], "https://memory.test.dev")

        # Get config
        cfg = get_remote_config()
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["url"], "https://memory.test.dev")
        self.assertEqual(cfg["token"], "mytoken")

        # Clear config
        cleared = clear_remote_config()
        self.assertTrue(cleared)
        self.assertIsNone(get_remote_config())


if __name__ == "__main__":
    unittest.main()
