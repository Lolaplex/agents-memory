"""Deterministic markdown merge engine for multi-device sync without data loss."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _normalize_bullet(line: str) -> str:
    """Strip bullet marker and whitespace for deduplication comparison."""
    stripped = line.strip()
    # Match - [ ] or - [x] or - or * or 1.
    stripped = re.sub(r"^[-*+]\s*(\[[ xX]\]\s*)?", "", stripped)
    stripped = re.sub(r"^\d+\.\s*", "", stripped)
    return stripped.strip().lower()


def merge_bullet_markdown(base_text: str, incoming_text: str) -> str:
    """Merge two markdown documents with headers and bullet lists without duplicates.
    
    Preserves heading structure, comments, and appends unique incoming bullets
    under their respective sections. Base order is preserved.
    """
    if not base_text.strip():
        return incoming_text
    if not incoming_text.strip():
        return base_text
    if base_text.strip() == incoming_text.strip():
        return base_text

    def parse_sections(text: str) -> list[tuple[str, list[str]]]:
        """Split text into (heading, lines) blocks."""
        sections: list[tuple[str, list[str]]] = []
        current_heading = ""
        current_lines: list[str] = []

        for line in text.splitlines():
            if line.startswith("#"):
                if current_lines or current_heading:
                    sections.append((current_heading, current_lines))
                current_heading = line.strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines or current_heading:
            sections.append((current_heading, current_lines))
        return sections

    base_sections = parse_sections(base_text)
    inc_sections = parse_sections(incoming_text)

    # Map incoming sections by heading
    inc_map: dict[str, list[str]] = {}
    for h, lines in inc_sections:
        inc_map[h] = lines

    merged_sections: list[tuple[str, list[str]]] = []
    seen_headings: set[str] = set()

    for h, base_lines in base_sections:
        seen_headings.add(h)
        if h not in inc_map:
            merged_sections.append((h, base_lines))
            continue

        inc_lines = inc_map[h]
        # Collect existing bullets in base
        base_bullet_norms = set()
        for line in base_lines:
            if re.match(r"^\s*[-*+\d]\s*", line):
                base_bullet_norms.add(_normalize_bullet(line))

        # Build combined lines
        combined = list(base_lines)
        added_bullets = []
        for line in inc_lines:
            if re.match(r"^\s*[-*+\d]\s*", line):
                norm = _normalize_bullet(line)
                if norm and norm not in base_bullet_norms:
                    added_bullets.append(line)
                    base_bullet_norms.add(norm)
            elif line.strip() and not any(line.strip() == bl.strip() for bl in base_lines):
                # Non-bullet unique line (e.g. paragraph or comment)
                added_bullets.append(line)

        if added_bullets:
            # Ensure nice spacing before appending
            if combined and combined[-1].strip() != "":
                combined.append("")
            combined.extend(added_bullets)

        merged_sections.append((h, combined))

    # Append any sections that only existed in incoming
    for h, inc_lines in inc_sections:
        if h not in seen_headings:
            merged_sections.append((h, inc_lines))

    # Reconstruct document
    out_lines: list[str] = []
    for i, (h, lines) in enumerate(merged_sections):
        if h:
            if out_lines and out_lines[-1].strip() != "":
                out_lines.append("")
            out_lines.append(h)
        for line in lines:
            out_lines.append(line)

    return "\n".join(out_lines).strip() + "\n"


def merge_table_markdown(base_text: str, incoming_text: str, pk_col_index: int = 0) -> str:
    """Merge two markdown tables (e.g. in PROJECTS.md) by primary key column (slug)."""
    merged, _ = merge_table_markdown_with_conflicts(base_text, incoming_text, pk_col_index)
    return merged


def merge_table_markdown_with_conflicts(
    base_text: str, incoming_text: str, pk_col_index: int = 0
) -> tuple[str, list[dict[str, str]]]:
    """Merge PROJECTS-style tables; incoming wins on row edits; log conflicts."""
    conflicts: list[dict[str, str]] = []
    if not base_text.strip():
        return incoming_text, conflicts
    if not incoming_text.strip():
        return base_text, conflicts

    def extract_rows(text: str) -> tuple[list[str], dict[str, str], list[str]]:
        header_lines: list[str] = []
        rows: dict[str, str] = {}
        footer_lines: list[str] = []
        in_table = False
        table_done = False

        for line in text.splitlines():
            sline = line.strip()
            if sline.startswith("|") and sline.endswith("|"):
                if not in_table:
                    in_table = True
                if re.match(r"^\|(?:\s*[-:]+\s*\|)+$", sline):
                    header_lines.append(line)
                    continue
                cells = [c.strip() for c in sline[1:-1].split("|")]
                if len(header_lines) == 0:
                    header_lines.append(line)
                else:
                    if len(cells) > pk_col_index:
                        pk = cells[pk_col_index].lower()
                        rows[pk] = line
            else:
                if in_table:
                    table_done = True
                if not in_table and not table_done:
                    header_lines.append(line)
                else:
                    footer_lines.append(line)

        return header_lines, rows, footer_lines

    base_headers, base_rows, base_footers = extract_rows(base_text)
    inc_headers, inc_rows, inc_footers = extract_rows(incoming_text)

    if not base_rows and not inc_rows:
        return merge_bullet_markdown(base_text, incoming_text), conflicts

    merged_rows = dict(base_rows)
    for pk, row_line in inc_rows.items():
        if pk not in merged_rows:
            merged_rows[pk] = row_line
        elif merged_rows[pk].strip() != row_line.strip():
            conflicts.append(
                {
                    "slug": pk,
                    "file": "PROJECTS.md",
                    "base": merged_rows[pk],
                    "incoming": row_line,
                }
            )
            merged_rows[pk] = row_line

    out_lines: list[str] = []
    headers = base_headers if base_headers else inc_headers
    out_lines.extend(headers)

    seen = set()
    for pk in base_rows.keys():
        if pk in merged_rows:
            out_lines.append(merged_rows[pk])
            seen.add(pk)
    for pk, row_line in merged_rows.items():
        if pk not in seen:
            out_lines.append(row_line)

    footers = base_footers if base_footers else inc_footers
    if footers:
        out_lines.extend(footers)

    return "\n".join(out_lines).strip() + "\n", conflicts


def merge_staging_markdown(base_text: str, incoming_text: str) -> str:
    """Merge staging inbox markdown documents without losing raw captured thoughts."""
    return merge_bullet_markdown(base_text, incoming_text)


def merge_json_content(base_str: str, incoming_str: str) -> str:
    """Deterministically merge two JSON strings (dicts/lists)."""
    try:
        base_obj = json.loads(base_str)
        inc_obj = json.loads(incoming_str)
        if isinstance(base_obj, dict) and isinstance(inc_obj, dict):
            merged_obj = dict(base_obj)
            for k, v in inc_obj.items():
                if k not in merged_obj:
                    merged_obj[k] = v
                elif isinstance(merged_obj[k], list) and isinstance(v, list):
                    for item in v:
                        if item not in merged_obj[k]:
                            merged_obj[k].append(item)
                elif isinstance(merged_obj[k], dict) and isinstance(v, dict):
                    merged_obj[k].update(v)
                else:
                    merged_obj[k] = v
            return json.dumps(merged_obj, indent=2)
    except Exception:
        pass
    return incoming_str


def merge_markdown_files(base_path: Path, incoming_content: str) -> tuple[str, bool]:
    """Merge incoming markdown or json string into existing file at base_path.
    
    Returns (merged_content, was_modified).
    """
    if not base_path.exists():
        return incoming_content, True

    base_content = base_path.read_text(encoding="utf-8", errors="replace")
    if base_content.strip() == incoming_content.strip():
        return base_content, False

    if base_path.suffix.lower() == ".json":
        merged = merge_json_content(base_content, incoming_content)
        return merged, (merged.strip() != base_content.strip())

    name_lower = base_path.name.lower()
    if name_lower == "projects.md":
        merged = merge_table_markdown(base_content, incoming_content)
    elif "staging" in str(base_path).lower() or name_lower == "captured.md":
        merged = merge_staging_markdown(base_content, incoming_content)
    else:
        merged = merge_bullet_markdown(base_content, incoming_content)

    return merged, (merged.strip() != base_content.strip())


def merge_file_trees(
    target_root: Path,
    incoming_files: dict[str, str],
) -> dict[str, Any]:
    """Deterministically merge an incoming dictionary of {relative_path: content} into target_root.
    
    Returns report of added, modified, unchanged files.
    """
    report = {
        "added": [],
        "merged": [],
        "unchanged": [],
        "total_incoming": len(incoming_files),
    }

    target_root.mkdir(parents=True, exist_ok=True)

    for rel_path, content in incoming_files.items():
        dest = target_root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        if not dest.exists():
            dest.write_text(content, encoding="utf-8")
            report["added"].append(rel_path)
        else:
            merged, modified = merge_markdown_files(dest, content)
            if modified:
                dest.write_text(merged, encoding="utf-8")
                report["merged"].append(rel_path)
            else:
                report["unchanged"].append(rel_path)

    return report
