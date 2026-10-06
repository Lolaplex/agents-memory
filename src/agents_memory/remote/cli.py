"""CLI subcommands for remote cloud memory sync and server."""
from __future__ import annotations

import argparse
import os
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
    remote_bump_epoch,
    remote_health_check,
    remote_pull,
    remote_push_merge,
    save_remote_config,
    verify_remote_tool_api,
)
from .sync_bundle import EPOCH_QUESTIONS_REL
from .lock import SyncBusy
from .server import run_server


def format_sync_report(report: dict) -> str:
    if not isinstance(report, dict):
        return "0 added, 0 merged, 0 unchanged."

    if report.get("replaced"):
        user = report.get("user") if isinstance(report.get("user"), dict) else {}
        written = len(user.get("written") or [])
        removed = len(user.get("removed") or [])
        backup = report.get("backup") or ""
        msg = f"replaced: {written} files written, {removed} stale files removed."
        if backup:
            msg += f" Backup: {backup}"
        return msg

    # Flat report format fallback
    if "added" in report or "merged" in report:
        added = len(report.get("added", []))
        merged = len(report.get("merged", []))
        unchanged = len(report.get("unchanged", []))
        return f"{added} added, {merged} merged, {unchanged} unchanged."

    added_count = 0
    merged_count = 0
    unchanged_count = 0

    for sec_key in ("user", "rules", "mirror_store"):
        sec = report.get(sec_key)
        if isinstance(sec, dict):
            added_count += len(sec.get("added", []))
            merged_count += len(sec.get("merged", []))
            unchanged_count += len(sec.get("unchanged", []))

    repos = report.get("repos")
    if isinstance(repos, dict):
        added_count += len(repos.get("applied", []))

    return f"{added_count} added, {merged_count} merged, {unchanged_count} unchanged."


