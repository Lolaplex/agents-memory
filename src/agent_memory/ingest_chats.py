"""Build ~/.agents/memory/chats-index.md — thin wrapper around ingest catalog phase."""
from __future__ import annotations

from .ingest_catalog import run_catalog


def main() -> int:
    result = run_catalog()
    print(f"wrote {result['chats_index']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
