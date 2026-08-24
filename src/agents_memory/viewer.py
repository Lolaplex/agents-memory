"""Local static browser and web export projection for agents-memory.

Provides a human-navigable viewer (WEBVIEW shell projection over markdown).
No node/npm/external CDN dependency — 100% pure Python standard library.
"""
from __future__ import annotations

import html
import http.server
import json
import re
import socketserver
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from .index import get_related, rebuild_index, search_hybrid
from .store import (
    CHRONICLE_DIR,
    PROJECTS_MD,
    USER_MEMORY,
    _read,
    get_staging_inbox,
    parse_projects,
)

EXPORT_DIR = USER_MEMORY / "export"


def _md_to_html(md_text: str) -> str:
    """Minimal, robust markdown to HTML converter using standard library."""
    lines = md_text.splitlines()
    out: List[str] = []
    in_code = False
    in_list = False
    in_table = False

    for line in lines:
        stripped = line.strip()

        # Code blocks
        if stripped.startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                lang = stripped[3:].strip()
                out.append(f"<pre><code class=\"language-{html.escape(lang)}\">")
                in_code = True
            continue

        if in_code:
            out.append(html.escape(line))
            continue

        # Close list if not a list item
        if in_list and not (stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\.\s", stripped)):
            out.append("</ul>")
            in_list = False

        # Close table if not a table row
        if in_table and not stripped.startswith("|"):
            out.append("</tbody></table></div>")
            in_table = False

        if not stripped:
            continue

        # Headings
        if stripped.startswith("# "):
            out.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            out.append(f"<h3>{html.escape(stripped[4:])}</h3>")
        elif stripped.startswith("#### "):
            out.append(f"<h4>{html.escape(stripped[5:])}</h4>")
        elif stripped.startswith("> "):
            out.append(f"<blockquote>{html.escape(stripped[2:])}</blockquote>")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            item_text = _format_inline(stripped[2:])
            out.append(f"<li>{item_text}</li>")
        elif stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if all(set(c).issubset({"-", ":", " "}) for c in cells):
                continue  # Header divider
            if not in_table:
                out.append("<div class=\"table-wrap\"><table><tbody>")
                in_table = True
            row_html = "".join(f"<td>{_format_inline(c)}</td>" for c in cells)
            out.append(f"<tr>{row_html}</tr>")
        else:
            out.append(f"<p>{_format_inline(stripped)}</p>")

    if in_code:
        out.append("</code></pre>")
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</tbody></table></div>")

    return "\n".join(out)


def _format_inline(text: str) -> str:
    """Format bold, italic, code, and links in markdown lines."""
    t = html.escape(text)
    # Inline code
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    # Bold
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    # Italic
    t = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", t)
    # Markdown links: [label](url)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    return t


CSS_THEME = """
:root {
  --bg: #0f1117;
  --surface: #181b24;
  --surface-hover: #222734;
  --border: #2b3040;
  --text: #e1e4ed;
  --text-muted: #8b94a8;
  --accent: #5e81f4;
  --accent-light: #8ba2ff;
  --tag-bg: #1f2538;
  --code-bg: #141720;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.sidebar {
  width: 300px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid var(--border);
  font-weight: bold;
  font-size: 1.1rem;
  color: var(--accent-light);
  display: flex;
  align-items: center;
  gap: 8px;
}
.search-box {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.search-box input {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  outline: none;
}
.search-box input:focus { border-color: var(--accent); }
.nav-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
.nav-section {
  font-size: 0.75rem;
  text-transform: uppercase;
  color: var(--text-muted);
  letter-spacing: 0.05em;
  margin: 14px 8px 6px;
}
.nav-item {
  display: block;
  padding: 8px 12px;
  color: var(--text);
  text-decoration: none;
  border-radius: 6px;
  font-size: 0.9rem;
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nav-item:hover, .nav-item.active {
  background: var(--surface-hover);
  color: var(--accent-light);
}
.content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.content-header {
  padding: 14px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  font-size: 1.1rem;
  font-weight: 600;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.content-body {
  flex: 1;
  padding: 28px 36px;
  overflow-y: auto;
  line-height: 1.65;
}
h1, h2, h3, h4 { color: #fff; margin: 1.2em 0 0.5em; }
h1:first-child { margin-top: 0; }
p { margin-bottom: 1em; }
ul, ol { margin-bottom: 1em; padding-left: 1.4em; }
li { margin-bottom: 0.3em; }
blockquote {
  border-left: 3px solid var(--accent);
  padding: 8px 16px;
  background: var(--surface);
  color: var(--text-muted);
  margin-bottom: 1em;
  border-radius: 0 6px 6px 0;
}
pre {
  background: var(--code-bg);
  border: 1px solid var(--border);
  padding: 14px;
  border-radius: 8px;
  overflow-x: auto;
  margin-bottom: 1em;
}
code {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.9em;
  background: var(--code-bg);
  padding: 2px 5px;
  border-radius: 4px;
  color: #ff9b5e;
}
pre code { background: none; padding: 0; color: var(--text); }
.table-wrap { overflow-x: auto; margin-bottom: 1em; }
table {
  width: 100%;
  border-collapse: collapse;
  border: 1px solid var(--border);
}
th, td {
  padding: 10px 14px;
  border: 1px solid var(--border);
  text-align: left;
}
tr:nth-child(even) { background: var(--surface); }
a { color: var(--accent-light); text-decoration: none; }
a:hover { text-decoration: underline; }
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  background: var(--tag-bg);
  color: var(--accent-light);
  font-size: 0.75rem;
  font-weight: bold;
}
"""


def _generate_page_html(title: str, body_html: str, active_doc: str = "") -> str:
    projects = parse_projects()
    proj_links = "".join(
        f'<a class="nav-item {"active" if active_doc == p.slug else ""}" href="/project/{html.escape(p.slug)}">{html.escape(p.slug)} <span class="badge">{html.escape(p.stack)}</span></a>'
        for p in projects
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)} — agents-memory viewer</title>
  <style>{CSS_THEME}</style>
