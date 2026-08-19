"""Local markdown memory MCP — reference implementation of abi/MCP.md."""
from __future__ import annotations

import json
import sys
from mcp.server.fastmcp import FastMCP

from .store import (
    add_memory as store_add,
    delete_memory as store_delete,
    ensure_memory_layout,
    get_project_memories as store_get_project,
    ignore_slug,
    inject_into_repo,
    inventory_report,
    parse_projects,
    promote_bullet as store_promote,
    register_project as store_register,
    search_memory as store_search,
    sync_injection,
)

ensure_memory_layout()

mcp = FastMCP("agent-memory")


@mcp.tool()
def search_memory(query: str, project: str = "") -> str:
    """Search all local markdown (concepts/entities/workflows/projects/notes + each repo .agents/memory)."""
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
    """File a durable fact in the right folder.

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
        return f"Saved to {loc}"
    except Exception as e:
        return f"Error saving memory: {e}"


@mcp.tool()
def promote_bullet(
    bullet: str,
    kind: str,
    name: str,
    project: str = "",
    collection: str = "",
    source_path: str = "",
) -> str:
    """Promote a staging bullet into a typed memory file (kind+name) and delete it from staging.

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
        return f"Promoted to {loc} {status}"
    except Exception as e:
        return f"Error promoting bullet: {e}"


@mcp.tool()
def get_project_memories(project: str) -> str:
    """Return the project link plus in-tree `.agents/memory` markdown."""
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
    """Rebuild chats-index.md and entity reference cards from ingest.json (catalog phase)."""
    try:
        from .ingest_catalog import run_catalog

        result = run_catalog()
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error running ingest catalog: {e}"


@mcp.tool()
def ingest_extract(source_id: str = "") -> str:
    """Extract durable user lines into staging/ingest/<id>/captured.md (extract phase)."""
    try:
        from .ingest_extractors import run_extract

        result = run_extract(source_id=source_id)
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error running ingest extract: {e}"


@mcp.tool()
def ingest_status() -> str:
    """Show ingest/state.json summary for configured sources."""
    try:
        from .ingest_common import ingest_state_path, load_state
        from .ingest_config import list_sources, load_ingest

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
                    "staging": entry.get("staging"),
                }
            )
        return json.dumps({"state_file": str(ingest_state_path()), "sources": rows}, indent=2)
    except Exception as e:
        return f"Error reading ingest status: {e}"


def main() -> int:
    print("Starting local agent-memory MCP on stdio...", file=sys.stderr)
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
