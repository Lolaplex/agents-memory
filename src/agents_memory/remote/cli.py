"""CLI subcommands for remote cloud memory sync and server."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from .. import __version__
from ..store import USER_MEMORY, merge_agent_mcp, merge_zed_mcp, sync_injection
from .client import (
    board_attach,
    clear_remote_config,
    get_remote_config,
    main_bridge,
    remote_health_check,
    remote_pull,
    remote_push_merge,
    save_remote_config,
    verify_remote_tool_api,
)
from .server import run_server


def build_remote_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agents-memory remote",
        description="Remote cloud memory sync and multi-device coordination.",
    )
    subparsers = parser.add_subparsers(dest="remote_cmd", help="Remote commands")

    # serve
    serve_p = subparsers.add_parser("serve", help="Start remote memory server")
    serve_p.add_argument("--host", default="0.0.0.0", help="Host address (default: 0.0.0.0)")
    serve_p.add_argument("--port", "-p", type=int, default=8443, help="Port (default: 8443)")
    serve_p.add_argument("--token", "-t", default="", help="Bearer token secret (or AGENTS_MEMORY_TOKEN env)")
    serve_p.add_argument("--log-level", default="info", help="Log level (debug, info, warning)")

    # connect
    connect_p = subparsers.add_parser("connect", help="Connect local machine to remote memory server")
    connect_p.add_argument("url", help="Remote server URL (e.g. https://memory.example.com or http://vps:8443)")
    connect_p.add_argument("--token", "-t", default="", help="Authentication token")
    connect_p.add_argument("--merge", "-m", action="store_true", default=True, help="Merge local memory into remote (default: True)")
    connect_p.add_argument("--pull-only", action="store_true", help="Do not upload local files; pull remote state only")
    connect_p.add_argument("--no-auto-pull", action="store_true", help="Do not auto-pull prompt files on client bridge start")
    connect_p.add_argument("--insecure", "-k", action="store_true", help="Allow self-signed or unverified TLS certificates")

    # disconnect
    disconnect_p = subparsers.add_parser("disconnect", help="Disconnect from remote server and restore local mode")

    # status
    status_p = subparsers.add_parser("status", help="Show remote connection status")

    # push
    push_p = subparsers.add_parser("push", help="Push and merge local memory into remote server")

    # pull
    pull_p = subparsers.add_parser("pull", help="Pull latest memory snapshot from remote server")

    # client
    client_p = subparsers.add_parser("client", help="Run stdio-to-remote MCP bridge")
    client_p.add_argument("--url", help="Override remote server URL")
    client_p.add_argument("--token", help="Override authentication token")

    attach_p = subparsers.add_parser(
        "attach",
        help="Attach a board project memory tree as an extra root (does not replace local USER.md)",
    )
    attach_p.add_argument(
        "url",
        help="Board memory URL, e.g. https://board.lolaplex.org/projects/cyplex/memory",
    )
    attach_p.add_argument("--token", "-t", default="", help="Board bearer token (lpb_…)")
    attach_p.add_argument(
        "--dir",
        default="",
        help="Local directory (default: ~/.agents/board-memory/<slug>)",
    )
    attach_p.add_argument("--insecure", "-k", action="store_true", help="Skip TLS verify")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args_list = list(argv if argv is not None else sys.argv[1:])
    parser = build_remote_parser()

    if not args_list or args_list[0] in ("-h", "--help", "help"):
        parser.print_help()
        return 0

    args = parser.parse_args(args_list)
    cmd = args.remote_cmd

    if cmd == "serve":
        run_server(
            host=args.host,
            port=args.port,
            token=args.token,
            log_level=args.log_level,
        )
        return 0

    elif cmd == "connect":
        url = args.url.strip().rstrip("/")
        token = args.token.strip()
        verify_ssl = not args.insecure

        print(f"Connecting to remote memory at {url}...")
        try:
            health = remote_health_check(url, token=token, verify_ssl=verify_ssl)
            print(f"Connection OK! Remote running agents-memory v{health.get('version', '?')}")
            print(f"Remote files in store: {health.get('files_count', 0)}")
            try:
                verify_remote_tool_api(url, token=token, verify_ssl=verify_ssl)
                print("Mirror sync API: OK (/api/v1/merge + /api/v1/snapshot)")
            except Exception as e:
                print(
                    f"WARNING: Remote server may need upgrade ({e}). "
                    "Deploy latest agents-memory on the server for full mirror sync.",
                    file=sys.stderr,
                )
        except PermissionError:
            print("ERROR: Authentication failed. Please provide a valid --token.", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"ERROR: Could not connect to remote server: {e}", file=sys.stderr)
            return 1

        if args.pull_only:
            print("Pulling remote memory snapshot...")
            res = remote_pull(url, token=token, verify_ssl=verify_ssl)
            print(f"Pulled {res.get('total_files', 0)} files.")
        else:
            print("Performing deterministic multi-device merge...")
            res = remote_push_merge(url, token=token, verify_ssl=verify_ssl)
            report = res.get("server_report", {})
            print(
                f"Merge complete: {len(report.get('added', []))} added, "
                f"{len(report.get('merged', []))} merged, "
                f"{len(report.get('unchanged', []))} unchanged."
            )

        # Save config
        save_remote_config(
            url=url,
            token=token,
            auto_pull=not args.no_auto_pull,
            extra={"verify_ssl": verify_ssl},
        )
        print(f"Saved remote config to {USER_MEMORY / 'remote_config.json'}")

        # Update host MCP configs to point to client bridge
        merge_agent_mcp()
        merge_zed_mcp()
        sync_injection()

        print("\nSUCCESS: Connected to remote agents-memory!")
        print("Mirror sync enabled: all MCP tools local; cloud holds merged mirror bundle.")
        print("IDE MCP entry: python -m agents_memory.remote.sync_mcp")
        print("Please reload your Agent / IDE window.")
        return 0

    elif cmd == "disconnect":
        cfg = get_remote_config()
        if not cfg:
            print("Not connected to any remote memory server (already in local mode).")
            return 0

        url = cfg.get("url", "")
        token = cfg.get("token", "")
        print(f"Disconnecting from {url}...")

        try:
            print("Pulling final snapshot to ensure local files are up-to-date...")
            remote_pull(url, token=token)
        except Exception as e:
            print(f"Warning: Could not pull latest snapshot ({e}). Proceeding with disconnect.")

        clear_remote_config()
        # Restore local MCP configs
        merge_agent_mcp()
        merge_zed_mcp()
        sync_injection()

        print("\nSUCCESS: Disconnected from remote memory.")
        print("Restored local stdio mode. Please reload your Agent / IDE window.")
        return 0

    elif cmd == "status":
        cfg = get_remote_config()
        if not cfg:
            print("Mode: LOCAL (No remote cloud server configured)")
            print(f"Local Store: {USER_MEMORY}")
            return 0

        url = cfg.get("url", "")
        token = cfg.get("token", "")
        print(f"Mode: REMOTE CLOUD SYNC")
        print(f"Server URL : {url}")
        print(f"Token      : {'***' if token else 'NONE'}")
        print(f"Last Saved : {cfg.get('updated_at', 'unknown')}")

        print("\nChecking server health...")
        try:
            health = remote_health_check(url, token=token)
            print(f"Server Status : ONLINE (v{health.get('version', '?')})")
            print(f"Remote Files  : {health.get('files_count', 0)}")
        except Exception as e:
            print(f"Server Status : OFFLINE / ERROR ({e})")
        return 0

    elif cmd == "push":
        cfg = get_remote_config()
        if not cfg:
            print("Error: Not connected to a remote server. Run 'agents-memory remote connect <URL>' first.", file=sys.stderr)
            return 1
        url = cfg.get("url", "")
        token = cfg.get("token", "")
        print(f"Pushing and merging local memory to {url}...")
        try:
            res = remote_push_merge(url, token=token)
            report = res.get("server_report", {})
            print(
                f"Push & Merge complete: {len(report.get('added', []))} added, "
                f"{len(report.get('merged', []))} merged, "
                f"{len(report.get('unchanged', []))} unchanged."
            )
            return 0
        except Exception as e:
            print(f"Error pushing memory: {e}", file=sys.stderr)
            return 1

    elif cmd == "pull":
        cfg = get_remote_config()
        if not cfg:
            print("Error: Not connected to a remote server. Run 'agents-memory remote connect <URL>' first.", file=sys.stderr)
            return 1
        url = cfg.get("url", "")
        token = cfg.get("token", "")
        print(f"Pulling latest memory snapshot from {url}...")
        try:
            res = remote_pull(url, token=token)
            report = res.get("report", {})
            print(
                f"Pull complete: {len(report.get('added', []))} added, "
                f"{len(report.get('merged', []))} merged, "
                f"{len(report.get('unchanged', []))} unchanged."
            )
            return 0
        except Exception as e:
            print(f"Error pulling memory: {e}", file=sys.stderr)
            return 1

    elif cmd == "client":
        return main_bridge()

    elif cmd == "attach":
        url = args.url.strip().rstrip("/")
        token = args.token.strip()
        dest = Path(args.dir).expanduser() if args.dir else None
        print(f"Attaching board memory at {url} (local store stays the personal root)...")
        try:
            res = board_attach(url, token=token, dest_dir=dest, verify_ssl=not args.insecure)
        except PermissionError:
            print("ERROR: Authentication failed. Pass a valid --token (lpb_…).", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"ERROR: Could not attach board memory: {e}", file=sys.stderr)
            return 1
        report = res.get("report", {})
        print(f"Wrote extra root {res.get('dir')}")
        print(
            f"Files: {len(report.get('added', []))} added, "
            f"{len(report.get('merged', []))} merged, "
            f"{len(report.get('skipped', []))} skipped (personal paths)."
        )
        print("This does not switch MCP to remote connect.")
        return 0

    parser.print_help()
    return 0