def _print_epoch_questions(res: dict) -> None:
    staged = res.get("staged") if isinstance(res.get("staged"), list) else []
    if not staged:
        return
    print(
        f"Epoch changed: parked {len(staged)} local edit(s) in {EPOCH_QUESTIONS_REL} (not pushed)."
    )
    print("Review with get_staging_inbox, then re-add via add/write if you still want them.")


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
    serve_p.add_argument(
        "--min-client-version",
        default="",
        help="Reject older writers and writers with no version header (env AGENTS_MEMORY_MIN_CLIENT_VERSION)",
    )
    serve_p.add_argument(
        "--update-hint",
        default="",
        help="Install command included in the HTTP 426 body (env AGENTS_MEMORY_UPDATE_HINT)",
    )

    # connect
    connect_p = subparsers.add_parser("connect", help="Connect local machine to remote memory server")
    connect_p.add_argument("url", help="Remote server URL (e.g. https://memory.example.com or http://vps:8443)")
    connect_p.add_argument("--token", "-t", default="", help="Authentication token")
    connect_p.add_argument("--merge", "-m", action="store_true", default=True, help="Merge local memory into remote (default: True)")
    connect_p.add_argument("--pull-only", action="store_true", help="Do not upload local files; pull remote state only")
    connect_p.add_argument(
        "--replace",
        action="store_true",
        help="Replace the local store with the remote snapshot (backup first; no merge)",
    )
    connect_p.add_argument("--no-auto-pull", action="store_true", help="Do not auto-pull prompt files on client bridge start")
    connect_p.add_argument("--insecure", "-k", action="store_true", help="Allow self-signed or unverified TLS certificates")

    # disconnect
    disconnect_p = subparsers.add_parser("disconnect", help="Disconnect from remote server and restore local mode")

    # status
    status_p = subparsers.add_parser("status", help="Show remote connection status")

    # push
    push_p = subparsers.add_parser("push", help="Push and merge local memory into remote server")
    push_p.add_argument(
        "--replace",
        action="store_true",
        help="Replace the remote store with this machine and bump the vault epoch",
    )

    subparsers.add_parser(
        "bump-epoch",
        help="Increment the server vault epoch so older clients must replace-pull",
    )

    # pull
    pull_p = subparsers.add_parser("pull", help="Pull latest memory snapshot from remote server")
    pull_p.add_argument(
        "--replace",
        action="store_true",
        help="Make the local synced store match the remote snapshot exactly (backup first)",
    )

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
        help="Board memory URL, e.g. https://board.example/projects/<slug>/memory",
    )
    attach_p.add_argument(
        "--slug",
        default="",
        help="Agent key stem: ~/.agents/keys/<slug>.ed25519 (DID challenge, not a bearer)",
    )
    attach_p.add_argument(
        "--token",
        "-t",
        default="",
        help="Spare door: hashed bearer lpb_… (omit; use --slug)",
    )
    attach_p.add_argument(
        "--project",
        default="",
        help="Registered local slug (dest: <repo>/.agents/memory). Required when the board slug differs.",
    )
    attach_p.add_argument(
        "--dir",
        default="",
        help="Override dest. Default: registered project memory, else ~/.agents/shared/by-url/<id>/",
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
        if getattr(args, "min_client_version", ""):
            os.environ["AGENTS_MEMORY_MIN_CLIENT_VERSION"] = args.min_client_version
        if getattr(args, "update_hint", ""):
            os.environ["AGENTS_MEMORY_UPDATE_HINT"] = args.update_hint
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

        if args.replace:
            print("Replacing local memory with the remote snapshot...")
            try:
                res = remote_pull(url, token=token, verify_ssl=verify_ssl, replace=True)
            except SyncBusy as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 1
            print(format_sync_report(res.get("report") or {}))
        elif args.pull_only:
            print("Pulling remote memory snapshot...")
            res = remote_pull(url, token=token, verify_ssl=verify_ssl)
            print(f"Pulled {res.get('total_files', 0)} files.")
        else:
            print("Performing deterministic multi-device merge...")
            res = remote_push_merge(url, token=token, verify_ssl=verify_ssl)
            report = res.get("server_report", {})
            print(f"Merge complete: {format_sync_report(report)}")

        # Save config. Keep the epoch this sync just adopted (first connect has no file yet).
        extra: dict = {"verify_ssl": verify_ssl}
        if isinstance(res, dict) and res.get("epoch") is not None:
            extra["epoch"] = res.get("epoch")
        save_remote_config(
            url=url,
            token=token,
            auto_pull=not args.no_auto_pull,
            extra=extra,
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
        last_sync = cfg.get("last_sync") or cfg.get("updated_at", "unknown")
        print(f"Mode: REMOTE CLOUD SYNC")
        print(f"Server URL : {url}")
        print(f"Token      : {'***' if token else 'NONE'}")
        print(f"Last Sync  : {last_sync}")
        print(f"Vault epoch: {cfg.get('epoch', 0)}")
        if cfg.get("upgrade_required"):
            print(cfg["upgrade_required"])
        questions = USER_MEMORY / EPOCH_QUESTIONS_REL
        if questions.is_file():
            parked = sum(
                1
                for line in questions.read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("- ")
            )
            if parked:
                print(
                    f"Epoch questions: {parked} local edit(s) not pushed "
                    f"({EPOCH_QUESTIONS_REL}). Review with get_staging_inbox."
                )

        print("\nChecking server health...")
        try:
            health = remote_health_check(url, token=token)
            print(f"Server Status : ONLINE (v{health.get('version', '?')})")
            print(f"Remote Files  : {health.get('files_count', 0)}")
            print(f"Server epoch  : {health.get('epoch', 0)}")
            if health.get("min_client_version"):
                print(f"Min client    : {health.get('min_client_version')}")
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
            if getattr(args, "replace", False):
                print("Replacing the remote store with this machine and bumping the vault epoch...")
                res = remote_push_merge(url, token=token, replace=True)
            else:
                res = remote_push_merge(url, token=token, publish_absences=True)
            if res.get("auto_epoch"):
                print("Remote vault epoch changed. Local store replaced from the snapshot.")
                _print_epoch_questions(res)
            else:
                report = res.get("server_report", {})
                print(f"Push & Merge complete: {format_sync_report(report)}")
            if res.get("epoch"):
                print(f"Vault epoch: {res.get('epoch')}")
            return 0
        except Exception as e:
            print(f"Error pushing memory: {e}", file=sys.stderr)
            return 1

    elif cmd == "bump-epoch":
        cfg = get_remote_config()
        if not cfg:
            print("Error: Not connected to a remote server. Run 'agents-memory remote connect <URL>' first.", file=sys.stderr)
            return 1
        try:
            res = remote_bump_epoch(str(cfg.get("url") or ""), token=str(cfg.get("token") or ""))
        except Exception as e:
            print(f"Error bumping epoch: {e}", file=sys.stderr)
            return 1
        print(f"Vault epoch is now {res.get('epoch')}. Other devices replace-pull on their next sync.")
        return 0

    elif cmd == "pull":
        cfg = get_remote_config()
        if not cfg:
            print("Error: Not connected to a remote server. Run 'agents-memory remote connect <URL>' first.", file=sys.stderr)
            return 1
        url = cfg.get("url", "")
        token = cfg.get("token", "")
        print(f"Pulling latest memory snapshot from {url}...")
        try:
            res = remote_pull(url, token=token, replace=bool(getattr(args, "replace", False)))
            report = res.get("report", {})
            print(f"Pull complete: {format_sync_report(report)}")
            _print_epoch_questions(res)
            return 0
        except SyncBusy as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
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
            res = board_attach(
                url,
                token=token,
                dest_dir=dest,
                verify_ssl=not args.insecure,
                project=getattr(args, "project", "") or "",
                slug=getattr(args, "slug", "") or "",
            )
        except PermissionError:
            print(
                "ERROR: Authentication failed. Use --slug <agent> "
                "(file ~/.agents/keys/<slug>.ed25519).",
                file=sys.stderr,
            )
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
