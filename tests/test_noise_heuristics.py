import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents_memory.ingest_common import is_ephemeral_noise, keep_user_line
from agents_memory import store


class TestNoiseHeuristics(unittest.TestCase):
    def test_german_ephemeral_chatter(self):
        chatter_lines = [
            "kannst du das committen?",
            "könnte man in omnus das hier verwenden?",
            "warum klappt das nicht?",
            "hä das hab ich schon alles",
            "er behauptet der server sei aktiv aber es klappt 0%",
            "warte kurz",
            "schau mal",
            "ja wow supportet kein .de",
            "ah nvm ich zahle 50 cent pro monat",
            "ok",
            "danke dir",
            "alles klar!",
        ]
        for line in chatter_lines:
            is_noise, reason = is_ephemeral_noise(line)
            self.assertTrue(is_noise, f"Expected noise for: {line} (reason: {reason})")

    def test_english_ephemeral_chatter(self):
        chatter_lines = [
            "can you fix line 40?",
            "how do I configure lint rules?",
            "why is this failing?",
            "please look at the trace",
            "ok",
            "thanks a lot",
        ]
        for line in chatter_lines:
            is_noise, reason = is_ephemeral_noise(line)
            self.assertTrue(is_noise, f"Expected noise for: {line} (reason: {reason})")

    def test_build_and_test_reports(self):
        reports = [
            "npm test: 41/41 Tests bestanden",
            "cargo test passed (2/2)",
            "npm run build: Erfolgreich gebaut",
            "build fehlerfrei abgeschlossen",
            "0 errors found",
            "exit code 1",
            "SyntaxError: unexpected token",
        ]
        for line in reports:
            is_noise, reason = is_ephemeral_noise(line)
            self.assertTrue(is_noise, f"Expected noise for: {line} (reason: {reason})")

    def test_code_and_sql_snippets(self):
        snippets = [
            "ALTER TABLE users ADD COLUMN credits INTEGER NOT NULL DEFAULT 50;",
            "CREATE TABLE IF NOT EXISTS credit_transactions (id text);",
            "git commit -am 'quick fix'",
            "export const useAuth = () => {}",
            "import { useState } from 'react'",
        ]
        for line in snippets:
            is_noise, reason = is_ephemeral_noise(line)
            self.assertTrue(is_noise, f"Expected noise for: {line} (reason: {reason})")

    def test_header_stubs_and_urls(self):
        stubs = [
            "**Rust Backend (`src-tauri`):**",
            "### Section Title",
            "https://medium.com/data-science/some-article-12345",
        ]
        for line in stubs:
            is_noise, reason = is_ephemeral_noise(line)
            self.assertTrue(is_noise, f"Expected noise for: {line} (reason: {reason})")

    def test_durable_facts_kept(self):
        durable = [
            "Always use Tailwind v3 for styling across all components",
            "Never commit .env or secrets to git",
            "We prefer Azure neural speech over ElevenLabs for TTS",
            "Immer deutsche Prompts und englischen Code verwenden",
            "Datenschutz: Niemals Userdaten an externe Analyse-Tools mitschicken",
            "Ship decisions as numbered markdown files under the repo memory tree",
        ]
        for line in durable:
            is_noise, reason = is_ephemeral_noise(line)
            self.assertFalse(is_noise, f"Expected durable fact kept: {line} (got noise: {reason})")
            self.assertTrue(keep_user_line("title", line), f"Expected keep_user_line=True for: {line}")

    def test_sync_conflicts_excluded_from_staging(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        user = root / "user"
        staging = user / "staging"
        staging.mkdir(parents=True)

        (staging / "captured.md").write_text("# Staging\n\n- Valid bullet\n", encoding="utf-8")
        (staging / "sync-conflicts.md").write_text("# Conflicts\n\n- Conflict log entry\n", encoding="utf-8")
        (staging / "sync-errors.md").write_text("# Errors\n\n- Error log entry\n", encoding="utf-8")

        with patch.object(store, "USER_MEMORY", user), patch.object(store, "parse_projects", return_value=[]):
            paths = store._collect_staging_paths()
            path_names = [p.name for p in paths]
            self.assertIn("captured.md", path_names)
            self.assertNotIn("sync-conflicts.md", path_names)
            self.assertNotIn("sync-errors.md", path_names)

    def test_auto_distill_returns_candidate_suggestions(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        user = root / "user"
        staging = user / "staging"
        staging.mkdir(parents=True)

        captured = staging / "captured.md"
        captured.write_text(
            "# Staging\n\n"
            "- ok\n"
            "- npm test: 41 passed\n"
            "- Always use Tailwind v3\n"
            "- Die Reader-Controls sollen alle einzeln switchable sein\n",
            encoding="utf-8",
        )

        with patch.object(store, "USER_MEMORY", user), patch.object(
            store, "sync_injection", lambda **k: ([], [])
        ), patch.object(store, "parse_projects", return_value=[]):
            res = store.auto_distill(limit=50, discard_noise=True, auto_sync=False)
            self.assertEqual(res["discarded"], 2)  # 'ok', 'npm test...'
            self.assertEqual(res["promoted"], 1)   # 'Always use Tailwind v3'
            self.assertEqual(res["remaining_staging_count"], 1)  # 'Die Reader-Controls...'
            self.assertEqual(len(res["candidates"]), 1)
            candidate = res["candidates"][0]
            self.assertIn("Reader-Controls", candidate["bullet"])
            self.assertEqual(candidate["suggested_kind"], "note")


if __name__ == "__main__":
    unittest.main()
