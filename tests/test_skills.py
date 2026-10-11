"""Unit tests for always-on skills management: configuration, extraction, CLI, and rule injection."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents_memory import rules, skills, store


class SkillsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "memory"
        self.skills_dir = self.root / "skills"
        self.user.mkdir(parents=True)
        self.skills_dir.mkdir(parents=True)

        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "USER_MD", self.user / "USER.md"),
            patch.object(store, "PROJECTS_MD", self.user / "PROJECTS.md"),
            patch.object(store, "AGENTS_RULES", self.user / "rules"),
            patch.dict(os.environ, {"AGENTS_SKILLS_DIR": str(self.skills_dir)}),
        ]
        for p in self.patches:
            p.start()

        (self.user / "USER.md").write_text("# User Profile\n", encoding="utf-8")
        (self.user / "PROJECTS.md").write_text("# Projects\n", encoding="utf-8")

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_default_config_empty(self) -> None:
        self.assertEqual(skills.DEFAULT_CONFIG["active_skills"], [])
        self.assertEqual(skills.DEFAULT_CONFIG["intensity"], {})

        cfg = skills.load_active_skills_config()
        self.assertEqual(cfg["active_skills"], [])
        self.assertEqual(cfg["intensity"], {})
        self.assertTrue(skills.active_skills_path().is_file())

    def test_extract_skill_rules_intensity_dict(self) -> None:
        skill_dir = self.skills_dir / "tester"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: tester\n"
            "always_on_rule:\n"
            "  ultra: \"Ultra terse mode.\"\n"
            "  full: \"Full detailed mode.\"\n"
            "  lite: \"Lite mode.\"\n"
            "---\n"
            "# Tester skill\n",
            encoding="utf-8",
        )

        rules_ultra = skills.extract_skill_rules("tester", skill_file, "ultra")
        self.assertEqual(rules_ultra, ["Ultra terse mode."])

        rules_full = skills.extract_skill_rules("tester", skill_file, "full")
        self.assertEqual(rules_full, ["Full detailed mode."])

        rules_default = skills.extract_skill_rules("tester", skill_file, "unknown")
        self.assertEqual(rules_default, ["Full detailed mode."])

    def test_extract_skill_rules_scalar_string(self) -> None:
        skill_dir = self.skills_dir / "single-rule"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: single-rule\n"
            "always_on_rule: \"Always enforce strict formatting.\"\n"
            "---\n",
            encoding="utf-8",
        )
        extracted = skills.extract_skill_rules("single-rule", skill_file)
        self.assertEqual(extracted, ["Always enforce strict formatting."])

    def test_extract_skill_rules_list(self) -> None:
        skill_dir = self.skills_dir / "multi-rule"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: multi-rule\n"
            "rules:\n"
            "  - \"First rule line.\"\n"
            "  - \"Second rule line.\"\n"
            "---\n",
            encoding="utf-8",
        )
        extracted = skills.extract_skill_rules("multi-rule", skill_file)
        self.assertEqual(extracted, ["First rule line.", "Second rule line."])

    def test_extract_skill_rules_markdown_section(self) -> None:
        skill_dir = self.skills_dir / "section-rule"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: section-rule\n"
            "---\n"
            "# Section Skill\n\n"
            "## Always-On Rules\n"
            "- Markdown rule alpha\n"
            "- Markdown rule beta\n\n"
            "## Other Section\n"
            "- Not a rule\n",
            encoding="utf-8",
        )
        extracted = skills.extract_skill_rules("section-rule", skill_file)
        self.assertEqual(extracted, ["Markdown rule alpha", "Markdown rule beta"])

    def test_extract_skill_rules_description_fallback(self) -> None:
        skill_dir = self.skills_dir / "fallback-skill"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: fallback-skill\n"
            "description: Essential linting guidelines for code.\n"
            "---\n",
            encoding="utf-8",
        )
        extracted = skills.extract_skill_rules("fallback-skill", skill_file)
        self.assertEqual(extracted, ["fallback-skill: Essential linting guidelines for code."])

    def test_enable_and_disable_skill(self) -> None:
        skills.enable_skill("custom-one", intensity="lite")
        cfg = skills.load_active_skills_config()
        self.assertIn("custom-one", cfg["active_skills"])
        self.assertEqual(cfg["intensity"]["custom-one"], "lite")

        skills.disable_skill("custom-one")
        cfg2 = skills.load_active_skills_config()
        self.assertNotIn("custom-one", cfg2["active_skills"])

    def test_cli_subcommands(self) -> None:
        # Create a skill in mock skills_dir
        skill_dir = self.skills_dir / "mock-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: mock-skill\ndescription: Mock description\n---\n",
            encoding="utf-8",
        )

        ret = skills.skills_main(["enable", "mock-skill", "--intensity", "ultra"])
        self.assertEqual(ret, 0)
        cfg = skills.load_active_skills_config()
        self.assertEqual(cfg["active_skills"], ["mock-skill"])
        self.assertEqual(cfg["intensity"]["mock-skill"], "ultra")

        ret = skills.skills_main(["list"])
        self.assertEqual(ret, 0)

        ret = skills.skills_main(["disable", "mock-skill"])
        self.assertEqual(ret, 0)
        cfg = skills.load_active_skills_config()
        self.assertEqual(cfg["active_skills"], [])

    def test_rules_render_integration(self) -> None:
        # 1. No active skills, no HARD.md -> empty
        self.assertEqual(rules.render_rules(), "")

        # 2. Add active skill
        skill_dir = self.skills_dir / "polite"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: polite\n"
            "always_on_rule:\n"
            "  full: \"Always respond concisely and accurately.\"\n"
            "---\n",
            encoding="utf-8",
        )
        skills.enable_skill("polite", intensity="full")

        rendered = rules.render_rules()
        self.assertIn("<memory_rules>", rendered)
        self.assertIn("- Always respond concisely and accurately.", rendered)
        self.assertIn("</memory_rules>", rendered)

        data = rules.render_rules_data()
        self.assertEqual(data["skill_rules"], ["Always respond concisely and accurately."])

    def test_store_always_on_body_note(self) -> None:
        # Without active skills, no skills note
        body_empty = store.always_on_body()
        self.assertNotIn("Global skills directory:", body_empty)

        # With active skill, skills note is injected
        skills.enable_skill("dummy-skill")
        body_active = store.always_on_body()
        self.assertIn("Global skills directory:", body_active)
        self.assertIn(skills.SKILLS_NOTE, body_active)

    def test_resolve_memory_path(self) -> None:
        p1 = store.resolve_memory_path("active_skills.json")
        self.assertEqual(p1, skills.active_skills_path())

        p2 = store.resolve_memory_path("user/active_skills.json")
        self.assertEqual(p2, skills.active_skills_path())


if __name__ == "__main__":
    unittest.main()
