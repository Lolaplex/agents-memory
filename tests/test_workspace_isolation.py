"""Per-call workspace resolution: two workspaces in one process stay isolated."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents_memory import index, store
from agents_workspace import Host


def _ws_env(host: Path, ws_id: str) -> dict:
    with patch.dict(os.environ, {"AGENTS_HOST_DIR": str(host)}, clear=False):
        if not Host.from_env().workspace_exists(ws_id):
            Host.from_env().create(ws_id)
    return {
        "AGENTS_HOST_DIR": str(host),
        "AGENTS_WORKSPACE": ws_id,
    }


class WorkspaceIsolationTests(unittest.TestCase):
    """Memory paths must resolve per call, never frozen at import."""

    def test_two_workspaces_separate_memory_files(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        host = Path(tmp.name) / "host"
        host.mkdir(parents=True)

        with patch.dict(os.environ, _ws_env(host, "alpha"), clear=False):
            a_mem = store.USER_MEMORY
            store.add_memory("alpha body", kind="note", name="only-in-alpha")
            self.assertTrue(str(a_mem).endswith(os.path.join("workspaces", "alpha", "memory")))
            alpha_text = "".join(p.read_text(encoding="utf-8") for p in a_mem.rglob("*.md"))
            self.assertIn("alpha body", alpha_text)

        with patch.dict(os.environ, _ws_env(host, "beta"), clear=False):
            b_mem = store.USER_MEMORY
            self.assertTrue(str(b_mem).endswith(os.path.join("workspaces", "beta", "memory")))
            self.assertNotEqual(a_mem, b_mem)
            store.add_memory("beta body", kind="note", name="only-in-beta")
            beta_text = "".join(p.read_text(encoding="utf-8") for p in b_mem.rglob("*.md"))
            self.assertIn("beta body", beta_text)
            self.assertNotIn("alpha body", beta_text)

        # alpha content did not leak into beta
        self.assertIn("alpha body", alpha_text)
        self.assertNotIn("only-in-beta", alpha_text)

    def test_two_workspaces_separate_index_dbs(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        host = Path(tmp.name) / "host"
        host.mkdir(parents=True)

        with patch.dict(os.environ, _ws_env(host, "wa"), clear=False):
            store.add_memory("alpha index content", kind="note", name="idx-wa")
            index.rebuild_index()
            fts_a = index.FTS_DB
            self.assertTrue(fts_a.is_file())
            self.assertIn("wa", str(fts_a))

        with patch.dict(os.environ, _ws_env(host, "wb"), clear=False):
            store.add_memory("beta index content", kind="note", name="idx-wb")
            index.rebuild_index()
            fts_b = index.FTS_DB
            self.assertTrue(fts_b.is_file())
            self.assertIn("wb", str(fts_b))
            self.assertNotEqual(fts_a, fts_b)
            hits_b = index.search_hybrid("beta index content")
            self.assertTrue(hits_b)

        with patch.dict(os.environ, _ws_env(host, "wa"), clear=False):
            hits_a = index.search_hybrid("index content")
            self.assertTrue(hits_a)
            self.assertFalse(any("idx-wb" in h["id"] for h in hits_a))

    def test_workspace_change_rewrites_paths_without_reimport(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        host = Path(tmp.name) / "host"
        host.mkdir(parents=True)
        with patch.dict(os.environ, _ws_env(host, "one"), clear=False):
            first = store.USER_MEMORY
        with patch.dict(os.environ, _ws_env(host, "two"), clear=False):
            second = store.USER_MEMORY
        self.assertIn("one", str(first))
        self.assertIn("two", str(second))
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
