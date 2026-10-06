"""Hard rules: budget, staging-only proposals, render, MCP delivery, CLI, injection."""
from __future__ import annotations

import asyncio
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

from agents_memory import mcp_server, rules, store
from agents_memory.remote import sync_bundle
from agents_memory.remote.merge import merge_markdown_files

ROOT = Path(__file__).resolve().parents[1]


class RulesStoreCase(unittest.TestCase):
    """Isolated user store; no host injection or remote push."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "memory"
        self.repo = self.root / "repo"
        self.user.mkdir(parents=True)
        self.repo.mkdir(parents=True)
        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n"
            f"| demo | `{self.repo}` | demo project | py | active |\n",
            encoding="utf-8",
        )
        (self.user / "USER.md").write_text("# Profile\n\nName: Test\n", encoding="utf-8")
        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "USER_MD", self.user / "USER.md"),
            patch.object(store, "PROJECTS_MD", self.projects_md),
            patch.object(store, "SCAN_JSON", self.user / "scan.json"),
            patch.object(store, "ORPHANS", self.user / "orphans"),
            patch.object(store, "_finish_store_write", lambda: None),
            patch.dict(
                os.environ,
                {
                    rules.ENV_MAX_LINES: "",
                    rules.ENV_MAX_CHARS: "",
                    rules.ENV_PROJECT_MAX_LINES: "",
                },
            ),
        ]
        for p in self.patches:
            p.start()
        store.clear_memory_cache()
        rules.DELIVERY.reset()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        rules.DELIVERY.reset()
        store.clear_memory_cache()
        self.tmp.cleanup()

    def write_global(self, *lines: str) -> Path:
        path = self.user / "rules" / "HARD.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Hard rules\n\n" + "".join(f"- {ln}\n" for ln in lines), encoding="utf-8")
        return path

    def write_overlay(self, slug: str, *lines: str) -> Path:
        path = self.user / "projects" / slug / "RULES.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"- {ln}\n" for ln in lines), encoding="utf-8")
        return path


class RenderTests(RulesStoreCase):
    def test_missing_files_render_empty(self) -> None:
        self.assertEqual(rules.render_rules(), "")
        self.assertEqual(rules.render_rules("demo"), "")
        self.assertEqual(rules.render_rules("demo", include_global=False), "")
        self.assertEqual(rules.render_instructions(), rules.SESSION_HINT)

    def test_global_and_overlay(self) -> None:
        self.write_global("Rule one.", "Rule two.")
        self.write_overlay("demo", "Project rule.")
        self.assertEqual(
            rules.render_rules(),
            "<memory_rules>\n- Rule one.\n- Rule two.\n</memory_rules>",
        )
        self.assertEqual(
            rules.render_rules("demo"),
            "<memory_rules>\n- Rule one.\n- Rule two.\n"
            '<project name="demo">\n- Project rule.\n</project>\n</memory_rules>',
        )
        self.assertEqual(
            rules.render_rules("demo", include_global=False),
            '<memory_rules project="demo">\n- Project rule.\n</memory_rules>',
        )

    def test_overlay_without_global(self) -> None:
        self.write_overlay("demo", "Only here.")
        self.assertEqual(rules.render_rules(), "")
        self.assertIn("- Only here.", rules.render_rules("demo"))

    def test_parse_skips_headings_comments_and_list_markers(self) -> None:
        text = "# Title\n\n<!-- note -->\n- a\n* b\n1. c\nd\n   \n"
        self.assertEqual(rules.parse_rules(text), ["a", "b", "c", "d"])

    def test_path_like_project_is_ignored(self) -> None:
        self.write_global("Rule one.")
        self.assertEqual(rules.render_rules("../etc"), rules.render_rules())
        with self.assertRaises(rules.RulesError):
            rules.project_rules_path("../etc")

    def test_instructions_carry_rules_and_hint(self) -> None:
        self.write_global("Rule one.")
        text = rules.render_instructions()
        self.assertTrue(text.startswith(rules.render_rules()))
        self.assertTrue(text.endswith(rules.SESSION_HINT))
        rules.refresh_instructions(mcp_server.mcp)
        self.assertEqual(mcp_server.mcp.instructions, text)


class BudgetTests(RulesStoreCase):
    def test_global_line_budget(self) -> None:
        for i in range(rules.DEFAULT_MAX_LINES):
            rules.add_rule(f"Rule {i}.", user_intent=True)
        before = (self.user / "rules" / "HARD.md").read_text(encoding="utf-8")
        with self.assertRaises(rules.RulesBudgetError) as ctx:
            rules.add_rule("One too many.", user_intent=True)
        self.assertIn("Consolidate", str(ctx.exception))
        self.assertIn("31/30 rule lines", str(ctx.exception))
        self.assertEqual((self.user / "rules" / "HARD.md").read_text(encoding="utf-8"), before)

    def test_global_char_budget(self) -> None:
        long_rule = "x" * (rules.DEFAULT_MAX_CHARS + 1)
        with self.assertRaises(rules.RulesBudgetError) as ctx:
            rules.add_rule(long_rule, user_intent=True)
        self.assertIn("characters", str(ctx.exception))
        self.assertFalse((self.user / "rules" / "HARD.md").exists())

    def test_project_line_budget(self) -> None:
        for i in range(rules.DEFAULT_PROJECT_MAX_LINES):
            rules.add_rule(f"P {i}.", "demo", user_intent=True)
        with self.assertRaises(rules.RulesBudgetError) as ctx:
            rules.add_rule("P extra.", "demo", user_intent=True)
        self.assertIn("project 'demo'", str(ctx.exception))
        self.assertEqual(len(rules.load_rules("demo")), rules.DEFAULT_PROJECT_MAX_LINES)

    def test_env_overrides_limits(self) -> None:
        with patch.dict(os.environ, {rules.ENV_MAX_LINES: "2", rules.ENV_PROJECT_MAX_LINES: "1"}):
            rules.add_rule("A.", user_intent=True)
            rules.add_rule("B.", user_intent=True)
            with self.assertRaises(rules.RulesBudgetError):
                rules.add_rule("C.", user_intent=True)
            rules.add_rule("P.", "demo", user_intent=True)
            with self.assertRaises(rules.RulesBudgetError):
                rules.add_rule("Q.", "demo", user_intent=True)
        with patch.dict(os.environ, {rules.ENV_MAX_CHARS: "5"}):
            with self.assertRaises(rules.RulesBudgetError):
                rules.add_rule("Longer than five.", "", user_intent=True)
        with patch.dict(os.environ, {rules.ENV_MAX_LINES: "junk"}):
            self.assertEqual(rules.max_lines(), rules.DEFAULT_MAX_LINES)

    def test_over_budget_file_may_shrink_but_not_grow(self) -> None:
        self.write_global(*[f"Rule {i}." for i in range(rules.DEFAULT_MAX_LINES + 3)])
        rules.remove_rule(1, user_intent=True)
        self.assertEqual(len(rules.load_rules()), rules.DEFAULT_MAX_LINES + 2)
        rules.edit_rule(1, "Short.", user_intent=True)
        with self.assertRaises(rules.RulesBudgetError):
            rules.edit_rule(1, "A much longer replacement rule than before.", user_intent=True)
        with self.assertRaises(rules.RulesBudgetError):
            rules.add_rule("Grow.", user_intent=True)

    def test_set_replaces_file_within_budget(self) -> None:
        rules.save_rules_text("# Hard rules\n\n- One.\n- Two.\n", user_intent=True)
        self.assertEqual(rules.load_rules(), ["One.", "Two."])
        too_many = "".join(f"- R{i}\n" for i in range(rules.DEFAULT_MAX_LINES + 1))
        with self.assertRaises(rules.RulesBudgetError):
            rules.save_rules_text(too_many, user_intent=True)
        self.assertEqual(rules.load_rules(), ["One.", "Two."])

    def test_rule_input_validation(self) -> None:
        with self.assertRaises(rules.RulesError):
            rules.add_rule("two\nlines", user_intent=True)
        with self.assertRaises(rules.RulesError):
            rules.add_rule("   ", user_intent=True)
        rules.add_rule("Same.", user_intent=True)
        with self.assertRaises(rules.RulesError):
            rules.add_rule("same.", user_intent=True)
        with self.assertRaises(rules.RulesError):
            rules.remove_rule(5, user_intent=True)


class WriteBoundaryTests(RulesStoreCase):
    def test_writes_need_user_intent(self) -> None:
        with self.assertRaises(rules.RulesWriteDenied):
            rules.save_rules_text("- X.\n")
        with self.assertRaises(rules.RulesWriteDenied):
            rules.add_rule("X.")
        with self.assertRaises(rules.RulesWriteDenied):
            rules.remove_rule(1)
        self.assertFalse((self.user / "rules" / "HARD.md").exists())

    def test_vault_crud_refuses_rule_files(self) -> None:
        hard = self.write_global("Keep me.")
        overlay = self.write_overlay("demo", "Keep me too.")
        for fid in ("user/rules/HARD.md", "user/projects/demo/RULES.md"):
            with self.assertRaises(rules.RulesWriteDenied):
                store.write_memory_file(fid, "- hacked\n", auto_sync=False)
            with self.assertRaises(rules.RulesWriteDenied):
                store.delete_memory_file(fid, auto_sync=False)
        with self.assertRaises(rules.RulesWriteDenied):
            store.delete_memory("user/rules/HARD.md:3", auto_sync=False)
        with patch.object(store, "memory_file_for", return_value=hard):
            with self.assertRaises(rules.RulesWriteDenied):
                store.add_memory("sneak in", kind="note", name="x", auto_sync=False)
        out = mcp_server.write_memory_file("user/rules/HARD.md", "- hacked\n")
        self.assertIn("propose_rule", out)
        self.assertEqual(rules.load_rules(), ["Keep me."])
        self.assertEqual(rules.load_rules("demo"), ["Keep me too."])
        self.assertTrue(overlay.is_file())

    def test_other_files_named_rules_stay_writable(self) -> None:
        loc = store.write_memory_file("user/notes/rules.md", "- fine\n", auto_sync=False)
        self.assertEqual(loc, "user/notes/rules.md")

    def test_proposals_go_to_staging_only(self) -> None:
        self.write_global("Existing.")
        out = mcp_server.propose_rule("Always run the linter.")
        self.assertIn("staging/rule-proposals.md", out)
        out2 = mcp_server.propose_rule("Use tabs.", project="demo")
        self.assertIn("project 'demo'", out2)
        self.assertEqual(rules.load_rules(), ["Existing."])
        self.assertEqual(rules.load_rules("demo"), [])
        staged = (self.user / "staging" / "rule-proposals.md").read_text(encoding="utf-8")
        self.assertIn("- [rule @ global] Always run the linter.", staged)
        self.assertIn("- [rule @ project:demo] Use tabs.", staged)
        inbox = store.get_staging_inbox(limit=0)
        texts = [b["text"] for g in inbox["groups"] for b in g["bullets"]]
        self.assertIn("Always run the linter.", texts)
        self.assertIn("Error proposing rule", mcp_server.propose_rule("multi\nline"))

    def test_auto_distill_leaves_proposals_for_the_user(self) -> None:
        mcp_server.propose_rule("Never deploy on Fridays.")
        res = store.auto_distill(limit=50, discard_noise=True, auto_sync=False)
        self.assertEqual(res.get("promoted", 0), 0)
        staged = (self.user / "staging" / "rule-proposals.md").read_text(encoding="utf-8")
        self.assertIn("Never deploy on Fridays.", staged)
        self.assertEqual(rules.load_rules(), [])

    def test_user_add_consumes_matching_proposal(self) -> None:
        mcp_server.propose_rule("Never deploy on Fridays.")
        mcp_server.propose_rule("Keep this one.")
        rules.add_rule("Never deploy on Fridays.", user_intent=True)
        staged = (self.user / "staging" / "rule-proposals.md").read_text(encoding="utf-8")
        self.assertNotIn("Fridays", staged)
        self.assertIn("Keep this one.", staged)
        self.assertEqual(rules.load_rules(), ["Never deploy on Fridays."])


class DeliveryTests(RulesStoreCase):
    def test_first_response_gets_block_then_deduped(self) -> None:
        self.write_global("Rule one.")
        block = rules.render_rules()
        first = rules.DELIVERY.apply("result-1")
        self.assertEqual(first, f"{block}\n\nresult-1")
        self.assertEqual(rules.DELIVERY.apply("result-2"), "result-2")

    def test_project_overlay_once_per_project(self) -> None:
        self.write_global("Rule one.")
        self.write_overlay("demo", "Demo rule.")
        self.write_overlay("other", "Other rule.")
        demo = rules.render_rules("demo", include_global=False)
        other = rules.render_rules("other", include_global=False)
        first = rules.DELIVERY.apply("r1", project="demo")
        self.assertEqual(first, f"{rules.render_rules()}\n\n{demo}\n\nr1")
        self.assertEqual(rules.DELIVERY.apply("r2", project="demo"), "r2")
        self.assertEqual(rules.DELIVERY.apply("r3", project="other"), f"{other}\n\nr3")
        self.assertEqual(rules.DELIVERY.apply("r4", project="other"), "r4")
        self.assertEqual(rules.DELIVERY.apply("r5"), "r5")

    def test_changed_rules_are_delivered_again(self) -> None:
        self.write_global("Rule one.")
        rules.DELIVERY.apply("r1")
        self.write_global("Rule one.", "Rule two.")
        self.assertIn("- Rule two.", rules.DELIVERY.apply("r2"))

    def test_sessions_are_independent(self) -> None:
        self.write_global("Rule one.")

        class Session:
            pass

        a, b = Session(), Session()
        self.assertIn("<memory_rules>", rules.DELIVERY.apply("x", session=a))
        self.assertEqual(rules.DELIVERY.apply("x", session=a), "x")
        self.assertIn("<memory_rules>", rules.DELIVERY.apply("x", session=b))

    def test_no_rules_no_change(self) -> None:
        self.assertEqual(rules.DELIVERY.apply("plain", project="demo"), "plain")

    def test_registered_tool_wrapper_prefixes_once(self) -> None:
        self.write_global("Rule one.")
        self.write_overlay("demo", "Demo rule.")
        tool = mcp_server.mcp._tool_manager.get_tool("get_project_memories")
        first = tool.fn(project="demo")
        self.assertTrue(first.startswith(rules.render_rules()))
        self.assertIn(rules.render_rules("demo", include_global=False), first)
        second = tool.fn(project="demo")
        self.assertNotIn("<memory_rules", second)
        self.assertEqual(second, mcp_server.get_project_memories("demo"))
        # Module-level functions (tests, remote REST, hybrid dispatch) stay unprefixed.
        rules.DELIVERY.reset()
        self.assertNotIn("<memory_rules", mcp_server.list_projects())

    def test_mcp_session_end_to_end(self) -> None:
        self.write_global("Rule one.")
        self.write_overlay("demo", "Demo rule.")
        rules.refresh_instructions(mcp_server.mcp)
        global_block = rules.render_rules()
        demo_block = rules.render_rules("demo", include_global=False)

        async def one_session() -> tuple:
            import anyio
            from mcp.client.session import ClientSession
            from mcp.shared.memory import create_client_server_memory_streams

            server = mcp_server.mcp._mcp_server
            async with create_client_server_memory_streams() as (client_streams, server_streams):
                async with anyio.create_task_group() as tg:
                    tg.start_soon(
                        lambda: server.run(
                            server_streams[0],
                            server_streams[1],
                            server.create_initialization_options(),
                        )
                    )
                    async with ClientSession(client_streams[0], client_streams[1]) as client:
                        init = await client.initialize()
                        texts = []
                        for name, args in (
                            ("list_projects", {}),
                            ("list_projects", {}),
                            ("get_project_memories", {"project": "demo"}),
                            ("get_project_memories", {"project": "demo"}),
                        ):
                            res = await client.call_tool(name, args)
                            texts.append(res.content[0].text)
                    tg.cancel_scope.cancel()
            return init.instructions, texts

        instructions, texts = asyncio.run(one_session())
        self.assertIn("- Rule one.", instructions)
        self.assertIn(rules.SESSION_HINT, instructions)
        self.assertTrue(texts[0].startswith(global_block + "\n\n"))
        self.assertNotIn("<memory_rules", texts[1])
        self.assertTrue(texts[2].startswith(demo_block + "\n\n"))
        self.assertNotIn("- Rule one.", texts[2])
        self.assertNotIn("<memory_rules", texts[3])

        _, again = asyncio.run(one_session())
        self.assertTrue(again[0].startswith(global_block), "a new session gets the block again")


class GeneratorTests(RulesStoreCase):
    def test_always_on_and_agent_rule_use_render(self) -> None:
        self.assertNotIn("<memory_rules", store.always_on_body())
        self.write_global("Rule one.")
        block = rules.render_rules()
        body = store.always_on_body()
        self.assertTrue(body.startswith(block + "\n\n# Profile"))
        self.assertIn(block, store.agent_rule_text())
        self.assertIn(block, store.gemini_agents_text())

    def test_project_injection_uses_overlay_render(self) -> None:
        demo = store.projects_by_slug()["demo"]
        self.assertNotIn("<memory_rules", store.project_agents_text(demo))
        self.write_global("Rule one.")
        self.write_overlay("demo", "Demo rule.")
        text = store.project_agents_text(demo)
        self.assertIn(rules.render_rules("demo", include_global=False), text)
        self.assertNotIn("- Rule one.", text)


class SyncTests(RulesStoreCase):
    def test_vault_rules_file_is_user_content_in_bundle(self) -> None:
        self.assertTrue(sync_bundle.is_agent_rule_key("rules/user-rules.mdc"))
        self.assertFalse(sync_bundle.is_agent_rule_key("rules/HARD.md"))
        self.assertFalse(sync_bundle.is_agent_rule_key("rules/sub/x.mdc"))
        user, agent_rules, _ = sync_bundle._split_bundle(
            {"rules/HARD.md": "- a\n", "rules/user-rules.mdc": "x", "USER.md": "u"}
        )
        self.assertIn("rules/HARD.md", user)
        self.assertEqual(list(agent_rules), ["rules/user-rules.mdc"])
        self.write_global("Rule one.")
        with patch.object(sync_bundle, "_rules_dir", return_value=self.root / "no-rules"):
            bundle = sync_bundle.collect_sync_bundle(include_projects=False, memory_root=self.user)
        self.assertIn("rules/HARD.md", bundle)

    def test_rule_files_merge_last_write_wins(self) -> None:
        hard = self.write_global("A.", "B.")
        merged, changed = merge_markdown_files(hard, "# Hard rules\n\n- A.\n- C.\n")
        self.assertTrue(changed)
        self.assertEqual(merged, "# Hard rules\n\n- A.\n- C.\n")
        overlay = self.write_overlay("demo", "X.")
        merged, _ = merge_markdown_files(overlay, "- Y.\n")
        self.assertEqual(merged, "- Y.\n")


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.agents = self.home / ".agents"
        self.mem = self.agents / "memory"
        self.mem.mkdir(parents=True)
        (self.mem / "USER.md").write_text("# Profile\n", encoding="utf-8")
        (self.mem / "PROJECTS.md").write_text(
            "# Projects\n\n| slug | path | role | stack | status |\n|------|------|------|-------|--------|\n",
            encoding="utf-8",
        )
        (self.mem / "scan.json").write_text(json.dumps({"roots": [], "ignore_slugs": []}), encoding="utf-8")
        self.env = dict(os.environ)
        for key in (rules.ENV_MAX_LINES, rules.ENV_MAX_CHARS, rules.ENV_PROJECT_MAX_LINES, "AGENTS_MEMORY_PATH"):
            self.env.pop(key, None)
        self.env.update(
            {
                "HOME": str(self.home),
                "USERPROFILE": str(self.home),
                "AGENTS_HOME": str(self.agents),
                "AGENTS_NO_UPDATE_CHECK": "1",
                "PYTHONPATH": _SRC,
            }
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def cli(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "agents_memory", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            input=stdin,
            env=self.env,
            timeout=120,
        )

    def test_context_and_rules_roundtrip(self) -> None:
        empty = self.cli("context")
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(empty.stdout, "")

        self.assertEqual(self.cli("rules", "add", "Rule one.").returncode, 0)
        self.assertEqual(self.cli("rules", "add", "--project", "demo", "Demo rule.").returncode, 0)

        md = self.cli("context", "--project", "demo")
        self.assertEqual(md.returncode, 0, md.stderr)
        self.assertEqual(
            md.stdout,
            '<memory_rules>\n- Rule one.\n<project name="demo">\n- Demo rule.\n</project>\n</memory_rules>\n',
        )

        js = self.cli("context", "--project", "demo", "--format", "json")
        self.assertEqual(js.returncode, 0, js.stderr)
        data = json.loads(js.stdout)
        self.assertEqual(data["rules"], ["Rule one."])
        self.assertEqual(data["project_rules"], ["Demo rule."])
        self.assertEqual(data["block"], md.stdout.rstrip("\n"))
        self.assertEqual(data["usage"]["global"]["max_lines"], 30)
        self.assertEqual(data["usage"]["project"]["max_lines"], 10)

        show = self.cli("rules", "show")
        self.assertIn("1. Rule one.", show.stdout)
        self.assertIn("1/30 lines", show.stdout)
        self.assertEqual(self.cli("rules", "check").returncode, 0)

        denied = self.cli("write", "user/rules/HARD.md", "- hacked")
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("agents-memory rules", denied.stderr)

        self.assertEqual(self.cli("rules", "edit", "1", "Rule uno.").returncode, 0)
        self.assertEqual(self.cli("rules", "remove", "--project", "demo", "1").returncode, 0)
        md2 = self.cli("context", "--project", "demo")
        self.assertEqual(md2.stdout, "<memory_rules>\n- Rule uno.\n</memory_rules>\n")

        over = "".join(f"- R{i}\n" for i in range(31))
        res = self.cli("rules", "set", stdin=over)
        self.assertEqual(res.returncode, 1)
        self.assertIn("Consolidate", res.stderr)
        self.assertEqual((self.mem / "rules" / "HARD.md").read_text(encoding="utf-8").count("- "), 1)

    def test_help_json_lists_rule_commands(self) -> None:
        spec = json.loads(self.cli("--help-json").stdout)
        self.assertIn("context", spec["commands"])
        fmt = [o for o in spec["commands"]["context"]["options"] if o["dest"] == "fmt"][0]
        self.assertEqual(fmt["choices"], ["md", "json"])
        self.assertIn("add", spec["commands"]["rules"]["subcommands"])


if __name__ == "__main__":
    unittest.main()
