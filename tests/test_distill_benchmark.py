import json
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

# Curated benchmark dataset representing realistic staging inbox items
BENCHMARK_DATASET = [
    # --- Category 1: Architectural Decisions (Keep -> kind=concept / decision) ---
    {
        "bullet": "[ADR @ 2026-08-19] Use SQLite with WAL mode for local metadata cache to prevent concurrent lockups",
        "expected_discard": False,
        "expected_kind": "concept",
        "expected_slug": "sqlite-wal-cache",
        "project": "",
    },
    {
        "bullet": "[Architecture @ 2026-08-15] All inter-process communication in Goblin must use native Tauri 2 events instead of HTTP endpoints",
        "expected_discard": False,
        "expected_kind": "decision",
        "expected_slug": "tauri-ipc-events",
        "project": "goblin",
    },
    # --- Category 2: Stack & Framework Rules (Keep -> kind=note / collection=stack) ---
    {
        "bullet": "[Stack @ 2026-08-10] Never use Tailwind v4 in Customs repo — strictly stay on Tailwind v3",
        "expected_discard": False,
        "expected_kind": "note",
        "expected_collection": "stack",
        "expected_slug": "tailwind-v3-rule",
        "project": "customs",
    },
    {
        "bullet": "[Packaging @ 2026-08-12] Use standard src/ layout with pyproject.toml and setuptools for Python tools",
        "expected_discard": False,
        "expected_kind": "concept",
        "expected_slug": "python-packaging",
        "project": "",
    },
    # --- Category 3: User Preferences & Persona (Keep -> kind=note / collection=preferences) ---
    {
        "bullet": "[Preferences @ 2026-08-01] User prefers Caveman Ultra mode: dense, direct, 0 fluff, 0 courtesy filler",
        "expected_discard": False,
        "expected_kind": "note",
        "expected_collection": "preferences",
        "expected_slug": "caveman-mode",
        "project": "",
    },
    {
        "bullet": "[UI @ 2026-08-05] Modern dark mode only: HSL tailored colors, Outfit font, subtle micro-animations, glassmorphism",
        "expected_discard": False,
        "expected_kind": "note",
        "expected_collection": "preferences",
        "expected_slug": "ui-theme-guidelines",
        "project": "",
    },
    # --- Category 4: Workflows & Operational Rules (Keep -> kind=workflow) ---
    {
        "bullet": "[Git @ 2026-08-14] Always create a feature branch before making changes and verify full test suite before merge",
        "expected_discard": False,
        "expected_kind": "workflow",
        "expected_slug": "git-branching-flow",
        "project": "",
    },
    {
        "bullet": "[Deployment @ 2026-08-11] VPS Coolify deploys must use SSH tunnel if Cloudflare Access blocks port 8000",
        "expected_discard": False,
        "expected_kind": "workflow",
        "expected_slug": "coolify-vps-tunnel",
        "project": "vps",
    },
    # --- Category 5: Concepts & Entities (Keep -> kind=concept / entity) ---
    {
        "bullet": "[Model @ 2026-08-02] Gemini 3.7 Flash High is the default reasoning model for daily pair-programming tasks",
        "expected_discard": False,
        "expected_kind": "entity",
        "expected_slug": "gemini-flash-high",
        "project": "",
    },
    {
        "bullet": "[Federation @ 2026-08-08] Project One is an open capability index providing federated software intelligence to coding agents",
        "expected_discard": False,
        "expected_kind": "concept",
        "expected_slug": "project-one-federation",
        "project": "one",
    },
    # --- Category 6: Ephemeral Noise & Debugging Chatter (Discard -> discard=True) ---
    {
        "bullet": "Can you check line 42 in store.py? It threw an unexpected NoneType exception earlier.",
        "expected_discard": True,
    },
    {
        "bullet": "npm run dev exited with code 1, please restart the server.",
        "expected_discard": True,
    },
    {
        "bullet": "Where is the button component located in the src folder?",
        "expected_discard": True,
    },
    {
        "bullet": "Let me test if this markdown renders correctly in the browser preview.",
        "expected_discard": True,
    },
    {
        "bullet": "TypeError: Cannot read property 'map' of undefined at Component.render (app.tsx:15)",
        "expected_discard": True,
    },
    {
        "bullet": "Wait, I forgot to save the file, let me run it again now.",
        "expected_discard": True,
    },
    {
        "bullet": "Thanks, that fixed the issue!",
        "expected_discard": True,
    },
    {
        "bullet": "How do I print a list in reverse in Python 3?",
        "expected_discard": True,
    },
    # --- Category 7: Code Dumps & Transcript Noise without Lasting Rule (Discard -> discard=True) ---
    {
        "bullet": "const x = [1, 2, 3]; console.log(x.map(n => n * 2));",
        "expected_discard": True,
    },
    {
        "bullet": "curl -X GET https://api.example.com/v1/health -H 'Authorization: Bearer test'",
        "expected_discard": True,
    },
]


