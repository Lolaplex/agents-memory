import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents_memory import check, frontmatter, store


class EnvPathTests(unittest.TestCase):
    def test_env_path_overrides_default(self):
        raw = Path(tempfile.mkdtemp())
        default = Path.home() / ".agents" / "memory"
        with patch.dict(os.environ, {"AGENTS_MEMORY_PATH": ""}, clear=False):
            self.assertEqual(store._env_path("AGENTS_MEMORY_PATH", default), default)
        with patch.dict(os.environ, {"AGENTS_MEMORY_PATH": str(raw)}):
            self.assertEqual(
                store._env_path("AGENTS_MEMORY_PATH", default), raw.resolve()
            )


class FrontmatterSchemaTests(unittest.TestCase):
    def test_body_only_is_clean(self):
        self.assertEqual(frontmatter.lint_frontmatter_text("# Hello\n\nNo fence.\n"), [])

    def test_unclosed_fence(self):
        issues = frontmatter.lint_frontmatter_text("---\nrefs:\n  - user/USER.md\n")
        self.assertEqual(issues, ["unclosed frontmatter fence"])

    def test_unknown_key_rejected(self):
        text = "---\nump: '1.0'\nrefs:\n  - user/USER.md\n---\n\n# X\n"
        issues = frontmatter.lint_frontmatter_text(text)
        self.assertTrue(any("unknown keys" in i and "ump" in i for i in issues))

    def test_id_key_allowed(self):
        text = "---\nid: agent-transcripts\nkind: agent-jsonl\nrole: chat-source\n---\n\n# X\n"
        self.assertEqual(frontmatter.lint_frontmatter_text(text), [])
        text = (
            "---\nslug: demo\npath: C:/tmp\nrole: test\nstack: py\nstatus: active\n---\n\n# demo\n"
        )
        self.assertEqual(frontmatter.lint_frontmatter_text(text), [])

    def test_bad_provenance(self):
        text = "---\nprovenance: vendor\n---\n\n# X\n"
        issues = frontmatter.lint_frontmatter_text(text)
        self.assertTrue(any("provenance" in i for i in issues))

    def test_near_duplicate_stems(self):
        root = Path(tempfile.mkdtemp())
        a = root / "eori.md"
        b = root / "eori-number.md"
        a.write_text("a", encoding="utf-8")
        b.write_text("b", encoding="utf-8")
        pairs = frontmatter.near_duplicate_stems([a, b])
        self.assertEqual(len(pairs), 1)


class CheckRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.user = Path(self.tmp.name) / "user"
        self.user.mkdir()
        (self.user / "concepts").mkdir()
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n| slug | path | role | stack | status |\n"
            "|---|---|---|---|---|\n",
            encoding="utf-8",
        )
        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "PROJECTS_MD", self.projects_md),
            patch.object(store, "parse_projects", lambda: []),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_frontmatter_schema_named_id(self):
        (self.user / "USER.md").write_text("# Agent profile\n\nName: test.\n", encoding="utf-8")
        (self.user / "concepts" / "ump-shaped.md").write_text(
            "---\nintegrity: ed25519:nope\nrefs:\n  - user/USER.md\n---\n\n# Bad\n\nBody.\n",
            encoding="utf-8",
        )
        schema = check.check_frontmatter_schema()
        self.assertFalse(schema["ok"])
        self.assertEqual(schema["check"], "frontmatter-schema")
        self.assertTrue(any("unknown keys" in f and "integrity" in f for f in schema["files"]))

    def test_dangling_refs_named_id(self):
        (self.user / "USER.md").write_text("# Agent profile\n\nName: test.\n", encoding="utf-8")
        (self.user / "concepts" / "ok.md").write_text(
            "---\nrefs:\n  - user/notes/missing.md\nprovenance: human\n---\n\n# Ok\n\nEnough body text here.\n",
            encoding="utf-8",
        )
        dangling = check.check_dangling_refs()
        self.assertFalse(dangling["ok"])
        self.assertEqual(dangling["check"], "dangling-refs")
        self.assertTrue(any("user/notes/missing.md" in f for f in dangling["files"]))

    def test_near_duplicate_slugs_named_id(self):
        (self.user / "concepts" / "ok.md").write_text(
            "# Ok\n\nEnough body text here for the stub check.\n",
            encoding="utf-8",
        )
        near = check.check_near_duplicate_slugs()
        self.assertTrue(near["ok"])
        self.assertEqual(near["check"], "near-duplicate-slugs")

    def test_run_all_json_ids(self):
        (self.user / "concepts" / "note.md").write_text(
            "# Note\n\nLong enough body for stub check to pass here.\n",
            encoding="utf-8",
        )
        ids = [r["check"] for r in [
            check.check_staging(),
            check.check_duplicates(),
            check.check_near_duplicate_slugs(),
            check.check_stubs(),
            check.check_index_stale(),
            check.check_frontmatter_schema(),
            check.check_dangling_refs(),
        ]]
        self.assertEqual(
            ids,
            [
                "staging-leftovers",
                "duplicate-notes",
                "near-duplicate-slugs",
                "stub-notes",
                "index-stale",
                "frontmatter-schema",
                "dangling-refs",
            ],
        )


if __name__ == "__main__":
    unittest.main()
