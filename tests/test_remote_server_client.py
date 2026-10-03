"""Tests for remote server, client config, and sync endpoints (isolated)."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from starlette.testclient import TestClient

import agents_memory.remote.server as server_mod
import agents_memory.remote.client as client_mod
import agents_memory.store as store_mod
from agents_memory.remote.server import create_remote_app, get_server_tombstones
from agents_memory.remote.client import (
    save_remote_config,
    get_remote_config,
    clear_remote_config,
    remote_delete_file,
)


class TestRemoteServerClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.patchers = [
            patch.object(server_mod, "USER_MEMORY", self.tmp_path),
            patch.object(client_mod, "USER_MEMORY", self.tmp_path),
            patch.object(store_mod, "USER_MEMORY", self.tmp_path),
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
        import agents_memory.remote.client as client_mod
        orig_config_file = client_mod.CONFIG_FILE
        try:
            with tempfile.TemporaryDirectory() as td:
                client_mod.CONFIG_FILE = Path(td) / "remote_config.json"
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
        finally:
            client_mod.CONFIG_FILE = orig_config_file

    def test_sse_dns_rebinding_protection_off(self):
        """Reverse-proxy Host headers must reach SSE; do not pin a personal domain."""
        from agents_memory.remote.server import mcp

        create_remote_app(token="testtoken")
        settings = getattr(mcp.settings, "transport_security", None)
        self.assertIsNotNone(settings)
        self.assertFalse(settings.enable_dns_rebinding_protection)

    def test_server_delete_file_endpoint(self):
        app = create_remote_app(token="testtoken")
        client = TestClient(app)
        headers = {"Authorization": "Bearer testtoken"}

        # Create file in server store
        test_file = self.tmp_path / "obsolete.md"
        test_file.write_text("# Delete me\n", encoding="utf-8")
        self.assertTrue(test_file.is_file())

        # Unauthenticated -> 401
        resp = client.delete("/api/v1/file?path=obsolete.md")
        self.assertEqual(resp.status_code, 401)

        # Authenticated -> 200
        resp = client.delete("/api/v1/file?path=obsolete.md", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["deleted"], "obsolete.md")
        self.assertTrue(data["existed"])
        self.assertFalse(test_file.is_file())

        # Tombstone recorded
        tombstones = get_server_tombstones()
        self.assertIn("obsolete.md", tombstones)

    def test_server_merge_deletions(self):
        app = create_remote_app(token="testtoken")
        client = TestClient(app)
        headers = {"Authorization": "Bearer testtoken"}

        # Create file in server store
        victim = self.tmp_path / "victim.md"
        victim.write_text("# Victim\n", encoding="utf-8")
        self.assertTrue(victim.is_file())

        # Merge with deleted array
        merge_payload = {
            "files": {
                "alive.md": "# Alive\n"
            },
            "deleted": ["victim.md"]
        }
        resp = client.post("/api/v1/merge", json=merge_payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        res = resp.json()
        self.assertIn("victim.md", res.get("report", {}).get("deleted", []))
        self.assertFalse(victim.is_file())
        self.assertTrue((self.tmp_path / "alive.md").is_file())

        # Snapshot includes tombstone
        snap_resp = client.get("/api/v1/snapshot", headers=headers)
        self.assertEqual(snap_resp.status_code, 200)
        snap_data = snap_resp.json()
        self.assertIn("victim.md", snap_data.get("deleted", []))

    def test_client_deletion_tracking(self):
        from agents_memory.store import (
            record_local_deletion,
            load_local_deletions,
            clear_acknowledged_deletions,
        )

        record_local_deletion("notes/old.md")
        record_local_deletion("concepts/removed.md")
        deletions = load_local_deletions()
        self.assertEqual(deletions, ["notes/old.md", "concepts/removed.md"])

        # Duplicate should be ignored
        record_local_deletion("notes/old.md")
        self.assertEqual(load_local_deletions(), ["notes/old.md", "concepts/removed.md"])

        # Acknowledge one
        clear_acknowledged_deletions(["notes/old.md"])
        self.assertEqual(load_local_deletions(), ["concepts/removed.md"])

        # Acknowledge remaining
        clear_acknowledged_deletions(["concepts/removed.md"])
        self.assertEqual(load_local_deletions(), [])


if __name__ == "__main__":
    unittest.main()