</head>
<body>
  <div class="sidebar">
    <div class="sidebar-header">
      <span>🧠 agents-memory</span>
    </div>
    <div class="search-box">
      <input type="text" id="searchInput" placeholder="Search memory (FTS)..." onkeyup="handleSearch(event)">
    </div>
    <div class="nav-list" id="navList">
      <div class="nav-section">Overview</div>
      <a class="nav-item {"active" if active_doc == "projects_map" else ""}" href="/">📍 Projects Map</a>
      <a class="nav-item {"active" if active_doc == "chronicle" else ""}" href="/chronicle">📜 Chronicle Timeline</a>
      <a class="nav-item {"active" if active_doc == "staging" else ""}" href="/staging">📥 Staging Inbox</a>

      <div class="nav-section">Architecture & Contracts</div>
      <a class="nav-item {"active" if active_doc == "hygiene" else ""}" href="/hygiene">🛡️ Hygiene Law</a>
      <a class="nav-item {"active" if active_doc == "flow_protocol" else ""}" href="/flow-protocol">⚡ Flow Capabilities</a>
      <a class="nav-item {"active" if active_doc == "webview" else ""}" href="/webview">🪟 WebView 3-Layer</a>

      <div class="nav-section">Projects</div>
      {proj_links}
    </div>
  </div>

  <div class="content">
    <div class="content-header">
      <span>{html.escape(title)}</span>
      <button onclick="rebuildIndex()" style="background:var(--surface-hover);border:1px solid var(--border);color:var(--text);padding:6px 12px;border-radius:6px;cursor:pointer;">🔄 Rebuild Index</button>
    </div>
    <div class="content-body" id="contentBody">
      {body_html}
    </div>
  </div>

  <script>
    async function rebuildIndex() {{
      const btn = event.target;
      btn.innerText = "Rebuilding...";
      try {{
        const res = await fetch("/api/rebuild");
        const data = await res.json();
        alert(`Index rebuilt! Indexed ${{data.indexed}} docs in ${{data.duration_ms}}ms.`);
      }} catch(e) {{
        alert("Error rebuilding index: " + e);
      }} finally {{
        btn.innerText = "🔄 Rebuild Index";
      }}
    }}

    async function handleSearch(e) {{
      if (e.key === "Enter") {{
        const q = e.target.value.trim();
        if (!q) return;
        const res = await fetch("/api/search?q=" + encodeURIComponent(q));
        const hits = await res.json();
        let html = `<h1>Search results for "${{q}}"</h1>`;
        if (hits.length === 0) {{
          html += "<p>No matching documents found.</p>";
        }} else {{
          html += "<ul>";
          for (const h of hits) {{
            html += `<li><a href="/doc/${{h.id}}"><strong>${{h.title}}</strong> (${{h.id}})</a><br><small style="color:var(--text-muted);">${{h.snippet}}</small></li>`;
          }}
          html += "</ul>";
        }}
        document.getElementById("contentBody").innerHTML = html;
      }}
    }}
  </script>
