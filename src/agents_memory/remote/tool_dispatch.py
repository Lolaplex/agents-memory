"""Route MCP tool calls to local handlers, remote REST proxy, or hybrid merge."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from ..store import (
    USER_MEMORY,
    add_memory as store_add,
    file_id,
    iter_project_memory_files,
    memory_file_for,
    projects_by_slug,
    search_memory as store_search,
    sync_injection,
)
from .client import get_remote_config, remote_pull, remote_push_merge
from .locality import PUSH_AFTER_LOCAL, tool_locality


def _cfg() -> dict[str, Any]:
    return get_remote_config() or {}


def _verify_ssl(cfg: dict[str, Any]) -> bool:
    if cfg.get("verify_ssl") is False:
        return False
    return True


def _auth_headers(token: str) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def remote_connected() -> bool:
    cfg = _cfg()
    return bool(cfg.get("url"))


def maybe_push_after(tool_name: str) -> dict[str, Any] | None:
    if tool_name not in PUSH_AFTER_LOCAL or not remote_connected():
        return None
    cfg = _cfg()
    try:
        return remote_push_merge(
            cfg["url"],
            token=str(cfg.get("token") or ""),
            verify_ssl=_verify_ssl(cfg),
        )
    except Exception as e:
        return {"status": "push_failed", "error": str(e)}


def maybe_refresh_local_index() -> None:
    """Rebuild disposable FTS cache from local mirror + repo trees (never synced)."""
    try:
        from ..index import rebuild_index

        rebuild_index()
    except Exception:
        pass


def maybe_pull_after_write(refresh_index: bool = True) -> None:
    if not remote_connected():
        return
    cfg = _cfg()
    try:
        remote_pull(
            cfg["url"],
            token=str(cfg.get("token") or ""),
            verify_ssl=_verify_ssl(cfg),
        )
        if refresh_index:
            maybe_refresh_local_index()
    except Exception:
        try:
            sync_injection()
        except Exception:
            pass


def call_remote_tool(name: str, arguments: dict[str, Any]) -> str:
    cfg = _cfg()
    url = str(cfg.get("url") or "").rstrip("/")
    if not url:
        raise RuntimeError("No remote memory URL configured.")
    target = f"{url}/api/v1/tool"
    payload = {"name": name, "arguments": arguments}
    with httpx.Client(timeout=120.0, verify=_verify_ssl(cfg)) as client:
        resp = client.post(
            target,
            json=payload,
            headers=_auth_headers(str(cfg.get("token") or "")),
        )
        if resp.status_code == 401:
            raise PermissionError("Unauthorized: token rejected by remote server.")
        if resp.status_code == 400:
            data = resp.json()
            raise RuntimeError(data.get("error") or resp.text)
        resp.raise_for_status()
        data = resp.json()
    result = data.get("result")
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, ensure_ascii=False)


def _path_is_repo_memory(path: Path) -> bool:
    try:
        path = path.resolve()
    except OSError:
        return False
    for p in projects_by_slug().values():
        if not p.path_obj.is_dir():
            continue
        root = (p.path_obj / ".agents" / "memory").resolve()
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def hybrid_search_memory(query: str, project: str = "") -> str:
    remote_lines: list[str] = []
    if remote_connected():
        try:
            remote_lines.append(call_remote_tool("search_memory", {"query": query, "project": project}))
        except Exception as e:
            remote_lines.append(f"[remote search failed: {e}]")

    local_hits = store_search(query, project=project)
    local_lines: list[str] = []
    if local_hits:
        local_lines.append(f"Found {len(local_hits)} local repo hits:")
        for h in local_hits:
            ident = h.get("file") or h.get("id", "")
            if ident.startswith("user/"):
                continue
            local_lines.append(f"- [{h['id']}] {h['text']}")

    parts = [p for p in remote_lines + local_lines if p]
    if not parts:
        return f"No memories for '{query}'" + (f" in {project}" if project else "")
    return "\n".join(parts)


def _file_id_is_local_only(file_id: str) -> bool:
    fid = file_id.replace("\\", "/").lstrip("/")
    if fid.startswith("project/"):
        return True
    if fid.startswith("rules/"):
        return True
    return False


def hybrid_read_memory_file(file_id: str, local_handler: Callable[..., str]) -> str:
    if _file_id_is_local_only(file_id):
        return local_handler(file_id=file_id)
    if remote_connected():
        return call_remote_tool("read_memory_file", {"file_id": file_id})
    return local_handler(file_id=file_id)


def hybrid_write_memory_file(
    file_id: str, content: str, local_handler: Callable[..., str]
) -> str:
    if _file_id_is_local_only(file_id):
        return local_handler(file_id=file_id, content=content)
    if remote_connected():
        result = call_remote_tool(
            "write_memory_file", {"file_id": file_id, "content": content}
        )
        maybe_pull_after_write()
        return result
    return local_handler(file_id=file_id, content=content)


def hybrid_check_memory_freshness(local_handler: Callable[..., str]) -> str:
    """Staging on remote when connected; batons always local."""
    import json as _json

    nags: list[str] = []
    staging_count = 0
    if remote_connected():
        try:
            raw = call_remote_tool("get_staging_inbox", {"limit": 1})
            if "empty" not in raw.lower():
                payload = _json.loads(raw)
                staging_count = int(payload.get("total") or 0)
        except Exception as e:
            nags.append(f"Could not read remote staging inbox: {e}")
    else:
        local_raw = local_handler()
        try:
            payload = _json.loads(local_raw)
            staging_count = int(payload.get("staging_count") or payload.get("total") or 0)
            nags.extend(payload.get("nags") or [])
        except Exception:
            return local_raw

    if staging_count > 20:
        nags.append(
            f"Staging inbox has {staging_count} unprocessed bullets (recommend distill / memory-distill)."
        )

    import time

    from ..store import parse_projects

    now = time.time()
    for proj in parse_projects():
        baton_file = proj.memory_dir / "rituals" / "baton.md"
        if baton_file.exists():
            try:
                age_hours = (now - baton_file.stat().st_mtime) / 3600.0
                if age_hours > 24.0:
                    nags.append(
                        f"Project '{proj.slug}' baton is stale ({round(age_hours, 1)}h since last update)."
                    )
            except OSError:
                pass

    payload = {
        "status": "warning" if nags else "ok",
        "staging_count": staging_count,
        "nags": nags,
    }
    return _json.dumps(payload, indent=2)


def hybrid_add_memory(
    fact_or_message: str,
    kind: str = "",
    name: str = "",
    project: str = "",
    collection: str = "",
) -> str:
    target = memory_file_for(kind=kind, name=name, project=project, collection=collection)
    if _path_is_repo_memory(target):
        loc = store_add(
            fact_or_message,
            kind=kind,
            name=name,
            project=project,
            collection=collection,
            auto_sync=True,
        )
        return f"Saved to {loc} (local repo; not synced to remote store)"

    if remote_connected():
        result = call_remote_tool(
            "add_memory",
            {
                "fact_or_message": fact_or_message,
                "kind": kind,
                "name": name,
                "project": project,
                "collection": collection,
            },
        )
        maybe_pull_after_write()
        return result

    loc = store_add(
        fact_or_message,
        kind=kind,
        name=name,
        project=project,
        collection=collection,
        auto_sync=True,
    )
    return f"Saved to {loc}"


def hybrid_baton_tool(
    tool_name: str,
    arguments: dict[str, Any],
    local_handler: Callable[..., str],
) -> str:
    project = str(arguments.get("project") or "").strip()
    if project:
        p = projects_by_slug().get(project)
        if p and p.path_obj.is_dir():
            return local_handler(**arguments)
    if remote_connected():
        result = call_remote_tool(tool_name, arguments)
        maybe_pull_after_write()
        return result
    return local_handler(**arguments)


def dispatch_tool(name: str, local_handler: Callable[..., str], **arguments: Any) -> str:
    loc = tool_locality(name)

    if loc == "remote":
        if not remote_connected():
            return local_handler(**arguments)
        result = call_remote_tool(name, arguments)
        if name in {"write_memory_file", "auto_distill", "promote_bullet", "distill_batch", "delete_memory"}:
            maybe_pull_after_write()
        return result

    if loc == "hybrid":
        if name == "search_memory":
            return hybrid_search_memory(
                str(arguments.get("query") or ""),
                str(arguments.get("project") or ""),
            )
        if name == "add_memory":
            return hybrid_add_memory(
                str(arguments.get("fact_or_message") or ""),
                kind=str(arguments.get("kind") or ""),
                name=str(arguments.get("name") or ""),
                project=str(arguments.get("project") or ""),
                collection=str(arguments.get("collection") or ""),
            )
        if name == "read_memory_file":
            return hybrid_read_memory_file(
                str(arguments.get("file_id") or ""), local_handler
            )
        if name == "write_memory_file":
            return hybrid_write_memory_file(
                str(arguments.get("file_id") or ""),
                str(arguments.get("content") or ""),
                local_handler,
            )
        if name == "check_memory_freshness":
            return hybrid_check_memory_freshness(local_handler)
        if name in {"get_baton", "set_baton", "append_chronicle"}:
            return hybrid_baton_tool(name, arguments, local_handler)

    result = local_handler(**arguments)
    push_report = maybe_push_after(name)
    if push_report and push_report.get("status") == "ok":
        merged = push_report.get("server_report", {}).get("merged") or []
        added = push_report.get("server_report", {}).get("added") or []
        if merged or added:
            result += f"\n\n[synced to remote: {len(added)} added, {len(merged)} merged]"
        if name in {"ingest_catalog", "ingest_extract"} or merged or added:
            maybe_refresh_local_index()
    elif push_report and push_report.get("status") == "push_failed":
        result += f"\n\n[WARNING: remote push failed: {push_report.get('error')}]"
    return result
