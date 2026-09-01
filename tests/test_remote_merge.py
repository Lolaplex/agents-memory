"""Tests for deterministic markdown merge engine."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents_memory.remote.merge import (
    merge_bullet_markdown,
    merge_table_markdown,
    merge_staging_markdown,
    merge_file_trees,
)


class TestRemoteMerge(unittest.TestCase):
    def test_merge_bullet_markdown_basic(self):
        base = """# Global Facts
- User is Felix
- Uses Windows 11
"""
        incoming = """# Global Facts
- User is Felix
- Prefers Python FastAPI
- Uses Windows 11
"""
        merged = merge_bullet_markdown(base, incoming)
        self.assertIn("- User is Felix", merged)
        self.assertIn("- Uses Windows 11", merged)
        self.assertIn("- Prefers Python FastAPI", merged)
        self.assertEqual(merged.count("User is Felix"), 1)
        self.assertEqual(merged.count("Windows 11"), 1)

    def test_merge_bullet_markdown_new_section(self):
        base = """# Global Facts
- Fact 1
"""
        incoming = """# Global Facts
- Fact 1

# New Rules
- Never use emojis
"""
        merged = merge_bullet_markdown(base, incoming)
        self.assertIn("# Global Facts", merged)
        self.assertIn("# New Rules", merged)
        self.assertIn("- Never use emojis", merged)

    def test_merge_table_markdown_projects(self):
        base = """# Projects (Compact)

| slug | role | stack | status |
| --- | --- | --- | --- |
| demo | test | py | active |
"""
        incoming = """# Projects (Compact)

| slug | role | stack | status |
| --- | --- | --- | --- |
| demo | test | py | active |
| web-app | client frontend | react/ts | dev |
"""
        merged = merge_table_markdown(base, incoming)
        self.assertIn("| demo | test | py | active |", merged)
        self.assertIn("| web-app | client frontend | react/ts | dev |", merged)
        self.assertEqual(merged.count("demo"), 1)
        self.assertEqual(merged.count("web-app"), 1)

    def test_merge_table_incoming_wins_on_edit(self):
        base = """| slug | path |\n| --- | --- |\n| demo | /old/path |\n"""
        incoming = """| slug | path |\n| --- | --- |\n| demo | /new/path |\n"""
        merged = merge_table_markdown(base, incoming)
        self.assertIn("/new/path", merged)
        self.assertNotIn("/old/path", merged)

    def test_merge_staging_markdown(self):
        base = """# Staging Inbox
## Session 1
- Initial raw thought 1
"""
        incoming = """# Staging Inbox
