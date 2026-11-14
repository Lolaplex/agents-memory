"""Write-time secret redaction. Secrets must not reach the store."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents_memory import mcp_server, rules, store
from agents_memory.ingest_common import scrub, write_staging
from agents_memory.receipt import RECEIPT_FIELDS
from agents_memory.redact import (
    MAX_EXTRA_INPUT,
    REDACTED,
    annotate_success,
    clear_redact_cache,
    redact_secrets,
    redaction_notice,
)

ROOT = Path(__file__).resolve().parents[1]

OPENAI = "sk-1234567890abcdef1234567890"
OPENAI_SHORT = "sk-1234567890"
OPENAI_LETTERS = "sk-abcdefghijklmnopqrstuvwxyz"
ANTHROPIC = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
GITHUB = "ghp_123456789012345678901234567890"
GITHUB_LETTERS = "ghp_" + ("a" * 36)
GITHUB_PAT = "github_pat_" + ("1a" * 16)
RESEND = "re_12345678901234567890"
NETLIFY = "nfp_12345678901234567890"
GOOGLE = "AIzaSyD-1234567890123456789012345678901"
AWS = "AKIAIOSFODNN7EXAMPLE"
JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ"
    ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)
STRIPE = "sk_live_" + ("a1" * 12)
NPM = "npm_" + ("a1" * 18)
HF = "hf_" + ("a1" * 17)
SENDGRID = "SG." + ("a" * 22) + "." + ("b" * 43)
PYPI = "pypi-AgEIcHlwaS5vcmc" + ("a1" * 12)
GITLAB = "glpat-" + ("a1" * 10)
SLACK = "xoxb-123456789012-123456789012-abcdefghijklmnopqrstuvwx"
GROQ = "gsk_" + ("a1" * 12)
ASSIGN = "abcd1234EFGH5678"
PEM = (
    "-----BEGIN PRIVATE KEY-----\n"
    "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7exampleKeyMat\n"
    "-----END PRIVATE KEY-----\n"
)
VENDOR_SECRETS = (
    OPENAI,
    OPENAI_SHORT,
    OPENAI_LETTERS,
    ANTHROPIC,
    GITHUB,
    GITHUB_LETTERS,
    GITHUB_PAT,
    RESEND,
    NETLIFY,
    GOOGLE,
    AWS,
    JWT,
    STRIPE,
    NPM,
    HF,
    SENDGRID,
    PYPI,
    GITLAB,
    SLACK,
    GROQ,
)

BENIGN = """# Notes

Prefer token-based auth. Password managers are part of the stack.
The token budget is 2000 characters.
kind=note name=preferences collection=preferences
stack: typescript, python
Authorization model is role-based for this service.
Bearer instrument of record.
sk-implementation is a documentation stem, not a credential.
See the ghp_ prefix in GitHub's docs before rotating keys.
fragments plus app.css tokens only.
https://example.com/docs/api-reference
user/notes/programming/chat-stores.md:3#a1b2c3d4
sha256 a1b2c3d4e5f6789012345678901234567890abcd
password=changeme
password: required
password: policy
token: preferences
token: none
API_KEY=${API_KEY}
API_KEY=$API_KEY
password: ****
password: <secret>
token=1.3.0
export const token = "short"
password: https://example.com/reset
Rank-4 kernel survives a read-back check

