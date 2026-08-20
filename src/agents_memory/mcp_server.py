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
    promote_bullet as store_promote,
    read_memory_file as store_read_file,
    register_project as store_register,
    search_memory as store_search,
    staging_status_summary,
    sync_injection,
    write_memory_file as store_write_file,
)

ensure_memory_layout()

mcp = FastMCP("agents-memory")


def _with_staging_nag(output: str) -> str:
    try:
        summary = staging_status_summary()
        nag = summary.get("nag")
        if nag:
            return f"{output}\n\n[NOTICE: {nag}]"
    except Exception:
        pass
    return output


@mcp.tool()
def search_memory(query: str, project: str = "") -> str:
    """Search typed markdown under ~/.agents/memory and registered repos. Does not search product chat/jsonl graves — use chats-index.md for body paths."""
    try:
        hits = store_search(query, project=project)
        if not hits:
            return _with_staging_nag(
                f"No local memories for '{query}'" + (f" in {project}" if project else "")
            )
        lines = [f"Found {len(hits)} hits:"]
        for h in hits:
            lines.append(f"- [{h['id']}] {h['text']}")
        return _with_staging_nag("\n".join(lines))
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

    kind=concept|entity|workflow|project|note|scratch|research|plans|tasks|roadmap|waves|decision|proposed|implemented|rejected|staging
    plus name= (file stem). collection= for notes/ or a note class
    (feature, bug-fix, simplification, architecture, process, testing).
    Sequential 001-topic.md: plans, tasks, waves, roadmap, decisions, lifecycle notes.
    kind=research is topical (input). project= alone writes staging/captured.md (inbox).
    Do not dump transcripts, emails, phones, tokens, or one-shot how-tos.
    """
    try:
        loc = store_add(
            fact_or_message,
            kind=kind,
            name=name,
            project=project,
            collection=collection,
        )
        return _with_staging_nag(f"Saved to {loc}")
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
        return _with_staging_nag(f"Saved and synced {loc}")
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
def promote_bullet(
    bullet: str,
    kind: str,
    name: str,
    project: str = "",
    collection: str = "",
    source_path: str = "",
) -> str:
    """Promote a staging bullet into a typed memory file (kind+name) and delete it from staging. Auto-syncs to all IDEs/CLIs.

    Example: promote_bullet("prefer dark mode", kind="note", name="ui", collection="preferences")
    """
    try:
        loc, removed = store_promote(
            bullet=bullet,
            kind=kind,
            name=name,
            project=project,
            collection=collection,
            source_path=source_path,
        )
        status = "and removed from staging" if removed else "(staging bullet not found to delete)"
        return _with_staging_nag(f"Promoted to {loc} {status}")
    except Exception as e:
        return f"Error promoting bullet: {e}"


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
    """Return the project link plus in-tree `.agents/memory` markdown."""
    try:
        return _with_staging_nag(store_get_project(project))
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
        from .ingest_catalog import run_catalog

        result = run_catalog()
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error running ingest catalog: {e}"


@mcp.tool()
def ingest_extract(source_id: str = "") -> str:
    """Extract phase: filter durable user lines into staging/ingest/<id>/captured.md (inbox, not memory). Distill explicitly afterward."""
    try:
        from .ingest_extractors import run_extract

        result = run_extract(source_id=source_id)
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
        return json.dumps(
            {
                "state_file": str(ingest_state_path()),
                "staging": staging_status_summary(),
                "sources": rows,
            },
            indent=2,
        )
    except Exception as e:
        return f"Error reading ingest status: {e}"


# Auto-trace all tool calls to ~/.agents/traces/ if agents-traces is installed
try:
    from agents_traces import auto_trace_mcp
    auto_trace_mcp(mcp)
except Exception:
    pass


def main() -> int:
    print("Starting local agents-memory MCP on stdio...", file=sys.stderr)
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
