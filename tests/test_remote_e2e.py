"""End-to-end integration tests for remote cloud sync server and client workflows."""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn

import agents_memory.remote.client as client_mod
import agents_memory.remote.server as server_mod
from agents_memory.remote.client import (
    clear_remote_config,
    get_remote_config,
    remote_health_check,
    remote_pull,
    remote_push_merge,
    save_remote_config,
)
from agents_memory.remote.server import create_remote_app
from agents_memory.store import mcp_entry


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestRemoteE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server_tmp = tempfile.TemporaryDirectory()
        cls.server_dir = Path(cls.server_tmp.name)
        cls.token = "e2e_secret_token_456"
        cls.port = find_free_port()

        # Patch server store dir to server_dir
        cls.server_patch = patch.object(server_mod, "USER_MEMORY", cls.server_dir)
        cls.server_patch.start()

        # Initialize mock server files
        (cls.server_dir / "facts.md").write_text("# Master Facts\n- VPS is live\n", encoding="utf-8")

        app = create_remote_app(token=cls.token)
        config = uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="error")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()

        # Wait for server to listen
        url = f"http://127.0.0.1:{cls.port}/health"
        headers = {"Authorization": f"Bearer {cls.token}"}
        for _ in range(50):
            try:
                r = httpx.get(url, headers=headers, timeout=0.2)
                if r.status_code == 200:
                    break
            except Exception:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.server_patch.stop()
        cls.server_tmp.cleanup()

    def setUp(self):
        self.client_tmp = tempfile.TemporaryDirectory()
        self.client_dir = Path(self.client_tmp.name)
        self.patchers = [
            patch.object(client_mod, "USER_MEMORY", self.client_dir),
            patch.object(client_mod, "CONFIG_FILE", self.client_dir / "remote_config.json"),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.client_tmp.cleanup()

    def test_e2e_health_and_auth(self):
        base_url = f"http://127.0.0.1:{self.port}"
        # Valid auth
        health = remote_health_check(base_url, token=self.token)
        self.assertEqual(health["status"], "ok")
        self.assertGreaterEqual(health["files_count"], 1)

        # Invalid auth
        with self.assertRaises(PermissionError):
            remote_health_check(base_url, token="badtoken")

    def test_e2e_push_merge_and_pull(self):
        base_url = f"http://127.0.0.1:{self.port}"

        # Client has local facts
        (self.client_dir / "facts.md").write_text("# Master Facts\n- Local Laptop Fact\n", encoding="utf-8")
        (self.client_dir / "USER.md").write_text("# User Profile\n- Name: Felix\n", encoding="utf-8")

        # Push & merge into server
        push_res = remote_push_merge(base_url, token=self.token, source_dir=self.client_dir)
        self.assertEqual(push_res["status"], "ok")

        # Verify server now has merged facts
        server_facts = (self.server_dir / "facts.md").read_text(encoding="utf-8")
        self.assertIn("- VPS is live", server_facts)
        self.assertIn("- Local Laptop Fact", server_facts)

        # Save remote config
        save_remote_config(url=base_url, token=self.token)
        cfg = get_remote_config()
        self.assertIsNotNone(cfg)

        # Test mcp_entry uses remote bridge
        entry = mcp_entry()
        self.assertIn("remote", entry["args"])
        self.assertIn("client", entry["args"])

        # Disconnect restores local mode
        clear_remote_config()
        entry_local = mcp_entry()
        self.assertEqual(entry_local["args"], ["-m", "agents_memory.mcp_server"])


if __name__ == "__main__":
    unittest.main()