-----BEGIN PRIVATE KEY-----
(not key material)
-----END PRIVATE KEY-----
"""


def _absent(blob: str, secret: str) -> None:
    if secret and secret in blob:
        raise AssertionError(f"secret leaked: {secret[:8]}… ({len(secret)} chars)")


class RedactUnitTests(unittest.TestCase):
    def test_vendor_tokens_are_replaced(self) -> None:
        for secret in VENDOR_SECRETS:
            out = redact_secrets(f"prefix {secret} suffix", use_config=False)
            self.assertNotIn(secret, out.text, secret[:12])
            self.assertIn(REDACTED, out.text)
            self.assertGreaterEqual(out.count, 1)
            self.assertTrue(out.text.startswith("prefix "))
            self.assertTrue(out.text.endswith(" suffix"))

    def test_headers_assignments_userinfo_and_pem(self) -> None:
        cases = [
            f"API_KEY={ASSIGN}",
            f'password="{ASSIGN}"',
            '{"api_key": "' + ASSIGN + '"}',
            f"?access_token={ASSIGN}&x=1",
            f"export SECRET={ASSIGN}",
            "password: supersecret",
            "password: hunter2",
            "password: 123456",
            f"client_secret={ASSIGN}",
            f"Authorization: Bearer {JWT}",
            "Authorization: Basic dXNlcjpzM2NyZXQh",
            f"Proxy-Authorization: Bearer {GITHUB}",
            "https://deploy:s3cret-token@example.com/repo.git",
            f"keep\n{PEM}tail",
        ]
        needles = (ASSIGN, "supersecret", "hunter2", "s3cret-token", "dXNlcjpzM2NyZXQh", JWT, GITHUB, "exampleKeyMat")
        for text in cases:
            out = redact_secrets(text, use_config=False)
            for needle in needles:
                if needle in text:
                    self.assertNotIn(needle, out.text, text[:40])
            self.assertIn(REDACTED, out.text)

    def test_benign_text_is_unchanged(self) -> None:
        out = redact_secrets(BENIGN, use_config=False)
        self.assertEqual(out.text, BENIGN)
        self.assertEqual(out.count, 0)
        self.assertEqual(redact_secrets(out.text, use_config=False).count, 0)

    def test_markdown_around_a_secret_stays(self) -> None:
        body = f"# Title\n\n- Keep this fact.\n\n```\nAPI_KEY={ASSIGN}\n```\n\n{PEM}\n- Tail stays.\n"
        out = redact_secrets(body, use_config=False)
        self.assertIn("# Title", out.text)
        self.assertIn("- Keep this fact.", out.text)
        self.assertIn("- Tail stays.", out.text)
        self.assertIn("```", out.text)
        self.assertIn("API_KEY=[redacted]", out.text)
        self.assertNotIn(ASSIGN, out.text)
        self.assertNotIn("exampleKeyMat", out.text)
        self.assertGreater(out.text.count("\n"), 4)
        again = redact_secrets(out.text, use_config=False)
        self.assertEqual(again.text, out.text)
        self.assertEqual(again.count, 0)

    def test_two_secrets_count_separately(self) -> None:
        text = f"API_KEY={ASSIGN} and {GITHUB}"
        out = redact_secrets(text, use_config=False)
        self.assertGreaterEqual(out.count, 2)
        self.assertNotIn(ASSIGN, out.text)
        self.assertNotIn(GITHUB, out.text)

    def test_notice_is_empty_when_clean(self) -> None:
        self.assertEqual(redaction_notice(0), "")
        self.assertEqual(annotate_success("Saved to user/a.md", 0), "Saved to user/a.md")
        self.assertEqual(
            annotate_success("Saved to user/a.md", 1),
            "Saved to user/a.md (1 secret replaced with [redacted])",
        )
        self.assertEqual(
            annotate_success("Wrote user/a.md", 2),
            "Wrote user/a.md (2 secrets replaced with [redacted])",
        )

    def test_scrub_still_drops_email_and_token(self) -> None:
        text = f"mail me at person@example.com key {OPENAI}"
        cleaned = scrub(text)
        self.assertNotIn(OPENAI, cleaned)
        self.assertNotIn("person@example.com", cleaned)
        self.assertIn(REDACTED, cleaned)

    def test_near_miss_token_prefix_survives_scrub(self) -> None:
        cleaned = scrub("sk-implementation is a documentation stem")
        self.assertIn("sk-implementation", cleaned)

    def test_extra_pattern_and_rejected_patterns(self) -> None:
        secret = "corp_Abcd1234Wxyz"
        out = redact_secrets(
            f"shipped {secret} today",
            extra_patterns=[r"corp_[A-Za-z0-9]{12}"],
            use_config=False,
        )
        self.assertNotIn(secret, out.text)
        self.assertIn(REDACTED, out.text)

        stderr = StringIO()
        with patch("sys.stderr", stderr):
            clear_redact_cache()
            kept = redact_secrets(
                "Rank-4 kernel survives a read-back check",
                extra_patterns=["(unclosed", "kernel", "ab", r"corp_[A-Za-z0-9]{12}"],
                use_config=False,
            )
        self.assertEqual(kept.text, "Rank-4 kernel survives a read-back check")
        notes = stderr.getvalue()
        self.assertIn("does not compile", notes)
        self.assertIn("matches ordinary prose", notes)
        self.assertIn("shorter than 4 characters", notes)
        self.assertNotIn("(unclosed", notes)
        self.assertNotIn("kernel", notes)

    def test_catastrophic_extra_pattern_is_rejected(self) -> None:
        text = "a" * 24
        stderr = StringIO()
        started = time.perf_counter()
        with patch("sys.stderr", stderr):
            out = redact_secrets(text, extra_patterns=["(a+)+$"], use_config=False)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.25)
        self.assertEqual(out.text, text)
        self.assertEqual(out.count, 0)
        self.assertIn("nested quantifiers", stderr.getvalue())
        self.assertNotIn("(a+)+", stderr.getvalue())

        stderr = StringIO()
        with patch("sys.stderr", stderr):
            ambiguous = redact_secrets("a" * 24, extra_patterns=["(a|aa)+"], use_config=False)
        self.assertEqual(ambiguous.text, "a" * 24)
        self.assertIn("ambiguous quantifiers", stderr.getvalue())

    def test_extra_patterns_skip_oversized_input(self) -> None:
        secret = "corp_Abcd1234Wxyz"
        short = redact_secrets(
            f"shipped {secret} today",
            extra_patterns=[r"corp_[A-Za-z0-9]{12}"],
            use_config=False,
        )
        self.assertNotIn(secret, short.text)
        huge = f"shipped {secret} today " + ("x" * MAX_EXTRA_INPUT)
        stderr = StringIO()
        with patch("sys.stderr", stderr):
            kept = redact_secrets(
                huge,
                extra_patterns=[r"corp_[A-Za-z0-9]{12}"],
                use_config=False,
            )
        self.assertIn(secret, kept.text)
        self.assertEqual(kept.count, 0)
        self.assertIn("longer than", stderr.getvalue())

    def test_sync_module_does_not_redact(self) -> None:
        source = (ROOT / "src" / "agents_memory" / "sync.py").read_text(encoding="utf-8")
        self.assertNotIn("redact", source)


class _Vault(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.repo = self.root / "repo"
        self.rules_dir = self.root / "rules"
        self.user.mkdir()
        self.repo.mkdir()
        self.rules_dir.mkdir()
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n"
            f"| demo | `{self.repo}` | test | py | active |\n",
            encoding="utf-8",
        )
        self.env = patch.dict(
            os.environ,
            {"AGENTS_MEMORY_REDACT_PATTERNS": "", "AGENTS_MEMORY_REDACT_CONFIG": ""},
        )
        self.env.start()
        clear_redact_cache()
        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "PROJECTS_MD", self.projects_md),
            patch.object(store, "ORPHANS", self.user / "orphans"),
            patch.object(store, "AGENTS_RULES", self.rules_dir),
            patch.object(store, "USER_MD", self.user / "USER.md"),
            patch.object(store, "CHRONICLE_DIR", self.user / "events" / "chronicle"),
            patch.object(store, "HOST_PATHS_JSON", self.user / "host_paths.json"),
            patch.object(store, "sync_injection", lambda **_k: ([], [])),
            patch.object(store, "_finish_store_write", lambda: None),
        ]
        for item in self.patches:
            item.start()
        store.clear_memory_cache()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.env.stop()
        clear_redact_cache()
        store.clear_memory_cache()
        self.tmp.cleanup()

    def assert_tree_clean(self, *secrets: str) -> None:
        blobs: list[str] = []
        for path in self.root.rglob("*"):
            if path.is_file():
                blobs.append(path.read_text(encoding="utf-8", errors="replace"))
        blob = "\n".join(blobs)
        for secret in secrets:
            self.assertNotIn(secret, blob)


class RedactStorageTests(_Vault):
    def test_write_memory_file_keeps_markdown_and_drops_secrets(self) -> None:
        body = f"# Title\n\n- Keep this fact.\n\n```\nAPI_KEY={ASSIGN}\n```\n\n{PEM}\n- Tail stays.\n"
        receipt = store.write_memory_file("user/notes/sealed.md", body, auto_sync=False)
        path = self.user / "notes" / "sealed.md"
        stored = path.read_text(encoding="utf-8")
        self.assertIn("# Title", stored)
        self.assertIn("- Keep this fact.", stored)
        self.assertIn("- Tail stays.", stored)
        self.assertIn("```", stored)
        self.assertNotIn(ASSIGN, stored)
        self.assertNotIn("exampleKeyMat", stored)
        self.assertIn(REDACTED, stored)
        self.assertGreaterEqual(receipt.secrets_redacted, 1)
        self.assertEqual(tuple(receipt.as_dict()), RECEIPT_FIELDS)
        self.assertEqual(receipt.sha256, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertNotEqual(receipt.sha256, hashlib.sha256(body.encode("utf-8")).hexdigest())
        self.assert_tree_clean(ASSIGN, "exampleKeyMat")

    def test_benign_write_is_byte_for_byte(self) -> None:
        receipt = store.write_memory_file("user/notes/benign.md", BENIGN, auto_sync=False)
        stored = (self.user / "notes" / "benign.md").read_text(encoding="utf-8")
        self.assertEqual(stored, BENIGN)
        self.assertEqual(receipt.secrets_redacted, 0)

    def test_add_memory_search_and_project_file(self) -> None:
        fact = f"kernel index marker {OPENAI} stays useful"
        receipt = store.add_memory(fact, kind="concept", name="sealed", auto_sync=False)
        self.assertGreaterEqual(receipt.secrets_redacted, 1)
        stored = (self.user / "concepts" / "sealed.md").read_text(encoding="utf-8")
        self.assertNotIn(OPENAI, stored)
        self.assertIn("kernel index marker", stored)
        self.assertIn(REDACTED, stored)
        hits = store.search_memory("kernel index marker")
        blob = " ".join(hit["text"] for hit in hits)
        self.assertNotIn(OPENAI, blob)
        self.assertIn(REDACTED, blob)
        self.assertEqual(store.search_memory(OPENAI), [])
        store.add_memory(f"project fact {GITHUB}", project="demo", auto_sync=False)
        project_file = self.repo / ".agents" / "memory" / "facts.md"
        self.assertNotIn(GITHUB, project_file.read_text(encoding="utf-8"))
        self.assert_tree_clean(OPENAI, GITHUB)

    def test_add_memory_keeps_documentation_stem(self) -> None:
        store.add_memory(
            "sk-implementation is a documentation stem",
            kind="note",
            name="stem",
            auto_sync=False,
        )
        stored = (self.user / "notes" / "scratch" / "stem.md").read_text(encoding="utf-8")
        self.assertIn("sk-implementation", stored)

    def test_distill_staging_rules_chronicle_and_projects(self) -> None:
        from agents_memory.ingest_common import append_staging_bullets

        write_staging("demo-source", "Demo", [f"captured {SLACK} from a chat"])
        staged = (self.user / "staging" / "ingest" / "demo-source" / "captured.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(SLACK, staged)
        self.assertIn(REDACTED, staged)
        append_staging_bullets("demo-source", "Demo", [f"later API_KEY={ASSIGN}"])
        staged = (self.user / "staging" / "ingest" / "demo-source" / "captured.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(ASSIGN, staged)

        store.distill_batch(
            [
                {
                    "bullet": f"durable fact {JWT}",
                    "kind": "note",
                    "name": "distilled",
                    "collection": "programming",
                }
            ],
            auto_sync=False,
        )
        distilled = (self.user / "notes" / "programming" / "distilled.md").read_text(encoding="utf-8")
        self.assertNotIn(JWT, distilled)

        def _boom(*_a, **_k):
            raise ValueError("nope")

        with patch.object(store, "add_memory", _boom):
            failed = store.distill_batch(
                [{"bullet": f"note {AWS} here", "kind": "note", "name": "x"}],
                auto_sync=False,
            )
        self.assertTrue(failed["errors"])
        self.assertNotIn(AWS, " ".join(failed["errors"]))

        rules.add_rule(f"Never log API_KEY={ASSIGN} in rules.", user_intent=True)
        rule_text = (self.rules_dir / "HARD.md").read_text(encoding="utf-8")
        self.assertNotIn(ASSIGN, rule_text)
        self.assertIn("API_KEY=[redacted]", rule_text)

        proposed = mcp_server.propose_rule(f"Never paste {GITHUB} into chat.")
        self.assertIn("1 secret replaced", proposed)
        self.assertNotIn(GITHUB, proposed)
        proposal_file = (self.user / "staging" / "rule-proposals.md").read_text(encoding="utf-8")
        self.assertNotIn(GITHUB, proposal_file)

        store.append_chronicle(f"shipped build {STRIPE}", project="")
        chronicle = list((self.user / "events" / "chronicle").rglob("*.md"))
        self.assertTrue(chronicle)
        self.assertNotIn(STRIPE, chronicle[0].read_text(encoding="utf-8"))

        store.set_baton(f"baton carries {HF}")
        baton = (self.user / "rituals" / "baton.md").read_text(encoding="utf-8")
        self.assertNotIn(HF, baton)

        store.write_projects(
            [
                store.Project(
                    slug="demo",
                    path=str(self.repo),
                    role="app",
                    stack=f"API_KEY={ASSIGN}",
                    status="active",
                )
            ]
        )
        table = self.projects_md.read_text(encoding="utf-8")
        self.assertNotIn(ASSIGN, table)
        self.assertIn(str(self.repo), table)
        self.assert_tree_clean(SLACK, ASSIGN, JWT, AWS, GITHUB, STRIPE, HF)

    def test_config_file_and_env_patterns(self) -> None:
        corp = "corp_Abcd1234Wxyz"
        acme = "acme_ZZ99secretKEY1"
        (self.user / "redact.json").write_text(
            json.dumps({"version": 1, "extra_patterns": [r"corp_[A-Za-z0-9]{12}"]}),
            encoding="utf-8",
        )
        clear_redact_cache()
        store.add_memory(f"widget {corp} shipped", kind="note", name="corp", auto_sync=False)
        stored = (self.user / "notes" / "scratch" / "corp.md").read_text(encoding="utf-8")
        self.assertNotIn(corp, stored)

        legacy = f"acme_[A-Za-z0-9]{{12,}};;{acme}"
        with patch.dict(os.environ, {"AGENTS_MEMORY_REDACT_PATTERNS": legacy}):
            clear_redact_cache()
            stderr = StringIO()
            with patch("sys.stderr", stderr):
                ignored = store.add_memory(
                    f"legacy {acme} stays",
                    kind="note",
                    name="legacy",
                    auto_sync=False,
                )
        self.assertIn("JSON array of strings", stderr.getvalue())
        self.assertEqual(ignored.secrets_redacted, 0)
        legacy_file = (self.user / "notes" / "scratch" / "legacy.md").read_text(encoding="utf-8")
        self.assertIn(acme, legacy_file)

        with patch.dict(
            os.environ,
            {"AGENTS_MEMORY_REDACT_PATTERNS": json.dumps([r"acme_[A-Za-z0-9]{12,}"])},
        ):
            clear_redact_cache()
            store.add_memory(f"other {acme} value", kind="note", name="acme", auto_sync=False)
        stored = (self.user / "notes" / "scratch" / "acme.md").read_text(encoding="utf-8")
        self.assertNotIn(acme, stored)
        self.assert_tree_clean(corp)

    def test_broad_config_pattern_does_not_eat_prose(self) -> None:
        (self.user / "redact.json").write_text(
            json.dumps({"version": 1, "extra_patterns": ["kernel", "(unclosed"]}),
            encoding="utf-8",
        )
        clear_redact_cache()
        stderr = StringIO()
        with patch("sys.stderr", stderr):
            clear_redact_cache()
            receipt = store.add_memory(
                "Rank-4 kernel survives a read-back check",
                kind="concept",
                name="isar",
                auto_sync=False,
            )
        stored = (self.user / "concepts" / "isar.md").read_text(encoding="utf-8")
        self.assertIn("Rank-4 kernel survives a read-back check", stored)
        self.assertEqual(receipt.secrets_redacted, 0)
        self.assertIn("matches ordinary prose", stderr.getvalue())
        self.assertIn("does not compile", stderr.getvalue())

    def test_mcp_add_and_write_hide_the_secret(self) -> None:
        added = mcp_server.add_memory(
            f"remember marker {NPM} please",
            kind="concept",
            name="mcp",
        )
        self.assertNotIn(NPM, added)
        self.assertIn("1 secret replaced with [redacted]", added)
        self.assertTrue(added.startswith("Saved to user/concepts/mcp.md"))
        payload = json.loads(added.splitlines()[-1])
        self.assertEqual(tuple(payload.keys()), ("bytes", "id", "message", "path", "schema", "sha256", "verified", "written_at"))
        self.assertNotIn(NPM, json.dumps(payload))
        written = mcp_server.write_memory_file(
            "user/notes/mcp.md",
            f"# Note\n\nAuthorization: Bearer {JWT}\n",
        )
        self.assertNotIn(JWT, written)
        self.assertIn("secret replaced with [redacted]", written)
        self.assert_tree_clean(NPM, JWT)


class RedactCLITests(unittest.TestCase):
    def test_cli_add_write_and_rules_do_not_store_secrets(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        agents = home / "agents"
        (agents / "memory").mkdir(parents=True)
        import site

        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), site.getusersitepackages()))
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        env["AGENTS_HOME"] = str(agents)
        env["AGENTS_NO_UPDATE_CHECK"] = "1"
        env.pop("AGENTS_MEMORY_PATH", None)
        env.pop("AGENTS_MEMORY_REDACT_PATTERNS", None)
        env.pop("AGENTS_MEMORY_REDACT_CONFIG", None)

        def run(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, "-m", "agents_memory", *args],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                input=stdin,
                env=env,
                check=False,
            )

        added = run(
            "add",
            f"cli marker {OPENAI} stays",
            "--kind",
            "concept",
            "--name",
            "cli-secret",
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertNotIn(OPENAI, added.stdout)
        self.assertNotIn(OPENAI, added.stderr)
        self.assertIn("1 secret replaced with [redacted]", added.stdout)
        self.assertTrue(
            added.stdout.startswith(
                "Saved to user/concepts/cli-secret.md (1 secret replaced with [redacted])\n"
            )
        )

        secret_file = home / "body.md"
        secret_file.write_text(f"# Note\n\nAPI_KEY={ASSIGN}\n{PEM}", encoding="utf-8")
        written = run("write", "user/notes/cli-secret.md", "--file", str(secret_file))
        self.assertEqual(written.returncode, 0, written.stderr)
        self.assertNotIn(ASSIGN, written.stdout + written.stderr)
        self.assertNotIn("exampleKeyMat", written.stdout + written.stderr)
        self.assertIn("replaced with [redacted]", written.stdout)

        ruled = run("rules", "add", f"Never log API_KEY={ASSIGN} in a rule.")
        self.assertEqual(ruled.returncode, 0, ruled.stderr)
        self.assertNotIn(ASSIGN, ruled.stdout + ruled.stderr)
        self.assertIn("1 secret replaced with [redacted]", ruled.stderr)

        secret_file.unlink()
        blob = []
        for path in agents.rglob("*"):
            if path.is_file():
                blob.append(path.read_text(encoding="utf-8", errors="replace"))
        text = "\n".join(blob)
        for secret in (OPENAI, ASSIGN, "exampleKeyMat"):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
