"""Local markdown memory — reference implementation of the agent-memory ABI."""
from __future__ import annotations

from pathlib import Path

__all__ = ["ROOT", "__version__"]


def _engine_root() -> Path:
    here = Path(__file__).resolve().parent
    for path in [here, *here.parents]:
        if (path / "abi" / "VERSION").is_file():
            return path
    return here.parents[2]


ROOT = _engine_root()
__version__ = (ROOT / "abi" / "VERSION").read_text(encoding="utf-8").strip()
