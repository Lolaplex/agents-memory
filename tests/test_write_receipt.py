"""Verified write receipts for add/write, including failed and mismatched writes."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents_memory import mcp_server, store
from agents_memory.receipt import (
    RECEIPT_FIELDS,
    RECEIPT_SCHEMA,
    MemoryReceipt,
    MemoryWriteVerificationError,
)

ROOT = Path(__file__).resolve().parents[1]
FACT = "Rank-4 kernel survives a read-back check"


class _VaultCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.repo = self.root / "repo"
        self.rules = self.root / "rules"
        self.user.mkdir()
        self.repo.mkdir()
        self.rules.mkdir()
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n"
            f"| demo | `{self.repo}` | test | py | active |\n",
            encoding="utf-8",
        )
        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "PROJECTS_MD", self.projects_md),
            patch.object(store, "ORPHANS", self.user / "orphans"),
            patch.object(store, "AGENTS_RULES", self.rules),
            patch.object(store, "USER_MD", self.user / "USER.md"),
            patch.object(store, "sync_injection", lambda **_k: ([], [])),
            patch("agents_memory.receipt.utc_now_iso", return_value="2026-11-05T17:22:00Z"),
        ]
        for item in self.patches:
            item.start()
        store.clear_memory_cache()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def _assert_receipt(self, receipt: MemoryReceipt, path: Path, memory_id: str) -> None:
        raw = path.read_bytes()
        self.assertIsInstance(receipt, MemoryReceipt)
        self.assertIsInstance(receipt, str)
        self.assertEqual(receipt, memory_id)
        self.assertEqual(receipt.id, memory_id)
        self.assertEqual(receipt.path, memory_id)
        self.assertEqual(receipt.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt.bytes, len(raw))
        self.assertEqual(receipt.bytes, path.stat().st_size)
        self.assertEqual(receipt.written_at, "2026-11-05T17:22:00Z")
        self.assertIs(receipt.verified, True)
        payload = receipt.as_dict()
        self.assertEqual(tuple(payload), RECEIPT_FIELDS)
        self.assertEqual(payload["schema"], RECEIPT_SCHEMA)
        self.assertEqual(payload["sha256"], receipt.sha256)
        self.assertEqual(payload["bytes"], len(raw))
        self.assertIs(payload["verified"], True)
        self.assertIn(FACT.split()[0], path.read_text(encoding="utf-8"))


class WriteReceiptTests(_VaultCase):
    def test_add_memory_receipt_matches_persisted_bytes(self) -> None:
        receipt = store.add_memory(FACT, kind="concept", name="isar", auto_sync=False)
        path = self.user / "concepts" / "isar.md"
        self._assert_receipt(receipt, path, "user/concepts/isar.md")
        self.assertIn("isar.md", receipt)

    def test_project_add_uses_stable_project_id(self) -> None:
        receipt = store.add_memory(FACT, project="demo", auto_sync=False)
        path = self.repo / ".agents" / "memory" / "facts.md"
        self._assert_receipt(receipt, path, "project/demo/facts.md")

    def test_write_memory_file_receipt_matches_persisted_bytes(self) -> None:
        body = f"# Note\n\n- {FACT}\n"
        receipt = store.write_memory_file("user/notes/kernel.md", body, auto_sync=False)
        path = self.user / "notes" / "kernel.md"
        self._assert_receipt(receipt, path, "user/notes/kernel.md")
        self.assertEqual(path.read_text(encoding="utf-8"), body)

    def test_append_update_receipt_covers_the_full_file(self) -> None:
        first = store.add_memory(FACT, kind="concept", name="isar", auto_sync=False)
        second = store.add_memory(
            "second durable fact for the same file",
            kind="concept",
            name="isar",
            auto_sync=False,
        )
        path = self.user / "concepts" / "isar.md"
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        self.assertIn(FACT, text)
        self.assertIn("second durable fact", text)
        self.assertNotEqual(second.sha256, first.sha256)
        self.assertEqual(second.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(second.bytes, len(raw))
        self.assertEqual(second, "user/concepts/isar.md")

    def test_overwrite_update_receipt_matches_new_bytes(self) -> None:
        original = f"# Note\n\n- {FACT}\n"
        first = store.write_memory_file("user/notes/kernel.md", original, auto_sync=False)
        updated = "# Note\n\n- replaced fact that must be the only body\n"
        second = store.write_memory_file("user/notes/kernel.md", updated, auto_sync=False)
        path = self.user / "notes" / "kernel.md"
        raw = path.read_bytes()
        self.assertEqual(path.read_text(encoding="utf-8"), updated)
        self.assertNotEqual(second.sha256, first.sha256)
        self.assertEqual(second.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(second.bytes, len(raw))
        self.assertNotIn(FACT, path.read_text(encoding="utf-8"))

    def test_duplicate_add_receipts_the_existing_file(self) -> None:
        first = store.add_memory(FACT, kind="entity", name="lars", auto_sync=False)
        second = store.add_memory(FACT, kind="entity", name="lars", auto_sync=False)
        path = self.user / "entities" / "lars.md"
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(FACT), 1)
        self.assertEqual(second.sha256, first.sha256)
        self.assertEqual(second.sha256, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_partial_write_is_an_error(self) -> None:
        real_write = store._write

        def partial(path: Path, content: str) -> None:
            real_write(path, content)
            raw = path.read_bytes()
            self.assertGreater(len(raw), 8)
            path.write_bytes(raw[:8])

        with patch.object(store, "_write", partial):
            with self.assertRaises(MemoryWriteVerificationError) as ctx:
                store.add_memory(FACT, kind="concept", name="partial", auto_sync=False)
        self.assertEqual(ctx.exception.reason, "partial_write")
        self.assertEqual(ctx.exception.memory_id, "user/concepts/partial.md")
        self.assertIn("partial_write", str(ctx.exception))
        self.assertNotIn("Saved", str(ctx.exception))

    def test_missing_file_after_write_is_an_error(self) -> None:
        real_write = store._write

        def drop(path: Path, content: str) -> None:
            real_write(path, content)
            path.unlink()

        with patch.object(store, "_write", drop):
            with self.assertRaises(MemoryWriteVerificationError) as ctx:
                store.write_memory_file("user/notes/gone.md", f"- {FACT}\n", auto_sync=False)
        self.assertEqual(ctx.exception.reason, "missing")
        self.assertFalse((self.user / "notes" / "gone.md").exists())

    def test_writer_oserror_is_an_error(self) -> None:
        def boom(path: Path, content: str) -> None:
            raise OSError("disk full")

        with patch.object(store, "_write", boom):
            with self.assertRaises(OSError):
                store.add_memory(FACT, kind="concept", name="full", auto_sync=False)
        self.assertFalse((self.user / "concepts" / "full.md").exists())

    def test_readback_mismatch_is_an_error(self) -> None:
        def lie(path: Path) -> bytes:
            _ = path
            return b"this is not the document that was requested\n"

        with patch("agents_memory.receipt.read_persisted_bytes", lie):
            with self.assertRaises(MemoryWriteVerificationError) as ctx:
                store.write_memory_file(
                    "user/notes/mismatch.md",
                    f"# Note\n\n- {FACT}\n",
                    auto_sync=False,
                )
        self.assertEqual(ctx.exception.reason, "readback_mismatch")
        self.assertNotIn("Saved", str(ctx.exception))
        # The successful writer did land the real bytes; the receipt still refused them
        # because the read-back did not match.
        self.assertIn(FACT, (self.user / "notes" / "mismatch.md").read_text(encoding="utf-8"))


class MCPReceiptTests(_VaultCase):
    def _payload(self, text: str) -> dict:
        lines = [line for line in text.splitlines() if line.startswith("{")]
        self.assertEqual(len(lines), 1, text)
        return json.loads(lines[0])

    def test_add_and_write_keep_legacy_text_and_receipt(self) -> None:
        added = mcp_server.add_memory(FACT, kind="concept", name="indexing")
        self.assertTrue(added.startswith("Saved to user/concepts/indexing.md\n"))
        self.assertIn("Saved to user/concepts/indexing.md", added)
        payload = self._payload(added)
        path = self.user / "concepts" / "indexing.md"
        raw = path.read_bytes()
        self.assertEqual(payload["message"], "Saved to user/concepts/indexing.md")
        self.assertEqual(payload["id"], "user/concepts/indexing.md")
        self.assertEqual(payload["path"], payload["id"])
        self.assertEqual(payload["schema"], RECEIPT_SCHEMA)
        self.assertEqual(payload["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(payload["bytes"], len(raw))
        self.assertEqual(payload["written_at"], "2026-11-05T17:22:00Z")
        self.assertIs(payload["verified"], True)

        body = f"# Note\n\n- {FACT}\n"
        written = mcp_server.write_memory_file("user/notes/indexing.md", body)
        self.assertTrue(written.startswith("Saved and synced user/notes/indexing.md\n"))
        written_payload = self._payload(written)
        note = self.user / "notes" / "indexing.md"
        self.assertEqual(written_payload["message"], "Saved and synced user/notes/indexing.md")
        self.assertEqual(
            written_payload["sha256"],
            hashlib.sha256(note.read_bytes()).hexdigest(),
        )
        self.assertEqual(note.read_text(encoding="utf-8"), body)

    def test_failed_partial_and_mismatch_are_not_success(self) -> None:
        real_write = store._write

        def partial(path: Path, content: str) -> None:
            real_write(path, content)
            path.write_bytes(path.read_bytes()[:8])

        with patch.object(store, "_write", partial):
            partial_res = mcp_server.add_memory(FACT, kind="concept", name="partial")
        self.assertTrue(partial_res.startswith("Error saving memory:"))
        self.assertIn("partial_write", partial_res)
        self.assertNotIn("Saved to", partial_res)
        self.assertNotIn('"verified":true', partial_res)

        def lie(path: Path) -> bytes:
            _ = path
            return b"read back something else entirely\n"

        with patch("agents_memory.receipt.read_persisted_bytes", lie):
            mismatch = mcp_server.write_memory_file("user/notes/bad.md", f"- {FACT}\n")
        self.assertTrue(mismatch.startswith("Error writing memory file"))
        self.assertIn("readback_mismatch", mismatch)
        self.assertNotIn("Saved and synced", mismatch)
        self.assertNotIn('"verified":true', mismatch)

        def boom(path: Path, content: str) -> None:
            raise OSError("disk full")

        with patch.object(store, "_write", boom):
            failed = mcp_server.add_memory(FACT, kind="concept", name="full")
        self.assertTrue(failed.startswith("Error saving memory:"))
        self.assertIn("disk full", failed)
        self.assertNotIn("Saved to", failed)
        self.assertNotIn('"verified":true', failed)


class CLIReceiptTests(unittest.TestCase):
    def test_cli_add_and_write_print_receipt(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        agents = root / "agents"
        (agents / "memory").mkdir(parents=True)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        env["AGENTS_HOME"] = str(agents)
        env["AGENTS_NO_UPDATE_CHECK"] = "1"
        env.pop("AGENTS_MEMORY_PATH", None)

        added = subprocess.run(
            [
                sys.executable,
                "-m",
                "agents_memory",
                "add",
                FACT,
                "--kind",
                "concept",
                "--name",
                "cli-fact",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertTrue(added.stdout.startswith("Saved to user/concepts/cli-fact.md\n"))
        payload = json.loads(added.stdout.splitlines()[-1])
        path = agents / "memory" / "concepts" / "cli-fact.md"
        raw = path.read_bytes()
        self.assertEqual(payload["id"], "user/concepts/cli-fact.md")
        self.assertEqual(payload["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(payload["bytes"], len(raw))
        self.assertIs(payload["verified"], True)
        self.assertIn(FACT, path.read_text(encoding="utf-8"))

        body = f"# Note\n\n- {FACT}\n"
        written = subprocess.run(
            [sys.executable, "-m", "agents_memory", "write", "user/notes/cli-note.md", body],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
        self.assertEqual(written.returncode, 0, written.stderr)
        self.assertIn("Wrote user/notes/cli-note.md", written.stdout)
        note_payload = json.loads([line for line in written.stdout.splitlines() if line.startswith("{")][-1])
        note = agents / "memory" / "notes" / "cli-note.md"
        self.assertEqual(note.read_text(encoding="utf-8"), body)
        self.assertEqual(note_payload["sha256"], hashlib.sha256(note.read_bytes()).hexdigest())
        self.assertEqual(note_payload["bytes"], note.stat().st_size)


if __name__ == "__main__":
    unittest.main()
