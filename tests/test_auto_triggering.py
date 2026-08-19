import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agents_memory import store

ROOT = Path(__file__).resolve().parents[1]


def parse_skill_frontmatter(content: str) -> dict:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return {}
    raw = match.group(1)
    meta = {}
    for line in raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def match_skill_intent(prompt: str) -> str:
    """Heuristic intent matcher mirroring coding agent skill trigger rules."""
    p_lower = prompt.lower()

    # Memory Distill triggers
    distill_triggers = [
        "distill",
        "staging aufräumen",
        "staging leeren",
        "staging verdichten",
        "inbox abarbeiten",
        "inbox aufräumen",
        "memory verdichten",
        "staging items",
        "clean up staging",
        "staging-inbox",
    ]
    for trig in distill_triggers:
        if trig in p_lower:
            return "memory-distill"

    # Memory Sync triggers
    sync_triggers = [
        "bestandsaufnahme",
        "bestandaufnahme",
        "memory sync",
        "neues projekt",
        "neues repo",
        "repo angelegt",
        "projekt angelegt",
        "inventory",
        "projekte updaten",
        "register project",
        "register new repo",
        "projekte scannen",
    ]
    for trig in sync_triggers:
        if trig in p_lower:
            return "memory-sync"

    # Search triggers
    if "search memory" in p_lower or "suche in memory" in p_lower:
        return "search_memory"

    return "none"


class AutoTriggeringTests(unittest.TestCase):
    def test_distill_skill_frontmatter_and_content(self):
        skill_file = ROOT / "skills" / "memory-distill" / "SKILL.md"
        self.assertTrue(skill_file.is_file(), "memory-distill SKILL.md missing")
        content = skill_file.read_text(encoding="utf-8")
        meta = parse_skill_frontmatter(content)
        self.assertEqual(meta.get("name"), "memory-distill")
        self.assertIn("staging", meta.get("description", "").lower())
        self.assertIn("distill", meta.get("description", "").lower())

        # Check workflow contract in body
        self.assertIn("get_staging_inbox", content)
        self.assertIn("distill_batch", content)
        self.assertIn("source_path", content)

    def test_sync_skill_frontmatter_and_content(self):
        skill_file = ROOT / "skills" / "memory-sync" / "SKILL.md"
        self.assertTrue(skill_file.is_file(), "memory-sync SKILL.md missing")
        content = skill_file.read_text(encoding="utf-8")
        meta = parse_skill_frontmatter(content)
        self.assertEqual(meta.get("name"), "memory-sync")
        self.assertIn("inventory", meta.get("description", "").lower())

    def test_skill_sync_mirroring(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        user_home = Path(tmp.name)
        cursor_skills = user_home / ".cursor" / "skills"
        agents_skills = user_home / ".agents" / "skills"
        gemini_skills = user_home / ".gemini" / "config" / "skills"

        with patch("pathlib.Path.home", return_value=user_home), patch.object(
            store, "USER_MEMORY", user_home / ".agents" / "memory"
        ):
            # Ensure skill source exists
            store.sync_injection(include_repos=False)

        # Check if skills were mirrored to global skill directories
        self.assertTrue((agents_skills / "memory-distill" / "SKILL.md").exists())
        self.assertTrue((gemini_skills / "memory-distill" / "SKILL.md").exists())
        self.assertTrue((cursor_skills / "memory-distill" / "SKILL.md").exists())
        self.assertTrue((agents_skills / "memory-sync" / "SKILL.md").exists())

    def test_prompt_intent_classification(self):
        test_cases = [
            # Distill prompts
            ("Kannst du bitte die Staging-Inbox abarbeiten?", "memory-distill"),
            ("Lass uns distill machen", "memory-distill"),
            ("Staging aufräumen bitte", "memory-distill"),
            ("Bitte Memory verdichten", "memory-distill"),
            ("Distill staging items into typed files", "memory-distill"),
            ("Clean up staging inbox now", "memory-distill"),

            # Sync prompts
            ("Mach mal eine Bestandsaufnahme der Projekte", "memory-sync"),
            ("Bitte memory sync ausführen", "memory-sync"),
            ("Ich habe ein neues Projekt angelegt", "memory-sync"),
            ("Run inventory over all repos", "memory-sync"),
            ("Register new repo under Coding", "memory-sync"),

            # Search prompts
            ("Search memory for supabase setup", "search_memory"),
            ("Suche in memory nach Tailwind Regeln", "search_memory"),

            # Negative cases (should not trigger memory actions)
            ("Fix the syntax error in store.py", "none"),
            ("Add unit test for authentication", "none"),
            ("Write a CSS button component", "none"),
            ("What is the weather today?", "none"),
        ]

        correct = 0
        for prompt, expected_intent in test_cases:
            detected = match_skill_intent(prompt)
            self.assertEqual(
                detected,
                expected_intent,
                f"Prompt '{prompt}' classified as '{detected}', expected '{expected_intent}'",
            )
            correct += 1

        accuracy = correct / len(test_cases)
        self.assertEqual(accuracy, 1.0)


if __name__ == "__main__":
    unittest.main()