## Session 1
- Initial raw thought 1
- Thought 2 from device B
"""
        merged = merge_staging_markdown(base, incoming)
        self.assertIn("Initial raw thought 1", merged)
        self.assertIn("Thought 2 from device B", merged)
        self.assertEqual(merged.count("Initial raw thought 1"), 1)

    def test_merge_file_trees_tempdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "facts.md").write_text("# Facts\n- Fact 1\n", encoding="utf-8")

            incoming = {
                "facts.md": "# Facts\n- Fact 1\n- Fact 2\n",
                "projects/new_proj.md": "# Project New\nRole: Dev\n",
            }

            report = merge_file_trees(root, incoming)
            self.assertIn("projects/new_proj.md", report["added"])
            self.assertIn("facts.md", report["merged"])

            facts_content = (root / "facts.md").read_text(encoding="utf-8")
            self.assertIn("- Fact 1", facts_content)
            self.assertIn("- Fact 2", facts_content)

            new_proj_content = (root / "projects/new_proj.md").read_text(encoding="utf-8")
            self.assertIn("Role: Dev", new_proj_content)


class TestBoardAttachPaths(unittest.TestCase):
    def test_personal_files_rejected(self):
        from agents_memory.remote.client import board_memory_path_ok

        self.assertFalse(board_memory_path_ok("USER.md"))
        self.assertFalse(board_memory_path_ok("projects.md"))
        self.assertTrue(board_memory_path_ok("decisions/001-ftp-host.md"))
        self.assertTrue(board_memory_path_ok("staging/captured.md"))
        self.assertFalse(board_memory_path_ok("../decisions/001-x.md"))

    def test_unregistered_dest_is_opaque_url_id(self):
        from unittest.mock import patch
        from agents_memory.remote.client import attach_dest_from_url, unregistered_attach_dest

        url = "https://board.example/projects/alpha/memory"
        with patch("agents_memory.remote.client.find_project", return_value=None):
            dest = attach_dest_from_url(url)
            again = attach_dest_from_url(url + "/snapshot")
            other = attach_dest_from_url("https://board.example/projects/beta/memory")
        self.assertEqual(dest, again)
        self.assertEqual(dest, unregistered_attach_dest(url))
        self.assertNotEqual(dest, other)
        self.assertNotIn("alpha", dest.parts)
        self.assertIn("by-url", dest.parts)

    def test_registered_dest_is_clone_memory(self):
        from unittest.mock import patch
        from agents_memory.remote.client import attach_dest_from_url
        from agents_memory.store import Project

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / "clone"
        repo.mkdir()
        proj = Project("alpha", str(repo), "role", "py")
        with patch("agents_memory.remote.client.find_project", return_value=proj):
            dest = attach_dest_from_url("https://board.example/projects/alpha/memory")
            other_name = attach_dest_from_url(
                "https://board.example/projects/board-name/memory",
                project="alpha",
            )
        self.assertEqual(dest, (repo / ".agents" / "memory").resolve())
        self.assertEqual(other_name, dest)

    def test_unknown_explicit_project_raises(self):
        from unittest.mock import patch
        from agents_memory.remote.client import attach_dest_from_url

        with patch("agents_memory.remote.client.find_project", return_value=None):
            with self.assertRaises(ValueError):
                attach_dest_from_url(
                    "https://board.example/projects/alpha/memory",
                    project="missing",
                )

    def test_dest_must_not_be_personal_store(self):
        from agents_memory.remote.client import board_attach
        from agents_memory.store import USER_MEMORY

        with self.assertRaises(ValueError):
            board_attach(
                "https://board.example/projects/x/memory",
                dest_dir=USER_MEMORY,
            )
        with self.assertRaises(ValueError):
            board_attach(
                "https://board.example/projects/x/memory",
                dest_dir=USER_MEMORY / "nested",
            )

    def test_attach_requires_slug_or_token(self):
        from agents_memory.remote.client import board_attach

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dest = Path(tmp.name) / "out"
        with self.assertRaises(ValueError) as ctx:
            board_attach(
                "https://board.example/projects/x/memory",
                dest_dir=dest,
            )
        self.assertIn("--slug", str(ctx.exception))

    def test_did_attach_uses_session_cookie_not_bearer(self):
        import httpx
        from agents_memory.remote.client import board_attach

        did = "did:key:z6MktULudTtAsAhRegYPiZ6631RV3viv12qd4GQF8z1xB22S"
        signature = "ab" * 32
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        dest = root / "dest"
        user = root / "user"
        user.mkdir()
        nonce = "board-login:test-nonce"
        seen = {"cookie": False, "bearer": False}

        def fake_keys(*args: str) -> str:
            if args[:1] == ("did",):
                return did
            if args[:1] == ("sign",):
                self.assertEqual(args[2], nonce)
                return signature
            raise AssertionError(args)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/login":
                payload = json.loads(request.content)
                if payload.get("verb") == "challenge":
                    self.assertEqual(payload.get("did"), did)
                    return httpx.Response(200, json={"nonce": nonce, "did": did})
                if payload.get("verb") == "verify":
                    self.assertEqual(payload.get("signature"), signature)
                    return httpx.Response(
                        200,
                        json={"ok": True},
                        headers={"set-cookie": "board_sid=sess1; Path=/"},
                    )
                return httpx.Response(422, json={"error": "bad verb"})
            if request.url.path.endswith("/snapshot"):
                if request.headers.get("authorization"):
                    seen["bearer"] = True
                if "board_sid=sess1" in (request.headers.get("cookie") or ""):
                    seen["cookie"] = True
                return httpx.Response(
                    200,
                    json={"files": {"decisions/001-hello.md": "# Hello\n"}},
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)

        with patch("agents_memory.remote.client.keys_cli", side_effect=fake_keys):
            with patch("agents_memory.remote.client.USER_MEMORY", user):
                with patch(
                    "agents_memory.remote.client.ATTACH_FILE",
                    user / "board_attach.json",
                ):
                    with patch("agents_memory.remote.client.ensure_memory_layout"):
                        with patch(
                            "agents_memory.remote.client._get_http_client",
                            lambda **_k: httpx.Client(transport=transport),
                        ):
                            res = board_attach(
                                "https://board.example/projects/alpha/memory",
                                slug="shcpy",
                                dest_dir=dest,
                            )
        self.assertTrue(seen["cookie"], "snapshot must send board_sid")
        self.assertFalse(seen["bearer"])
        self.assertEqual(res["did"], did)
        self.assertTrue((dest / "decisions" / "001-hello.md").is_file())
        sidecar = json.loads((user / "board_attach.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["attaches"][0]["slug"], "shcpy")
        self.assertNotIn("token", sidecar["attaches"][0])


if __name__ == "__main__":
    unittest.main()
