"""Local markdown memory — reference implementation of the agents-memory ABI."""
from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["ROOT", "__version__", "PACKAGE_DIR"]

PACKAGE_DIR = Path(__file__).resolve().parent


def _engine_root() -> Path:
    here = PACKAGE_DIR
    for path in [here, *here.parents]:
        if (path / "abi" / "VERSION").is_file():
            return path
    return here


ROOT = _engine_root()


def _resolve_version() -> str:
    # 1. Source checkout: abi/VERSION
    if (ROOT / "abi" / "VERSION").is_file():
        return (ROOT / "abi" / "VERSION").read_text(encoding="utf-8").strip()
    # 2. Bundled resource: bundled/abi/VERSION
    bundled_version = PACKAGE_DIR / "bundled" / "abi" / "VERSION"
    if bundled_version.is_file():
        return bundled_version.read_text(encoding="utf-8").strip()
    # 3. Installed package metadata
    try:
        from importlib.metadata import version
        return version("agents-memory")
    except Exception:
        pass
    return "1.0.0"


__version__ = _resolve_version()
