#!/usr/bin/env python3
"""dev-suite.py — one dev switch for the whole agents-* suite.

Reads pyproject.toml (the only dep list — it cannot drift) and installs
every ``agents-*`` requirement from source, never from PyPI:

  - a sibling checkout exists (``<repo-parent>/agents-*``) → ``pip install -e``
    so uncommitted local work flows through — true lock-step with dev work
  - no sibling → ``pip install "name @ git+https://github.com/Lolaplex/<name>.git@<ref>"``
    (in CI, probes GITHUB_HEAD_REF first so multi-repo feature branches resolve
    against matching remote branches before falling back to SUITE_REF / dev)

Usage:

    python scripts/dev-suite.py            # install the suite from source
    python scripts/dev-suite.py --emit     # print git-ref requirement lines
    python scripts/dev-suite.py --dry-run  # show what would run

Env:

    SUITE_REF          default git ref (default: dev) — same name the
                       Dockerfile ARG and self-deploy.sh use
    <NAME>_REF         per-package override, dashes → underscores
                       (e.g. RELAY_REF=main for agents-relay) — same names
                       the Dockerfile ARGs use
    AGENTS_SUITE_DIR   directory holding sibling checkouts
                       (default: parent of this repo)

``--emit`` always prints the git-URL form for every dep — the Dockerfile
consumes it (images have no sibling checkouts but keep the per-package
ARG override surface).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

REPO = Path(__file__).resolve().parent.parent
DEP_RE = re.compile(r"^(agents-[\w-]+)(\[[^\]]+\])?")
GIT_URL = "git+https://github.com/Lolaplex/{name}.git@{ref}"


def _read_dependencies(text: str) -> list[str]:
    if tomllib is not None:
        return list(tomllib.loads(text).get("project", {}).get("dependencies", []))
    in_project = False
    collecting = False
    deps: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r'#(?=(?:[^"\']*["\'][^"\']*["\'])*[^"\']*$).*$', "", raw).strip()
        if not line:
            continue
        if line.startswith("[") and not collecting:
            in_project = line == "[project]"
            continue
        if not in_project:
            continue
        if not collecting:
            m = re.match(r"dependencies\s*=\s*\[(.*)", line)
            if m:
                rest = m.group(1)
                deps.extend(re.findall(r'["\']([^"\']+)["\']', rest))
                collecting = "]" not in rest
        else:
            deps.extend(re.findall(r'["\']([^"\']+)["\']', line))
            if "]" in line:
                collecting = False
                break
    return deps


def suite_deps() -> list[tuple[str, str]]:
    """(name, extras) for every agents-* dependency in pyproject.toml."""
    pyproject = REPO / "pyproject.toml"
    if not pyproject.is_file():
        return []
    deps = _read_dependencies(pyproject.read_text(encoding="utf-8"))
    out = []
    for dep in deps:
        m = DEP_RE.match(dep)
        if m:
            out.append((m.group(1), m.group(2) or ""))
    return out


def _explicit_ref(name: str) -> str:
    full = name.upper().replace("-", "_") + "_REF"
    short = name.removeprefix("agents-").upper().replace("-", "_") + "_REF"
    for key in (full, short):
        val = os.environ.get(key)
        if val:
            return val
    return ""


def ref_for(name: str) -> str:
    exp = _explicit_ref(name)
    if exp:
        return exp
    return os.environ.get("SUITE_REF") or "dev"


def _remote_branch_exists(name: str, ref: str) -> bool:
    url = f"https://github.com/Lolaplex/{name}.git"
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--heads", url, ref],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def resolve_remote_ref(name: str) -> str | None:
    """Pick the first reachable remote branch for ``name`` (or None if unreachable)."""
    candidates: list[str] = []
    exp = _explicit_ref(name)
    if exp:
        candidates.append(exp)
    suite_ref = os.environ.get("SUITE_REF", "").strip()
    if suite_ref and suite_ref not in candidates:
        candidates.append(suite_ref)
    gh_head = os.environ.get("GITHUB_HEAD_REF", "").strip()
    if gh_head and gh_head != "main" and gh_head not in candidates:
        candidates.append(gh_head)
    if "dev" not in candidates:
        candidates.append("dev")
    for cand in candidates:
        if _remote_branch_exists(name, cand):
            return cand
    return None


def git_req(name: str, extras: str, ref: str | None = None) -> str:
    chosen = ref or ref_for(name)
    return f"{name}{extras} @ {GIT_URL.format(name=name, ref=chosen)}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit", action="store_true", help="print git-ref requirements and exit")
    ap.add_argument("--dry-run", action="store_true", help="print the pip command and exit")
    args = ap.parse_args()

    deps = suite_deps()
    if args.emit:
        for name, extras in deps:
            print(git_req(name, extras))
        return 0

    if not deps:
        print("dev-suite: no agents-* dependencies in pyproject.toml")
        return 0

    suite_dir = Path(os.environ.get("AGENTS_SUITE_DIR", REPO.parent))
    reqs, plan = [], []
    for name, extras in deps:
        sibling = suite_dir / name
        if (sibling / "pyproject.toml").is_file():
            reqs += ["-e", f"{sibling}{extras}"]
            plan.append(f"{name}{extras}: editable {sibling}")
        else:
            chosen = ref_for(name) if args.dry_run else resolve_remote_ref(name)
            if chosen:
                reqs.append(git_req(name, extras, chosen))
                plan.append(f"{name}{extras}: git@{chosen} (no sibling in {suite_dir})")
            else:
                plan.append(f"{name}{extras}: fallback to index (remote branch unreachable)")

    print("\n".join(plan))
    if not reqs:
        return 0
    cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir", *reqs]
    if args.dry_run:
        print("$ " + " ".join(cmd))
        return 0
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