</body>
</html>
"""


def _get_hygiene_md() -> str:
    pkg_dir = Path(__file__).resolve().parent
    repo_hygiene = pkg_dir.parent.parent / "abi" / "HYGIENE.md"
    if repo_hygiene.exists():
        return _read(repo_hygiene)
    bundled = pkg_dir / "bundled" / "HYGIENE.md"
    if bundled.exists():
        return _read(bundled)
    return "# Hygiene Contract\n\nRefer to `abi/HYGIENE.md`."


def _get_flow_protocol_md() -> str:
    return """# Flow Capabilities Architecture

A **flow** is a self-describing capability continuation without raw filesystem paths.

## Side-by-Side Scope Descriptors

| Scope | Role | Capabilities | Primary Outcomes |
|---|---|---|---|
| `memory.v1` | Local agent memory | `memory.resolve`, `memory.relate`, `memory.promote`, `quarantine.propose` | `found`, `ambiguous`, `promoted`, `accepted` |
| `plex.v1` | Record shell / desktop | `records.resolve`, `records.open`, `landmarks.list`, `quarantine.propose` | `found`, `opened`, `accepted` |
| `media.v1` | Capability media slice | `media.resolve`, `media.relate`, `media.authorize`, `media.play` | `found`, `granted`, `playing` |

## Branch Continuation Syntax

```koru
# Resolve show -> next episode -> authorize -> play
media.resolve(ref: query("The Expanse S03E01"))
| found show |>
    media.relate(subject: show, relation: "next")
    | found episode |>
        media.authorize(media: episode)
        | granted grant |>
            media.play(grant: grant)
            | playing session |> result { session: session }
            | failed reason |> result { error: reason }
```
"""


def _get_webview_md() -> str:
    return """# WebView Record Shell: Three-Layer Architecture

Personal page database with a system WebView as renderer. Not a browser with a bigger tab strip.

```
Profile (one)     → cookies, logins, permissions, site storage partitions (~/.plex/webview-profile)
Record (many)     → url, title, tags, links, notes, status, optional snapshot (SQLite rows)
Instance (few)    → live WebView bound to a Record id (temporary render process)
```

| Layer | Lifetime | Cost | Owns |
|---|---|---|---|
| **Profile** | Long-lived, singular | Medium | Cookies, IDB, Cache, SW registrations, permissions |
| **Record** | Unbounded archive | Cheap | URL, tags, links, notes, snapshot refs |
| **Instance** | Ephemeral | Expensive | Actual WebView / renderer process |
"""


class MemoryViewerHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        url = urllib.parse.urlparse(self.path)
        path = url.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(url.query)

        if path == "/api/search":
            q = (query.get("q") or [""])[0]
            hits = search_hybrid(q)
            self._send_json(hits)
            return

        if path == "/api/rebuild":
            stats = rebuild_index()
            self._send_json(stats)
            return

        if path == "/":
            projects = parse_projects()
            md = "# Projects Map\n\n| slug | path | role | stack | status |\n|---|---|---|---|---|\n"
            for p in projects:
                md += f"| [{p.slug}](/project/{p.slug}) | `{p.path}` | {p.role} | `{p.stack}` | {p.status} |\n"
            content_html = _md_to_html(md)
            self._send_html(_generate_page_html("Projects Map", content_html, active_doc="projects_map"))
            return

        if path == "/chronicle":
            beats: List[str] = ["# Chronicle Beats\n"]
            if CHRONICLE_DIR.is_dir():
                for f in sorted(CHRONICLE_DIR.glob("*.md"), reverse=True):
                    beats.append(f"\n## {f.stem}\n" + _read(f))
            else:
                beats.append("\nNo chronicle events recorded yet.")
            content_html = _md_to_html("\n".join(beats))
            self._send_html(_generate_page_html("Chronicle Timeline", content_html, active_doc="chronicle"))
            return

        if path == "/staging":
            inbox = get_staging_inbox()
            md = f"# Staging Inbox\n\nTotal: {inbox['total']} bullets ({inbox['shown']} shown)\n\n"
            for g in inbox["groups"]:
                md += f"### {g.get('source') or g.get('file')}\n"
                for b in g["bullets"]:
                    md += f"- {b.get('title', '')} {b.get('text', '')}\n"
            content_html = _md_to_html(md)
            self._send_html(_generate_page_html("Staging Inbox", content_html, active_doc="staging"))
            return

        if path == "/hygiene":
            content_html = _md_to_html(_get_hygiene_md())
            self._send_html(_generate_page_html("Hygiene Law", content_html, active_doc="hygiene"))
            return

        if path == "/flow-protocol":
            content_html = _md_to_html(_get_flow_protocol_md())
            self._send_html(_generate_page_html("Flow Capabilities", content_html, active_doc="flow_protocol"))
            return

        if path == "/webview":
            content_html = _md_to_html(_get_webview_md())
            self._send_html(_generate_page_html("WebView 3-Layer Architecture", content_html, active_doc="webview"))
            return

        if path.startswith("/project/"):
            slug = path[len("/project/"):]
            for p in parse_projects():
                if p.slug == slug:
                    readme = p.detail_path
                    text = _read(readme) or f"# {p.slug}\n\nPath: `{p.path}`\nRole: {p.role}\nStack: {p.stack}"
                    content_html = _md_to_html(text)
                    self._send_html(_generate_page_html(f"Project: {slug}", content_html, active_doc=slug))
                    return
            self._send_error(404, f"Project {slug} not found")
            return

        if path.startswith("/doc/"):
            doc_id = path[len("/doc/"):]
            hits = search_hybrid(doc_id, limit=1)
            if hits:
                related = get_related(hits[0]["id"])
                md_text = f"# {hits[0]['title']}\n\n" + json.dumps(hits[0].get("frontmatter", {}), indent=2)
                content_html = _md_to_html(md_text)
                self._send_html(_generate_page_html(hits[0]["title"], content_html))
                return
            self._send_error(404, "Document not found")
            return

        self._send_error(404, "Page not found")

    def _send_html(self, content: str) -> None:
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj: Any) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, code: int, msg: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg.encode("utf-8"))


def serve_viewer(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Start localhost HTTP memory viewer."""
    server_address = (host, port)
    with socketserver.TCPServer(server_address, MemoryViewerHandler) as httpd:
        print(f"Serving agents-memory viewer on http://{host}:{port}/ ... (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down viewer server.")


