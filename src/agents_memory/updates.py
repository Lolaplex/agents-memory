"""Lightweight, non-blocking PyPI update check for CLI / MCP entrypoints."""
from __future__ import annotations

import functools
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

_TRUTHY = ("1", "true", "yes", "on")
_CI_KEYS = (
    "CI",
    "CONTINUOUS_INTEGRATION",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "TF_BUILD",
    "BUILDKITE",
    "CIRCLECI",
)

# Process-local: one MCP PyPI check (and at most one notice) per package.
_mcp_checked: set[str] = set()


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def disabled() -> bool:
    if _env_truthy("AGENTS_NO_UPDATE_CHECK"):
        return True
    return any(_env_truthy(k) for k in _CI_KEYS)


def _parse_version(v: str) -> tuple[int, ...]:
    clean = v.lstrip("v").split("+")[0].split("-")[0]
    try:
        return tuple(int(x) for x in clean.split(".") if x.isdigit())
    except Exception:
        return (0,)


def _cache_file(package_name: str) -> Path:
    override = os.environ.get("AGENTS_HOME")
    if override:
        base = Path(override).expanduser().resolve() / "cache"
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        base = (
            Path(xdg).expanduser().resolve() / "agents"
            if xdg
            else Path.home() / ".cache" / "agents"
        )
    return base / f"updates-{package_name}.json"


def format_notice(package_name: str, current: str, latest: str) -> str:
    return (
        f"{package_name} {latest} available (you have {current}): "
        f"uv tool upgrade {package_name}"
    )


def latest_available(
    package_name: str,
    current_version: str,
    *,
    cache_ttl_sec: int = 86400,
    timeout: float = 1.0,
) -> str | None:
    """Return a newer PyPI version, or None. Cached ~24h; silent on failure."""
    if disabled():
        return None

    now = time.time()
    cache_file = _cache_file(package_name)
    latest_version: str | None = None
    last_checked = 0.0
    try:
        if cache_file.is_file():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            last_checked = float(data.get("last_checked") or 0)
            latest_version = data.get("latest_version") or None
    except Exception:
        latest_version = None

    if latest_version and (now - last_checked) < cache_ttl_sec:
        if _parse_version(latest_version) > _parse_version(current_version):
            return str(latest_version)
        return None

    try:
        req = urllib.request.Request(
            f"https://pypi.org/pypi/{package_name}/json",
            headers={"User-Agent": f"{package_name}/{current_version} (update-check)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        latest_version = payload.get("info", {}).get("version")
        if not latest_version:
            return None
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps(
                {"last_checked": int(now), "latest_version": latest_version},
                indent=2,
            ),
            encoding="utf-8",
        )
        if _parse_version(latest_version) > _parse_version(current_version):
            return str(latest_version)
    except Exception:
        pass
    return None


def check_for_updates(
    package_name: str,
    current_version: str,
    cache_ttl_sec: int = 86400,
    timeout: float = 1.0,
) -> None:
    """CLI: print one stderr line if a newer PyPI release exists. Never touches stdout."""
    latest = latest_available(
        package_name,
        current_version,
        cache_ttl_sec=cache_ttl_sec,
        timeout=timeout,
    )
    if latest:
        sys.stderr.write(format_notice(package_name, current_version, latest) + "\n")
        sys.stderr.flush()


def mcp_update_notice(
    package_name: str,
    current_version: str,
    cache_ttl_sec: int = 86400,
    timeout: float = 1.0,
) -> str:
    """One-line notice for the first MCP tool response this process; else empty."""
    if package_name in _mcp_checked:
        return ""
    _mcp_checked.add(package_name)
    latest = latest_available(
        package_name,
        current_version,
        cache_ttl_sec=cache_ttl_sec,
        timeout=timeout,
    )
    if not latest:
        return ""
    return format_notice(package_name, current_version, latest)


def attach_mcp_update_notice(mcp: object, package_name: str, current_version: str) -> None:
    """Wrap future ``add_tool`` registrations so the first str result may get a notice.

    Call once right after ``FastMCP(...)`` and before ``@mcp.tool()`` decorators.
    """
    original = mcp.add_tool  # type: ignore[attr-defined]

    def add_tool(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        @functools.wraps(fn)
        def wrapped(*a, **kw):
            result = fn(*a, **kw)
            if isinstance(result, str):
                notice = mcp_update_notice(package_name, current_version)
                if notice and not result.startswith(notice):
                    return f"{notice}\n\n{result}"
            return result

        return original(wrapped, *args, **kwargs)

    mcp.add_tool = add_tool  # type: ignore[method-assign]