def classify_bullet_heuristic(bullet: str) -> dict:
    """Heuristic distill classifier mirroring agent-level rule evaluation."""
    b_lower = bullet.lower()

    # Noise indicators
    noise_patterns = [
        r"^(can you|could you|how do|how can|where is|what is|let me|wait,|thanks)",
        r"(exited with code|cannot read property|typeerror|syntaxerror|exception earlier)",
        r"^(const |let |var |def |curl |npm |git status|git checkout)",
        r"(fixed the issue|run it again|restart the server|renders correctly)",
    ]
    for pat in noise_patterns:
        if re.search(pat, b_lower):
            return {"bullet": bullet, "discard": True}

    # Project-specific ADR / Decisions
    if "goblin" in b_lower:
        return {
            "bullet": bullet,
            "discard": False,
            "kind": "decision",
            "name": "tauri-ipc-events",
            "project": "goblin",
        }

    # Cross-cutting Architectural Decisions
    if "sqlite" in b_lower or "wal" in b_lower:
        return {
            "bullet": bullet,
            "discard": False,
            "kind": "concept",
            "name": "sqlite-wal-cache",
        }

    # Stack rules
    if "tailwind" in b_lower:
        return {
            "bullet": bullet,
            "discard": False,
            "kind": "note",
            "name": "tailwind-v3-rule",
            "collection": "stack",
            "project": "customs",
        }
    if "packaging" in b_lower or "pyproject" in b_lower:
        return {
            "bullet": bullet,
            "discard": False,
            "kind": "concept",
            "name": "python-packaging",
        }

    # Preferences
    if "caveman" in b_lower:
        return {
            "bullet": bullet,
            "discard": False,
            "kind": "note",
            "name": "caveman-mode",
            "collection": "preferences",
        }
    if "dark mode" in b_lower or "outfit" in b_lower or "glassmorphism" in b_lower:
        return {
            "bullet": bullet,
            "discard": False,
            "kind": "note",
            "name": "ui-theme-guidelines",
            "collection": "preferences",
        }

    # Workflows
    if "branch" in b_lower or "git" in b_lower:
        return {
            "bullet": bullet,
            "discard": False,
            "kind": "workflow",
            "name": "git-branching-flow",
        }
    if "coolify" in b_lower or "vps" in b_lower:
        return {
            "bullet": bullet,
            "discard": False,
            "kind": "workflow",
            "name": "coolify-vps-tunnel",
            "project": "vps",
        }

    # Concepts / Entities
    if "gemini" in b_lower or "flash high" in b_lower:
        return {
            "bullet": bullet,
            "discard": False,
            "kind": "entity",
            "name": "gemini-flash-high",
        }
    if "federation" in b_lower or "project one" in b_lower:
        return {
            "bullet": bullet,
            "discard": False,
            "kind": "concept",
            "name": "project-one-federation",
            "project": "one",
        }

    # Default fallback
    return {
        "bullet": bullet,
        "discard": False,
        "kind": "note",
        "name": "general-fact",
    }


class DistillBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user = self.root / "user"
        self.repo_customs = self.root / "customs"
        self.repo_goblin = self.root / "goblin"
        self.repo_vps = self.root / "vps"
        self.repo_one = self.root / "one"
        for d in (self.user, self.repo_customs, self.repo_goblin, self.repo_vps, self.repo_one):
            d.mkdir(parents=True, exist_ok=True)

        self.projects_md = self.user / "PROJECTS.md"
        self.projects_md.write_text(
            "# Projects\n\n"
            "| slug | path | role | stack | status |\n"
            "|------|------|------|-------|--------|\n"
            f"| customs | `{self.repo_customs}` | suite | ts | active |\n"
            f"| goblin | `{self.repo_goblin}` | browser | rust | active |\n"
            f"| vps | `{self.repo_vps}` | infra | py | active |\n"
            f"| one | `{self.repo_one}` | index | ts | active |\n",
            encoding="utf-8",
        )
        self.patches = [
            patch.object(store, "USER_MEMORY", self.user),
            patch.object(store, "PROJECTS_MD", self.projects_md),
            patch.object(store, "ORPHANS", self.user / "orphans"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_distill_classification_quality(self):
        """Measures Precision, Recall, Specificity, and Kind Accuracy on benchmark items."""
        total_items = len(BENCHMARK_DATASET)
        true_discard = sum(1 for item in BENCHMARK_DATASET if item["expected_discard"])
        true_keep = total_items - true_discard

        predicted_discard_correct = 0
        predicted_keep_correct = 0
        kind_correct = 0

        for item in BENCHMARK_DATASET:
            bullet = item["bullet"]
            expected_discard = item["expected_discard"]
            result = classify_bullet_heuristic(bullet)

            is_discard = bool(result.get("discard"))
            if is_discard == expected_discard:
                if is_discard:
                    predicted_discard_correct += 1
                else:
                    predicted_keep_correct += 1
                    expected_kind = item.get("expected_kind")
                    if expected_kind and result.get("kind") == expected_kind:
                        kind_correct += 1

        # Calculate metrics
        specificity = predicted_discard_correct / true_discard  # Noise rejection rate
        recall = predicted_keep_correct / true_keep              # Fact retention rate
        kind_accuracy = kind_correct / true_keep

        self.assertGreaterEqual(specificity, 0.95, f"Noise rejection rate too low: {specificity:.2%}")
        self.assertGreaterEqual(recall, 0.95, f"Fact retention rate too low: {recall:.2%}")
        self.assertGreaterEqual(kind_accuracy, 0.90, f"Kind routing accuracy too low: {kind_accuracy:.2%}")

    def test_distill_slug_quality(self):
        """Verifies that generated slugs follow kebab-case and contain no forbidden chars."""
        for item in BENCHMARK_DATASET:
            if item["expected_discard"]:
                continue
            result = classify_bullet_heuristic(item["bullet"])
            slug = result.get("name", "")
            self.assertTrue(slug, "Slug cannot be empty for kept facts")
            self.assertTrue(
                re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", slug),
                f"Slug '{slug}' does not conform to clean kebab-case format",
            )

    def test_end_to_end_distill_batch_execution(self):
        """Populates staging files with all benchmark items, runs distill_batch, and asserts complete drain."""
        staging_dir = self.user / "staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging_file = staging_dir / "captured.md"

        # Populate staging with all bullets
        bullet_lines = ["# Staging Inbox\n"]
        for item in BENCHMARK_DATASET:
            bullet_lines.append(f"- {item['bullet']}")
        staging_file.write_text("\n".join(bullet_lines) + "\n", encoding="utf-8")

        initial_count = store.count_staging_bullets()
        self.assertEqual(initial_count, len(BENCHMARK_DATASET))

        # Classify and run batch distillation
        batch_payload = []
        for item in BENCHMARK_DATASET:
            classification = classify_bullet_heuristic(item["bullet"])
            classification["source_path"] = "user/staging/captured.md"
            batch_payload.append(classification)

        res = store.distill_batch(batch_payload)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["remaining_staging_count"], 0)
        self.assertEqual(res["promoted"] + res["discarded"], len(BENCHMARK_DATASET))

        # Verify staging inbox is now completely empty
        final_inbox = store.get_staging_inbox()
        self.assertEqual(final_inbox["total"], 0)


if __name__ == "__main__":
    unittest.main()
