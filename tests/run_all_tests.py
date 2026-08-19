#!/usr/bin/env python3
"""Master test runner & distill evaluation benchmark for agent-memory."""
from __future__ import annotations

import os
import sys
import time
import unittest
from io import StringIO
from pathlib import Path

# Bootstrap src/ and tests/ on sys.path
ROOT = Path(__file__).resolve().parents[1]
_SRC = str(ROOT / "src")
_TESTS = str(ROOT / "tests")
for p in (str(ROOT), _SRC, _TESTS):
    if p not in sys.path:
        sys.path.insert(0, p)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run_full_suite() -> bool:
    print("=" * 70)
    print("  AGENT-MEMORY COMPREHENSIVE TEST SUITE & BENCHMARK")
    print("=" * 70)
    print(f"Repository Root: {ROOT}")
    print(f"Python Runtime : {sys.executable} (v{sys.version.split()[0]})")
    print("-" * 70)

    start_time = time.time()

    # Discover and run all unit, CLI, MCP, Ingest, and Distill tests
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(ROOT / "tests"), pattern="test_*.py")

    stream = StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = runner.run(suite)
    elapsed = time.time() - start_time

    # Parse details from test results
    total_tests = result.testsRun
    failed = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped)
    passed = total_tests - failed - errors - skipped

    print("\n[1] FEATURE TEST MATRIX")
    print("-" * 70)
    print(f"  Total Test Cases : {total_tests}")
    print(f"  Passed           : {passed} [OK]")
    if failed:
        print(f"  Failures         : {failed} [FAIL]")
    if errors:
        print(f"  Errors           : {errors} [ERR]")
    if skipped:
        print(f"  Skipped          : {skipped}")
    print(f"  Duration         : {elapsed:.3f}s")
    print("-" * 70)

    # Print any failure details
    if result.failures:
        print("\nFAILURES:")
        for test, trace in result.failures:
            print(f"- {test}:\n{trace}")
    if result.errors:
        print("\nERRORS:")
        for test, trace in result.errors:
            print(f"- {test}:\n{trace}")

    # Run Benchmark Evaluation
    print("\n[2] DISTILL & AUTO-TRIGGERING BENCHMARK REPORT")
    print("-" * 70)
    from tests.test_distill_benchmark import BENCHMARK_DATASET, classify_bullet_heuristic
    from tests.test_auto_triggering import match_skill_intent

    # Evaluate Distill Quality
    total_samples = len(BENCHMARK_DATASET)
    true_discard = sum(1 for item in BENCHMARK_DATASET if item["expected_discard"])
    true_keep = total_samples - true_discard

    correct_discard = 0
    correct_keep = 0
    correct_kind = 0

    for item in BENCHMARK_DATASET:
        res = classify_bullet_heuristic(item["bullet"])
        is_discard = bool(res.get("discard"))
        if is_discard == item["expected_discard"]:
            if is_discard:
                correct_discard += 1
            else:
                correct_keep += 1
                if item.get("expected_kind") and res.get("kind") == item["expected_kind"]:
                    correct_kind += 1

    noise_rejection = correct_discard / true_discard if true_discard else 1.0
    fact_retention = correct_keep / true_keep if true_keep else 1.0
    kind_routing = correct_kind / true_keep if true_keep else 1.0
    overall_distill_score = (noise_rejection + fact_retention + kind_routing) / 3.0

    print(f"  Dataset Size              : {total_samples} samples")
    print(f"  Noise Rejection Rate      : {noise_rejection * 100:.1f}% ({correct_discard}/{true_discard})")
    print(f"  Fact Retention Rate       : {fact_retention * 100:.1f}% ({correct_keep}/{true_keep})")
    print(f"  Kind Routing Precision    : {kind_routing * 100:.1f}% ({correct_kind}/{true_keep})")
    print(f"  Distill Composite Score   : {overall_distill_score * 100:.1f}%")

    # Evaluate Auto-Triggering Intent Classification
    trigger_cases = [
        ("Kannst du die Staging Inbox aufräumen?", "memory-distill"),
        ("Bitte einmal memory-distill durchlaufen lassen", "memory-distill"),
        ("Mach mal eine Bestandsaufnahme", "memory-sync"),
        ("Ich habe ein neues Repo angelegt", "memory-sync"),
        ("Suche in memory nach SQLite Cache", "search_memory"),
        ("Fix line 40 in test_store.py", "none"),
    ]
    correct_triggers = sum(
        1 for prompt, expected in trigger_cases if match_skill_intent(prompt) == expected
    )
    trigger_score = correct_triggers / len(trigger_cases)
    print(f"  Intent Trigger Accuracy   : {trigger_score * 100:.1f}% ({correct_triggers}/{len(trigger_cases)})")

    print("-" * 70)
    all_green = result.wasSuccessful() and overall_distill_score >= 0.95 and trigger_score >= 0.95
    status_label = "ALL CHECKS PASSED [READY FOR MERGE]" if all_green else "SOME CHECKS FAILED"
    print(f"  Final Verdict: {status_label}")
    print("=" * 70)

    return all_green


if __name__ == "__main__":
    success = run_full_suite()
    sys.exit(0 if success else 1)
