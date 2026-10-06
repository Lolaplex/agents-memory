"""Local markdown memory MCP — reference implementation of abi/MCP.md."""
from __future__ import annotations

import json
import sys
from mcp.server.fastmcp import FastMCP

from .store import (
    add_memory as store_add,
    auto_distill as store_auto_distill,
    delete_memory as store_delete,
    ensure_memory_layout,
    get_project_memories as store_get_project,
    ignore_slug,
    inject_into_repo,
    inventory_report,
    parse_projects,
    read_memory_file as store_read_file,
    register_project as store_register,
    search_memory as store_search,
    staging_status_summary,
    sync_injection,
    write_memory_file as store_write_file,
    maybe_run_startup_noise_pass,
)

ensure_memory_layout()

mcp = FastMCP("agents-memory")

# Auto-trace all tool calls to ~/.agents/traces/ if agents-traces is installed
try:
    from agents_traces import auto_trace_mcp
    auto_trace_mcp(mcp)
except Exception:
    pass

@mcp.tool()
def search_memory(query: str, project: str = "") -> str:
    """Search typed markdown. Empty project= is the user store only (~/.agents/memory).

    Scans typed markdown under ~/.agents/memory and registered repo `.agents/memory/`.
    Pass project=<slug> for that clone plus the user store. project=* searches every
    registered clone. Exact substring first (max two hits per file, hash ids), then
    ranked FTS5 fill so one noisy file does not hide another. Repo architecture:
    get_project_memories(slug) or pass project=. Does not search product chat/jsonl.
    CALL PROACTIVELY before guessing architecture, decisions, or preferences.

    Not for chat transcripts — use `session_grep` / `session_snap` (agents-traces) or
    `chats-index.md` for product jsonl body paths.
    """
    try:
        hits = store_search(query, project=project)
        if not hits:
            return f"No local memories for '{query}'" + (f" in {project}" if project else "")
        lines = [f"Found {len(hits)} hits:"]
        for h in hits:
            lines.append(f"- [{h['id']}] {h['text']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching local memory: {e}"


@mcp.tool()
def add_memory(
    fact_or_message: str,
    kind: str = "",
    name: str = "",
    project: str = "",
    collection: str = "",
) -> str:
    """File a durable fact in the right folder. Auto-syncs to all IDEs/CLIs.

    PROACTIVE USAGE: ALWAYS call this tool immediately when the user establishes durable preferences,
    architecture decisions (ADRs), tool/package choices, styling conventions, or corrections.
    Do NOT wait for explicit user commands like 'save this'.

    kind=fact|concept|entity|workflow|project|note|scratch|research|plans|tasks|roadmap|waves|decision|proposed|implemented|rejected|staging
    plus name= (file stem). collection= for notes/ or a note class
    (feature, bug-fix, simplification, architecture, process, testing).
    Sequential 001-topic.md: plans, tasks, waves, roadmap, decisions, lifecycle notes.
    kind=research is topical (input). project= alone writes <repo>/.agents/memory/facts.md (direct fact).
    Do not dump transcripts, emails, phones, tokens, or one-shot how-tos.
    Revise-in-place kinds (research, decision, adr, implemented) can be initialized with add_memory,
    but subsequent edits to an existing file MUST use write_memory_file.
    """
    try:
        loc = store_add(
            fact_or_message,
            kind=kind,
            name=name,
            project=project,
            collection=collection,
        )
        return f"Saved to {loc}"
    except Exception as e:
        return f"Error saving memory: {e}"


@mcp.tool()
def read_memory_file(file_id: str) -> str:
    """Read the raw markdown or json content of any memory file or rule by file_id (e.g. 'user/USER.md', 'rules/user-rules.mdc', 'user/notes/preferences/memory-meta.md', 'project/customs/README.md')."""
    try:
        return store_read_file(file_id)
    except Exception as e:
        return f"Error reading memory file '{file_id}': {e}"


@mcp.tool()
def write_memory_file(file_id: str, content: str) -> str:
    """Write/overwrite any memory file or rule (e.g. 'user/USER.md', 'rules/user-rules.mdc', 'user/notes/preferences/note.md') and auto-sync immediately across all IDEs and CLIs."""
    try:
        loc = store_write_file(file_id, content, auto_sync=True)
        return f"Saved and synced {loc}"
    except Exception as e:
        return f"Error writing memory file '{file_id}': {e}"


@mcp.tool()
def auto_distill(limit: int = 50, discard_noise: bool = True) -> str:
    """Automatically classify and distill staging bullets (discard obvious noise/chatter, promote standard facts/preferences) and auto-sync immediately."""
    try:
        res = store_auto_distill(limit=limit, discard_noise=discard_noise, auto_sync=True)
        return json.dumps(res, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error in auto_distill: {e}"


@mcp.tool()
def get_staging_inbox(project: str = "", limit: int = 20) -> str:
    """Fetch un-distilled bullets from staging, grouped by source file.

    Each bullet includes file and source_path for distill_batch.
    """
    try:
        from .store import get_staging_inbox as store_get_inbox

        payload = store_get_inbox(project=project, limit=limit)
        if payload["total"] == 0:
            return "Staging inbox is empty (all caught up)."
        summary = staging_status_summary()
        if summary.get("nag"):
            payload["notice"] = summary["nag"]
        return json.dumps(payload, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error reading staging inbox: {e}"


@mcp.tool()
def distill_batch(items_json: str) -> str:
    """Batch-process staging bullets into memory or discard them. Auto-syncs to all IDEs/CLIs.

    Pass a JSON array of objects:
    [{"bullet": "fact text", "kind": "note", "name": "stem", "project": "slug"},
     {"bullet": "throwaway chatter", "discard": true}]
    """
    try:
        from .store import distill_batch as store_distill_batch

        parsed = json.loads(items_json) if isinstance(items_json, str) else items_json
        if not isinstance(parsed, list):
            return "Error: expected a JSON list of items"
        result = store_distill_batch(parsed)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error in distill_batch: {e}"


@mcp.tool()
def get_project_memories(project: str) -> str:
    """Return the project link plus in-tree `.agents/memory` markdown.
    
    CALL PROACTIVELY when starting work in a repository to load its architecture, facts, ADRs, and tasks.
    """
    try:
        return store_get_project(project)
    except Exception as e:
        return f"Error fetching project memories: {e}"


@mcp.tool()
def delete_memory(memory_id: str) -> str:
    """Delete a memory line by id from search_memory, e.g. user/notes/programming/chat-stores.md:3 or project/git-updater/staging/captured.md:12."""
    try:
        removed = store_delete(memory_id)
        return f"Deleted {memory_id}: {removed}"
    except Exception as e:
        return f"Error deleting memory: {e}"


@mcp.tool()
def list_projects() -> str:
    """List all tracked projects (slug, path, role, stack, status)."""
    rows = parse_projects()
    if not rows:
        return "No projects in PROJECTS.md"
    lines = [f"{len(rows)} projects:"]
    for p in rows:
        lines.append(f"- {p.slug} | {p.path} | {p.role} | {p.stack} | {p.status}")
    return "\n".join(lines)


@mcp.tool()
def inventory_projects() -> str:
    """Bestandaufnahme: compare scan.json roots to PROJECTS.md. Returns unknown and missing folders."""
    try:
        return json.dumps(inventory_report(), indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Error running inventory: {e}"


@mcp.tool()
def register_project(
    slug: str,
    path: str,
    role: str = "unclassified",
    stack: str = "—",
    status: str = "active",
) -> str:
    """Add or update a project in PROJECTS.md, write `<repo>/.agents/memory/` (link + folders), inject AGENTS.md+CLAUDE.md, sync."""
    try:
        p = store_register(slug, path, role=role, stack=stack, status=status)
        written, warnings = sync_injection(include_repos=True)
        extra = inject_into_repo(p)
        warn_txt = f" Warnings: {'; '.join(warnings)}" if warnings else ""
        return (
            f"Registered {p.slug} at {p.path}. "
            f"Synced {len(written)} files. Repo inject: {len(extra)} files.{warn_txt}"
        )
    except Exception as e:
        return f"Error registering project: {e}"


@mcp.tool()
def ignore_project(slug: str) -> str:
    """Stop listing this folder as unknown in inventory (scan.json ignore_slugs)."""
    try:
        ignore_slug(slug)
        return f"Ignored slug '{slug}'"
    except Exception as e:
        return f"Error ignoring project: {e}"


@mcp.tool()
def sync_local_agents_md(project_folder_path: str = "", project_slug: str = "") -> str:
    """Sync always-on memory into your Agent hosts. Optional: also inject one repo by path or slug."""
    try:
        written, warnings = sync_injection(include_repos=True)
        extra = []
        if project_slug:
            from .store import projects_by_slug

            p = projects_by_slug().get(project_slug)
            if p:
                extra = inject_into_repo(p)
        elif project_folder_path:
            from .store import Project, inject_into_repo as inj
            from pathlib import Path as P

            slug = project_slug or P(project_folder_path).name
            extra = inj(
                Project(
                    slug=slug,
                    path=project_folder_path,
                    role="see PROJECTS.md",
                    stack="—",
                )
            )
        out = "Synced:\n" + "\n".join(written + extra)
        if warnings:
            out += "\nWarnings:\n" + "\n".join(f"- {w}" for w in warnings)
        return out
    except Exception as e:
        return f"Error syncing: {e}"


@mcp.tool()
def ingest_catalog() -> str:
    """Catalog phase: rebuild chats-index.md + entity cards (titles/paths only). Bodies stay in product folders. Same contract for every ingest source."""
    try:
        from .remote.locality import assert_ingest_runs_locally

        assert_ingest_runs_locally()
        from .ingest_catalog import run_catalog

        result = run_catalog()
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error running ingest catalog: {e}"


@mcp.tool()
def ingest_extract(source_id: str = "") -> str:
    """Extract phase: filter durable user lines into staging/ingest/<id>/captured.md (inbox, not memory). Distill explicitly afterward."""
    try:
        from .remote.locality import assert_ingest_runs_locally

        assert_ingest_runs_locally()
        from .ingest_extractors import run_extract

        result = run_extract(source_id=source_id)
        maybe_run_after_extract_noise_pass(auto_sync=True)
        try:
            from .remote.sync_hooks import push_if_connected

            push_if_connected(refresh_index=True)
        except Exception:
            pass
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error running ingest extract: {e}"


@mcp.tool()
def ingest_status() -> str:
    """Show ingest/state.json summary plus staging inbox depth and nag."""
    try:
        from .ingest_common import ingest_state_path, load_state
        from .ingest_config import list_sources, load_ingest
        from .store import staging_status_summary

        cfg = load_ingest()
        state = load_state()
        rows = []
        for src in list_sources(cfg):
            sid = str(src["id"])
            entry = state.get("sources", {}).get(sid, {})
            rows.append(
                {
                    "id": sid,
                    "kind": src.get("kind"),
                    "last_catalog": entry.get("last_catalog"),
                    "last_extract": entry.get("last_extract"),
                    "catalog_count": entry.get("catalog_count"),
                    "extract_count": entry.get("extract_count"),
                    "extract_capped": entry.get("extract_capped"),
                    "extract_total_before_cap": entry.get("extract_total_before_cap"),
                    "staging": entry.get("staging"),
                }
            )
        body = {
            "state_file": str(ingest_state_path()),
            "staging": staging_status_summary(),
            "sources": rows,
        }
        if body["staging"].get("nag"):
            body["notice"] = body["staging"]["nag"]
        return json.dumps(body, indent=2)
    except Exception as e:
        return f"Error reading ingest status: {e}"


@mcp.tool()
def get_baton(project: str = "", cwd: str = "") -> str:
    """Read the session handoff baton marker for a project or global user store."""
    try:
        return store_get_baton(project=project, cwd=cwd)
    except Exception as e:
        return f"Error reading baton: {e}"


@mcp.tool()
def set_baton(text: str, project: str = "", cwd: str = "") -> str:
    """Write or update the session handoff baton marker (mutable ritual)."""
    try:
        loc = store_set_baton(text, project=project, cwd=cwd)
        return f"Baton updated at {loc}"
    except Exception as e:
        return f"Error setting baton: {e}"


@mcp.tool()
def append_chronicle(
    beat: str, project: str = "", emoji: str = "📝", refs: list[str] | None = None
) -> str:
    """Append a beat to the event chronicle (~/.agents/memory/events/chronicle/<slug>.md)."""
    try:
        loc = store_append_chronicle(beat, project=project, emoji=emoji, refs=refs)
        return f"Beat recorded to {loc}"
    except Exception as e:
        return f"Error appending chronicle: {e}"


@mcp.tool()
def session_snap(limit: int = 20, project: str = "", cwd: str = "") -> str:
    """Recent **conversation** lines from agents-traces plus baton header.

    Session/transcript tier — not markdown memory. For architecture/ADRs/facts use
    `get_project_memories` or `search_memory`. Run `python -m agents_traces ingest` first
    if vendor chats are not yet in traces.
    """
    try:
        return store_session_snap(limit=limit, project=project, cwd=cwd)
    except Exception as e:
        return f"Error taking session snap: {e}"


@mcp.tool()
def session_grep(pattern: str, since: str = "", project: str = "") -> str:
    """Regex search in agents-traces session messages — not markdown memory.

    For durable notes/ADRs use `search_memory`. For full chat file paths see `chats-index.md`.
    """
    try:
        return store_session_grep(pattern=pattern, since=since, project=project)
    except Exception as e:
        return f"Error running session grep: {e}"


@mcp.tool()
def session_tail(session_id: str = "", limit: int = 10) -> str:
    """Tail agents-traces lines for one session id (or latest). Not markdown memory."""
    try:
        return store_session_tail(session_id=session_id, limit=limit)
    except Exception as e:
        return f"Error running session tail: {e}"


@mcp.tool()
def rebuild_index() -> str:
    """Rebuild disposable SQLite FTS cache from markdown on disk.

    Maintenance only — normal search goes through `search_memory` (auto-rebuilds if missing).
    Call when `check_memory_freshness` reports a stale index or after bulk file edits outside MCP.
    """
    try:
        from .index import rebuild_index as run_rebuild
        res = run_rebuild()
        return f"Index rebuilt: {res['indexed']} documents in {res['duration_ms']}ms -> {res['db_path']}"
    except Exception as e:
        return f"Error rebuilding index: {e}"


@mcp.tool()
def search_hybrid(query: str, project: str = "", limit: int = 20) -> str:
    """FTS5 BM25 + sparse TF-IDF fused by RRF — secondary to `search_memory`.

    Prefer `search_memory` (exact substring first, then this index). Use this when you
    need raw ranks/snippets. Same disposable `fts.sqlite` cache; no embedding model.
    Does not search product chat/jsonl. For graph neighbors use `get_related`.
    """
    try:
        from .index import search_hybrid as run_search
        hits = run_search(query, project=project, limit=limit)
        if not hits:
            return f"No matches found for '{query}'"
        lines = [f"Found {len(hits)} matches:"]
        for h in hits:
            lines.append(f"- [{h['id']}] {h['title']} — {h['snippet']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error running search: {e}"


@mcp.tool()
def get_related(memory_id: str, limit: int = 5) -> str:
    """Graph neighbors for a known memory id (refs, supersedes, same_as, backlinks).

    Requires an id from `search_memory` / `read_memory_file`, not free-text query.
    To propose new links from overlap use `suggest_links` (human review only).
    """
    try:
        from .index import get_related as run_related
        res = run_related(memory_id, limit=limit)
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error fetching related memories: {e}"


@mcp.tool()
def suggest_links(from_id: str, limit: int = 5) -> str:
    """Propose candidate typed relation links for human review — does not write memory.
    For existing relations on a known id use `get_related`.
    """
    try:
        from .index import suggest_links as run_suggest
        suggestions = run_suggest(from_id, limit=limit)
        return json.dumps(suggestions, indent=2)
    except Exception as e:
        return f"Error suggesting links: {e}"


@mcp.tool()
def check_memory_freshness() -> str:
    """Mechanical health: staging depth, baton/index staleness — not a search tool.

    Run before long tasks; follow nag with `get_staging_inbox`, `rebuild_index`, or distill.
    """
    try:
        from .store import check_memory_freshness as run_check
        res = run_check()
        summary = staging_status_summary()
        if summary.get("nag"):
            res["staging_notice"] = summary["nag"]
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error checking memory freshness: {e}"

def main() -> int:
    print("Starting local agents-memory MCP on stdio...", file=sys.stderr)
    try:
        maybe_run_startup_noise_pass()
    except Exception:
        pass
    try:
        from .index import rebuild_index
        rebuild_index()
    except Exception:
        pass
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