def export_static_web(dest_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Export memory repository as static HTML website to ~/.agents/memory/export/."""
    target = dest_dir or EXPORT_DIR
    target.mkdir(parents=True, exist_ok=True)

    rebuild_index()
    projects = parse_projects()

    # 1. Index page
    index_md = "# Projects Map\n\n| slug | path | role | stack | status |\n|---|---|---|---|---|\n"
    for p in projects:
        index_md += f"| [{p.slug}](projects/{p.slug}.html) | `{p.path}` | {p.role} | `{p.stack}` | {p.status} |\n"
    (target / "index.html").write_text(
        _generate_page_html("Projects Map", _md_to_html(index_md), active_doc="projects_map"),
        encoding="utf-8",
    )

    # 2. Public docs pages
    (target / "hygiene.html").write_text(
        _generate_page_html("Hygiene Law", _md_to_html(_get_hygiene_md()), active_doc="hygiene"),
        encoding="utf-8",
    )
    (target / "flow-protocol.html").write_text(
        _generate_page_html("Flow Capabilities", _md_to_html(_get_flow_protocol_md()), active_doc="flow_protocol"),
        encoding="utf-8",
    )
    (target / "webview.html").write_text(
        _generate_page_html("WebView 3-Layer Architecture", _md_to_html(_get_webview_md()), active_doc="webview"),
        encoding="utf-8",
    )

    # 3. Projects pages
    proj_dir = target / "projects"
    proj_dir.mkdir(exist_ok=True)
    for p in projects:
        readme = p.detail_path
        text = _read(readme) or f"# {p.slug}\n\nPath: `{p.path}`\nRole: {p.role}\nStack: {p.stack}"
        (proj_dir / f"{p.slug}.html").write_text(
            _generate_page_html(f"Project: {p.slug}", _md_to_html(text), active_doc=p.slug),
            encoding="utf-8",
        )

    # 4. Chronicle page
    beats: List[str] = ["# Chronicle Beats\n"]
    if CHRONICLE_DIR.is_dir():
        for f in sorted(CHRONICLE_DIR.glob("*.md"), reverse=True):
            beats.append(f"\n## {f.stem}\n" + _read(f))
    (target / "chronicle.html").write_text(
        _generate_page_html("Chronicle Timeline", _md_to_html("\n".join(beats)), active_doc="chronicle"),
        encoding="utf-8",
    )

    return {"status": "ok", "export_dir": str(target), "files": len(list(target.rglob("*.html")))}
