"""Lightweight, non-blocking PyPI update check for CLI entrypoints."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path


def _parse_version(v: str) -> tuple[int, ...]:
    clean = v.lstrip("v").split("+")[0].split("-")[0]
    try:
        return tuple(int(x) for x in clean.split(".") if x.isdigit())
    except Exception:
        return (0,)


def check_for_updates(
    package_name: str,
    current_version: str,
    cache_ttl_sec: int = 86400,
    timeout: float = 0.8,
) -> None:
    """Check PyPI for newer versions. Cached for 24h, non-blocking, fails silently."""
    if os.environ.get("AGENTS_NO_UPDATE_CHECK", "").strip().lower() in ("1", "true", "yes"):
        return

    override_dir = os.environ.get("AGENTS_HOME")
    agents_dir = Path(override_dir).expanduser().resolve() if override_dir else (Path.home() / ".agents")
    cache_dir = agents_dir / "cache"
    cache_file = cache_dir / "updates.json"
    now = time.time()
    cache: dict[str, dict] = {}

    try:
        if cache_file.is_file():
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        cache = {}

    pkg_entry = cache.get(package_name, {})
    last_checked = pkg_entry.get("last_checked", 0)
    latest_version = pkg_entry.get("latest_version")

    # If cache is fresh, check if cached latest is newer
    if (now - last_checked < cache_ttl_sec) and latest_version:
        if _parse_version(latest_version) > _parse_version(current_version):
            _print_notice(package_name, current_version, latest_version)
        return

    # Cache expired or missing -> query PyPI with short timeout
    try:
        req = urllib.request.Request(
            f"https://pypi.org/pypi/{package_name}/json",
            headers={"User-Agent": f"{package_name}/{current_version} (update-check)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latest_version = data.get("info", {}).get("version")

        if latest_version:
            cache[package_name] = {
                "last_checked": int(now),
                "latest_version": latest_version,
            }
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")

            if _parse_version(latest_version) > _parse_version(current_version):
                _print_notice(package_name, current_version, latest_version)
    except Exception:
        # Network down, offline, timeout, or PyPI error -> silently ignore
        pass


def _print_notice(pkg: str, cur: str, latest: str) -> None:
    msg = (
        f"\n[notice] A new release of {pkg} is available: {cur} -> {latest}\n"
        f"[notice] To update, run: pip install --upgrade {pkg}\n"
    )
    sys.stderr.write(msg)
    sys.stderr.flush()
